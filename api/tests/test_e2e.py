from campaign_fixtures import create_campaign

"""End-to-end tests covering the four PRD scenarios.

Run:  pytest -v   (from the api/ directory)
Uses an in-memory-ish SQLite file created on startup.
"""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

# Use a temporary DB file for the test run
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["PAN_HASH_SECRET"] = "test-only-hmac-secret"
os.environ["AUTH_ENABLED"] = "true"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"

from app import models
from app.db import SessionLocal, init_db
from app.main import app  # noqa: E402
from app.services.security import hash_password

init_db()
with SessionLocal() as db:
    db.add(
        models.AdminUser(
            username="test-admin", password_hash=hash_password("test-password"), role="super_admin"
        )
    )
    db.commit()
client = TestClient(app)
login = client.post(
    "/api/v1/auth/login", json={"username": "test-admin", "password": "test-password"}
)
client.headers["Authorization"] = "Bearer " + login.json()["access_token"]


@pytest.fixture(scope="module")
def merchant_id():
    r = client.post("/api/v1/merchants", json={"name": "Test Shop"})
    assert r.status_code == 200
    return r.json()["id"]


def test_points_per_spend(merchant_id):
    # campaign: 1 point per 10 EUR
    created = create_campaign(
        client,
        f"/api/v1/merchants/{merchant_id}/campaigns",
        json={
            "type": "points_per_spend",
            "config": {"points": 1, "amount_unit": 10, "rounding": "floor"},
        },
    )
    # enroll a customer
    r = client.post(
        f"/api/v1/merchants/{merchant_id}/customers",
        json={
            "customer_code": "C1",
            "email": "c1@example.com",
            "campaign_ids": [created.json()["id"]],
        },
    )
    assert r.json()["customer"]["id"]

    # physical purchase 23.50 EUR -> 2 points
    r = client.post(
        "/api/v1/transactions",
        json={
            "merchant_id": merchant_id,
            "external_transaction_id": "tx-1",
            "source": "getnet",
            "amount": 23.50,
            "identifiers": {"email": "c1@example.com"},
        },
    )
    body = r.json()
    assert body["status"] == "matched"
    assert body["points_delta"] == 2
    assert body["new_balance"] == 2


def test_idempotency(merchant_id):
    # same external_transaction_id must not double-count
    r = client.post(
        "/api/v1/transactions",
        json={
            "merchant_id": merchant_id,
            "external_transaction_id": "tx-1",
            "source": "getnet",
            "amount": 23.50,
            "identifiers": {"email": "c1@example.com"},
        },
    )
    assert r.json()["status"] == "duplicate"


def test_ecommerce_purchase(merchant_id):
    r = client.post(
        "/api/v1/transactions",
        json={
            "merchant_id": merchant_id,
            "external_transaction_id": "tx-2",
            "source": "ecommerce",
            "amount": 50,
            "identifiers": {"email": "c1@example.com"},
        },
    )
    assert r.json()["status"] == "matched"
    assert r.json()["new_balance"] == 7  # 2 + 5


def test_unmatched(merchant_id):
    r = client.post(
        "/api/v1/transactions",
        json={
            "merchant_id": merchant_id,
            "external_transaction_id": "tx-3",
            "source": "getnet",
            "amount": 30,
            "identifiers": {"email": "nobody@example.com"},
        },
    )
    assert r.json()["status"] == "unmatched"


def test_coupon(merchant_id):
    r = client.post(
        f"/api/v1/merchants/{merchant_id}/customers",
        json={"customer_code": "C2", "email": "c2@example.com"},
    )
    cid = r.json()["customer"]["id"]
    r = client.post(
        f"/api/v1/merchants/{merchant_id}/coupons", json={"customer_id": cid, "amount": 5}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "issued"


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from app.services.loyalty import _points_for_spend
from app.services.security import hash_pan


def shop():
    mid = client.post("/api/v1/merchants", json={"name": "Edge shop"}).json()["id"]
    cid = client.post(
        f"/api/v1/merchants/{mid}/customers",
        json={
            "customer_code": "C",
            "email": "edge@example.com",
            "card_hash": hash_pan("4111111111111111"),
        },
    ).json()["customer"]["id"]
    return mid, cid


def payment(mid, **kwargs):
    payload = {
        "merchant_id": mid,
        "external_transaction_id": str(uuid4()),
        "amount": 20,
        "identifiers": {"customer_number": "C"},
    }
    payload.update(kwargs)
    return client.post("/api/v1/transactions", json=payload)


@pytest.mark.parametrize(
    "mode,amount,expected",
    [("floor", 0.3, 3), ("ceil", 0.31, 4), ("round", 0.25, 3), ("floor", 0, 0)],
)
def test_decimal_rounding(mode, amount, expected):
    assert (
        _points_for_spend({"points": 1, "amount_unit": 0.1, "rounding": mode}, amount) == expected
    )


def test_stamps_are_per_campaign_not_points():
    mid, cid = shop()
    for kind, config in [
        ("points_per_spend", {"points": 7, "amount_unit": 1}),
        ("interaction", {"interactions_required": 2, "reward_description": "Free coffee"}),
        ("interaction", {"interactions_required": 3, "reward_description": "Free tea"}),
    ]:
        assert (
            create_campaign(
                client, f"/api/v1/merchants/{mid}/campaigns", json={"type": kind, "config": config}
            ).status_code
            == 200
        )
    for _ in range(3):
        assert payment(mid, amount=1).status_code == 200
    movements = client.get(f"/api/v1/customers/{cid}/movements").json()
    assert len([m for m in movements if m["type"] == "interaction"]) == 6
    assert sorted(m["description"] for m in movements if m["type"] == "reward") == [
        "Free coffee",
        "Free tea",
    ]
    assert client.get(f"/api/v1/customers/{cid}").json()["points_balance"] == 21


def test_coupon_redemption_and_duplicate():
    mid, cid = shop()
    for amount in (5, 10):
        assert (
            client.post(
                f"/api/v1/merchants/{mid}/coupons", json={"customer_id": cid, "amount": amount}
            ).status_code
            == 200
        )
    key = str(uuid4())
    assert payment(mid, amount=5, external_transaction_id=key).json()["status"] == "matched"
    assert payment(mid, amount=5, external_transaction_id=key).json()["status"] == "duplicate"
    coupons = client.get(f"/api/v1/merchants/{mid}/coupons").json()
    assert sorted(c["status"] for c in coupons) == ["issued", "redeemed"]
    movements = client.get(f"/api/v1/customers/{cid}/movements").json()
    assert len([m for m in movements if m["type"] == "coupon_redeemed"]) == 1


def test_matching_priority_and_card_hash():
    mid, cid = shop()
    other = client.post(
        f"/api/v1/merchants/{mid}/customers",
        json={"customer_code": "other", "email": "other@example.com"},
    ).json()["customer"]["id"]
    assert (
        payment(
            mid, identifiers={"card_hash": hash_pan("4111111111111111"), "customer_number": "other"}
        ).json()["customer_id"]
        == cid
    )
    assert (
        payment(
            mid,
            identifiers={
                "card_hash": "a" * 64,
                "customer_number": "other",
                "email": "edge@example.com",
            },
        ).json()["customer_id"]
        == other
    )
    assert (
        payment(mid, identifiers={"email": "unknown@example.com"}).json()["status"] == "unmatched"
    )
    response = payment(mid, identifiers={"card_hash": "4111111111111111"})
    assert response.status_code == 422
    assert "4111111111111111" not in response.text


@pytest.mark.parametrize(
    "body",
    [
        {"type": "bogus", "config": {}},
        {"type": "points_per_spend", "config": {"amount_unit": 0}},
        {"type": "interaction", "config": {"interactions_required": 0, "reward_description": "x"}},
    ],
)
def test_invalid_campaign(body):
    mid, _ = shop()
    assert (
        create_campaign(client, f"/api/v1/merchants/{mid}/campaigns", json=body).status_code == 422
    )


def test_invalid_payment_and_enrollment():
    mid, cid = shop()
    assert payment(mid, amount=-1).status_code == 422
    assert payment(mid, amount=0.001).status_code == 422
    assert payment("unknown").status_code == 404
    assert (
        client.post(f"/api/v1/merchants/{mid}/customers", json={"customer_code": "C"}).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/merchants/{mid}/coupons", json={"customer_id": cid, "amount": -1}
        ).status_code
        == 422
    )
    mid2, _ = shop()
    assert (
        client.post(
            f"/api/v1/merchants/{mid2}/coupons", json={"customer_id": cid, "amount": 5}
        ).status_code
        == 404
    )
    client.patch(f"/api/v1/merchants/{mid}", json={"status": "inactive"})
    assert payment(mid).status_code == 409


def test_concurrent_ingestion():
    mid, cid = shop()
    create_campaign(
        client,
        f"/api/v1/merchants/{mid}/campaigns",
        json={"type": "points_per_spend", "config": {"points": 1, "amount_unit": 1}},
    )
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: payment(mid, external_transaction_id=key), range(4)))
    assert sorted(r.json()["status"] for r in responses) == [
        "duplicate",
        "duplicate",
        "duplicate",
        "matched",
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: payment(mid), range(4)))
    assert all(r.status_code == 200 for r in responses)
    assert client.get(f"/api/v1/customers/{cid}").json()["points_balance"] == 100


def test_auth_roles_language_and_logout(expect_anonymous=False):
    anon = TestClient(app)
    assert anon.get("/api/v1/merchants").status_code == (200 if expect_anonymous else 401)
    assert (
        anon.post(
            "/api/v1/auth/login", json={"username": "test-admin", "password": "wrong"}
        ).status_code
        == 401
    )
    mid, cid = shop()
    other_mid, other_cid = shop()
    username = str(uuid4())
    with SessionLocal() as db:
        db.add(
            models.AdminUser(
                username=username,
                password_hash=hash_password("sme-password"),
                role="sme_admin",
                merchant_id=mid,
            )
        )
        db.commit()
    token = anon.post(
        "/api/v1/auth/login", json={"username": username, "password": "sme-password"}
    ).json()["access_token"]
    anon.headers["Authorization"] = f"Bearer {token}"
    assert [m["id"] for m in anon.get("/api/v1/merchants").json()] == [mid]
    assert anon.get(f"/api/v1/customers/{other_cid}").status_code == 403
    assert anon.get(f"/api/v1/merchants/{other_mid}/customers").status_code == 403
    assert anon.get("/api/v1/settings/wallet").status_code == 403
    assert anon.post("/api/v1/merchants", json={"name": "forbidden"}).status_code == 403
    assert anon.patch("/api/v1/users/me", json={"language": "en"}).json()["language"] == "en"
    assert anon.get("/api/v1/users/me").json()["language"] == "en"
    assert anon.post("/api/v1/auth/logout").status_code == 200
    assert anon.get("/api/v1/users/me").status_code == 401


def test_docs_and_openapi():
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_unmatched_duplicate_and_merchant_isolation():
    mid, cid = shop()
    other_mid = client.post("/api/v1/merchants", json={"name": "Empty merchant"}).json()["id"]
    key = str(uuid4())
    assert payment(other_mid, external_transaction_id=key).json()["status"] == "unmatched"
    assert payment(other_mid, external_transaction_id=key).json()["status"] == "duplicate"
    response = payment(mid, external_transaction_id=key)
    assert response.status_code == 409
    assert cid not in response.text
    assert (
        payment(
            other_mid,
            identifiers={"card_hash": hash_pan("4111111111111111"), "email": "edge@example.com"},
        ).json()["status"]
        == "unmatched"
    )


def test_inactive_campaign_and_dni_fallback():
    mid, cid = shop()
    create_campaign(
        client,
        f"/api/v1/merchants/{mid}/campaigns",
        json={"type": "points_per_spend", "config": {"amount_unit": 1}, "active": False},
    )
    other = client.post(
        f"/api/v1/merchants/{mid}/customers", json={"customer_code": "D", "dni": "TEST-DNI"}
    ).json()["customer"]["id"]
    result = payment(
        mid, identifiers={"customer_number": "unknown", "email": "unknown", "dni": "TEST-DNI"}
    ).json()
    assert result["customer_id"] == other
    assert result["points_delta"] == 0
    assert client.get(f"/api/v1/customers/{cid}/movements").json() == []
