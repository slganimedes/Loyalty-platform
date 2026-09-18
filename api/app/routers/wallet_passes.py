"""Apple PassKit web service and public pass branding assets."""

import hmac
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..db import get_db
from ..services import passes

router = APIRouter(prefix="/api/v1", tags=["wallet"])


def apple_config(db: Session) -> dict:
    cfg = passes._wallet_config(db)
    if not cfg or not cfg.apple_enabled:
        raise HTTPException(404, "Apple Wallet disabled")
    return passes.provider_config(cfg, "apple")


def authorized_pass(
    db: Session, serial: str, token: str, pass_type: str | None = None
) -> models.Pass:
    row = db.get(models.Pass, serial)
    if (
        not row
        or row.platform != "apple"
        or row.status != "active"
        or (pass_type is not None and row.pass_type_id != pass_type)
    ):
        raise HTTPException(404, "Pass not found")
    if not token or not row.auth_token or not hmac.compare_digest(row.auth_token, token):
        raise HTTPException(401, "Invalid pass token")
    return row


def apple_token(authorization: str | None) -> str:
    return (
        authorization.removeprefix("ApplePass ")
        if authorization and authorization.startswith("ApplePass ")
        else ""
    )


def pass_response(
    db: Session,
    row: models.Pass,
    config: dict,
    if_modified_since: str | None = None,
    if_none_match: str | None = None,
) -> Response:
    modified = datetime.fromtimestamp(row.updated_tag / 1000, timezone.utc)
    # ZIP metadata/signing time may differ while the pass content is equivalent.
    etag = f'W/"{row.id}-{row.updated_tag}"'
    headers = {
        "Last-Modified": format_datetime(modified, usegmt=True),
        "ETag": etag,
        "Cache-Control": "private, no-cache",
        "Content-Disposition": 'attachment; filename="loyalty.pkpass"',
    }
    if if_none_match is not None:
        candidates = {value.strip().removeprefix("W/") for value in if_none_match.split(",")}
        if "*" in candidates or etag.removeprefix("W/") in candidates:
            return Response(status_code=304, headers=headers)
    elif if_modified_since:
        try:
            # Compare the full precision change time. HTTP dates have only second
            # precision: rounding here can incorrectly hide a newer same-second pass.
            if parsedate_to_datetime(if_modified_since) >= modified:
                return Response(status_code=304, headers=headers)
        except (ValueError, TypeError, OverflowError):
            pass
    try:
        bundle = passes.apple_bundle(db, row.customer, row, config)
    except Exception:
        raise HTTPException(503, "Apple signing configuration unavailable")
    return Response(bundle, media_type="application/vnd.apple.pkpass", headers=headers)


@router.get("/passes/apple/{serial}.pkpass")
def download_pass(serial: str, token: str = "", db: Session = Depends(get_db)) -> Response:
    config = apple_config(db)
    return pass_response(db, authorized_pass(db, serial, token), config)


class RegistrationIn(BaseModel):
    pushToken: str = Field(min_length=1, max_length=512, pattern=r"^[0-9a-fA-F]+$")


@router.post("/wallet/apple/v1/devices/{device}/registrations/{pass_type}/{serial}")
def register(
    device: str,
    pass_type: str,
    serial: str,
    body: RegistrationIn,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Response:
    apple_config(db)
    row = authorized_pass(db, serial, apple_token(authorization), pass_type)
    registration = (
        db.query(models.DeviceRegistration).filter_by(device_id=device, pass_id=row.id).first()
    )
    status = 200 if registration else 201
    db.query(models.DeviceRegistration).filter_by(device_id=device).update(
        {"push_token": body.pushToken}
    )
    if not registration:
        db.add(
            models.DeviceRegistration(device_id=device, pass_id=row.id, push_token=body.pushToken)
        )
    db.commit()
    return Response(status_code=status)


@router.delete("/wallet/apple/v1/devices/{device}/registrations/{pass_type}/{serial}")
def unregister(
    device: str,
    pass_type: str,
    serial: str,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Response:
    apple_config(db)
    row = authorized_pass(db, serial, apple_token(authorization), pass_type)
    db.query(models.DeviceRegistration).filter_by(device_id=device, pass_id=row.id).delete()
    db.commit()
    return Response(status_code=200)


@router.get("/wallet/apple/v1/devices/{device}/registrations/{pass_type}", response_model=None)
def updates(
    device: str,
    pass_type: str,
    passesUpdatedSince: int | None = None,
    db: Session = Depends(get_db),
) -> dict | Response:
    apple_config(db)
    query = (
        db.query(models.Pass)
        .join(models.DeviceRegistration)
        .filter(
            models.DeviceRegistration.device_id == device,
            models.Pass.pass_type_id == pass_type,
            models.Pass.status == "active",
        )
    )
    if passesUpdatedSince is not None:
        query = query.filter(models.Pass.updated_tag > passesUpdatedSince)
    rows = query.all()
    if not rows:
        return Response(status_code=204)
    return {
        "serialNumbers": [r.id for r in rows],
        "lastUpdated": str(max(r.updated_tag for r in rows)),
    }


@router.get("/wallet/apple/v1/passes/{pass_type}/{serial}")
def latest(
    pass_type: str,
    serial: str,
    authorization: str | None = Header(default=None),
    if_modified_since: str | None = Header(default=None),
    if_none_match: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Response:
    config = apple_config(db)
    row = authorized_pass(db, serial, apple_token(authorization), pass_type)
    return pass_response(db, row, config, if_modified_since, if_none_match)


class LogIn(BaseModel):
    logs: list[str] = Field(max_length=100)


@router.post("/wallet/apple/v1/log")
def device_log(body: LogIn) -> dict:
    # Wallet diagnostic strings can contain tokens/PII; acknowledge without storage.
    return {"status": "ok"}


@router.get("/wallet/merchants/{merchant_id}/logo.png")
def logo(merchant_id: str, db: Session = Depends(get_db)) -> Response:
    merchant = db.get(models.Merchant, merchant_id)
    if not merchant:
        raise HTTPException(404, "Merchant not found")
    data = passes._png(merchant.pass_color, 256)
    if merchant.logo_data:
        data = merchant.logo_data
    elif merchant.pass_logo_path:
        root = Path(settings.assets_dir).resolve()
        path = (root / merchant.pass_logo_path).resolve()
        if not path.is_relative_to(root) or path.suffix.lower() != ".png" or not path.is_file():
            raise HTTPException(404, "Logo not found")
        data = path.read_bytes()
        if not data.startswith(b"\x89PNG"):
            raise HTTPException(404, "Logo not found")
    return Response(data, media_type="image/png", headers={"Cache-Control": "public, max-age=300"})
