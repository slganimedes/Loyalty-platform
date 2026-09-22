"""Seed the database with a super-admin, 2 demo merchants, customers and campaigns.

Run:  python seed.py   (from the api/ directory, with the venv active)
"""

import io

from PIL import Image

from app import models
from app.config import settings
from app.db import SessionLocal, init_db
from app.schemas import CampaignCreate
from app.services.campaigns import enrollment, save_campaign
from app.services.pass_assets import store_image
from app.services.security import hash_pan, hash_password


def demo_campaign(db, merchant, kind, config):
    assets = []
    for size in ((128, 128), (800, 240)):
        buffer = io.BytesIO()
        Image.new("RGB", size, merchant.pass_color).save(buffer, "PNG")
        assets.append(store_image(db, merchant.id, buffer.getvalue()).id)
    return save_campaign(
        db,
        merchant,
        CampaignCreate(
            name=f"{merchant.name} rewards",
            type=kind,
            config=config,
            design={
                "logo_asset_id": assets[0],
                "hero_asset_id": assets[1],
                "background_color": merchant.pass_color,
                "logo_description": f"Logo demo de {merchant.name}",
                "hero_description": "Fondo de campaña demo",
            },
        ),
    )


def run() -> None:
    init_db()
    db = SessionLocal()
    try:
        if (
            not db.query(models.AdminUser)
            .filter_by(username=settings.bootstrap_admin_username)
            .first()
        ):
            if not settings.bootstrap_admin_password:
                raise ValueError("Set BOOTSTRAP_ADMIN_PASSWORD before seeding")
            db.add(
                models.AdminUser(
                    username=settings.bootstrap_admin_username,
                    password_hash=hash_password(settings.bootstrap_admin_password),
                    role="super_admin",
                )
            )
            db.commit()
        if db.query(models.Merchant).first():
            print("Data already present; skipping seed.")
            return

        # Wallet config (both providers off by default for the pilot)
        if not db.query(models.WalletConfig).first():
            db.add(models.WalletConfig(apple_enabled=False, google_enabled=False))

        # Merchant 1: Café Central
        cafe = models.Merchant(name="Café Central", pass_color="#B85042")
        db.add(cafe)
        db.flush()
        cafe_campaign = demo_campaign(
            db, cafe, "points_per_spend", {"points": 1, "amount_unit": 10, "rounding": "floor"}
        )
        ana = models.Customer(
            merchant_id=cafe.id,
            name="Ana Demo",
            customer_code="CC-00817",
            card_hash=hash_pan("4111111111111111"),
            email="ana@example.com",
        )
        db.add(ana)
        db.flush()
        enrollment(db, cafe_campaign, ana)

        # Merchant 2: Tienda Sol
        sol = models.Merchant(name="Tienda Sol", pass_color="#2E6DA4")
        db.add(sol)
        db.flush()
        sol_campaign = demo_campaign(
            db,
            sol,
            "interaction",
            {"interactions_required": 10, "reward_description": "1 free menu"},
        )
        luis = models.Customer(
            merchant_id=sol.id, name="Luis Demo", customer_code="TS-00001", email="luis@example.com"
        )
        db.add(luis)
        db.flush()
        enrollment(db, sol_campaign, luis)

        db.commit()
        print("Seed complete: merchants 'Café Central' & 'Tienda Sol'.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
