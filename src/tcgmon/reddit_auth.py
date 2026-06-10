"""One-time Reddit OAuth helper — mint a permanent refresh token.

Run once on a machine with a browser:

    python -m tcgmon.reddit_auth

Prerequisites:
  1. Create an app at https://www.reddit.com/prefs/apps
       - type:          web app
       - redirect uri:  http://localhost:8080   (must match EXACTLY)
  2. Put the credentials in .env:
       REDDIT_CLIENT_ID=...
       REDDIT_CLIENT_SECRET=...

This opens your browser to Reddit's consent page (log in / click Allow),
catches the redirect on localhost:8080, exchanges the code, and prints a
REDDIT_REFRESH_TOKEN line to paste into .env. The monitor then refreshes
access tokens on its own — you never have to do this again.
"""

from __future__ import annotations

import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()

REDIRECT_URI = "http://localhost:8080"
PORT = 8080
AUTHORIZE_URL = "https://www.reddit.com/api/v1/authorize"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
USER_AGENT = "gottacatchemall-tcg-monitor/0.1 (oauth setup)"

_HTML_OK = (
    b"<html><body style='font-family:sans-serif'>"
    b"<h2>Authorized.</h2><p>You can close this tab and return to the terminal."
    b"</p></body></html>"
)
_HTML_ERR = (
    b"<html><body style='font-family:sans-serif'>"
    b"<h2>Authorization failed.</h2><p>Check the terminal for details.</p>"
    b"</body></html>"
)


class _CallbackHandler(BaseHTTPRequestHandler):
    # Filled in by the server loop.
    result: dict = {}
    expected_state: str = ""

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        params = parse_qs(urlparse(self.path).query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        error = params.get("error", [None])[0]

        if error or not code or state != self.expected_state:
            _CallbackHandler.result = {
                "error": error or ("state mismatch" if state != self.expected_state
                                   else "no code returned")
            }
            self.send_response(400)
            self.end_headers()
            self.wfile.write(_HTML_ERR)
        else:
            _CallbackHandler.result = {"code": code}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(_HTML_OK)

    def log_message(self, *_args) -> None:  # silence the default access log
        pass


def main() -> int:
    client_id = os.environ.get("REDDIT_CLIENT_ID", "")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print("ERROR: set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env first.")
        print("Create the app at https://www.reddit.com/prefs/apps (type: web app,")
        print(f"redirect uri: {REDIRECT_URI}).")
        return 1

    state = secrets.token_urlsafe(24)
    _CallbackHandler.expected_state = state
    _CallbackHandler.result = {}

    authorize_url = AUTHORIZE_URL + "?" + urlencode({
        "client_id": client_id,
        "response_type": "code",
        "state": state,
        "redirect_uri": REDIRECT_URI,
        "duration": "permanent",   # permanent => we get a refresh token
        "scope": "read",
    })

    server = HTTPServer(("localhost", PORT), _CallbackHandler)
    thread = threading.Thread(target=server.handle_request)  # serve exactly one
    thread.start()

    print("\nOpen this URL in a browser logged into the Reddit account:\n")
    print(f"  {authorize_url}\n")
    try:
        import webbrowser
        webbrowser.open(authorize_url)
        print("(attempted to open it for you automatically)\n")
    except Exception:  # noqa: BLE001
        pass

    print(f"Waiting for the redirect on {REDIRECT_URI} ...")
    thread.join()
    server.server_close()

    result = _CallbackHandler.result
    if "error" in result:
        print(f"\nAuthorization failed: {result['error']}")
        return 1

    # Exchange the one-time code for tokens.
    try:
        resp = httpx.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": result["code"],
                "redirect_uri": REDIRECT_URI,
            },
            auth=(client_id, client_secret),
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
        )
        resp.raise_for_status()
        tokens = resp.json()
    except httpx.HTTPError as exc:
        print(f"\nToken exchange failed: {exc}")
        return 1

    refresh = tokens.get("refresh_token")
    if not refresh:
        print("\nNo refresh_token returned. Was the app created as a 'web app' "
              "with duration=permanent? Response was:")
        print(tokens)
        return 1

    print("\n" + "=" * 64)
    print("SUCCESS. Add this line to your .env:\n")
    print(f"REDDIT_REFRESH_TOKEN={refresh}")
    print("=" * 64 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
