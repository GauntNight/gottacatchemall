"""Configuration: ``targets.yaml`` (what to watch) + ``.env`` (secrets).

Design rule #5: targets are config-driven. Adding the next set is editing
YAML, not code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()  # pull .env into os.environ if present


@dataclass(slots=True)
class Target:
    """One thing to watch, mapped to a fetcher by ``fetcher`` name."""

    name: str
    fetcher: str
    url: str = ""
    interval_minutes: float = 15.0
    # ``keywords``: ANY-of filter (OR). Empty = match everything.
    keywords: list[str] = field(default_factory=list)
    # ``require``: ALL-of filter (AND). Every term must be present. Empty =
    # no constraint. Combine the two to express "(any purchase signal) AND
    # (the set name)" — e.g. keywords=[preorder, "now live"], require=["pitch black"].
    require: list[str] = field(default_factory=list)
    enabled: bool = True
    # Free-form per-fetcher options (e.g. Best Buy search term, key names).
    options: dict = field(default_factory=dict)

    @property
    def interval_seconds(self) -> float:
        return self.interval_minutes * 60.0

    def matches(self, text: str) -> bool:
        """True if ``text`` passes this target's keyword filter.

        ``keywords`` is OR (at least one must appear, unless empty);
        ``require`` is AND (every term must appear). Both are case-insensitive
        substring tests. Used by every Tier-1 fetcher so filtering is uniform.
        """
        low = text.lower()
        if self.keywords and not any(kw.lower() in low for kw in self.keywords):
            return False
        if self.require and not all(req.lower() in low for req in self.require):
            return False
        return True


@dataclass(slots=True)
class Settings:
    db_path: str = "state.db"
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: str = ""               # empty -> dry-run (console only)
    bestbuy_api_key: str = ""
    jitter_spread: float = 0.3
    targets: list[Target] = field(default_factory=list)


def load_targets(path: str | Path) -> list[Target]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    out: list[Target] = []
    for entry in raw.get("targets", []):
        out.append(
            Target(
                name=entry["name"],
                fetcher=entry["fetcher"],
                url=entry.get("url", ""),
                interval_minutes=float(entry.get("interval_minutes", 15)),
                keywords=list(entry.get("keywords", [])),
                require=list(entry.get("require", [])),
                enabled=bool(entry.get("enabled", True)),
                options=dict(entry.get("options", {})),
            )
        )
    return out


def load_settings(targets_path: str | Path = "targets.yaml") -> Settings:
    return Settings(
        db_path=os.environ.get("TCGMON_DB", "state.db"),
        ntfy_server=os.environ.get("NTFY_SERVER", "https://ntfy.sh"),
        ntfy_topic=os.environ.get("NTFY_TOPIC", ""),
        bestbuy_api_key=os.environ.get("BESTBUY_API_KEY", ""),
        jitter_spread=float(os.environ.get("TCGMON_JITTER", "0.3")),
        targets=load_targets(targets_path),
    )
