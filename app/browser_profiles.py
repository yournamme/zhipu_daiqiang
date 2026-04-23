"""Stable per-account browser impersonation helpers."""

from __future__ import annotations

import secrets

AVAILABLE_BROWSER_IMPERSONATIONS: tuple[str, ...] = (
    "chrome",
    "edge",
    "firefox",
)

DEFAULT_BROWSER_IMPERSONATE = "chrome"

DEFAULT_USER_AGENTS: dict[str, str] = {
    "chrome": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "edge": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0"
    ),
    "firefox": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) "
        "Gecko/20100101 Firefox/137.0"
    ),
}


def random_browser_impersonate() -> str:
    """Pick a browser impersonation for a new account."""
    return secrets.choice(AVAILABLE_BROWSER_IMPERSONATIONS)


def resolve_browser_impersonate(raw: str | None) -> str:
    """Normalize browser impersonation to a supported value."""
    normalized = (raw or "").strip().lower()
    if normalized in AVAILABLE_BROWSER_IMPERSONATIONS:
        return normalized
    return DEFAULT_BROWSER_IMPERSONATE


def resolve_user_agent(user_agent: str | None, browser_impersonate: str | None) -> str:
    """Return explicit UA or a stable default matching the impersonation."""
    explicit = (user_agent or "").strip()
    if explicit:
        return explicit
    return DEFAULT_USER_AGENTS.get(
        resolve_browser_impersonate(browser_impersonate),
        DEFAULT_USER_AGENTS[DEFAULT_BROWSER_IMPERSONATE],
    )
