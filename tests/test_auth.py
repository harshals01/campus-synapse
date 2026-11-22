"""Authentication: tokens, rejection paths, and immediate deactivation."""
import jwt
import pytest

from backend import config
from backend.auth import create_access_token, create_preview_token
from backend.models.db_models import User


def test_all_roles_can_log_in(login):
    for key in ("admin", "teacher", "cse5", "ece3"):
        assert login(key)["Authorization"].startswith("Bearer ")


def test_wrong_password_is_rejected(client, accounts):
    import backend.routes.auth as auth_routes
    auth_routes._login_attempts.clear()
    response = client.post(
        "/auth/login",
        json={"college_id": accounts["cse5"]["college_id"], "password": "not-the-password"},
    )
    assert response.status_code == 401
    # The message must not reveal which field was wrong.
    assert "password" not in response.json()["detail"].lower()


def test_unknown_user_is_rejected_the_same_way(client):
    import backend.routes.auth as auth_routes
    auth_routes._login_attempts.clear()
    response = client.post(
        "/auth/login",
        json={"college_id": "nobody@bitmesra.ac.in", "password": "Passw0rd!"},
    )
    assert response.status_code == 401


def test_non_college_email_is_rejected_before_any_db_lookup(client):
    import backend.routes.auth as auth_routes
    auth_routes._login_attempts.clear()
    response = client.post(
        "/auth/login",
        json={"college_id": "someone@gmail.com", "password": "Passw0rd!"},
    )
    assert response.status_code == 422


def test_login_is_rate_limited(client, accounts):
    """The limiter is per IP, which every TestClient call shares."""
    import backend.routes.auth as auth_routes
    auth_routes._login_attempts.clear()
    codes = []
    for _ in range(auth_routes._MAX_ATTEMPTS + 2):
        codes.append(
            client.post(
                "/auth/login",
                json={"college_id": accounts["cse5"]["college_id"], "password": "wrongpass"},
            ).status_code
        )
    assert 429 in codes, f"expected a 429 once over the limit, got {codes}"
    auth_routes._login_attempts.clear()


@pytest.mark.parametrize("header", [None, {"Authorization": "Bearer not.a.jwt"}, {"Authorization": "Bearer "}])
def test_missing_or_malformed_token_is_401(client, header):
    response = client.get("/documents", headers=header or {})
    assert response.status_code in (401, 403)


def test_token_signed_with_another_secret_is_rejected(client, accounts):
    forged = jwt.encode(
        {"sub": accounts["admin"]["id"], "exp": 9999999999},
        "a-different-secret",
        algorithm="HS256",
    )
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


def test_expired_token_is_rejected(client, accounts, monkeypatch):
    monkeypatch.setattr(config, "JWT_EXPIRE_MINUTES", -5)
    expired = create_access_token(accounts["cse5"]["id"])
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_preview_token_cannot_be_used_as_a_session_token(client, accounts):
    """Different audience claim, so it must not authenticate an API call."""
    preview = create_preview_token(accounts["cse5"]["id"], "some-doc-id", 1)
    response = client.get("/documents", headers={"Authorization": f"Bearer {preview}"})
    assert response.status_code == 401


def test_me_returns_the_profile(client, login, accounts):
    body = client.get("/auth/me", headers=login("cse5")).json()
    assert body["college_id"] == accounts["cse5"]["college_id"]
    assert body["role"] == "student"
    assert body["branch"] == "CSE"
    assert body["semester"] == 5
    assert "password_hash" not in body


def test_deactivation_takes_effect_on_the_next_request(client, login, db_session, accounts):
    """The JWT carries only a user id; role and active flag are re-read per request."""
    headers = login("cse5")
    assert client.get("/documents", headers=headers).status_code == 200

    user = db_session.get(User, accounts["cse5"]["id"])
    user.active = False
    db_session.commit()
    try:
        assert client.get("/documents", headers=headers).status_code == 401
    finally:
        user.active = True
        db_session.commit()


def test_deactivated_account_cannot_log_in(client, db_session, accounts):
    import backend.routes.auth as auth_routes
    user = db_session.get(User, accounts["ece3"]["id"])
    user.active = False
    db_session.commit()
    try:
        auth_routes._login_attempts.clear()
        response = client.post(
            "/auth/login",
            json={"college_id": accounts["ece3"]["college_id"], "password": "Passw0rd!"},
        )
        assert response.status_code == 401
    finally:
        user.active = True
        db_session.commit()


def test_admin_routes_are_closed_to_students(client, login):
    assert client.get("/admin/users", headers=login("cse5")).status_code == 403
    assert client.get("/admin/questions", headers=login("teacher")).status_code == 403
    assert client.get("/admin/users", headers=login("admin")).status_code == 200
