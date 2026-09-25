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
Admin auth is mandatory: username + password and real sessions regardless of `AUTH_ENABLED`.

## 4. Key decisions (locked)
1. Customers unique per merchant.
2. Admin web exposes the same operations as the API.
3. Single API for admin + ingestion.
4. PAN never stored in clear — irreversible hash only.
5. Points don't expire; no refunds/reversals in MVP.
6. Real-time pass update on every change.
7. Business API endpoints are open in the default test mode; admin login/profile/logout remain protected. `AUTH_ENABLED=true` also requires authentication for business calls.
8. SQLite + docker-compose.
9. Wallet config in admin web with independent Apple/Google toggles.
10. Admin web bilingual ES/EN, persisted per authenticated user, default ES.

## 5. Loyalty engine — 3 campaign types
- **points_per_spend**: `{points, amount_unit, rounding}` (e.g. 1 pt / 10 €).
- **interaction** (stamp-card): `{interactions_required, reward_description}`.
- **coupon**: `{amount}` issued to a customer; auto-redeemed at payment/QR.

## 6. Transaction ingestion (POST /transactions)
- Business endpoints, including ingestion, accept anonymous calls in test mode (`AUTH_ENABLED=false`). Supplied sessions keep their merchant scope; `true` makes authentication mandatory for business calls too.
- Same contract for Getnet / ecommerce / other.
- Idempotent by `external_transaction_id`.
- Matching priority: card_hash → customer_number → email → dni (scoped to merchant).
- No match → stored as `unmatched`, no accrual.
- On accrual → update pass in real time.
- Optional `send_notification` (default false) with editable content records an outbox
  entry in the same transaction; a repeated payment cannot duplicate its notification.

## 7. Passes
Passes belong to campaigns and are explicitly assigned to customers of the same merchant.
One active pass per customer/campaign/provider; enrollment never creates passes automatically.
Admin shows the installation URL and its QR. The QR inside a campaign pass identifies its enrollment using an opaque token.
Content: campaign name and balance, merchant name, campaign movements, customer code, QR.
Customers/campaigns can be soft-deleted and passes revoked; Google receives INACTIVE,
Apple receives a voided pass and APNs notification. Failed revocations retry durably.
Existing passes without a campaign remain labelled legacy; no automatic reassignment.
See [campaign pass behavior](CAMPAIGN_PASSES.md) for endpoints and retention semantics.
Campaign creation includes logo/hero uploads, image descriptions, background color,
subheader, points/customer-since labels, QR alternate text and locale, with preview.
`cardTitle` comes from Merchant, `header` from Customer, and points from the campaign ledger.
Customer joining date is stored in the existing `customer.created_at`, optionally supplied
as `joined_on` during registration. The pass shows three month letters and year:
`ene 2020`, `sep 2026` (`Jan 2020`, `Sep 2026` in English). Enrollment timestamps remain separate.
Real-time update (Apple APNs + web service; Google API patch).

The **Notifications** menu sends personalized messages to campaign pass holders or
one pass. Includes search, shared ES/EN composer, placeholders, approximate Apple/
Google previews, confirmation, filtered history, user audit and configurable quotas.
Provider acceptance is distinguished from device delivery. Failed/uncertain provider
calls never reverse payments; unattempted deliveries survive restarts. See
[NOTIFICATIONS.md](NOTIFICATIONS.md) for contracts and provider limits.

## 8. Data model (SQLite)
merchant, admin_user, wallet_config, customer, pass, campaign, coupon, transaction, movement,
campaign_enrollment, pass_design, pass_asset, schema_migration,
notification, notification_delivery, pass_notification_state.
See `api/app/models/__init__.py` for the authoritative schema.

## 9. API (base /api/v1)
- POST/GET/PATCH /merchants[...]
- POST/GET /merchants/{id}/customers ; GET /customers/{id}[/movements|/passes]
- POST/GET /merchants/{id}/campaigns
- POST/GET /merchants/{id}/coupons
- POST /transactions
- GET/PUT /settings/wallet[/apple|/google]
- POST /auth/login, PATCH /users/me {language}
- GET /merchants/{id}/notification-campaigns, /notification-passes
- POST /merchants/{id}/notifications/preview ; POST/GET /merchants/{id}/notifications
- GET /merchants/{id}/notifications/{notification_id}

## 10. Security posture (MVP)
- PAN hash only (HMAC-SHA256 keyed by PAN_HASH_SECRET) — validate with bank before prod.
- API test mode (`AUTH_ENABLED=false`) permits anonymous business/Apple requests. The admin panel always requires credentials, and profile/logout always require a session. The panel login does not prevent direct anonymous API access in this mode. `true` also requires Bearer/ApplePass authentication for business requests.
- Admin passwords hashed (bcrypt/argon2). TLS everywhere (Cloudflare edge).
- Every notification is audited with sender, timestamp, content, recipients and outcome.
- Pre-production: add API-key/mTLS to ingestion; full GDPR; audit of remaining operations.

## 11. Deployment
Unraid (Docker Compose Manager) + Cloudflare Tunnel. Public hostnames:
`api.slmartinez.org` → api:8000 ; `admin.slmartinez.org` → admin-web:80.
Pass web-service URLs must use the public HTTPS domain, never a local IP.
Use the single `docker-compose.unraid.yml` for Unraid and local Docker with standard Python/Node/Nginx images;
source is downloaded from a pinned GitHub commit. No custom application images required.
See [Unraid redeployment](REDEPLOY_UNRAID.md), [Compose deployment](COMPOSE_DEPLOYMENT.md), `Unraid_Cloudflare.md` and `DEPLOYMENT_README.md`.
Do not publish to GitHub without an explicit user request.


## Merchant deletion, design and installation update

Merchant deletion is available to super admins with a server-generated impact
summary, stale-confirmation protection, cascading logical deletion and durable
Google/Apple revocation retries. History is retained. The admin uses red Getnet-inspired
accents, rounded surfaces, accessible focus and responsive navigation.
Public API documentation is available at `/docs` and linked from the API root
and admin. See `docs/CAMPAIGN_PASSES.md` and `docs/COMPOSE_DEPLOYMENT.md`
(paths relative to the repository root). Both Unraid and local Docker use only
`docker-compose.unraid.yml`. Edit `x-installation` privately in Unraid; locally use
`.env` for paths, ports and credentials. See the Compose guide for both commands.
Do not publish private settings.
