"""Signed Apple passes, PassKit/APNs delivery and Google Wallet REST integration."""

import hashlib
import io
import ipaddress
import json
import logging
import secrets
import ssl
import struct
import tempfile
import time
import zipfile
import zlib
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Any, TypeVar
from urllib.parse import urlparse

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs7, pkcs12
from google.auth import jwt
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..config import settings

logger = logging.getLogger("passes")
# Provider exceptions may include URLs/tokens. Never log their text or HTTP requests.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
GOOGLE_BASE = "https://walletobjects.googleapis.com/walletobjects/v1"
_customer_locks = [RLock() for _ in range(64)]
T = TypeVar("T")


def serialize_customer(function: Callable[..., T]) -> Callable[..., T]:
    """Keep provider writes ordered in the pilot's single API worker."""

    @wraps(function)
    def wrapped(db: Session, customer: models.Customer, *args: Any, **kwargs: Any) -> T:
        with _customer_locks[hash(customer.id) % len(_customer_locks)]:
            db.expire_all()
            db.refresh(customer)
            return function(db, customer, *args, **kwargs)

    return wrapped


def public_https_url(value: str) -> str:
    parsed = urlparse(value)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or host == "localhost"
        or host.endswith((".local", ".localhost"))
        or "." not in host
    ):
        raise ValueError("A public HTTPS hostname is required")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return value.rstrip("/")
    raise ValueError("Wallet URLs must use a public hostname, not an IP address")


def _wallet_config(db: Session) -> models.WalletConfig | None:
    return db.query(models.WalletConfig).first()


def provider_config(cfg: models.WalletConfig, provider: str) -> dict:
    fields = {
        "apple": (
            "team_id",
            "pass_type_id",
            "cert_path",
            "cert_password",
            "wwdr_cert_path",
            "webservice_url",
        ),
        "google": ("issuer_id", "sa_json"),
    }[provider]
    result = {field: getattr(settings, f"{provider}_{field}") for field in fields}
    result.update(getattr(cfg, f"{provider}_config") or {})
    return result


def _next_tag(db: Session) -> int:
    maximum = db.query(func.max(models.Pass.updated_tag)).scalar() or 0
    return max(time.time_ns() // 1000000, maximum + 1)


def ensure_pass(
    db: Session,
    customer: models.Customer,
    platform: str,
    config: dict,
    campaign_id: str | None = None,
) -> models.Pass:
    row = (
        db.query(models.Pass)
        .filter_by(
            customer_id=customer.id, platform=platform, campaign_id=campaign_id, status="active"
        )
        .first()
    )
    membership = (
        db.query(models.CampaignEnrollment)
        .filter_by(customer_id=customer.id, campaign_id=campaign_id)
        .first()
        if campaign_id
        else None
    )
    campaign = db.get(models.Campaign, campaign_id) if campaign_id else None
    generic = (
        platform == "google"
        and campaign
        and campaign.type == "points_per_spend"
        and campaign.lifecycle == "ready"
    )
    if not row and generic and membership:
        row = (
            db.query(models.Pass)
            .filter_by(enrollment_id=membership.id, platform="google", google_kind="generic")
            .first()
        )
        if row:
            if row.updated_tag != row.synced_tag:
                raise ValueError(
                    "Wait for the previous revocation before reissuing this enrollment"
                )
            row.status = "active"
            row.updated_tag = _next_tag(db)
    if not row:
        row = models.Pass(
            customer_id=customer.id,
            campaign_id=campaign_id,
            platform=platform,
            enrollment_id=membership.id if membership else None,
            google_kind="generic" if generic else "loyalty",
            auth_token=secrets.token_urlsafe(32),
            updated_tag=_next_tag(db),
            synced_tag=0,
        )
        db.add(row)
        db.flush()
    if not row.auth_token:
        row.auth_token = secrets.token_urlsafe(32)
    if platform == "apple":
        if row.pass_type_id and row.pass_type_id != config["pass_type_id"]:
            raise ValueError("Existing passes require the original Pass Type ID")
        row.pass_type_id = config["pass_type_id"]
        row.external_pass_id = row.id
    else:
        suffix = row.id if row.campaign_id else customer.id
        if row.google_kind == "generic":
            from .points_pass import identifiers

            external_id = identifiers(config["issuer_id"], campaign_id, membership.id)[1]
        else:
            external_id = f"{config['issuer_id']}.{suffix.replace('-', '')}"
        if row.external_pass_id and row.external_pass_id != external_id:
            raise ValueError("Existing passes require the original issuer ID")
        row.external_pass_id = external_id
    return row


def campaign_balance(db: Session, customer: models.Customer, row: models.Pass) -> int:
    if not row.campaign_id:
        return customer.points_balance
    query = db.query(models.Movement).filter_by(
        customer_id=customer.id, campaign_id=row.campaign_id
    )
    if row.campaign.type == "interaction":
        return query.filter_by(type="interaction").count()
    return int(
        query.with_entities(func.coalesce(func.sum(models.Movement.points_delta), 0)).scalar()
    )


def _recent_movements(
    db: Session, customer: models.Customer, campaign_id: str | None = None
) -> str:
    rows = (
        db.query(models.Movement)
        .filter_by(customer_id=customer.id)
        .filter(models.Movement.campaign_id == campaign_id if campaign_id else True)
        .order_by(models.Movement.created_at.desc(), models.Movement.id.desc())
        .limit(5)
        .all()
    )
    return (
        "\n".join(
            f"{r.created_at:%Y-%m-%d}: {r.description or r.type} ({r.points_delta:+d})"
            for r in rows
        )
        or "No movements / Sin movimientos"
    )


def _coupons(db: Session, customer: models.Customer) -> str:
    rows = db.query(models.Coupon).filter_by(customer_id=customer.id, status="issued").all()
    return ", ".join(f"{r.amount:.2f} EUR" for r in rows) or "0 EUR"


def _load_signer(config: dict):
    key, cert, chain = pkcs12.load_key_and_certificates(
        Path(config["cert_path"]).read_bytes(), config.get("cert_password", "").encode() or None
    )
    if key is None or cert is None:
        raise ValueError("Certificate must include a private key")
    return key, cert, chain or []


def _png(color: str, size: int) -> bytes:
    rgb = bytes.fromhex(color.lstrip("#"))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    pixels = (b"\x00" + rgb * size) * size
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def apple_bundle(db: Session, customer: models.Customer, row: models.Pass, config: dict) -> bytes:
    from .notification_providers import apple_message_fields
    from .points_pass import format_customer_since

    base = public_https_url(config["webservice_url"])
    if not config["team_id"] or not config["pass_type_id"]:
        raise ValueError("Apple Team ID and Pass Type ID are required")
    merchant = customer.merchant
    design = row.campaign.design if row.campaign else None
    color = design.background_color if design else merchant.pass_color
    rgb = tuple(bytes.fromhex(color.lstrip("#")))
    payload = {
        "formatVersion": 1,
        "voided": row.status == "revoked",
        "passTypeIdentifier": row.pass_type_id,
        "serialNumber": row.id,
        "teamIdentifier": config["team_id"],
        "organizationName": merchant.name,
        "description": row.campaign.name if row.campaign else f"{merchant.name} Loyalty",
        "logoText": row.campaign.name if row.campaign else merchant.name,
        "backgroundColor": f"rgb({rgb[0]}, {rgb[1]}, {rgb[2]})",
        "foregroundColor": "rgb(255, 255, 255)",
        "labelColor": "rgb(255, 255, 255)",
        "webServiceURL": base + "/api/v1/wallet/apple",
        "authenticationToken": row.auth_token,
        "barcodes": [
            {
                "format": "PKBarcodeFormatQR",
                "message": row.enrollment.barcode_token
                if row.enrollment
                else customer.customer_code,
                "messageEncoding": "utf-8",
            }
        ],
        "storeCard": {
            "primaryFields": [
                {
                    "key": "points",
                    "label": "Stamps / Sellos"
                    if row.campaign and row.campaign.type == "interaction"
                    else "Points / Puntos",
                    "value": campaign_balance(db, customer, row),
                }
            ],
            "secondaryFields": [
                {
                    "key": "customer",
                    "label": "Customer / Cliente",
                    "value": customer.name or customer.customer_code,
                },
                {
                    "key": "customer_since",
                    "label": (design.member_since_label if design else None)
                    or "Cliente desde / Member since",
                    "value": format_customer_since(
                        customer.created_at, design.locale if design else "es-ES"
                    ),
                },
            ],
            "backFields": [
                {
                    "key": "movements",
                    "label": "Latest movements / Movimientos",
                    "value": _recent_movements(db, customer, row.campaign_id),
                },
                {"key": "coupons", "label": "Coupons / Cupones", "value": _coupons(db, customer)},
            ],
        },
    }
    payload["storeCard"]["backFields"].extend(apple_message_fields(db, row))
    files = {
        "pass.json": json.dumps(payload, ensure_ascii=False).encode(),
        "icon.png": _png(merchant.pass_color, 29),
        "icon@2x.png": _png(merchant.pass_color, 58),
    }
    if design and design.hero_asset_id:
        files["strip.png"] = db.get(models.PassAsset, design.hero_asset_id).content
    if design and design.logo_asset_id:
        files["logo.png"] = db.get(models.PassAsset, design.logo_asset_id).content
    elif merchant.logo_data:
        files["logo.png"] = merchant.logo_data
    elif merchant.pass_logo_path:
        root = Path(settings.assets_dir).resolve()
        logo = (root / merchant.pass_logo_path).resolve()
        if not logo.is_relative_to(root) or logo.suffix.lower() != ".png":
            raise ValueError("Logo must be a PNG inside assets_dir")
        logo_bytes = logo.read_bytes()
        if not logo_bytes.startswith(b"\x89PNG"):
            raise ValueError("Invalid PNG logo")
        files["logo.png"] = logo_bytes
    manifest = json.dumps(
        {name: hashlib.sha1(data).hexdigest() for name, data in files.items()}, sort_keys=True
    ).encode()
    key, cert, chain = _load_signer(config)
    wwdr_data = Path(config["wwdr_cert_path"]).read_bytes()
    wwdr = (
        x509.load_pem_x509_certificate(wwdr_data)
        if b"BEGIN CERTIFICATE" in wwdr_data
        else x509.load_der_x509_certificate(wwdr_data)
    )
    signer = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(manifest)
        .add_signer(cert, key, hashes.SHA256())
        .add_certificate(wwdr)
    )
    for certificate in chain:
        if certificate.fingerprint(hashes.SHA256()) not in {
            cert.fingerprint(hashes.SHA256()),
            wwdr.fingerprint(hashes.SHA256()),
        }:
            signer = signer.add_certificate(certificate)
    files["manifest.json"] = manifest
    files["signature"] = signer.sign(
        serialization.Encoding.DER,
        [pkcs7.PKCS7Options.DetachedSignature, pkcs7.PKCS7Options.Binary],
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return output.getvalue()


def _apns_client(config: dict) -> httpx.Client:
    key, cert, chain = _load_signer(config)
    context = ssl.create_default_context()
    # The on-disk temporary private key is encrypted; the password stays in memory.
    password = secrets.token_urlsafe(32).encode()
    with tempfile.TemporaryDirectory() as directory:
        pem = Path(directory) / "client.pem"
        pem.write_bytes(
            cert.public_bytes(serialization.Encoding.PEM)
            + b"".join(c.public_bytes(serialization.Encoding.PEM) for c in chain)
            + key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.BestAvailableEncryption(password),
            )
        )
        context.load_cert_chain(str(pem), password=password)
    return httpx.Client(http2=True, verify=context, timeout=10)


def push_apple(db: Session, row: models.Pass, config: dict) -> bool:
    registrations = db.query(models.DeviceRegistration).filter_by(pass_id=row.id).all()
    if not registrations:
        return True  # The updated pass is available when a device first installs it.
    success = True
    with _apns_client(config) as client:
        for registration in registrations:
            response = client.post(
                f"https://api.push.apple.com/3/device/{registration.push_token}",
                json={},
                headers={"apns-topic": row.pass_type_id, "apns-priority": "5"},
            )
            if response.status_code == 410 or (
                response.status_code == 400 and response.json().get("reason") == "BadDeviceToken"
            ):
                db.query(models.DeviceRegistration).filter_by(
                    push_token=registration.push_token
                ).delete(synchronize_session=False)
            elif response.status_code != 200:
                success = False
    return success


def _google_credentials(config: dict):
    if not config["issuer_id"]:
        raise ValueError("Google issuer ID is required")
    return service_account.Credentials.from_service_account_file(
        config["sa_json"], scopes=["https://www.googleapis.com/auth/wallet_object.issuer"]
    )


def google_sync(db: Session, customer: models.Customer, row: models.Pass, config: dict) -> str:
    from .points_pass import format_customer_since

    if row.external_pass_id and not row.external_pass_id.startswith(config["issuer_id"] + "."):
        raise ValueError(
            "Existing passes require the original issuer ID; revoke and reassign the failed pass"
        )
    credentials = _google_credentials(config)
    credentials.refresh(Request())
    merchant = customer.merchant
    class_suffix = (
        f"campaign_{row.campaign_id.replace('-', '')}"
        if row.campaign_id
        else f"merchant_{merchant.id.replace('-', '')}"
    )
    class_id = f"{config['issuer_id']}.{class_suffix}"
    logo_url = public_https_url(settings.public_api_url) + (
        merchant.logo_url or f"/api/v1/wallet/merchants/{merchant.id}/logo.png"
    )
    class_body = {
        "id": class_id,
        "issuerName": merchant.name,
        "programName": row.campaign.name if row.campaign else merchant.name,
        "programLogo": {"sourceUri": {"uri": logo_url}},
        "reviewStatus": "UNDER_REVIEW",
        "hexBackgroundColor": merchant.pass_color,
    }
    design = row.campaign.design if row.campaign else None
    if design:
        from .pass_assets import public_url

        class_body["hexBackgroundColor"] = design.background_color
        for asset_id, key, description in (
            (design.logo_asset_id, "programLogo", design.logo_description),
            (design.hero_asset_id, "heroImage", design.hero_description),
        ):
            if asset_id:
                class_body[key] = {
                    "sourceUri": {"uri": public_url(asset_id)},
                    "contentDescription": {
                        "defaultValue": {"language": design.locale, "value": description}
                    },
                }
    obj = {
        "id": row.external_pass_id,
        "classId": class_id,
        "state": "ACTIVE",
        "accountId": customer.customer_code,
        "accountName": customer.name or customer.customer_code,
        "loyaltyPoints": {
            "label": "Stamps / Sellos"
            if row.campaign and row.campaign.type == "interaction"
            else "Points / Puntos",
            "balance": {"int": campaign_balance(db, customer, row)},
        },
        "barcode": {
            "type": "QR_CODE",
            "value": row.enrollment.barcode_token if row.enrollment else customer.customer_code,
        },
        "textModulesData": [
            {
                "id": "cliente_desde",
                "header": (design.member_since_label if design else None)
                or "Cliente desde / Member since",
                "body": format_customer_since(
                    customer.created_at, design.locale if design else "es-ES"
                ),
            },
            {
                "id": "movements",
                "header": "Movements / Movimientos",
                "body": _recent_movements(db, customer, row.campaign_id),
            },
            {"id": "coupons", "header": "Coupons / Cupones", "body": _coupons(db, customer)},
        ],
    }
    generic = row.google_kind == "generic"
    if generic:
        from .points_pass import build_points_pass

        obj = build_points_pass(
            db,
            merchant,
            row.campaign,
            customer,
            row.enrollment,
            row.campaign.design,
            config["issuer_id"],
        )
        if obj["id"] != row.external_pass_id:
            raise ValueError(
                "Existing passes require the original issuer ID; revoke before changing issuer"
            )
        class_id = obj["classId"]
        class_body = {"id": class_id}
    resource = "generic" if generic else "loyalty"
    with httpx.Client(
        timeout=15, headers={"Authorization": f"Bearer {credentials.token}"}
    ) as client:
        response = client.post(f"{GOOGLE_BASE}/{resource}Class", json=class_body)
        if response.status_code == 409:
            # Google requires UNDER_REVIEW even when patching an approved class.
            patch = {key: value for key, value in class_body.items() if key != "id"}
            if patch:
                client.patch(
                    f"{GOOGLE_BASE}/{resource}Class/{class_id}", json=patch
                ).raise_for_status()
        else:
            response.raise_for_status()
        response = client.post(f"{GOOGLE_BASE}/{resource}Object", json=obj)
        if response.status_code == 409:
            client.patch(
                f"{GOOGLE_BASE}/{row.google_kind}Object/{row.external_pass_id}", json=obj
            ).raise_for_status()
        else:
            response.raise_for_status()
    token = jwt.encode(
        credentials.signer,
        {
            "iss": credentials.service_account_email,
            "aud": "google",
            "typ": "savetowallet",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
            "origins": [public_https_url(settings.public_admin_url)],
            "payload": {resource + "Objects": [{"id": row.external_pass_id}]},
        },
    )
    return "https://pay.google.com/gp/v/save/" + token.decode()


@serialize_customer
def issue_pass_links(db: Session, customer: models.Customer, pass_id: str | None = None) -> dict:
    cfg = _wallet_config(db)
    links = {}
    if not cfg:
        return links
    for row in db.query(models.Pass).filter_by(customer_id=customer.id, status="active").all():
        if pass_id is not None and row.id != pass_id:
            continue
        provider = row.platform
        link_key = row.id if row.campaign_id else provider
        if (
            customer.deleted
            or (row.campaign and (row.campaign.deleted or not row.campaign.active))
            or (row.enrollment and row.enrollment.status != "active")
        ):
            continue
        if not getattr(cfg, f"{provider}_enabled"):
            continue
        try:
            config = provider_config(cfg, provider)
            db.commit()
            if row.status != "active":
                continue
            if provider == "apple":
                apple_bundle(db, customer, row, config)  # Only return an installable link.
                if not db.query(models.DeviceRegistration).filter_by(pass_id=row.id).first():
                    row.synced_tag = row.updated_tag
                    db.commit()
                links[link_key] = (
                    public_https_url(settings.public_api_url)
                    + f"/api/v1/passes/apple/{row.id}.pkpass?token={row.auth_token}"
                )
            else:
                links[link_key] = google_sync(db, customer, row, config)
                row.synced_tag = row.updated_tag
                db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning(
                "Wallet issuance failed: provider=%s kind=%s", provider, type(exc).__name__
            )
    return links


@serialize_customer
def revoke_pass(db: Session, customer: models.Customer, pass_id: str) -> bool:
    row = db.get(models.Pass, pass_id)
    if not row or row.customer_id != customer.id:
        raise ValueError("Pass not found")
    if row.status != "revoked":
        row.status = "revoked"
        row.updated_tag = _next_tag(db)
        db.commit()  # Block new links even if the provider is unavailable.
    if row.synced_tag == row.updated_tag:
        return True
    try:
        cfg = _wallet_config(db)
        if not cfg:
            return False
        config = provider_config(cfg, row.platform)
        if row.platform == "google":
            if row.external_pass_id:
                credentials = _google_credentials(config)
                credentials.refresh(Request())
                with httpx.Client(
                    timeout=15, headers={"Authorization": f"Bearer {credentials.token}"}
                ) as client:
                    response = client.patch(
                        f"{GOOGLE_BASE}/{row.google_kind}Object/{row.external_pass_id}",
                        json={"state": "INACTIVE"},
                    )
                    if response.status_code != 404:
                        response.raise_for_status()
        else:
            registrations = db.query(models.DeviceRegistration).filter_by(pass_id=row.id).count()
            if registrations:
                if not cfg.apple_enabled:
                    return False
                apple_bundle(db, customer, row, config)
                if not push_apple(db, row, config):
                    return False
        row.synced_tag = row.updated_tag
        db.commit()
        return True
    except Exception as exc:
        db.rollback()
        logger.warning(
            "Wallet revocation pending: provider=%s kind=%s", row.platform, type(exc).__name__
        )
        return False


@serialize_customer
def update_customer_pass(db: Session, customer: models.Customer) -> bool:
    cfg = _wallet_config(db)
    if not cfg:
        return False
    updated = False
    for row in db.query(models.Pass).filter_by(customer_id=customer.id, status="active").all():
        provider = row.platform
        if (
            customer.deleted
            or (row.campaign and (row.campaign.deleted or not row.campaign.active))
            or (row.enrollment and row.enrollment.status != "active")
        ):
            continue
        if not getattr(cfg, f"{provider}_enabled"):
            continue
        try:
            config = provider_config(cfg, provider)
            if row.status != "active":
                continue
            row.updated_tag = _next_tag(db)
            db.commit()  # Device fetches must observe committed balances and tags.
            if provider == "apple":
                apple_bundle(db, customer, row, config)
                success = push_apple(db, row, config)
            else:
                google_sync(db, customer, row, config)
                success = True
            if success:
                row.synced_tag = row.updated_tag
                updated = True
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning(
                "Wallet update pending: provider=%s kind=%s", provider, type(exc).__name__
            )
    return updated


def mark_revoked(db: Session, rows: list[models.Pass]) -> None:
    """Persist revocation intent in the same transaction as a parent deletion."""
    for row in rows:
        if row.status != "revoked":
            row.status = "revoked"
            row.updated_tag = _next_tag(db)


def retry_pending_revocations() -> None:
    from ..db import SessionLocal

    with SessionLocal() as db:
        ids = [
            row.id
            for row in db.query(models.Pass)
            .filter(
                models.Pass.status == "revoked", models.Pass.updated_tag != models.Pass.synced_tag
            )
            .all()
        ]
    for pass_id in ids:
        with SessionLocal() as db:
            row = db.get(models.Pass, pass_id)
            if row:
                revoke_pass(db, row.customer, row.id)


def maintenance() -> None:
    from ..db import SessionLocal
    from .pass_assets import cleanup_assets

    retry_pending_revocations()
    with SessionLocal() as db:
        customer_ids = {
            r.customer_id
            for r in db.query(models.Pass)
            .filter(
                models.Pass.status == "active", models.Pass.updated_tag != models.Pass.synced_tag
            )
            .all()
        }
    for customer_id in customer_ids:
        with SessionLocal() as db:
            customer = db.get(models.Customer, customer_id)
            if customer and not customer.deleted:
                update_customer_pass(db, customer)
    with SessionLocal() as db:
        cleanup_assets(db)
