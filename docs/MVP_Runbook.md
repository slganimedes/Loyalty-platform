# MVP Build Runbook (solo developer)

Two tracks run in parallel: **A. Build** (offline with mock data) and **B. Accounts**
(Apple/Google — start day 1, slow approvals). Each phase ends with a testable checkpoint.

## Track B — start now (critical path)
- Apple Developer Program → Pass Type ID + signing cert (.p12) + Team ID + APNs.
- Google Cloud → enable Google Wallet API → Issuer account → service-account JSON.
- Cloudflare → move `slmartinez.org` DNS, create tunnel, copy token.

## Phases
0. **Foundations** — Git, Python 3.12, Docker, VS Code. Create repo. ✅ tools respond.
1. **Backend skeleton** — FastAPI `/health` + `/docs`. ✅ already done in `api/`.
2. **Data model** — SQLite tables. ✅ `api/app/models`, `python seed.py`.
3. **Admin endpoints** — merchants/customers. ✅ `routers/merchants.py`.
4. **Loyalty engine + ingestion** ⭐ — `POST /transactions`. ✅ `services/loyalty.py`, tests pass.
5. **Wallet passes** (needs Track B) — Apple `.pkpass`+APNs and Google Wallet object
   create/patch implemented and tested with synthetic credentials/mock transports.
   Real phone installation and updates remain pending.
6. **Admin web** — ✅ React SPA with login, merchant/customer/campaign/coupon/payment
   operations and ES/EN; complete browser workflow passes.
7. **Wallet config screen** — ✅ Super Admin saves Apple/Google creds, independent toggles.
8. **Docker** — ✅ `docker compose up -d --build --wait` validated on 2026-09-18;
   both services healthy, HTTP and authentication through Nginx verified.
9. **Deploy on Unraid** — pending: Cloudflare Tunnel, verify from mobile data.
10. **Pilot** — pending: one real merchant; connect Getnet to the ingestion endpoint.

## What's already implemented in this scaffold
- FastAPI app, SQLite models, merchant/customer/campaign/coupon endpoints.
- Loyalty engine (points-per-spend, interaction, coupon) + idempotent ingestion + matching.
- PAN hashing (HMAC-SHA256), admin password hashing (bcrypt).
- Signed Apple passes, APNs/PassKit service and Google Wallet REST integration, gated independently.
- React admin with authentication and persisted ES/EN, Docker packaging and browser tests.

## Definition of done
`docker compose up` runs the stack; `/health` + `/docs` respond; `pytest` green (45 tests);
admin web does what the API does and switches ES/EN; no secrets in git.
