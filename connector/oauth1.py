"""OAuth 1.0a one-legged signing, as used by WooCommerce REST over plain HTTP."""
import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import quote


def _enc(v) -> str:
    return quote(str(v), safe="~")


def signature(method: str, url: str, params: dict, consumer_secret: str) -> str:
    """url must have no query string; params = every query param except oauth_signature."""
    pairs = sorted((_enc(k), _enc(v)) for k, v in params.items())
    param_str = "&".join(f"{k}={v}" for k, v in pairs)
    base = "&".join([method.upper(), _enc(url), _enc(param_str)])
    digest = hmac.new((consumer_secret + "&").encode(), base.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def sign(method: str, url: str, params: dict, key: str, secret: str) -> dict:
    p = dict(params)
    p.update({
        "oauth_consumer_key": key,
        "oauth_timestamp": str(int(time.time())),
        "oauth_nonce": secrets.token_hex(8),
        "oauth_signature_method": "HMAC-SHA256",
    })
    p["oauth_signature"] = signature(method, url, p, secret)
    return p
