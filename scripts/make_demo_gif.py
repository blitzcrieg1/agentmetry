#!/usr/bin/env python3
"""Render docs/assets/demo.gif from the REAL output of scripts/demo.py.

    python scripts/make_demo_gif.py

This runs the demo as a subprocess with colour forced on, parses the ANSI codes,
and draws a terminal animation. It never hand-writes the transcript: if the
detection stops firing, the GIF stops showing it. A marketing asset that can
drift from the product is a liability on a security tool.

Only dependency is Pillow (already required by the dashboard build chain).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_REPO = Path(__file__).resolve().parent.parent
_OUT = _REPO / "docs" / "assets" / "demo.gif"
_OUT_SHORT = _REPO / "docs" / "assets" / "demo-short.gif"

# The social cut. LinkedIn/X viewers are scrolling: drop the framing and the
# receipts, keep the three tool calls and the detection that lands on them.
_SHORT_DROP = (
    "AGENTMETRY", "Replaying an agent session", "Trail:", "The receipts",
    "Secret value", "Detections from the trail", "Events sent to SIEM",
    "Everything above stayed",
)

# GitHub-dark palette; ANSI code -> RGB.
BG = (13, 17, 23)
CHROME = (22, 27, 34)
FG = (201, 209, 217)
ANSI = {
    "0": FG,
    "1": (255, 255, 255),   # bold
    "2": (110, 118, 129),   # dim
    "91": (255, 123, 114),  # red
    "92": (63, 185, 80),    # green
    "93": (210, 168, 255),  # yellow -> violet reads better on dark
    "96": (121, 192, 255),  # blue
}

FONT_SIZE = 15
LINE_H = 21
PAD_X, PAD_TOP = 22, 46
COLS = 78
CURSOR = (63, 185, 80)

_SGR = re.compile(r"\033\[([0-9;]*)m")


def _font(bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "consolab.ttf" if bold else "consola.ttf"
    for candidate in (Path("C:/Windows/Fonts") / name, Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")):
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), FONT_SIZE)
    return ImageFont.load_default()


REG, BOLD = _font(), _font(bold=True)

Span = tuple[str, tuple[int, int, int], bool]  # text, colour, bold


def parse_ansi(line: str) -> list[Span]:
    """Split one ANSI-coded line into (text, colour, bold) spans."""
    spans: list[Span] = []
    colour, bold, pos = FG, False, 0
    for m in _SGR.finditer(line):
        if m.start() > pos:
            spans.append((line[pos : m.start()], colour, bold))
        for code in (m.group(1) or "0").split(";"):
            if code in ("", "0"):
                colour, bold = FG, False
            elif code == "1":
                bold = True
            elif code in ANSI:
                colour = ANSI[code]
        pos = m.end()
    if pos < len(line):
        spans.append((line[pos:], colour, bold))
    return spans


def wrap(spans: list[Span], width: int = COLS) -> list[list[Span]]:
    """Wrap a span line to `width` columns, preserving colour across the break.

    Without this a long detection summary is silently truncated at the frame
    edge — i.e. the GIF would crop the one sentence the whole demo exists for.
    """
    plain = "".join(s[0] for s in spans)
    if len(plain) <= width:
        return [spans]

    indent = " " * (len(plain) - len(plain.lstrip()) + 2)
    out: list[list[Span]] = []
    cur: list[Span] = []
    used = 0
    for text, colour, bold in spans:
        while text:
            room = width - used
            if len(text) <= room:
                cur.append((text, colour, bold))
                used += len(text)
                break
            cut = text.rfind(" ", 0, room + 1)
            if cut <= 0:
                cut = room
            cur.append((text[:cut], colour, bold))
            out.append(cur)
            text = text[cut:].lstrip()
            cur = [(indent, FG, False)]
            used = len(indent)
    if cur:
        out.append(cur)
    return out


def draw_frame(lines: list[list[Span]], height: int, cursor: bool) -> Image.Image:
    img = Image.new("RGB", (COLS * 9 + PAD_X * 2, height), BG)
    d = ImageDraw.Draw(img)

    # window chrome
    d.rectangle([0, 0, img.width, 30], fill=CHROME)
    for i, dot in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([16 + i * 18, 11, 24 + i * 18, 19], fill=dot)
    d.text((img.width // 2 - 60, 8), "agentmetry — demo", font=REG, fill=(110, 118, 129))

    y = PAD_TOP
    for spans in lines:
        x = PAD_X
        for text, colour, bold in spans:
            d.text((x, y), text, font=BOLD if bold else REG, fill=colour)
            x += int(d.textlength(text, font=BOLD if bold else REG))
        if cursor and spans is lines[-1]:
            d.rectangle([x + 1, y + 2, x + 9, y + FONT_SIZE + 2], fill=CURSOR)
        y += LINE_H
    return img


def main() -> int:
    short = "--short" in sys.argv
    out = _OUT_SHORT if short else _OUT
    env = {**os.environ, "AGENTMETRY_DEMO_COLOR": "1", "AGENTMETRY_DEMO_FAST": "1"}
    proc = subprocess.run(
        [sys.executable, str(_REPO / "scripts" / "demo.py")],
        capture_output=True, text=True, env=env, cwd=_REPO, encoding="utf-8",
    )
    if proc.returncode != 0:
        print("demo.py failed — refusing to render a GIF of a broken demo", file=sys.stderr)
        print(proc.stderr[-2000:], file=sys.stderr)
        return 1

    raw = [ln.rstrip("\n") for ln in proc.stdout.splitlines()]
    if short:
        kept: list[str] = []
        dropped_prev = False
        for ln in raw:
            if any(k in ln for k in _SHORT_DROP):
                dropped_prev = True
                continue
            # A separator rule belongs to the heading above it. If that heading
            # was cut, the rule must go too, or it dangles in the frame.
            # Strip the ANSI codes first — the rule is dim-coloured.
            plain = _SGR.sub("", ln).strip()
            is_rule = bool(plain) and set(plain) <= {"─", "-"}
            if is_rule and dropped_prev:
                continue
            dropped_prev = False
            kept.append(ln)
        raw = kept
    # Trim leading/trailing blanks, collapse runs of blank lines.
    lines: list[str] = []
    for ln in raw:
        if not ln.strip() and (not lines or not lines[-1].strip()):
            continue
        lines.append(ln)
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)

    # Pre-wrap so the canvas is tall enough for every rendered row.
    wrapped: list[tuple[str, list[list[Span]]]] = [
        (line, wrap(parse_ansi(line))) for line in lines
    ]
    rows = sum(len(w) for _, w in wrapped)
    height = PAD_TOP + LINE_H * rows + 18
    print(f"rendering {rows} rows -> {COLS * 9 + PAD_X * 2}x{height}")

    frames: list[Image.Image] = []
    durations: list[int] = []
    shown: list[list[Span]] = []

    for line, chunks in wrapped:
        spans = parse_ansi(line)
        plain = "".join(s[0] for s in spans)

        if plain.strip().startswith("$"):
            # Type the command out, character by character.
            step = 18 if short else 28
            for i in range(1, len(plain) + 1):
                budget, typed = i, []
                for text, colour, bold in spans:
                    if budget <= 0:
                        break
                    typed.append((text[:budget], colour, bold))
                    budget -= len(text)
                frames.append(draw_frame([*shown, typed], height, True))
                durations.append(step)
            shown.extend(chunks)
            frames.append(draw_frame(shown, height, True))
            durations.append(220 if short else 320)
        else:
            shown.extend(chunks)
            frames.append(draw_frame(shown, height, True))
            # Linger on the payoff lines.
            hot = any(k in plain for k in ("CRITICAL", "DLP", "detection", "Secret value"))
            if hot:
                durations.append(560 if short else 620)
            else:
                durations.append(120 if short else 190)

    # Hold the final frame so the punchline is readable in a loop.
    frames.append(draw_frame(shown, height, False))
    durations.append(2600 if short else 3200)

    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        out, save_all=True, append_images=frames[1:], duration=durations,
        loop=0, optimize=True, disposal=2,
    )
    kb = out.stat().st_size / 1024
    print(f"wrote {out.relative_to(_REPO)}  ({len(frames)} frames, {kb:.0f} KB, "
          f"{sum(durations)/1000:.1f}s)")
    if kb > 5000:
        print("WARNING: >5MB — GitHub may not autoplay it", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
