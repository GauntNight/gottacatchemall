"""One-time Reddit login — capture a logged-in browser session.

Run once on a machine with a display:

    python -m tcgmon.reddit_login

Opens a real Chromium window. Log into Reddit normally (handle any
2FA/captcha in the window). The helper polls Reddit's cookie-authenticated
``/api/me.json`` and, once it sees you logged in, saves the session to
``.reddit_session.json`` (override with ``REDDIT_SESSION_FILE``). The
``reddit_browser`` fetcher then reuses that session headlessly.

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
LOGIN_URL = "https://www.reddit.com/login/"
SESSION_FILE = os.environ.get("REDDIT_SESSION_FILE", ".reddit_session.json")
WAIT_SECONDS = 300  # how long to wait for you to finish logging in


async def _run() -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Playwright not installed. Run:")
        print('  pip install -e ".[browser]"  &&  playwright install chromium')
        return 1

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=False)
        except Exception as exc:  # noqa: BLE001
            print(f"Could not launch Chromium: {exc}")
            print("Did you run `playwright install chromium`?")
            return 1

        context = await browser.new_context(user_agent=BROWSER_USER_AGENT)
        page = await context.new_page()
        await page.goto(LOGIN_URL)
        print("\nA browser window opened. Log into Reddit there "
              "(2FA/captcha as needed).")
        print(f"Waiting up to {WAIT_SECONDS // 60} min for login...\n")

        # Poll cookie-auth identity on a side page so we don't disturb login.
        probe = await context.new_page()
        username = None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + WAIT_SECONDS
        while loop.time() < deadline:
            try:
                resp = await probe.goto(ME_URL, wait_until="domcontentloaded")
                if resp and resp.ok:
                    data = json.loads(await resp.text())
                    username = data.get("data", {}).get("name")
                    if username:
                        break
            except Exception:  # noqa: BLE001 — keep polling
                pass
            await asyncio.sleep(3)

        if not username:
            print("Timed out waiting for login. Nothing saved.")
            await browser.close()
            return 1

        await context.storage_state(path=SESSION_FILE)
        await browser.close()

    print(f"\nLogged in as u/{username}.")
    print(f"Session saved to {SESSION_FILE}")
    print("The reddit_browser fetcher will now use it. (Re-run this if the "
          "session ever expires.)")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
