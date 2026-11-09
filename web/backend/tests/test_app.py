import httpx
import psycopg
from fastapi.testclient import TestClient

from web.backend import app as auth_app


def mock_authenticated_user(monkeypatch) -> None:
    class AuthenticatedUserClient:
        def __init__(self, timeout: float) -> None:
            pass

        async def __aenter__(self) -> "AuthenticatedUserClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, *, headers: dict[str, str]):
            return httpx.Response(
                200,
                json={
                    "id": "user-123",
                    "email": "ana@example.com",
                    "user_metadata": {"full_name": "Ana Silva"},
                },
                request=httpx.Request("GET", url),
            )

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    monkeypatch.setattr(auth_app.httpx, "AsyncClient", AuthenticatedUserClient)


def test_register_creates_user_with_publishable_key_and_hides_tokens(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    captured: dict[str, object] = {}
    long_password = "x" * 256

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
            "password": long_password,
            "confirm_password": long_password,
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
    assert captured["body"]["password"] == long_password


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


def test_login_sets_http_only_cookies_and_does_not_return_tokens(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    monkeypatch.setenv("COOKIE_SECURE", "false")

    class LoginClient:
        def __init__(self, timeout: float) -> None:
            pass

        async def __aenter__(self) -> "LoginClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]):
            assert url.endswith("/auth/v1/token?grant_type=password")
            return httpx.Response(
                200,
                json={
                    "access_token": "private-access-token",
                    "refresh_token": "private-refresh-token",
                    "expires_in": 3600,
                    "user": {
                        "id": "user-123",
                        "email": "ana@example.com",
                        "user_metadata": {"full_name": "Ana Silva"},
                    },
                },
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(auth_app.httpx, "AsyncClient", LoginClient)
    response = TestClient(auth_app.app).post(
        "/auth/login",
        json={"email": "ana@example.com", "password": "senha-segura-123"},
    )

    assert response.status_code == 200
    assert response.json() == {"id": "user-123", "email": "ana@example.com", "nome": "Ana Silva"}
    assert "private-access-token" not in response.text
    assert "private-refresh-token" not in response.text
    set_cookies = response.headers.get_list("set-cookie")
    assert any(
        "inflatrack_access_token" in cookie and "httponly" in cookie.lower()
        for cookie in set_cookies
    )
    assert any(
        "inflatrack_refresh_token" in cookie and "httponly" in cookie.lower()
        for cookie in set_cookies
    )


def test_auth_me_returns_name_from_supabase_metadata(monkeypatch) -> None:
    mock_authenticated_user(monkeypatch)
    client = TestClient(auth_app.app)
    client.cookies.set("inflatrack_access_token", "test-access-token")

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json() == {"id": "user-123", "email": "ana@example.com", "nome": "Ana Silva"}


def test_login_reports_unconfirmed_email_from_supabase(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")

    class UnconfirmedEmailClient:
        def __init__(self, timeout: float) -> None:
            pass

        async def __aenter__(self) -> "UnconfirmedEmailClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]):
            return httpx.Response(
                400,
                json={"code": "email_not_confirmed", "message": "Email not confirmed"},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(auth_app.httpx, "AsyncClient", UnconfirmedEmailClient)
    response = TestClient(auth_app.app).post(
        "/auth/login",
        json={"email": "ana@example.com", "password": "senha-segura-123"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Seu e-mail ainda não foi confirmado. Confirme-o antes de entrar."
    )


def test_login_keeps_invalid_credentials_message_generic(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")

    class InvalidCredentialsClient:
        def __init__(self, timeout: float) -> None:
            pass

        async def __aenter__(self) -> "InvalidCredentialsClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]):
            return httpx.Response(
                400,
                json={"code": "invalid_credentials", "message": "Invalid login credentials"},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(auth_app.httpx, "AsyncClient", InvalidCredentialsClient)
    response = TestClient(auth_app.app).post(
        "/auth/login",
        json={"email": "ana@example.com", "password": "senha-segura-123"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == (
        "E-mail ou senha incorretos. Confira os dados e tente novamente."
    )


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


def test_dashboard_reads_serie_tables_in_read_only_transaction(monkeypatch) -> None:
    mock_authenticated_user(monkeypatch)

    class FakeCursor:
        def __init__(self) -> None:
            self.query_index = -1
            self.queries: list[str] = []
            self.rows = [
                [{"mes": "2026-09-01", "ipca_12m_pct": 4.5, "inpc_12m_pct": 4.2}],
                [{"setor": "Índice geral", "inflacao_12m_pct": 4.5}],
                [{"localidade": "Brasil", "ipca_12m_pct": 4.5, "inpc_12m_pct": 4.2}],
                [{"mes_referencia": "2026-09-01", "ipca_12m_pct": 4.5, "inpc_12m_pct": 4.2}],
                [{"mes_numero": 1, "mes": "jan", "indice_geral_pct": 0.4}],
                [{"mes_referencia": "2026-09-01", "poder_compra_100_reais": 46.0}],
            ]

        def __enter__(self) -> "FakeCursor":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, query: str) -> None:
            self.queries.append(query)
            if query != "SET TRANSACTION READ ONLY":
                self.query_index += 1

        def fetchone(self) -> dict[str, object]:
            return self.rows[self.query_index][0]

        def fetchall(self) -> list[dict[str, object]]:
            return self.rows[self.query_index]

    class FakeConnection:
        def __init__(self) -> None:
            self.fake_cursor = FakeCursor()

        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def cursor(self, *, row_factory):
            assert row_factory is auth_app.dict_row
            return self.fake_cursor

    connection = FakeConnection()
    monkeypatch.setattr(
        auth_app.psycopg,
        "connect",
        lambda *args, **kwargs: connection,
    )

    client = TestClient(auth_app.app)
    client.cookies.set("inflatrack_access_token", "test-access-token")
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert response.json()["latest_month"] == "2026-09-01"
    assert response.json()["kpis"] == {"ipca_12m_pct": 4.5, "inpc_12m_pct": 4.2}
    assert connection.fake_cursor.queries[0] == "SET TRANSACTION READ ONLY"
    assert all("serie." in query for query in connection.fake_cursor.queries[1:])


def test_dashboard_reports_unavailable_postgres(monkeypatch) -> None:
    mock_authenticated_user(monkeypatch)

    def fail_connect(*args: object, **kwargs: object):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(auth_app.psycopg, "connect", fail_connect)

    client = TestClient(auth_app.app)
    client.cookies.set("inflatrack_access_token", "test-access-token")
    response = client.get("/dashboard")

    assert response.status_code == 503
    assert "execute o pipeline Dagster" in response.json()["detail"]


def test_dashboard_requires_authenticated_session() -> None:
    response = TestClient(auth_app.app).get("/dashboard")

    assert response.status_code == 401
    assert response.json()["detail"] == "Entre na sua conta para continuar."