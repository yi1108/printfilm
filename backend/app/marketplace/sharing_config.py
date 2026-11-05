"""Validate a public share origin without network requests or secret material."""
from ipaddress import ip_address
from urllib.parse import urlsplit


def validate_share_origin(value: str) -> str:
    value = value.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname or ""
        port = parsed.port
    except ValueError as exc:
        raise ValueError("作品分享地址必须为有效的公网 HTTPS 根地址。") from exc
    if (parsed.scheme != "https" or not hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or port not in (None, 443)
            or any(char.isspace() for char in value) or "\\" in value):
        raise ValueError("作品分享地址必须为公网 HTTPS 根地址，不能包含路径、账号或查询参数。")
    lowered = hostname.lower().rstrip(".")
    if lowered in ("localhost", "localhost.localdomain") or lowered.endswith((".localhost", ".local", ".internal")) or "." not in lowered:
        raise ValueError("作品分享地址不能使用本机或局域网地址。")
    try:
        address = ip_address(hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("作品分享地址不能使用本机或局域网地址。")
    return value
