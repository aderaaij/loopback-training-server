"""Admin user-management + auth self-service endpoints (dashboard items 1-3).

Covers the role guard, the CLI-mirroring admin verbs, change-password (400 on
wrong current — never 401, which the SPA reads as "token dead"), and
self-service token minting.
"""

from fastapi.testclient import TestClient

from app.main import app
from app.version import __version__


def _client(token: str) -> TestClient:
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def _new_user(client_admin: TestClient, username: str, password: str = "hunter2secret", **over):
    body = {"username": username, "password": password, **over}
    return client_admin.post("/api/admin/users", json=body)


def _login(username: str, password: str):
    return TestClient(app).post("/api/auth/login", json={"username": username, "password": password})


# --- role guard --------------------------------------------------------------

def test_admin_routes_reject_non_admin(client_a, user_b):
    assert client_a.get("/api/admin/users").status_code == 403
    assert _new_user(client_a, "eve").status_code == 403
    uid = str(user_b[0])
    assert client_a.post(f"/api/admin/users/{uid}/password", json={"password": "hunter2secret"}).status_code == 403
    assert client_a.patch(f"/api/admin/users/{uid}", json={"isActive": False}).status_code == 403


def test_admin_routes_reject_unauthenticated():
    assert TestClient(app).get("/api/admin/users").status_code in (401, 403)


# --- list --------------------------------------------------------------------

def test_list_users_shape(client_admin, user_a):
    rows = client_admin.get("/api/admin/users").json()
    assert {r["username"] for r in rows} == {"root", "alice"}
    alice = next(r for r in rows if r["username"] == "alice")
    assert set(alice) == {
        "id", "username", "displayName", "role", "isActive", "tokenCount", "lastSeenAt",
        "lastWorkoutSyncAt", "lastHealthDate",
        "dataConsent", "dataConsentUpdatedAt", "dataConsentReportedAt",
    }
    assert alice["role"] == "user"
    assert alice["isActive"] is True
    assert alice["tokenCount"] == 1  # the fixture's login token
    # No seeded workouts/health for the fixture user.
    assert alice["lastWorkoutSyncAt"] is None
    assert alice["lastHealthDate"] is None
    # Never reported consent — both stamps null, permissive default in force.
    assert alice["dataConsent"] == ["training", "recovery", "body", "activity", "nutrition"]
    assert alice["dataConsentReportedAt"] is None


# --- create ------------------------------------------------------------------

def test_create_user_and_login(client_admin):
    res = _new_user(client_admin, "  Sam  ", display_name="Sam Rivera")
    assert res.status_code == 201
    row = res.json()
    assert row["username"] == "sam"  # normalized
    assert row["displayName"] == "Sam Rivera"
    assert row["role"] == "user"
    assert row["tokenCount"] == 0 and row["lastSeenAt"] is None

    assert _login("sam", "hunter2secret").status_code == 200
    assert _login("sam", "wrong-password").status_code == 401


def test_create_admin_role(client_admin):
    assert _new_user(client_admin, "boss", role="admin").json()["role"] == "admin"


def test_create_user_validation(client_admin, user_a):
    assert _new_user(client_admin, "alice").status_code == 409  # duplicate
    assert _new_user(client_admin, "eve", password="short").status_code == 422
    assert _new_user(client_admin, "eve", role="superuser").status_code == 422
    assert _new_user(client_admin, "has space").status_code == 422
    assert _new_user(client_admin, "x" * 33).status_code == 422


# --- reset password ------------------------------------------------------------

def test_reset_password(client_admin, user_a):
    uid = str(user_a[0])
    assert client_admin.post(f"/api/admin/users/{uid}/password", json={"password": "fresh-password"}).status_code == 204
    assert _login("alice", "fresh-password").status_code == 200
    assert _login("alice", "pw").status_code == 401  # old password dead


# --- deactivate / reactivate ---------------------------------------------------

def test_deactivate_revokes_tokens_and_reactivate(client_admin, user_a, client_a):
    uid = str(user_a[0])
    res = client_admin.patch(f"/api/admin/users/{uid}", json={"isActive": False})
    assert res.status_code == 200
    assert res.json()["isActive"] is False
    assert res.json()["tokenCount"] == 0  # tokens deleted, not just inactive

    # The device stops authenticating immediately (its token row is gone).
    assert client_a.get("/api/workouts").status_code == 401
    # And login is refused while inactive.
    assert _login("alice", "pw").status_code == 401

    assert client_admin.patch(f"/api/admin/users/{uid}", json={"isActive": True}).json()["isActive"] is True
    assert _login("alice", "pw").status_code == 200


def test_admin_cannot_deactivate_self(client_admin, admin_user):
    uid = str(admin_user[0])
    assert client_admin.patch(f"/api/admin/users/{uid}", json={"isActive": False}).status_code == 400


# --- change own password -------------------------------------------------------

def test_change_password_wrong_current_is_400_not_401(client_a):
    res = client_a.post("/api/auth/password", json={"currentPassword": "nope", "newPassword": "fresh-password"})
    assert res.status_code == 400  # 401 would make the SPA drop the session


def test_change_password_revokes_other_sessions(client_a):
    # Mint a second token = a second device.
    other_raw = client_a.post("/api/auth/tokens", json={"name": "Other device"}).json()["token"]
    other = _client(other_raw)
    assert other.get("/api/auth/me").status_code == 200

    res = client_a.post("/api/auth/password", json={"currentPassword": "pw", "newPassword": "fresh-password"})
    assert res.status_code == 200
    assert res.json() == {"revokedTokens": 1}

    assert client_a.get("/api/auth/me").status_code == 200  # this session survives
    assert other.get("/api/auth/me").status_code == 401  # the other one is out
    assert _login("alice", "fresh-password").status_code == 200
    assert _login("alice", "pw").status_code == 401


def test_change_password_validates_new(client_a):
    res = client_a.post("/api/auth/password", json={"currentPassword": "pw", "newPassword": "short"})
    assert res.status_code == 422


# --- self-service token minting --------------------------------------------------

def test_mint_token(client_a):
    res = client_a.post("/api/auth/tokens", json={"name": "  Coach MCP  "})
    assert res.status_code == 201
    body = res.json()
    assert set(body) == {"token", "tokenId"}
    assert body["token"].startswith("tapi_")

    minted = _client(body["token"])
    assert minted.get("/api/auth/me").status_code == 200
    names = {t["name"]: t for t in minted.get("/api/auth/me").json()["tokens"]}
    assert names["Coach MCP"]["expiresAt"] is None  # name trimmed, no expiry


def test_mint_token_with_expiry(client_a):
    res = client_a.post("/api/auth/tokens", json={"name": "Ephemeral", "expiresAt": "2030-01-01T00:00:00Z"})
    assert res.status_code == 201
    me = client_a.get("/api/auth/me").json()
    tok = next(t for t in me["tokens"] if t["name"] == "Ephemeral")
    assert tok["expiresAt"] is not None

    # A past expiry mints a token that is already dead — the expiry path 401s.
    past = client_a.post("/api/auth/tokens", json={"name": "Dead", "expiresAt": "2020-01-01T00:00:00Z"})
    assert _client(past.json()["token"]).get("/api/auth/me").status_code == 401


def test_mint_token_validation(client_a):
    assert client_a.post("/api/auth/tokens", json={"name": "   "}).status_code == 422
    # Naive datetimes are rejected — the column is timezone-aware.
    res = client_a.post("/api/auth/tokens", json={"name": "x", "expiresAt": "2030-01-01T00:00:00"})
    assert res.status_code == 422


# --- admin token inspection / revoke -----------------------------------------

def test_admin_list_and_revoke_user_token(client_admin, user_a, client_a):
    uid = str(user_a[0])
    tokens = client_admin.get(f"/api/admin/users/{uid}/tokens").json()
    assert len(tokens) == 1 and tokens[0]["name"] == "test-device"

    tid = tokens[0]["id"]
    assert client_admin.delete(f"/api/admin/users/{uid}/tokens/{tid}").status_code == 204
    # That device stops authenticating immediately.
    assert client_a.get("/api/auth/me").status_code == 401
    assert client_admin.get(f"/api/admin/users/{uid}/tokens").json() == []


def test_admin_revoke_token_wrong_user_is_404(client_admin, user_a, user_b):
    # user_b's token can't be revoked via user_a's id — no cross-user probing.
    b_tokens = client_admin.get(f"/api/admin/users/{user_b[0]}/tokens").json()
    res = client_admin.delete(f"/api/admin/users/{user_a[0]}/tokens/{b_tokens[0]['id']}")
    assert res.status_code == 404


def test_admin_token_routes_reject_non_admin(client_a, user_a):
    assert client_a.get(f"/api/admin/users/{user_a[0]}/tokens").status_code == 403


# --- auth events feed --------------------------------------------------------

def test_events_feed_records_login_and_admin_actions(client_admin, user_a):
    # A failed then successful login.
    assert _login("alice", "wrong").status_code == 401
    assert _login("alice", "pw").status_code == 200
    # An admin action (password reset) with a distinct actor.
    client_admin.post(f"/api/admin/users/{user_a[0]}/password", json={"password": "brand-new-pw"})

    events = client_admin.get("/api/admin/events").json()
    kinds = {e["event"] for e in events}
    assert {"login_failed", "login_success", "password_reset"} <= kinds
    reset = next(e for e in events if e["event"] == "password_reset")
    assert reset["username"] == "alice" and reset["actorUsername"] == "root"
    fail = next(e for e in events if e["event"] == "login_failed")
    assert fail["username"] == "alice"


def test_events_feed_rejects_non_admin(client_a):
    assert client_a.get("/api/admin/events").status_code == 403


def test_rate_limited_login_audits_once_per_window(client_admin, user_a):
    # 5/min/IP on login; past that every request 429s but the audit trail gets
    # at most one row per IP per window — hammering can't flood the table.
    codes = [_login("alice", "wrong").status_code for _ in range(8)]
    assert codes.count(429) >= 2

    events = client_admin.get("/api/admin/events").json()
    limited = [e for e in events if e["event"] == "login_rate_limited"]
    assert len(limited) == 1
    assert limited[0]["ip"] is not None


# --- system status -----------------------------------------------------------

def test_system_status_shape(client_admin, user_a):
    body = client_admin.get("/api/admin/system").json()
    assert set(body) == {"appVersion", "backup", "backupCount", "dbSizeBytes", "migrationHead", "counts"}
    assert body["appVersion"] == __version__
    assert body["dbSizeBytes"] > 0
    assert "users" in body["counts"] and body["counts"]["users"] >= 2
    # backup may or may not exist depending on env (the container mounts the NAS
    # dir; a bare checkout has none). The two must agree, and it never errors.
    assert body["backupCount"] >= 0
    assert (body["backup"] is not None) == (body["backupCount"] > 0)


def test_system_status_rejects_non_admin(client_a):
    assert client_a.get("/api/admin/system").status_code == 403
