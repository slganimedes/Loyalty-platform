# SME Loyalty Platform

## Project context
Loyalty program management platform for SMEs (pilot / MVP), offered as part of the Getnet
value proposition. Customers get an Apple/Google **Wallet pass** (no app); payment transactions
(Getnet, ecommerce or other systems) are the input that automatically rewards them.
State: **MVP / pilot**, single developer.

Full spec lives in `docs/PRD.md`. Step-by-step build plan in `docs/MVP_Runbook.md`.
Deployment (Unraid + Cloudflare Tunnel, domain `slmartinez.org`) in `docs/Unraid_Cloudflare.md`.
**Read those before large changes.**

## Tech stack
- Backend: **Python + FastAPI** (single API for admin web + transaction ingestion)
- DB: **SQLite** (file in `/data`), via SQLAlchemy
- Passes: Apple Wallet (`.pkpass`, PassKit) + Google Wallet API
- Admin web: **React SPA** (Vite) consuming the same API; bilingual **ES/EN**
- Packaging: **Docker Compose**, single mono-repo
- Deploy: **Unraid** at home, exposed via **Cloudflare Tunnel** (no open ports)

## Structure
- `api/app/models/`   – SQLAlchemy tables (merchant, admin_user, customer, pass, campaign, coupon, transaction, movement, wallet_config)
- `api/app/schemas/`  – Pydantic models
- `api/app/routers/`  – endpoints
- `api/app/services/` – matching, loyalty engine, pass generation
- `admin-web/`        – admin console (ES/EN)
- `data/`             – SQLite DB + assets (logos, certs) — gitignored
- `docs/`             – PRD, runbook, deployment guide

## Commands
```bash
# dev (from api/)
uvicorn app.main:app --reload        # dev server → http://localhost:8000/docs
# full stack
docker compose up --build            # api + admin-web (+ cloudflared in prod)
```

## Conventions
- Type hints on all functions; Pydantic for I/O validation.
- API base path: `/api/v1`. OpenAPI auto-generated (check at `/docs`).
- Single ingestion endpoint `POST /transactions` shared by Getnet / ecommerce / other.
  - Idempotent by `external_transaction_id`.
  - Customer matching priority: `card_hash → customer_number → email → dni`.
  - No match → store as `unmatched`, no accrual.
- Three campaign types: points-per-spend, interaction stamp-card, coupons (configurable per merchant).
- Every balance change writes a `movement` row (functional traceability).
- Admin web must expose the **same operations** as the API. Two roles: super_admin, sme_admin.

## Hard constraints (do not violate)
- **Never store the PAN in clear** — only an irreversible hash. Never log full PAN.
- **Never commit secrets** — `.env`, `.p12`, service-account JSON live only in Unraid `appdata`.
- Pass web-service URLs must use the **public HTTPS domain** (`https://api.slmartinez.org`), never a local IP.
- MVP decision: ingestion endpoint has **no auth** — protect it at the network layer (Cloudflare WAF/Access). Don't add auth without discussing.
- Points do not expire and there are no refunds/reversals in the MVP.

## Definition of done
A task is complete when:
1. The API starts and `/docs` loads with no errors.
2. New endpoints are tested (happy path + no-match / duplicate cases where relevant).
3. `docker compose up --build` runs the full stack locally.
4. No secrets added to git; `.env.example` updated if new variables were introduced.

## Current focus
Bootstrapping the MVP: project scaffolding → backend core (models + merchant/customer/loyalty engine)
→ wallet integrations → ingestion → admin web → Docker → deploy on Unraid.

## Notes for the assistant
- Never push or publish to GitHub unless the user explicitly requests it.
- Campaign passes, deletion and installation URL/QR behavior: `docs/CAMPAIGN_PASSES.md`.
- Standalone production Compose with standard images and GitHub source: `docs/COMPOSE_DEPLOYMENT.md`.
- Ask before cross-file refactors or adding new dependencies.
- Prefer small, verifiable steps; show the diff.
- When unsure about business rules, check `docs/PRD.md` instead of guessing.
