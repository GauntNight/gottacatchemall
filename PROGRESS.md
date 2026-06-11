# Build Progress

Status snapshot for the TCG drop monitor. Tracking set: **Pitch Black (ME05)**,
release 2026-07-17. See [`tcg-drop-monitor-spec.md`](./tcg-drop-monitor-spec.md)
for the source research and architecture.

_Last updated: 2026-06-11._

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
| target-etb | redsky | ⚠️ built — needs real TCIN + public web key; untested live |
| walmart-etb | nextdata | ⚠️ built — needs real `/ip/{slug}/{itemId}`; untested live |
| dacardworld | html_button | ⚠️ 403s on raw HTTP — needs the browser path |

Notifications run in **DRY-RUN** (console) until `NTFY_TOPIC` is set in `.env`.

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
2. **Target / Walmart** — live-discover a real TCIN + public web key and a real
   Walmart itemId, fill the configs, and smoke-test `redsky` + `nextdata` (both
   are written to documented shapes but have **never** run against a real
   listing — expect shape drift).
3. **DA Card World** — move onto the shared `browser.py` path (currently 403s).
4. **Notifications** — set `NTFY_TOPIC` so armed watchers (esp. rocket-city's
   MSRP one) actually reach the phone.

## Notes

- Tests: 18 logic tests pass. `tests/test_store.py` errors with a Windows
  `PermissionError` on pytest's tmp_path — a sandbox quirk, not a code failure.
- Pokémon Center detection is environment-dependent: headless is always blocked;
  headed real Chrome with a warmed `.pc_profile` gets through intermittently and
  should fare better from a residential IP.
