import os
from pathlib import Path
from typing import Self

import httpx
import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, EmailStr, SecretStr, field_validator, model_validator
from starlette.concurrency import run_in_threadpool

from inflatrack.common.db import dsn_do_ambiente

load_dotenv(Path(__file__).with_name(".env"))

app = FastAPI(title="Inflatrack Auth API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:3000,http://localhost:3001",
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    email: EmailStr
    password: SecretStr
    confirm_password: SecretStr

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Informe seu nome.")
        if len(normalized) > 120:
            raise ValueError("O nome deve ter no máximo 120 caracteres.")
        return normalized

    @field_validator("password", "confirm_password")
    @classmethod
    def validate_password_length(cls, value: SecretStr) -> SecretStr:
        password = value.get_secret_value()
        if len(password) < 8:
            raise ValueError("A senha deve ter pelo menos 8 caracteres.")
        return value

    @model_validator(mode="after")
    def validate_password_confirmation(self) -> Self:
        if self.password.get_secret_value() != self.confirm_password.get_secret_value():
            raise ValueError("As senhas não coincidem.")
        return self


class RegistrationResponse(BaseModel):
    user_id: str | None
    email: EmailStr
    confirmation_required: bool


class LoginRequest(BaseModel):
    email: EmailStr
    password: SecretStr


def _is_duplicate_email_error(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False

    details = " ".join(
        str(payload.get(key, ""))
        for key in ("code", "error_code", "error", "message", "msg", "details")
    ).lower()
    duplicate_markers = (
        "user_already_exists",
        "email_exists",
        "already registered",
        "already exists",
        "duplicate key",
    )
    return any(marker in details for marker in duplicate_markers)


def _is_unconfirmed_email_error(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False

    details = " ".join(
        str(payload.get(key, ""))
        for key in ("code", "error_code", "error", "message", "msg", "error_description")
    ).lower()
    markers = ("email_not_confirmed", "email not confirmed", "email is not confirmed")
    return any(marker in details for marker in markers)


@app.exception_handler(RequestValidationError)
async def hide_validation_input(
    request: Request,
    exception: RequestValidationError,
) -> JSONResponse:
    errors = [
        {key: error[key] for key in ("loc", "msg", "type") if key in error}
        for error in exception.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


def _supabase_config() -> tuple[str, str]:
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    if not supabase_url or not publishable_key:
        raise HTTPException(
            status_code=503,
            detail="O serviço de autenticação não está configurado.",
        )
    return supabase_url, publishable_key


def _cookie_secure() -> bool:
    return os.getenv("COOKIE_SECURE", "false").lower() == "true"


def _set_session_cookies(response: Response, session: dict[str, object]) -> None:
    access_token = session.get("access_token")
    refresh_token = session.get("refresh_token")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str):
        raise HTTPException(
            status_code=401,
            detail="Confirme seu e-mail antes de entrar na conta.",
        )

    expires_in = session.get("expires_in")
    max_age = expires_in if isinstance(expires_in, int) else 3600
    cookie_options = {
        "httponly": True,
        "secure": _cookie_secure(),
        "samesite": "lax",
        "path": "/",
    }
    response.set_cookie(
        "inflatrack_access_token",
        access_token,
        max_age=max_age,
        **cookie_options,
    )
    response.set_cookie(
        "inflatrack_refresh_token",
        refresh_token,
        max_age=60 * 60 * 24 * 30,
        **cookie_options,
    )


def _public_user(user: dict[str, object]) -> dict[str, str]:
    email = user.get("email")
    metadata = user.get("user_metadata")
    name = metadata.get("full_name") if isinstance(metadata, dict) else None
    if not isinstance(email, str):
        raise HTTPException(
            status_code=502,
            detail="O serviço de autenticação retornou usuário inválido.",
        )
    if not isinstance(name, str) or not name.strip():
        name = email.split("@", maxsplit=1)[0]
    return {"id": str(user.get("id", "")), "email": email, "nome": name.strip()}


async def _authenticated_user(request: Request, response: Response) -> dict[str, str]:
    access_token = request.cookies.get("inflatrack_access_token")
    refresh_token = request.cookies.get("inflatrack_refresh_token")
    if not access_token and not refresh_token:
        raise HTTPException(status_code=401, detail="Entre na sua conta para continuar.")

    supabase_url, publishable_key = _supabase_config()
    headers = {"apikey": publishable_key}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            user_response = (
                await client.get(f"{supabase_url}/auth/v1/user", headers=headers)
                if access_token
                else None
            )

            if user_response is None or user_response.status_code == 401:
                if not refresh_token:
                    raise HTTPException(
                        status_code=401,
                        detail="Sua sessão expirou. Entre novamente.",
                    )
                refreshed = await client.post(
                    f"{supabase_url}/auth/v1/token?grant_type=refresh_token",
                    headers={"apikey": publishable_key},
                    json={"refresh_token": refresh_token},
                )
                if refreshed.is_error:
                    raise HTTPException(
                        status_code=401,
                        detail="Sua sessão expirou. Entre novamente.",
                    )
                session = refreshed.json()
                if not isinstance(session, dict):
                    raise HTTPException(
                        status_code=401,
                        detail="Sua sessão expirou. Entre novamente.",
                    )
                _set_session_cookies(response, session)
                user = session.get("user")
            elif user_response.is_error:
                raise HTTPException(
                    status_code=502,
                    detail="Não foi possível validar sua sessão no Supabase.",
                )
            else:
                user = user_response.json()
    except httpx.TimeoutException as error:
        raise HTTPException(
            status_code=504,
            detail="O serviço de autenticação demorou para responder.",
        ) from error
    except httpx.HTTPError as error:
        raise HTTPException(
            status_code=502,
            detail="Não foi possível conectar ao Supabase Auth.",
        ) from error

    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="Sua sessão expirou. Entre novamente.")
    return _public_user(user)


@app.post("/auth/login")
async def login_user(payload: LoginRequest, response: Response) -> dict[str, str]:
    supabase_url, publishable_key = _supabase_config()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            supabase_response = await client.post(
                f"{supabase_url}/auth/v1/token?grant_type=password",
                headers={"apikey": publishable_key},
                json={
                    "email": str(payload.email),
                    "password": payload.password.get_secret_value(),
                },
            )
    except httpx.TimeoutException as error:
        raise HTTPException(
            status_code=504,
            detail="O serviço de autenticação demorou para responder.",
        ) from error
    except httpx.HTTPError as error:
        raise HTTPException(
            status_code=502,
            detail="Não foi possível conectar ao Supabase Auth.",
        ) from error

    if supabase_response.status_code == 429:
        raise HTTPException(
            status_code=429,
            detail="Muitas tentativas de login. Aguarde e tente novamente.",
        )
    if supabase_response.is_error:
        try:
            error_payload = supabase_response.json()
        except ValueError:
            error_payload = None
        if _is_unconfirmed_email_error(error_payload):
            raise HTTPException(
                status_code=403,
                detail="Seu e-mail ainda não foi confirmado. Confirme-o antes de entrar.",
            )
        if supabase_response.status_code < 500:
            raise HTTPException(
                status_code=401,
                detail="E-mail ou senha incorretos. Confira os dados e tente novamente.",
            )
        raise HTTPException(status_code=502, detail="O serviço de autenticação está indisponível.")

    try:
        session = supabase_response.json()
    except ValueError as error:
        raise HTTPException(
            status_code=502,
            detail="Resposta inválida do Supabase Auth.",
        ) from error
    if not isinstance(session, dict) or not isinstance(session.get("user"), dict):
        raise HTTPException(status_code=502, detail="Resposta inválida do Supabase Auth.")

    _set_session_cookies(response, session)
    return _public_user(session["user"])


@app.get("/auth/me")
async def current_user(request: Request, response: Response) -> dict[str, str]:
    return await _authenticated_user(request, response)


@app.post("/auth/logout")
async def logout_user(request: Request, response: Response) -> dict[str, bool]:
    access_token = request.cookies.get("inflatrack_access_token")
    if access_token:
        supabase_url, publishable_key = _supabase_config()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"{supabase_url}/auth/v1/logout",
                    headers={
                        "apikey": publishable_key,
                        "Authorization": f"Bearer {access_token}",
                    },
                )
        except httpx.HTTPError:
            pass

    response.delete_cookie(
        "inflatrack_access_token",
        path="/",
        secure=_cookie_secure(),
        samesite="lax",
    )
    response.delete_cookie(
        "inflatrack_refresh_token",
        path="/",
        secure=_cookie_secure(),
        samesite="lax",
    )
    return {"ok": True}


def load_dashboard_data(connection: psycopg.Connection) -> dict[str, object]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")

        cursor.execute(
            """
            with ultimo_mes as (
                select max(mes_referencia) as mes
                from serie.fct_inflacao_mensal
                where indice = 'IPCA' and codigo_localidade = 1 and nivel_categoria = 'geral'
            )
            select u.mes,
                max(f.variacao_acum_12m_pct) filter (where f.indice = 'IPCA') as ipca_12m_pct,
                max(f.variacao_acum_12m_pct) filter (where f.indice = 'INPC') as inpc_12m_pct
            from ultimo_mes u
            left join serie.fct_inflacao_mensal f
                on f.mes_referencia = u.mes
                and f.codigo_localidade = 1
                and f.nivel_categoria = 'geral'
            group by u.mes
            """
        )
        summary = cursor.fetchone() or {}

        cursor.execute(
            """
            with ultimo_mes as (
                select max(mes_referencia) as mes
                from serie.fct_inflacao_mensal
                where indice = 'IPCA' and codigo_localidade = 1 and nivel_categoria = 'geral'
            )
            select c.nome_categoria as setor,
                round(f.variacao_acum_12m_pct, 2) as inflacao_12m_pct,
                to_char(f.mes_referencia, 'MM/YYYY') as ate_o_mes
            from serie.fct_inflacao_mensal f
            join ultimo_mes u on f.mes_referencia = u.mes
            join serie.dim_cesta_ipca_scd2 c on c.id_versao_cesta = f.id_versao_cesta
            where f.indice = 'IPCA'
                and f.codigo_localidade = 1
                and f.nivel_categoria in ('geral', 'grupo')
            order by f.nivel_categoria = 'geral' desc, f.variacao_acum_12m_pct desc
            """
        )
        sectors = cursor.fetchall()

        cursor.execute(
            """
            with ultimo_mes as (
                select max(mes_referencia) as mes
                from serie.fct_inflacao_mensal
                where indice = 'IPCA' and codigo_localidade = 1 and nivel_categoria = 'geral'
            )
            select l.nome_localidade as localidade,
                max(f.variacao_acum_12m_pct) filter (where f.indice = 'IPCA') as ipca_12m_pct,
                max(f.variacao_acum_12m_pct) filter (where f.indice = 'INPC') as inpc_12m_pct
            from serie.fct_inflacao_mensal f
            join ultimo_mes u on f.mes_referencia = u.mes
            join serie.dim_localidade l on l.codigo_localidade = f.codigo_localidade
            where f.nivel_categoria = 'geral'
            group by l.codigo_localidade, l.nome_localidade
            order by l.codigo_localidade = 1 desc, ipca_12m_pct desc nulls last
            """
        )
        locations = cursor.fetchall()

        cursor.execute(
            """
            with ultimo_mes as (
                select max(mes_referencia) as mes
                from serie.fct_inflacao_mensal
                where indice = 'IPCA' and codigo_localidade = 1 and nivel_categoria = 'geral'
            )
            select f.mes_referencia,
                max(f.variacao_acum_12m_pct) filter (where f.indice = 'IPCA') as ipca_12m_pct,
                max(f.variacao_acum_12m_pct) filter (where f.indice = 'INPC') as inpc_12m_pct
            from serie.fct_inflacao_mensal f
            cross join ultimo_mes u
            where f.codigo_localidade = 1
                and f.nivel_categoria = 'geral'
                and f.mes_referencia > u.mes - interval '60 months'
            group by f.mes_referencia
            order by f.mes_referencia
            """
        )
        history = cursor.fetchall()

        cursor.execute(
            """
            select extract(month from f.mes_referencia)::int as mes_numero,
                (array['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out',
                    'nov', 'dez'])[extract(month from f.mes_referencia)::int] as mes,
                round(avg(f.variacao_mensal_pct) filter (where f.nivel_categoria = 'geral'), 2)
                    as indice_geral_pct,
                round(avg(f.variacao_mensal_pct) filter (where f.codigo_categoria = '1'), 2)
                    as alimentacao_pct,
                round(avg(f.variacao_mensal_pct) filter (where f.codigo_categoria = '2'), 2)
                    as habitacao_pct,
                round(avg(f.variacao_mensal_pct) filter (where f.codigo_categoria = '4'), 2)
                    as vestuario_pct,
                round(avg(f.variacao_mensal_pct) filter (where f.codigo_categoria = '5'), 2)
                    as transportes_pct
            from serie.fct_inflacao_mensal f
            where f.indice = 'IPCA'
                and f.codigo_localidade = 1
                and f.nivel_categoria in ('geral', 'grupo')
                and f.mes_referencia >= date '2006-07-01'
            group by mes_numero
            order by mes_numero
            """
        )
        seasonality = cursor.fetchall()

        cursor.execute(
            """
            with base as (
                select numero_indice
                from serie.fct_inflacao_mensal
                where indice = 'IPCA'
                    and codigo_localidade = 1
                    and nivel_categoria = 'geral'
                    and mes_referencia = date '2006-01-01'
            )
            select f.mes_referencia,
                round(100 * b.numero_indice / f.numero_indice, 2) as poder_compra_100_reais
            from serie.fct_inflacao_mensal f
            cross join base b
            where f.indice = 'IPCA'
                and f.codigo_localidade = 1
                and f.nivel_categoria = 'geral'
                and f.numero_indice is not null
                and f.mes_referencia >= date '2006-01-01'
            order by f.mes_referencia
            """
        )
        purchasing_power = cursor.fetchall()

    return {
        "latest_month": summary.get("mes"),
        "kpis": {
            "ipca_12m_pct": summary.get("ipca_12m_pct"),
            "inpc_12m_pct": summary.get("inpc_12m_pct"),
        },
        "sectors": sectors,
        "locations": locations,
        "history": history,
        "seasonality": seasonality,
        "purchasing_power": purchasing_power,
    }


def _read_dashboard_from_postgres() -> dict[str, object]:
    with psycopg.connect(dsn_do_ambiente(), connect_timeout=3) as connection:
        return load_dashboard_data(connection)


@app.get("/dashboard")
async def dashboard(request: Request, response: Response) -> dict[str, object]:
    await _authenticated_user(request, response)
    try:
        return await run_in_threadpool(_read_dashboard_from_postgres)
    except psycopg.Error as error:
        raise HTTPException(
            status_code=503,
            detail=(
                "Dados do dashboard indisponíveis. Inicie o PostgreSQL e execute o pipeline "
                "Dagster para preencher o schema serie."
            ),
        ) from error


@app.post("/auth/register", response_model=RegistrationResponse, status_code=201)
async def register_user(payload: RegistrationRequest) -> RegistrationResponse:
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    if not supabase_url or not publishable_key:
        raise HTTPException(status_code=503, detail="O serviço de cadastro não está configurado.")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{supabase_url}/auth/v1/signup",
                headers={"apikey": publishable_key},
                json={
                    "email": str(payload.email),
                    "password": payload.password.get_secret_value(),
                    "data": {"full_name": payload.name},
                },
            )
    except httpx.TimeoutException as error:
        raise HTTPException(
            status_code=504,
            detail="O serviço de autenticação demorou para responder.",
        ) from error
    except httpx.HTTPError as error:
        raise HTTPException(
            status_code=502,
            detail="Não foi possível conectar ao serviço de autenticação.",
        ) from error

    if response.status_code == 429:
        raise HTTPException(
            status_code=429,
            detail="Muitas tentativas de cadastro. Aguarde e tente novamente.",
        )
    if response.is_error:
        try:
            error_payload = response.json()
        except ValueError:
            error_payload = None
        if _is_duplicate_email_error(error_payload):
            raise HTTPException(status_code=409, detail="Este e-mail já está cadastrado.")
        if response.status_code < 500:
            raise HTTPException(
                status_code=400,
                detail="Não foi possível criar a conta. Verifique os dados e tente novamente.",
            )
        raise HTTPException(
            status_code=502,
            detail="O serviço de autenticação está indisponível.",
        )

    try:
        result = response.json()
    except ValueError as error:
        raise HTTPException(
            status_code=502,
            detail="Resposta inválida do serviço de autenticação.",
        ) from error

    if not isinstance(result, dict):
        raise HTTPException(
            status_code=502,
            detail="Resposta inválida do serviço de autenticação.",
        )

    user = result.get("user")
    user_id = user.get("id") if isinstance(user, dict) else None
    identities = user.get("identities") if isinstance(user, dict) else None
    if isinstance(identities, list) and not identities:
        raise HTTPException(status_code=409, detail="Este e-mail já está cadastrado.")

    return RegistrationResponse(
        user_id=user_id if isinstance(user_id, str) else None,
        email=payload.email,
        confirmation_required=not bool(result.get("session")),
    )