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

        headers = {"Title": title}
        if alert.url:
            headers["Click"] = alert.url
        headers["Tags"] = (
            "shopping_cart" if alert.new_status is Status.IN_STOCK else "bell"
        )
        headers["Priority"] = (
            "high" if alert.new_status is Status.IN_STOCK else "default"
        )
        try:
            resp = await client.post(
                f"{self.server}/{self.topic}",
                content=body.encode("utf-8"),
                headers=headers,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:  # never let a notify failure kill a job
            log.warning("ntfy send failed: %s", exc)
