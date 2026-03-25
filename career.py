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

NOTE_PATH = Path("/home/pi/Projects/rhizome/02_zettelkasten/Career Pursuit.md")

# Fallback for local dev on macOS
_MAC_NOTE = Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents/rhizome" / "02_zettelkasten" / "Career Pursuit.md"
if not NOTE_PATH.exists() and _MAC_NOTE.exists():
    NOTE_PATH = _MAC_NOTE


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
    from sankeyflow import Sankey as _Sankey

    matplotlib.rcParams.update({
        "font.family":      "DejaVu Sans",
        "text.color":       TEXT,
        "figure.facecolor": BG,
        "axes.facecolor":   BG,
        "axes.edgecolor":   BORDER,
    })

    career    = parse_career_note()
    job_items = career.get("job", [])
    phd_items = career.get("phd", [])
    error     = career.get("error")

    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(BG)

    fig.text(0.50, 0.97, "CAREER PURSUIT",
             ha="center", color=TEXT, fontsize=18, fontweight="bold")
    fig.text(0.97, 0.97, f"↻ {time.strftime('%H:%M')}",
             ha="right", color=MUTED, fontsize=10)

    if error:
        ax = fig.add_axes([0.05, 0.1, 0.9, 0.8])
        ax.axis("off"); ax.set_facecolor(BG)
        ax.text(0.5, 0.5, error, ha="center", va="center",
                color=RED, fontsize=14, transform=ax.transAxes)
        canvas = FigureCanvasAgg(fig)
        canvas.draw()
        surf = pygame.image.frombuffer(canvas.buffer_rgba(), (W, H), "RGBA")
        plt.close(fig)
        return surf

    # ── Count by status ────────────────────────────────────────────────────────
    def _counts(items):
        c = {" ": 0, "/": 0, "-": 0, "x": 0}
        for item in items:
            if item["status"] in c:
                c[item["status"]] += 1
        return c

    jc = _counts(job_items)
    pc = _counts(phd_items)

    job_total = sum(jc.values())
    phd_total = sum(pc.values())

    C_JOB  = ORANGE    # #d29922
    C_PHD  = "#a371f7" # purple
    C_APPL = BLUE      # #58a6ff  applied/sent
    C_TODO = MUTED     # #8b949e  not yet sent
    C_IDLE = "#6e7681" # darker muted — pending response
    C_REJ  = RED       # #f85149  rejected
    C_ACC  = GREEN     # #3fb950  accepted

    # ── Derived counts ─────────────────────────────────────────────────────────
    # "Applied" (level 1) = everything that has been sent: "/" + "-" + "x"
    j_sent = jc["/"] + jc["-"] + jc["x"]
    p_sent = pc["/"] + pc["-"] + pc["x"]
    total_sent     = j_sent + p_sent
    total_idle     = jc["/"] + pc["/"]   # sent but still waiting
    total_rejected = jc["-"] + pc["-"]
    total_accepted = jc["x"] + pc["x"]
    total_todo     = jc[" "] + pc[" "]

    # ── Build Sankey nodes & flows ─────────────────────────────────────────────
    level0 = []
    if job_total > 0:
        level0.append(("Job", job_total,
                        {"color": C_JOB, "label_pos": "left",
                         "label_format": "Job\n{value:.0f} total"}))
    if phd_total > 0:
        level0.append(("PhD", phd_total,
                        {"color": C_PHD, "label_pos": "left",
                         "label_format": "PhD\n{value:.0f} total"}))

    level1 = []
    if total_sent > 0:
        level1.append(("Applied", total_sent,
                        {"color": C_APPL,
                         "label_format": "Applied\n{value:.0f}"}))
    if total_todo > 0:
        level1.append(("TODO", total_todo,
                        {"color": C_TODO,
                         "label_format": "TODO\n{value:.0f}"}))

    level2 = []
    if total_idle > 0:
        level2.append(("Idle", total_idle,
                        {"color": C_IDLE, "label_pos": "right",
                         "label_format": "Idle\n{value:.0f}"}))
    if total_rejected > 0:
        level2.append(("Rejected", total_rejected,
                        {"color": C_REJ, "label_pos": "right",
                         "label_format": "Rejected\n{value:.0f}"}))
    if total_accepted > 0:
        level2.append(("Accepted", total_accepted,
                        {"color": C_ACC, "label_pos": "right",
                         "label_format": "Accepted\n{value:.0f}"}))

    flows = []
    # Job / PhD → Applied (sent) and TODO
    if j_sent > 0:
        flows.append(("Job", "Applied", j_sent))
    if p_sent > 0:
        flows.append(("PhD", "Applied", p_sent))
    if jc[" "] > 0:
        flows.append(("Job", "TODO", jc[" "]))
    if pc[" "] > 0:
        flows.append(("PhD", "TODO", pc[" "]))
    # Applied → Idle / Rejected / Accepted
    if total_idle > 0:
        flows.append(("Applied", "Idle", total_idle))
    if total_rejected > 0:
        flows.append(("Applied", "Rejected", total_rejected))
    if total_accepted > 0:
        flows.append(("Applied", "Accepted", total_accepted))

    nodes = [level0, level1]
    if level2:
        nodes.append(level2)

    # ── Sankey (left 58%) ─────────────────────────────────────────────────────
    ax_s = fig.add_axes([0.02, 0.06, 0.56, 0.84])
    ax_s.set_facecolor(BG)
    ax_s.axis("off")

    _Sankey(
        flows=flows,
        nodes=nodes,
        flow_color_mode="dest",
        flow_color_mode_alpha=0.38,
        node_width=0.04,
        node_pad_y_min=0.05,
        node_pad_y_max=0.14,
        align_y="justify",
        node_opts={"fontsize": 13, "color": TEXT},
        flow_opts={"curvature": 0.45},
    ).draw(ax=ax_s)

    # ── Application list panel (right 40%) ────────────────────────────────────
    ax_l = fig.add_axes([0.60, 0.06, 0.38, 0.84])
    ax_l.set_facecolor(CARD)
    ax_l.set_xlim(0, 1); ax_l.set_ylim(0, 1)
    ax_l.axis("off")

    # Show Applied first, then Accepted, then TODO — skip Rejected (noise)
    show_order   = ["/", "x", " "]
    section_sep  = 0.04
    row_h        = 0.062
    y            = 0.96
    max_per_sect = 6

    for s in show_order:
        items_s = (
            [i for i in job_items if i["status"] == s] +
            [i for i in phd_items if i["status"] == s]
        )
        if not items_s:
            continue

        name, color = STATUS_NODE[s]
        ax_l.text(0.04, y, name.upper(), color=color, fontsize=9,
                  fontweight="bold", va="top", transform=ax_l.transAxes)
        y -= row_h * 0.85

        for item in items_s[:max_per_sect]:
            dot   = STATUS_META[s]["dot"]
            label = item["label"]
            if len(label) > 38:
                label = label[:37] + "…"
            ax_l.text(0.04, y, dot,   color=color, fontsize=10,
                      va="top", transform=ax_l.transAxes, family="DejaVu Sans")
            ax_l.text(0.11, y, label, color=TEXT,  fontsize=10,
                      va="top", transform=ax_l.transAxes)
            y -= row_h
            if y < 0.04:
                break

        remaining = len(items_s) - max_per_sect
        if remaining > 0:
            ax_l.text(0.11, y, f"+ {remaining} more…",
                      color=MUTED, fontsize=9, style="italic",
                      va="top", transform=ax_l.transAxes)
            y -= row_h

        y -= section_sep
        if y < 0.04:
            break

    # ── Bake to pygame surface ─────────────────────────────────────────────────
    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    surf = pygame.image.frombuffer(canvas.buffer_rgba(), (W, H), "RGBA")
    plt.close(fig)
    return surf
