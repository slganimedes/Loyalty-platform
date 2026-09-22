# Running and deploying the MVP

For deployment from a standalone Compose file with standard images and source from
GitHub, use [COMPOSE_DEPLOYMENT.md](COMPOSE_DEPLOYMENT.md). Both Unraid and local
Docker use `docker-compose.unraid.yml` and download its pinned application release.

## Local Docker stack

Requirements: Python 3.12 for setup; a running Docker engine with Compose v2.
From the repository root:

```bash
python scripts/setup_env.py
docker compose -f docker-compose.unraid.yml config --quiet
docker compose -f docker-compose.unraid.yml up -d --wait --wait-timeout 600 api admin-web
docker compose -f docker-compose.unraid.yml ps -a
```

The setup script creates an ignored `.env` with random PAN-hashing and bootstrap
password values; it never prints secrets or overwrites an existing `.env`.
Sign in as `BOOTSTRAP_ADMIN_USERNAME` using `BOOTSTRAP_ADMIN_PASSWORD` from that
file. Startup creates this account only if it does not exist. Changing the variable
does not reset an existing account. There is no default `admin/admin` login.

- Admin: http://localhost:8080
- API health: http://localhost:8000/health
- API docs: http://localhost:8000/docs
- Both ports bind only to 127.0.0.1. Data persists in `./data`.
- Nginx proxies `/api/` and `/health` to the backend. SPA routes survive reloads.
- Wallet providers default to disabled; no Apple/Google accounts are required to
  run the admin, loyalty engine or tests.
- Existing local `.env` files need `DATA_DIR=./data`, `CERTS_DIR=./data/certs`,
  `API_PORT=8000`, `ADMIN_PORT=8080`; new files include them.
- Cloudflare starts by default on Unraid. The local command selects only `api admin-web`
  and their dependencies. Omit the service names to also start a configured tunnel.

For optional demo merchants and campaigns (POSIX shell):

```sh
docker compose -f docker-compose.unraid.yml exec api sh -c 'cd /source/$SOURCE_REF/api && /python-env/$SOURCE_REF/bin/python seed.py'
docker compose -f docker-compose.unraid.yml exec api sh -c 'cd /source/$SOURCE_REF/api && /python-env/$SOURCE_REF/bin/python create_admin.py shop-owner --merchant-id MERCHANT_UUID'
```

This prompts for a password and grants access only to that merchant. Super admins
can create merchants and change wallet settings; SME admins can manage their own
merchant branding, customers, campaigns and coupons. Admin sessions expire after
`SESSION_HOURS` (12 by default), are stored hashed in SQLite and revoked on logout.
The browser stores its bearer token in sessionStorage; language is persisted in
the user record and restored at login.

## Native development and validation

```bash
python -m pip install -r api/requirements-dev.txt
cd api
python -m pytest -v
python -m ruff check app tests seed.py create_admin.py
python -m ruff format --check app tests seed.py create_admin.py
python -m uvicorn app.main:app --reload --no-access-log
```

In another terminal:

```bash
cd admin-web
npm ci
npm run dev
```

Vite serves http://localhost:5173 and proxies API/health to localhost:8000.
Use `API_TARGET` to change that target. Node 20+ is required.
For reproducible browser validation:

```bash
cd admin-web
npm run build
npx playwright install chromium
npm run test:e2e
npm audit
```

Playwright starts its own API and Vite servers on ports 8015/5175 with a fresh
temporary SQLite database and synthetic test credentials. It exercises real HTTP
login, merchant editing, enrollment, campaigns, coupons, payment accrual,
idempotency, movements, wallet settings and persisted ES/EN language.

## Wallet setup

Use the super-admin Wallet settings page. Apple and Google are independent.
Values can come from `.env`; saved provider settings override those values.
Secrets are masked on reads; blank/masked fields preserve existing values on save.
Place credential files in ignored `data/certs`, mounted read-only at `/certs`.
Provider errors never roll back a committed payment; failed updates retain an
unsynced update tag. Use **Passes > URL and QR** to retry and obtain links for an assigned campaign pass.
Customer enrollment does not issue a pass; assign it explicitly from **Passes**.
See [CAMPAIGN_PASSES.md](CAMPAIGN_PASSES.md) for assignment, deletion and retry behavior.
No install link is returned for a provider that fails generation/creation.
The `pass_updated` ingestion flag means at least one provider update succeeded;
it does not prove delivery to a physical device.

### Apple

Required: Apple Developer membership, a Pass Type ID, Team ID, a matching signing
certificate and private key exported as `.p12`, and the appropriate Apple WWDR
intermediate certificate (PEM or DER).

```dotenv
APPLE_TEAM_ID=YOUR_TEAM_ID
APPLE_PASS_TYPE_ID=pass.org.slmartinez.loyalty
APPLE_CERT_PATH=/certs/pass.p12
APPLE_CERT_PASSWORD=
APPLE_WWDR_CERT_PATH=/certs/wwdr.pem
APPLE_WEBSERVICE_URL=https://api.slmartinez.org
```

`APPLE_WEBSERVICE_URL` is the public HTTPS **origin**, without the PassKit suffix.
The generated pass uses `/api/v1/wallet/apple` as its web-service base and contains
an opaque authentication token. PassKit registration, deregistration, changed
serial listings, authenticated downloads, Last-Modified/304 and diagnostic log
acknowledgment are implemented under that base's `/v1` routes. Diagnostics are
not persisted because device logs may contain personal data.

Conditional downloads also support weak ETags and `If-None-Match` precedence.
Date-only requests compare against the full-precision update timestamp and can
return the pass again when the HTTP date cannot distinguish same-second changes.
This prevents a newer balance from being hidden by an incorrect 304 response.
See [HTTP conditional requests](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.3).

Passes are ZIP archives with SHA-1 manifests and detached PKCS#7 signatures.
APNs uses HTTP/2 and the same signing certificate/private key; invalid device
registrations are removed. The certificate's identifier must remain consistent
for existing passes. Public URLs reject local IPs, localhost and HTTP.

Merchant logos uploaded through the admin are stored as PNG bytes in SQLite's
`merchant.logo_data` column. PNG/JPG/WebP inputs are normalized to PNG in the browser;
uploads are limited to 2 MB and 2048 × 2048 pixels. Create/PATCH accepts
`logo_base64` (raw PNG base64); omitting it preserves the image and explicit null
removes it. Responses expose a versioned `logo_url`, not the binary payload.
The existing public logo endpoint serves the stored image for Google Wallet and
the admin; Apple bundles include those same bytes. Legacy PNG paths relative to
`ASSETS_DIR` (`/data/assets` in Docker) remain supported until replaced by an upload.
Filesystem traversal is rejected. A brand-color icon is included by default.
Campaign name and balance, merchant name, color, logo, customer QR, campaign
movements and outstanding customer coupons appear on the pass. Changing merchant branding
refreshes its customer passes.

### Google

Required: Google Wallet issuer account, Wallet API enabled, and a service account
with issuer access. Supply `GOOGLE_ISSUER_ID` and
`GOOGLE_SA_JSON=/certs/google-sa.json`. The service creates one loyalty class per
campaign, creates a loyalty object per assignment, patches existing resources, and
returns a signed Save-to-Wallet JWT link valid for one hour. Regenerate expired
links from **Passes > URL and QR**. Legacy passes retain their original identifiers. Google review/publishing approval is still required for
public distribution. Public merchant logo URLs are served by the API.

Provider references:
- [Apple pass construction](https://developer.apple.com/documentation/walletpasses/building-a-pass)
- [Apple update protocol](https://developer.apple.com/library/archive/documentation/UserExperience/Conceptual/PassKit_PG/Updating.html)
- [Google loyalty classes and objects](https://developers.google.com/wallet/retail/loyalty-cards/use-cases/create)
- [Google Save-to-Wallet JWT](https://developers.google.com/wallet/retail/loyalty-cards/use-cases/jwt)

## Loyalty rules and ingestion

The requested test configuration sets `AUTH_ENABLED=false`: business API calls,
including payments, Wallet settings and Apple callbacks, allow anonymous access.
The admin panel always requires username/password; profile and logout always use a session.
`AUTH_ENABLED=true` also protects business API calls; external connectors then
authenticate and renew expired sessions. Do not place Cloudflare interactive
authentication in front of Apple callbacks, pass install links or public pass assets.
See [campaign designs and migration](CAMPAIGN_DESIGNS.md) for the updated model,
new upload limits, persistent storage, automatic pre-migration backup and rollback.
Follow [the Unraid redeployment steps](REDEPLOY_UNRAID.md) to install the published version.

- Identifiers are scoped to a merchant, with priority card hash, customer code,
  email, DNI. Enrollment and ingestion both accept only a lowercase 64-character
  HMAC-SHA256 `card_hash`, never a raw PAN. The trusted payment connector must
  compute that digest using the same `PAN_HASH_SECRET`; do not put this key in a
  browser or send PAN to the admin application. Keep the key stable for matching.
- Duplicate external IDs never accrue twice, even with concurrent requests.
  IDs are globally unique; reuse across merchants returns 409 without disclosing
  another merchant's customer.
- Unknown merchants return 404; inactive merchants reject new payments. Unmatched
  transactions are stored without earning rewards.
- Amounts are nonnegative decimal EUR values with at most two decimal places.
  Points use decimal math; `round` uses half-up rounding. Points never expire.
- Each active stamp campaign counts its own interactions. Stamps do not inflate
  the points balance. Every threshold records a reward movement with its configured
  description. Null/zero-amount interactions can earn stamps, but not spend points.
- Issued coupons redeem automatically on a matched payment, including matching by
  the customer code from the pass QR. Whole coupons are processed oldest first
  within the payment amount; oversized coupons remain issued. There is no partial
  redemption, cash change, refund or reversal. Accrual uses the submitted amount.
- Coupon and stamp/reward events, as well as every points change, have movements.

Run the Compose API with one Uvicorn worker. Wallet writes are ordered per customer
in that worker; multi-worker outbound delivery needs a shared delivery queue.

SQLite schema upgrades are additive at startup and preserve original scaffold
rows. Back up `data/loyalty.db` before upgrading. Legacy interaction movements
have no campaign association; only newly recorded stamps count toward thresholds.
Old enrollment hashes from the scaffold may have been double-hashed and must be
re-enrolled from a trusted connector if card matching fails.

## Unraid and Cloudflare

Keep `.env`, data and certificates in Unraid appdata. Configure the two tunnel
hostnames as documented in `Unraid_Cloudflare.md`, set the tunnel token, then run:

```bash
docker compose -f docker-compose.unraid.yml up -d --wait --wait-timeout 600
```

The tunnel routes `api.slmartinez.org` to `api:8000` and `admin.slmartinez.org` to
`admin-web:80`. No LAN/public ports are opened by Compose; only loopback ports are
published for host-local diagnostics. Apply the pilot ingestion network rules
before making either hostname public. Disable URL/query logging at external
proxies for pass links. API access logs and Nginx API access logs are disabled to
avoid logging pass download tokens.

## Validation recorded on 2026-09-18

The baseline had 6 passing tests. The expanded suite verifies real signatures
with generated test certificates, mock APNs/Google transports, role isolation,
concurrent ingestion and the loyalty edge cases. Real Apple/Google accounts,
physical phone installation and Cloudflare delivery require deployment credentials
and remain external acceptance checks.

Recorded results: **37 pytest tests passed**, **1 complete Playwright browser
workflow passed**, production Vite build passed, Ruff lint/format checks passed,
and `npm audit` reported **0 vulnerabilities**. Both default and tunnel-profile
Compose configuration checks passed. At that baseline, the workspace had no `.git`
directory; no commits were created and Git history could not be audited. Source scans found
no embedded private keys; generated environment values and data are ignored.

On resuming work on 2026-09-18, the Docker daemon responded successfully (Engine
29.8.0). The previously recorded Docker Desktop/WSL startup failure no longer
reproduces. `docker compose up -d --build --wait` completed successfully and both
`api` and `admin-web` reported healthy. The stack remains running locally.

HTTP checks returned 200 for API `/health`, `/docs`, `/openapi.json`, the admin
root, the `/customers` SPA fallback and the admin-proxied `/health`. Bootstrap
login, authenticated `/users/me` and `/merchants`, and logout also passed through
Nginx on port 8080 without printing credentials or tokens. The 37 pytest tests,
one Playwright workflow, production build and Ruff checks passed again. Both
Compose configuration profiles validated; the public tunnel was not started.

Remaining acceptance work: deploy on Unraid, configure Cloudflare and verify
both public hostnames from mobile data, then install and update passes on real
Apple/Google devices using provider credentials. Finally connect a pilot merchant's
trusted payment connector and verify accrual from an actual payment.

### Merchant logo uploads and payment simulation (2026-09-18)

Validation after adding database-backed logos and the customer payment selector:
**45 pytest tests passed**, **2 Playwright workflows passed**, production Vite
build and Ruff lint/format checks passed. Tests cover logo persistence/replacement/
removal, rejected uploads, merchant authorization, additive migration, inclusion
in signed Apple passes, selection of the merchant's customers, distinct payment
IDs after success and idempotent retry after losing a committed payment response.

A consistent SQLite backup was created in ignored `data/backups` before rebuilding
the running stack. `docker compose up -d --build --wait` completed with both services
healthy. HTTP checks verified admin routes, health, authenticated merchant listing
and the deployed logo upload schema. The workspace was initialized as a Git
repository for publication to `slganimedes/Loyalty-platform`; local environment,
database, backup, certificates and generated artifacts are excluded.

## Campaign passes validation (2026-09-20)

52 backend tests and 3 Playwright browser workflows passed, including explicit
assignment, installation URL/QR, campaign/customer deletion, provider revocation
retries, signed voided Apple passes and preservation of legacy records during
SQLite migration. Provider calls use test doubles; this does not assert delivery
to a physical wallet device. Ruff checks and the production Vite build passed.

`python scripts/check_deployment.py` successfully exercised the standalone Compose
using standard images and an isolated archive of the unpublished working tree:
source extraction, Python dependency installation, web compilation, healthchecks,
SPA routing and login/logout through Nginx. It used synthetic credentials and
removed only its own temporary Docker resources. GitHub publication was not performed.

The local stack was rebuilt and both services became healthy. A verified SQLite
backup was taken before the migration. Post-upgrade checks verified database
integrity, foreign keys, unchanged existing record counts and HTTP access to the
admin routes. No existing pass was revoked as part of deployment validation.


## Merchant deletion and installer validation (2026-09-20)

The backend suite passed 55 tests. The merchant/campaign subset passed again after
serializing merchant writes against deletion. Four browser workflows passed
(the three existing flows together, followed by the new merchant deletion flow).
Desktop/mobile screenshots were inspected, including cancellation and the impact
summary. Provider failures, authorization, stale summaries, access revocation and
preservation of history are covered using synthetic records.

The no-.env installer passed a complete isolated Compose deployment from a local
source archive: standard images, source extraction, dependency installation,
production build, health, API documentation/schema and login/logout. No real
merchant was removed. The local stack was rebuilt after a verified SQLite backup.
That historical installer has been superseded by `docker-compose.unraid.yml`,
the only Compose for both local and Unraid startup. Private configuration must not be committed.
