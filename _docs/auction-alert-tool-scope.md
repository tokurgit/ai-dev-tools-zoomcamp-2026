# Latvian Real Estate Auction Alert Tool — Project Scope

Source site: https://izsoles.ta.gov.lv/

## Purpose
A tool that monitors the Latvian government e-auction site (izsoles.ta.gov.lv) and notifies users when new or updated real estate auction listings match their personal saved filter criteria.

## Data Source
The site publishes an official open data feed, refreshed once daily:

- `https://izsoles.ta.gov.lv/open_data/izsoles.csv` — all registered auction listings
- `https://izsoles.ta.gov.lv/open_data/kategorija.csv` — property category codes
- `https://izsoles.ta.gov.lv/open_data/region.csv` — region codes
- `https://izsoles.ta.gov.lv/open_data/birojs.csv` — auction organizers (ZTI/MPA/etc.)

Note: a direct fetch from this sandbox was blocked by bot detection — worth re-testing with proper headers/from the VPS itself during implementation. No scraping should be needed if the CSV feed works as documented.

## Scope Decisions

| Area | Decision |
|---|---|
| Auction type | Real estate only (Nekustamie īpašumi) |
| Relevance definition | Combination of filters, user-configurable (region, category, price range, etc.) |
| Users | Multi-user; each user can have multiple saved filter profiles |
| Filter management | Web UI with login; forms to build/edit/delete filter profiles |
| Alert types (per profile, configurable) | New listing / price or status change / deadline-approaching reminder — any combination |
| Notification channel | Email for v1 (via Resend or Postmark, not raw SMTP from the VPS); architecture should allow adding Telegram/SMS later without a rewrite |
| Notification timing | Configurable per user (immediate vs. digest) — though real-world difference is minor since source data only updates daily |
| Target scale | Handful of users for now (not over-engineered for growth) |

## Technical Stack

| Layer | Choice | Notes |
|---|---|---|
| Backend framework | Django | Built-in admin, ORM, easy scheduled jobs via management commands |
| Database | SQLite | Sufficient for daily-cron + few-user workload; easy to migrate to Postgres later if needed |
| Frontend | Django templates + HTMX | Server-rendered, minimal JS, but dynamic enough for a filter-builder UI |
| Scheduled job | Django management command + system cron | Fetches CSV daily, diffs against DB, matches against user filters, queues notifications. No Celery/Redis needed at this scale. |
| Email | Resend or Postmark (transactional email API) | Better deliverability than sending raw SMTP from a VPS IP |
| Hosting | Hetzner CX22 VPS (~€4–5/mo) | Ubuntu 24.04 LTS |
| App server | Gunicorn + Nginx reverse proxy | Standard Django deployment |
| TLS | Let's Encrypt via Certbot | Free, auto-renewing |
| Backups | Hetzner automated snapshots | Covers the SQLite DB file |

## Rough Architecture Flow
1. Daily cron triggers a Django management command
2. Command downloads/parses `izsoles.csv` (+ supporting reference CSVs)
3. New/changed listings are diffed against the local DB
4. Each user's saved filter profiles are checked against new/changed listings
5. Matches are queued as notifications
6. Notification sender dispatches emails (immediate or batched into a digest, per user preference)

## Open Items / Next Steps
- Confirm CSV feed is accessible without bot-detection issues from the VPS
- Inspect actual CSV column structure to finalize the Listing data model
- Design Django models: User, FilterProfile, Listing, ListingChange, Notification
- Decide on user signup flow (self-registration vs. invite-only, given small user count)
