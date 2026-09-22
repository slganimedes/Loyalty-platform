"""Explicit image/membership setup for regression scenarios written before enrollments."""

import io

from PIL import Image


def image_data(color="red", format="PNG"):
    output = io.BytesIO()
    Image.new("RGB", (32, 20), color).save(output, format=format)
    return output.getvalue()


def design(client, mid):
    ids = []
    for color in ("red", "blue"):
        response = client.post(
            f"/api/v1/merchants/{mid}/pass-assets",
            content=image_data(color),
            headers={"Content-Type": "image/png"},
        )
        assert response.status_code == 201, response.text
        ids.append(response.json()["id"])
    return {
        "logo_asset_id": ids[0],
        "hero_asset_id": ids[1],
        "background_color": "#373839",
        "logo_description": "Test logo",
        "hero_description": "Test hero",
    }


def create_campaign(client, path, *, json):
    mid = path.split("/")[-2]
    customers = client.get(f"/api/v1/merchants/{mid}/customers").json()
    body = {
        **json,
        "design": design(client, mid),
        "customer_ids": [c["id"] for c in customers] if json.get("active", True) else [],
    }
    return client.post(path, json=body)
