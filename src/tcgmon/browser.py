"""Shared stealth browser launch for bot-protected sites (Akamai, etc.).

Strips the fingerprints that flag a browser as automated and prefers the
user's real installed Chrome over Playwright's bundled Chromium. A
persistent context is used so cookies (e.g. Akamai's validated ``_abck``)
survive between polls, which materially raises the success rate against
bot managers. Used by the Pokémon Center fetcher; available to any future
browser-path fetcher.
"""

from __future__ import annotations

import logging

log = logging.getLogger("tcgmon.browser")

# The bits that let a site flag the browser as automation-driven.
ANTI_AUTOMATION_ARGS = ["--disable-blink-features=AutomationControlled"]
IGNORE_DEFAULT_ARGS = ["--enable-automation"]
STEALTH_INIT = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
)


async def launch_stealth_persistent_context(
    p, *, user_data_dir: str, user_agent: str, headless: bool = False
):
    """Launch a persistent context with automation fingerprints stripped.

    Prefers real Chrome (``channel="chrome"``) and falls back to bundled
    Chromium. The stealth init script is registered on the context so it
    runs in every page before site JS.
    """
    common = dict(
        user_data_dir=user_data_dir,
        headless=headless,
        args=ANTI_AUTOMATION_ARGS,
        ignore_default_args=IGNORE_DEFAULT_ARGS,
        user_agent=user_agent,
    )
    try:
        ctx = await p.chromium.launch_persistent_context(channel="chrome", **common)
    except Exception as exc:  # noqa: BLE001 — Chrome channel not available
        log.info("real Chrome unavailable (%s); using bundled Chromium", exc)
        ctx = await p.chromium.launch_persistent_context(**common)
    await ctx.add_init_script(STEALTH_INIT)
    return ctx
