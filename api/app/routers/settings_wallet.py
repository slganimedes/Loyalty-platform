"""Wallet provider configuration endpoints (Super Admin).

Secrets are write-only: the GET response masks sensitive fields.
"""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from .auth import super_admin

router = APIRouter(
    prefix="/api/v1/settings", tags=["wallet-config"], dependencies=[Depends(super_admin)]
)


class ProviderConfig(BaseModel):
    enabled: bool = False
    config: dict = Field(default_factory=dict)


class WalletUpdate(BaseModel):
    apple_enabled: bool | None = None
    google_enabled: bool | None = None
    apple_config: dict | None = None
    google_config: dict | None = None


def _get_or_create(db: Session) -> models.WalletConfig:
    cfg = db.query(models.WalletConfig).first()
    if not cfg:
        cfg = models.WalletConfig()
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def _mask(config: dict | None) -> dict:
    if not config:
        return {}
    masked = {}
    for k, v in config.items():
        masked[k] = (
            "********"
            if any(s in k.lower() for s in ("cert", "password", "key", "json", "secret"))
            else v
        )
    return masked


@router.get("/wallet")
def get_wallet(db: Session = Depends(get_db)) -> dict:
    cfg = _get_or_create(db)
    return {
        "apple_enabled": cfg.apple_enabled,
        "apple_config": _mask(cfg.apple_config),
        "google_enabled": cfg.google_enabled,
        "google_config": _mask(cfg.google_config),
    }


@router.put("/wallet/apple")
def set_apple(body: ProviderConfig, db: Session = Depends(get_db)) -> dict:
    cfg = _get_or_create(db)
    cfg.apple_enabled = body.enabled
    cfg.apple_config = _merge(cfg.apple_config, body.config, "apple")
    db.commit()
    return {"apple_enabled": cfg.apple_enabled}


@router.get("/wallet/{provider}")
def get_provider(provider: Literal["apple", "google"], db: Session = Depends(get_db)) -> dict:
    cfg = _get_or_create(db)
    return {
        "enabled": getattr(cfg, f"{provider}_enabled"),
        "config": _mask(getattr(cfg, f"{provider}_config")),
    }


@router.put("/wallet")
def set_wallet(body: WalletUpdate, db: Session = Depends(get_db)) -> dict:
    cfg = _get_or_create(db)
    for provider in ("apple", "google"):
        enabled = getattr(body, f"{provider}_enabled")
        config = getattr(body, f"{provider}_config")
        if enabled is not None:
            setattr(cfg, f"{provider}_enabled", enabled)
        if config is not None:
            setattr(
                cfg,
                f"{provider}_config",
                _merge(getattr(cfg, f"{provider}_config"), config, provider),
            )
    db.commit()
    return get_wallet(db)


@router.put("/wallet/google")
def set_google(body: ProviderConfig, db: Session = Depends(get_db)) -> dict:
    cfg = _get_or_create(db)
    cfg.google_enabled = body.enabled
    cfg.google_config = _merge(cfg.google_config, body.config, "google")
    db.commit()
    return {"google_enabled": cfg.google_enabled}


def _merge(existing: dict | None, incoming: dict, provider: str) -> dict:
    from fastapi import HTTPException

    from ..services.passes import public_https_url

    allowed = {
        "apple": {
            "pass_type_id",
            "team_id",
            "cert_path",
            "cert_password",
            "wwdr_cert_path",
            "webservice_url",
        },
        "google": {"issuer_id", "sa_json"},
    }[provider]
    if set(incoming) - allowed:
        raise HTTPException(422, "Unknown provider setting")
    merged = dict(existing or {})
    for key, value in incoming.items():
        if not isinstance(value, str):
            raise HTTPException(422, "Provider settings must be strings")
        if value and value != "********":
            if key == "webservice_url":
                try:
                    public_https_url(value)
                except ValueError:
                    raise HTTPException(422, "Wallet URL must use a public HTTPS hostname")
            merged[key] = value
    return merged
