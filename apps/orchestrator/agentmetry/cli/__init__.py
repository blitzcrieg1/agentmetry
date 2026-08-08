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

_ORCH_ROOT = Path(__file__).resolve().parents[2]          # apps/orchestrator
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
                "agentmetry.api.main:app",
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


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the orchestrator in the foreground, logging to a file.

    This is the entry point autostart registers, and it exists because of a
    specific Windows failure. A background task must not flash a console window,
    which means `pythonw.exe` — and under `pythonw.exe` there is no console, so
    `sys.stdout` and `sys.stderr` are None. Uvicorn configures a logging handler
    against `sys.stdout` on startup and dies before serving a single request.
    The scheduled task ran, exited 1, and left no trace of why, which is the
    same shape of silent failure the spool had.

    So: point the streams at the same log `agentmetry start` uses, then run in
    the foreground. Foreground matters. A supervisor watching a process that
    forks and exits is watching the wrong process, and would never restart the
    one that actually died.
    """
    log_dir = _DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    out_log = log_dir / "uvicorn.out"

    stream = out_log.open("a", buffering=1, encoding="utf-8", errors="replace")
    sys.stdout = stream
    sys.stderr = stream

    import uvicorn

    uvicorn.run("agentmetry.api.main:app", host=args.host, port=args.port)
    return 0


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
    """Register the orchestrator to start by itself and stay up.

    This used to be Windows-only, and used to start at logon with no restart
    policy, so a crashed recorder stayed dead until the next logon. Both are
    fixed. It is still opt-in: a persistent background process is the user's
    decision, and `doctor` only points at this command rather than running it.
    """
    from agentmetry.core.diagnostics import autostart

    current = autostart.status()
    # "Already configured" is the right answer only for a registration that
    # works. A broken one used to get the same reply, which sent the operator
    # to the command they had just run: doctor said run install, install said
    # already installed, and the recorder stayed down. Re-registering is how a
    # stale launch command gets repaired, so a failing task is exactly when
    # this must not short-circuit.
    if current.configured and current.healthy is not False:
        print(f"Already configured via {current.backend}: {current.detail}")
        return 0
    if current.configured:
        print(f"Re-registering a failing autostart ({current.backend}): {current.detail}")

    ok, message = autostart.install()
    print(message)
    if not ok:
        return 1
    print("The recorder now starts by itself. Check it with `agentmetry doctor`.")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    from agentmetry.core.diagnostics import autostart

    current = autostart.status()
    if not current.configured:
        print(f"Nothing to remove ({current.backend}: {current.detail}).")
        return 0

    ok, message = autostart.remove()
    print(message)
    if not ok:
        return 1
    print(
        "Autostart removed. The hooks keep capturing whether or not the recorder "
        "is up, but events only reach the trail while it is running."
    )
    return 0


# ------------------------------------------------------------------- export


def _write_compliance_digest(from_date, to_date, args: argparse.Namespace) -> int:
    """Periodic governance summary — the artifact a reviewer files monthly."""
    import json

    from agentmetry.core.audit.compliance_digest import build_digest, render_markdown
    from agentmetry.core.audit.evidence_pack import default_export_path

    digest = build_digest(from_date, to_date)
    as_json = getattr(args, "json", False)

    if args.output:
        out = Path(args.output)
    else:
        out = default_export_path(from_date, to_date).with_name(
            f"digest-{from_date.isoformat()}_to_{to_date.isoformat()}"
            f".{'json' if as_json else 'md'}"
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    body = (
        json.dumps(digest, indent=2, default=str) + "\n"
        if as_json
        else render_markdown(digest)
    )
    out.write_text(body, encoding="utf-8")

    activity = digest["activity"]
    oversight = digest["oversight"]
    print(f"Compliance digest -> {out}")
    print(
        f"  {activity['events']} events, {activity['sessions']} sessions, "
        f"{activity['tool_denials']} denials"
    )
    print(
        f"  {len(digest['findings'])} distinct finding(s); "
        f"{oversight['inferred']}/{oversight['approval_gates']} approvals inferred"
    )
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from agentmetry.core.audit.evidence_pack import (
        build_evidence_pack,
        default_export_path,
        parse_date,
        write_evidence_pack,
    )

    digest_mode = getattr(args, "compliance_digest", False)
    if not args.evidence and not digest_mode:
        print(
            "Use: agentmetry export --evidence --from YYYY-MM-DD --to YYYY-MM-DD\n"
            "  or: agentmetry export --compliance-digest --from … --to …"
        )
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

    if digest_mode:
        return _write_compliance_digest(from_date, to_date, args)

    pack = build_evidence_pack(from_date, to_date)
    out = Path(args.output) if args.output else default_export_path(from_date, to_date)
    write_evidence_pack(pack, out)

    summary = pack.get("summary", {})
    print(f"Evidence pack -> {out}")
    print(
        f"  {summary.get('event_count', 0)} events, "
        f"{summary.get('sessions', 0)} sessions, "
        f"{summary.get('tool_calls', 0)} tool calls, "
        f"{summary.get('tool_denials', 0)} denials"
    )
    print(
        f"  {summary.get('approval_gates', 0)} approval gates "
        f"({summary.get('approvals_inferred', 0)} inferred), "
        f"{summary.get('detections', 0)} detections"
    )
    chain = pack["meta"].get("trail_chain", {})
    if chain.get("head_sha256"):
        print(f"  chain head: seq {chain.get('head_seq')} {chain['head_sha256'][:16]}…")
    print(f"  integrity: {pack['meta']['integrity_sha256'][:16]}…")
    return 0


def cmd_import_agt(args: argparse.Namespace) -> int:
    """Ingest a Microsoft Agent Governance Toolkit audit file into the trail.

    AGT decides allow or deny per call; this says what a session of those calls
    adds up to. In testing it read three calls AGT had individually allowed and
    raised one critical `credential-exfil` across them.
    """
    import os

    from agentmetry.core.audit.adapters.agt import agt_file_to_canonical
    from agentmetry.core.audit.trail_chain import append_chained_line
    from agentmetry.core.config import settings

    path = Path(args.path)
    if not path.is_file():
        print(f"No such file: {path}")
        return 1

    key: bytes | None = None
    raw_key = args.key or os.environ.get("AGENTMETRY_AGT_HMAC_KEY", "")
    if raw_key:
        key = raw_key.encode()

    result, events = agt_file_to_canonical(
        path,
        secret_key=key,
        host_id=args.host_id or settings.operator_id or "",
        fleet_id=settings.fleet_id or "",
    )

    if not result.ok:
        # Nothing is imported. Writing an unverified record into a hash-chained
        # trail would have the chain vouch for a claim nobody checked.
        print(f"FAILED — {result.message}")
        print("  Nothing imported. The trail does not launder unverified records.")
        return 1

    print(f"OK — {result.message}")
    if key is None:
        print(
            "  No HMAC key supplied, so signatures were not checked. Hashes and "
            "chain linkage were, which catches editing and reordering. Pass --key "
            "or set AGENTMETRY_AGT_HMAC_KEY to check forgery too."
        )

    if args.dry_run:
        print(f"  Dry run: {len(events)} event(s) would be appended.")
        from agentmetry.core.audit.detection.engine import run_detections

        detections = run_detections(events)
        for detection in detections:
            print(f"  [{detection.severity}] {detection.rule_id}: {detection.title}")
        if not detections:
            print("  No detections would fire on this session.")
        return 0

    trail = Path(settings.audit_export_path)
    for event in events:
        append_chained_line(trail, event)
    print(f"  Appended {len(events)} event(s) to {trail}")
    print("  Marked source.tier=external, app=agt: Agentmetry read this record "
          "rather than observing the calls.")
    return 0


def cmd_prove(args: argparse.Namespace) -> int:
    """Produce or check a Merkle inclusion proof for one trail record.

    The point of the separate command is disclosure. Handing an auditor the
    trail to prove one tool call happened also hands them every other tool call,
    which is why "just send the log" is not an answer anyone likes giving. A
    proof is the one record plus about log2(n) sibling hashes.
    """
    import json

    from agentmetry.core.audit.trail_merkle import (
        InclusionProof,
        build_proof,
        merkle_root,
        record_root,
        verify_proof,
    )

    path = Path(args.path)

    if args.check:
        proof_path = Path(args.check)
        if not proof_path.is_file():
            print(f"No such proof file: {proof_path}")
            return 1
        try:
            proof = InclusionProof.from_dict(json.loads(proof_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            print(f"Not a readable proof: {exc}")
            return 1
        expected = args.root
        if not expected and path.is_file():
            # At the proof's tree size, not the current one. The trail is
            # append-only and live, so today's root is not the root the proof
            # was issued against and comparing them fails for no useful reason.
            try:
                expected, _ = merkle_root(path, tree_size=proof.tree_size)
            except ValueError as exc:
                print(f"FAILED — {exc}")
                return 1
        ok, message = verify_proof(proof, expected_root=expected)
        print(("OK — " if ok else "FAILED — ") + message)
        if ok and not args.root:
            print(
                "  Supply --root with a value you recorded elsewhere to make this "
                "a real check; a trail can always vouch for itself."
            )
        return 0 if ok else 1

    if not path.is_file():
        print(f"No such file: {path}")
        return 1
    if args.record_root:
        result = record_root(path)
        print(f"Recorded merkle root {result['root']}")
        print(f"  tree size: {result['tree_size']}")
        print(f"  sidecar: {result['sidecar']}")
        return 0
    if args.seq is None:
        print("Give --seq N to prove a record, --record-root to store the root, "
              "or --check PROOF to verify one.")
        return 1

    try:
        proof = build_proof(path, args.seq)
    except ValueError as exc:
        print(str(exc))
        return 1

    payload = json.dumps(proof.to_dict(), indent=2)
    if args.out:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
        print(f"Wrote proof for seq {proof.seq} to {args.out}")
        print(f"  root: {proof.root_sha256}")
        print(f"  path length: {len(proof.path)} of tree size {proof.tree_size}")
    else:
        print(payload)
    return 0


def cmd_anchor(args: argparse.Namespace) -> int:
    """Publish, list, or check the checkpoints that commit the trail externally.

    The chain and the Merkle root are both computed on the audited machine from
    the audited file, so an attacker who can rewrite one can rewrite all of them.
    A checkpoint is the escape: publish `(tree_size, root)` off-host and any later
    edit below that size stops matching. This command produces the commitment;
    where it goes is the operator's trust decision, not ours.
    """
    import json

    from agentmetry.core.audit.trail_anchor import (
        FileAnchorSink,
        anchor_path,
        build_checkpoint,
        coverage_lines,
        read_checkpoints,
        verify_anchors,
    )

    path = Path(args.path)
    if not path.is_file():
        print(f"No such file: {path}")
        return 1
    anchors = Path(args.anchors) if args.anchors else anchor_path(path)

    if args.show:
        checkpoints = read_checkpoints(anchors)
        if not checkpoints:
            print(f"No checkpoints in {anchors}")
            return 0
        print(f"{len(checkpoints)} checkpoint(s) in {anchors}")
        for cp in checkpoints:
            print(f"  {cp.timestamp}  size {cp.tree_size:>7}  root {cp.root_sha256[:16]}…")
        return 0

    if args.verify:
        coverage = verify_anchors(path, anchors)
        for line in coverage_lines(coverage):
            print(line.strip())
        return 0 if coverage.ok else 1

    try:
        checkpoint = build_checkpoint(path, host_id=args.host_id or "")
    except ValueError as exc:
        print(str(exc))
        return 1

    # --print emits without recording. The point is to hand the statement to a
    # sink we do not implement (a timestamp authority, a git commit, a log)
    # without also implying it was anchored here.
    if args.print_only:
        print(checkpoint.statement() if not args.json else json.dumps(checkpoint.to_dict(), indent=2))
        return 0

    try:
        receipt = FileAnchorSink(anchors).publish(checkpoint)
    except (ValueError, OSError) as exc:
        print(f"FAILED — {exc}")
        return 1

    print(f"Anchored {checkpoint.tree_size} record(s) at root {checkpoint.root_sha256}")
    print(f"  checkpoint: {receipt.ref} in {anchors}")
    print(f"  statement: {checkpoint.statement()}")
    # Phrased as a condition, not an assertion. With --anchors the log may
    # already be in a working copy of a protected remote, and telling an
    # operator who has done the work that they have not is how a correct
    # warning teaches people to ignore warnings.
    print(
        "  Until a copy of this log lives where this machine cannot write it, "
        "the commitment can be rewritten along with the trail."
    )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    import json

    path = Path(args.path)
    if not path.exists():
        print(f"No such file: {path}")
        return 1

    if getattr(args, "trail", False):
        from agentmetry.core.audit.trail_chain import verify_trail_file

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

            from agentmetry.core.audit.trail_merkle import merkle_root

            root, size = merkle_root(path)
            if size:
                # The head proves the file is intact end to end. The root is
                # what lets a single event be proved later without handing over
                # the file, so it is the more useful of the two to publish.
                print(f"  merkle root: {root}")
                print(f"  tree size: {size} (rfc6962-sha256)")

            # Everything above was computed from the file being checked, which is
            # the file an attacker with host access would have rewritten. Anchor
            # coverage is the only part of this output that can contradict it, so
            # it prints even when there are no anchors — an operator who never
            # sees the sentence never learns the guarantee has a ceiling.
            from agentmetry.core.audit.trail_anchor import coverage_lines, verify_anchors

            # --anchors is how this check becomes worth running. Against the
            # anchor log sitting next to the trail, an attacker who rewrote one
            # rewrote the other. Pointed at a copy they could not reach, the
            # same comparison is the only thing here they cannot forge.
            coverage = verify_anchors(
                path, Path(args.anchors) if getattr(args, "anchors", None) else None,
                local_only=not getattr(args, "anchors", None),
            )
            for line in coverage_lines(coverage):
                print(line)
            if not coverage.ok:
                # The chain printed OK several lines ago and it was telling the
                # truth: the file is internally consistent, because whoever
                # rewrote it made it so. Leaving that as the last word would let
                # a skimmer take the wrong verdict away, so restate it.
                print(
                    "FAILED — the chain is internally consistent but contradicts a "
                    "published anchor. The file was rewritten."
                )
                return 1
            return 0
        print(f"FAILED — {result.message}")
        if result.first_bad_line:
            print(f"  first bad line: {result.first_bad_line}")
        return 1

    from agentmetry.core.audit.evidence_pack import verify_evidence_pack

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
    from agentmetry.core.audit.replay import format_timeline
    from agentmetry.core.bus.outbox import get_outbox

    thread_id = args.thread_id.strip()
    if not thread_id:
        print("thread_id is required")
        return 1
    rows = get_outbox().read_by_thread_id(thread_id)
    print(format_timeline(rows, thread_id=thread_id))
    return 0 if rows else 1


def cmd_dogfood(args: argparse.Namespace) -> int:
    """Score the dogfood period, or start the clock.

    The beta gate is four consecutive green weeks. It went unstarted for weeks
    because checking a week meant a twenty-minute manual pass, so it never got
    checked. This makes the question cheap enough to actually ask.
    """
    sys.path.insert(0, str(_ORCH_ROOT))
    from agentmetry.core.audit.dogfood import assess, read_marker, render, start_clock

    if getattr(args, "start", False):
        existing = read_marker()
        if existing and not getattr(args, "restart", False):
            print(f"Clock already started {existing['started_utc']}. "
                  "Use --restart to reset it, which discards the current run.")
            return 1
        from agentmetry.core.config import settings

        marker = start_clock(operator=settings.operator_id)
        print(f"Dogfood clock started {marker['started_utc']}.")
        print("Check progress any time with: agentmetry dogfood")
        return 0

    report = assess()
    print(render(report))
    # Exit non-zero only when a *finished* week failed, so this can be run as a
    # weekly check without crying wolf on day one for the crime of not yet
    # having four weeks of history.
    return 1 if any(w.complete and not w.green for w in report.weeks) else 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    """Replay the recorded detection corpus and score the rules.

    Exists so the product's central claim is checkable rather than asserted.
    Anyone can clone this repo and run it: which rules fired on which recorded
    sessions, and how many times they fired on benign ones. A false-positive
    count you publish is worth more than a detection count you assert.
    """
    sys.path.insert(0, str(_ORCH_ROOT))
    from agentmetry.core.audit.detection.benchmark import render_report, run_benchmark

    report = run_benchmark(getattr(args, "corpus", None))
    print(render_report(report))
    return 0 if report.passed else 1


def cmd_doctor(args: argparse.Namespace) -> int:
    """SIEM preflight: manifests, trail chain, orchestrator health, hooks."""
    sys.path.insert(0, str(_ORCH_ROOT))
    from agentmetry.core.diagnostics.doctor import format_report, run_doctor

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
    serve = sub.add_parser(
        "serve",
        help="run the orchestrator in the foreground (what autostart registers)",
    )
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
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
    sub.add_parser(
        "install",
        help="keep the recorder running: at-logon start plus restart on failure",
    )
    sub.add_parser("uninstall", help="remove the autostart registration")
    export = sub.add_parser("export", help="export audit artifacts")
    export.add_argument(
        "--evidence", action="store_true",
        help="build EU AI Act-oriented evidence pack (JSON)",
    )
    export.add_argument(
        "--compliance-digest", dest="compliance_digest", action="store_true",
        help="periodic governance summary for control review (Markdown)",
    )
    export.add_argument(
        "--json", action="store_true",
        help="with --compliance-digest: emit JSON instead of Markdown",
    )
    export.add_argument("--from", dest="date_from", metavar="DATE", required=False)
    export.add_argument("--to", dest="date_to", metavar="DATE", required=False)
    export.add_argument("-o", "--output", default=None, help="output path (default: vault/30-Archive/exports/)")
    import_agt = sub.add_parser(
        "import-agt",
        help="ingest a Microsoft Agent Governance Toolkit audit file into the trail",
    )
    import_agt.add_argument("path", help="AGT FileAuditSink JSONL")
    import_agt.add_argument(
        "--key", default=None,
        help="HMAC secret key, to verify signatures as well as hashes "
             "(or AGENTMETRY_AGT_HMAC_KEY)",
    )
    import_agt.add_argument("--host-id", dest="host_id", default="", help="host to attribute events to")
    import_agt.add_argument(
        "--dry-run", dest="dry_run", action="store_true",
        help="verify and show what would fire, without writing to the trail",
    )
    prove = sub.add_parser(
        "prove",
        help="Merkle inclusion proof for one trail record (prove an event without the file)",
    )
    prove.add_argument("path", help="JSONL trail file")
    prove.add_argument("--seq", type=int, default=None, help="record sequence number to prove")
    prove.add_argument("-o", "--out", default=None, help="write the proof JSON here")
    prove.add_argument("--check", metavar="PROOF", default=None, help="verify a proof file")
    prove.add_argument(
        "--root", default=None,
        help="with --check: the root you recorded elsewhere. Without it a trail vouches for itself.",
    )
    prove.add_argument(
        "--record-root", dest="record_root", action="store_true",
        help="recompute the root and store it in the chain sidecar",
    )
    anchor = sub.add_parser(
        "anchor",
        help="publish a checkpoint committing the trail somewhere the host cannot rewrite",
    )
    anchor.add_argument("path", help="JSONL trail file")
    anchor.add_argument(
        "--anchors", default=None,
        help="anchor log to append to (default: <trail>.anchors.jsonl)",
    )
    anchor.add_argument(
        "--print", dest="print_only", action="store_true",
        help="print the checkpoint statement without recording it, to hand to an external sink",
    )
    anchor.add_argument("--json", action="store_true", help="with --print: emit JSON, not one line")
    anchor.add_argument("--show", action="store_true", help="list recorded checkpoints")
    anchor.add_argument(
        "--verify", action="store_true",
        help="recompute each checkpoint's root from the trail and compare",
    )
    anchor.add_argument("--host-id", dest="host_id", default="", help="identity to stamp on the checkpoint")
    verify = sub.add_parser("verify", help="verify evidence pack or JSONL trail chain")
    verify.add_argument(
        "path",
        help="evidence JSON file, or JSONL trail with --trail",
    )
    verify.add_argument(
        "--trail",
        action="store_true",
        help="verify the hash chain on an audit JSONL file and report anchor coverage",
    )
    verify.add_argument(
        "--anchors",
        default=None,
        help="with --trail: check against this anchor log instead of the one beside "
             "the trail. Point it at an off-host copy; a local one can be rewritten "
             "by whoever rewrote the trail.",
    )
    doctor = sub.add_parser(
        "doctor", help="SIEM preflight (manifests, trail chain, health, hooks)"
    )
    doctor.add_argument(
        "--fix",
        action="store_true",
        help="rewrite drivers.json to portable {PYTHON}/{VAULT_PATH} tokens",
    )
    benchmark = sub.add_parser(
        "benchmark",
        help="replay the recorded detection corpus and score the rules",
    )
    benchmark.add_argument(
        "--corpus",
        type=Path,
        default=None,
        help="corpus directory (default: the corpus shipped inside the package)",
    )
    dogfood = sub.add_parser(
        "dogfood", help="score the four-week dogfood gate, or start the clock"
    )
    dogfood.add_argument("--start", action="store_true", help="start the clock today")
    dogfood.add_argument(
        "--restart", action="store_true", help="with --start, discard the current run"
    )
    replay = sub.add_parser("replay", help="ASCII timeline of audit events for one run")
    replay.add_argument("thread_id", help="correlation_id / session id to replay from audit trail")

    args = parser.parse_args(argv)
    handlers = {
        "start": cmd_start,
        "serve": cmd_serve,
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
        "prove": cmd_prove,
        "anchor": cmd_anchor,
        "import-agt": cmd_import_agt,
        "doctor": cmd_doctor,
        "benchmark": cmd_benchmark,
        "dogfood": cmd_dogfood,
        "replay": cmd_replay,
    }
    return handlers[args.command](args)
