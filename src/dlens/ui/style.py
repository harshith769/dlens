"""The UI's design tokens and its one block of custom CSS, plus tiny HTML builders that escape
everything they are given. No Streamlit import.

Colors and fonts of the Streamlit theme itself live in ``.streamlit/config.toml``; this file
holds only what the theme cannot express (badges, chips, the steps timeline, the source view).
"""

from __future__ import annotations

from html import escape
from typing import Literal

TEXT = "#1B2A3A"
MUTED = "#5B6B7B"
BORDER = "#D5DEE7"
BACKGROUND = "#F7F9FB"
PRIMARY = "#1F5F8B"
VERIFIED = "#2E7D5B"
WARNING = "#B7791F"

# Edge-kind colors: used ONLY by the lineage diagram and its legend.
KIND_COLORS = {
    "IDENTITY": "#64748B",
    "RENAME": "#4F46E5",
    "TRANSFORMATION": "#D97706",
    "AGGREGATION": "#0F766E",
}

Tone = Literal["primary", "verified", "warning", "neutral"]
_TONES: dict[str, str] = {
    "primary": PRIMARY,
    "verified": VERIFIED,
    "warning": WARNING,
    "neutral": MUTED,
}

CSS = f"""
<style>
.block-container {{ padding-top: 1.6rem; }}
.dl-badge {{ display: inline-block; padding: 0.1rem 0.55rem; margin-right: 0.4rem;
  border: 1px solid currentColor; border-radius: 4px; font-size: 0.85rem; font-weight: 500;
  background: #FFFFFF; }}
.dl-muted {{ color: {MUTED}; font-size: 0.9rem; }}
.dl-stats {{ color: {MUTED}; font-size: 0.9rem; padding-bottom: 0.45rem; }}
.dl-claim {{ margin: 0.15rem 0 0.1rem 0; }}
.dl-src {{ border: 1px solid {BORDER}; border-radius: 4px; background: #FFFFFF;
  overflow-x: auto; max-height: 34rem; overflow-y: auto; }}
.dl-src pre {{ margin: 0; padding: 0.5rem 0; font-size: 0.82rem; line-height: 1.5;
  font-family: "IBM Plex Mono", monospace; background: transparent; white-space: pre;
  color: {TEXT}; }}
.dl-src .row {{ display: inline-block; min-width: 100%; padding-right: 0.75rem; }}
.dl-src .ln {{ color: {MUTED}; user-select: none; display: inline-block; text-align: right;
  box-sizing: content-box;
  padding: 0 0.6rem 0 0.75rem; margin-right: 0.75rem; border-right: 1px solid {BORDER};
  background: {BACKGROUND}; }}
.dl-src .hl {{ background: #FFF3D6; }}
.dl-src .hl .ln {{ background: #FCE7B6; color: {TEXT}; }}
.dl-legend {{ display: flex; flex-wrap: wrap; gap: 0.25rem 1rem; font-size: 0.82rem;
  color: {MUTED}; margin: 0.25rem 0 0.25rem 0; }}
.dl-legend span {{ display: inline-flex; align-items: center; gap: 0.35rem; }}
.dl-legend i {{ display: inline-block; width: 1.4rem; height: 0; border-top: 2px solid; }}
/* Tabs: the underline marks the active tab; no focus box or bar on top of it. */
[data-testid="stTab"], [data-testid="stTab"]:focus, [data-testid="stTab"]:focus-visible {{
  outline: none !important; box-shadow: none !important; }}
[data-testid="stTab"][data-focus-visible] p {{ text-decoration: underline; }}
.dl-pipe {{ display: flex; flex-wrap: wrap; align-items: stretch; gap: 0.5rem 0;
  margin: 0.25rem 0 0.4rem 0; }}
.dl-pipe .step {{ border: 1px solid {BORDER}; border-radius: 6px; background: #FFFFFF;
  padding: 0.4rem 0.7rem; font-size: 0.9rem; line-height: 1.3; }}
.dl-pipe .step small {{ display: block; color: {MUTED}; font-size: 0.8rem; }}
.dl-pipe .arrow {{ color: {MUTED}; align-self: center; padding: 0 0.45rem; }}
.dl-timeline {{ list-style: none; padding-left: 0; margin: 0; }}
.dl-timeline li {{ border-left: 2px solid {BORDER}; padding: 0 0 0.8rem 0.9rem;
  position: relative; }}
.dl-timeline li::before {{ content: ""; position: absolute; left: -6px; top: 0.35rem;
  width: 10px; height: 10px; border-radius: 50%; background: {PRIMARY}; }}
.dl-timeline li.code::before {{ background: {MUTED}; }}
.dl-timeline li.check::before {{ background: {VERIFIED}; }}
.dl-timeline li.warn::before {{ background: {WARNING}; }}
.dl-timeline .meta {{ color: {MUTED}; font-size: 0.85rem; }}
</style>
"""


def badge(label: str, tone: Tone = "neutral") -> str:
    """A small outlined label; ``label`` is escaped."""
    return f'<span class="dl-badge" style="color:{_TONES[tone]}">{escape(label)}</span>'


def legend_row(kinds: tuple[str, ...] | list[str]) -> str:
    """The edge-kind legend: a colored line and the kind's name, for the given kinds only."""
    items = "".join(
        f'<span><i style="color:{KIND_COLORS.get(k, MUTED)}"></i>{escape(k.capitalize())}</span>'
        for k in kinds
    )
    return f'<div class="dl-legend">{items}</div>'


def muted(text: str) -> str:
    return f'<span class="dl-muted">{escape(text)}</span>'


_STATUS = {
    "verified": ("✓", VERIFIED, ""),
    "repaired": ("⚠", WARNING, "repaired id"),
    "completed": ("⚠", WARNING, "completed citations"),
}


def claim_line(text: str, status: str) -> str:
    """One claim with its check mark; ``text`` is escaped."""
    mark, color, note = _STATUS.get(status, ("⚠", WARNING, status))
    tail = f' <span class="dl-muted">({escape(note)})</span>' if note else ""
    return (
        f'<div class="dl-claim"><span style="color:{color};font-weight:600">{mark}</span> '
        f"{escape(text)}{tail}</div>"
    )


def pipeline(steps: tuple[tuple[str, str], ...] | list[tuple[str, str]]) -> str:
    """The question-to-answer pipeline as boxes joined by arrows; wraps on narrow screens, so no
    label is ever clipped or shrunk. All text is escaped."""
    boxes = [
        f'<div class="step"><b>{escape(title)}</b><small>{escape(detail)}</small></div>'
        for title, detail in steps
    ]
    return '<div class="dl-pipe">' + '<span class="arrow">→</span>'.join(boxes) + "</div>"


def timeline(items: list[tuple[str, str, str, str]]) -> str:
    """A vertical list of steps: (title, detail, meta, css kind); all text is escaped."""
    rows = "".join(
        f'<li class="{escape(kind)}"><b>{escape(title)}</b>'
        + (f"<br>{escape(detail)}" if detail else "")
        + f'<br><span class="meta">{escape(meta)}</span></li>'
        for title, detail, meta, kind in items
    )
    return f'<ul class="dl-timeline">{rows}</ul>'
