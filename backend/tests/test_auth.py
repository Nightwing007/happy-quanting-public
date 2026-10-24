import logging
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auth, clock
from app.models import Account, AccountKind, User, UserSession

PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def fresh_limiter() -> None:
    auth.login_limiter.reset()


def _signup(client: TestClient, username: str = "alice"):
    return client.post(
        "/api/auth/signup", json={"username": username, "password": PASSWORD, "display_name": "Alice"}
    )


def test_signup_me_logout_me(client: TestClient) -> None:
    r = _signup(client)
    assert r.status_code == 200
    assert r.json()["username"] == "alice"
    assert "password_hash" not in r.json()
    me = client.get("/api/me")
    assert me.status_code == 200 and me.json()["display_name"] == "Alice"
    assert client.post("/api/auth/logout").status_code == 204
    again = client.get("/api/me")
    assert again.status_code == 401
    assert again.json() == {"detail": "Please log in.", "code": "not_authenticated"}


def test_update_profile(client: TestClient) -> None:
    _signup(client)
    r = client.put("/api/me", json={"bio": "hi", "display_name": "Al", "avatar_url": "http://x/y.png"})
    assert r.status_code == 200
    assert (r.json()["bio"], r.json()["display_name"], r.json()["avatar_url"]) == (
        "hi",
        "Al",
        "http://x/y.png",
    )


def test_signup_validation_and_duplicates(client: TestClient) -> None:
    assert client.post("/api/auth/signup", json={"username": "a!", "password": PASSWORD}).status_code == 400
    weak = client.post("/api/auth/signup", json={"username": "bobby", "password": "short"})
    assert weak.json()["code"] == "weak_password"
    assert _signup(client, "Alice").status_code == 200  # stored lower-cased
    assert _signup(client, "alice").status_code == 409


def test_wrong_password_and_unknown_user_look_the_same(client: TestClient) -> None:
    _signup(client)
    client.post("/api/auth/logout")
    wrong = client.post("/api/auth/login", json={"username": "alice", "password": "nope-nope-nope"})
    unknown = client.post("/api/auth/login", json={"username": "ghost", "password": "nope-nope-nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json()["detail"] == "Wrong username or password."
    ok = client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
    assert ok.status_code == 200


def test_rate_limit_on_sixth_failure(client: TestClient) -> None:
    body = {"username": "ghost", "password": "nope-nope-nope"}
    assert [client.post("/api/auth/login", json=body).status_code for _ in range(5)] == [401] * 5
    sixth = client.post("/api/auth/login", json=body)
    assert sixth.status_code == 429
    assert sixth.json()["detail"].endswith(".")


def test_hash_format_and_verify() -> None:
    stored = auth.hash_password("hunter2hunter2")
    scheme, n, r, p, salt, digest = stored.split("$")
    assert (scheme, n, r, p) == ("scrypt", "16384", "8", "1")
    assert salt and digest
    assert auth.verify_password("hunter2hunter2", stored)
    assert not auth.verify_password("hunter3hunter3", stored)
    assert not auth.verify_password("anything", "!")
    assert auth.hash_password("hunter2hunter2") != stored  # fresh salt


def test_expired_session_is_refused(client: TestClient, db_session: Session) -> None:
    _signup(client)
    row = db_session.scalar(select(UserSession).order_by(UserSession.id.desc()))  # alice's, not tester's
    row.expires_at = clock.now() - timedelta(seconds=1)
    db_session.commit()
    assert client.get("/api/me").status_code == 401


def test_token_is_stored_hashed(client: TestClient, db_session: Session) -> None:
    _signup(client)
    token = client.cookies.get(auth.COOKIE)
    row = db_session.scalar(select(UserSession))
    assert token and row.token_hash != token and len(row.token_hash) == 64


def test_cookie_flags(client: TestClient) -> None:
    header = _signup(client).headers["set-cookie"].lower()
    assert "httponly" in header and "samesite=lax" in header and "path=/" in header
    assert "max-age=2592000" in header
    assert "secure" not in header.replace("httponly", "")


def test_password_never_in_responses_or_logs(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    bodies = [
        _signup(client).text,
        client.get("/api/me").text,
        client.post("/api/auth/logout").text,
        client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD}).text,
        client.post("/api/auth/login", json={"username": "alice", "password": "bad-password-1"}).text,
    ]
    assert all(PASSWORD not in b for b in bodies)
    assert PASSWORD not in caplog.text and "bad-password-1" not in caplog.text


def test_signup_creates_a_live_account_owned_by_the_user(client: TestClient, db_session: Session) -> None:
    user_id = _signup(client).json()["id"]
    account = db_session.scalar(select(Account).where(Account.user_id == user_id))
    assert account is not None and account.kind == AccountKind.LIVE
    assert db_session.get(User, user_id).username == "alice"


def test_demo_password_is_set_once(db_session: Session) -> None:
    db_session.add(User(username="demo", display_name="Demo", password_hash="!", created_at=clock.now()))
    db_session.commit()
    pw = auth.ensure_demo_password(db_session)
    assert pw and auth.ensure_demo_password(db_session) is None
    demo = db_session.scalar(select(User))
    assert auth.verify_password(pw, demo.password_hash)
