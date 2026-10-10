def test_unauthenticated_api_is_rejected(client):
    for method, path in [("get", "/api/projects"), ("get", "/api/providers"), ("get", "/api/preferences"),
                         ("post", "/api/jobs/selftest"), ("get", "/media/anything.mp4")]:
        r = getattr(client, method)(path)
        assert r.status_code == 401, (path, r.status_code)
        if path.startswith("/api/"):
            assert r.json()["error"]["code"] == "unauthenticated"


def test_public_endpoints_open(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/auth/me").json() == {"authenticated": False}


def test_wrong_password_then_rate_limit(client):
    for _ in range(5):
        assert client.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    r = client.post("/api/auth/login", json={"password": "nope"})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "too_many_attempts"


def test_login_sets_httponly_cookie_and_grants_access(client):
    r = client.post("/api/auth/login", json={"password": "test-password-123"})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert client.get("/api/auth/me").json() == {"authenticated": True}
    assert client.get("/api/projects").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/projects").status_code == 401


def test_tampered_cookie_rejected(client):
    from app.auth import COOKIE, make_token
    tok = make_token()
    client.cookies.set(COOKIE, tok[:-2] + ("00" if not tok.endswith("00") else "11"))
    assert client.get("/api/projects").status_code == 401


def test_security_headers(client):
    r = client.get("/api/health")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
