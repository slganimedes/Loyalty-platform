# SME Loyalty Platform (MVP / Pilot)

Wallet-based loyalty for Getnet merchants. Customers get an Apple/Google **Wallet pass**
(no app); **payments** automatically reward them. Single **FastAPI** backend + **SQLite**,
packaged with **Docker Compose**, deployed on **Unraid** via **Cloudflare Tunnel**
(domain `slmartinez.org`).

The backend, authenticated React admin, signed Apple passes/APNs/PassKit, and Google
Wallet creation/updates are implemented. Real provider credentials are required for
phone delivery. The local Docker stack has been validated with both services healthy.
See `docs/DEPLOYMENT_README.md` for validation and deployment prerequisites.

## Quick start (local)

```bash
# 1) Generate ignored local environment, then start the backend
python scripts/setup_env.py
cd api
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python seed.py                     # optional demo merchants; credentials from .env
uvicorn app.main:app --reload --no-access-log

# 2) Tests
pytest -v

# 3) Admin SPA (React) — in another terminal
cd ../admin-web
npm ci
npm run dev            # http://localhost:5173  (proxies /api to the backend)

# 4) Full stack with Docker
cd ..
docker compose up -d --build
```

Try the API at **http://localhost:8000/docs** and the Docker admin at
**http://localhost:8080**. Ports bind only to loopback. Cloudflare is optional:
`docker compose --profile tunnel up -d --build`. Sign in using the bootstrap
username and generated password in `.env`.

## Merchant logos and payment simulation

In **Merchants**, select a PNG, JPG or WebP logo when creating or editing a merchant
(up to 2 MB and 2048 × 2048 pixels). The browser converts it to PNG; the API stores
the image bytes in SQLite. You can preview, replace or remove the logo, and both
Wallet providers use the stored image. Existing databases gain the logo column
automatically on startup; back up your database before upgrading.

In **Payments**, choose the merchant and one of its customers, enter the amount
and select the source. Payment IDs are generated automatically. Each successful
submission represents a new payment; retrying a failed request with unchanged
values reuses its ID while the form stays open to prevent duplicate rewards.

## Repo layout
```
api/            FastAPI backend (models, schemas, routers, services, tests)
admin-web/      Admin console — React SPA (Vite), bilingual ES/EN
data/           SQLite DB + assets + certs (git-ignored)
docs/           PRD, runbook, deployment guides, kickoff prompt
docker-compose.yml   api + admin-web + cloudflared (Unraid/Cloudflare)
.env.example    Copy to .env and fill in
CLAUDE.md       Briefing for the IDE AI agent (Claude Code)
.github/copilot-instructions.md   Instructions for Copilot Agent Mode
.vscode/settings.json             Agent auto-approval settings
```

## Deployment
For standalone deployment using **standard container images and source downloaded
from GitHub**, use `docker-compose.deploy.yml` and follow
[the Compose deployment guide](docs/COMPOSE_DEPLOYMENT.md).
`docker-compose.yml` remains the local development stack for unpublished changes.

## Campaign passes and deletion

Passes belong to campaigns and are assigned explicitly to customers. Customer
enrollment no longer issues passes. **Wallet passes** lets administrators select
campaign, customer and provider, then view the installation URL and scan its QR.
Customers, campaigns and passes can be deleted; affected passes are revoked with
Google/Apple, with persistent automatic retries if a provider is unavailable.
History is preserved. See [the functional guide](docs/CAMPAIGN_PASSES.md).

## Provider and network setup
See **`docs/Unraid_Cloudflare.md`** (Unraid + Cloudflare Tunnel, `slmartinez.org`) and
**`docs/DEPLOYMENT_README.md`** (setup, wallet credentials, validation and remaining acceptance checks).

## Security notes (pilot)
- PAN is stored only as an irreversible hash (`PAN_HASH_SECRET`).
- The ingestion endpoint (`POST /api/v1/transactions`) has **no auth** by design — protect it
  with Cloudflare WAF/Access. Add API-key/mTLS before production.
- Never commit `.env`, certificates, or the SQLite DB.

## Build it out with your AI agent
Open the repo in VS Code, then paste `docs/KICKOFF_PROMPT.md` into your agent (Claude Code,
etc.). It reads `CLAUDE.md` + `docs/PRD.md` automatically and continues the build.
