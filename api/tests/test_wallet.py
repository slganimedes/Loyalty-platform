import base64
import hashlib
import io
import json
import shutil
import subprocess
import zipfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlparse

import httpx
import pytest
from campaign_fixtures import create_campaign
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7, pkcs12
from cryptography.x509.oid import NameOID
from google.auth import crypt, jwt
from test_e2e import SessionLocal, client, models, payment
from test_e2e import shop as base_shop

from app.services import passes


def shop():
    """Seed explicit legacy assignments to retain coverage of already installed passes."""
    mid, cid = base_shop()
    with SessionLocal() as db:
        customer = db.get(models.Customer, cid)
        cfg = passes._wallet_config(db)
        passes.ensure_pass(db, customer, "apple", passes.provider_config(cfg, "apple"))
        config = passes.provider_config(cfg, "google")
        config["issuer_id"] = "123"
        passes.ensure_pass(db, customer, "google", config)
        db.commit()
    return mid, cid


@pytest.fixture
def wallet_config(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test signer")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "test.p12"
    cert_path.write_bytes(
        pkcs12.serialize_key_and_certificates(
            b"test", key, cert, None, serialization.BestAvailableEncryption(b"test")
        )
    )
    wwdr = tmp_path / "wwdr.pem"
    wwdr.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    config = {
        "team_id": "TEAM",
        "pass_type_id": "pass.example.loyalty",
        "cert_path": str(cert_path),
        "cert_password": "test",
        "wwdr_cert_path": str(wwdr),
        "webservice_url": "https://api.example.com",
    }
    with SessionLocal() as db:
        cfg = passes._wallet_config(db)
        if not cfg:
            cfg = models.WalletConfig()
            db.add(cfg)
        cfg.apple_enabled = True
        cfg.apple_config = config
        cfg.google_enabled = False
        db.commit()
    yield config, key, cert
    with SessionLocal() as db:
        cfg = passes._wallet_config(db)
        cfg.apple_enabled = False
        cfg.google_enabled = False
        db.commit()


def apple_pass(cid):
    with SessionLocal() as db:
        row = db.query(models.Pass).filter_by(customer_id=cid, platform="apple").one()
        return row.id, row.auth_token, row.pass_type_id


def test_pass_cache_does_not_hide_same_second_update(wallet_config):
    _, cid = shop()
    serial, token, kind = apple_pass(cid)
    route = f"/api/v1/wallet/apple/v1/passes/{kind}/{serial}"
    auth = {"Authorization": f"ApplePass {token}"}
    with SessionLocal() as db:
        row = db.get(models.Pass, serial)
        row.updated_tag = row.updated_tag // 1000 * 1000 + 100
        db.commit()
    original = client.get(route, headers=auth)
    with SessionLocal() as db:
        row = db.get(models.Pass, serial)
        row.updated_tag += 100
        row.customer.points_balance = 17
        db.commit()
    updated = client.get(
        route, headers={**auth, "If-Modified-Since": original.headers["last-modified"]}
    )
    assert updated.status_code == 200
    assert updated.headers["etag"] != original.headers["etag"]
    assert (
        client.get(
            route,
            headers={
                **auth,
                "If-None-Match": original.headers["etag"],
                "If-Modified-Since": "Wed, 31 Dec 2098 23:59:59 GMT",
            },
        ).status_code
        == 200
    )
    with zipfile.ZipFile(io.BytesIO(updated.content)) as archive:
        payload = json.loads(archive.read("pass.json"))
        assert payload["storeCard"]["primaryFields"][0]["value"] == 17


def test_pass_cache_date_and_etag_conditions(wallet_config):
    _, cid = shop()
    serial, token, kind = apple_pass(cid)
    route = f"/api/v1/wallet/apple/v1/passes/{kind}/{serial}"
    auth = {"Authorization": f"ApplePass {token}"}
    # Exact-second timestamps have no ambiguity for date-based validation.
    with SessionLocal() as db:
        row = db.get(models.Pass, serial)
        row.updated_tag = row.updated_tag // 1000 * 1000
        db.commit()
    original = client.get(route, headers=auth)
    assert (
        client.get(
            route, headers={**auth, "If-Modified-Since": original.headers["last-modified"]}
        ).status_code
        == 304
    )
    assert client.get(route, headers={**auth, "If-Modified-Since": "invalid"}).status_code == 200
    assert (
        client.get(
            route, headers={**auth, "If-None-Match": f'"unrelated", {original.headers["etag"]}'}
        ).status_code
        == 304
    )
    assert client.get(route, headers={**auth, "If-None-Match": "*"}).status_code == 304
    assert client.get(route, headers={"If-None-Match": "*"}).status_code == 401


def test_signed_bundle_and_passkit_lifecycle(wallet_config, tmp_path):
    mid, cid = shop()
    logo_bytes = passes._png("#123456", 64)
    response = client.patch(
        f"/api/v1/merchants/{mid}",
        json={"logo_base64": base64.b64encode(logo_bytes).decode()},
    )
    assert response.status_code == 200
    serial, token, kind = apple_pass(cid)
    link = client.get(f"/api/v1/customers/{cid}/passes").json()["pass_links"]["apple"]
    parsed = urlparse(link)
    response = client.get(parsed.path + "?" + parsed.query)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.apple.pkpass"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        payload = json.loads(archive.read("pass.json"))
        assert payload["storeCard"]["primaryFields"][0]["value"] == 0
        assert payload["webServiceURL"].startswith("https://")
        manifest = json.loads(archive.read("manifest.json"))
        for filename, digest in manifest.items():
            assert hashlib.sha1(archive.read(filename)).hexdigest() == digest
        assert pkcs7.load_der_pkcs7_certificates(archive.read("signature"))
        assert archive.read("logo.png") == logo_bytes
        signature = tmp_path / "signature.der"
        manifest_file = tmp_path / "manifest.json"
        signature.write_bytes(archive.read("signature"))
        manifest_file.write_bytes(archive.read("manifest.json"))
    openssl = shutil.which("openssl") or "C:/Program Files/Git/usr/bin/openssl.exe"
    if __import__("pathlib").Path(openssl).is_file():
        verify = subprocess.run(
            [
                openssl,
                "smime",
                "-verify",
                "-inform",
                "DER",
                "-in",
                str(signature),
                "-content",
                str(manifest_file),
                "-noverify",
                "-out",
                str(tmp_path / "verified.json"),
            ],
            capture_output=True,
        )
        assert verify.returncode == 0, verify.stderr
    root = "/api/v1/wallet/apple/v1"
    route = f"{root}/devices/device1/registrations/{kind}/{serial}"
    auth = {"Authorization": f"ApplePass {token}"}
    assert client.post(route, json={"pushToken": "abcdef"}).status_code == 401
    assert client.post(route, headers=auth, json={"pushToken": "abcdef"}).status_code == 201
    assert client.post(route, headers=auth, json={"pushToken": "abcd12"}).status_code == 200
    updates = client.get(f"{root}/devices/device1/registrations/{kind}").json()
    assert updates["serialNumbers"] == [serial]
    assert (
        client.get(
            f"{root}/devices/device1/registrations/{kind}",
            params={"passesUpdatedSince": updates["lastUpdated"]},
        ).status_code
        == 204
    )
    latest = client.get(f"{root}/passes/{kind}/{serial}", headers=auth)
    assert latest.status_code == 200
    assert (
        client.get(
            f"{root}/passes/{kind}/{serial}",
            headers={**auth, "If-None-Match": latest.headers["etag"]},
        ).status_code
        == 304
    )
    assert client.get(f"{root}/passes/{kind}/{serial}").status_code == 401
    assert client.delete(route, headers=auth).status_code == 200
    assert client.delete(route, headers=auth).status_code == 200
    assert client.get(f"{root}/devices/device1/registrations/{kind}").status_code == 204


def test_apns_update_and_invalid_token_cleanup(wallet_config, monkeypatch):
    mid, cid = shop()
    serial, token, kind = apple_pass(cid)
    client.post(
        f"/api/v1/wallet/apple/v1/devices/device/registrations/{kind}/{serial}",
        headers={"Authorization": f"ApplePass {token}"},
        json={"pushToken": "abcdef"},
    )
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["apns-topic"] == kind
        assert json.loads(request.content) == {}
        return httpx.Response(410, json={"reason": "Unregistered"})

    monkeypatch.setattr(
        passes, "_apns_client", lambda config: httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert payment(mid).json()["pass_updated"] is True
    assert len(calls) == 1
    with SessionLocal() as db:
        assert db.query(models.DeviceRegistration).filter_by(pass_id=serial).count() == 0


def test_google_create_patch_and_signed_save_link(wallet_config, monkeypatch):
    config, key, cert = wallet_config
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    credentials = SimpleNamespace(
        token="fake-token",
        refresh=Mock(),
        signer=crypt.RSASigner.from_string(pem),
        service_account_email="test@example.iam.gserviceaccount.com",
    )
    monkeypatch.setattr(passes, "_google_credentials", lambda config: credentials)
    calls = []
    created = set()

    def handler(request):
        calls.append(request)
        if request.method == "PATCH" and "loyaltyClass/" in request.url.path:
            if json.loads(request.content).get("reviewStatus") != "UNDER_REVIEW":
                return httpx.Response(400, json={"error": {"message": "Invalid review status"}})
        if request.method == "POST":
            resource = json.loads(request.content)["id"]
            if resource in created:
                return httpx.Response(409)
            created.add(resource)
        return httpx.Response(200, json={})

    original_client = httpx.Client
    monkeypatch.setattr(
        passes.httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    with SessionLocal() as db:
        cfg = passes._wallet_config(db)
        cfg.apple_enabled = False
        cfg.google_enabled = True
        cfg.google_config = {"issuer_id": "123", "sa_json": "unused"}
        db.commit()
    mid, cid = shop()
    links = client.get(f"/api/v1/customers/{cid}/passes").json()["pass_links"]
    assert "apple" not in links
    token = links["google"].rsplit("/", 1)[1]
    claims = jwt.decode(
        token, certs=cert.public_bytes(serialization.Encoding.PEM), audience="google"
    )
    assert claims["payload"]["loyaltyObjects"][0]["id"].startswith("123.")
    create_campaign(
        client,
        f"/api/v1/merchants/{mid}/campaigns",
        json={"type": "points_per_spend", "config": {"amount_unit": 10}},
    )
    assert payment(mid).json()["pass_updated"] is True
    objects = [
        json.loads(r.content)
        for r in calls
        if r.method == "PATCH" and "loyaltyObject/" in str(r.url)
    ]
    assert objects[-1]["loyaltyPoints"]["balance"]["int"] == 2


def test_provider_failure_preserves_payment_and_independent_provider(wallet_config, monkeypatch):
    mid, cid = shop()
    monkeypatch.setattr(passes, "push_apple", Mock(side_effect=RuntimeError("secret-not-logged")))
    with SessionLocal() as db:
        cfg = passes._wallet_config(db)
        cfg.google_enabled = True
        cfg.google_config = {"issuer_id": "123"}
        db.commit()
    google = Mock(return_value="https://pay.google.com/gp/v/save/test")
    monkeypatch.setattr(passes, "google_sync", google)
    create_campaign(
        client,
        f"/api/v1/merchants/{mid}/campaigns",
        json={"type": "points_per_spend", "config": {"amount_unit": 10}},
    )
    result = payment(mid, external_transaction_id="wallet-failure-test").json()
    assert result["new_balance"] == 2
    assert result["pass_updated"] is True
    assert google.called
    assert (
        payment(mid, external_transaction_id="wallet-failure-test").json()["status"] == "duplicate"
    )
    with SessionLocal() as db:
        row = db.query(models.Pass).filter_by(customer_id=cid, platform="apple").one()
        assert row.updated_tag > row.synced_tag
    monkeypatch.setattr(passes, "push_apple", Mock(return_value=True))
    assert client.post(f"/api/v1/customers/{cid}/passes/refresh").json()["pass_updated"] is True


def test_write_only_config_and_toggle_preserves_secrets(wallet_config):
    assert (
        client.put(
            "/api/v1/settings/wallet/apple",
            json={"enabled": False, "config": {"cert_password": "********"}},
        ).status_code
        == 200
    )
    body = client.get("/api/v1/settings/wallet").json()
    assert body["apple_config"]["cert_password"] == "********"
    with SessionLocal() as db:
        assert passes._wallet_config(db).apple_config["cert_password"] == "test"
    assert (
        client.put(
            "/api/v1/settings/wallet/apple",
            json={"enabled": True, "config": {"webservice_url": "http://127.0.0.1"}},
        ).status_code
        == 422
    )
    mid, cid = shop()
    assert client.get(f"/api/v1/customers/{cid}/passes").json()["pass_links"] == {}


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com",
        "https://localhost",
        "https://192.168.1.1",
        "https://user:password@example.com",
        "https://example.local",
    ],
)
def test_public_wallet_urls(url):
    with pytest.raises(ValueError):
        passes.public_https_url(url)


def test_combined_config_and_individual_read(wallet_config):
    response = client.put(
        "/api/v1/settings/wallet",
        json={
            "apple_enabled": False,
            "google_enabled": True,
            "google_config": {"issuer_id": "123", "sa_json": "/certs/test.json"},
        },
    )
    assert response.status_code == 200
    assert response.json()["apple_enabled"] is False
    assert response.json()["google_config"]["sa_json"] == "********"
    assert client.get("/api/v1/settings/wallet/google").json()["enabled"] is True
    assert client.get("/api/v1/settings/wallet/apple").json()["enabled"] is False
    assert (
        client.put(
            "/api/v1/settings/wallet",
            json={"apple_enabled": True, "google_config": {"unknown": "value"}},
        ).status_code
        == 422
    )
    assert client.get("/api/v1/settings/wallet/apple").json()["enabled"] is False


def test_apns_tls_client_loads_signing_identity(wallet_config):
    client = passes._apns_client(wallet_config[0])
    client.close()


def test_concurrent_wallet_updates_end_at_latest_balance(wallet_config, monkeypatch):
    import time
    from concurrent.futures import ThreadPoolExecutor

    mid, cid = shop()
    with SessionLocal() as db:
        cfg = passes._wallet_config(db)
        cfg.apple_enabled = False
        cfg.google_enabled = True
        cfg.google_config = {"issuer_id": "123"}
        db.commit()
    sent_balances = []

    def sync(db, customer, row, config):
        balance = customer.points_balance
        if balance == 20:
            time.sleep(0.1)
        sent_balances.append(balance)
        return "https://pay.google.com/gp/v/save/test"

    monkeypatch.setattr(passes, "google_sync", sync)
    create_campaign(
        client,
        f"/api/v1/merchants/{mid}/campaigns",
        json={"type": "points_per_spend", "config": {"amount_unit": 1}},
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: payment(mid), range(2)))
    assert all(r.status_code == 200 for r in responses)
    assert sent_balances[-1] == 40
    with SessionLocal() as db:
        row = db.query(models.Pass).filter_by(customer_id=cid, platform="google").one()
        assert row.updated_tag == row.synced_tag
