"""Campaign ownership, enrollment balances, public images and deterministic pass contracts."""

import io
import json
import os
import runpy
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from campaign_fixtures import design, image_data
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_e2e import SessionLocal, client, models, payment, shop

from app import db as database
from app.config import settings
from app.main import app
from app.migrations.campaign_designs import VERSION, migrate
from app.services import pass_assets
from app.services.points_pass import build_points_pass
from app.services.security import hash_password


def create(mid, ids=(), **extra):
    body = {
        "name": "Rewards",
        "type": "points_per_spend",
        "config": {"points": 1, "amount_unit": 10},
        "design": design(client, mid),
        "customer_ids": list(ids),
        **extra,
    }
    response = client.post(f"/api/v1/merchants/{mid}/campaigns", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def members(campaign):
    return client.get(f"/api/v1/campaigns/{campaign['id']}/customers").json()


def test_many_campaigns_empty_explicit_membership_and_pending_customer():
    mid, cid = shop()
    first, second = create(mid), create(mid, [cid])
    assert first["merchant_id"] == second["merchant_id"] == mid
    assert members(first) == []
    assert len(members(second)) == 1
    path = f"/api/v1/campaigns/{first['id']}/customers"
    a = client.post(path, json={"customer_ids": [cid, cid]})
    b = client.post(path, json={"customer_ids": [cid]})
    assert a.status_code == b.status_code == 200
    assert a.json()[0]["id"] == b.json()[0]["id"]
    assert len(client.get(f"/api/v1/customers/{cid}/campaigns").json()) == 2
    new = client.post(
        f"/api/v1/merchants/{mid}/customers", json={"customer_code": "pending"}
    ).json()["customer"]
    assert new["membership_status"] == "pending"
    active = client.post(
        f"/api/v1/merchants/{mid}/customers",
        json={"customer_code": "active", "campaign_ids": [first["id"], second["id"]]},
    ).json()["customer"]
    assert active["membership_status"] == "active"
    assert len(client.get(f"/api/v1/customers/{active['id']}/campaigns").json()) == 2


def test_points_only_accrue_in_active_enrollments_and_history_survives_archive():
    mid, cid = shop()
    a = create(mid, [cid])
    b = create(mid, [cid], config={"points": 3, "amount_unit": 10})
    unused = create(mid)
    assert payment(mid).json()["points_delta"] == 8
    assert members(a)[0]["points_balance"] == 2
    assert members(b)[0]["points_balance"] == 6
    assert members(unused) == []
    path = f"/api/v1/campaigns/{a['id']}/customers/{cid}"
    assert client.patch(path, json={"status": "suspended"}).status_code == 200
    assert payment(mid).json()["points_delta"] == 6
    assert members(a)[0]["points_balance"] == 2
    assert (
        client.post(
            f"/api/v1/campaigns/{a['id']}/customers", json={"customer_ids": [cid]}
        ).status_code
        == 409
    )
    assert client.patch(path, json={"status": "active"}).status_code == 200
    assert client.post(f"/api/v1/campaigns/{b['id']}/archive").status_code == 200
    assert payment(mid).json()["points_delta"] == 2
    assert members(b)[0]["points_balance"] == 12


def test_cross_merchant_batch_and_customer_creation_roll_back():
    mid, cid = shop()
    other, foreign = shop()
    camp = create(mid)
    path = f"/api/v1/campaigns/{camp['id']}/customers"
    assert client.post(path, json={"customer_ids": [cid, foreign]}).status_code == 404
    assert members(camp) == []
    response = client.post(
        f"/api/v1/merchants/{other}/customers",
        json={"customer_code": "must-rollback", "campaign_ids": [camp["id"]]},
    )
    assert response.status_code == 404
    assert not any(
        c["customer_code"] == "must-rollback"
        for c in client.get(f"/api/v1/merchants/{other}/customers").json()
    )
    with SessionLocal() as db:
        db.add(models.CampaignEnrollment(campaign_id=camp["id"], customer_id=foreign))
        with pytest.raises(IntegrityError):
            db.commit()


def test_design_singleton_draft_color_and_atomic_publication(monkeypatch):
    mid, cid = shop()
    other, foreign = shop()
    assets = design(client, mid)
    body = {
        "name": "Atomic",
        "type": "points_per_spend",
        "config": {},
        "design": assets,
        "customer_ids": [cid, foreign],
    }
    path = f"/api/v1/merchants/{mid}/campaigns"
    assert client.post(path, json=body).status_code == 404
    assert client.get(path).json() == []
    asset_path = f"/api/v1/public/pass-assets/{assets['logo_asset_id']}"
    assert TestClient(app).get(asset_path).status_code == 404
    body["customer_ids"] = []
    body["design"]["background_color"] = "red"
    assert client.post(path, json=body).status_code == 422
    body["design"]["background_color"] = "#aB1234"
    original = pass_assets.store_image

    # Failure of a second upload must not create a campaign or publish the first upload.
    def failure(*args):
        raise HTTPException(503, "Storage unavailable")

    monkeypatch.setattr(pass_assets, "store_image", failure)
    assert (
        client.post(f"/api/v1/merchants/{mid}/pass-assets", content=image_data()).status_code == 503
    )
    assert client.get(path).json() == []
    monkeypatch.setattr(pass_assets, "store_image", original)
    camp = client.post(path, json=body).json()
    assert camp["design"]["background_color"] == "#aB1234"
    assert TestClient(app).get(asset_path).status_code == 200
    with SessionLocal() as db:
        assert db.query(models.PassDesign).filter_by(campaign_id=camp["id"]).count() == 1
        db.add(models.PassDesign(campaign_id=camp["id"]))
        with pytest.raises(IntegrityError):
            db.commit()
    draft = client.post(path, json={"type": "points_per_spend", "config": {}}).json()
    assert draft["lifecycle"] == "draft" and not draft["active"] and draft["design"]
    assert (
        client.post(
            f"/api/v1/campaigns/{draft['id']}/customers", json={"customer_ids": [cid]}
        ).status_code
        == 409
    )


@pytest.mark.parametrize("format", ["PNG", "JPEG", "WEBP"])
def test_upload_validates_content_and_normalizes_public_images(format):
    mid, _ = shop()
    asset = client.post(
        f"/api/v1/merchants/{mid}/pass-assets",
        content=image_data(format=format),
        headers={"Content-Type": "text/plain", "X-Filename": "../../private.key"},
    )
    assert asset.status_code == 201
    info = asset.json()
    assert info["content_type"] == "image/png" and info["url"].startswith("https://")
    public = "/api/v1/public/pass-assets/" + info["id"]
    assert TestClient(app).get(public).status_code == 404
    private = client.get(f"/api/v1/merchants/{mid}/pass-assets/{info['id']}/content")
    assert Image.open(io.BytesIO(private.content)).format == "PNG"
    assert client.delete(f"/api/v1/merchants/{mid}/pass-assets/{info['id']}").status_code == 200


@pytest.mark.parametrize(
    "content,status",
    [(b"", 413), (b"<svg></svg>", 422), (b"not-image", 422), (b"\x89PNG\r\n\x1a\n", 422)],
)
def test_upload_rejects_invalid_content(content, status):
    mid, _ = shop()
    assert (
        client.post(
            f"/api/v1/merchants/{mid}/pass-assets",
            content=content,
            headers={"Content-Type": "image/png"},
        ).status_code
        == status
    )


def test_upload_size_pixels_and_authorization(monkeypatch):
    mid, _ = shop()
    path = f"/api/v1/merchants/{mid}/pass-assets"
    assert TestClient(app).post(path, content=image_data()).status_code == 401
    monkeypatch.setattr(settings, "pass_asset_max_bytes", 50)
    assert client.post(path, content=image_data()).status_code == 413
    monkeypatch.setattr(settings, "pass_asset_max_bytes", 4194304)
    monkeypatch.setattr(settings, "pass_asset_max_pixels", 100)
    assert client.post(path, content=image_data()).status_code == 422


def test_tenant_resource_access_and_foreign_assets():
    mid, cid = shop()
    other, _ = shop()
    camp = create(mid, [cid])
    username = "tenant-" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(
            models.AdminUser(
                username=username,
                password_hash=hash_password("tenant-password"),
                role="sme_admin",
                merchant_id=other,
            )
        )
        db.commit()
    restricted = TestClient(app)
    token = restricted.post(
        "/api/v1/auth/login", json={"username": username, "password": "tenant-password"}
    ).json()["access_token"]
    restricted.headers["Authorization"] = "Bearer " + token
    payment_body = {
        "merchant_id": mid,
        "external_transaction_id": "denied",
        "amount": 20,
        "identifiers": {"customer_number": "C"},
    }
    assert TestClient(app).post("/api/v1/transactions", json=payment_body).status_code == 401
    assert restricted.post("/api/v1/transactions", json=payment_body).status_code == 403
    for path in [
        f"/campaigns/{camp['id']}",
        f"/campaigns/{camp['id']}/customers",
        f"/customers/{cid}/campaigns",
        f"/campaigns/{camp['id']}/customers/{cid}/passes",
        f"/merchants/{mid}/pass-assets/{camp['design']['logo_asset_id']}",
    ]:
        assert restricted.get("/api/v1" + path).status_code == 403
    assert (
        restricted.post(f"/api/v1/merchants/{mid}/pass-assets", content=image_data()).status_code
        == 403
    )
    assert (
        restricted.put(f"/api/v1/campaigns/{camp['id']}/design", json=camp["design"]).status_code
        == 403
    )
    assert (
        restricted.patch(
            f"/api/v1/campaigns/{camp['id']}/customers/{cid}", json={"status": "cancelled"}
        ).status_code
        == 403
    )
    foreign_design = design(client, other)
    assert (
        client.put(f"/api/v1/campaigns/{camp['id']}/design", json=foreign_design).status_code == 404
    )
    assert (
        client.get(f"/api/v1/campaigns/{camp['id']}").json()["design"]["logo_asset_id"]
        == camp["design"]["logo_asset_id"]
    )


def test_replace_retains_old_until_synced_then_collects_orphans():
    mid, cid = shop()
    camp = create(mid, [cid])
    old = camp["design"]["logo_asset_id"]
    replacement = design(client, mid)
    assert client.put(f"/api/v1/campaigns/{camp['id']}/design", json=replacement).status_code == 200
    assert TestClient(app).get(f"/api/v1/public/pass-assets/{old}").status_code == 200
    with SessionLocal() as db:
        asset = db.get(models.PassAsset, old)
        asset.retired_at = models._now() - timedelta(days=8)
        row = models.Pass(
            customer_id=cid, campaign_id=camp["id"], platform="google", updated_tag=2, synced_tag=1
        )
        db.add(row)
        db.commit()
        pass_assets.cleanup_assets(db)
        assert db.get(models.PassAsset, old)
        row.synced_tag = 2
        db.commit()
        pass_assets.cleanup_assets(db)
        assert db.get(models.PassAsset, old) is None
    assert TestClient(app).get(f"/api/v1/public/pass-assets/{old}").status_code == 404


def test_points_contract_is_deterministic_tenant_scoped_and_opaque(monkeypatch):
    monkeypatch.setattr(settings, "public_api_url", "https://wallet-api.example.com")
    mid, cid = shop()
    camp = create(mid, [cid])
    payment(mid)
    with SessionLocal() as db:
        customer = db.get(models.Customer, cid)
        customer.name = "Ana <Example>"
        customer.created_at = datetime(2024, 2, 1)
        customer.customer_code = "PRIVATE-CUSTOMER-CODE-92817"
        row = (
            db.query(models.CampaignEnrollment)
            .filter_by(campaign_id=camp["id"], customer_id=cid)
            .one()
        )
        row.enrolled_at = datetime(2026, 9, 1)
        db.commit()
        args = (db, customer.merchant, row.campaign, customer, row, row.campaign.design, "123")
        payload = build_points_pass(*args)
        assert payload == build_points_pass(*args)
        assert payload["cardTitle"]["defaultValue"]["value"] == customer.merchant.name
        assert payload["header"]["defaultValue"]["value"] == "Ana <Example>"
        assert payload["textModulesData"][0]["body"] == "2"
        assert payload["textModulesData"][1]["body"] == "feb 2024"
        assert payload["hexBackgroundColor"] == "#373839"
        assert payload["classId"].startswith("123.points_")
        assert payload["id"] == "123.enrollment_" + row.id.replace("-", "")
        assert "Casa Luis" not in json.dumps(payload)
        assert payload["logo"]["sourceUri"]["uri"].startswith(
            "https://wallet-api.example.com/api/v1/public/pass-assets/"
        )
        barcode = payload["barcode"]["value"]
        assert len(barcode) >= 40
        for private in (cid, row.id, customer.customer_code, customer.email):
            if private:
                assert private not in barcode
        other, _ = shop()
        with pytest.raises(ValueError, match="same merchant"):
            build_points_pass(db, db.get(models.Merchant, other), *args[2:])
    path = f"/api/v1/merchants/{mid}/enrollments/verify"
    assert TestClient(app).post(path, json={"token": barcode}).status_code == 401
    assert client.post(path, json={"token": barcode}).json()["customer_id"] == cid
    assert (
        client.post(
            f"/api/v1/merchants/{other}/enrollments/verify", json={"token": barcode}
        ).status_code
        == 404
    )
    client.patch(f"/api/v1/campaigns/{camp['id']}/customers/{cid}", json={"status": "cancelled"})
    assert client.post(path, json={"token": barcode}).status_code == 404


def test_migration_preserves_balances_membership_images_passes_and_is_idempotent(
    tmp_path, monkeypatch
):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    monkeypatch.setattr(database, "engine", engine)
    database.init_db()
    with Session(engine) as db:
        db.delete(db.get(models.SchemaMigration, VERSION))
        merchant = models.Merchant(name="Migration", logo_data=image_data())
        db.add(merchant)
        db.flush()
        customer = models.Customer(merchant_id=merchant.id, customer_code="M1", points_balance=21)
        db.add(customer)
        db.flush()
        a, b = [
            models.Campaign(
                merchant_id=merchant.id, type="points_per_spend", lifecycle="legacy", config={}
            )
            for _ in range(2)
        ]
        db.add_all([a, b])
        db.flush()
        db.add_all(
            [
                models.Movement(
                    customer_id=customer.id, campaign_id=a.id, type="earn", points_delta=3
                ),
                models.Movement(
                    customer_id=customer.id, campaign_id=b.id, type="earn", points_delta=5
                ),
            ]
        )
        row = models.Pass(
            customer_id=customer.id,
            campaign_id=a.id,
            platform="google",
            external_pass_id="123.existing",
        )
        db.add(row)
        db.commit()
        ids = merchant.id, customer.id, a.id, b.id, row.id
    # Recreate the actual old schema by dropping only newly introduced tables/columns.
    with engine.begin() as con:
        for trigger in ["enrollment_tenant_insert", "enrollment_tenant_update"]:
            con.execute(text(f"DROP TRIGGER {trigger}"))
        con.execute(text("DROP INDEX ix_pass_enrollment_id"))
        con.execute(
            text("""CREATE TABLE pass_previous (
            id VARCHAR PRIMARY KEY, customer_id VARCHAR NOT NULL REFERENCES customer(id),
            campaign_id VARCHAR REFERENCES campaign(id), platform VARCHAR NOT NULL,
            external_pass_id VARCHAR, status VARCHAR, auth_token VARCHAR,
            updated_tag INTEGER, synced_tag INTEGER, pass_type_id VARCHAR)""")
        )
        columns = "id, customer_id, campaign_id, platform, external_pass_id, status, auth_token, updated_tag, synced_tag, pass_type_id"
        con.execute(text(f'INSERT INTO pass_previous SELECT {columns} FROM "pass"'))
        con.execute(text('DROP TABLE "pass"'))
        con.execute(text('ALTER TABLE pass_previous RENAME TO "pass"'))
        for table, column in [
            ("customer", "name"),
            ("customer", "legacy_points_balance"),
            ("campaign", "description"),
            ("campaign", "lifecycle"),
        ]:
            con.execute(text(f'ALTER TABLE "{table}" DROP COLUMN {column}'))
        for table in ["pass_design", "pass_asset", "campaign_enrollment", "schema_migration"]:
            con.execute(text(f"DROP TABLE {table}"))
    database.init_db()
    migrate(engine)
    import sqlite3

    backups = list((tmp_path / "backups").glob("before-*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as original:
        assert original.execute("SELECT points_balance FROM customer").fetchone()[0] == 21
        assert "legacy_points_balance" not in [
            r[1] for r in original.execute("PRAGMA table_info(customer)")
        ]
        assert original.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with Session(engine) as db:
        assert db.query(models.CampaignEnrollment).count() == 2
        assert db.query(models.PassDesign).count() == 2
        customer = db.get(models.Customer, ids[1])
        assert customer.points_balance == 21 and customer.legacy_points_balance == 13
        assert db.get(models.Merchant, ids[0]).logo_data == image_data()
        assert db.get(models.Pass, ids[4]).external_pass_id == "123.existing"
        assert db.get(models.Pass, ids[4]).enrollment_id
        assert db.get(models.Pass, ids[4]).google_kind == "loyalty"
        for c in db.query(models.Campaign).all():
            assert (
                c.design.logo_asset_id
                and c.design.hero_asset_id
                and c.design.legacy_review_required
            )
            assert c.lifecycle == "legacy"
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()


def test_documented_example_matches_production_builder():
    root = Path(__file__).resolve().parents[2]
    example = runpy.run_path(str(root / "scripts/export_points_example.py"))["example_payload"]()
    documented = json.loads((root / "docs/examples/points-pass.json").read_text(encoding="utf-8"))
    assert example == documented


def test_failed_commit_never_publishes_assets_or_leaves_campaign(monkeypatch):
    mid, _ = shop()
    assets = design(client, mid)
    original = Session.commit

    def fail(db):
        if db.query(models.Campaign).filter_by(merchant_id=mid, name="Failed commit").first():
            raise RuntimeError("Synthetic persistence failure")
        original(db)

    monkeypatch.setattr(Session, "commit", fail)
    with pytest.raises(RuntimeError, match="Synthetic persistence failure"):
        client.post(
            f"/api/v1/merchants/{mid}/campaigns",
            json={
                "name": "Failed commit",
                "type": "points_per_spend",
                "config": {},
                "design": assets,
            },
        )
    monkeypatch.setattr(Session, "commit", original)
    assert client.get(f"/api/v1/merchants/{mid}/campaigns").json() == []
    assert (
        TestClient(app).get(f"/api/v1/public/pass-assets/{assets['logo_asset_id']}").status_code
        == 404
    )


def test_invalid_public_base_rejects_upload_without_persistence(monkeypatch):
    mid, _ = shop()
    monkeypatch.setattr(settings, "public_api_url", "http://localhost:8000")
    assert (
        client.post(f"/api/v1/merchants/{mid}/pass-assets", content=image_data()).status_code == 503
    )
    with SessionLocal() as db:
        assert db.query(models.PassAsset).filter_by(merchant_id=mid).count() == 0


@pytest.mark.parametrize("protected", [False, True])
def test_seed_creates_complete_designs_enrollments_and_is_repeatable(tmp_path, protected):
    root = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{tmp_path / 'seed.db'}",
        "AUTH_ENABLED": "true" if protected else "false",
        "BOOTSTRAP_ADMIN_USERNAME": "seed-test",
        "BOOTSTRAP_ADMIN_PASSWORD": "synthetic-seed-password" if protected else "",
        "PAN_HASH_SECRET": "synthetic-seed-hmac",
    }
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "seed.py"], cwd=root, env=env, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
    engine = create_engine(env["DATABASE_URL"])
    with Session(engine) as db:
        assert db.query(models.AdminUser).count() == (1 if protected else 0)
        assert db.query(models.Merchant).count() == 2
        assert db.query(models.CampaignEnrollment).count() == 2
        assert db.query(models.PassDesign).count() == 2
        assert db.query(models.Pass).count() == 0
        for row in db.query(models.PassDesign).all():
            assert row.logo_asset_id and row.hero_asset_id
    engine.dispose()
