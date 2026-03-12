"""
Energy data processing — gas and electricity consumption, costs, projections.
All data comes from config.yaml (no external API).
"""
from datetime import date, timedelta

GAS_KWH_PER_M3 = 10.55  # standard calorific value for Austria/Germany


def _to_date(val) -> date:
    if isinstance(val, date):
        return val
    return date.fromisoformat(str(val))


def parse_gas(entries: list) -> list:
    """Returns sorted [{date, reading, disputed}]."""
    return sorted(
        [{"date": _to_date(e["date"]), "reading": e["reading_m3"],
          "disputed": e.get("disputed", False)} for e in entries],
        key=lambda x: x["date"],
    )


def parse_elec(entries: list) -> list:
    """Returns sorted [{date, reading}]."""
    return sorted(
        [{"date": _to_date(e["date"]), "reading": e["reading_kwh"]} for e in entries],
        key=lambda x: x["date"],
    )


def periods(parsed: list) -> list:
    """
    Consumption between consecutive readings.
    Returns [{start, end, days, consumed, per_day, disputed}].
    'disputed' flag is taken from the END reading.
    """
    result = []
    for i in range(1, len(parsed)):
        a, b = parsed[i - 1], parsed[i]
        days = max((b["date"] - a["date"]).days, 1)
        consumed = b["reading"] - a["reading"]
        result.append({
            "start":    a["date"],
            "end":      b["date"],
            "days":     days,
            "consumed": consumed,
            "per_day":  consumed / days,
            "disputed": b.get("disputed", False),
        })
    return result


def latest_rate(parsed: list) -> float:
    """Daily consumption rate from the most recent non-disputed period."""
    for p in reversed(periods(parsed)):
        if not p["disputed"]:
            return p["per_day"]
    # Fall back to most recent period even if disputed
    ps = periods(parsed)
    return ps[-1]["per_day"] if ps else 0.0


def current_period(parsed: list, today: date) -> dict:
    """Estimate consumption from last reading to today."""
    if not parsed:
        return {}
    last = parsed[-1]
    days = (today - last["date"]).days
    rate = latest_rate(parsed)
    return {
        "last_date":    last["date"],
        "last_reading": last["reading"],
        "days_since":   days,
        "rate":         rate,
        "estimated":    rate * days,
    }


def gas_cost(m3: float, days: int, tariff: dict, kwh_per_m3: float = GAS_KWH_PER_M3) -> float:
    """Total EUR cost for m³ of gas over days."""
    return (m3 * kwh_per_m3 * tariff["price_cents_per_kwh"] / 100
            + tariff["base_fee_per_year_eur"] * days / 365)


def elec_cost(kwh: float, days: int, tariff: dict) -> float:
    """Total EUR cost for kWh of electricity over days."""
    return (kwh * tariff["price_cents_per_kwh"] / 100
            + tariff["base_fee_per_year_eur"] * days / 365)


def gas_projection(per_day_m3: float, tariff: dict, kwh_per_m3: float = GAS_KWH_PER_M3) -> float:
    return gas_cost(per_day_m3 * 365, 365, tariff, kwh_per_m3)


def elec_projection(per_day_kwh: float, tariff: dict) -> float:
    return elec_cost(per_day_kwh * 365, 365, tariff)
