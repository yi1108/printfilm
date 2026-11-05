"""Validate a public share origin without network requests or secret material."""
from ipaddress import ip_address
from urllib.parse import urlsplit
import re


def validate_android_association(package: str, fingerprints: str) -> tuple[str, str]:
    package = package.strip()
    if package and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+", package):
        raise ValueError("Android 包名格式无效，例如 com.example.app。")
    values = []
    for value in re.split(r"[\r\n,;]+", fingerprints):
        value = value.strip().upper()
        if not value:
            continue
        if not re.fullmatch(r"(?:[0-9A-F]{2}:){31}[0-9A-F]{2}", value):
            raise ValueError("Android SHA-256 指纹必须是32组冒号分隔的十六进制字节。")
        if value not in values:
            values.append(value)
    if bool(package) != bool(values):
        raise ValueError("Android 包名和签名证书 SHA-256 指纹必须一起填写或一起清空。")
    return package, "\n".join(values)


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
