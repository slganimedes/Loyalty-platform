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

The test configuration uses **`AUTH_ENABLED=false`** for anonymous business API
requests, including payments, Wallet settings and Apple callbacks. **The admin web
always requires a username and password**; login, profile and logout keep real sessions.
Authenticated requests retain the user's merchant permissions. Anyone with the API
URL can still read and modify data anonymously in this test mode; the panel login
does not restrict that API access. Set `AUTH_ENABLED=true` to protect business API calls too.

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
docker compose -f docker-compose.unraid.yml up -d --wait --wait-timeout 600 api admin-web
```

Try the API at **http://localhost:8000/docs** and the Docker admin at
**http://localhost:8080**. Set `DATA_DIR=./data`, `CERTS_DIR=./data/certs`,
`API_PORT=8000` and `ADMIN_PORT=8080` in existing local `.env` files (new ones
include these defaults). The command above starts the application without the tunnel.
On Unraid, **Compose Up starts Cloudflare automatically**. To run a dedicated local
tunnel too, configure its token and omit `api admin-web` from the command.
Both environments download the same pinned GitHub release. Sign in using the bootstrap
username and generated password in `.env`, even with `AUTH_ENABLED=false`.
`BOOTSTRAP_ADMIN_PASSWORD` creates a missing account; changing it does not overwrite
the password of an existing account.

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
docker-compose.unraid.yml   single stack for Unraid and local Docker, including Cloudflare
.env.example    Copy to .env and fill in
CLAUDE.md       Briefing for the IDE AI agent (Claude Code)
.github/copilot-instructions.md   Instructions for Copilot Agent Mode
.vscode/settings.json             Agent auto-approval settings
```

## Deployment
For standalone deployment using **standard container images and source downloaded
from GitHub**, use `docker-compose.unraid.yml` in both environments and follow
[the Compose deployment guide](docs/COMPOSE_DEPLOYMENT.md).
For unpublished changes, use native development or `python scripts/check_deployment.py`,
which validates the working tree with isolated data using this same Compose.

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
- `AUTH_ENABLED=false` opens business API and Apple calls for platform testing.
  Admin login, `/users/me` and logout remain protected. `true` protects business calls too.
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
(paths relative to the repository root). Both Unraid and local Docker use only
`docker-compose.unraid.yml`. Edit `x-installation` privately in Unraid; locally use
`.env` for paths, ports and credentials. See the Compose guide for both commands.
Do not publish private settings.

For the four-button Unraid Compose Manager editor, paste `docker-compose.unraid.yml`
into **Compose File**, fill its installation settings and leave **Env File** empty.
The tunnel starts automatically; diagnostic ports bind only to loopback (18000/18080). See
[the Unraid editor instructions](docs/COMPOSE_DEPLOYMENT.md#unraid-los-cuatro-botones-del-editor).
