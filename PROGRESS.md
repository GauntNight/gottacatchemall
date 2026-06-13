# Build Progress

Status snapshot for the TCG drop monitor. Tracking set: **Pitch Black (ME05)**,
release 2026-07-17. See [`tcg-drop-monitor-spec.md`](./tcg-drop-monitor-spec.md)
for the source research and architecture.

_Last updated: 2026-06-12._

## Where we are

Tier 1 (aggregate intelligence) is fully connected. Tier 2 (SKU watchers) has the
easy wins live; the bot-protected retailers are built and fail-soft but mostly
need real product IDs or a key before they can be trusted.

### Target status (`targets.yaml`)

| Target | Fetcher | Status |
|---|---|---|
| reddit-pkmntcgdeals | reddit_browser | ✅ live |
| reddit-pokemontcg | reddit_browser | ✅ live |
| pokebeach-news | rss | ✅ live, filtered to the Pitch Black preorder |
| galactic-toys | shopify_json | ✅ live — in stock $114.95 |
| rocket-city-toys | shopify_json | ✅ live — OOS $49.99 MSRP, **armed**, fires on flip |
| bestbuy-etb-search / bestbuy-pitch-black | bestbuy_api | ⚙️ ready — needs `BESTBUY_API_KEY` |
| pokecenter-etb | pokemoncenter | ⚠️ built, fail-soft, headed + probabilistic Akamai; off by default |
| target-etb | redsky | ✅ live — Pitch Black ETB (TCIN 1011483406), OOS $59.99, **armed**, fires on flip |
| walmart-etb | nextdata | ⚠️ built — needs real `/ip/{slug}/{itemId}`; untested live |
| dacardworld | html_button | ⚠️ 403s on raw HTTP — needs the browser path |

Notifications are **LIVE** via ntfy.sh (`NTFY_TOPIC` set in `.env`, gitignored).
Subscribe to that topic in the ntfy app to receive pushes on the phone.

## What we did (recent commits)

- **Tier-1 connectivity** — raw HTTP 403s on Reddit/PokeBeach are a TLS/stack
  fingerprint block, not a UA problem. `reddit_browser` now needs no login
  session: warm the `old.reddit.com` HTML page, then the `.json` returns 200.
  PokeBeach runs XenForo (not WordPress) — fixed the feed URL.
- **`require` filter** — AND-of terms alongside the existing OR `keywords`,
  centralized in `Target.matches()`. Narrowed PokeBeach 30 → 1 (the preorder).
- **Shopify `.js`** — the documented `.json` omits `available` on these stores;
  `.js` has it (and price in cents). Two watchers enabled.
- **Best Buy** — SKU-batch via the `in()` operator; 403 = rate-limit/bad-key.
- **Pokémon Center** — category-tile discovery watcher + shared `browser.py`
  stealth launcher. Success judged by tiles rendering, not HTTP status.

## What's next

1. **Best Buy** — once a free key exists: enable search, `--once` to discover the
   Pitch Black SKUs, paste them into `bestbuy-pitch-black.skus`, run precise mode.
2. **Walmart** — live-discover a real `/ip/{slug}/{itemId}` URL, fill the config,
   and smoke-test `nextdata` (written to a documented shape but never run against
   a real listing — expect shape drift). _Target is now done (see below)._
3. **DA Card World** — move onto the shared `browser.py` path (currently 403s).
4. **Notifications** — _done 2026-06-12._ Topic set; verified end-to-end against
   ntfy.sh. Fixed a latent crash: the notifier put the alert title in an HTTP
   header, so the emoji (🟢) / accented product names (Pokémon) in the IN_STOCK
   alert raised `UnicodeEncodeError` — the most important push would have died.
   Switched to ntfy **JSON publishing** (title/message in a UTF-8 body; priority
   5 = max for in-stock). Only surfaced because prior runs were all dry-run.

### Target — done 2026-06-12

Live-discovered the standard Pitch Black ETB: **TCIN `1011483406`**, $59.99,
street date 2026-07-17, currently `OUT_OF_STOCK` (armed). Rewrote `redsky.py`
against the real API shape:

- The public web `key` is static frontend JS (`9f36…3e96`); shipped as a
  baked-in default so no devtools step is needed (override via `options.key`).
- Availability is **not** in `pdp_client_v1` (its `fulfillment` is null) and
  `pdp_fulfillment_v1` is now `410 Gone`. Stock lives in
  **`product_fulfillment_v1`** under `fulfillment.shipping_options.availability_status`
  (needs a location; defaults to a NYC point — shipping availability is national).
- We read that for the edge signal and enrich title/price from `pdp_client_v1`
  best-effort. Parsing verified deterministically across OOS / IN_STOCK /
  PRE_ORDER_SELLABLE / weird-status / 403 scenarios.
- RedSky is Akamai-protected and 403s under a request **burst** (→ UNKNOWN,
  never a false alert). At the 10-min poll cadence there is no burst.

## Notes

- Tests: 36 pass (the `tests/test_store.py` Windows `PermissionError` on
  pytest's tmp_path does not reproduce in the current environment).
- Pokémon Center detection is environment-dependent: headless is always blocked;
  headed real Chrome with a warmed `.pc_profile` gets through intermittently and
  should fare better from a residential IP.
