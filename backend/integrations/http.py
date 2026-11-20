"""Bounded metadata GET cache and transient-failure retry policy."""
import asyncio
from collections import OrderedDict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import random
from threading import Lock
from time import monotonic

import httpx


_cache = OrderedDict()
_lock = Lock()


def clear_cache():
    with _lock:
        _cache.clear()


def retry_delay(response, attempt):
    value = response.headers.get("Retry-After") if response is not None else None
    if value:
        if value.isdigit():
            return int(value)
        try:
            return max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            pass
    return 0.25 * 2 ** attempt + random.uniform(0, 0.1)


async def metadata_get(client, url, **kwargs):
    # Hash the full identity, including credentials, without storing secret-bearing URLs as keys.
    key = hashlib.sha256(json.dumps([url, kwargs], sort_keys=True).encode()).digest()
    with _lock:
        entry = _cache.get(key)
        if entry and entry[0] > monotonic():
            _cache.move_to_end(key)
            return httpx.Response(200, content=entry[1], headers=entry[2], request=httpx.Request("GET", url))
    for attempt in range(3):
        try:
            response = await client.get(url, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError):
            if attempt == 2:
                raise
            await asyncio.sleep(retry_delay(None, attempt))
            continue
        if response.status_code not in (429, 502, 503, 504) or attempt == 2:
            break
        delay = retry_delay(response, attempt)
        if delay > 3:
            return response
        await asyncio.sleep(delay)
    if (response.status_code == 200 and len(response.content) <= 262144
            and "no-store" not in response.headers.get("cache-control", "").lower()):
        with _lock:
            _cache[key] = (monotonic() + 300, response.content,
                           {"content-type": response.headers.get("content-type", "application/json")})
            _cache.move_to_end(key)
            if len(_cache) > 128:
                _cache.popitem(last=False)
    return response
