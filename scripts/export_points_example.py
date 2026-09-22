"""Export a real builder result using synthetic, deterministic in-memory fixtures."""
# ruff: noqa: E402 -- the script imports the local api package after adding its root.

import io
import json
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from app import models as m
from app.config import settings
from app.db import Base
from app.schemas import CampaignCreate
from app.services.campaigns import enrollment, save_campaign
from app.services.pass_assets import store_image
from app.services.points_pass import build_points_pass


def example_payload():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    original_url = settings.public_api_url
    settings.public_api_url = "https://api.example.com"
    try:
        with Session(engine) as db:
            merchant = m.Merchant(
                id="11111111-1111-4111-8111-111111111111",
                name="Cafetería Aurora",
                pass_color="#373839",
            )
            db.add(merchant)
            db.flush()
            assets = []
            for number in (1, 2):
                data = io.BytesIO()
                Image.new("RGB", (32, 20), "#373839").save(data, "PNG")
                asset = store_image(db, merchant.id, data.getvalue())
                asset.id = f"44444444-4444-4444-8444-44444444444{number}"
                assets.append(asset.id)
            customer = m.Customer(
                id="22222222-2222-4222-8222-222222222222",
                merchant_id=merchant.id,
                customer_code="DEMO-001",
                name="Ana Demo",
                points_balance=320,
                created_at=datetime(2026, 9, 1),
            )
            campaign = m.Campaign(
                id="33333333-3333-4333-8333-333333333333",
                merchant_id=merchant.id,
                type="points_per_spend",
                config={},
            )
            db.add_all([customer, campaign])
            db.flush()
            save_campaign(
                db,
                merchant,
                CampaignCreate(
                    name="Puntos Aurora",
                    type="points_per_spend",
                    config={},
                    design={
                        "logo_asset_id": assets[0],
                        "hero_asset_id": assets[1],
                        "background_color": "#373839",
                        "logo_description": "Logo de Cafetería Aurora",
                        "hero_description": "Imagen de la campaña Puntos Aurora",
                    },
                ),
                campaign,
            )
            row = enrollment(db, campaign, customer)
            row.id = "55555555-5555-4555-8555-555555555555"
            row.barcode_token = "synthetic-fixture-only-not-valid-for-redemption"
            row.enrolled_at = datetime(2026, 9, 1)
            db.add(
                m.Movement(
                    customer_id=customer.id,
                    campaign_id=campaign.id,
                    type="earn",
                    points_delta=320,
                    description="Synthetic example",
                )
            )
            db.commit()
            return build_points_pass(
                db, merchant, campaign, customer, row, campaign.design, "1234567890"
            )
    finally:
        settings.public_api_url = original_url
        engine.dispose()


if __name__ == "__main__":
    target = ROOT / "docs" / "examples" / "points-pass.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(
        json.dumps(example_payload(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "Generated docs/examples/points-pass.json from the production builder and synthetic fixtures."
    )
