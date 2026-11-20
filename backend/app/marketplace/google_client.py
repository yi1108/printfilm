"""Publisher REST client. Network calls must run outside money transactions."""
import asyncio
import hashlib
import time
import logging
import re
from urllib.parse import quote
import httpx
from jose import jwt
from .google_config import credentials, fail

_access = {}
_access_lock = asyncio.Lock()
_certs = (0, {})
BASE = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications/"


class GoogleTokenFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        if "androidpublisher.googleapis.com" in message or "/tokens/" in message:
            record.msg = re.sub(r"(/tokens/)[^\s\"?]+", r"\1[redacted]", message)
            record.args = ()
        return True


for _name in ("httpx", "httpcore.http11", "httpcore.http2"):
    _logger = logging.getLogger(_name)
    if not any(isinstance(f, GoogleTokenFilter) for f in _logger.filters):
        _logger.addFilter(GoogleTokenFilter())


async def access_token(secret):
    digest = hashlib.sha256(secret.encode()).hexdigest()
    async with _access_lock:
        cached = _access.get(digest)
        if cached and cached[0] > time.time() + 60:
            return cached[1]
        data = credentials(secret)
        instant = int(time.time())
        assertion = jwt.encode(dict(iss=data["client_email"], scope="https://www.googleapis.com/auth/androidpublisher",
            aud="https://oauth2.googleapis.com/token", iat=instant, exp=instant + 3600),
            data["private_key"], algorithm="RS256")
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post("https://oauth2.googleapis.com/token", data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})
                response.raise_for_status()
                result = response.json()
                token = result["access_token"]
                _access.clear()
                _access[digest] = (time.time() + min(int(result["expires_in"]), 3600), token)
                return token
        except (httpx.HTTPError, KeyError, ValueError):
            fail("GOOGLE_AUTH_UNAVAILABLE", "Google 授权失败，请检查服务账号权限。", "Google authentication unavailable.", 503)


async def request(secret, package, path, *, method="GET", params=None, allow_consumed=False):
    token = await access_token(secret)
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.request(method, BASE + quote(package, safe="") + "/" + path,
                headers={"Authorization": "Bearer " + token}, params=params)
        # Concurrent client consumption is confirmed by the next purchase query;
        # an arbitrary 400/409 is never proof of consumption.
        response.raise_for_status()
        return response.json() if response.content else {}
    except (httpx.HTTPError, ValueError):
        fail("GOOGLE_UPSTREAM_UNAVAILABLE", "Google 凭证查询暂时失败，请稍后重试。", "Google purchase verification temporarily unavailable.", 503)


async def query(secret, package, product, token):
    return await request(secret, package, f"purchases/products/{quote(product, safe='')}/tokens/{quote(token, safe='')}")


async def consume(secret, package, product, token):
    await request(secret, package, f"purchases/products/{quote(product, safe='')}/tokens/{quote(token, safe='')}:consume",
        method="POST", allow_consumed=True)


async def verify_push(bearer, config):
    """Verify Google-signed Pub/Sub OIDC JWT, exact audience and service account."""
    global _certs
    if not config.get("rtdn_audience") or not config.get("rtdn_service_account"):
        fail("GOOGLE_RTDN_UNAVAILABLE", "Google 通知验证尚未配置。", "RTDN authentication is not configured.", 503)
    try:
        header = jwt.get_unverified_header(bearer)
        if header.get("alg") != "RS256":
            raise ValueError()
        if _certs[0] < time.time() or header.get("kid") not in _certs[1]:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get("https://www.googleapis.com/oauth2/v1/certs")
                response.raise_for_status()
                _certs = (time.time() + 1800, response.json())
        claims = jwt.decode(bearer, _certs[1][header["kid"]], algorithms=["RS256"],
            audience=config["rtdn_audience"], options={"require_exp": True, "require_iat": True})
        if (claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com")
                or claims.get("email") != config["rtdn_service_account"] or claims.get("email_verified") is not True):
            raise ValueError()
    except (ValueError, KeyError, jwt.JWTError, httpx.HTTPError):
        fail("GOOGLE_RTDN_UNAUTHORIZED", "通知身份验证失败。", "Invalid notification identity.", 401)
