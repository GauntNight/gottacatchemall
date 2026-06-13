"""Push notifier (ntfy.sh) with a console dry-run fallback.

Design rule #6: the payload carries retailer, product, old->new state,
price, and the direct URL — alert-to-checkout time is the real metric, so
the URL is the whole point.
"""

from __future__ import annotations

import logging

import httpx

from .models import Alert, Status

log = logging.getLogger("tcgmon.notifier")


def _format(alert: Alert) -> tuple[str, str]:
    product = alert.title or alert.key
    if alert.new_status is Status.IN_STOCK:
        title = f"🟢 IN STOCK: {product}"
    elif alert.new_status is Status.LISTED:
        title = f"🆕 NEW: {product}"
    else:
        title = f"{product}: {alert.new_status.value}"

    transition = (
        f"{alert.old_status.value if alert.old_status else 'absent'}"
        f" → {alert.new_status.value}"
    )
    lines = [f"[{alert.source}] {transition}"]
    if alert.price:
        lines.append(f"Price: {alert.price}")
    if alert.url:
        lines.append(alert.url)
    return title, "\n".join(lines)


class Notifier:
    def __init__(self, server: str, topic: str) -> None:
        self.server = server.rstrip("/")
        self.topic = topic

    async def send(self, alert: Alert, client: httpx.AsyncClient) -> None:
        title, body = _format(alert)

        if not self.topic:
            log.info("DRY-RUN notify | %s | %s", title, body.replace("\n", " | "))
            return

        # ntfy's header-based publishing requires ASCII header values, so a
        # title with an emoji (🟢) or an accented product name (Pokémon)
        # raises UnicodeEncodeError — and that's the IN_STOCK alert we care
        # about most. Use JSON publishing instead: title/message ride in a
        # UTF-8 body, so unicode is safe. Priority is an int (5=max .. 1=min).
        payload: dict = {
            "topic": self.topic,
            "title": title,
            "message": body,
            "tags": ["shopping_cart"] if alert.new_status is Status.IN_STOCK else ["bell"],
            "priority": 5 if alert.new_status is Status.IN_STOCK else 3,
        }
        if alert.url:
            payload["click"] = alert.url
        try:
            resp = await client.post(self.server, json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as exc:  # never let a notify failure kill a job
            log.warning("ntfy send failed: %s", exc)
