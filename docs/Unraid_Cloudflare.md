# Deployment on Unraid with Cloudflare Tunnel — slmartinez.org

## Subdomains
| Subdomain | Internal service | Use |
|---|---|---|
| `api.slmartinez.org` | `http://api:8000` | API: ingestion + Apple pass web service + Google Wallet |
| `admin.slmartinez.org` | `http://admin-web:80` | Admin console (ES/EN) |

One tunnel exposes both services.

## One-time setup
1. **Move DNS to Cloudflare**: add `slmartinez.org`, switch nameservers, wait for **Active**.
2. **Create the tunnel**: Zero Trust → Networks → Tunnels → Create (Cloudflared). Copy the **token** → `.env` as `CLOUDFLARE_TUNNEL_TOKEN`.
3. **Public hostnames** on the tunnel:
   - `api.slmartinez.org` → HTTP → `api:8000`
   - `admin.slmartinez.org` → HTTP → `admin-web:80`

## Unraid
- Install **Community Applications** → **Docker Compose Manager**.
- Put persistent data in appdata; map volumes:
  - `/mnt/user/appdata/loyalty-platform/data:/data`
  - `/mnt/user/appdata/loyalty-platform/certs:/certs`
- Place the real `.env` in that appdata folder (never in git).
- Paste this repo's `docker-compose.yml` into a new stack → **Compose Up**.

## Why no open ports
`api`/`admin-web` use `expose` plus loopback-only host ports. Only `cloudflared` makes an **outbound**
connection to Cloudflare. Result: zero inbound ports, IP never exposed, valid HTTPS at the edge.
Works even behind CGNAT.

## Protect the ingestion endpoint (pilot)
`POST /api/v1/transactions` has no auth. Add a **Cloudflare WAF** rule allowing only Getnet IPs
(when known), and/or **Cloudflare Access** on `admin.slmartinez.org`.

## Verify
From **outside your network** (mobile data): `https://api.slmartinez.org/docs` must load.
Apple/Google only talk to the public HTTPS URL — never the local IP.

Start the tunnel with `docker compose --profile tunnel up -d --build`.
Apply ingestion restrictions to both public hostnames because the admin host proxies `/api/`.


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
