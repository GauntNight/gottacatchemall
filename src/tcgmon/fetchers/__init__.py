"""Fetcher package. Importing it registers every fetcher implementation."""

from __future__ import annotations

from .base import Fetcher, get_fetcher, register, registered

# Import side effects populate the registry. Phase 1 + 2 are functional;
# Phase 3 fetchers are best-effort and fail soft to UNKNOWN.
from . import reddit_json  # noqa: F401,E402  (Tier 1)
from . import rss  # noqa: F401,E402           (Tier 1)
from . import shopify_json  # noqa: F401,E402  (Tier 2)
from . import bestbuy_api  # noqa: F401,E402   (Tier 2)
from . import redsky  # noqa: F401,E402        (Tier 2, Phase 3)
from . import nextdata  # noqa: F401,E402      (Tier 2, Phase 3 — Walmart)
from . import html_button  # noqa: F401,E402   (Tier 2, Phase 3 — generic)

__all__ = ["Fetcher", "get_fetcher", "register", "registered"]
