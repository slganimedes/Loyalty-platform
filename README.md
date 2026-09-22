# SME Loyalty Platform (MVP / Pilot)

Wallet-based loyalty for Getnet merchants. Customers get an Apple/Google **Wallet pass**
(no app); **payments** automatically reward them. Single **FastAPI** backend + **SQLite**,
packaged with **Docker Compose**, deployed on **Unraid** via **Cloudflare Tunnel**
(domain `slmartinez.org`).

The backend, authenticated React admin, signed Apple passes/APNs/PassKit, and Google
Wallet creation/updates are implemented. Real provider credentials are required for
phone delivery. The local Docker stack has been validated with both services healthy.
See `docs/DEPLOYMENT_README.md` for validation and deployment prerequisites.

Campaign creation now includes a pass designer (logo, hero, color, preview and
optional customers). Customers enroll explicitly in one or more campaigns of
their merchant; points come from each campaign's ledger. See the complete
[design, API, migration and rollback guide](docs/CAMPAIGN_DESIGNS.md) and the
[generated points-pass example](docs/examples/points-pass.json).

The published test configuration uses **`AUTH_ENABLED=false`**: the admin opens
without login and every API endpoint accepts requests without authentication,
including payments, Wallet settings and Apple callbacks. Anyone with the URL can
read and modify data. Set `AUTH_ENABLED=true` to restore sessions and tenant authorization.

The campaign designer requests logo, hero, accessible descriptions, background color,
customer label, points label, customer-since label, QR text and pass language.
Merchant name, customer name, campaign points and generated identifiers come from
the database. Customers can enter a joining date at registration (`joined_on`);
it is stored in the existing `Customer.created_at` and displayed as **`sep 2026`**.
This is the customer's date at the merchant, not the campaign enrollment date.

Campaigns without a design are inactive drafts; customers without campaigns are
pending. Existing balances, passes, images and joining dates are preserved.
For redeployment, follow [the Unraid update instructions](docs/REDEPLOY_UNRAID.md).

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
username and generated password in `.env` only if `AUTH_ENABLED=true`; the default
test mode opens the admin immediately.

## Merchant logos and payment simulation

In **Merchants**, select a PNG, JPG or WebP logo when creating or editing a merchant
(up to 2 MB and 2048 × 2048 pixels). The browser converts it to PNG; the API stores
the image bytes in SQLite. You can preview, replace or remove the logo, and both
legacy Wallet passes use the stored image. New campaign passes use the campaign's
own uploaded logo and hero. Existing databases gain the logo column
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
- `AUTH_ENABLED=false` deliberately opens **all** API routes for platform testing.
  `AUTH_ENABLED=true` restores Bearer sessions, merchant authorization and ApplePass tokens.
- Never commit `.env`, certificates, or the SQLite DB.

## Build it out with your AI agent
Open the repo in VS Code, then paste `docs/KICKOFF_PROMPT.md` into your agent (Claude Code,
etc.). It reads `CLAUDE.md` + `docs/PRD.md` automatically and continues the build.


## Merchant deletion, design and installation update

Merchant deletion is available to super admins with a server-generated impact
summary, stale-confirmation protection, cascading logical deletion and durable
Google/Apple revocation retries. History is retained. The admin uses red Getnet-inspired
accents, rounded surfaces, accessible focus and responsive navigation.
Public API documentation is available at `/docs` and linked from the API root
and admin. See `docs/CAMPAIGN_PASSES.md` and `docs/COMPOSE_DEPLOYMENT.md`
(paths relative to the repository root). For installation without `.env`, copy
`docker-compose.install.yml` to a private file and fill in `x-installation`.
Regenerate that template with `python scripts/render_install_compose.py` after
changes to the canonical Compose. Do not publish the private settings.

For the four-button Unraid Compose Manager editor, paste `docker-compose.unraid.yml`
into **Compose File**, fill its installation settings and leave **Env File** empty.
The tunnel starts automatically and no host ports are published. See
[the Unraid editor instructions](docs/COMPOSE_DEPLOYMENT.md#unraid-los-cuatro-botones-del-editor).
