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
8. **Docker** — ✅ `docker compose -f docker-compose.unraid.yml up -d --wait --wait-timeout 600 api admin-web` uses the single Unraid/local Compose;
   both services healthy, HTTP and authentication through Nginx verified.
9. **Deploy on Unraid** — pending: Cloudflare Tunnel, verify from mobile data.
10. **Pilot** — pending: one real merchant; connect Getnet to the ingestion endpoint.

## What's already implemented in this scaffold
- FastAPI app, SQLite models, merchant/customer/campaign/coupon endpoints.
- Loyalty engine (points-per-spend, interaction, coupon) + idempotent ingestion + matching.
- PAN hashing (HMAC-SHA256), admin password hashing (bcrypt).
- Signed Apple passes, APNs/PassKit service and Google Wallet REST integration, gated independently.
- React admin with authentication and persisted ES/EN, Docker packaging and browser tests.
- Notifications Center, personalized campaign/pass sends, optional payment messages,
  durable history/outbox, provider adapters and quotas. See [NOTIFICATIONS.md](NOTIFICATIONS.md).

## Definition of done
`docker compose -f docker-compose.unraid.yml up` runs the stack; `/health` + `/docs` respond; `pytest` green (132 tests);
admin web does what the API does and switches ES/EN; no secrets in git.

Latest browser validation: 7 authenticated-mode workflows plus 1 public-mode
workflow passed. Wallet device delivery still requires real provider credentials.

## Campaign passes and standalone deployment (2026-09-20)

Passes are assigned explicitly to a customer and campaign. The admin displays
installation URLs and QR codes and supports deletion of customers, campaigns and
passes with durable provider revocation retries. Existing unassociated passes are
retained as legacy. See [CAMPAIGN_PASSES.md](CAMPAIGN_PASSES.md).

Use [COMPOSE_DEPLOYMENT.md](COMPOSE_DEPLOYMENT.md) for standard containers that
download source from GitHub. Publication requires an explicit user request.


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
# Actualización: diseño de campañas e inscripciones (2026-09-21)

El flujo actual crea campañas con su diseño, imágenes, color y clientes opcionales.
Los puntos proceden del ledger por cliente/campaña. El modo de prueba `AUTH_ENABLED=false`
abre la API de negocio y callbacks Apple; el panel siempre exige contraseña y sesión.
`true` protege también la API de negocio. El alta del cliente admite
fecha y el pase muestra mes de tres letras y año desde su alta en el comercio.
Consultar [CAMPAIGN_DESIGNS.md](CAMPAIGN_DESIGNS.md) para arquitectura, endpoints,
migración automática, backup/rollback, fixtures y compatibilidad del despliegue.
