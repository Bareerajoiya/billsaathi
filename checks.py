"""checks.py - the RULES part of BillSaathi.

Gemma reads and explains. THIS file does the arithmetic and the rules,
because a model can slip on maths and plain code cannot.
The same bill always gives the same result. No AI is used here.
"""
import re

# ---- Thresholds: change them here, in one place ---------------------------
# WARNING: the 200-unit rule came from a news report (officials' statement).
# Confirm it with FESCO / NEPRA before the demo.
PROTECTED_UNITS_LIMIT = 200
HIGH_USAGE_RATIO = 1.5      # this month >= 1.5x the earlier average -> warn
LOW_USAGE_RATIO = 0.5       # this month <= 0.5x the earlier average -> info
LONG_CYCLE_DAYS = 31        # more than this -> warn
SHORT_CYCLE_DAYS = 27       # less than this -> info
MIN_HISTORY_MONTHS = 3      # need at least this many earlier months

URDU_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def to_number(value):
    """Turn '1,234', 'Rs. 1,234.50', '۱۲۳' or 412 into a number. Bad input -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).translate(URDU_DIGITS).replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    number = float(match.group())
    return int(number) if number.is_integer() else number


def _protected_flag(value):
    """'protected' -> True, 'non-protected' -> False, anything else -> None."""
    if value is None:
        return None
    text = str(value).strip().lower().replace("_", "-")
    if "non" in text or "un" in text or text in ("no", "false"):
        return False
    if "protected" in text or text in ("yes", "true"):
        return True
    return None


def normalize_extraction(raw):
    """Clean whatever the model returned into a predictable shape."""
    raw = raw or {}
    history = []
    for row in raw.get("unit_history") or []:
        if not isinstance(row, dict):
            continue
        units = to_number(row.get("units"))
        if units is not None:
            history.append({"month": str(row.get("month") or "").strip(), "units": units})
    unreadable = raw.get("unreadable") or []
    if isinstance(unreadable, str):
        unreadable = [unreadable]
    return {
        "is_electricity_bill": raw.get("is_electricity_bill") is not False,
        "company": raw.get("company"),
        "billing_month": raw.get("billing_month"),
        "due_date": raw.get("due_date"),
        "tariff_category": raw.get("tariff_category"),
        "protected_status": _protected_flag(raw.get("protected_status")),
        "previous_reading": to_number(raw.get("previous_reading")),
        "present_reading": to_number(raw.get("present_reading")),
        "units_consumed": to_number(raw.get("units_consumed")),
        "billing_days": to_number(raw.get("billing_days")),
        "export_units": to_number(raw.get("export_units")),
        "total_payable": to_number(raw.get("total_payable")),
        "payable_after_due": to_number(raw.get("payable_after_due")),
        "arrears": to_number(raw.get("arrears")),
        "unit_history": history,
        "unreadable": [str(x) for x in unreadable],
    }


def _flag(check_id, severity, title, detail):
    return {"id": check_id, "severity": severity, "title": title, "detail": detail}


def _check_readings(d):
    prev, pres, units = d["previous_reading"], d["present_reading"], d["units_consumed"]
    if None in (prev, pres, units):
        return None
    diff = pres - prev
    if abs(diff - units) <= 1:
        return _flag("readings", "ok", "Readings match units",
                     f"Present {pres} - previous {prev} = {diff}; billed units = {units}.")
    if diff > 0 and units > 0 and units % diff == 0:
        return _flag("readings", "info", "Meter multiplier possible",
                     f"Reading difference is {diff} but billed units are {units} "
                     f"(x{units // diff}). This can be a meter multiplier - confirm with the office.")
    return _flag("readings", "warn", "Readings do not match billed units",
                 f"Present {pres} - previous {prev} = {diff}, but billed units are {units}.")


def _check_days(d):
    days = d["billing_days"]
    if days is None:
        return None
    if days > LONG_CYCLE_DAYS:
        return _flag("billing_days", "warn", "Long billing cycle",
                     f"Cycle is {days} days (limit used here: {LONG_CYCLE_DAYS}). "
                     "Long cycles push units up and can change the tariff slab.")
    if days < SHORT_CYCLE_DAYS:
        return _flag("billing_days", "info", "Short billing cycle",
                     f"Cycle is only {days} days (below {SHORT_CYCLE_DAYS}).")
    return _flag("billing_days", "ok", "Billing cycle looks normal", f"Cycle is {days} days.")


def _earlier_months(d):
    """History rows excluding the current billing month, if it appears there."""
    current = re.sub(r"\W", "", str(d["billing_month"] or "")).upper()
    rows = []
    for row in d["unit_history"]:
        if current and re.sub(r"\W", "", row["month"]).upper() == current:
            continue
        rows.append(row)
    return rows


def _check_history(d):
    units = d["units_consumed"]
    earlier = _earlier_months(d)
    if units is None or len(earlier) < MIN_HISTORY_MONTHS:
        return None
    average = sum(r["units"] for r in earlier) / len(earlier)
    if average <= 0:
        return None
    ratio = units / average
    text = f"This bill: {units} units. Average of {len(earlier)} earlier months: {average:.0f} units ({ratio:.2f}x)."
    if ratio >= HIGH_USAGE_RATIO:
        return _flag("history", "warn", "Units much higher than usual", text)
    if ratio <= LOW_USAGE_RATIO:
        return _flag("history", "info", "Units much lower than usual", text)
    return _flag("history", "ok", "Units in line with earlier months", text)


def _check_protected(d):
    units, status = d["units_consumed"], d["protected_status"]
    if units is None or status is None:
        return None
    earlier = [r["units"] for r in _earlier_months(d)]
    if status is False:
        if units <= PROTECTED_UNITS_LIMIT and all(u <= PROTECTED_UNITS_LIMIT for u in earlier):
            return _flag("protected", "warn", "Protected status worth verifying",
                         f"Bill says NON-protected, but this bill ({units} units) and all "
                         f"{len(earlier)} earlier months are at or below {PROTECTED_UNITS_LIMIT} units.")
        return _flag("protected", "ok", "Protected status looks consistent",
                     "Non-protected, and usage went above the protected limit in at least one month.")
    if units > PROTECTED_UNITS_LIMIT:
        return _flag("protected", "info", "Protected but units above limit",
                     f"Bill says protected, but units are {units} (limit used here: {PROTECTED_UNITS_LIMIT}).")
    return _flag("protected", "ok", "Protected status looks consistent",
                 f"Protected, and {units} units is within {PROTECTED_UNITS_LIMIT}.")


def _check_net_metering(d):
    export = d["export_units"]
    if export and export > 0:
        return _flag("net_metering", "info", "Solar export units present",
                     f"{export} export units appear. Check the export rate used for your credit.")
    return None


def _check_readability(d):
    missing = [name for name in ("units_consumed", "total_payable") if d[name] is None]
    if d["unreadable"] or missing:
        fields = ", ".join(d["unreadable"] + missing)
        return _flag("readability", "info", "Some fields could not be read",
                     f"Not read: {fields}. A clearer photo may help.")
    return None


def run_checks(data):
    """Run every rule on normalized data. Returns flags, warn first."""
    flags = []
    for check in (_check_readings, _check_days, _check_history, _check_protected,
                  _check_net_metering, _check_readability):
        flag = check(data)
        if flag:
            flags.append(flag)
    order = {"warn": 0, "info": 1, "ok": 2}
    return sorted(flags, key=lambda f: order[f["severity"]])