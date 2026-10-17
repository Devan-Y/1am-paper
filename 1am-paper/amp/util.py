"""Small shared helpers: HTTP with retries, dates in New York time, text cleanup.

Standard library only, so the project needs no `pip install`.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "one-am-paper/1.0 (+https://github.com; nightly literature digest)"


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message[:300]}")
        self.status = status
        self.body = message


def http_request(url: str, *, method: str = "GET", data: bytes | None = None,
                 headers: dict | None = None, timeout: float = 60,
                 retries: int = 3, backoff: float = 5.0) -> bytes:
    """Fetch a URL and return the body bytes. Retries on 429, 5xx and network errors."""
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace") if e.fp else ""
            last_err = HttpError(e.code, body)
            if e.code == 429 or 500 <= e.code < 600:
                wait = backoff * (2 ** attempt)
                retry_after = e.headers.get("Retry-After") if e.headers else None
                if retry_after and retry_after.isdigit():
                    wait = max(wait, int(retry_after))
                if attempt < retries:
                    time.sleep(min(wait, 120))
                    continue
            raise last_err
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(backoff * (2 ** attempt))
                continue
            raise
    raise last_err  # pragma: no cover


def get_json(url: str, params: dict | None = None, **kw) -> dict:
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    return json.loads(http_request(url, **kw).decode("utf-8"))


def get_text(url: str, **kw) -> str:
    return http_request(url, **kw).decode("utf-8", "replace")


def post_json(url: str, payload: dict, headers: dict | None = None, **kw) -> dict:
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    body = http_request(url, method="POST", data=json.dumps(payload).encode("utf-8"),
                        headers=hdrs, **kw)
    return json.loads(body.decode("utf-8"))


# ---------------------------------------------------------------- dates

def _us_eastern_offset(utc_now: dt.datetime) -> dt.timedelta:
    """UTC offset for US Eastern time without the tz database (Windows fallback).
    DST runs from 2:00 local on the 2nd Sunday of March to 2:00 local on the 1st Sunday of November."""
    year = utc_now.year

    def nth_sunday(month: int, n: int) -> dt.date:
        d = dt.date(year, month, 1)
        d += dt.timedelta(days=(6 - d.weekday()) % 7)
        return d + dt.timedelta(weeks=n - 1)

    dst_start_utc = dt.datetime.combine(nth_sunday(3, 2), dt.time(7, 0))   # 2:00 EST = 7:00 UTC
    dst_end_utc = dt.datetime.combine(nth_sunday(11, 1), dt.time(6, 0))    # 2:00 EDT = 6:00 UTC
    naive = utc_now.replace(tzinfo=None)
    return dt.timedelta(hours=-4) if dst_start_utc <= naive < dst_end_utc else dt.timedelta(hours=-5)


def local_now(tz_name: str = "America/New_York") -> dt.datetime:
    utc_now = dt.datetime.now(dt.timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return utc_now.astimezone(ZoneInfo(tz_name))
    except Exception:
        if tz_name != "America/New_York":
            raise
        return (utc_now + _us_eastern_offset(utc_now)).replace(tzinfo=None)


def parse_date(s: str | None) -> dt.date | None:
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        return None


def fmt_short(d: dt.date) -> str:
    """Sep 8, 2026"""
    return f"{d:%b} {d.day}, {d.year}"


def fmt_masthead(d: dt.date) -> str:
    """Fri Oct 16, 2026"""
    return f"{d:%a} {d:%b} {d.day}, {d.year}"


# ---------------------------------------------------------------- text

_ws = re.compile(r"\s+")


def squash(s: str) -> str:
    return _ws.sub(" ", s or "").strip()


def word_count(s: str) -> int:
    return len(re.findall(r"\S+", s or ""))


def truncate_words(s: str, n: int) -> str:
    words = (s or "").split()
    return s if len(words) <= n else " ".join(words[:n]) + " …"
