"""Tiny HTTP helper built on the standard library.

Deliberately dependency-free (urllib) so the framework installs and runs with a
bare Python. Adds a browser-ish User-Agent, a timeout, and bounded retries with
exponential backoff — the minimum needed to talk to public market-data APIs
reliably.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

DEFAULT_UA = "quantum-engine/0.1 (+https://github.com/; research)"


class HTTPError(RuntimeError):
    pass


def get(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 20.0,
    retries: int = 3,
    backoff: float = 1.0,
) -> bytes:
    """HTTP GET returning raw bytes, with retries on transient failures."""
    hdrs = {"User-Agent": DEFAULT_UA, "Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    last_exc: Optional[Exception] = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:  # 4xx/5xx
            # Client errors won't fix themselves on retry (except 429).
            if exc.code not in (429, 500, 502, 503, 504):
                raise HTTPError(f"GET {url} -> HTTP {exc.code}") from exc
            last_exc = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
        if attempt < retries - 1:
            time.sleep(backoff * (2 ** attempt))
    raise HTTPError(f"GET {url} failed after {retries} attempts: {last_exc}")


def get_json(url: str, **kwargs: Any) -> Any:
    return json.loads(get(url, **kwargs).decode("utf-8"))


def get_text(url: str, **kwargs: Any) -> str:
    return get(url, **kwargs).decode("utf-8")
