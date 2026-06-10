"""Fetcher protocol and registry.

A fetcher is an async callable ``(target, client) -> list[Observation]``.
It must fail soft: on a challenge, timeout, or parse error, return an
``UNKNOWN`` observation (or an empty list), never raise. The scheduler
also wraps every call, but fetchers own their own error semantics.
"""

from __future__ import annotations

from typing import Awaitable, Callable

import httpx

from ..config import Target
from ..models import Observation

Fetcher = Callable[[Target, httpx.AsyncClient], Awaitable[list[Observation]]]

_REGISTRY: dict[str, Fetcher] = {}


def register(name: str) -> Callable[[Fetcher], Fetcher]:
    def deco(fn: Fetcher) -> Fetcher:
        _REGISTRY[name] = fn
        return fn

    return deco


def get_fetcher(name: str) -> Fetcher:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"unknown fetcher {name!r}; registered: {sorted(_REGISTRY)}"
        ) from None


def registered() -> list[str]:
    return sorted(_REGISTRY)
