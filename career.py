"""
Career Pursuit screen — job and PhD application tracker.

Parses the Obsidian note directly (no Obsidian CLI dependency on the Pi).
Tasks tagged #todo/apply are split into JOB and PhD sections.

Status icons:
    [ ]  → TODO    (grey)
    [/]  → APPLIED (blue)
    [-]  → REJECTED (red)
    [x]  → ACCEPTED (green)
"""
import re
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.patches import FancyBboxPatch
import pygame

# ── Palette (shared with dashboard.py) ────────────────────────────────────────
BG     = "#0d1117"
CARD   = "#161b22"
TEXT   = "#e6edf3"
MUTED  = "#8b949e"
GREEN  = "#3fb950"
ORANGE = "#d29922"
RED    = "#f85149"
BLUE   = "#58a6ff"
BORDER = "#21262d"
TRACK  = "#30363d"

VAULT_ROOT = Path("/home/pi/Library/Mobile Documents/iCloud~md~obsidian/Documents/rhizome")
NOTE_PATH  = VAULT_ROOT / "02_zettelkasten" / "Career Pursuit.md"

# Fallback for local dev on macOS
_MAC_ROOT  = Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents/rhizome"
if not VAULT_ROOT.exists() and _MAC_ROOT.exists():
    NOTE_PATH = _MAC_ROOT / "02_zettelkasten" / "Career Pursuit.md"


# ── Status config ──────────────────────────────────────────────────────────────
STATUS_META = {
    " ": {"label": "TODO",     "color": MUTED,   "dot": "○"},
    "/": {"label": "APPLIED",  "color": BLUE,    "dot": "◑"},
    "-": {"label": "REJECTED", "color": RED,     "dot": "✕"},
    "x": {"label": "ACCEPTED", "color": GREEN,   "dot": "✓"},
}


# ── Parsing ────────────────────────────────────────────────────────────────────
_TASK_RE   = re.compile(r"^\s*-\s+\[([/ x\-])\].*?#todo/apply\s*(.*)")
_LINK_RE   = re.compile(r"\[([^\]]+)\]\([^)]+\)")   # [text](url) → text
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")  # [[note|alias]]
_TAG_RE    = re.compile(r"#\S+")
_EMOJI_RE  = re.compile(
    "[\U00002600-\U000027BF"
    "\U0001F300-\U0001F9FF"
    "\U00002702-\U000027B0"
    "\U0000FE0F"
    "\U00002000-\U00002BFF"
    "⏫⬆️🔺📅🛫✅❌]+",
    re.UNICODE,
)
# Obsidian Tasks date fields: 📅 2026-03-30 / ✅ 2026-01-01 etc
_DATE_FIELD_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _clean_label(raw: str) -> str:
    """Strip markdown links, tags, task-management emoji, extra whitespace."""
    s = raw.strip()
    # Replace markdown links with their display text
    s = _LINK_RE.sub(r"\1", s)
    # Replace wikilinks with their display name
    s = _WIKILINK_RE.sub(r"\1", s)
    # Remove tags
    s = _TAG_RE.sub("", s)
    # Remove common task-management emoji and Obsidian symbols
    s = _EMOJI_RE.sub("", s)
    # Remove bare dates left after emoji stripping (e.g. "2026-01-01")
    s = _DATE_FIELD_RE.sub("", s)
    # Remove escaped pipe and escaped underscore (markdown escaping in link text)
    s = s.replace(r"\|", "|").replace(r"\_", "_")
    # Strip leading markdown heading marker if link text starts with "# "
    s = re.sub(r"^#+\s+", "", s)
    # Collapse whitespace
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s or "(untitled)"


def parse_career_note(path: Path = NOTE_PATH) -> dict:
    """
    Returns {"job": [...], "phd": [...]} where each item is:
        {"status": " "/"/"/"-"/"x", "label": str}
    Only lines tagged #todo/apply are included.
    Callout blocks (> ...) inside the PhD section are also parsed.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"job": [], "phd": [], "error": f"Note not found: {path}"}

    job_items: list = []
    phd_items: list = []

    section = None   # "job" | "phd" | None

    for raw_line in text.splitlines():
        # Strip blockquote prefix (callout lines start with "> ")
        line = re.sub(r"^(\s*>\s*)+", "", raw_line)

        # Detect section headings (## JOB / ## PhD)
        heading = line.strip().lstrip("#").strip().lower()
        if re.match(r"^job\b", heading) and line.startswith("#"):
            section = "job"
            continue
        if re.match(r"^phd\b", heading) and line.startswith("#"):
            section = "phd"
            continue
        # ### sub-headings stay in same section
        if re.match(r"^#{1,6}\s", line) and section not in ("job", "phd"):
            section = None
            continue

        if section is None:
            continue

        m = _TASK_RE.match(line)
        if not m:
            continue

        status_char = m.group(1)
        rest        = m.group(2)
        label       = _clean_label(rest)

        item = {"status": status_char, "label": label}
        if section == "job":
            job_items.append(item)
        else:
            phd_items.append(item)

    return {"job": job_items, "phd": phd_items}


# ── Rendering helper ───────────────────────────────────────────────────────────
def _draw_section(ax, items: list, title: str, start_y: float, row_h: float,
                  max_rows: int) -> float:
    """
    Draw a labelled section of application items onto ax (axes-fraction coords).
    Returns the y position after the last drawn row.
    """
    ax.text(0.01, start_y, title, color=MUTED, fontsize=9,
            va="top", transform=ax.transAxes, fontweight="bold")
    y = start_y - 0.06

    status_order = ["/", " ", "-", "x"]   # applied first, then todo, rejected, accepted
    ordered = sorted(items, key=lambda i: status_order.index(i["status"])
                     if i["status"] in status_order else 99)

    for idx, item in enumerate(ordered[:max_rows]):
        meta   = STATUS_META.get(item["status"], STATUS_META[" "])
        dot    = meta["dot"]
        color  = meta["color"]
        label  = item["label"]

        # Truncate label to fit
        if len(label) > 52:
            label = label[:51] + "…"

        ax.text(0.01, y, dot,   color=color, fontsize=11,
                va="top", transform=ax.transAxes, family="DejaVu Sans")
        ax.text(0.06, y, label, color=TEXT,  fontsize=10,
                va="top", transform=ax.transAxes)
        y -= row_h

    if len(items) > max_rows:
        remaining = len(items) - max_rows
        ax.text(0.06, y, f"+ {remaining} more…", color=MUTED, fontsize=9,
                va="top", transform=ax.transAxes, style="italic")
        y -= row_h

    return y


def _status_counts(items: list) -> dict:
    counts = {k: 0 for k in STATUS_META}
    for item in items:
        if item["status"] in counts:
            counts[item["status"]] += 1
    return counts


def _draw_legend(ax, items: list, x: float, y: float):
    """Draw a mini legend row: ○ todo  ◑ applied  ✕ rejected  ✓ accepted."""
    counts = _status_counts(items)
    parts = [
        ("/", "applied"),
        (" ", "todo"),
        ("-", "rejected"),
        ("x", "accepted"),
    ]
    cur_x = x
    for status, name in parts:
        n = counts.get(status, 0)
        meta = STATUS_META[status]
        label = f"{meta['dot']} {n} {name}  "
        ax.text(cur_x, y, label, color=meta["color"], fontsize=8,
                va="top", transform=ax.transAxes)
        cur_x += 0.22  # rough spacing; matplotlib won't overflow axes


# ── Main render function ───────────────────────────────────────────────────────
def render_career(data: dict, W: int, H: int) -> pygame.Surface:
    """
    Render the Career Pursuit screen.
    `data` is the shared data dict from fetch_data; this screen doesn't need it
    but receives it for API consistency.
    """
    matplotlib.rcParams.update({
        "font.family":      "DejaVu Sans",
        "text.color":       TEXT,
        "figure.facecolor": BG,
        "axes.facecolor":   CARD,
        "axes.edgecolor":   BORDER,
    })

    career = parse_career_note()
    job_items = career.get("job", [])
    phd_items = career.get("phd", [])
    error     = career.get("error")

    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)

    # ── Header ────────────────────────────────────────────────────────────────
    fig.text(0.50, 0.97, "CAREER PURSUIT",
             ha="center", color=TEXT, fontsize=18, fontweight="bold")
    fig.text(0.97, 0.97,
             f"↻ {time.strftime('%H:%M')}",
             ha="right", color=MUTED, fontsize=10)

    if error:
        ax = fig.add_axes([0.05, 0.1, 0.9, 0.8])
        ax.axis("off")
        ax.set_facecolor(BG)
        ax.text(0.5, 0.5, error, ha="center", va="center",
                color=RED, fontsize=14, transform=ax.transAxes)
        canvas = FigureCanvasAgg(fig)
        canvas.draw()
        surf = pygame.image.frombuffer(canvas.buffer_rgba(), (W, H), "RGBA")
        plt.close(fig)
        return surf

    # ── Two-column layout ──────────────────────────────────────────────────────
    gs = gridspec.GridSpec(
        1, 2, figure=fig,
        left=0.03, right=0.98, top=0.88, bottom=0.04,
        hspace=0.0, wspace=0.06,
    )

    ax_job = fig.add_subplot(gs[0, 0])
    ax_phd = fig.add_subplot(gs[0, 1])

    for ax in (ax_job, ax_phd):
        ax.set_facecolor(CARD)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        for spine in ax.spines.values():
            spine.set_color(BORDER)

    ROW_H   = 0.068   # fraction of axes height per row
    MAX_JOB = 11
    MAX_PHD = 11

    # ── JOB column ────────────────────────────────────────────────────────────
    job_counts = _status_counts(job_items)
    job_subtitle = (
        f"{job_counts.get('/', 0)} applied  ·  "
        f"{job_counts.get(' ', 0)} todo  ·  "
        f"{job_counts.get('-', 0)} rejected  ·  "
        f"{job_counts.get('x', 0)} accepted"
    )
    ax_job.text(0.01, 0.97, "JOB",
                color=TEXT, fontsize=14, fontweight="bold",
                va="top", transform=ax_job.transAxes)
    ax_job.text(0.01, 0.91, job_subtitle,
                color=MUTED, fontsize=8,
                va="top", transform=ax_job.transAxes)

    _draw_section(ax_job, job_items, "", 0.83, ROW_H, MAX_JOB)

    # ── PhD column ────────────────────────────────────────────────────────────
    phd_counts = _status_counts(phd_items)
    phd_subtitle = (
        f"{phd_counts.get('/', 0)} applied  ·  "
        f"{phd_counts.get(' ', 0)} todo  ·  "
        f"{phd_counts.get('-', 0)} rejected  ·  "
        f"{phd_counts.get('x', 0)} accepted"
    )
    ax_phd.text(0.01, 0.97, "PhD",
                color=TEXT, fontsize=14, fontweight="bold",
                va="top", transform=ax_phd.transAxes)
    ax_phd.text(0.01, 0.91, phd_subtitle,
                color=MUTED, fontsize=8,
                va="top", transform=ax_phd.transAxes)

    _draw_section(ax_phd, phd_items, "", 0.83, ROW_H, MAX_PHD)

    # ── Bake to pygame surface ─────────────────────────────────────────────────
    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    surf = pygame.image.frombuffer(canvas.buffer_rgba(), (W, H), "RGBA")
    plt.close(fig)
    return surf
