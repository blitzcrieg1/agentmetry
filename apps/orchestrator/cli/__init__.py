"""agentmetry — local ops CLI for the Agentmetry appliance.

Commands: start, stop, status, logs, backup, restore, export, verify, install, uninstall.
Pure stdlib + httpx; never imports the FastAPI app (fast startup, no side effects).
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

_ORCH_ROOT = Path(__file__).resolve().parents[1]          # apps/orchestrator
_REPO_ROOT = _ORCH_ROOT.parents[1]                        # repo root
_DATA_DIR = _ORCH_ROOT / "data"
_PID_FILE = _DATA_DIR / "agentmetry.pid"
_TASK_NAME = "Agentmetry Orchestrator"

# Paths bundled by backup, relative to the repo root.
_BACKUP_PREFIXES = ("vault/", "apps/orchestrator/data/")
_BACKUP_EXCLUDE_DIRS = {"logs"}
_BACKUP_EXCLUDE_SUFFIXES = {".pid"}


def _base_url(port: int, host: str = "127.0.0.1") -> str:
    display = host if host != "0.0.0.0" else "127.0.0.1"
    return f"http://{display}:{port}"


def _lan_ip() -> str | None:
    """Best-effort local IPv4 for phone/LAN access hints."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return None


def _print_lan_hint(port: int) -> None:
    ip = _lan_ip()
    if not ip:
        print("LAN: could not detect local IP — run ipconfig and use http://<your-ip>:8000")
        return
    print(f"Phone / LAN dashboard: http://{ip}:{port}")
    print("  (Needs dashboard built — run scripts\\serve.bat or scripts\\mobile.bat first)")


def _fetch_health(port: int) -> dict | None:
    try:
        # Generous: /health probes optional services whose ports may black-hole.
        resp = httpx.get(f"{_base_url(port)}/api/v1/health", timeout=10.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- start/stop


def cmd_start(args: argparse.Namespace) -> int:
    host = getattr(args, "host", "127.0.0.1")
    if _fetch_health(args.port):
        print(f"Already running on {_base_url(args.port, host)}")
        if host == "0.0.0.0":
            _print_lan_hint(args.port)
        return 0

    _DATA_DIR.joinpath("logs").mkdir(parents=True, exist_ok=True)
    out_log = _DATA_DIR / "logs" / "uvicorn.out"

    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP

    with out_log.open("ab") as out:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "api.main:app",
                "--host",
                host,
                "--port",
                str(args.port),
            ],
            cwd=str(_ORCH_ROOT),
            stdout=out,
            stderr=out,
            creationflags=flags,
        )
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(proc.pid), encoding="utf-8")

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if _fetch_health(args.port):
            print(f"Agentmetry running on {_base_url(args.port, host)} (pid {proc.pid})")
            if host == "0.0.0.0":
                _print_lan_hint(args.port)
            return 0
        if proc.poll() is not None:
            print(f"Orchestrator exited early (code {proc.returncode}) - see {out_log}")
            return 1
        time.sleep(0.5)
    print(f"Started pid {proc.pid} but health did not respond in 20s - see {out_log}")
    return 1


def cmd_stop(args: argparse.Namespace) -> int:
    if not _PID_FILE.exists():
        if _fetch_health(args.port):
            print("Running, but no pid file (started manually?) — stop that process directly.")
            return 1
        print("Not running.")
        return 0

    pid = _PID_FILE.read_text(encoding="utf-8").strip()
    if os.name == "nt":
        # Hard kill of the tree. Equivalent to closing the terminal today;
        # SQLite is crash-safe and pending approvals recover on next start.
        result = subprocess.run(
            ["taskkill", "/PID", pid, "/T", "/F"], capture_output=True, text=True
        )
        ok = result.returncode == 0 or "not found" in (result.stderr or "").lower()
    else:
        try:
            os.kill(int(pid), 15)
            ok = True
        except ProcessLookupError:
            ok = True
        except Exception:
            ok = False
    _PID_FILE.unlink(missing_ok=True)
    print(f"Stopped (pid {pid})." if ok else f"Could not stop pid {pid}.")
    return 0 if ok else 1


# -------------------------------------------------------------------- status


def cmd_status(args: argparse.Namespace) -> int:
    health = _fetch_health(args.port)
    if health is None:
        print(f"Agentmetry: not running ({_base_url(args.port)})")
        return 1

    print(f"Agentmetry: {health.get('status', '?')} on {_base_url(args.port)}")
    print(f"  Mode:   {health.get('mode', 'siem')}")
    audit = health.get("audit_export") or {}
    if audit:
        print(f"  Export: {'enabled' if audit.get('enabled') else 'disabled'} → {audit.get('path', '?')}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """Audit trail metrics over a window — dogfood weekly counts."""
    try:
        data = httpx.get(
            f"{_base_url(args.port)}/api/v1/audit/stats",
            params={"days": args.days},
            timeout=10.0,
        ).json()
    except Exception:
        print("Not running - start Agentmetry first (stats reads via the API).")
        return 1

    if not data.get("enabled", True):
        print("Audit export disabled — enable AGENTMETRY_AUDIT_EXPORT to collect stats.")
        return 1

    days = data.get("window_days", args.days)
    print(f"Audit trail — last {days} day(s):")
    print(f"  Events:          {data.get('total_events', 0)}")
    print(f"  Sessions:        {data.get('sessions', 0)}")
    print(f"  Detections:      {data.get('detections', 0)}")
    print(f"  Denied:          {data.get('denied', 0)}")
    print(f"  DLP matches:     {data.get('dlp_matches', 0)}")
    print(f"  Tool policy:     {data.get('tool_policy_hits', 0)} hits / "
          f"{data.get('tool_policy_blocks', 0)} blocked")
    by_source = data.get("by_source") or {}
    if by_source:
        parts = ", ".join(f"{k}={v}" for k, v in by_source.items())
        print(f"  By source:       {parts}")
    last = data.get("last_event_utc")
    if last:
        print(f"  Last event:      {last}")
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    log = _DATA_DIR / "logs" / "orchestrator.log"
    if not log.exists():
        print(f"No log file yet at {log}")
        return 1

    def tail() -> list[str]:
        return log.read_text(encoding="utf-8", errors="replace").splitlines()[-args.lines:]

    for line in tail():
        print(line)
    if args.follow:
        seen = log.stat().st_size
        try:
            while True:
                time.sleep(1.0)
                size = log.stat().st_size
                if size > seen:
                    with log.open("r", encoding="utf-8", errors="replace") as f:
                        f.seek(seen)
                        print(f.read(), end="")
                    seen = size
        except KeyboardInterrupt:
            pass
    return 0


# ----------------------------------------------------------- backup/restore


def _iter_backup_files(repo_root: Path):
    for prefix in _BACKUP_PREFIXES:
        root = repo_root / prefix
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(repo_root).as_posix()
            parts = set(path.relative_to(root).parts[:-1])
            if parts & _BACKUP_EXCLUDE_DIRS:
                continue
            if path.suffix in _BACKUP_EXCLUDE_SUFFIXES:
                continue
            yield path, rel


def create_backup(repo_root: Path = _REPO_ROOT, out_path: Path | None = None) -> Path:
    """Zip the vault (runtime dirs included) and data stores.

    SQLite files are snapshotted via the backup API so a live orchestrator
    never yields a torn copy.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    if out_path is None:
        out_path = repo_root / "backups" / f"agentmetry-backup-{stamp}.zip"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(
        out_path, "w", zipfile.ZIP_DEFLATED
    ) as zf:
        for path, rel in _iter_backup_files(repo_root):
            if path.suffix == ".db":
                snapshot = Path(tmp) / f"{count}-{path.name}"
                src = sqlite3.connect(str(path))
                try:
                    dst = sqlite3.connect(str(snapshot))
                    with dst:
                        src.backup(dst)
                    dst.close()
                finally:
                    src.close()
                zf.write(snapshot, rel)
            else:
                zf.write(path, rel)
            count += 1
    # ASCII only: Windows consoles often run cp1252.
    print(f"Backed up {count} files -> {out_path}")
    return out_path


def restore_backup(zip_path: Path, repo_root: Path = _REPO_ROOT) -> int:
    """Extract a backup over vault/ and data/. Zip-slip guarded."""
    allowed_roots = [(repo_root / prefix).resolve() for prefix in _BACKUP_PREFIXES]

    def _validated_target(name: str) -> Path:
        normalized = name.replace("\\", "/")
        target = (repo_root / normalized).resolve()
        # Resolved containment, not string prefixes: rejects vault/../evil.txt.
        if not any(root == target or root in target.parents for root in allowed_roots):
            raise ValueError(f"Backup member outside allowed roots: {name}")
        return target

    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if not n.endswith("/")]
        targets = {name: _validated_target(name) for name in members}  # validate all first
        for name, target in targets.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    print(f"Restored {len(members)} files from {zip_path}")
    return len(members)


def cmd_backup(args: argparse.Namespace) -> int:
    create_backup(out_path=Path(args.out) if args.out else None)
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    if _fetch_health(args.port):
        print("Refusing to restore while Agentmetry is running — run 'agentmetry stop' first.")
        return 1
    zip_path = Path(args.backup_zip)
    if not zip_path.exists():
        print(f"No such backup: {zip_path}")
        return 1
    # Safety net: snapshot current state before overwriting it.
    pre = create_backup(
        out_path=_REPO_ROOT / "backups" / f"pre-restore-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.zip"
    )
    print(f"Current state saved to {pre}")
    restore_backup(zip_path)
    return 0


# --------------------------------------------------------- install/uninstall


def cmd_install(args: argparse.Namespace) -> int:
    if os.name != "nt":
        print("install is Windows-only (Task Scheduler).")
        return 1
    bat = _REPO_ROOT / "scripts" / "agentmetry.bat"
    tr = f'cmd /c ""{bat}" start"'
    result = subprocess.run(
        ["schtasks", "/Create", "/TN", _TASK_NAME, "/TR", tr,
         "/SC", "ONLOGON", "/RL", "LIMITED", "/IT", "/F"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"schtasks failed: {result.stderr.strip() or result.stdout.strip()}")
        return 1
    print(f"Registered '{_TASK_NAME}' to start at logon (user session, so toasts work).")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    if os.name != "nt":
        print("uninstall is Windows-only (Task Scheduler).")
        return 1
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", _TASK_NAME, "/F"], capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"schtasks failed: {result.stderr.strip() or result.stdout.strip()}")
        return 1
    print(f"Removed scheduled task '{_TASK_NAME}'.")
    return 0


# ------------------------------------------------------------------- export


def cmd_export(args: argparse.Namespace) -> int:
    from core.audit.evidence_pack import (
        build_evidence_pack,
        default_export_path,
        parse_date,
        write_evidence_pack,
    )

    if not args.evidence:
        print("Use: agentmetry export --evidence --from YYYY-MM-DD --to YYYY-MM-DD")
        return 1
    if not args.date_from or not args.date_to:
        print("--from and --to are required (YYYY-MM-DD)")
        return 1

    try:
        from_date = parse_date(args.date_from)
        to_date = parse_date(args.date_to)
    except ValueError as exc:
        print(f"Invalid date: {exc}")
        return 1

    pack = build_evidence_pack(from_date, to_date)
    out = Path(args.output) if args.output else default_export_path(from_date, to_date)
    write_evidence_pack(pack, out)

    summary = pack.get("summary", {})
    print(f"Evidence pack -> {out}")
    print(
        f"  {summary.get('event_count', 0)} events, "
        f"{summary.get('run_ledger_rows', 0)} ledger rows, "
        f"{summary.get('approval_gates', 0)} approval gates, "
        f"{summary.get('tool_calls', 0)} tool calls"
    )
    print(f"  integrity: {pack['meta']['integrity_sha256'][:16]}…")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    import json

    path = Path(args.path)
    if not path.exists():
        print(f"No such file: {path}")
        return 1

    if getattr(args, "trail", False):
        from core.audit.trail_chain import verify_trail_file

        result = verify_trail_file(path)
        if result.ok:
            print(f"OK — {result.message}")
            if result.lines_total:
                print(
                    f"  lines: {result.lines_total} total, "
                    f"{result.lines_chained} chained, {result.lines_legacy} legacy"
                )
            if result.head_sha256:
                # Record this pair somewhere the audited agent cannot write
                # (a git commit, a note) — comparing it later is the only
                # defense against someone deleting the newest lines.
                print(f"  head: seq {result.head_seq}, sha256 {result.head_sha256}")
            return 0
        print(f"FAILED — {result.message}")
        if result.first_bad_line:
            print(f"  first bad line: {result.first_bad_line}")
        return 1

    from core.audit.evidence_pack import verify_evidence_pack

    try:
        pack = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}")
        return 1

    ok, message = verify_evidence_pack(pack)
    if ok:
        print(f"OK — {message}")
        meta = pack.get("meta", {})
        print(
            f"  {meta.get('date_from')} .. {meta.get('date_to')}  "
            f"schema {meta.get('schema_version')}"
        )
        return 0
    print(f"FAILED — {message}")
    return 1


def cmd_replay(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(_ORCH_ROOT))
    from core.audit.replay import format_timeline
    from core.bus.outbox import get_outbox

    thread_id = args.thread_id.strip()
    if not thread_id:
        print("thread_id is required")
        return 1
    rows = get_outbox().read_by_thread_id(thread_id)
    print(format_timeline(rows, thread_id=thread_id))
    return 0 if rows else 1


def cmd_doctor(args: argparse.Namespace) -> int:
    """SIEM preflight: manifests, trail chain, orchestrator health, hooks."""
    sys.path.insert(0, str(_ORCH_ROOT))
    from core.diagnostics.doctor import format_report, run_doctor

    report = run_doctor(fix_drivers=getattr(args, "fix", False))
    print("Agentmetry doctor\n" + format_report(report))
    return report.exit_code


# ---------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    # A Windows console defaults to cp1252 and cannot encode the dashes this CLI
    # prints, so `verify --trail` rendered as "OK ? 422 chained line(s)". That is
    # the flagship trust command; it must not look broken on the primary dogfood
    # platform. Same guard as scripts/demo.py.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # pragma: no cover - depends on the host console
        pass

    parser = argparse.ArgumentParser(prog="agentmetry", description="Agentmetry local ops")
    parser.add_argument("--port", type=int, default=8000)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("stop", help="stop the orchestrator")
    start = sub.add_parser("start", help="start the orchestrator (detached)")
    start.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind address — use 0.0.0.0 for phone/LAN access (default: 127.0.0.1)",
    )
    sub.add_parser("status", help="orchestrator health and audit export status")
    stats = sub.add_parser("stats", help="audit trail metrics for dogfood (events, detections)")
    stats.add_argument("--days", type=int, default=7)
    logs = sub.add_parser("logs", help="tail the orchestrator log")
    logs.add_argument("-n", "--lines", type=int, default=50)
    logs.add_argument("-f", "--follow", action="store_true")
    backup = sub.add_parser("backup", help="zip vault + data stores")
    backup.add_argument("--out", default=None)
    restore = sub.add_parser("restore", help="restore a backup (server must be stopped)")
    restore.add_argument("backup_zip")
    sub.add_parser("install", help="register at-logon start (Task Scheduler)")
    sub.add_parser("uninstall", help="remove the scheduled task")
    export = sub.add_parser("export", help="export audit artifacts")
    export.add_argument(
        "--evidence", action="store_true",
        help="build EU AI Act-oriented evidence pack (JSON)",
    )
    export.add_argument("--from", dest="date_from", metavar="DATE", required=False)
    export.add_argument("--to", dest="date_to", metavar="DATE", required=False)
    export.add_argument("-o", "--output", default=None, help="output path (default: vault/30-Archive/exports/)")
    verify = sub.add_parser("verify", help="verify evidence pack or JSONL trail chain")
    verify.add_argument(
        "path",
        help="evidence JSON file, or JSONL trail with --trail",
    )
    verify.add_argument(
        "--trail",
        action="store_true",
        help="verify tamper-evident hash chain on an audit JSONL file",
    )
    doctor = sub.add_parser(
        "doctor", help="SIEM preflight (manifests, trail chain, health, hooks)"
    )
    doctor.add_argument(
        "--fix",
        action="store_true",
        help="rewrite drivers.json to portable {PYTHON}/{VAULT_PATH} tokens",
    )
    replay = sub.add_parser("replay", help="ASCII timeline of audit events for one run")
    replay.add_argument("thread_id", help="correlation_id / session id to replay from audit trail")

    args = parser.parse_args(argv)
    handlers = {
        "start": cmd_start,
        "stop": cmd_stop,
        "status": cmd_status,
        "stats": cmd_stats,
        "logs": cmd_logs,
        "backup": cmd_backup,
        "restore": cmd_restore,
        "install": cmd_install,
        "uninstall": cmd_uninstall,
        "export": cmd_export,
        "verify": cmd_verify,
        "doctor": cmd_doctor,
        "replay": cmd_replay,
    }
    return handlers[args.command](args)
