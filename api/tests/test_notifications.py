"""Notification API, outbox, provider protocol and payment atomicity regressions."""

import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from test_e2e import SessionLocal, client
from test_e2e import models as m
from test_wallet import wallet_config  # noqa: F401

from app.config import settings
from app.routers.auth import token_hash
from app.schemas.notifications import NotificationContent
from app.services import notifications as n
from app.services import passes
from app.services.notification_providers import (
    AppleWalletNotificationProvider,
    GoogleWalletNotificationProvider,
    apple_message_fields,
)


@pytest.fixture
def audience(monkeypatch):
    calls = []

    class Provider:
        def send(self, db, row, delivery, config):
            calls.append((row.id, delivery.payload))
            return "success", None

    monkeypatch.setattr(n, "PROVIDERS", {"apple": Provider(), "google": Provider()})
    monkeypatch.setattr(passes, "update_customer_pass", lambda *args: True)
    with SessionLocal() as db:
        merchant = m.Merchant(name="Notification cafe")
        db.add(merchant)
        db.flush()
        campaign = m.Campaign(
            merchant_id=merchant.id,
            name="Coffee Rewards",
            type="points_per_spend",
            lifecycle="ready",
            active=True,
            config={"points": 1, "amount_unit": 1},
        )
        db.add(campaign)
        db.flush()
        customer_ids, pass_ids = [], []
        for i in range(2):
            customer = m.Customer(
                merchant_id=merchant.id,
                name=f"Customer {i}",
                customer_code=f"N{i}",
                email=f"n{i}@example.com",
                points_balance=10,
            )
            db.add(customer)
            db.flush()
            member = m.CampaignEnrollment(customer_id=customer.id, campaign_id=campaign.id)
            db.add(member)
            db.flush()
            customer_ids.append(customer.id)
            db.add(
                m.Movement(
                    customer_id=customer.id, campaign_id=campaign.id, type="earn", points_delta=10
                )
            )
            for provider in ("apple", "google") if i == 0 else ("google",):
                row = m.Pass(
                    customer_id=customer.id,
                    campaign_id=campaign.id,
                    enrollment_id=member.id,
                    platform=provider,
                    google_kind="generic",
                    external_pass_id=f"123.{uuid4().hex}",
                    pass_type_id="pass.example.loyalty",
                )
                db.add(row)
                db.flush()
                pass_ids.append(row.id)
        cfg = passes._wallet_config(db)
        if not cfg:
            cfg = m.WalletConfig()
            db.add(cfg)
            db.flush()
        previous = cfg.apple_enabled, cfg.google_enabled
        cfg.apple_enabled = cfg.google_enabled = True
        db.commit()
        result = SimpleNamespace(
            mid=merchant.id,
            campaign=campaign.id,
            customers=customer_ids,
            passes=pass_ids,
            calls=calls,
        )
    yield result
    with SessionLocal() as db:
        cfg = passes._wallet_config(db)
        cfg.apple_enabled, cfg.google_enabled = previous
        db.commit()


def draft(a, **changes):
    return {
        "target_type": "campaign",
        "campaign_id": a.campaign,
        "title": "{{campaignName}}",
        "message": "{{customerName}}, you have {{currentPoints}} points.",
        **changes,
    }


def prepare(a, **changes):
    body = draft(a, **changes)
    response = client.post(f"/api/v1/merchants/{a.mid}/notifications/preview", json=body)
    assert response.status_code == 200, response.text
    preview = response.json()
    return {
        **body,
        "request_id": str(uuid4()),
        "expected_recipients": preview["estimated_recipients"],
        "audience_revision": preview["audience_revision"],
    }


def send(a, body=None):
    return client.post(f"/api/v1/merchants/{a.mid}/notifications", json=body or prepare(a))


def detail(a, response):
    return client.get(f"/api/v1/merchants/{a.mid}/notifications/{response.json()['id']}").json()


def test_campaign_send_personalizes_deduplicates_holders_and_audits(audience):
    a = audience
    body = prepare(a, url="https://example.com/rewards", preview_text="Balance: {{currentPoints}}")
    response = send(a, body)
    assert response.status_code == 202, response.text
    row = detail(a, response)
    assert row["estimated_recipients"] == 2 and row["pass_count"] == 3
    assert row["status"] == "success" and row["sender_name"] == "test-admin"
    assert row["title"] == "{{campaignName}}"
    assert len(a.calls) == 3
    assert all(p["title"] == "Coffee Rewards" for _, p in a.calls)
    assert "Customer 1, you have 10 points." in [p["message"] for _, p in a.calls]
    assert all(p["preview_text"] == "Balance: 10" for _, p in a.calls)
    assert row["delivery_counts"] == {"success": 3}


def test_idempotency_and_conflicting_reuse(audience):
    a = audience
    body = prepare(a)
    first = send(a, body)
    assert send(a, body).json()["id"] == first.json()["id"]
    assert len(a.calls) == 3
    assert send(a, {**body, "message": "different"}).status_code == 409


def test_concurrent_requests_reserve_once(audience):
    a = audience
    body = prepare(a)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: send(a, body), range(3)))
    assert [r.status_code for r in results] == [202, 202, 202]
    assert len({r.json()["id"] for r in results}) == 1
    assert len(a.calls) == 3


@pytest.mark.parametrize("query", ["Customer 0", "n0@example.com", "pass_id", "qr"])
def test_individual_search_and_summary(audience, query):
    a = audience
    with SessionLocal() as db:
        row = db.get(m.Pass, a.passes[0])
        query = (
            row.id
            if query == "pass_id"
            else row.enrollment.barcode_token
            if query == "qr"
            else query
        )
    response = client.get(f"/api/v1/merchants/{a.mid}/notification-passes", params={"q": query})
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["customer_name"] == "Customer 0"
    assert response.json()["items"][0]["points_balance"] == 10
    body = prepare(a, target_type="pass", campaign_id=None, pass_id=a.passes[0])
    assert detail(a, send(a, body))["pass_count"] == 1


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,test",
        "https://user:pass@example.com",
        "https://example.com/\nbad",
        "https://example.com:bad",
        "https://example.com/{{customerName}}",
    ],
)
def test_invalid_links_rejected(audience, url):
    response = client.post(
        f"/api/v1/merchants/{audience.mid}/notifications/preview", json=draft(audience, url=url)
    )
    assert response.status_code == 422


@pytest.mark.parametrize("message", [" ", "{{secret}}", "{{customerName", "{{amount}}", "x" * 2001])
def test_invalid_templates_rejected(audience, message):
    response = client.post(
        f"/api/v1/merchants/{audience.mid}/notifications/preview",
        json=draft(audience, message=message),
    )
    assert response.status_code == 422


def test_empty_long_and_mass_audiences(audience, monkeypatch):
    a = audience
    monkeypatch.setattr(settings, "notification_mass_threshold", 1)
    body = prepare(a, message="x" * 250)
    preview = client.post(
        f"/api/v1/merchants/{a.mid}/notifications/preview", json=draft(a, message="x" * 250)
    ).json()
    assert set(preview["warnings"]) == {"mass_send", "long_message"}
    assert send(a, body).status_code == 422
    assert send(a, {**body, "confirm_mass_send": True}).status_code == 202
    with SessionLocal() as db:
        db.query(m.Pass).filter(m.Pass.id.in_(a.passes)).update(
            {"status": "revoked"}, synchronize_session=False
        )
        db.commit()
    empty = client.post(f"/api/v1/merchants/{a.mid}/notifications/preview", json=draft(a)).json()
    assert empty["warnings"] == ["no_passes"]
    assert send(a, {**body, "request_id": str(uuid4())}).status_code == 422


def test_audience_changes_require_new_confirmation(audience):
    a = audience
    body = prepare(a)
    with SessionLocal() as db:
        db.get(m.Pass, a.passes[0]).status = "revoked"
        db.commit()
    # Same number of holders, different passes: count alone must not suffice.
    assert send(a, body).status_code == 409
    assert not a.calls


def test_rate_limits_are_durable_and_visible(audience, monkeypatch):
    a = audience
    monkeypatch.setattr(settings, "notification_passes_per_day", 1)
    assert detail(a, send(a))["status"] == "success"
    limited = detail(a, send(a))
    assert limited["status"] == "skipped"
    assert {d["reason"] for d in limited["deliveries"]} == {"daily_pass_limit"}
    assert len(a.calls) == 3
    monkeypatch.setattr(settings, "notification_sends_per_hour", 2)
    assert send(a).status_code == 429


def test_provider_partial_failure_and_uncertain_not_retried(audience, monkeypatch):
    a = audience

    class Provider:
        def send(self, db, row, delivery, config):
            if row.platform == "google":
                raise httpx.ReadTimeout("secret provider URL")
            return "success", None

    monkeypatch.setattr(n, "PROVIDERS", {"apple": Provider(), "google": Provider()})
    row = detail(a, send(a))
    assert row["status"] == "partial"
    assert row["delivery_counts"] == {"success": 1, "unknown": 2}
    assert "secret" not in json.dumps(row)
    monkeypatch.setattr(n, "PROVIDERS", {})  # no retry may reach a provider
    n.dispatch_pending()
    assert (
        client.get(f"/api/v1/merchants/{a.mid}/notifications/{row['id']}").json()["delivery_counts"]
        == row["delivery_counts"]
    )


def test_history_filters_and_tenant_security(audience, monkeypatch):
    a = audience
    response = send(a)
    with SessionLocal() as db:
        other = m.Merchant(name="Other merchant")
        db.add(other)
        db.flush()
        user = m.AdminUser(
            username=str(uuid4()), password_hash="unused", role="sme_admin", merchant_id=other.id
        )
        db.add(user)
        db.flush()
        token = str(uuid4())
        db.add(
            m.AdminSession(
                token_hash=token_hash(token),
                user_id=user.id,
                expires_at=m._now() + timedelta(hours=1),
            )
        )
        db.commit()
        other_id = other.id
    header = {"Authorization": "Bearer " + token}
    monkeypatch.setattr(settings, "auth_enabled", False)
    for path in [
        "notification-campaigns",
        "notification-passes",
        "notifications",
        f"notifications/{response.json()['id']}",
    ]:
        assert client.get(f"/api/v1/merchants/{a.mid}/{path}", headers=header).status_code == 403
    assert (
        client.post(
            f"/api/v1/merchants/{a.mid}/notifications", json=prepare(a), headers=header
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/v1/merchants/{other_id}/notifications/{response.json()['id']}", headers=header
        ).status_code
        == 404
    )
    today = m._now().date().isoformat()
    base = f"/api/v1/merchants/{a.mid}/notifications"
    assert (
        client.get(
            base,
            params={
                "campaign_id": a.campaign,
                "status": "success",
                "date_from": today,
                "date_to": today,
            },
        ).json()["total"]
        == 1
    )
    assert client.get(base, params={"status": "failed"}).json()["total"] == 0
    assert client.get(base, params={"date_from": "2099-01-01", "date_to": today}).status_code == 422


def payment_body(a, **changes):
    return {
        "merchant_id": a.mid,
        "external_transaction_id": str(uuid4()),
        "amount": "25.00",
        "identifiers": {"customer_number": "N0"},
        **changes,
    }


def test_payment_opt_in_is_atomic_personalized_and_idempotent(audience):
    a = audience
    body = payment_body(a)
    assert client.post("/api/v1/transactions", json=body).json()["notification_id"] is None
    assert not a.calls
    body = payment_body(
        a,
        send_notification=True,
        notification={
            "title": "Purchase registered",
            "message": "€{{amount}} / {{pointsEarned}} earned / {{currentPoints}} available",
        },
    )
    response = client.post("/api/v1/transactions", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["points_delta"] == 25
    assert len(a.calls) == 2
    assert {payload["message"] for _, payload in a.calls} == {"€25.00 / 25 earned / 60 available"}
    duplicate = client.post("/api/v1/transactions", json=body).json()
    assert (
        duplicate["status"] == "duplicate"
        and duplicate["notification_id"] == response.json()["notification_id"]
    )
    assert len(a.calls) == 2


def test_payment_failure_does_not_lose_payment_and_unmatched_is_audited(audience, monkeypatch):
    a = audience

    class Failed:
        def send(self, *args):
            return "failed", "provider_rejected"

    monkeypatch.setattr(n, "PROVIDERS", {"apple": Failed(), "google": Failed()})
    content = {"title": "Purchase", "message": "{{currentPoints}}"}
    response = client.post(
        "/api/v1/transactions", json=payment_body(a, send_notification=True, notification=content)
    )
    assert response.json()["new_balance"] == 35
    row = client.get(
        f"/api/v1/merchants/{a.mid}/notifications/{response.json()['notification_id']}"
    ).json()
    assert row["status"] == "failed"
    response = client.post(
        "/api/v1/transactions",
        json=payment_body(a, identifiers={}, send_notification=True, notification=content),
    )
    assert response.json()["status"] == "unmatched"
    assert response.json()["notification_status"] == "skipped"


def test_payment_outbox_failure_rolls_back_accrual(audience, monkeypatch):
    a = audience

    def fail(*args, **kwargs):
        raise HTTPException(503, "Outbox unavailable")

    monkeypatch.setattr(n, "enqueue_payment", fail)
    body = payment_body(
        a, send_notification=True, notification={"title": "Purchase", "message": "Thanks"}
    )
    assert client.post("/api/v1/transactions", json=body).status_code == 503
    with SessionLocal() as db:
        assert db.get(m.Customer, a.customers[0]).points_balance == 10
        assert (
            not db.query(m.Transaction)
            .filter_by(external_transaction_id=body["external_transaction_id"])
            .first()
        )


def test_outbox_recovers_only_unattempted_deliveries(audience, monkeypatch):
    a = audience
    real_dispatch = n.dispatch_pending
    monkeypatch.setattr(n, "dispatch_pending", lambda: None)
    response = send(a)
    assert not a.calls
    with SessionLocal() as db:
        delivery = (
            db.query(m.NotificationDelivery)
            .filter_by(notification_id=response.json()["id"])
            .first()
        )
        delivery.status = "sending"
        delivery.attempted_at = m._now() - timedelta(minutes=11)
        db.commit()
    real_dispatch()
    assert len(a.calls) == 2
    assert detail(a, response)["delivery_counts"] == {"success": 2, "unknown": 1}


@pytest.mark.parametrize("kind", ["generic", "loyalty"])
def test_google_add_message_wire_contract(audience, monkeypatch, kind):
    recorded = []

    def transport(request):
        recorded.append(request)
        return httpx.Response(200, json={})

    client_class = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: client_class(transport=httpx.MockTransport(transport), **kw)
    )
    monkeypatch.setattr(
        passes,
        "_google_credentials",
        lambda _: SimpleNamespace(token="test-token", refresh=lambda _: None),
    )
    with SessionLocal() as db:
        row = db.get(m.Pass, audience.passes[1])
        row.google_kind = kind
        delivery = m.NotificationDelivery(
            id="unique-message",
            payload={
                "title": "Title",
                "message": '<script>& "Hi"',
                "url": "https://example.com/?a=1&b=2",
                "preview_text": "More",
            },
        )
        assert GoogleWalletNotificationProvider().send(db, row, delivery, {}) == ("success", None)
        assert recorded[0].method == "GET"
        assert str(recorded[-1].url).endswith(f"/{kind}Object/{row.external_pass_id}/addMessage")
        data = json.loads(recorded[-1].content)["message"]
        assert data["id"] == "unique-message" and data["messageType"] == "TEXT_AND_NOTIFY"
        assert "<script>" not in data["body"] and "&lt;script&gt;" in data["body"]
        assert '<a href="https://example.com/?a=1&amp;b=2">' in data["body"]


def test_apple_signed_update_and_persistent_message(audience, wallet_config, monkeypatch):  # noqa: F811
    a = audience
    config = wallet_config[0]
    pushes = []

    def push(db, row, config):
        with SessionLocal() as other:
            pushes.append(other.get(m.PassNotificationState, row.id).payload)
        return True

    monkeypatch.setattr(passes, "push_apple", push)
    with SessionLocal() as db:
        row = db.get(m.Pass, a.passes[0])
        assert apple_message_fields(db, row)[0]["value"] == ""
        db.add(
            m.DeviceRegistration(
                pass_id=row.id, device_id="notification-device", push_token="test-token"
            )
        )
        db.commit()
        delivery = m.NotificationDelivery(
            payload={
                "title": "News",
                "message": "245 points",
                "preview_text": "Enjoy",
                "url": "https://example.com/reward",
            }
        )
        assert AppleWalletNotificationProvider().send(db, row, delivery, config) == (
            "success",
            None,
        )
        assert len(pushes) == 1
        row.customer.points_balance += 10
        bundle = passes.apple_bundle(db, row.customer, row, config)
        data = json.loads(zipfile.ZipFile(io.BytesIO(bundle)).read("pass.json"))
        fields = {f["key"]: f for f in data["storeCard"]["backFields"]}
        assert fields["notification"]["value"] == "News\n245 points"
        assert fields["notification"]["changeMessage"] == "%@"
        assert fields["notification_url"]["value"] == "https://example.com/reward"


def test_unknown_placeholder_is_never_silently_erased():
    with pytest.raises(ValueError):
        NotificationContent(title="News", message="Hello {{unknown}}")


@pytest.mark.parametrize("owned_message", [True, False])
def test_google_retains_only_nine_old_messages_without_deleting_external_content(
    audience, monkeypatch, owned_message
):
    a = audience
    response = send(a)
    with SessionLocal() as db:
        delivery = (
            db.query(m.NotificationDelivery)
            .filter_by(notification_id=response.json()["id"], pass_id=a.passes[1])
            .one()
        )
        message_id = delivery.id
    messages = [{"id": f"external-{i}", "body": str(i)} for i in range(9)]
    messages.append({"id": message_id if owned_message else "external-10", "body": "Old"})
    recorded = []

    def transport(request):
        recorded.append(request)
        return httpx.Response(200, json={"messages": messages} if request.method == "GET" else {})

    client_class = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: client_class(transport=httpx.MockTransport(transport), **kw)
    )
    monkeypatch.setattr(
        passes,
        "_google_credentials",
        lambda _: SimpleNamespace(token="test-token", refresh=lambda _: None),
    )
    with SessionLocal() as db:
        row = db.get(m.Pass, a.passes[1])
        new = m.NotificationDelivery(
            id="new-message", payload={"title": "News", "message": "Hello"}
        )
        result = GoogleWalletNotificationProvider().send(db, row, new, {})
    if owned_message:
        assert result == ("success", None)
        assert [r.method for r in recorded] == ["GET", "PATCH", "POST"]
        assert json.loads(recorded[1].content)["messages"] == messages[:9]
    else:
        assert result == ("failed", "provider_message_limit")
        assert [r.method for r in recorded] == ["GET"]


@pytest.mark.parametrize(
    "status, expected",
    [
        (429, ("failed", "provider_rate_limit")),
        (503, ("unknown", "delivery_uncertain")),
        (400, ("failed", "provider_rejected")),
    ],
)
def test_google_response_outcomes(audience, monkeypatch, status, expected):
    client_class = httpx.Client
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200 if request.method == "GET" else status, json={})
    )
    monkeypatch.setattr(httpx, "Client", lambda **kw: client_class(transport=transport, **kw))
    monkeypatch.setattr(
        passes,
        "_google_credentials",
        lambda _: SimpleNamespace(token="test-token", refresh=lambda _: None),
    )
    with SessionLocal() as db:
        row = db.get(m.Pass, audience.passes[1])
        delivery = m.NotificationDelivery(
            id="new-message", payload={"title": "News", "message": "Hello"}
        )
        assert GoogleWalletNotificationProvider().send(db, row, delivery, {}) == expected


def test_queued_pass_revocation_prevents_delivery(audience, monkeypatch):
    a = audience
    real_dispatch = n.dispatch_pending
    monkeypatch.setattr(n, "dispatch_pending", lambda: None)
    response = send(a)
    with SessionLocal() as db:
        db.get(m.Pass, a.passes[0]).status = "revoked"
        db.commit()
    real_dispatch()
    assert len(a.calls) == 2
    assert detail(a, response)["delivery_counts"] == {"skipped": 1, "success": 2}


def test_anonymous_test_mode_is_identified_and_auth_mode_blocks_it(audience, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    anonymous = TestClient(app)
    a = audience
    body = prepare(a)
    monkeypatch.setattr(settings, "auth_enabled", True)
    assert anonymous.post(f"/api/v1/merchants/{a.mid}/notifications", json=body).status_code == 401
    monkeypatch.setattr(settings, "auth_enabled", False)
    response = anonymous.post(f"/api/v1/merchants/{a.mid}/notifications", json=body)
    assert response.status_code == 202, response.text
    assert response.json()["sender_name"] == "public-test"
    assert response.json()["sender_id"] is None


def test_notification_migration_preserves_existing_data_and_backs_up_once(tmp_path, monkeypatch):
    import sqlite3

    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.orm import Session

    from app import db as database
    from app.migrations.notifications import VERSION

    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    monkeypatch.setattr(database, "engine", engine)
    database.init_db()
    with Session(engine) as db:
        merchant = m.Merchant(name="Retained")
        db.add(merchant)
        db.flush()
        customer = m.Customer(merchant_id=merchant.id, customer_code="M1", points_balance=42)
        db.add(customer)
        db.delete(db.get(m.SchemaMigration, VERSION))
        db.commit()
        customer_id = customer.id
    with engine.begin() as connection:
        for table in ("pass_notification_state", "notification_delivery", "notification"):
            connection.execute(text(f"DROP TABLE {table}"))
    database.init_db()
    database.init_db()
    assert {"notification", "notification_delivery", "pass_notification_state"} <= set(
        inspect(engine).get_table_names()
    )
    with Session(engine) as db:
        assert db.get(m.Customer, customer_id).points_balance == 42
        assert db.get(m.SchemaMigration, VERSION)
    backups = list((tmp_path / "backups").glob(f"before-{VERSION}-*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert backup.execute("SELECT points_balance FROM customer").fetchone()[0] == 42
        assert not backup.execute(
            "SELECT name FROM sqlite_master WHERE name='notification'"
        ).fetchone()
    engine.dispose()
