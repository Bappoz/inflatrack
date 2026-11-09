import httpx
from fastapi.testclient import TestClient

from web.backend import app as auth_app


def test_register_creates_user_with_publishable_key_and_hides_tokens(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]):
            captured.update({"url": url, "headers": headers, "body": json})
            return httpx.Response(
                200,
                json={
                    "user": {"id": "user-123", "email": "ana@example.com"},
                    "session": None,
                    "access_token": "must-not-be-returned",
                },
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(auth_app.httpx, "AsyncClient", FakeAsyncClient)
    response = TestClient(auth_app.app).post(
        "/auth/register",
        json={
            "name": " Ana Silva ",
            "email": "ana@example.com",
            "password": "senha-segura-123",
            "confirm_password": "senha-segura-123",
        },
    )

    assert response.status_code == 201
    assert response.json() == {
        "user_id": "user-123",
        "email": "ana@example.com",
        "confirmation_required": True,
    }
    assert captured["url"] == "https://example.supabase.co/auth/v1/signup"
    assert captured["headers"] == {"apikey": "sb_publishable_test"}
    assert captured["body"]["data"] == {"full_name": "Ana Silva"}


def test_register_rejects_mismatched_passwords_without_echoing_them() -> None:
    password = "first-secret-password"
    confirmation = "second-secret-password"
    response = TestClient(auth_app.app).post(
        "/auth/register",
        json={
            "name": "Ana Silva",
            "email": "ana@example.com",
            "password": password,
            "confirm_password": confirmation,
        },
    )

    assert response.status_code == 422
    assert "As senhas não coincidem." in response.text
    assert password not in response.text
    assert confirmation not in response.text


def test_register_requires_supabase_configuration(monkeypatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY", raising=False)
    response = TestClient(auth_app.app).post(
        "/auth/register",
        json={
            "name": "Ana Silva",
            "email": "ana@example.com",
            "password": "senha-segura-123",
            "confirm_password": "senha-segura-123",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "O serviço de cadastro não está configurado."


def test_register_rejects_email_reported_as_already_registered(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")

    class DuplicateEmailClient:
        def __init__(self, timeout: float) -> None:
            pass

        async def __aenter__(self) -> "DuplicateEmailClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]):
            return httpx.Response(
                422,
                json={"code": "user_already_exists", "message": "User already registered"},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(auth_app.httpx, "AsyncClient", DuplicateEmailClient)
    response = TestClient(auth_app.app).post(
        "/auth/register",
        json={
            "name": "Ana Silva",
            "email": "ana@example.com",
            "password": "senha-segura-123",
            "confirm_password": "senha-segura-123",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Este e-mail já está cadastrado."


def test_register_rejects_supabase_obfuscated_duplicate(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")

    class ObfuscatedDuplicateClient:
        def __init__(self, timeout: float) -> None:
            pass

        async def __aenter__(self) -> "ObfuscatedDuplicateClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]):
            return httpx.Response(
                200,
                json={"user": {"id": "existing-user", "identities": []}, "session": None},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(auth_app.httpx, "AsyncClient", ObfuscatedDuplicateClient)
    response = TestClient(auth_app.app).post(
        "/auth/register",
        json={
            "name": "Ana Silva",
            "email": "ana@example.com",
            "password": "senha-segura-123",
            "confirm_password": "senha-segura-123",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Este e-mail já está cadastrado."