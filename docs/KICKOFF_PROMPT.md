# Kickoff prompt for your IDE AI agent (Claude Code / others)

Paste this into the agent chat with the repo open.

---

You are continuing an existing MVP scaffold. Read `CLAUDE.md` and `docs/PRD.md` first.

**Goal:** finish the SME Loyalty Platform so that all items in the "Definition of done"
(in `.github/copilot-instructions.md` and `CLAUDE.md`) pass. Work autonomously, phase by
phase, running the validation commands after each phase and fixing errors yourself before
continuing. Do not ask me to confirm between phases unless a decision truly blocks you.

**Suggested order (much is already scaffolded):**
1. Verify the backend runs: `pip install -r api/requirements.txt`, then `pytest -v` (from api/). Fix any failures.
2. Extend the loyalty engine edge cases and add tests.
3. Implement Apple `.pkpass` generation + APNs update and Google Wallet object create/patch
   in `api/app/services/passes.py` (replace the stubs). Gate behind the wallet_config toggles.
4. Build the real admin web (React) replacing `admin-web/index.html`: login, merchants,
   customers, campaigns, coupons, wallet-config screen with independent toggles, ES/EN i18n.
5. Wire `.env`, confirm `docker compose up -d --build` runs the full stack.
6. Update `docs/DEPLOYMENT_README.md` if anything changed.

**Constraints:** never store PAN in clear; never commit secrets; the user's test configuration opens
all endpoints with `AUTH_ENABLED=false`. `true` restores Bearer/ApplePass protection.
See `CAMPAIGN_DESIGNS.md` for the explicit enrollment and design model, and `REDEPLOY_UNRAID.md` for redeployment.
Keep Phase 2 items (cross-merchant, BI) OUT of scope.

Start by running the tests and reporting what passes/fails.
