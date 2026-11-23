"""Domestic Android H5 payment readiness; settings never imply provider certification."""
import re
from urllib.parse import urlsplit
from app.config import get_settings
from app.marketplace.sharing_config import validate_android_association, validate_share_origin

FIELDS = ("android_epay_enabled", "android_epay_alipay_enabled", "android_epay_wxpay_enabled",
          "android_epay_package_name", "android_epay_sha256_fingerprints", "android_epay_return_base_url",
          "android_epay_checkout_hosts", "android_epay_app_scheme")

def validate(config):
    package = config.get("android_epay_package_name", "").strip()
    fingerprints = config.get("android_epay_sha256_fingerprints", "").strip()
    if fingerprints:
        package, fingerprints = validate_android_association(package, fingerprints)
    elif package and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+", package):
        raise ValueError("Android 包名格式无效。")
    config["android_epay_package_name"], config["android_epay_sha256_fingerprints"] = package, fingerprints
    origin = config.get("android_epay_return_base_url", "")
    if origin:
        config["android_epay_return_base_url"] = validate_payment_origin(origin)
    scheme = config.get("android_epay_app_scheme", "").strip().lower()
    if scheme and (not re.fullmatch(r"[a-z][a-z0-9+.-]{1,39}", scheme) or scheme in ("http", "https", "javascript", "file", "intent", "data")):
        raise ValueError("安卓返回 App 协议格式无效。")
    config["android_epay_app_scheme"] = scheme
    hosts = []
    for host in config.get("android_epay_checkout_hosts", "").split(","):
        host = host.strip().lower()
        if not host:
            continue
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) or ".." in host or "." not in host:
            raise ValueError("收银台白名单只填写完整主机名，用英文逗号分隔，不支持通配符。")
        if host not in hosts:
            hosts.append(host)
    config["android_epay_checkout_hosts"] = ",".join(hosts)
    if config.get("android_epay_enabled"):
        if not config.get("epay_pid") or not config.get("epay_key"):
            raise ValueError("请先配置现有网页支付商户凭证。")
        payment_return_origin(config)
        api = urlsplit(config.get("epay_api_url", ""))
        if api.scheme != "https" or not api.hostname or api.username or api.password or api.query or api.fragment:
            raise ValueError("安卓支付必须使用 HTTPS 易支付服务地址。")
        if not (config.get("android_epay_alipay_enabled") or config.get("android_epay_wxpay_enabled")):
            raise ValueError("请至少确认并开启一种移动收银台渠道。")
    return config

def readiness(cfg=None):
    cfg = cfg or get_settings()
    missing = []
    try:
        validate({name: getattr(cfg, name) for name in FIELDS + ("epay_api_url", "epay_pid", "epay_key", "public_base_url")})
    except ValueError:
        missing.append("configuration_incomplete")
    if not cfg.android_epay_enabled:
        missing.append("android_payment_disabled")
    if not cfg.epay_pid or not cfg.epay_key:
        missing.append("merchant_unconfigured")
    if not cfg.unified_wallet_enabled:
        missing.append("unified_wallet_disabled")
    if cfg.wallet_environment != "Production":
        missing.append("production_wallet_required")
    channels = [name for name, enabled in (("alipay", cfg.android_epay_alipay_enabled),
        ("wxpay", cfg.android_epay_wxpay_enabled)) if enabled]
    if not channels:
        missing.append("mobile_channels_disabled")
    return {"available": not missing, "unavailable_reasons": missing, "pay_types": channels if not missing else [],
            "payment_client": "android_domestic", "environment": "Production"}

def checkout_url(value, cfg):
    value = str(value or "").strip()
    try:
        url = urlsplit(value)
        allowed = {urlsplit(cfg.epay_api_url).hostname}
        allowed.update(part.strip().lower() for part in cfg.android_epay_checkout_hosts.split(",") if part.strip())
        if (url.scheme != "https" or not url.hostname or url.hostname.lower() not in allowed or url.port not in (None, 443)
            or url.username or url.password or any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value):
            raise ValueError()
    except ValueError:
        raise ValueError("易支付未返回受信任的 HTTPS 移动收银台链接，请检查供应商能力和域名白名单。") from None
    return value


def payment_return_origin(config):
    """Use the existing public Web site unless an optional return origin is configured."""
    explicit = (config.get("android_epay_return_base_url") or "").strip()
    if explicit:
        return validate_payment_origin(explicit)
    # Admin flat settings intentionally exclude deployment-only fields.
    value = config.get("public_base_url", get_settings().public_base_url)
    try:
        return validate_payment_origin(value)
    except ValueError:
        raise ValueError("支付返回站点留空，但现有网站地址未配置为公网 HTTPS 根地址。请在「支付后返回 App → 返回站点」填写网页站点根地址，例如 https://www.printfilm.com。") from None


def validate_payment_origin(value):
    try:
        return validate_share_origin(value)
    except ValueError:
        raise ValueError("支付返回站点必须是公网 HTTPS 根地址，例如 https://www.printfilm.com；不能包含路径、账号或查询参数。") from None
