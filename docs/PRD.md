# PRD — SME Loyalty Platform (MVP / Pilot)

> Condensed reference for the AI agent and developer. Owner: S. L. Martínez Fernández.
> Domain: **slmartinez.org**. Deploy: **Unraid + Cloudflare Tunnel**.

## 1. Purpose & rationale
Loyalty platform for SME (Getnet) merchants. Customers get an Apple/Google **Wallet pass**
(no app); **payment transactions** (Getnet/ecommerce/other) automatically reward them.
**Core driver: merchant retention** — move the acquiring relationship away from price-only
competition by bundling a value-added loyalty service.

Future layers (OUT of MVP): cross-merchant proximity offers; business intelligence for merchants.

## 2. Goal of the MVP
Register merchants, customers and campaigns; explicitly assign campaign passes
to customers, then accrue rewards per transaction and update the assigned passes.

## 3. Roles
- **Super Admin** (bank): all merchants + wallet config.
- **SME Admin** (merchant): own merchant only.
- **End customer**: interacts only via the wallet pass (no login).
Admin auth: username + password.

## 4. Key decisions (locked)
1. Customers unique per merchant.
2. Admin web exposes the same operations as the API.
3. Single API for admin + ingestion.
4. PAN never stored in clear — irreversible hash only.
5. Points don't expire; no refunds/reversals in MVP.
6. Real-time pass update on every change.
7. Ingestion endpoint has NO auth in the pilot (protect at network layer).
8. SQLite + docker-compose.
9. Wallet config in admin web with independent Apple/Google toggles.
10. Admin web bilingual ES/EN, persisted per user, default ES.

## 5. Loyalty engine — 3 campaign types
- **points_per_spend**: `{points, amount_unit, rounding}` (e.g. 1 pt / 10 €).
- **interaction** (stamp-card): `{interactions_required, reward_description}`.
- **coupon**: `{amount}` issued to a customer; auto-redeemed at payment/QR.

## 6. Transaction ingestion (POST /transactions)
- Same contract for Getnet / ecommerce / other.
- Idempotent by `external_transaction_id`.
- Matching priority: card_hash → customer_number → email → dni (scoped to merchant).
- No match → stored as `unmatched`, no accrual.
- On accrual → update pass in real time.

## 7. Passes
Passes belong to campaigns and are explicitly assigned to customers of the same merchant.
One active pass per customer/campaign/provider; enrollment never creates passes automatically.
Admin shows the installation URL and its QR. The QR inside a pass identifies the customer.
Content: campaign name and balance, merchant name, campaign movements, customer code, QR.
Customers/campaigns can be soft-deleted and passes revoked; Google receives INACTIVE,
Apple receives a voided pass and APNs notification. Failed revocations retry durably.
Existing passes without a campaign remain labelled legacy; no automatic reassignment.
See [campaign pass behavior](CAMPAIGN_PASSES.md) for endpoints and retention semantics.
Per-merchant branding: color, name, logo. Real-time update (Apple APNs + web service; Google API patch).

## 8. Data model (SQLite)
merchant, admin_user, wallet_config, customer, pass, campaign, coupon, transaction, movement.
See `api/app/models/__init__.py` for the authoritative schema.

## 9. API (base /api/v1)
- POST/GET/PATCH /merchants[...]
- POST/GET /merchants/{id}/customers ; GET /customers/{id}[/movements|/passes]
- POST/GET /merchants/{id}/campaigns
- POST/GET /merchants/{id}/coupons
- POST /transactions
- GET/PUT /settings/wallet[/apple|/google]
- POST /auth/login, PATCH /users/me {language}

## 10. Security posture (MVP)
- PAN hash only (HMAC-SHA256 keyed by PAN_HASH_SECRET) — validate with bank before prod.
- Ingestion endpoint unauthenticated → restrict via Cloudflare WAF/Access.
- Admin passwords hashed (bcrypt/argon2). TLS everywhere (Cloudflare edge).
- Pre-production: add API-key/mTLS to ingestion; full GDPR; audit logging.

## 11. Deployment
Unraid (Docker Compose Manager) + Cloudflare Tunnel. Public hostnames:
`api.slmartinez.org` → api:8000 ; `admin.slmartinez.org` → admin-web:80.
Pass web-service URLs must use the public HTTPS domain, never a local IP.
Use standalone `docker-compose.deploy.yml` with standard Python/Node/Nginx images;
source is downloaded from a pinned GitHub commit. No custom application images required.
See [Compose deployment](COMPOSE_DEPLOYMENT.md), `Unraid_Cloudflare.md` and `DEPLOYMENT_README.md`.
Do not publish to GitHub without an explicit user request.
