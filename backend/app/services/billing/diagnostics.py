"""Bounded payment diagnostics: never log exception text, receipt bodies or credentials."""
import re

def failure_fields(exc):
    detail = getattr(exc, "detail", None)
    code = detail.get("code") if isinstance(detail, dict) else getattr(exc, "code", None)
    if not isinstance(code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,99}", code):
        code = "UNCLASSIFIED"
    status = getattr(exc, "status_code", getattr(exc, "status", None))
    if not isinstance(status, int) or isinstance(status, bool) or not 100 <= status <= 599:
        status = "-"
    return type(exc).__name__, status, code
