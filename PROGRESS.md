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
| pokecenter-etb | pokemoncenter | ✅ enabled — category-tile watcher, narrowed to "pitch black"; headed + probabilistic Akamai (UNKNOWN from datacenter IPs) |
| gamestop-pitch-black | gamestop | ✅ enabled — browser-path product watcher (item 20034819); JSON-LD availability + text fallback; headed (challenged headless) |
| target-etb | redsky | ✅ live — Pitch Black ETB (TCIN 1011483406), OOS $59.99, **armed**; browser fallback beats the Akamai 403 |
| walmart-etb | walmart | ✅ enabled — browser path + **price gate** (item 20161351456); marketplace-only ~$145, armed, fires when an offer ≤ $80 lands |
| bestbuy-etb-search / bestbuy-pitch-black | bestbuy_api | ❌ dropped — user can't get an API key |
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

1. **Verify the browser watchers from a residential machine.** gamestop-pitch-black
   and pokecenter-etb both return UNKNOWN from this datacenter IP (headed Chrome is
   challenged). Run headed on a home network with a warmed profile to confirm they
   read availability. Target redsky likewise needs a clean (non-burst) IP.
2. **Barnes & Noble** — Pitch Black ETB page wasn't listed yet (they carry other
   Mega Evolution ETBs at `/w/{slug}/{id}`). Re-check closer to the 2026-07-17
   release, then add a watcher (bot-walled → browser path or stock-XHR from devtools).
3. **DA Card World** — move onto the shared `browser.py` path (currently 403s).
4. ~~Best Buy~~ — dropped (no API key available). ~~Walmart~~ — done (see below).

### Walmart — done 2026-06-13

PerimeterX walls plain HTTP (captcha page, no `__NEXT_DATA__`), so the new
`walmart` fetcher renders via the stealth browser and reads
`props.pageProps.initialData.data.product`. The Pitch Black listing
(item 20161351456) is **marketplace-only** — buy box rotates among 3P resellers
(~$145, e.g. Vaulted Cards / Revolution Sports Marketing), no Walmart $59.99
offer yet. So it **gates on price**: IN_STOCK only when `currentPrice` ≤
`options.max_price` (default $80); a scalper-priced "in stock" reads
OUT_OF_STOCK (armed). Verified headed: $144.77 → out_of_stock. Pure helpers
(`extract_offer` / `status_from_offer`) unit-tested. Tune `max_price` if $80 is
too tight/loose.

### Notifications — done 2026-06-12

Topic set; verified end-to-end against
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
- RedSky is Akamai-protected and 403s a flagged IP. **Browser fallback
  (2026-06-13):** on a 403 the fetcher transparently re-runs the same JSON
  calls (`product_fulfillment_v1` + `pdp_client_v1`) from a warmed target.com
  page via the stealth browser, inheriting Akamai's `_abck` cookie + Origin —
  so it works even when plain HTTP is blocked. Verified headed on this machine:
  httpx 403 → browser → `out_of_stock $59.99`. Plain HTTP stays primary (lighter
  on a clean IP); `options.browser: true` forces the browser path.

### GameStop + Pokémon Center — enabled 2026-06-13

- **GameStop** `gamestop` fetcher (new): bot-walled (403 plain HTTP), so it
  renders the PDP with the shared stealth browser and reads `offers.availability`
  from JSON-LD, falling back to add-to-cart/text signals. Tracks one product
  (item 20034819); OOS↔IN_STOCK; fails soft to UNKNOWN. Pure helpers unit-tested.
- **Pokémon Center** enabled (preorders are live there now), category-tile
  watcher narrowed to `keywords: [pitch black]`.
- Both are headed-Chrome paths: headless is challenged (verified). Their live
  success is environment-dependent (residential IP + warmed profile).

## Notes

- Tests: 47 pass (added GameStop parsing tests; the old `tests/test_store.py`
  Windows `PermissionError` on pytest's tmp_path does not reproduce here).
- Pokémon Center detection is environment-dependent: headless is always blocked;
  headed real Chrome with a warmed `.pc_profile` gets through intermittently and
  should fare better from a residential IP.
