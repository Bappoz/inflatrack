import os
from pathlib import Path
from typing import Self

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, SecretStr, field_validator, model_validator

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
    allow_credentials=False,
    allow_methods=["POST"],
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
        if not 8 <= len(password) <= 128:
            raise ValueError("A senha deve ter entre 8 e 128 caracteres.")
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