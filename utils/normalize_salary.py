# -*- coding: utf-8 -*-
# @Time    : 2025/11/15 16:20:49
# @Author  : 墨烟行(GitHub UserName: CloudSwordSage)
# @File    : normalize_salary.py
# @License : Apache-2.0
# @Desc    : 标准化薪资范围

import re
from typing import Optional, Tuple

UNIT_MULTIPLIER = {"元": 1, "百": 100, "千": 1000, "k": 1000, "w": 10000, "万": 10000}


def _detect_period(s: str) -> Optional[str]:
    s = s.lower()
    if re.search(r"(年薪|/年|每年|年)", s):
        return "year"
    if re.search(r"(月薪|/月|每月|月)", s):
        return "month"
    if re.search(r"(每周|/周|周|星期)", s):
        return "week"
    if re.search(r"(每小时|/小时|小时|/时|时)", s):
        return "hour"
    return "day" if re.search(r"(每天|/天|/日|天|日)", s) else None


def _format_k(x: float) -> str:
    v = round(x, 1)
    return f"{int(v)}K" if abs(v - int(v)) < 0.05 else f"{v}K"


def _parse_raw(segment: str) -> Tuple[Optional[float], Optional[str], Optional[str]]:
    seg = segment.strip().lower().replace("￥", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*([kw万千百元]?)", seg)
    if not m:
        return None, None, None
    num = float(m.group(1))
    unit = (m.group(2) or "").lower()
    unit = {"k": "k", "w": "w"}.get(unit, unit)
    period = _detect_period(seg)
    return num, unit or None, period


def _to_monthly_k(
    amount_yuan: float,
    period: Optional[str],
    work_days_per_month: int,
    hours_per_day: int,
    weeks_per_month: float,
) -> float:
    p = period or "month"
    if p == "day":
        monthly_yuan = amount_yuan * work_days_per_month
    elif p == "hour":
        monthly_yuan = amount_yuan * hours_per_day * work_days_per_month
    elif p == "week":
        monthly_yuan = amount_yuan * weeks_per_month
    elif p == "year":
        monthly_yuan = amount_yuan / 12.0
    else:
        monthly_yuan = amount_yuan
    return monthly_yuan / 1000.0


def _detect_bound_type(text: str) -> Optional[str]:
    t = text.lower()
    has_upper = (
        re.search(r"(以下|以内|不超过|至多|最多|<=|≤|小于|低于|上限)", t) is not None
    )
    has_lower = re.search(r"(以上|不低于|至少|>=|≥|大于|高于|下限|起)", t) is not None
    if has_upper and not has_lower:
        return "upper"
    return "lower" if has_lower and not has_upper else None


def normalize_salary(
    s: str,
    work_days_per_month: int = 30,
    hours_per_day: int = 8,
    weeks_per_month: float = 4.33,
) -> str:
    if not s or not isinstance(s, str):
        return ""
    text = re.sub(r"[~～–—至到]", "-", s.strip())
    explicit_period = _detect_period(text)
    bound = _detect_bound_type(text)

    parts = text.split("-")
    if len(parts) >= 2 and not bound:
        left, right = parts[0], parts[1]
        ln, lu, lp = _parse_raw(left)
        rn, ru, rp = _parse_raw(right)
        if ln is None and rn is None:
            return ""
        shared_period = explicit_period or lp or rp

        def lower_unit(u: str) -> str:
            if u in {"w", "万"}:
                return "k"
            return "元" if u in {"k", "千"} else "元"

        if lu is None and ru is not None and ln is not None and rn is not None:
            if ru in ("w", "万"):
                lu = "w" if ln <= rn else lower_unit("w")
            elif ru in ("k", "千"):
                lu = "k" if ln <= rn else lower_unit("k")
            else:
                lu = ru
        if ru is None and lu is not None and ln is not None and rn is not None:
            if lu in ("w", "万"):
                ru = "w" if rn <= ln else lower_unit("w")
            elif lu in ("k", "千"):
                ru = "k" if rn <= ln else lower_unit("k")
            else:
                ru = lu

        def conv(
            num: Optional[float], unit: Optional[str], period: Optional[str]
        ) -> Optional[float]:
            if num is None:
                return None
            if unit:
                p = explicit_period or period or shared_period
                return _to_monthly_k(
                    num * UNIT_MULTIPLIER.get(unit, 1),
                    p,
                    work_days_per_month,
                    hours_per_day,
                    weeks_per_month,
                )
            if num < 10:
                return _to_monthly_k(
                    num * UNIT_MULTIPLIER["k"],
                    explicit_period or period or "month",
                    work_days_per_month,
                    hours_per_day,
                    weeks_per_month,
                )
            if 10 <= num <= 100:
                return _to_monthly_k(
                    num * UNIT_MULTIPLIER["元"],
                    explicit_period or period or "hour",
                    work_days_per_month,
                    hours_per_day,
                    weeks_per_month,
                )
            return _to_monthly_k(
                num * UNIT_MULTIPLIER["元"],
                explicit_period or period or "day",
                work_days_per_month,
                hours_per_day,
                weeks_per_month,
            )

        k1 = conv(ln, lu, lp)
        k2 = conv(rn, ru, rp)
        if k1 is None and k2 is not None:
            k1 = k2
        if k2 is None and k1 is not None:
            k2 = k1
        if k1 is None or k2 is None:
            return ""
        low, high = (k1, k2) if k1 <= k2 else (k2, k1)
        return f"{_format_k(low)}-{_format_k(high)}/月"

    a, u, p = _parse_raw(text)
    if a is None:
        return ""

    def conv_single(num: float, unit: Optional[str], period: Optional[str]) -> float:
        if unit:
            return _to_monthly_k(
                num * UNIT_MULTIPLIER.get(unit, 1),
                explicit_period or period,
                work_days_per_month,
                hours_per_day,
                weeks_per_month,
            )
        if num < 10:
            return _to_monthly_k(
                num * UNIT_MULTIPLIER["k"],
                explicit_period or period or "month",
                work_days_per_month,
                hours_per_day,
                weeks_per_month,
            )
        if 10 <= num <= 100:
            return _to_monthly_k(
                num * UNIT_MULTIPLIER["元"],
                explicit_period or period or "hour",
                work_days_per_month,
                hours_per_day,
                weeks_per_month,
            )
        return _to_monthly_k(
            num * UNIT_MULTIPLIER["元"],
            explicit_period or period or "day",
            work_days_per_month,
            hours_per_day,
            weeks_per_month,
        )

    k = conv_single(a, u, p)
    if bound == "upper":
        return f"0K-{_format_k(k)}/月"
    return f"{_format_k(k)}-{_format_k(k)}/月"
