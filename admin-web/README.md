# Loyalty administration

React SPA with real API authentication, merchant scoping, ES/EN saved per user,
merchant branding, customer enrollment and movements, campaigns, coupons,
transaction ingestion and independent Apple/Google configuration.

```bash
npm ci
npm run dev
npm run build
npx playwright install chromium
npm run test:e2e
```

Requires Node 20+. Vite proxies `/api` and `/health` to the backend at localhost:8000
(or `API_TARGET`). Production uses Nginx and the same-origin `/api/v1` base.
See `../docs/DEPLOYMENT_README.md` for credentials, roles, wallet setup and deployment.

Passes belong to campaigns. In **Passes**, select a campaign, customer and provider
to assign a pass and display its installation URL and locally generated QR.
Customer enrollment alone does not create passes. Customers, campaigns and passes
can be deleted with confirmation; pending provider revocations remain visible.
See [campaign pass behavior](../docs/CAMPAIGN_PASSES.md) and
[standalone Compose deployment](../docs/COMPOSE_DEPLOYMENT.md).


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
