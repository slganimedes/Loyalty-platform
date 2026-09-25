# Wallet Notifications Center

The **Notifications / Notificaciones** menu supports a campaign audience or one
active pass. Pick a campaign, review the suggested message, click Send and confirm.
An extra acknowledgment is required above the large-audience threshold. Search by
name, email, pass ID, customer code, Wallet ID or enrollment QR token. Two passes
for one customer count as one estimated holder and two affected passes. Assigned
pass counts do not prove installation or that device notifications are enabled.

The ES/EN interface includes mobile layouts, provider previews and paginated
history with campaign, inclusive UTC date range and status filters. History
retains sender, timestamp, original content, rendered per-pass content, counts
and outcomes, including after logical customer/campaign deletion.

## Content

Types: `general_update`, `new_reward`, `points_earned`, `coupon_available`,
`coupon_expiring`, `custom`. These guide suggestions; they do not issue coupons,
change rewards or schedule expiry alerts. The existing data model has no coupon
expiry date or point reward eligibility, so suggestions do not invent these values.

Required title: 1–200 characters; message: 1–2000. Optional HTTP(S) link: up to
2048, without credentials. Optional additional preview text: up to 200. Limits
also apply after personalization. The 60/240 character warnings are product
readability recommendations. Google link markup escapes user-supplied content.

| Placeholder | Value |
| --- | --- |
| `{{customerName}}` | Customer name, falling back to customer code |
| `{{campaignName}}` | Campaign name; merchant name for legacy passes |
| `{{currentPoints}}` | Campaign ledger balance; total for legacy passes |
| `{{currentStamps}}` | Campaign's recorded stamp count |
| `{{rewardName}}` | Configured stamp reward description, or empty if absent |
| `{{amount}}` | Payment amount with two decimals; payments only |
| `{{pointsEarned}}` | This payment's earnings for this campaign; payments only |

Unknown/malformed placeholders are rejected. Each delivery stores a rendered
snapshot. Campaign preview uses one example; each recipient gets their own values.

## API

Paths start with `/api/v1/merchants/{merchant_id}`. All routes enforce existing
merchant authorization. The panel requires a session. Like other business APIs,
`AUTH_ENABLED=false` permits anonymous test calls, audited as `public-test`;
supplied SME sessions retain their scope. Use `AUTH_ENABLED=true` to require
sessions on direct API calls as well.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/notification-campaigns` | Campaigns and counts |
| GET | `/notification-passes?q=...&offset=0` | Search, 30 results per page |
| POST | `/notifications/preview` | Render draft and return audience revision/warnings |
| POST | `/notifications` | Record outbox request, HTTP 202 |
| GET | `/notifications` | Filters: `campaign_id`, `date_from`, `date_to`, `status`, `offset`, `limit` |
| GET | `/notifications/{id}` | Audit with per-pass results |

Example preview body:

```json
{
  "target_type": "campaign",
  "campaign_id": "campaign-id",
  "title": "{{campaignName}}",
  "message": "{{customerName}}, you have {{currentPoints}} points.",
  "url": "https://example.com/rewards",
  "preview_text": "See you soon",
  "type": "general_update"
}
```

For a pass, use `target_type: "pass"` and `pass_id`, omitting `campaign_id`.
To send, add unique `request_id` (8–100 characters), `expected_recipients` and
`audience_revision` from preview. Above the threshold add `confirm_mass_send: true`.
Changed audiences return 409, including changes with the same holder count.
Identical retries return the original record; conflicting key reuse returns 409.
Request quotas return 429; per-pass quotas produce audited skips. Preview sends
nothing. `NotificationService.sendToPass` and `sendToCampaign` use this same contract.

## Payments and delivery

`POST /transactions` accepts `send_notification` (default false) and `notification`
with the common content fields. Opt-in requires valid title/message. Payment,
movements and outbox commit together. After commit the pass balance update runs
before delivery; the worker also refreshes the pass before payment notifications.
Provider failures never reverse payment or points. Repeating
`external_transaction_id` cannot create a second notification. Unmatched payments
and customers without passes get a skipped audit entry. Responses include
`notification_id` and `notification_status` for tracking.

Immediate background processing and the 30-second maintenance worker drain up to
50 pending deliveries per invocation. SQLite write reservations serialize keys,
quotas and claims across API workers. Only one notification per pass is in flight.
Attempts are committed before contacting providers. Unattempted work survives
restarts. A timeout or sending claim older than ten minutes becomes `unknown`;
uncertain calls are not replayed automatically, preventing possible duplicates.

Statuses: `queued`, `sending`, `success`, `partial`, `failed`, `skipped`, `unknown`.
Success means provider acceptance, not device delivery/read confirmation. Reasons
explain disabled providers, absent devices, revocation, quotas and failures.
Provider exception text and credentials are never stored in audit/log output.

## Provider mapping

Apple stores a stable back field with `changeMessage: "%@"`. It commits the new
message/version before sending the existing empty APNs payload; link and additional
preview text are separate back fields. Messages survive ordinary balance updates.
No registered device is a skip; the message stays available on the pass. Identical
text may not trigger a visible change. Passes installed before this release may
need one refresh to acquire the stable field before displaying alerts. See
[Apple's update protocol](https://developer.apple.com/library/archive/documentation/UserExperience/Conceptual/PassKit_PG/Updating.html).

Google uses object `addMessage` with `messageType: TEXT_AND_NOTIFY` for GenericObject
and legacy LoyaltyObject, using delivery ID as message ID. To respect the ten-message
limit it retires only its own oldest messages, preserving the full local audit.
Ten messages belonging to other sources produce an explicit failure. Google
controls the lock-screen alert; composed content and link appear in pass details.
See [Google notifications and daily quotas](https://developers.google.com/wallet/generic/use-cases/trigger-push-notifications)
and [object message limits](https://developers.google.com/wallet/reference/rest/v1/genericobject).

## Configuration and migration

Settings are exposed in `.env.example` and Compose's `x-installation`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `NOTIFICATION_MASS_THRESHOLD` | 100 | Extra acknowledgment above this holder count |
| `NOTIFICATION_MAX_PASSES` | 5000 | Hard campaign request cap |
| `NOTIFICATION_SENDS_PER_HOUR` | 30 | Requests per merchant, rolling hour |
| `NOTIFICATION_PASSES_PER_HOUR` | 10000 | Affected passes per merchant, rolling hour |
| `NOTIFICATION_PASSES_PER_DAY` | 3 | Reservations/attempts per pass, rolling 24h; configurable 1–3 |

Manual and payment notifications share persistent quotas. Pending work reserves
capacity; dispatch rechecks daily limits for delayed queues. Failed/skipped
deliveries do not reserve future daily capacity. Payment quota failures are
audited without failing the payment.

Startup backs up populated SQLite databases, creates additive `notification`,
`notification_delivery`, `pass_notification_state` tables and records migration
`20260925_notifications`. Existing balances, passes and sessions are preserved.
Repeated startup is safe. Backups are beside the database under
`backups/before-20260925_notifications-*`. Stop writers before restoring a backup.

No runtime dependencies were added. Use the `SOURCE_REF` from the current published
Compose template. When upgrading from `b795b88005facab100a69bff759fc8e0b2842bc6`,
changing the reference is sufficient if default quotas are retained. The five new
Compose settings make those quotas configurable. See [Unraid upgrade differences](REDEPLOY_UNRAID.md).
Validate the local working tree with `python scripts/check_deployment.py`; use
`python scripts/check_deployment.py --published` to download and test the pinned
commit from GitHub. Both use isolated data and synthetic credentials.

Validation: `python -m pytest -q` in `api`; `npm run build` and
`npx playwright test` in `admin-web`. Provider tests use synthetic certificates
and mocked transports; browser tests use isolated data and disabled providers.
Final device verification requires real configured credentials and installed passes.
