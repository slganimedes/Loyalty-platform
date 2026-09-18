"""Seed the database with a super-admin, 2 demo merchants, customers and campaigns.

Run:  python seed.py   (from the api/ directory, with the venv active)
"""

from app import models
from app.config import settings
from app.db import SessionLocal, init_db
from app.services.security import hash_pan, hash_password


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
        db.add(
            models.Campaign(
                merchant_id=cafe.id,
                type="points_per_spend",
                config={"points": 1, "amount_unit": 10, "rounding": "floor"},
            )
        )
        db.add(
            models.Customer(
                merchant_id=cafe.id,
                customer_code="CC-00817",
                card_hash=hash_pan("4111111111111111"),
                email="ana@example.com",
            )
        )

        # Merchant 2: Tienda Sol
        sol = models.Merchant(name="Tienda Sol", pass_color="#2E6DA4")
        db.add(sol)
        db.flush()
        db.add(
            models.Campaign(
                merchant_id=sol.id,
                type="interaction",
                config={"interactions_required": 10, "reward_description": "1 free menu"},
            )
        )
        db.add(
            models.Customer(merchant_id=sol.id, customer_code="TS-00001", email="luis@example.com")
        )

        db.commit()
        print("Seed complete: configured admin, merchants 'Café Central' & 'Tienda Sol'.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
