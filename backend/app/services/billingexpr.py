"""TokenFree / New API 计价表达式求值。

任务表达式（含 u()）的结果是美元；token 表达式的系数是美元/百万 tokens。
分组倍率取 1。结算若对上消费日志，以日志 quota 覆盖这里的结果。
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

from app.config import Settings, get_settings
from app.services.tokenfree_usage import usd_cny_rate

logger = logging.getLogger(__name__)

_TOKEN_VARS = ("p", "c", "len", "cr", "cc", "cc1h", "img", "ai", "ao")


def usd_to_charge_fen(usd: float, settings: Settings | None = None) -> int:
    """美元按 New API quota（500000 = 1 USD）折人民币分。"""
    try:
        amount = float(usd)
    except (TypeError, ValueError):
        return 0
    if amount <= 0:
        return 0
    fen = amount * usd_cny_rate(settings) * 100
    snapped = round(fen, 6)
    if snapped <= 0:
        return 0
    return max(1, int(math.ceil(snapped - 1e-9)))


def expression_usd(expr: str, *, tokens: dict[str, float], usage: dict[str, Any]) -> float | None:
    """求值 billing_expr，返回本单美元。语法错误或事实不足时返回 None。"""
    text = (expr or "").split("|||", 1)[0].strip()
    if not text:
        return None
    if _missing_task_fact(text, usage):
        return None
    env = {name: float(tokens.get(name) or 0) for name in _TOKEN_VARS}
    env["__usage__"] = usage
    try:
        value = float(_Parser(text, env).parse())
    except (ValueError, TypeError, ZeroDivisionError) as exc:
        logger.info("billing expr 求值失败: %s", exc)
        return None
    if not math.isfinite(value) or value < 0:
        return None
    if _is_task_expr(text):
        return value
    return value / 1_000_000.0


def quote_verified_charge_fen(
    *,
    model: str,
    prompt: int = 0,
    completion: int = 0,
    total: int = 0,
    usage: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> int | None:
    """按已缓存的 TokenFree 价目报价（分）。没有可核实规则时返回 None。"""
    from app.services.tokenfree_pricing import canonicalize_channel_model_id, lookup_rate

    rate = lookup_rate(model)
    if rate is None:
        mapped = canonicalize_channel_model_id(model)
        if mapped and mapped != (model or "").strip():
            rate = lookup_rate(mapped)
    if rate is None:
        return None
    facts = dict(usage) if isinstance(usage, dict) else {}
    s = settings or get_settings()
    # Seedance 等任务表达式读 u("tokens")；调用方只传 total 时补进 usage
    if (not facts.get("tokens") or float(facts.get("tokens") or 0) <= 0) and int(total or 0) > 0:
        facts["tokens"] = int(total)
    if rate.billing_mode == "tiered_expr" and rate.billing_expr:
        # Resolution tiers are the same size regardless of the caller's casing.
        # Match the spelling used by this rule (image rules often use "2K",
        # while video rules usually use "720p") without changing other facts.
        resolution = str(facts.get("resolution") or "").strip()
        tiers = re.findall(r'''u\(["']resolution["']\)\s*==\s*["']([^"']+)["']''', rate.billing_expr)
        matches = {tier for tier in tiers if tier.casefold() == resolution.casefold()}
        if len(matches) == 1:
            facts["resolution"] = matches.pop()
        usd = expression_usd(
            rate.billing_expr,
            tokens={
                "p": float(prompt or 0),
                "c": float(completion or 0),
                "len": float(prompt or total or 0),
            },
            usage=facts,
        )
        if usd is None or usd <= 0:
            return None
        fen = usd_to_charge_fen(usd, s)
        return fen if fen > 0 else None
    if rate.billing == "per_call" and rate.usd_per_call > 0:
        count = _positive_count(facts.get("image_count") or facts.get("results") or 1)
        fen = usd_to_charge_fen(rate.usd_per_call * count, s)
        return fen if fen > 0 else None
    if rate.billing == "token" and not rate.placeholder and (rate.cny_in_per_1m or rate.cny_out_per_1m):
        prompt_n, completion_n = int(prompt or 0), int(completion or 0)
        if prompt_n + completion_n <= 0 and int(total or 0) > 0:
            prompt_n = int(int(total) * 0.7)
            completion_n = int(total) - prompt_n
        if prompt_n + completion_n <= 0:
            return None
        yuan = (
            prompt_n / 1_000_000 * rate.cny_in_per_1m
            + completion_n / 1_000_000 * rate.cny_out_per_1m
        )
        if yuan <= 0:
            return None
        return max(1, int(math.ceil(round(yuan * 100, 6))))
    return None


def _is_task_expr(expr: str) -> bool:
    """含 u() 的是任务用量表达式，结果已经是美元。"""
    return 'u("' in expr or "u('" in expr


def _missing_task_fact(expr: str, usage: dict[str, Any]) -> bool:
    """秒价 / 字符价缺少对应事实时不要当成 0 美元。"""
    if 'u("seconds")' in expr or "u('seconds')" in expr:
        if float(usage.get("seconds") or 0) <= 0:
            return True
    if 'u("audio_characters")' in expr or "u('audio_characters')" in expr:
        if float(usage.get("audio_characters") or 0) <= 0:
            return True
    return False


def _positive_count(value: Any) -> int:
    try:
        count = int(float(value))
    except (TypeError, ValueError):
        return 1
    return count if count > 0 else 1


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value)
    if isinstance(value, bool):
        return value
    try:
        return float(value) != 0.0
    except (TypeError, ValueError):
        return bool(value)


def _cmp(op: str, left: Any, right: Any) -> bool:
    if op in {"==", "!="}:
        same = left == right
        if not same:
            try:
                same = float(left) == float(right)
            except (TypeError, ValueError):
                same = False
        return same if op == "==" else not same
    try:
        lf, rf = float(left), float(right)
    except (TypeError, ValueError):
        return False
    if op == "<":
        return lf < rf
    if op == "<=":
        return lf <= rf
    if op == ">":
        return lf > rf
    if op == ">=":
        return lf >= rf
    raise ValueError(f"未知比较 {op}")


class _Parser:
    """只支持价目里出现的三元表达式、比较、四则和 u/tier/fixed。"""

    def __init__(self, src: str, env: dict[str, Any]) -> None:
        self.src = src
        self.n = len(src)
        self.i = 0
        self.env = env

    def parse(self) -> Any:
        value = self._ternary()
        self._skip()
        if self.i < self.n:
            raise ValueError(f"表达式未解析完: {self.src[self.i:self.i + 24]}")
        return value

    def _skip(self) -> None:
        while self.i < self.n and self.src[self.i] in " \t\r\n":
            self.i += 1

    def _starts(self, token: str) -> bool:
        self._skip()
        return self.src.startswith(token, self.i)

    def _eat(self, token: str) -> bool:
        if self._starts(token):
            self.i += len(token)
            return True
        return False

    def _ternary(self) -> Any:
        cond = self._or()
        if self._eat("?"):
            yes = self._ternary()
            if not self._eat(":"):
                raise ValueError("三元表达式缺少 :")
            no = self._ternary()
            return yes if _truthy(cond) else no
        return cond

    def _or(self) -> Any:
        value = self._and()
        while self._eat("||"):
            right = self._and()
            value = _truthy(value) or _truthy(right)
        return value

    def _and(self) -> Any:
        value = self._cmp_expr()
        while self._eat("&&"):
            right = self._cmp_expr()
            value = _truthy(value) and _truthy(right)
        return value

    def _cmp_expr(self) -> Any:
        value = self._add()
        for op in ("==", "!=", "<=", ">=", "<", ">"):
            if self._eat(op):
                return _cmp(op, value, self._add())
        return value

    def _add(self) -> Any:
        value = self._mul()
        if not (self._starts("+") or self._starts("-")):
            return value
        value = float(value)
        while True:
            if self._eat("+"):
                value += float(self._mul())
            elif self._eat("-"):
                value -= float(self._mul())
            else:
                return value

    def _mul(self) -> Any:
        value = self._unary()
        if not (self._starts("*") or self._starts("/")):
            return value
        value = float(value)
        while True:
            if self._eat("*"):
                value *= float(self._unary())
            elif self._eat("/"):
                denom = float(self._unary())
                if denom == 0:
                    raise ZeroDivisionError("除数为 0")
                value /= denom
            else:
                return value

    def _unary(self) -> Any:
        if self._eat("-"):
            return -float(self._primary())
        return self._primary()

    def _primary(self) -> Any:
        self._skip()
        if self.i >= self.n:
            raise ValueError("表达式意外结束")
        ch = self.src[self.i]
        if ch == "(":
            self.i += 1
            value = self._ternary()
            if not self._eat(")"):
                raise ValueError("缺少 )")
            return value
        if ch == '"':
            return self._string()
        if ch.isdigit() or ch == ".":
            return self._number()
        name = self._ident()
        if self._eat("("):
            args: list[Any] = []
            if not self._eat(")"):
                while True:
                    args.append(self._ternary())
                    if self._eat(")"):
                        break
                    if not self._eat(","):
                        raise ValueError("函数参数缺少 ,")
            return self._call(name, args)
        if name in self.env and name != "__usage__":
            return self.env[name]
        raise ValueError(f"未知标识 {name}")

    def _string(self) -> str:
        self.i += 1
        chars: list[str] = []
        while self.i < self.n:
            ch = self.src[self.i]
            self.i += 1
            if ch == '"':
                return "".join(chars)
            if ch == "\\" and self.i < self.n:
                chars.append(self.src[self.i])
                self.i += 1
                continue
            chars.append(ch)
        raise ValueError("字符串未闭合")

    def _number(self) -> float:
        start = self.i
        while self.i < self.n and (self.src[self.i].isdigit() or self.src[self.i] == "."):
            self.i += 1
        try:
            return float(self.src[start:self.i])
        except ValueError as exc:
            raise ValueError(f"非法数字 {self.src[start:self.i]}") from exc

    def _ident(self) -> str:
        self._skip()
        start = self.i
        while self.i < self.n and (self.src[self.i].isalnum() or self.src[self.i] == "_"):
            self.i += 1
        if start == self.i:
            raise ValueError(f"无法解析 {self.src[self.i:self.i + 12]!r}")
        return self.src[start:self.i]

    def _call(self, name: str, args: list[Any]) -> Any:
        if name == "u":
            if len(args) != 1:
                raise ValueError("u() 需要一个参数")
            usage = self.env.get("__usage__")
            if not isinstance(usage, dict):
                return 0
            value = usage.get(str(args[0]), 0)
            return 0 if value is None else value
        if name == "tier":
            if len(args) != 2:
                raise ValueError("tier() 需要两个参数")
            return args[1]
        if name == "fixed":
            if len(args) != 1:
                raise ValueError("fixed() 需要一个参数")
            return float(args[0]) * 1_000_000.0
        if name in {"max", "min"} and len(args) == 2:
            nums = (float(args[0]), float(args[1]))
            return max(nums) if name == "max" else min(nums)
        raise ValueError(f"不支持的函数 {name}")
