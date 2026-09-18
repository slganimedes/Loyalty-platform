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
