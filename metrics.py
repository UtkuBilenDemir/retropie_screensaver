from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

WEEKDAY_HOURS = 5.0
WEEKEND_HOURS = 2.0


def daily_target(d: date) -> float:
    return WEEKDAY_HOURS if d.weekday() < 5 else WEEKEND_HOURS


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _parse_date(iso_str: str, tz: ZoneInfo) -> date:
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return dt.astimezone(tz).date()


def hours_by_date(entries: list, tz: ZoneInfo) -> dict:
    """Returns {date: total_hours} across all entries."""
    totals: dict[date, float] = defaultdict(float)
    for e in entries:
        d = _parse_date(e["start"], tz)
        totals[d] += e["_hours"]
    return dict(totals)


def hours_by_project(entries: list, d: date, tz: ZoneInfo) -> dict:
    """Returns {project_id: hours} for a specific date."""
    totals: dict = defaultdict(float)
    for e in entries:
        if _parse_date(e["start"], tz) == d:
            totals[e.get("project_id")] += e["_hours"]
    return dict(totals)


def weekly_stats(entries: list, tz: ZoneInfo, today: date) -> list:
    """Per-day breakdown for the current Mon–Sun week."""
    ws = week_start(today)
    by_date = hours_by_date(entries, tz)
    result = []
    for i in range(7):
        d = ws + timedelta(days=i)
        result.append({
            "date":      d,
            "day":       d.strftime("%a"),
            "actual":    0.0 if d > today else by_date.get(d, 0.0),
            "target":    daily_target(d),
            "is_today":  d == today,
            "is_future": d > today,
        })
    return result


def historical_weeks(entries: list, tz: ZoneInfo, today: date, n_weeks: int = 4) -> list:
    """Stats for the last n_weeks completed weeks + current week (pro-rated)."""
    ws = week_start(today)
    by_date = hours_by_date(entries, tz)
    weeks = []

    for i in range(n_weeks, 0, -1):
        wk_s = ws - timedelta(weeks=i)
        actual = sum(by_date.get(wk_s + timedelta(days=j), 0.0) for j in range(7))
        target = sum(daily_target(wk_s + timedelta(days=j)) for j in range(7))
        weeks.append({
            "label":  wk_s.strftime("%-d %b"),
            "actual": actual,
            "target": target,
        })

    # Current week up to today (fair comparison)
    days_so_far = today.weekday() + 1
    cur_actual = sum(by_date.get(ws + timedelta(days=j), 0.0) for j in range(days_so_far))
    cur_target = sum(daily_target(ws + timedelta(days=j)) for j in range(days_so_far))
    weeks.append({"label": "This\nWeek", "actual": cur_actual, "target": cur_target})

    return weeks


def debt_summary(entries: list, tz: ZoneInfo, today: date) -> dict:
    """Debt = target − actual. Positive = behind, negative = ahead."""
    by_date = hours_by_date(entries, tz)
    ws = week_start(today)

    today_actual = by_date.get(today, 0.0)
    today_target = daily_target(today)

    days_so_far = today.weekday() + 1
    week_debt = sum(
        daily_target(ws + timedelta(days=i)) - by_date.get(ws + timedelta(days=i), 0.0)
        for i in range(days_so_far)
    )

    return {
        "today_actual": today_actual,
        "today_target": today_target,
        "today_debt":   today_target - today_actual,
        "week_debt":    week_debt,
    }
