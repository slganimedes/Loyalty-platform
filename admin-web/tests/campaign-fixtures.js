import { expect } from "@playwright/test";

export const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAACAAAAAUCAIAAABj86gYAAAALElEQVR4nGP8z0BbwERj8xlGLSAIRoOIIBgNIoJgNIgIgtEgIghGg4iBEAAAKwkBJ9coQEsAAAAASUVORK5CYII=", "base64");

export async function createCampaign(request, mid, headers, body) {
  const assets = [];
  for (let i = 0; i < 2; i++) {
    const response = await request.post(`/api/v1/merchants/${mid}/pass-assets`, {headers: {...headers, "Content-Type": "image/png"}, data: png});
    expect(response.status()).toBe(201); assets.push((await response.json()).id);
  }
  const customers = await (await request.get(`/api/v1/merchants/${mid}/customers`, {headers})).json();
  const response = await request.post(`/api/v1/merchants/${mid}/campaigns`, {headers, data: {...body, design: {logo_asset_id: assets[0], hero_asset_id: assets[1], background_color: "#373839"}, customer_ids: customers.map(c => c.id)}});
  expect(response.ok()).toBe(true);
  return response.json();
}

export async function fillDesign(page) {
  await page.getByLabel("Pass logo", {exact: true}).setInputFiles({name: "logo.png", mimeType: "image/png", buffer: png});
  await expect(page.getByLabel("Accessible logo description")).toBeEnabled();
  await page.getByLabel("Accessible logo description").fill("Merchant logo");
  await page.getByLabel("Hero image", {exact: true}).setInputFiles({name: "hero.png", mimeType: "image/png", buffer: png});
  await expect(page.getByLabel("Accessible hero description")).toBeEnabled();
  await page.getByLabel("Accessible hero description").fill("Rewards banner");
}
