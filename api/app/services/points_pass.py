"""Deterministic Google GenericObject builder for an enrolled points customer."""

import re
from datetime import datetime

from sqlalchemy.orm import Session

from .. import models as m
from .campaigns import points_balance
from .pass_assets import public_url

MONTHS = {
    "es-ES": (
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    ),
    "en-US": (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ),
}


def format_customer_since(joined_at: datetime, locale: str = "es-ES") -> str:
    """Exactly three month letters, no period, followed by the four-digit year."""
    return f"{MONTHS[locale][joined_at.month - 1][:3]} {joined_at.year:04d}"


def identifiers(issuer_id: str, campaign_id: str, enrollment_id: str) -> tuple[str, str]:
    if not re.fullmatch(r"[0-9]+", issuer_id):
        raise ValueError("Google issuer ID must contain digits only")
    return (
        f"{issuer_id}.points_{campaign_id.replace('-', '')}",
        f"{issuer_id}.enrollment_{enrollment_id.replace('-', '')}",
    )


def build_points_pass(
    db: Session,
    merchant: m.Merchant,
    campaign: m.Campaign,
    customer: m.Customer,
    enrollment: m.CampaignEnrollment,
    design: m.PassDesign,
    issuer_id: str,
) -> dict:
    if not (
        campaign.merchant_id == customer.merchant_id == merchant.id
        and enrollment.customer_id == customer.id
        and enrollment.campaign_id == campaign.id
        and design.campaign_id == campaign.id
    ):
        raise ValueError("Pass entities must belong to the same merchant and enrollment")
    if (
        campaign.type != "points_per_spend"
        or campaign.deleted
        or customer.deleted
        or enrollment.status != "active"
        or not campaign.active
    ):
        raise ValueError("An active points campaign enrollment is required")
    for asset_id in (design.logo_asset_id, design.hero_asset_id):
        asset = db.get(m.PassAsset, asset_id) if asset_id else None
        if (
            not asset
            or asset.merchant_id != merchant.id
            or asset.campaign_id != campaign.id
            or not asset.published
        ):
            raise ValueError("A published campaign logo and hero image are required")
    class_id, object_id = identifiers(issuer_id, campaign.id, enrollment.id)
    locale = design.locale

    def localized(value: str) -> dict:
        return {"defaultValue": {"language": locale, "value": value}}

    def image(asset_id: str, description: str) -> dict:
        return {
            "sourceUri": {"uri": public_url(asset_id)},
            "contentDescription": localized(description),
        }

    return {
        "id": object_id,
        "classId": class_id,
        "state": "ACTIVE",
        "logo": image(design.logo_asset_id, design.logo_description),
        "cardTitle": localized(merchant.name),
        "subheader": localized(design.subheader),
        "header": localized(customer.name or customer.customer_code),
        "textModulesData": [
            {
                "id": "puntos",
                "header": design.points_label or ("Puntos" if locale == "es-ES" else "Points"),
                "body": str(points_balance(db, campaign.id, customer.id)),
            },
            {
                "id": "cliente_desde",
                "header": design.member_since_label
                or ("Cliente desde" if locale == "es-ES" else "Member since"),
                "body": format_customer_since(customer.created_at, locale),
            },
        ],
        "barcode": {
            "type": "QR_CODE",
            "value": enrollment.barcode_token,
            "alternateText": design.barcode_alternate_text
            or (
                "Canjea tus puntos en el comercio"
                if locale == "es-ES"
                else "Redeem your points in store"
            ),
        },
        "hexBackgroundColor": design.background_color,
        "heroImage": image(design.hero_asset_id, design.hero_description),
    }
