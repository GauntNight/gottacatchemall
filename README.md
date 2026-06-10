# gottacatchemall — TCG Drop Monitor

A Pokémon TCG preorder/restock monitor. It polls two tiers of sources on
independent, jittered schedules and pushes a notification **the moment a
stock state changes** — the alert-to-checkout window is the whole point.

- **Tier 1 — aggregate intelligence** (every 15–60 min): news/community
  feeds that *announce* drops (Reddit JSON, PokeBeach RSS).
- **Tier 2 — SKU watchers** (every 5–15 min, jittered): specific retailer
  product pages/APIs polled for a stock-state transition.

The core discipline is **edge detection**: store the last state per
`(source, key)` and alert only on a transition (`out_of_stock → in_stock`,
`absent → listed`). Bot challenges, timeouts, and parse failures are
`unknown` — they never alert and never overwrite a known state.

> See [`tcg-drop-monitor-spec.md`](./tcg-drop-monitor-spec.md) for the full
> source research and architecture rationale.

## Status

| Phase | Scope | State |
|---|---|---|
| **1** | Tier 1: Reddit JSON + PokeBeach RSS + ntfy | ✅ implemented |
| **2** | Best Buy API + Shopify `.json` watchers | ✅ implemented (add keys/URLs) |
| **3** | Target (RedSky) / Walmart (`__NEXT_DATA__`) / generic HTML | ⚠️ best-effort, fail-soft, off by default |

Phase 1 alone would have caught the 2026-06-10 Pitch Black preorder within
minutes.

## Architecture

```
scheduler (APScheduler)         one independent, jittered job per target
   │
   ├─ fetchers/                 one module per source type
   │    reddit_json · rss · shopify_json · bestbuy_api
   │    redsky · nextdata · html_button
   │
   ├─ store (SQLite)            (source,key) → status; alert on edge only
   │
   └─ notifier (ntfy.sh)        retailer · product · old→new · price · URL
```

Design choices for a single-process personal deploy (per the spec's own
recommendations): **SQLite** state store, **APScheduler** scheduler,
**ntfy.sh** push (no account/API key, just a mobile app).

## Quick start

```bash
# 1. Install (Python 3.12+)
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# 2. Configure
cp .env.example .env          # set NTFY_TOPIC (and BESTBUY_API_KEY if used)

# 3. See what's configured
python -m tcgmon --list

# 4. Run every enabled target ONCE (great for a smoke test / dry run)
python -m tcgmon --once

# 5. Run forever on the schedule
python -m tcgmon
```

With `NTFY_TOPIC` empty, the monitor runs in **dry-run**: alerts print to
the console instead of pushing. Set the topic and subscribe to it in the
[ntfy](https://ntfy.sh) mobile app to get phone notifications.

## Reddit OAuth (recommended)

Reddit throttles and frequently `403`s anonymous `.json` requests
regardless of IP. The fix is a free OAuth app — Reddit then allows 100
req/min from a stable, authenticated endpoint. One-time setup:

1. Create an app at <https://www.reddit.com/prefs/apps> →
   **type: web app**, **redirect uri: `http://localhost:8080`** (exact).
2. Put the id/secret in `.env`:
   ```
   REDDIT_CLIENT_ID=...
   REDDIT_CLIENT_SECRET=...
   ```
3. Mint a permanent refresh token (opens your browser, log in → Allow):
   ```bash
   python -m tcgmon.reddit_auth
   ```
4. Paste the printed `REDDIT_REFRESH_TOKEN=...` line into `.env`.

With all three values set, `reddit_json` automatically uses the
authenticated `oauth.reddit.com` API and refreshes its own access tokens.
Leave them blank to fall back to the (rate-limited) anonymous endpoint.

## Configuring targets

Everything you watch lives in [`targets.yaml`](./targets.yaml). Adding the
next set is editing YAML — no code:

```yaml
targets:
  - name: rocket-city-toys
    fetcher: shopify_json        # see `--list` for available fetchers
    url: https://www.rocketcitytoys.com/products/<handle>
    interval_minutes: 10
    enabled: true
    keywords: [pitch black, "elite trainer"]   # Tier 1 title filter
    options: {}                  # per-fetcher extras (e.g. bestbuy search, redsky tcin/key)
```

Phase 2/3 targets ship **disabled** with this-set placeholder URLs — flip
`enabled: true` and drop in real URLs/keys for the next set.

## Tests

```bash
pytest            # edge-detection logic, no network required
```

## Notes & honest caveats

- **Detection ≠ acquisition.** Hyped SKUs sell out in minutes; keep
  logged-in accounts with saved payment at each retailer. No auto-checkout.
- **Unofficial endpoints drift** (RedSky, Shopify `.json` semantics,
  Walmart `__NEXT_DATA__`). Those fetchers fail soft to `unknown` by design.
- **Run from a residential-ish IP.** Datacenter IPs get challenged faster by
  Pokémon Center / Walmart. Tier 1 runs fine from anywhere.
- Check each site's ToS if this ever becomes more than personal tooling.

MIT licensed.
