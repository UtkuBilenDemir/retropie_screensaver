import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.patches import Rectangle
import numpy as np
import pygame
import yaml

from toggl import TogglClient
from metrics import (
    week_start, hours_by_project, hours_by_project_per_day,
    weekly_stats, historical_weeks, debt_summary,
    daily_target,
)
from rewards import load_state, check_goals, notify, Confetti
from energy import (
    parse_gas, parse_elec, periods, current_period,
    gas_cost, elec_cost, gas_projection, elec_projection,
    GAS_KWH_PER_M3,
)
from career import render_career

# ── Palette ───────────────────────────────────────────────────────────────────
BG     = "#0d1117"
CARD   = "#161b22"
TEXT   = "#e6edf3"
MUTED  = "#8b949e"
GREEN  = "#3fb950"
ORANGE = "#d29922"
RED    = "#f85149"
BLUE   = "#58a6ff"
TRACK  = "#30363d"
BORDER = "#21262d"


def debt_color(debt: float) -> str:
    if debt <= 0:   return GREEN
    if debt < 1.0:  return ORANGE
    return RED


def fmt(h: float) -> str:
    h = abs(h)
    hours = int(h)
    mins  = int(round((h - hours) * 60))
    if mins == 60:
        hours += 1; mins = 0
    if hours == 0: return f"{mins}m"
    if mins  == 0: return f"{hours}h"
    return f"{hours}h {mins}m"


# ── Data ──────────────────────────────────────────────────────────────────────
def load_config(path="/home/pi/Projects/dashboard/config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


import os as _os
import pickle as _pickle

def _cache_path(config: dict) -> str:
    base = _os.path.dirname(_os.path.abspath(__file__))
    return _os.path.join(base, "data_cache.pkl")

def _save_cache(data: dict, config: dict) -> None:
    try:
        with open(_cache_path(config), "wb") as f:
            _pickle.dump(data, f)
    except Exception as e:
        print(f"[cache] save failed: {e}", flush=True)

def _load_cache(config: dict) -> dict | None:
    try:
        with open(_cache_path(config), "rb") as f:
            return _pickle.load(f)
    except Exception:
        return None


def fetch_data(config: dict) -> dict:
    from datetime import timedelta
    token        = config["api"]["token"]
    workspace_id = config["api"]["workspace_id"]
    tz           = ZoneInfo(config["settings"].get("timezone", "Europe/Vienna"))

    client  = TogglClient(token, workspace_id)
    today   = datetime.now(tz).date()
    start   = week_start(today) - timedelta(weeks=4)

    entries  = client.time_entries(start, today)
    projects = client.projects()

    ws = week_start(today)
    week_dates = [ws + timedelta(days=i) for i in range(7)]

    data = {
        "today":             today,
        "weekly":            weekly_stats(entries, tz, today),
        "weekly_by_project": hours_by_project_per_day(entries, tz, week_dates),
        "history":           historical_weeks(entries, tz, today, n_weeks=4),
        "debt":              debt_summary(entries, tz, today),
        "projects":          projects,
        "projects_today":    hours_by_project(entries, today, tz),
        "timer_running":     client.timer_running,
        "fetched_at":        time.time(),
        "energy_cfg":        config.get("energy", {}),
    }
    _save_cache(data, config)
    return data


def fetch_data_with_fallback(config: dict) -> dict:
    """Fetch from API; fall back to cached data, then to empty stub."""
    try:
        return fetch_data(config)
    except Exception as e:
        print(f"[fetch] API error: {e}", flush=True)
        cached = _load_cache(config)
        if cached is not None:
            print("[fetch] using cached data", flush=True)
            cached["api_error"]  = str(e)
            cached["energy_cfg"] = config.get("energy", {})
            return cached
        # No cache — return a minimal stub so the dashboard doesn't crash
        print("[fetch] no cache, using empty stub", flush=True)
        from datetime import date
        from metrics import daily_target
        today = date.today()
        return {
            "today":             today,
            "weekly":            [],
            "weekly_by_project": {},
            "history":           [],
            "debt":              {"today_actual": 0, "today_target": daily_target(today),
                                  "today_debt": daily_target(today), "week_debt": 0},
            "projects":          {},
            "projects_today":    {},
            "timer_running":     False,
            "fetched_at":        time.time(),
            "energy_cfg":        config.get("energy", {}),
            "api_error":         str(e),
        }


# ── Rendering ─────────────────────────────────────────────────────────────────
def _style(ax):
    ax.set_facecolor(CARD)
    for spine in ax.spines.values():
        spine.set_color(BORDER)
    ax.tick_params(colors=MUTED, labelsize=10)


def render(data: dict, W: int, H: int) -> pygame.Surface:
    matplotlib.rcParams.update({
        "font.family":       "DejaVu Sans",
        "text.color":        TEXT,
        "figure.facecolor":  BG,
        "axes.facecolor":    CARD,
        "axes.edgecolor":    BORDER,
    })

    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    gs  = gridspec.GridSpec(
        3, 2, figure=fig,
        left=0.04, right=0.97, top=0.91, bottom=0.06,
        hspace=0.55, wspace=0.10,
        height_ratios=[1.0, 2.5, 1.2],
    )

    debt    = data["debt"]
    weekly  = data["weekly"]
    history = data["history"]
    projs   = data["projects"]
    proj_t  = data["projects_today"]
    today   = data["today"]

    # Header
    fig.text(0.50, 0.97, today.strftime("%A  ·  %d %B %Y"),
             ha="center", color=TEXT, fontsize=18, fontweight="bold")
    streak = data.get("streak", 0)
    streak_str = f"  ·  {streak}d streak" if streak > 1 else ""
    api_err = data.get("api_error")
    fig.text(0.97, 0.97,
             f"{'⚠ cached  ' if api_err else ''}↻ {time.strftime('%H:%M', time.localtime(data['fetched_at']))}{streak_str}",
             ha="right", color=ORANGE if api_err else MUTED, fontsize=10)

    # ── TODAY ─────────────────────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, 0])
    _style(ax1)
    ax1.set_xlim(0, 1); ax1.set_ylim(0, 10); ax1.axis("off")

    actual = debt["today_actual"]
    tgt    = debt["today_target"]
    dv     = debt["today_debt"]
    dc     = debt_color(dv)
    pct    = min(actual / tgt, 1.0) if tgt > 0 else 0
    sign   = "−" if dv > 0 else "+"

    ax1.text(0.02, 9.6, "TODAY",           color=MUTED, fontsize=9,  va="top")
    ax1.text(0.02, 8.0, fmt(actual),       color=TEXT,  fontsize=30, va="top", fontweight="bold")
    ax1.text(0.55, 7.4, f"/ {fmt(tgt)}",  color=MUTED, fontsize=14, va="top")
    ax1.text(0.98, 8.0, f"{sign}{fmt(abs(dv))}",
             color=dc, fontsize=13, va="top", ha="right")

    # Progress bar
    ax1.barh(4.2, 1.0,   height=1.8, color=TRACK, left=0, align="center")
    ax1.barh(4.2, pct,   height=1.8, color=dc,    left=0, align="center")
    bar_label = "DONE" if pct >= 1.0 else f"{pct*100:.0f}%"
    ax1.text(0.5, 4.2, bar_label,
             color=BG if pct > 0.12 else TEXT,
             fontsize=11, ha="center", va="center", fontweight="bold")

    # ── PROJECTS TODAY ────────────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[1, 0])
    _style(ax2)
    ax2.axis("off")

    ax2.text(0.02, 0.97, "PROJECTS TODAY",
             color=MUTED, fontsize=9, va="top", transform=ax2.transAxes)

    sorted_p = sorted(proj_t.items(), key=lambda x: x[1], reverse=True)[:6]
    max_h    = max((h for _, h in sorted_p), default=tgt or 1.0)

    for i, (pid, hours) in enumerate(sorted_p):
        info   = projs.get(pid, {}) if pid else {}
        pname  = info.get("name", "—")[:22]
        pcolor = info.get("color", MUTED)
        y      = 0.86 - i * 0.145

        ax2.text(0.02, y, pname,     color=TEXT,  fontsize=11, va="center", transform=ax2.transAxes)
        ax2.text(0.44, y, fmt(hours), color=MUTED, fontsize=11, va="center",
                 ha="right", transform=ax2.transAxes)

        bar_w = (hours / max(max_h, 0.1)) * 0.52
        ax2.add_patch(Rectangle(
            (0.46, y - 0.05), bar_w, 0.10,
            color=pcolor, transform=ax2.transAxes, clip_on=True,
        ))

    # ── DEBT ──────────────────────────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[2, 0])
    _style(ax3)
    ax3.set_xlim(0, 1); ax3.set_ylim(0, 10); ax3.axis("off")

    ax3.text(0.02, 9.5, "DEBT", color=MUTED, fontsize=9, va="top")

    wv    = debt["week_debt"]
    wsign = "−" if wv > 0 else "+"

    ax3.text(0.02, 5.8, "Today",             color=MUTED, fontsize=11, va="center")
    ax3.text(0.02, 3.2, f"{sign}{fmt(abs(dv))}",
             color=dc, fontsize=22, fontweight="bold", va="center")

    ax3.text(0.52, 5.8, "This Week",         color=MUTED, fontsize=11, va="center")
    ax3.text(0.52, 3.2, f"{wsign}{fmt(abs(wv))}",
             color=debt_color(wv), fontsize=22, fontweight="bold", va="center")

    # ── WEEK CHART ────────────────────────────────────────────────────────────
    ax4 = fig.add_subplot(gs[0:2, 1])
    _style(ax4)

    weekly_by_proj = data["weekly_by_project"]

    days     = [d["day"]    for d in weekly]
    actuals  = [d["actual"] for d in weekly]
    targets_ = [d["target"] for d in weekly]

    # Collect all project IDs that appear this week, sorted by total hours
    proj_week_totals: dict = {}
    for d in weekly:
        for pid, h in weekly_by_proj.get(d["date"], {}).items():
            proj_week_totals[pid] = proj_week_totals.get(pid, 0.0) + h
    sorted_pids = sorted(proj_week_totals, key=lambda p: proj_week_totals[p], reverse=True)

    def _proj_color(pid):
        if pid is None: return MUTED
        return projs.get(pid, {}).get("color", MUTED)

    def _proj_name(pid):
        if pid is None: return "No project"
        return projs.get(pid, {}).get("name", str(pid))[:22]

    # Stacked horizontal bars per day
    for i, d in enumerate(weekly):
        day_projs = weekly_by_proj.get(d["date"], {})
        left = 0.0
        for pid in sorted_pids:
            h = day_projs.get(pid, 0.0)
            if h > 0:
                ax4.barh(i, h, left=left, height=0.6, color=_proj_color(pid))
                left += h

    # Target dash lines
    for i, tgt_h in enumerate(targets_):
        ax4.plot([tgt_h, tgt_h], [i - 0.38, i + 0.38],
                 color=TEXT, linewidth=1.5, linestyle="--", zorder=3)

    max_x = max(max(targets_) * 1.3, max(actuals + [0.1]) * 1.15)

    # Total label after each bar
    for i, act in enumerate(actuals):
        if act > 0:
            ax4.text(act + max_x * 0.02, i, fmt(act), va="center", color=TEXT, fontsize=10)

    # Highlight today's y-tick label
    yticklabels = []
    for d in weekly:
        if d["is_today"]:
            yticklabels.append(f"► {d['day']}")
        else:
            yticklabels.append(d["day"])

    ax4.set_yticks(range(7)); ax4.set_yticklabels(yticklabels, fontsize=12)
    ax4.invert_yaxis()
    ax4.set_xlim(0, max_x)
    ax4.set_xlabel("hours", fontsize=10, color=MUTED)
    ax4.set_title("THIS WEEK", color=MUTED, fontsize=10, loc="left", pad=6)
    ax4.tick_params(axis="y", colors=TEXT)
    ax4.grid(axis="x", color=BORDER, linewidth=0.5)

    # Legend — project colors
    from matplotlib.patches import Patch as _Patch
    legend_handles = [
        _Patch(facecolor=_proj_color(pid), label=_proj_name(pid))
        for pid in sorted_pids
    ]
    if legend_handles:
        ncol = 2 if len(legend_handles) > 4 else 1
        ax4.legend(handles=legend_handles, fontsize=8, facecolor=CARD,
                   labelcolor=TEXT, edgecolor=BORDER,
                   loc="lower right", ncol=ncol)

    # ── PAST 4 WEEKS ──────────────────────────────────────────────────────────
    ax5 = fig.add_subplot(gs[2, 1])
    _style(ax5)

    labels   = [w["label"]  for w in history]
    h_actual = [w["actual"] for w in history]
    h_target = [w["target"] for w in history]
    x        = np.arange(len(labels))
    bw       = 0.35

    ax5.bar(x - bw / 2, h_actual, bw, label="Actual", color=[
        GREEN if a >= t else ORANGE if a >= t * 0.75 else RED
        for a, t in zip(h_actual, h_target)
    ])
    ax5.bar(x + bw / 2, h_target, bw, label="Target", color=TRACK)

    ax5.set_xticks(x); ax5.set_xticklabels(labels, fontsize=9)
    ax5.set_title("PAST 4 WEEKS", color=MUTED, fontsize=10, loc="left", pad=6)
    ax5.tick_params(axis="x", colors=TEXT)
    ax5.grid(axis="y", color=BORDER, linewidth=0.5)
    ax5.legend(fontsize=9, facecolor=CARD, labelcolor=MUTED,
               edgecolor=BORDER, loc="upper left")

    # ── Bake to pygame surface ────────────────────────────────────────────────
    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    surf = pygame.image.frombuffer(canvas.buffer_rgba(), (W, H), "RGBA")
    plt.close(fig)
    return surf


# ── Energy screen ─────────────────────────────────────────────────────────────
def render_energy(data: dict, W: int, H: int) -> pygame.Surface:
    matplotlib.rcParams.update({
        "font.family":       "DejaVu Sans",
        "text.color":        TEXT,
        "figure.facecolor":  BG,
        "axes.facecolor":    CARD,
        "axes.edgecolor":    BORDER,
    })

    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    gs  = gridspec.GridSpec(
        2, 3, figure=fig,
        left=0.04, right=0.97, top=0.91, bottom=0.08,
        hspace=0.45, wspace=0.14,
        height_ratios=[1.0, 1.6],
    )

    today   = data["today"]
    ecfg    = data.get("energy_cfg", {})
    tariffs = ecfg.get("tariffs", {})
    kwh_m3  = ecfg.get("gas_kwh_per_m3", GAS_KWH_PER_M3)

    gas_t  = tariffs.get("gas",         {"price_cents_per_kwh": 7.89,  "base_fee_per_year_eur": 23.86})
    elec_t = tariffs.get("electricity", {"price_cents_per_kwh": 17.89, "base_fee_per_year_eur": 23.73})

    gas_entries  = parse_gas(ecfg.get("readings", {}).get("gas",         {}).get("entries", []))
    elec_entries = parse_elec(ecfg.get("readings", {}).get("electricity", {}).get("entries", []))

    gas_cur  = current_period(gas_entries,  today)
    elec_cur = current_period(elec_entries, today)

    # Header
    fig.text(0.50, 0.97, "ENERGY", ha="center", color=TEXT, fontsize=18, fontweight="bold")
    fig.text(0.97, 0.97,
             f"↻ {time.strftime('%H:%M', time.localtime(data['fetched_at']))}",
             ha="right", color=MUTED, fontsize=10)

    # ── GAS summary ───────────────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, 0])
    _style(ax1)
    ax1.set_xlim(0, 1); ax1.set_ylim(0, 10); ax1.axis("off")
    ax1.text(0.02, 9.6, "GAS", color=MUTED, fontsize=9, va="top")

    if gas_cur:
        est_m3   = gas_cur["estimated"]
        est_cost = gas_cost(est_m3, gas_cur["days_since"], gas_t, kwh_m3)
        proj     = gas_projection(gas_cur["rate"], gas_t, kwh_m3)

        ax1.text(0.02, 8.7,
                 f"Last reading: {gas_cur['last_reading']:,} m\u00b3"
                 f"  ({gas_cur['last_date'].strftime('%-d %b %Y')})",
                 color=TEXT, fontsize=11, va="top")
        ax1.text(0.02, 7.4,
                 f"Est. since:  +{est_m3:.0f} m\u00b3  \u2248 \u20ac{est_cost:.0f}",
                 color=TEXT, fontsize=11, va="top")
        ax1.text(0.02, 6.1,
                 f"Rate: {gas_cur['rate']:.2f} m\u00b3/day"
                 f"  ({gas_cur['rate'] * kwh_m3:.1f} kWh/day)",
                 color=MUTED, fontsize=10, va="top")
        ax1.text(0.02, 4.8, f"\u20ac{proj:.0f} / year",
                 color=BLUE, fontsize=20, va="top", fontweight="bold")
        ax1.text(0.02, 3.2,
                 f"{gas_t['price_cents_per_kwh']} ct/kWh  +  "
                 f"\u20ac{gas_t['base_fee_per_year_eur']:.2f} base/yr",
                 color=MUTED, fontsize=9, va="top")
    else:
        ax1.text(0.02, 6.0, "No readings yet", color=MUTED, fontsize=12, va="top")

    # ── COMBINED total ────────────────────────────────────────────────────────
    ax_mid = fig.add_subplot(gs[0, 1])
    _style(ax_mid)
    ax_mid.set_xlim(0, 1); ax_mid.set_ylim(0, 10); ax_mid.axis("off")
    ax_mid.text(0.5, 9.6, "TOTAL", color=MUTED, fontsize=9, va="top", ha="center")

    proj_gas  = gas_projection(gas_cur["rate"],  gas_t,  kwh_m3) if gas_cur  else 0.0
    proj_elec = elec_projection(elec_cur["rate"], elec_t)         if elec_cur else 0.0
    proj_total = proj_gas + proj_elec
    teilbetrag = proj_total / 10

    ax_mid.text(0.5, 8.0, f"\u20ac{proj_total:.0f}", color=TEXT,  fontsize=32,
                va="top", ha="center", fontweight="bold")
    ax_mid.text(0.5, 5.6, "per year", color=MUTED, fontsize=11, va="top", ha="center")

    ax_mid.add_patch(__import__("matplotlib.patches", fromlist=["FancyBboxPatch"])
                     .FancyBboxPatch((0.1, 2.2), 0.8, 1.8,
                                     boxstyle="round,pad=0.05",
                                     facecolor=CARD, edgecolor=BORDER,
                                     transform=ax_mid.transData))
    ax_mid.text(0.5, 4.0, f"\u20ac{teilbetrag:.0f}",
                color=BLUE, fontsize=22, va="top", ha="center", fontweight="bold")
    ax_mid.text(0.5, 2.5, "per Teilbetrag  \u00d7 10",
                color=MUTED, fontsize=9,  va="top", ha="center")

    # ── ELECTRICITY summary ───────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[0, 2])
    _style(ax2)
    ax2.set_xlim(0, 1); ax2.set_ylim(0, 10); ax2.axis("off")
    ax2.text(0.02, 9.6, "ELECTRICITY", color=MUTED, fontsize=9, va="top")

    if elec_cur:
        est_kwh   = elec_cur["estimated"]
        est_cost2 = elec_cost(est_kwh, elec_cur["days_since"], elec_t)
        proj2     = elec_projection(elec_cur["rate"], elec_t)

        ax2.text(0.02, 8.7,
                 f"Last reading: {elec_cur['last_reading']:,} kWh"
                 f"  ({elec_cur['last_date'].strftime('%-d %b %Y')})",
                 color=TEXT, fontsize=11, va="top")
        ax2.text(0.02, 7.4,
                 f"Est. since:  +{est_kwh:.0f} kWh  \u2248 \u20ac{est_cost2:.0f}",
                 color=TEXT, fontsize=11, va="top")
        ax2.text(0.02, 6.1,
                 f"Rate: {elec_cur['rate']:.2f} kWh/day",
                 color=MUTED, fontsize=10, va="top")
        ax2.text(0.02, 4.8, f"\u20ac{proj2:.0f} / year",
                 color=BLUE, fontsize=20, va="top", fontweight="bold")
        ax2.text(0.02, 3.2,
                 f"{elec_t['price_cents_per_kwh']} ct/kWh  +  "
                 f"\u20ac{elec_t['base_fee_per_year_eur']:.2f} base/yr",
                 color=MUTED, fontsize=9, va="top")
    else:
        ax2.text(0.02, 6.0, "No readings yet", color=MUTED, fontsize=12, va="top")

    # ── Historical gas chart ──────────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[1, 0:3])
    _style(ax3)

    gas_periods = periods(gas_entries)
    if gas_periods:
        labels = [
            f"{p['start'].strftime('%-d %b %y')}\n{p['end'].strftime('%-d %b %y')}"
            for p in gas_periods
        ]
        values = [p["per_day"] for p in gas_periods]
        bar_colors = [ORANGE if p["disputed"] else BLUE for p in gas_periods]

        x = np.arange(len(labels))
        bars = ax3.bar(x, values, color=bar_colors, width=0.55)

        for bar, p in zip(bars, gas_periods):
            label = f"{p['consumed']:.0f} m\u00b3\n({p['days']}d)"
            if p["disputed"]:
                label += "\n\u26a0 disputed"
            ax3.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max(values) * 0.02,
                label, ha="center", va="bottom",
                color=ORANGE if p["disputed"] else TEXT, fontsize=9,
            )

        ax3.set_xticks(x)
        ax3.set_xticklabels(labels, fontsize=9)
        ax3.tick_params(axis="x", colors=TEXT)
        ax3.set_ylabel("m\u00b3 / day", color=MUTED, fontsize=9)
        ax3.set_title("GAS — consumption per period (normalized)",
                      color=MUTED, fontsize=10, loc="left", pad=6)
        ax3.grid(axis="y", color=BORDER, linewidth=0.5)

        from matplotlib.patches import Patch as _Patch
        ax3.legend(
            handles=[_Patch(facecolor=BLUE, label="Measured"),
                     _Patch(facecolor=ORANGE, label="Disputed")],
            fontsize=9, facecolor=CARD, labelcolor=MUTED,
            edgecolor=BORDER, loc="upper right",
        )
    else:
        ax3.text(0.5, 0.5, "Add readings to config.yaml",
                 ha="center", va="center", color=MUTED, fontsize=14,
                 transform=ax3.transAxes)
        ax3.axis("off")

    # Bake to pygame surface
    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    surf = pygame.image.frombuffer(canvas.buffer_rgba(), (W, H), "RGBA")
    plt.close(fig)
    return surf


# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    import os
    config  = load_config()
    dash    = config.get("dashboard", {})
    refresh_active = dash.get("refresh_active_seconds", 60)
    refresh_idle   = dash.get("refresh_idle_seconds", 300)
    exit_btn       = dash.get("exit_button", 9)
    prev_btn       = dash.get("prev_screen_button", 6)
    next_btn       = dash.get("next_screen_button", 7)

    # Rewards config — all off by default if section absent
    rew_cfg    = config.get("rewards", {})
    rew_on     = rew_cfg.get("enabled", False)
    state_path = rew_cfg.get("state_path",
                             os.path.join(os.path.dirname(__file__), "state.json"))
    ntfy_topic = rew_cfg.get("ntfy_topic", "")
    do_confetti = rew_cfg.get("confetti", True)
    do_streak   = rew_cfg.get("streak", True)

    rw_state = load_state(state_path) if rew_on else {}
    reminder_day = config.get("energy", {}).get("reminder_day_of_month", 1)

    def check_meter_reminder(d: dict) -> None:
        """Send a monthly ntfy nudge to read the meters."""
        t = d["today"]
        if not ntfy_topic or t.day != reminder_day:
            return
        month_key = t.strftime("%Y-%m")
        if rw_state.get("last_meter_reminder") == month_key:
            return
        ecfg = d.get("energy_cfg", {})
        gas_entries  = parse_gas(ecfg.get("readings", {}).get("gas",         {}).get("entries", []))
        elec_entries = parse_elec(ecfg.get("readings", {}).get("electricity", {}).get("entries", []))
        parts = []
        if gas_entries:
            last = gas_entries[-1]
            days = (t - last["date"]).days
            parts.append(f"Gas: {last['reading']:,} m\u00b3 ({days}d ago)")
        if elec_entries:
            last = elec_entries[-1]
            days = (t - last["date"]).days
            parts.append(f"Electricity: {last['reading']:,} kWh ({days}d ago)")
        body = "Time to read your meters!\n" + "\n".join(parts)
        notify(ntfy_topic, "Meter reading reminder", body, tags="electric_plug")
        rw_state["last_meter_reminder"] = month_key
        from rewards import save_state
        save_state(state_path, rw_state)

    def apply_rewards(d: dict) -> "Confetti | None":
        """Check goals, update streak in data dict, fire ntfy, return confetti."""
        if not rew_on:
            return None
        events = check_goals(rw_state, state_path, d["today"], d["debt"])
        if do_streak:
            d["streak"] = rw_state.get("streak", 0)
        confetti = None
        if events["daily"]:
            if do_confetti:
                confetti = Confetti(W, H)
            if ntfy_topic:
                notify(ntfy_topic, "Daily goal hit!",
                       f"{fmt(d['debt']['today_actual'])} today"
                       + (f" · {events['streak']}d streak" if events["streak"] > 1 else ""),
                       tags="white_check_mark")
        if events["weekly"] and ntfy_topic:
            notify(ntfy_topic, "Weekly goal complete!",
                   f"Week done" + (f" · {events['streak']}d streak" if events["streak"] > 1 else ""),
                   tags="trophy")
        return confetti

    # Screens registry
    screens = [render, render_energy, render_career]
    screen_idx = 0

    pygame.init()
    pygame.joystick.init()

    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    W, H   = screen.get_size()
    clock  = pygame.time.Clock()

    # Loading screen
    screen.fill((13, 17, 23))
    f   = pygame.font.Font(None, 52)
    txt = f.render("Loading...", True, (230, 237, 243))
    screen.blit(txt, txt.get_rect(center=(W // 2, H // 2)))
    pygame.display.flip()

    data    = fetch_data_with_fallback(config)
    confetti_overlay = apply_rewards(data)
    check_meter_reminder(data)
    surface = screens[screen_idx](data, W, H)

    pending    = [None]
    lock       = threading.Lock()
    stop_event = threading.Event()

    def bg_refresh():
        while not stop_event.is_set():
            with lock:
                timer_running = data.get("timer_running", False)
            interval = refresh_active if timer_running else refresh_idle
            stop_event.wait(interval)
            if stop_event.is_set():
                break
            try:
                d = fetch_data_with_fallback(config)
                s = screens[screen_idx](d, W, H)
                with lock:
                    pending[0] = (d, s)
            except Exception as e:
                print(f"[refresh] {e}")

    threading.Thread(target=bg_refresh, daemon=True).start()

    joysticks = {}

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.JOYDEVICEADDED:
                joy = pygame.joystick.Joystick(event.device_index)
                joysticks[joy.get_instance_id()] = joy

            elif event.type == pygame.JOYDEVICEREMOVED:
                joysticks.pop(event.instance_id, None)

            elif event.type == pygame.JOYBUTTONDOWN:
                print(f"[btn] {event.button}", flush=True)
                if event.button == exit_btn:
                    running = False
                elif event.button == next_btn:
                    screen_idx = (screen_idx + 1) % len(screens)
                    with lock:
                        pending[0] = (data, screens[screen_idx](data, W, H))
                elif event.button == prev_btn:
                    screen_idx = (screen_idx - 1) % len(screens)
                    with lock:
                        pending[0] = (data, screens[screen_idx](data, W, H))

            elif event.type == pygame.KEYDOWN:
                running = False

            elif event.type == pygame.QUIT:
                running = False

        with lock:
            if pending[0]:
                data, surface  = pending[0]
                pending[0]     = None
                new_confetti = apply_rewards(data)
                if new_confetti:
                    confetti_overlay = new_confetti

        screen.blit(surface, (0, 0))

        if confetti_overlay:
            confetti_overlay.update(1 / 30)
            confetti_overlay.draw(screen)
            if confetti_overlay.done:
                confetti_overlay = None

        pygame.display.flip()
        clock.tick(30)

    stop_event.set()
    pygame.quit()


if __name__ == "__main__":
    main()
