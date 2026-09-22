"""Requested open access mode and customer date/custom pass fields."""

import io
import json
import zipfile
from datetime import datetime

import pytest
from campaign_fixtures import design
from fastapi.testclient import TestClient
from test_e2e import SessionLocal, client
from test_wallet import wallet_config as wallet_fixture

from app import models as m
from app.config import settings
from app.main import app
from app.services.points_pass import build_points_pass, format_customer_since

wallet_config = wallet_fixture


def test_public_api_keeps_admin_login_private_and_allows_business_operations(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    public = TestClient(app)
    assert public.get("/api/v1/users/me").status_code == 401
    assert public.post("/api/v1/auth/login").status_code == 422
    assert public.post("/api/v1/auth/logout").status_code == 401
    assert public.patch("/api/v1/users/me", json={"language": "en"}).status_code == 401
    assert public.get("/api/v1/settings/wallet").status_code == 200
    mid = public.post("/api/v1/merchants", json={"name": "Public test shop"}).json()["id"]
    configured = design(public, mid)
    configured.update(
        points_label="Saldo",
        member_since_label="Socio desde",
        barcode_alternate_text="Presenta este QR",
    )
    response = public.post(
        f"/api/v1/merchants/{mid}/campaigns",
        json={
            "name": "Open rewards",
            "type": "points_per_spend",
            "config": {},
            "design": configured,
        },
    )
    assert response.status_code == 200, response.text
    campaign = response.json()
    customer = public.post(
        f"/api/v1/merchants/{mid}/customers",
        json={
            "name": "Date fixture",
            "customer_code": "OPEN-C",
            "joined_on": "2020-01-17",
            "campaign_ids": [campaign["id"]],
        },
    ).json()["customer"]
    assert customer["created_at"].startswith("2020-01-17")
    assert (
        public.post(
            "/api/v1/transactions",
            json={
                "merchant_id": mid,
                "external_transaction_id": "public-payment",
                "amount": 30,
                "identifiers": {"customer_number": "OPEN-C"},
            },
        ).json()["points_delta"]
        == 3
    )
    with SessionLocal() as db:
        row = db.query(m.CampaignEnrollment).filter_by(customer_id=customer["id"]).one()
        payload = build_points_pass(
            db, row.customer.merchant, row.campaign, row.customer, row, row.campaign.design, "123"
        )
        assert payload["textModulesData"] == [
            {"id": "puntos", "header": "Saldo", "body": "3"},
            {"id": "cliente_desde", "header": "Socio desde", "body": "ene 2020"},
        ]
        assert payload["barcode"]["alternateText"] == "Presenta este QR"
    assert (
        public.get(f"/api/v1/customers/{customer['id']}").json()["created_at"]
        == customer["created_at"]
    )
    assert (
        public.get(f"/api/v1/campaigns/{campaign['id']}").json()["design"]["points_label"]
        == "Saldo"
    )
    schema = public.get("/openapi.json").json()
    assert "HTTPBearer" in schema["components"]["securitySchemes"]
    for url, path in schema["paths"].items():
        for operation in path.values():
            if isinstance(operation, dict):
                assert bool(operation.get("security")) == (
                    url in ("/api/v1/users/me", "/api/v1/auth/logout")
                )
    assert public.post(f"/api/v1/campaigns/{campaign['id']}/archive").status_code == 200
    assert public.delete(f"/api/v1/customers/{customer['id']}").status_code == 200
    assert public.delete(f"/api/v1/merchants/{mid}/campaigns/{campaign['id']}").status_code == 200
    preview = public.get(f"/api/v1/merchants/{mid}/deletion-preview").json()
    assert (
        public.request(
            "DELETE", f"/api/v1/merchants/{mid}", json={"revision": preview["revision"]}
        ).status_code
        == 200
    )
    monkeypatch.setattr(settings, "auth_enabled", True)
    assert public.get("/api/v1/users/me").status_code == 401
    assert public.get("/openapi.json").json()["paths"]["/api/v1/transactions"]["post"]["security"]


def test_public_api_still_validates_sessions_roles_expiry_and_logout(monkeypatch):
    from test_e2e import test_auth_roles_language_and_logout

    monkeypatch.setattr(settings, "auth_enabled", False)
    browser = TestClient(app)
    assert (
        browser.post(
            "/api/v1/auth/login", json={"username": "test-admin", "password": "wrong"}
        ).status_code
        == 401
    )
    login = browser.post(
        "/api/v1/auth/login", json={"username": "test-admin", "password": "test-password"}
    ).json()
    assert login["access_token"] and login["user"]["public_access"] is False
    browser.headers["Authorization"] = "Bearer " + login["access_token"]
    assert browser.get("/api/v1/users/me").status_code == 200
    assert browser.post("/api/v1/auth/logout").status_code == 200
    assert browser.get("/api/v1/users/me").status_code == 401
    assert browser.get("/api/v1/merchants").status_code == 401
    # Repeat the complete SME isolation/language/logout regression in API-open mode.
    test_auth_roles_language_and_logout(expect_anonymous=True)


def test_public_apple_download_and_callbacks_need_no_tokens(wallet_config, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    from test_wallet import shop

    mid, cid = shop()
    with SessionLocal() as db:
        row = db.query(m.Pass).filter_by(customer_id=cid, platform="apple").one()
        serial, pass_type = row.id, row.pass_type_id
        row.customer.created_at = datetime(2021, 12, 3)
        db.commit()
    public = TestClient(app)
    downloaded = public.get(f"/api/v1/passes/apple/{serial}.pkpass")
    assert downloaded.status_code == 200
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as bundle:
        fields = json.loads(bundle.read("pass.json"))["storeCard"]["secondaryFields"]
        assert next(f for f in fields if f["key"] == "customer_since")["value"] == "dic 2021"
    register = f"/api/v1/wallet/apple/v1/devices/public-device/registrations/{pass_type}/{serial}"
    assert public.post(register, json={"pushToken": "abcdef12"}).status_code == 201
    assert public.get(f"/api/v1/wallet/apple/v1/passes/{pass_type}/{serial}").status_code == 200
    assert public.delete(register).status_code == 200
    monkeypatch.setattr(settings, "auth_enabled", True)
    assert public.get(f"/api/v1/passes/apple/{serial}.pkpass").status_code == 401


@pytest.mark.parametrize(
    "month,es,en",
    [
        (1, "ene", "Jan"),
        (2, "feb", "Feb"),
        (3, "mar", "Mar"),
        (4, "abr", "Apr"),
        (5, "may", "May"),
        (6, "jun", "Jun"),
        (7, "jul", "Jul"),
        (8, "ago", "Aug"),
        (9, "sep", "Sep"),
        (10, "oct", "Oct"),
        (11, "nov", "Nov"),
        (12, "dic", "Dec"),
    ],
)
def test_month_exactly_three_letters(month, es, en):
    assert format_customer_since(datetime(2020, month, 1), "es-ES") == es + " 2020"
    assert format_customer_since(datetime(2020, month, 1), "en-US") == en + " 2020"


def test_future_customer_joining_date_rejected():
    mid = client.post("/api/v1/merchants", json={"name": "Date validation"}).json()["id"]
    assert (
        client.post(
            f"/api/v1/merchants/{mid}/customers",
            json={"customer_code": "FUTURE", "joined_on": "2999-01-01"},
        ).status_code
        == 422
    )
