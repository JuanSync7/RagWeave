from src.platform.security import auth


def test_api_key_auth_match(monkeypatch):
    payload = {
        "svc1": {
            "key": "test-key",
            "subject": "service-a",
            "tenant_id": "t-1",
            "roles": ["query"],
        }
    }
    monkeypatch.setattr(auth, "_API_KEY_INDEX", payload)
    principal = auth._principal_from_api_key("test-key")
    assert principal is not None
    assert principal.tenant_id == "t-1"
    assert "query" in principal.roles


def test_oidc_principal_mapping(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_OIDC_ENABLED", True)
    monkeypatch.setattr(auth, "AUTH_OIDC_ROLES_CLAIM", "roles")
    monkeypatch.setattr(auth, "AUTH_OIDC_SUBJECT_CLAIM", "sub")
    monkeypatch.setattr(auth, "AUTH_OIDC_TENANT_CLAIM", "tenant_id")
    monkeypatch.setattr(
        auth,
        "_verify_oidc_jwt",
        lambda _token: {
            "sub": "user-1",
            "tenant_id": "tenant-1",
            "roles": ["query", "admin"],
            "project_id": "p-1",
        },
    )
    principal = auth._principal_from_jwt("dummy")
    assert principal.subject == "user-1"
    assert principal.tenant_id == "tenant-1"
    assert "admin" in principal.roles
    assert principal.project_id == "p-1"

