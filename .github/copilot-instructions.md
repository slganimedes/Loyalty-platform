# AI Agent Instructions — SME Loyalty Platform
# The agent reads this on EVERY request. Keep it authoritative.

## Source of truth
- The full specification is in `docs/PRD.md`. Treat it as the contract.
- Build order and deployment: `docs/MVP_Runbook.md`, `docs/Unraid_Cloudflare.md`.
- If anything is ambiguous, prefer the PRD; only ask if a decision blocks progress.

## What we are building
A pilot loyalty platform for SME (Getnet) merchants: wallet passes (Apple + Google)
as the customer UX, payment transactions as the input to award points/stamps/coupons.
Single API serves both the admin web and transaction ingestion. Deployed via docker-compose
on Unraid, exposed through Cloudflare Tunnel (domain slmartinez.org).

## Tech stack
- Backend: Python + FastAPI, SQLAlchemy, Pydantic.
- Database: SQLite (file in /data).
- Admin web: lightweight SPA (React) or static; bilingual ES/EN.
- Packaging: Docker + docker-compose. Cloudflare Tunnel for public HTTPS.
- Auth: username/password for admin (argon2/bcrypt). Ingestion endpoint has NO auth in the pilot.

## Project structure
- api/app/{models,schemas,routers,services}
- admin-web/  frontend
- data/       SQLite DB, assets, certs (git-ignored)
- docs/       PRD, runbook, deployment guide

## Conventions
- Type hints everywhere; format with ruff/black.
- REST routes under /api/v1 (PRD §10). OpenAPI auto-generated.
- Ingestion POST /transactions: idempotent by external_transaction_id;
  matching priority card_hash → customer_number → email → dni; no match → unmatched.
- Every points change writes a movement row.
- Never store PAN in clear — only an irreversible hash.
- Admin web bilingual ES/EN, language persisted per user, default ES.
- Wallet config: independent apple_enabled / google_enabled toggles; secrets write-only.
- Never commit secrets; they live in /data (git-ignored) and .env.

## Commands
- pip install -r api/requirements.txt
- (from api/) uvicorn app.main:app --reload   → http://localhost:8000/docs
- (from api/) python seed.py                   → demo data (credentials from .env)
- (from api/) pytest -v
- docker compose up -d --build

## Definition of done
1. docker compose up starts api + admin-web with no errors.
2. GET /health returns ok; /docs loads.
3. The four scenarios pass via pytest: points-per-spend, ecommerce, idempotency/unmatched, coupon.
4. Admin web performs API operations and switches ES/EN.
5. No secrets in git; .env.example updated if new vars added.

## Do NOT
- Do not push or publish to GitHub without an explicit user instruction.
- Do not invent scope beyond the PRD (Phase 2 items are OUT).
- Do not run destructive commands (rm -rf, sudo, git push --force).
- Do not commit secrets or the SQLite DB.
