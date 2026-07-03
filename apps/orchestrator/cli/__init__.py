"""blackbox — local ops CLI for the BLACKBOX appliance.

Commands: start, stop, status, logs, backup, restore, install, uninstall.
Pure stdlib + httpx; never imports the FastAPI app (fast startup, no side effects).
"""

from __future__ import annotations

import argparse
import os
import shutil
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
_PID_FILE = _DATA_DIR / "blackbox.pid"
_TASK_NAME = "BLACKBOX Orchestrator"

# Paths bundled by backup, relative to the repo root.
_BACKUP_PREFIXES = ("vault/", "apps/orchestrator/data/")
_BACKUP_EXCLUDE_DIRS = {"logs"}
_BACKUP_EXCLUDE_SUFFIXES = {".pid"}


def _base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


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
    if _fetch_health(args.port):
        print(f"Already running on {_base_url(args.port)}")
        return 0

    _DATA_DIR.joinpath("logs").mkdir(parents=True, exist_ok=True)
    out_log = _DATA_DIR / "logs" / "uvicorn.out"

    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP

    with out_log.open("ab") as out:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api.main:app", "--port", str(args.port)],
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
            print(f"BLACKBOX running on {_base_url(args.port)} (pid {proc.pid})")
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
        print(f"BLACKBOX: not running ({_base_url(args.port)})")
        return 1

    modes = health.get("modes", {})
    budget = health.get("budget", {})
    vault = health.get("vault", {})
    print(f"BLACKBOX: {health.get('status', '?')} on {_base_url(args.port)}")
    print(f"  LLM:    {modes.get('llm', '?')}   RAG: {modes.get('rag', '?')}")
    print(f"  Vault:  {vault.get('notes', '?')} notes at {vault.get('path', '?')}")
    if budget:
        flag = "" if budget.get("autonomous_allowed") else "  [autonomous paused]"
        print(
            f"  Budget: {budget.get('flash_used', 0)}/{budget.get('flash_limit', 0)} "
            f"Flash calls today{flag}"
        )
    try:
        pending = httpx.get(
            f"{_base_url(args.port)}/api/v1/skills/pending", timeout=2.0
        ).json().get("pending", [])
        if pending:
            print(f"  Pending approvals: {len(pending)}")
    except Exception:
        pass
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
        out_path = repo_root / "backups" / f"blackbox-backup-{stamp}.zip"
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
        print("Refusing to restore while BLACKBOX is running — run 'blackbox stop' first.")
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
    bat = _REPO_ROOT / "scripts" / "blackbox.bat"
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


# ---------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="blackbox", description="BLACKBOX local ops")
    parser.add_argument("--port", type=int, default=8000)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("start", help="start the orchestrator (detached)")
    sub.add_parser("stop", help="stop the orchestrator")
    sub.add_parser("status", help="health, budget, pending approvals")
    logs = sub.add_parser("logs", help="tail the orchestrator log")
    logs.add_argument("-n", "--lines", type=int, default=50)
    logs.add_argument("-f", "--follow", action="store_true")
    backup = sub.add_parser("backup", help="zip vault + data stores")
    backup.add_argument("--out", default=None)
    restore = sub.add_parser("restore", help="restore a backup (server must be stopped)")
    restore.add_argument("backup_zip")
    sub.add_parser("install", help="register at-logon start (Task Scheduler)")
    sub.add_parser("uninstall", help="remove the scheduled task")

    args = parser.parse_args(argv)
    handlers = {
        "start": cmd_start,
        "stop": cmd_stop,
        "status": cmd_status,
        "logs": cmd_logs,
        "backup": cmd_backup,
        "restore": cmd_restore,
        "install": cmd_install,
        "uninstall": cmd_uninstall,
    }
    return handlers[args.command](args)
