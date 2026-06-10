# TCG Drop Monitor — Target Sources & Architecture Spec

> Spec for a Pokémon TCG preorder/restock monitor. Two tiers: low-frequency
> aggregate intelligence (news/community feeds that announce drops) and
> high-frequency SKU watchers (specific retailer product pages polled every
> 5–15 min). Edge-detection on state change → push notification.
>
> Context: Pitch Black (ME05) releases 2026-07-17. Pokémon Center preorders
> opened 2026-06-10 (37 days out — new normal is ~37–39 day windows, down
> from ~78). Design for the NEXT set, not this one.

---

## Tier 1 — Aggregate Intelligence Sources (poll every 15–60 min)

These announce drops/preorder openings. They're the "something is happening"
layer. All are polite to poll at low frequency.

### 1.1 Reddit JSON endpoints (easiest, structured, no auth needed)
Append `.json` to any subreddit/listing URL. Set a descriptive User-Agent
(Reddit blocks default UAs). Rate limit: ~60 req/10min unauthenticated;
use OAuth (free script app) for 100/min if needed.

| Source | URL | Notes |
|---|---|---|
| r/PKMNTCGDeals (new) | `https://www.reddit.com/r/PKMNTCGDeals/new.json?limit=25` | Deal/restock posts, usually within minutes of a drop |
| r/PokemonTCG (new) | `https://www.reddit.com/r/PokemonTCG/new.json?limit=25` | Noisier; filter titles for keywords |
| r/pkmntcgtrades / r/PokeInvesting | same pattern | Optional; investor chatter often leads news |

Parse: `data.children[].data.title`, `.url`, `.created_utc`. Keyword filter:
`preorder|pre-order|restock|live|in stock|ETB|elite trainer` + set name.

### 1.2 PokeBeach (news; fastest TCG-specific journalism)
- Site: `https://www.pokebeach.com/`
- RSS: `https://www.pokebeach.com/feed` (WordPress — standard `/feed` endpoint; verify on first run)
- Broke the Pitch Black preorder-opening story same-hour on 2026-06-10.
- Poll: 15–30 min. Parse with `feedparser`.

### 1.3 Official Pokémon news
- `https://www.pokemon.com/us/pokemon-news` — announces sets/dates, not drops.
  Slow-moving; poll hourly. Scrape the news index page for new article slugs.

### 1.4 Distributor release calendars (MSRP + street-date ground truth)
- PHD Games release posts: `https://www.phdgames.com/` — publishes item codes
  (e.g. PKU10416 = Pitch Black ETB), MSRP ($49.99), and street dates weeks early.
  Scrape their Pokémon category/blog. Poll daily — this is calendar data, not drops.

### 1.5 TCGPlayer (market price ticker)
- Product pages render price data client-side; the underlying endpoints
  (`mpapi.tcgplayer.com` / `mp-search-api`) are unofficial but stable JSON.
- Use for: market price drift on sealed product = demand signal. Not a
  stock monitor.
- Pitch Black ETB product family: search `tcgplayer.com` for "ME05 Pitch Black
  Elite Trainer Box" (regular + Pokemon Center Exclusive, product id 692949
  for the PC Exclusive).

---

## Tier 2 — SKU Page Watchers (poll every 5–15 min, jittered)

The "buy it now" layer. Watch a specific product URL per retailer for a
stock-state transition. **Alert on edge only** (state change), never on level.

### 2.1 Pokémon Center (official, MSRP, bot-protected)
- Product URLs: `https://www.pokemoncenter.com/product/{sku}/...`
- Category to discover new SKUs: `https://www.pokemoncenter.com/category/elite-trainer-box`
  and `/category/new-releases`
- **Caution:** Heavy bot mitigation (challenge pages, queue during drops; site
  fell over on 2026-06-10 from human traffic alone). Poll the *category* page
  at 10–15 min with realistic headers + jitter. Do NOT hammer product pages.
  Expect to be challenged; treat a challenge response as "unknown", not "OOS".
- Detection signal: new product tiles appearing in category JSON/HTML; product
  page "Add to Cart" button state.

### 2.2 Best Buy (the only retailer with a REAL official API)
- Products API: `https://api.bestbuy.com/v1/products(search=pokemon%20elite%20trainer)?apiKey={KEY}&format=json&show=sku,name,onlineAvailability,inStoreAvailability,regularPrice,url`
- Free API key: https://developer.bestbuy.com (instant signup)
- Returns `onlineAvailability` boolean per SKU. This is the gold standard —
  no scraping, no bans. Poll every 5 min, well within rate limits.

### 2.3 Target
- Product pages: `https://www.target.com/p/{slug}/-/A-{tcin}`
- Unofficial RedSky API: `https://redsky.target.com/redsky_aggregations/v1/web/pdp_client_v1?key={public_web_key}&tcin={TCIN}&...`
  The `key` is a public web key visible in browser devtools on any product page.
  Returns fulfillment/availability JSON. Unofficial = can change without notice;
  wrap in try/except and fall back to HTML scrape of the "Add to cart" button.
- Find the TCIN by searching target.com for the product once it's listed.

### 2.4 Walmart
- Product pages: `https://www.walmart.com/ip/{slug}/{itemId}`
- The page embeds `__NEXT_DATA__` JSON (Next.js) containing availability.
  Parse `<script id="__NEXT_DATA__">` → `props.pageProps.initialData...availabilityStatus`.
- Moderate bot protection (PerimeterX). Jitter, realistic UA, 10–15 min interval.

### 2.5 GameStop
- Product page (Pitch Black ETB): `https://www.gamestop.com/toys-games/trading-cards/products/pokemon-trading-card-game-pitch-black-elite-trainer-box/20034819.html`
- Note: Pitch Black preorder is currently **in-store only**; online stock state
  on the page is still worth watching for launch-day online allocation.
- Salesforce Commerce Cloud backend; availability via
  `Product-Variation` / inventory endpoints visible in devtools, or scrape the
  add-to-cart button state.

### 2.6 Amazon
- Watch the official "Pokemon" brand-sold listing only (third-party sellers =
  scalper pricing). Amazon is the most aggressively anti-scrape target on this
  list; recommend NOT polling directly. Instead use CamelCamelCamel
  (`https://camelcamelcamel.com`) price-watch emails, or skip Amazon entirely.

### 2.7 Dedicated TCG retailers (low/no bot protection, easy scrapes)
These ship preorders and rarely fight scrapers. Standard Shopify/Magento —
Shopify stores expose `{product_url}.json` (e.g. `.../products/{handle}.json`)
with `variants[].available`. Check each for the Shopify pattern first.

| Retailer | Product URL pattern | Stack hint |
|---|---|---|
| DA Card World | `https://www.dacardworld.com/gaming/pokemon-mega-evolution-pitch-black-elite-trainer-box` | Custom; scrape button |
| Miniature Market | `https://www.miniaturemarket.com/Pokemon-TCG-Pitch-Black-Elite-Trainer-Box-Preorder/PKU10416` | Magento; note SKU in URL |
| Galactic Toys | `https://galactictoys.com/products/pre-order-july-2026-pokemon-tcg-mega-evolutions-pitch-black-me05-elite-trainer-box` | **Shopify** — append `.json` |
| Rocket City Toys | `https://www.rocketcitytoys.com/products/pok-mon-tcg-mega-evolution-pitch-black-elite-trainer-box` | **Shopify** — append `.json` |
| ToyWiz | `https://toywiz.com/pokemon-mega-evolution-pitch-black-elite-trainer-box/` | Custom; scrape |

---

## Architecture (the layer Claude Code builds)

```
┌─────────────────────────────────────────────────┐
│  scheduler (Celery beat or APScheduler/cron)     │
│   ├─ tier1 tasks: 15–60 min intervals            │
│   └─ tier2 tasks: 5–15 min, ±30% jitter          │
├─────────────────────────────────────────────────┤
│  fetchers (one module per source type)           │
│   reddit_json | rss | shopify_json | bestbuy_api │
│   redsky | nextdata | html_button_scrape         │
├─────────────────────────────────────────────────┤
│  state store (Redis or SQLite)                   │
│   key: source:sku → {status, price, seen_at}     │
│   alert ONLY on status transition (edge detect)  │
│   challenge/error → status "unknown", no alert   │
├─────────────────────────────────────────────────┤
│  notifier                                        │
│   ntfy.sh (zero-setup: POST to ntfy.sh/{topic},  │
│   subscribe in ntfy mobile app)                  │
│   or Pushover ($5 one-time) / Telegram bot       │
└─────────────────────────────────────────────────┘
```

### Design rules
1. **Edge detection, not level detection.** Store last state per (source, sku).
   Alert only on `OOS→in_stock`, `absent→listed`, `preorder_closed→open`.
2. **Three-valued state:** `in_stock | out_of_stock | unknown`. Bot challenges,
   timeouts, and parse failures are `unknown` — never alert on them, never
   overwrite a known state with unknown.
3. **Jitter everything.** `interval * uniform(0.7, 1.3)`. Rotate realistic
   browser User-Agents. One source failing must not block others (per-task
   timeouts, independent Celery tasks).
4. **Respect the polite tier.** Official APIs (Best Buy) and JSON endpoints
   (Reddit, Shopify .json) can run at 5 min. Bot-protected HTML (Pokémon
   Center, Walmart) stays at 10–15 min with backoff on challenge.
5. **Config-driven targets.** `targets.yaml`: list of {name, url, fetcher_type,
   interval, keywords}. Adding the next set = adding YAML entries, no code.
6. **Notification payload:** retailer, product, old→new state, price, direct
   URL. The URL is the whole point — alert-to-checkout time is the real metric.

### Suggested stack
- Python 3.12, `httpx` (async), `feedparser`, `selectolax` or BeautifulSoup,
  Redis (you already run it) or SQLite if deploying somewhere thin,
  APScheduler for a single-process deploy / Celery beat if folding into
  existing infra, `ntfy` for push (no account, no API key, mobile app).
- Deploy: anywhere with a residential-ish IP. Datacenter IPs (AWS/DO) get
  challenged faster by Pokémon Center/Walmart. A box at home or a cheap
  residential proxy beats cloud for Tier 2; Tier 1 runs fine from anywhere.

### Phase plan
- **Phase 1:** Tier 1 only (Reddit JSON + PokeBeach RSS) + ntfy. ~1 evening.
  This alone would have caught today's Pitch Black drop within minutes.
- **Phase 2:** Best Buy API + Shopify .json watchers (the easy Tier 2 wins).
- **Phase 3:** Pokémon Center / Target / Walmart scrapers with challenge
  handling and backoff.

### Known constraints / honest caveats
- Detection ≠ acquisition. Hyped SKUs sell out in minutes; keep logged-in
  accounts with saved payment at each retailer. No auto-checkout in scope.
- Unofficial endpoints (RedSky, TCGPlayer mpapi, Shopify .json availability
  semantics) drift. Build fetchers to fail soft into `unknown`.
- Check each site's ToS if this ever becomes more than personal tooling.
