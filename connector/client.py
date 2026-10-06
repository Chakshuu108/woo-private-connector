"""Read-only WooCommerce REST client with auth, throttling and rate-limit handling."""
import random
import threading
import time
from urllib.parse import urlparse

import requests

from . import config, oauth1


class WooError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class WooAuthError(WooError): ...
class WooNotFound(WooError): ...
class WooRateLimited(WooError): ...


class TokenBucket:
    """Client-side throttle so we rarely hit the server's limit in the first place."""

    def __init__(self, rate: float, capacity: int | None = None):
        self.rate, self.capacity = rate, capacity or max(1, int(rate))
        self.tokens, self.t = float(self.capacity), time.monotonic()
        self.lock = threading.Lock()

    def acquire(self):
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.t) * self.rate)
                self.t = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            time.sleep(wait)


class WooClient:
    API = "/wp-json/wc/v3"
    RETRY_STATUS = {429, 502, 503, 504}

    def __init__(self, base_url=None, key=None, secret=None, auth_mode=None, rps=None,
                 max_retries=None, backoff_base=0.5, max_backoff=30.0, timeout=15):
        self.base_url = (base_url or config.WOO_BASE_URL).rstrip("/")
        self.key = key or config.WOO_CONSUMER_KEY
        self.secret = secret or config.WOO_CONSUMER_SECRET
        mode = auth_mode or config.WOO_AUTH_MODE
        if mode == "auto":
            mode = "basic" if self.base_url.startswith("https") else "oauth1"
        self.auth_mode = mode
        self.bucket = TokenBucket(rps or config.WOO_RPS)
        self.max_retries = config.WOO_MAX_RETRIES if max_retries is None else max_retries
        self.backoff_base, self.max_backoff, self.timeout = backoff_base, max_backoff, timeout
        self.session = requests.Session()
        self.stats = {"requests": 0, "retries": 0, "rate_limited": 0}

    # ---- public: GET only. There is deliberately no post/put/delete. ----
    def get(self, path: str, params: dict | None = None):
        """Returns (json_body, response_headers)."""
        url = f"{self.base_url}{self.API}{path}"
        params = {k: v for k, v in (params or {}).items() if v is not None}
        attempt = 0
        while True:
            self.bucket.acquire()
            self.stats["requests"] += 1
            try:
                resp = self._send(url, params)
            except (requests.ConnectionError, requests.Timeout) as e:
                if attempt >= self.max_retries:
                    raise WooError(f"network error: {e}") from e
                self._sleep(attempt, None)
                attempt += 1
                continue

            if resp.status_code in self.RETRY_STATUS:
                if resp.status_code == 429:
                    self.stats["rate_limited"] += 1
                if attempt >= self.max_retries:
                    cls = WooRateLimited if resp.status_code == 429 else WooError
                    raise cls(f"giving up after {attempt} retries (HTTP {resp.status_code})", resp.status_code)
                self._sleep(attempt, resp.headers.get("Retry-After"))
                attempt += 1
                continue
            return self._handle(resp)

    def ping(self) -> bool:
        self.get("/products", {"per_page": 1})
        return True

    # ---- internals ----
    def _send(self, url, params):
        if self.auth_mode == "basic":
            return self.session.get(url, params=params, auth=(self.key, self.secret), timeout=self.timeout)
        u = urlparse(url)
        signed = oauth1.sign("GET", f"{u.scheme}://{u.netloc}{u.path}", params, self.key, self.secret)
        return self.session.get(url, params=signed, timeout=self.timeout)

    def _sleep(self, attempt, retry_after):
        self.stats["retries"] += 1
        try:
            delay = float(retry_after)          # server told us how long to wait
        except (TypeError, ValueError):
            delay = self.backoff_base * (2 ** attempt) * (0.5 + random.random())  # exp. backoff + jitter
        time.sleep(min(delay, self.max_backoff))

    @staticmethod
    def _handle(resp):
        if resp.status_code in (401, 403):
            raise WooAuthError("authentication failed - check consumer key/secret and key permissions", resp.status_code)
        if resp.status_code == 404:
            raise WooNotFound("resource not found", 404)
        if not resp.ok:
            try:
                msg = resp.json().get("message", resp.text[:200])
            except ValueError:
                msg = resp.text[:200]
            raise WooError(f"HTTP {resp.status_code}: {msg}", resp.status_code)
        return resp.json(), resp.headers
