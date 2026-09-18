import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from test_e2e import SessionLocal, client, models

from app import db as database
from app.main import app
from app.services.passes import _png
from app.services.security import hash_password


def encoded(color="#123456"):
    return base64.b64encode(_png(color, 32)).decode()


def test_logo_database_lifecycle():
    response = client.post(
        "/api/v1/merchants", json={"name": "Uploaded logo", "logo_base64": encoded()}
    )
    assert response.status_code == 200
    merchant = response.json()
    mid = merchant["id"]
    assert "logo_base64" not in merchant and "logo_data" not in merchant
    with SessionLocal() as db:
        assert db.get(models.Merchant, mid).logo_data == _png("#123456", 32)
    public = TestClient(app)
    response = public.get(merchant["logo_url"])
    assert response.headers["content-type"] == "image/png"
    assert response.content == _png("#123456", 32)
    renamed = client.patch(f"/api/v1/merchants/{mid}", json={"name": "Renamed"}).json()
    assert renamed["logo_url"] == merchant["logo_url"]
    changed = client.patch(
        f"/api/v1/merchants/{mid}", json={"logo_base64": encoded("#abcdef")}
    ).json()
    assert changed["logo_url"] != merchant["logo_url"]
    assert public.get(changed["logo_url"]).content == _png("#abcdef", 32)
    removed = client.patch(f"/api/v1/merchants/{mid}", json={"logo_base64": None}).json()
    assert removed["logo_url"] is None
    with SessionLocal() as db:
        assert db.get(models.Merchant, mid).logo_data is None


@pytest.mark.parametrize(
    "value",
    [
        "not-base64!",
        base64.b64encode(b"<svg onload='alert(1)'></svg>").decode(),
        base64.b64encode(_png("#000000", 32)[:-12]).decode(),
        base64.b64encode(_png("#000000", 2049)).decode(),
        "A" * 2796208,
    ],
    ids=["base64", "svg", "truncated", "dimensions", "size"],
)
def test_invalid_logos_are_rejected_without_changes(value):
    merchant = client.post(
        "/api/v1/merchants", json={"name": "Keep logo", "logo_base64": encoded()}
    ).json()
    assert (
        client.post("/api/v1/merchants", json={"name": "Invalid", "logo_base64": value}).status_code
        == 422
    )
    assert (
        client.patch(f"/api/v1/merchants/{merchant['id']}", json={"logo_base64": value}).status_code
        == 422
    )
    assert client.get(merchant["logo_url"]).content == _png("#123456", 32)


def test_logo_upload_requires_merchant_access():
    own = client.post("/api/v1/merchants", json={"name": "Owned"}).json()["id"]
    other = client.post("/api/v1/merchants", json={"name": "Other"}).json()["id"]
    with SessionLocal() as db:
        db.add(
            models.AdminUser(
                username="logo-owner",
                password_hash=hash_password("test-password"),
                role="sme_admin",
                merchant_id=own,
            )
        )
        db.commit()
    scoped = TestClient(app)
    body = {"logo_base64": encoded()}
    assert scoped.patch(f"/api/v1/merchants/{own}", json=body).status_code == 401
    token = scoped.post(
        "/api/v1/auth/login",
        json={
            "username": "logo-owner",
            "password": "test-password",
        },
    ).json()["access_token"]
    scoped.headers["Authorization"] = "Bearer " + token
    assert scoped.patch(f"/api/v1/merchants/{other}", json=body).status_code == 403
    assert scoped.patch(f"/api/v1/merchants/{own}", json=body).status_code == 200


def test_logo_migration_preserves_existing_merchants(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE merchant (id VARCHAR PRIMARY KEY, name VARCHAR)"))
        connection.execute(text("INSERT INTO merchant (id, name) VALUES ('legacy', 'Existing')"))
    monkeypatch.setattr(database, "engine", engine)
    database.init_db()
    database.init_db()
    with engine.connect() as connection:
        assert "logo_data" in {
            column["name"] for column in inspect(connection).get_columns("merchant")
        }
        assert connection.execute(text("SELECT name, logo_data FROM merchant")).one() == (
            "Existing",
            None,
        )
    engine.dispose()
