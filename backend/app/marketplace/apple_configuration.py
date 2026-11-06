"""Admin-managed Apple credentials; secrets never appear in diagnostics."""
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def validate_material(private_key: str, certificates: str) -> None:
    if private_key:
        try:
            key = serialization.load_pem_private_key(private_key.encode(), password=None)
            if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
                raise ValueError
        except Exception:
            raise ValueError("Apple 私钥必须是有效的未加密 P-256 .p8 私钥。") from None
    if certificates:
        try:
            roots = x509.load_pem_x509_certificates(certificates.encode())
            if not roots:
                raise ValueError
            for root in roots:
                if root.issuer != root.subject or not root.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
                    raise ValueError
                root.verify_directly_issued_by(root)
        except Exception:
            raise ValueError("请上传有效的 Apple 根 CA 证书（PEM 或 DER），不能使用交易签名或叶证书。") from None


def material(cfg):
    key = cfg.apple_private_key
    if not key and cfg.apple_private_key_path:
        key = Path(cfg.apple_private_key_path).read_text(encoding="utf-8")
    certificates = cfg.apple_root_certificates
    if not certificates and cfg.certificate_paths():
        roots = []
        for path in cfg.certificate_paths():
            data = path.read_bytes()
            cert = x509.load_pem_x509_certificate(data) if b"-----BEGIN" in data else x509.load_der_x509_certificate(data)
            roots.append(cert.public_bytes(serialization.Encoding.PEM).decode())
        certificates = "".join(roots)
    validate_material(key, certificates)
    roots = tuple(cert.public_bytes(serialization.Encoding.DER)
                  for cert in x509.load_pem_x509_certificates(certificates.encode())) if certificates else ()
    return key, roots


def configuration_status(cfg):
    missing = []
    for name, label in (("apple_bundle_id", "Bundle ID"), ("apple_issuer_id", "Issuer ID"), ("apple_key_id", "Key ID")):
        if not getattr(cfg, name, "").strip():
            missing.append(label)
    if cfg.apple_environment == "Production" and not cfg.apple_app_id:
        missing.append("Apple App ID")
    try:
        key, roots = material(cfg)
        if not key:
            missing.append("Apple .p8 私钥")
        if not roots:
            missing.append("Apple 根证书")
    except Exception:
        missing.append("私钥或根证书不可解析")
    try:
        import appstoreserverlibrary  # noqa: F401
    except ImportError:
        missing.append("Apple 服务器 SDK")
    return {"configured": not missing, "missing": missing, "environment": cfg.apple_environment,
            "new_purchases_enabled": cfg.apple_iap_enabled, "live_payment_verified": False}
