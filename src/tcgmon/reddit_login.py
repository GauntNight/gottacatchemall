"""One-time Reddit login — capture a logged-in browser session.

Run once on a machine with a display:

    python -m tcgmon.reddit_login

Opens your *real* installed Chrome (not Playwright's bundled Chromium) with
the automation fingerprints stripped, so Reddit treats it as a normal
browser and won't throw the "this browser may not be secure" block. Log in
normally; the helper polls Reddit's cookie-authenticated ``/api/me.json``
and, once it sees you logged in, saves the session to
``.reddit_session.json`` (override with ``REDDIT_SESSION_FILE``). It also
keeps a persistent profile dir so re-logins are quick.

Tip: log in with your Reddit username/password (or email). Third-party SSO
("Continue with Google/Apple") hard-blocks automated browsers and will fail
even here — if that's your only login method, tell me and we'll adapt.

Prereqs:  pip install -e ".[browser]"  &&  playwright install chromium
"""

from __future__ import annotations

import asyncio
import json
import os

from dotenv import load_dotenv

from .http import BROWSER_USER_AGENT

load_dotenv()

ME_URL = "https://www.reddit.com/api/me.json"
# Auth-gated page: logged-out users get redirected to /login, logged-in
# users stay. Markup- and SSO-agnostic, so it survives Reddit API changes.
SETTINGS_URL = "https://www.reddit.com/settings/"
LOGIN_URL = "https://www.reddit.com/login/"
SESSION_FILE = os.environ.get("REDDIT_SESSION_FILE", ".reddit_session.json")
PROFILE_DIR = os.environ.get("REDDIT_PROFILE_DIR", ".reddit_profile")
WAIT_SECONDS = 300  # how long to wait for you to finish logging in

# Strip the bits that let sites flag the browser as automated.
_ANTI_AUTOMATION_ARGS = ["--disable-blink-features=AutomationControlled"]
_IGNORE_DEFAULT_ARGS = ["--enable-automation"]
_STEALTH_INIT = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
)


async def _launch_context(p):
    """Launch a persistent context, preferring real Chrome over Chromium."""
    common = dict(
        user_data_dir=PROFILE_DIR,
        headless=False,
        args=_ANTI_AUTOMATION_ARGS,
        ignore_default_args=_IGNORE_DEFAULT_ARGS,
        user_agent=BROWSER_USER_AGENT,
    )
    try:
        ctx = await p.chromium.launch_persistent_context(channel="chrome", **common)
        print("Using your installed Google Chrome.")
        return ctx
    except Exception as exc:  # noqa: BLE001 — Chrome channel not available
        print(f"(real Chrome unavailable: {exc}; falling back to Chromium)")
        return await p.chromium.launch_persistent_context(**common)


async def _try_username(page) -> str | None:
    """Best-effort display name for the success message; never fatal."""
    try:
        resp = await page.goto(ME_URL, wait_until="domcontentloaded")
        if resp and resp.ok:
            data = json.loads(await resp.text())
            return data.get("data", {}).get("name")
    except Exception:  # noqa: BLE001
        pass
    return None


async def _run() -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Playwright not installed. Run:")
        print('  pip install -e ".[browser]"  &&  playwright install chromium')
        return 1

    async with async_playwright() as p:
        try:
            context = await _launch_context(p)
        except Exception as exc:  # noqa: BLE001
            print(f"Could not launch a browser: {exc}")
            print("Is Google Chrome installed? Otherwise run "
                  "`playwright install chromium`.")
            return 1

        await context.add_init_script(_STEALTH_INIT)
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(LOGIN_URL)
        print("\nA Chrome window opened. Log into Reddit there "
              "(username/password; handle 2FA/captcha).")
        print(f"Waiting up to {WAIT_SECONDS // 60} min for login...\n")

        # Poll an auth-gated page on a side tab so we don't disturb login.
        probe = await context.new_page()
        logged_in = False
        loop = asyncio.get_running_loop()
        deadline = loop.time() + WAIT_SECONDS
        while loop.time() < deadline:
            try:
                await probe.goto(SETTINGS_URL, wait_until="domcontentloaded")
                # Redirected to /login => still anonymous; anything else => in.
                if "/login" not in probe.url:
                    logged_in = True
                    break
            except Exception:  # noqa: BLE001 — keep polling
                pass
            await asyncio.sleep(3)

        if not logged_in:
            print("Timed out waiting for login. Nothing saved.")
            await context.close()
            return 1

        username = await _try_username(probe)
        await context.storage_state(path=SESSION_FILE)
        await context.close()

    who = f"u/{username}" if username else "your account"
    print(f"\nLogged in as {who}.")
    print(f"Session saved to {SESSION_FILE}")
    print("The reddit_browser fetcher will now use it. (Re-run this if the "
          "session ever expires.)")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
