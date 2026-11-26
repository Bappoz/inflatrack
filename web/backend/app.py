import os
from pathlib import Path
from typing import Literal, Self
from uuid import UUID

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

if __package__:
    from . import publicacao
    from .chat import FeliciaIndisponivel, chat_configurado, responder
    from .database import DatabaseConfigurationError, check_user_store, get_engine, save_user
else:
    import publicacao
    from chat import FeliciaIndisponivel, chat_configurado, responder
    from database import DatabaseConfigurationError, check_user_store, get_engine, save_user

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

BrazilianState = Literal[
    "AC",
    "AL",
    "AP",
    "AM",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MT",
    "MS",
    "MG",
    "PA",
    "PB",
    "PR",
    "PE",
    "PI",
    "RJ",
    "RN",
    "RS",
    "RO",
    "RR",
    "SC",
    "SP",
    "SE",
    "TO",
]


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    email: EmailStr
    state: BrazilianState
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
    public = {"id": str(user.get("id", "")), "email": email, "nome": name.strip()}
    state = metadata.get("state") if isinstance(metadata, dict) else None
    if isinstance(state, str) and state.strip():
        public["state"] = state.strip().upper()
    return public


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


def _consultar_supabase(sql: str, params: dict[str, object]) -> list[dict[str, object]]:
    """Lê o que o pipeline publicou no Supabase (mesma conexão do cadastro, DATABASE_URL)."""
    with get_engine().connect() as connection:
        return [dict(row) for row in connection.execute(text(sql), params).mappings()]


@app.get("/dashboard")
async def dashboard(
    request: Request,
    response: Response,
    localidade: int = Query(1, ge=1),
    periodo: int = Query(60, ge=0, le=600),
) -> dict[str, object]:
    await _authenticated_user(request, response)

    def ler() -> dict[str, object] | None:
        dados = publicacao.dashboard(_consultar_supabase, localidade, periodo)
        if dados is not None:
            salario = publicacao.grafico(_consultar_supabase, "p3_salario_minimo_real")
            dados["minimum_wage"] = salario or []
        return dados

    dados = await _ler_publicacao(ler)
    if dados is None:
        raise HTTPException(status_code=404, detail="Praça sem dados publicados.")
    return dados


async def _ler_publicacao(funcao, *args):
    """Roda uma leitura do Supabase fora do loop; banco fora do ar vira 503."""
    try:
        return await run_in_threadpool(funcao, *args)
    except (DatabaseConfigurationError, SQLAlchemyError) as error:
        raise HTTPException(
            status_code=503,
            detail=(
                "Dados indisponíveis. Confira a DATABASE_URL e se o dashboard_job "
                "já fez a publicação no Supabase."
            ),
        ) from error


class ReajusteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codigo_subitem: str = Field(min_length=1, max_length=20)
    uf: str = Field(pattern=r"^[A-Za-z]{2}$")
    preco_atual: float = Field(gt=0, le=1_000_000)


@app.get("/produtos")
async def produtos(request: Request, response: Response) -> dict[str, object]:
    """A lista inteira de produtos com previsão: o site guarda por 24 h e filtra localmente."""
    await _authenticated_user(request, response)
    return {"produtos": await _ler_publicacao(publicacao.listar_produtos, _consultar_supabase)}


@app.post("/reajuste")
async def reajuste(
    payload: ReajusteRequest, request: Request, response: Response
) -> dict[str, object]:
    """Mesma conta da Felicia. O preço digitado não é gravado nem registrado em log (ADR 0004)."""
    await _authenticated_user(request, response)
    try:
        return await _ler_publicacao(
            publicacao.prever_reajuste,
            _consultar_supabase,
            payload.codigo_subitem,
            payload.uf,
            payload.preco_atual,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/previsoes/destaques")
async def previsoes_destaques(
    request: Request, response: Response, localidade: int = Query(1, ge=1)
) -> dict[str, object]:
    await _authenticated_user(request, response)
    return {
        "destaques": await _ler_publicacao(publicacao.destaques, _consultar_supabase, localidade)
    }


class MensagemHistorico(BaseModel):
    """Uma mensagem anterior da conversa, guardada no navegador."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    # As 10 últimas mensagens antes da pergunta nova; o servidor não guarda a conversa.
    history: list[MensagemHistorico] = Field(default_factory=list, max_length=10)


class ChatResponse(BaseModel):
    reply: str


def consultar_inflacao() -> dict:
    """IPCA/INPC em 12 meses, inflação por setor e por praça, do último mês divulgado (Brasil)."""
    dados = publicacao.dashboard(_consultar_supabase, publicacao.BRASIL, 1) or {}
    return {chave: dados.get(chave) for chave in ("latest_month", "kpis", "sectors", "locations")}


def buscar_produto(nome: str) -> dict:
    """Procura produtos (subitens do IPCA) pelo nome, como "arroz" ou "gasolina".

    Devolve até 10 opções com o `codigo_subitem`, que `prever_reajuste` precisa.
    """
    return {"produtos": publicacao.buscar_produto(_consultar_supabase, nome)}


def prever_reajuste(codigo_subitem: str, uf: str, preco_atual: float) -> dict:
    """Sugere o preço do produto para o próximo mês, pela inflação prevista na praça da UF.

    Args:
        codigo_subitem: código do produto, vindo de `buscar_produto`.
        uf: sigla do estado do lojista, como "SP".
        preco_atual: preço que o lojista cobra hoje, em reais.
    """
    try:
        return publicacao.prever_reajuste(_consultar_supabase, codigo_subitem, uf, preco_atual)
    except ValueError as error:
        return {"erro": str(error)}


FERRAMENTAS_FELICIA = {
    funcao.__name__: funcao for funcao in (consultar_inflacao, buscar_produto, prever_reajuste)
}


@app.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request, response: Response) -> ChatResponse:
    await _authenticated_user(request, response)
    if not chat_configurado():
        raise HTTPException(status_code=503, detail="A Felicia não está configurada.")
    historico = [item.model_dump() for item in payload.history]
    try:
        reply = await responder(payload.message, historico, FERRAMENTAS_FELICIA)
    except FeliciaIndisponivel as error:
        raise HTTPException(
            status_code=502,
            detail="A Felicia não conseguiu responder agora. Tente de novo em instantes.",
        ) from error
    return ChatResponse(reply=reply or "Não consegui formular uma resposta.")


@app.post("/auth/register", response_model=RegistrationResponse, status_code=201)
async def register_user(payload: RegistrationRequest) -> RegistrationResponse:
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    if not supabase_url or not publishable_key:
        raise HTTPException(status_code=503, detail="O serviço de cadastro não está configurado.")

    try:
        await run_in_threadpool(check_user_store)
    except (DatabaseConfigurationError, SQLAlchemyError) as error:
        raise HTTPException(
            status_code=503,
            detail=(
                "O banco de usuários está indisponível. Confira DATABASE_URL "
                "e aplique o esquema do backend."
            ),
        ) from error

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{supabase_url}/auth/v1/signup",
                headers={"apikey": publishable_key},
                json={
                    "email": str(payload.email),
                    "password": payload.password.get_secret_value(),
                    "data": {"full_name": payload.name, "state": payload.state},
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

    try:
        parsed_user_id = UUID(user_id) if isinstance(user_id, str) else None
    except ValueError as error:
        raise HTTPException(
            status_code=502, detail="O serviço de autenticação retornou usuário inválido."
        ) from error
    if parsed_user_id is None:
        raise HTTPException(
            status_code=502, detail="O serviço de autenticação retornou usuário inválido."
        )

    try:
        await run_in_threadpool(
            save_user,
            user_id=parsed_user_id,
            email=str(payload.email),
            name=payload.name,
            state=payload.state,
        )
    except (DatabaseConfigurationError, SQLAlchemyError) as error:
        raise HTTPException(
            status_code=503,
            detail=(
                "A conta foi criada no Supabase Auth, mas não foi possível confirmar "
                "os dados na tabela de usuários. Contate o suporte antes de tentar novamente."
            ),
        ) from error

    return RegistrationResponse(
        user_id=str(parsed_user_id),
        email=payload.email,
        confirmation_required=not bool(result.get("session")),
    )
