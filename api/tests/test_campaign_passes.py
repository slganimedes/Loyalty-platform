import io
import json
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from campaign_fixtures import create_campaign
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
from google.auth import crypt, jwt
from sqlalchemy import create_engine, text
from test_e2e import SessionLocal, client, models, payment, shop
from test_wallet import wallet_config as wallet_fixture

from app import db as database
from app.main import app
from app.services import passes
from app.services.security import hash_password

wallet_config = wallet_fixture


def campaign(mid, name="Campaign A"):
    return create_campaign(
        client,
        f"/api/v1/merchants/{mid}/campaigns",
        json={
            "name": name,
            "type": "points_per_spend",
            "config": {"points": 1, "amount_unit": 10},
        },
    ).json()["id"]


@pytest.fixture
def google_provider(wallet_config, monkeypatch):
    with SessionLocal() as db:
        cfg = passes._wallet_config(db)
        cfg.apple_enabled = False
        cfg.google_enabled = True
        cfg.google_config = {"issuer_id": "123", "sa_json": "unused"}
        db.commit()
    sync = Mock(
        side_effect=lambda db, c, row, cfg: "https://pay.google.com/gp/v/save/test-" + row.id
    )
    monkeypatch.setattr(passes, "google_sync", sync)
    monkeypatch.setattr(
        passes, "_google_credentials", lambda cfg: SimpleNamespace(token="test", refresh=Mock())
    )
    requests = []
    status = [200]
    original = httpx.Client

    def handler(request):
        requests.append(request)
        return httpx.Response(status[0], json={})

    monkeypatch.setattr(
        passes.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    return sync, requests, status


def assign(cid, camp, provider="google"):
    return client.post(
        f"/api/v1/customers/{cid}/passes", json={"campaign_id": camp, "platform": provider}
    )


def test_generic_provider_contract_updates_and_revokes_with_stable_object(
    wallet_config, monkeypatch
):
    _, key, cert = wallet_config
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    creds = SimpleNamespace(
        token="fake",
        refresh=Mock(),
        signer=crypt.RSASigner.from_string(pem),
        service_account_email="fixture@example.iam.gserviceaccount.com",
    )
    monkeypatch.setattr(passes, "_google_credentials", lambda config: creds)
    calls, created = [], set()

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            identity = json.loads(request.content)["id"]
            if identity in created:
                return httpx.Response(409)
            created.add(identity)
        return httpx.Response(200, json={})

    original = httpx.Client
    monkeypatch.setattr(
        passes.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    with SessionLocal() as db:
        cfg = passes._wallet_config(db)
        cfg.apple_enabled, cfg.google_enabled = False, True
        cfg.google_config = {"issuer_id": "123", "sa_json": "unused"}
        db.commit()
    mid, cid = shop()
    camp = campaign(mid)
    first = assign(cid, camp).json()
    assert first["provider_synced"]
    token = first["url"].rsplit("/", 1)[-1]
    claims = jwt.decode(
        token, certs=cert.public_bytes(serialization.Encoding.PEM), audience="google"
    )
    with SessionLocal() as db:
        external_id = db.get(models.Pass, first["pass"]["id"]).external_pass_id
    assert claims["payload"]["genericObjects"][0]["id"] == external_id
    assert any(r.url.path.endswith("/genericClass") for r in calls)
    assert any(r.url.path.endswith("/genericObject") for r in calls)
    payment(mid)
    patches = [
        json.loads(r.content)
        for r in calls
        if r.method == "PATCH" and "/genericObject/" in r.url.path
    ]
    assert patches[-1]["textModulesData"][0]["body"] == "2"
    assert patches[-1]["header"]["defaultValue"]["value"] == "C"
    assert client.post(f"/api/v1/campaigns/{camp}/archive").json()["pending_revocations"] == 0
    assert json.loads(calls[-1].content)["state"] == "INACTIVE"
    assert "/genericObject/" in calls[-1].url.path


def test_explicit_multiple_campaign_assignments_and_no_auto_creation(google_provider):
    mid, cid = shop()
    assert client.get(f"/api/v1/merchants/{mid}/passes").json() == []
    first, second = campaign(mid), campaign(mid, "Campaign B")
    payment(mid)
    assert client.get(f"/api/v1/merchants/{mid}/passes").json() == []
    a, b = assign(cid, first).json(), assign(cid, second).json()
    assert a["url"] and b["url"] and a["url"] != b["url"]
    assert a["pass"]["campaign_id"] == first
    assert b["pass"]["campaign_name"] == "Campaign B"
    assert assign(cid, first).json()["pass"]["id"] == a["pass"]["id"]
    with SessionLocal() as db:
        row = db.get(models.Pass, a["pass"]["id"])
        assert passes.campaign_balance(db, row.customer, row) == 2
        assert row.customer.points_balance == 4
    sync = google_provider[0]
    sync.reset_mock()
    client.get(f"/api/v1/merchants/{mid}/passes")
    assert not sync.called


def test_campaign_deletion_preserves_history_and_revokes_only_its_passes(google_provider):
    mid, cid = shop()
    first, second = campaign(mid), campaign(mid, "Second")
    a, b = assign(cid, first).json()["pass"], assign(cid, second).json()["pass"]
    payment(mid)
    response = client.delete(f"/api/v1/merchants/{mid}/campaigns/{first}")
    assert response.json()["pending_revocations"] == 0
    assert [c["id"] for c in client.get(f"/api/v1/merchants/{mid}/campaigns").json()] == [second]
    assert client.post(f"/api/v1/customers/{cid}/passes/{a['id']}/link").status_code == 410
    assert assign(cid, first).status_code == 404
    assert client.post(f"/api/v1/customers/{cid}/passes/{b['id']}/link").json()["url"]
    assert payment(mid).json()["points_delta"] == 2
    with SessionLocal() as db:
        assert db.query(models.Movement).filter_by(campaign_id=first).count() == 1
    assert len(google_provider[1]) == 1
    assert json.loads(google_provider[1][0].content) == {"state": "INACTIVE"}


def test_deleted_customer_no_longer_matches_and_pending_revocation_retries(google_provider):
    mid, cid = shop()
    a = assign(cid, campaign(mid)).json()["pass"]
    google_provider[2][0] = 503
    response = client.delete(f"/api/v1/customers/{cid}")
    assert response.json()["pending_revocations"] == 1
    assert client.get(f"/api/v1/merchants/{mid}/customers").json() == []
    assert payment(mid).json()["status"] == "unmatched"
    assert client.post(f"/api/v1/customers/{cid}/passes/{a['id']}/link").status_code == 410
    rows = client.get(f"/api/v1/merchants/{mid}/passes").json()
    assert rows[0]["status"] == "revoked" and rows[0]["sync_pending"]
    google_provider[2][0] = 200
    passes.retry_pending_revocations()
    assert not client.get(f"/api/v1/merchants/{mid}/passes").json()[0]["sync_pending"]
    calls = len(google_provider[1])
    client.delete(f"/api/v1/customers/{cid}")
    assert len(google_provider[1]) == calls


def test_reassign_after_deletion_keeps_enrollment_object_id(google_provider):
    mid, cid = shop()
    camp = campaign(mid)
    first = assign(cid, camp).json()["pass"]
    client.delete(f"/api/v1/customers/{cid}/passes/{first['id']}")
    second = assign(cid, camp).json()["pass"]
    assert second["id"] == first["id"]
    with SessionLocal() as db:
        assert (
            db.get(models.Pass, first["id"]).external_pass_id
            == db.get(models.Pass, second["id"]).external_pass_id
        )


def test_assignment_and_deletions_are_merchant_scoped(google_provider):
    mid, cid = shop()
    other_mid, other_cid = shop()
    other_camp = campaign(other_mid)
    assert assign(cid, other_camp).status_code == 404
    other_pass = assign(other_cid, other_camp).json()["pass"]
    with SessionLocal() as db:
        db.add(
            models.AdminUser(
                username="campaign-owner",
                password_hash=hash_password("test-password"),
                role="sme_admin",
                merchant_id=mid,
            )
        )
        db.commit()
    scoped = TestClient(app)
    token = scoped.post(
        "/api/v1/auth/login", json={"username": "campaign-owner", "password": "test-password"}
    ).json()["access_token"]
    scoped.headers["Authorization"] = "Bearer " + token
    assert scoped.delete(f"/api/v1/customers/{other_cid}").status_code == 403
    assert (
        scoped.delete(f"/api/v1/customers/{other_cid}/passes/{other_pass['id']}").status_code == 403
    )
    assert scoped.delete(f"/api/v1/merchants/{mid}/campaigns/{other_camp}").status_code == 404
    assert scoped.get(f"/api/v1/merchants/{other_mid}/passes").status_code == 403


def test_apple_revocation_delivers_voided_update_and_blocks_install(wallet_config, monkeypatch):
    mid, cid = shop()
    data = assign(cid, campaign(mid), "apple").json()
    row_id = data["pass"]["id"]
    with SessionLocal() as db:
        row = db.get(models.Pass, row_id)
        token, kind = row.auth_token, row.pass_type_id
        db.add(
            models.DeviceRegistration(
                device_id="revoke-device", pass_id=row.id, push_token="abcdef"
            )
        )
        db.commit()
    push = Mock(return_value=True)
    monkeypatch.setattr(passes, "push_apple", push)
    assert client.delete(f"/api/v1/customers/{cid}/passes/{row_id}").json()["provider_synced"]
    assert push.called
    assert (
        client.get(f"/api/v1/passes/apple/{row_id}.pkpass", params={"token": token}).status_code
        == 404
    )
    updates = client.get(
        f"/api/v1/wallet/apple/v1/devices/revoke-device/registrations/{kind}"
    ).json()
    assert row_id in updates["serialNumbers"]
    response = client.get(
        f"/api/v1/wallet/apple/v1/passes/{kind}/{row_id}",
        headers={"Authorization": "ApplePass " + token},
    )
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        assert json.loads(bundle.read("pass.json"))["voided"] is True
    assert (
        client.post(
            f"/api/v1/wallet/apple/v1/devices/new-device/registrations/{kind}/{row_id}",
            headers={"Authorization": "ApplePass " + token},
            json={"pushToken": "abcdef"},
        ).status_code
        == 404
    )


def test_legacy_pass_migration_preserves_tokens_and_registrations(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    monkeypatch.setattr(database, "engine", engine)
    database.init_db()
    with engine.begin() as con:
        con.execute(text('DROP TABLE "pass"'))
        con.execute(
            text("""CREATE TABLE "pass" (id VARCHAR PRIMARY KEY, customer_id VARCHAR,
            platform VARCHAR, external_pass_id VARCHAR, status VARCHAR, auth_token VARCHAR,
            updated_tag INTEGER, synced_tag INTEGER, pass_type_id VARCHAR,
            UNIQUE (customer_id, platform))""")
        )
        con.execute(models.Merchant.__table__.insert().values(id="m", name="Legacy"))
        con.execute(
            models.Customer.__table__.insert().values(id="c", merchant_id="m", customer_code="C")
        )
        con.execute(
            text(
                """INSERT INTO "pass" VALUES ('p','c','apple','p','active','keep-token',10,10,'pass.test')"""
            )
        )
        con.execute(text("INSERT INTO device_registration VALUES ('d','device','p','push')"))
    database.init_db()
    database.init_db()
    with engine.connect() as con:
        assert con.execute(text('SELECT auth_token, campaign_id FROM "pass"')).one() == (
            "keep-token",
            None,
        )
        assert con.execute(text("SELECT pass_id FROM device_registration")).scalar() == "p"
        assert con.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()


def test_merchant_deletion_summary_cascade_and_retries(google_provider):
    mid, cid = shop()
    other_mid, other_cid = shop()
    camp = campaign(mid)
    a = assign(cid, camp).json()["pass"]
    payment(mid)
    coupon = client.post(
        f"/api/v1/merchants/{mid}/coupons", json={"customer_id": cid, "amount": 5}
    ).json()
    with SessionLocal() as db:
        user = models.AdminUser(
            username="deleted-shop-admin",
            password_hash=hash_password("secret"),
            role="sme_admin",
            merchant_id=mid,
        )
        db.add(user)
        db.commit()
    login = client.post(
        "/api/v1/auth/login", json={"username": "deleted-shop-admin", "password": "secret"}
    )
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert (
        client.get(f"/api/v1/merchants/{mid}/deletion-preview", headers=headers).status_code == 403
    )
    preview = client.get(f"/api/v1/merchants/{mid}/deletion-preview").json()
    assert (
        preview["customers"]
        == preview["passes"]
        == preview["campaigns"]
        == preview["coupons"]
        == preview["admins"]
        == 1
    )
    assert preview["transactions"] == 1
    assert client.delete(f"/api/v1/merchants/{mid}").status_code == 422
    google_provider[2][0] = 503
    result = client.request(
        "DELETE", f"/api/v1/merchants/{mid}", json={"revision": preview["revision"]}
    )
    assert result.status_code == 200 and result.json()["pending_revocations"] == 1
    assert mid not in [m["id"] for m in client.get("/api/v1/merchants").json()]
    assert client.get(f"/api/v1/merchants/{mid}/customers").status_code == 404
    assert client.patch(f"/api/v1/merchants/{mid}", json={"status": "active"}).status_code == 404
    assert (
        client.post(
            f"/api/v1/merchants/{mid}/customers", json={"customer_code": "late"}
        ).status_code
        == 404
    )
    assert client.get("/api/v1/users/me", headers=headers).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "deleted-shop-admin", "password": "secret"}
        ).status_code
        == 401
    )
    assert payment(mid).status_code == 404
    assert client.get(f"/api/v1/merchants/{other_mid}/customers").json()[0]["id"] == other_cid
    with SessionLocal() as db:
        assert db.get(models.Customer, cid).deleted
        assert db.get(models.Campaign, camp).deleted
        assert db.get(models.Coupon, coupon["id"]).status == "cancelled"
        assert db.get(models.Pass, a["id"]).status == "revoked"
        assert db.query(models.Movement).filter_by(customer_id=cid).count() > 0
    google_provider[2][0] = 200
    passes.retry_pending_revocations()
    with SessionLocal() as db:
        row = db.get(models.Pass, a["id"])
        assert row.updated_tag == row.synced_tag


def test_merchant_deletion_rejects_stale_confirmation():
    mid, cid = shop()
    preview = client.get(f"/api/v1/merchants/{mid}/deletion-preview").json()
    client.post(f"/api/v1/merchants/{mid}/customers", json={"customer_code": "added-after-preview"})
    response = client.request(
        "DELETE", f"/api/v1/merchants/{mid}", json={"revision": preview["revision"]}
    )
    assert response.status_code == 409
    assert client.get(f"/api/v1/merchants/{mid}").json()["status"] == "active"


def test_public_api_entry_and_documentation():
    public = TestClient(app)
    assert 'href="/docs"' in public.get("/").text
    assert public.get("/docs").status_code == 200
    assert public.get("/redoc").status_code == 200
    schema = public.get("/openapi.json").json()
    assert "delete" in schema["paths"]["/api/v1/merchants/{merchant_id}"]
    assert public.get("/api/v1/merchants").status_code == 401
