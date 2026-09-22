"""Transactional image store, following the project's existing SQLite BLOB decision."""

import io
import warnings
from datetime import timedelta

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models as m
from ..config import settings


def image_bytes(raw: bytes) -> tuple[bytes, int, int]:
    if not raw or len(raw) > settings.pass_asset_max_bytes:
        raise HTTPException(413, "Image is empty or exceeds PASS_ASSET_MAX_BYTES")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as im:
                if im.format not in ("PNG", "JPEG", "WEBP") or getattr(im, "is_animated", False):
                    raise ValueError("Unsupported image")
                if im.width * im.height > settings.pass_asset_max_pixels:
                    raise ValueError("Image dimensions exceed limit")
                im.verify()
            with Image.open(io.BytesIO(raw)) as im:
                im.load()
                clean = ImageOps.exif_transpose(im).convert("RGBA")
                clean.info.clear()
                output = io.BytesIO()
                clean.save(output, format="PNG")
                data = output.getvalue()
                if len(data) > settings.pass_asset_max_bytes:
                    raise HTTPException(413, "Normalized image exceeds PASS_ASSET_MAX_BYTES")
                return data, clean.width, clean.height
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise HTTPException(
            422, "Invalid image: use a non-animated PNG, JPEG or WebP within dimension limits"
        )


def store_image(db: Session, merchant_id: str, raw: bytes) -> m.PassAsset:
    data, width, height = image_bytes(raw)
    asset = m.PassAsset(
        merchant_id=merchant_id,
        content=data,
        content_type="image/png",
        width=width,
        height=height,
        size=len(data),
    )
    db.add(asset)
    db.flush()
    return asset


def public_url(asset_id: str) -> str:
    from .passes import public_https_url

    return public_https_url(settings.public_api_url) + "/api/v1/public/pass-assets/" + asset_id


def describe(asset: m.PassAsset) -> dict:
    return {
        "id": asset.id,
        "url": public_url(asset.id),
        "content_type": asset.content_type,
        "width": asset.width,
        "height": asset.height,
        "size": asset.size,
    }


def cleanup_assets(db: Session) -> int:
    now = m._now()
    candidates = (
        db.query(m.PassAsset)
        .filter(
            or_(
                (m.PassAsset.published.is_(False))
                & (m.PassAsset.created_at < now - timedelta(days=1)),  # noqa: E712
                m.PassAsset.retired_at < now - timedelta(days=7),
            )
        )
        .all()
    )
    deleted = 0
    for asset in candidates:
        referenced = (
            db.query(m.PassDesign)
            .filter(
                or_(m.PassDesign.logo_asset_id == asset.id, m.PassDesign.hero_asset_id == asset.id)
            )
            .first()
        )
        pending = (
            asset.campaign_id
            and db.query(m.Pass)
            .filter(
                m.Pass.campaign_id == asset.campaign_id, m.Pass.updated_tag != m.Pass.synced_tag
            )
            .first()
        )
        if not referenced and not pending:
            db.delete(asset)
            deleted += 1
    db.commit()
    return deleted
