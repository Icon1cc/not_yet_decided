"""
Text normalization and string utilities.
"""

from __future__ import annotations

import re
import unicodedata
import urllib.parse


def strip_accents(text: str) -> str:
    """Remove accents from text."""
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


def normalize_text(text: str | None) -> str:
    """
    Normalize text for comparison.
    - Strips accents
    - Converts to lowercase
    - Replaces & with 'and'
    - Removes non-alphanumeric characters
    - Normalizes whitespace
    """
    if not isinstance(text, str):
        return ""
    text = strip_accents(text).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonical_url(url: str | None) -> str | None:
    """
    Canonicalize a URL for deduplication.
    - Normalizes scheme to https
    - Removes www prefix
    - Normalizes path slashes
    - Handles Amazon /dp/ URLs specially
    """
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return None
    netloc = parsed.netloc.lower().removeprefix("www.")
    path = re.sub(r"/+", "/", parsed.path or "/")

    # Special handling for Amazon /dp/ URLs
    if "amazon." in netloc and "/dp/" in path:
        match = re.search(r"(/dp/[A-Z0-9]{10})", path, re.IGNORECASE)
        if match:
            path = match.group(1)

    return urllib.parse.urlunparse(
        (parsed.scheme.lower() or "https", netloc, path.rstrip("/"), "", "", "")
    )
