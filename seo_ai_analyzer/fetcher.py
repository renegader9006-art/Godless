from __future__ import annotations

from pathlib import Path

import certifi
import requests


DEFAULT_TIMEOUT_SECONDS = 15


def load_html_from_url(url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; SEOAnalyzerBot/1.0; +https://example.local)"
        )
    }
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers=headers,
        )
        response.raise_for_status()
        return response.text
    except requests.exceptions.SSLError:
        # Retry with explicit CA bundle if OS certificate store is broken.
        response = requests.get(
            url,
            timeout=timeout,
            headers=headers,
            verify=certifi.where(),
        )
        response.raise_for_status()
        return response.text
    except requests.exceptions.ProxyError:
        # Retry once without environment proxy vars if host proxy is misconfigured.
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(url, timeout=timeout, headers=headers)
            response.raise_for_status()
            return response.text


def load_html_from_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")
