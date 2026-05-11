"""Stable per-account browser fingerprint profile helpers."""

from __future__ import annotations

from dataclasses import dataclass
import secrets


@dataclass(frozen=True)
class BrowserProfile:
    """A coherent browser profile: stored id, curl-cffi TLS profile, UA, and Client Hints."""

    profile_id: str
    family: str       # "chrome" | "firefox" | "safari" | "edge"
    version: str
    impersonate: str  # curl-cffi impersonate target
    user_agent: str
    random_weight: int = 1
    enabled_for_random: bool = True
    platform: str = "windows"        # "windows" | "macos" | "android"
    sec_ch_ua: str = ""              # Low-entropy Client Hints string; "" for Firefox/Safari
    sec_ch_ua_platform: str = ""     # "Windows" | "macOS" | ""; "" for Firefox/Safari


# ---------------------------------------------------------------------------
# User-Agent strings
# ---------------------------------------------------------------------------

# Windows Chrome
WINDOWS_CHROME_146_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)
WINDOWS_CHROME_145_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)
WINDOWS_CHROME_136_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)
WINDOWS_CHROME_131_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# macOS Chrome
MACOS_CHROME_146_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)
MACOS_CHROME_145_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)

# Windows Firefox
WINDOWS_FIREFOX_149_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
    "Gecko/20100101 Firefox/149.0"
)

# Windows Edge (Chromium-based)
WINDOWS_EDGE_146_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0"
)

# ---------------------------------------------------------------------------
# Sec-CH-UA strings (low-entropy Client Hints, sent without server opt-in)
# The "Not/A)Brand" placeholder rotates alphabetically across Chrome releases.
# ---------------------------------------------------------------------------
SEC_CH_UA_CHROME_146 = '"Chromium";v="146", "Google Chrome";v="146", "Not/A)Brand";v="99"'
SEC_CH_UA_CHROME_145 = '"Chromium";v="145", "Google Chrome";v="145", "Not/A)Brand";v="24"'
SEC_CH_UA_CHROME_136 = '"Chromium";v="136", "Google Chrome";v="136", "Not/A)Brand";v="8"'
SEC_CH_UA_CHROME_131 = '"Chromium";v="131", "Google Chrome";v="131", "Not/A)Brand";v="24"'
SEC_CH_UA_EDGE_146   = '"Microsoft Edge";v="146", "Chromium";v="146", "Not/A)Brand";v="99"'

# ---------------------------------------------------------------------------
# Profile catalogue
# NOTE: profile_id keys use the normalized form (lowercase, no dashes/underscores)
# so that resolve_browser_impersonate() can find them after normalization.
# ---------------------------------------------------------------------------
AVAILABLE_BROWSER_PROFILES: dict[str, BrowserProfile] = {
    # ── Chrome 146 ──────────────────────────────────────────────────────────
    "chrome146": BrowserProfile(
        profile_id="chrome146",
        family="chrome",
        version="146",
        impersonate="chrome146",
        user_agent=WINDOWS_CHROME_146_UA,
        random_weight=28,
        platform="windows",
        sec_ch_ua=SEC_CH_UA_CHROME_146,
        sec_ch_ua_platform="Windows",
    ),
    "chrome146mac": BrowserProfile(
        profile_id="chrome146mac",
        family="chrome",
        version="146",
        impersonate="chrome146",
        user_agent=MACOS_CHROME_146_UA,
        random_weight=10,
        enabled_for_random=False,
        platform="macos",
        sec_ch_ua=SEC_CH_UA_CHROME_146,
        sec_ch_ua_platform="macOS",
    ),
    # ── Chrome 145 ──────────────────────────────────────────────────────────
    "chrome145": BrowserProfile(
        profile_id="chrome145",
        family="chrome",
        version="145",
        impersonate="chrome145",
        user_agent=WINDOWS_CHROME_145_UA,
        random_weight=4,
        platform="windows",
        sec_ch_ua=SEC_CH_UA_CHROME_145,
        sec_ch_ua_platform="Windows",
    ),
    "chrome145mac": BrowserProfile(
        profile_id="chrome145mac",
        family="chrome",
        version="145",
        impersonate="chrome145",
        user_agent=MACOS_CHROME_145_UA,
        random_weight=2,
        enabled_for_random=False,
        platform="macos",
        sec_ch_ua=SEC_CH_UA_CHROME_145,
        sec_ch_ua_platform="macOS",
    ),
    # ── Chrome 136 ──────────────────────────────────────────────────────────
    "chrome136": BrowserProfile(
        profile_id="chrome136",
        family="chrome",
        version="136",
        impersonate="chrome136",
        user_agent=WINDOWS_CHROME_136_UA,
        random_weight=3,
        platform="windows",
        sec_ch_ua=SEC_CH_UA_CHROME_136,
        sec_ch_ua_platform="Windows",
    ),
    # ── Chrome 131 ──────────────────────────────────────────────────────────
    "chrome131": BrowserProfile(
        profile_id="chrome131",
        family="chrome",
        version="131",
        impersonate="chrome131",
        user_agent=WINDOWS_CHROME_131_UA,
        random_weight=2,
        platform="windows",
        sec_ch_ua=SEC_CH_UA_CHROME_131,
        sec_ch_ua_platform="Windows",
    ),
    # ── Firefox 149 ─────────────────────────────────────────────────────────
    # Firefox does NOT send sec-ch-ua (Client Hints); sec_ch_ua stays empty.
    "firefox149": BrowserProfile(
        profile_id="firefox149",
        family="firefox",
        version="149",
        impersonate="firefox147",
        user_agent=WINDOWS_FIREFOX_149_UA,
        random_weight=5,
        enabled_for_random=False,
        platform="windows",
        sec_ch_ua="",
        sec_ch_ua_platform="",
    ),
    # ── Edge 146 ────────────────────────────────────────────────────────────
    # curl-cffi 0.15+ supports modern Chrome 146 TLS profile, so Edge 146 can
    # route transport through the matching Chromium generation.
    # to avoid mismatching a modern Edge UA with a very old TLS fingerprint.
    "edge146": BrowserProfile(
        profile_id="edge146",
        family="edge",
        version="146",
        impersonate="chrome146",
        user_agent=WINDOWS_EDGE_146_UA,
        random_weight=6,
        enabled_for_random=False,
        platform="windows",
        sec_ch_ua=SEC_CH_UA_EDGE_146,
        sec_ch_ua_platform="Windows",
    ),
}

# Total weight: 28+10+4+2+3+2+5+6 = 60
# Chrome 146 Win+Mac: ~63 %  |  Chrome 145: ~10 %  |  Chrome 136: ~5 %
# Chrome 131: ~3 %  |  Firefox: ~8 %  |  Edge: ~10 %

DEFAULT_BROWSER_PROFILE_ID = "chrome146"
DEFAULT_BROWSER_IMPERSONATE = DEFAULT_BROWSER_PROFILE_ID
AVAILABLE_BROWSER_IMPERSONATIONS: tuple[str, ...] = tuple(AVAILABLE_BROWSER_PROFILES)

DEFAULT_USER_AGENTS: dict[str, str] = {
    profile_id: profile.user_agent for profile_id, profile in AVAILABLE_BROWSER_PROFILES.items()
}

# ---------------------------------------------------------------------------
# Legacy / shorthand aliases  (all normalized: lowercase, no dash/underscore)
# ---------------------------------------------------------------------------
LEGACY_BROWSER_PROFILE_ALIASES: dict[str, str] = {
    # Generic family shorthands
    "chrome": "chrome146",
    "edge": "edge146",
    "firefox": "firefox149",
    # Old specific-version names that no longer exist as primary keys
    "chrome124": "chrome146",
    "chromemac": "chrome146mac",
    "edge101": "edge146",
    "firefox137": "firefox149",
    "firefox147": "firefox149",
}


def random_browser_impersonate() -> str:
    """Pick a realistic browser fingerprint profile for a new account."""
    candidates = [
        profile.profile_id
        for profile in AVAILABLE_BROWSER_PROFILES.values()
        if profile.enabled_for_random
        for _ in range(max(1, profile.random_weight))
    ]
    return secrets.choice(candidates)


def resolve_browser_impersonate(raw: str | None) -> str:
    """Normalize a stored profile id to a supported browser fingerprint profile key."""
    normalized = (raw or "").strip().lower().replace("_", "").replace("-", "")
    if normalized in AVAILABLE_BROWSER_PROFILES:
        return normalized
    return LEGACY_BROWSER_PROFILE_ALIASES.get(normalized, DEFAULT_BROWSER_PROFILE_ID)


def resolve_transport_impersonate(browser_impersonate: str | None) -> str:
    """Return the curl-cffi impersonate value for a stored profile id."""
    profile_id = resolve_browser_impersonate(browser_impersonate)
    return AVAILABLE_BROWSER_PROFILES[profile_id].impersonate


def resolve_user_agent(user_agent: str | None, browser_impersonate: str | None) -> str:
    """Return explicit UA or a stable default matching the fingerprint profile."""
    explicit = (user_agent or "").strip()
    if explicit:
        return explicit
    profile_id = resolve_browser_impersonate(browser_impersonate)
    return AVAILABLE_BROWSER_PROFILES[profile_id].user_agent
