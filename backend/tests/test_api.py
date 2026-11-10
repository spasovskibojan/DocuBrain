import uuid

import pytest

pytestmark = pytest.mark.asyncio

PASSWORD = "Str0ngPassw0rd"


def _new_email() -> str:
    return f"user_{uuid.uuid4().hex[:8]}@example.com"


async def _register(client, email: str, password: str = PASSWORD):
    return await client.post("/api/auth/register", json={"email": email, "password": password})


async def _login(client, email: str, password: str = PASSWORD):
    return await client.post("/api/auth/login", json={"email": email, "password": password})


async def test_health_check(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


async def test_register_and_login(client):
    email = _new_email()

    register = await _register(client, email)
    assert register.status_code == 201
    assert register.json()["email"] == email

    login = await _login(client, email)
    assert login.status_code == 200
    assert login.json()["access_token"]
    assert login.json()["user"]["email"] == email


async def test_register_rejects_duplicate_email(client):
    email = _new_email()
    await _register(client, email)

    response = await _register(client, email)
    assert response.status_code == 400


async def test_register_rejects_short_password(client):
    response = await _register(client, _new_email(), password="short")
    assert response.status_code == 422


async def test_login_returns_401_for_bad_credentials(client):
    email = _new_email()
    await _register(client, email)

    wrong_password = await _login(client, email, password="WrongPassw0rd")
    assert wrong_password.status_code == 401

    unknown_user = await _login(client, _new_email())
    assert unknown_user.status_code == 401


async def test_documents_require_auth(client):
    response = await client.get("/api/documents/")
    assert response.status_code == 403


async def test_invalid_token_is_rejected(client):
    response = await client.get("/api/documents/", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


async def test_new_user_has_empty_library(client):
    email = _new_email()
    await _register(client, email)
    token = (await _login(client, email)).json()["access_token"]

    response = await client.get("/api/documents/", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"documents": [], "total": 0}
