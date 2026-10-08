# TallyOS: barbershop ERP with a self-driving Google Ads loop

A mobile-first web app (installable PWA) for running a barbershop: bookings, clients,
checkout, inventory, finances and taxes. Its centerpiece is a **sense → think → act**
feedback loop that:

1. **predicts booking frequency** for each client and for each day,
2. **creates, scales and pauses Google Ads campaigns** to fill chair time the forecast says will sit empty, and
3. **detects how many people sign up from those ads** (by gclid/UTM attribution), which feeds the next cycle.

| Layer | Tech |
|---|---|
| Frontend | Vanilla JS (ES modules), no build step, installable PWA, responsive (bottom tabs on phones, side rail on desktop), light/dark |
| Backend | Python 3.11+, FastAPI, psycopg 3, numpy |
| Database | PostgreSQL 14+ |
| Ads | Google Ads API (`google-ads` client) or a built-in simulator for demos |

The original digital-twin research code (`barbershop_twin/`, `web_dashboard/`,
`claude_audit_report.md`) is unchanged. The ERP reuses its tax waterfall and its
Hill-curve ad-response model.

## Quick start

```bash
# 1. Postgres
docker compose up -d db          # or use any Postgres; set DATABASE_URL

# 2. Backend
cd backend
pip install -r requirements.txt
export DATABASE_URL=postgresql://tallyos:tallyos@localhost:5432/tallyos
python -m app.cli seed --reset   # demo shop: ~150 days of history + 60 days of loop runs
uvicorn app.main:app --reload    # http://localhost:8000
```

Open http://localhost:8000 on your phone (same network) and choose "Add to Home Screen".
The public sign-up page that ads point to is `/join.html`.

Or run the whole stack with `docker compose up --build`, then
`docker compose exec api python -m app.cli seed --reset`.

## The growth loop

```
             ┌──────────────────────── next cycle ────────────────────────┐
             ▼                                                            │
  SENSE  Google Ads spend/clicks/gclids · sign-ups · first bookings · lift │
  THINK  booking forecast → open-chair gap · client value → max CPA        │
         · Bayesian CPA per campaign → decisions                           │
  ACT    create / scale / reschedule / pause campaigns ·                   │
         upload booked sign-ups to Google as offline conversions ──────────┘
```

Run a cycle with `python -m app.cli run-loop [--dry-run]` (cron it daily), set
`TALLYOS_LOOP_HOURS=24` to have the server run it, or tap **Run now** / **Preview**
in the Growth tab. Every run is stored in `loop_runs` with its inputs, its reasoning
and what it did, and the app shows that history.

**Forecast** (`backend/app/growth/forecast.py`). Each client's rebooking interval is
modelled as Normal(μ, σ), using their own history shrunk toward the shop average.
Given the days since their last visit, it computes the probability that they book on
each upcoming day. That probability decays once they're overdue (lapsing clients),
and is reshaped by the weekdays they usually come in, with zero on closed days.
Already-booked appointments and organic new-client arrivals are added on top. A
built-in backtest scores the forecast against a "same day last week" baseline.

**Decisions** (`backend/app/growth/think.py`):
- *Client value:* margin per visit × expected visits in 12 months × measured new-client return rate. The loop never pays more than ⅓ of that per booked new client.
- *Cost per booked client:* CPC ÷ (click→sign-up rate from a Beta posterior × sign-up→booking rate).
- *Gap:* 85% of capacity minus expected bookings, per day. Budget = gap × CPA, within the guardrail.
- *Pausing:* a campaign is paused only when even its optimistic CPA is over the ceiling after ≥30 clicks.
- *Exploring:* with no data yet, the loop uses an optimistic prior, capped at half the guardrail budget.
- *Stability:* budgets move in bounded steps, and ad days have hysteresis so the schedule doesn't flap.

**Detection** (`backend/app/growth/signups.py`). `/join.html` reads `gclid` and
`utm_*` from the URL and posts them with the sign-up. A gclid is matched to a
campaign through Google's click report. Clicks that haven't been reported yet are
re-matched on the next cycle. A sign-up converts when that client books, and the
booked conversions are uploaded back to Google.

## Connecting a real Google Ads account

```bash
pip install google-ads
export TALLYOS_ADS_BACKEND=google
export GOOGLE_ADS_CONFIGURATION_FILE_PATH=/path/to/google-ads.yaml   # developer token + OAuth
export GOOGLE_ADS_CUSTOMER_ID=1234567890
export GOOGLE_ADS_CONVERSION_ACTION=987654321   # an "import from clicks" conversion action
export TALLYOS_BOOKING_URL=https://yourshop.example/join.html
export TALLYOS_SHOP_LAT=29.81 TALLYOS_SHOP_LNG=-95.40 TALLYOS_AD_RADIUS_MILES=3
```

Safety rails for real money:
- On a live account, new campaigns are created **paused**. Approve them in Growth → Campaigns, unless you set `TALLYOS_ADS_AUTO_ENABLE=true`.
- Total daily spend across loop-managed campaigns is capped (`GrowthConfig.max_total_daily_budget`, $40/day by default).
- Campaigns you create yourself in Google Ads are tracked but never changed.
- Untick "Let the growth loop manage this campaign" to take a campaign off autopilot.

The live adapter (`backend/app/ads/google_ads.py`) creates a Search campaign
(Maximize Clicks with a CPC ceiling) with a proximity radius, an ad schedule on the
gap weekdays, phrase-match local keywords, and a responsive search ad built from your
service menu. It has not been exercised against a real account in this repo; try it
on a test account first.

## Booksy: what people booked, and whether they came in late

TallyOS mirrors your Booksy bookings, so the forecast, the growth loop and the
reports use what clients actually booked. It records no-shows, cancellations and
arrival times, and turns them into a punctuality report.

There are three ways to bring bookings in. All of them update existing bookings
instead of creating duplicates:

| Way | When to use it | How |
|---|---|---|
| CSV import | Works today, no special access | Export appointments from Booksy Biz → More → Booksy → pick the file (or `python -m app.cli import-booksy export.csv`) |
| Partner API sync | Once Booksy grants partner API access | Set `BOOKSY_API_URL`, `BOOKSY_API_TOKEN`, `BOOKSY_BUSINESS_ID`, then use "Sync now", `python -m app.cli sync-booksy`, or `TALLYOS_LOOP_HOURS` (syncs before every loop run) |
| Webhooks | Live updates once Booksy enables them for you | Set `BOOKSY_WEBHOOK_SECRET` and give Booksy `https://<your-host>/api/integrations/booksy/webhook?secret=<it>`. Notifications are re-fetched from the API when credentials exist |

**Lateness** compares arrival time to booked start. Arrival time comes from Booksy's
check-in time (from the API or a CSV "Check-in time" column), or from the **Arrived**
button on Today. A visit counts as late after a 5-minute grace period, and lateness
per visit is capped at the appointment length. You get:
- on-time share, average lateness and chair hours lost
- no-shows and no-show rate
- late share by weekday
- habitual latecomers, with a one-tap reminder text
- "often late" flags on client profiles

**Matching:**
- Booksy clients are matched to existing TallyOS clients by Booksy id, then phone, then email. So a person who signed up from a Google Ad and then booked on Booksy still counts as a conversion for that campaign.
- Services and barbers are matched by Booksy id, then by name.
- Bookings finished in Booksy become sales, so finance stays complete.
- Checking a client out in TallyOS is never undone by a stale Booksy status.
- Every webhook, sync and CSV row is logged under More → Booksy → Recent activity.

> **Caveat:** Booksy's partner API is invite-only and its docs aren't public. The
> endpoint paths (`BOOKSY_APPOINTMENTS_PATH`, `BOOKSY_APPOINTMENT_PATH`, `BOOKSY_PARAM_FROM/TILL`)
> and the JSON field names (`FIELD_PATHS` and `STATUS_MAP` in `backend/app/booksy.py`) are
> tolerant best guesses. Check them against the partner docs or a real payload
> (Recent activity stores it) and adjust them; nothing else needs to change.
> The CSV importer recognises common column names and reports which ones it matched.

All timestamps are shop-local. Set `TALLYOS_TIMEZONE` (default `America/Chicago`).

## ERP features

- **Today:** bookings, sales, month-to-date profit, sign-ups, an **Arrived** check-in, one-tap checkout (tip presets, card/cash, retail add-ons), this week's forecast, punctuality, low stock.
- **Schedule:** day strip, conflict-checked booking with live availability, check out / no-show / cancel.
- **Clients:** search, profile with visit history, source/campaign, predicted next visit ("due", "overdue", "lapsed"), and punctuality.
- **Inventory:** retail and back-bar stock. Selling or using items decrements stock, and reorder points are flagged.
- **Finance:** P&L (card fees, supplies, commissions, rent, ad spend) and a federal / SE / state tax waterfall with take-home.
- **Menu & staff, Settings:** services, durations, commissions, hours, rent, tax settings, theme.

## Tests

```bash
cd backend
TALLYOS_TEST_DATABASE_URL=postgresql://tallyos:tallyos@localhost:5432/tallyos_test pytest
```

The tests cover booking rules, checkout and P&L, the forecaster, the decision rules,
attribution (gclid / pending / UTM / organic), the public booking checks, and full
sense-think-act cycles against the simulated Google Ads.
