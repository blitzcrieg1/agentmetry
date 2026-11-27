"""Plant local DLP decoys with a rollback record written before the target."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import string
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_FILE = HOME / ".agentmetry" / "canary" / "state.json"
MARK = "AGENTMETRY-CANARY"
_ALNUM = string.ascii_letters + string.digits
_MAX_STATE_BYTES = 1024 * 1024
_VALUE_PATTERNS = {
    "env": (re.compile(r"AGENTMETRY-CANARY-[a-zA-Z0-9]{24}"),),
    "aws": (re.compile(r"AKIA[A-Z0-9]{16}"), re.compile(r"[a-zA-Z0-9]{40}")),
}
_HASH = re.compile(r"[a-f0-9]{64}")
_OPEN_FLAGS = (
    getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
)


def _random_value(length: int, alphabet: str = _ALNUM) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _check_path(path: Path) -> os.stat_result | None:
    """Refuse links, nonregular files, and alternate paths to the same file."""
    for parent in path.parents:
        try:
            info = parent.lstat()
        except FileNotFoundError:
            continue
        if _is_link(info):
            raise ValueError("Refusing a linked canary path.")
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if _is_link(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("Canary files must be regular files with one link.")
    return info


@contextmanager
def _open_file(path: Path, *, writing: bool = False, create: bool = False, append: bool = False):
    info = _check_path(path)
    flags = os.O_RDWR if writing else os.O_RDONLY
    if create:
        flags |= os.O_CREAT | os.O_EXCL
    if append:
        flags |= os.O_APPEND
    fd = os.open(path, flags | _OPEN_FLAGS, 0o600)
    with os.fdopen(fd, "r+b" if writing else "rb") as handle:
        current = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or _is_link(current)
            or (not create and (info is None or not os.path.samestat(info, current)))
        ):
            raise ValueError("Canary file changed while opening it.")
        yield handle


def _block(kind: str, slot: int, values: list[str]) -> str:
    if kind == "aws":
        return (
            f"\n[agentmetry-canary-{slot}]\n"
            f"aws_access_key_id = {values[0]}\n"
            f"aws_secret_access_key = {values[1]}\n"
        )
    return f"\n# {MARK}: decoy, never a real credential\nAGENTMETRY_CANARY_{slot}={values[0]}\n"


def _record_slot(record: dict[str, Any]) -> int:
    """Validate serialized fields before using them as a pattern or edit plan."""
    name = record["name"]
    if not isinstance(name, str) or not name.isprintable() or record["rule_id"] != f"canary_{name}":
        raise ValueError("Invalid canary name or rule ID.")
    kind, values = record["kind"], record["values"]
    patterns = _VALUE_PATTERNS[kind]
    if not isinstance(values, list) or len(values) != len(patterns) or not all(
        pattern.fullmatch(value) for pattern, value in zip(patterns, values, strict=True)
    ):
        raise ValueError("Invalid canary value shape.")
    appended = record["appended"].replace("\r\n", "\n")
    slot_pattern = (
        r"\n\[agentmetry-canary-(\d{1,9})\]\n" if kind == "aws" else r"\nAGENTMETRY_CANARY_(\d{1,9})="
    )
    match = re.search(slot_pattern, appended, re.ASCII)
    if match is None or appended != _block(kind, int(match[1]), values):
        raise ValueError("Invalid canary block.")
    slot = int(match[1])
    key = f"agentmetry-canary-{slot}" if kind == "aws" else f"AGENTMETRY_CANARY_{slot}"
    if (
        type(record["existed_before"]) is not bool
        or not record["path"].isprintable()
        or record["where"] != f"{record['path']} [{key}]"
    ):
        raise ValueError("Invalid canary record.")
    datetime.fromisoformat(record["created_at"])
    if "previous_sha256" in record and (
        not _HASH.fullmatch(record["previous_sha256"])
        or type(record["previous_length"]) is not int
        or record["previous_length"] < 0
        or type(record["pending"]) is not bool
    ):
        raise ValueError("Invalid canary rollback plan.")
    return slot


def read_records(path: Path) -> list[dict[str, Any]]:
    """Read generated literal records, including inventory written by 0.17.0."""
    try:
        with _open_file(path) as handle:
            info = os.fstat(handle.fileno())
            if os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o022):
                raise ValueError("Canary state is writable by another account.")
            raw = handle.read(_MAX_STATE_BYTES + 1)
    except FileNotFoundError:
        return []
    if len(raw) > _MAX_STATE_BYTES:
        raise ValueError("Canary state is too large.")
    try:
        records = json.loads(raw)["decoys"]
        if not isinstance(records, list):
            raise ValueError("Invalid canary inventory.")
        names = set()
        for record in records:
            _record_slot(record)
            if record["name"] in names:
                raise ValueError("Duplicate canary name.")
            names.add(record["name"])
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
        raise ValueError("Cannot load canary state. Keep it for recovery.") from None
    return records


def _sync_directory(path: Path) -> None:
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _save_records(records: list[dict[str, Any]]) -> None:
    payload = (json.dumps({"decoys": records}, indent=2) + "\n").encode("utf-8")
    if len(payload) > _MAX_STATE_BYTES:
        raise ValueError("Canary state is too large.")
    _check_path(STATE_FILE)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=STATE_FILE.parent, delete=False) as stream:
            temp = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, STATE_FILE)
        _sync_directory(STATE_FILE.parent)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


@contextmanager
def _edit_records():
    """Serialize canary commands and refuse changes if the file lock fails."""
    from agentmetry.core.audit.trail_chain import _acquire, _release

    lock = STATE_FILE.with_suffix(".lock")
    try:
        _check_path(lock)
        lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            with _open_file(lock, writing=True, create=True):
                pass
        except FileExistsError:
            pass
        with _open_file(lock, writing=True) as handle:
            if not _acquire(handle):
                raise ValueError("Canary inventory is busy or cannot be locked.")
            try:
                yield read_records(STATE_FILE)
            finally:
                _release(handle)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    except OSError:
        raise SystemExit(
            "Canary operation could not finish. Check the recovery inventory with agentmetry canary list."
        ) from None


def _canonical(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def _checked_target(record: dict[str, Any]) -> Path:
    path = Path(record["path"])
    if not path.is_absolute() or path != _canonical(path):
        raise ValueError("Canary target has no canonical absolute path. Recover it manually.")
    if record["kind"] == "aws" and path != _canonical(HOME / ".aws" / "credentials"):
        raise ValueError("Canary AWS target is outside the expected profile.")
    if record["kind"] == "env" and path.name != ".env":
        raise ValueError("Canary project target must be a .env file.")
    _check_path(path)
    return path


def _snapshot(path: Path) -> bytes | None:
    try:
        with _open_file(path) as handle:
            return handle.read()
    except FileNotFoundError:
        return None


def _write_append(path: Path, previous: bytes | None, block: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _open_file(path, writing=True, create=previous is None, append=True) as handle:
        if previous is not None and handle.read() != previous:
            raise ValueError("Canary target changed before planting.")
        handle.write(block)
        handle.flush()
        os.fsync(handle.fileno())
    if previous is None:
        _sync_directory(path.parent)


def _record_prefix(record: dict[str, Any], current: bytes) -> bytes:
    """Find the original bytes after an interrupted append or removal."""
    block = record["appended"].encode("ascii")
    if "previous_sha256" not in record:
        # 0.17.0 stored logical newlines and translated them when writing.
        for ending in (block, block.replace(b"\n", b"\r\n")):
            if current.endswith(ending):
                return current[:-len(ending)]
    else:
        length = record["previous_length"]
        prefix, suffix = current[:length], current[length:]
        matches = suffix == block or not suffix or record["pending"] and block.startswith(suffix)
        if matches and len(prefix) == length and hashlib.sha256(prefix).hexdigest() == record["previous_sha256"]:
            return prefix
    raise ValueError("Canary target changed. Leave it intact and remove the decoy block manually.")


def _restore(path: Path, record: dict[str, Any]) -> None:
    current = _snapshot(path)
    if current is None:
        return
    prefix = _record_prefix(record, current)
    # Without decoy bytes, an empty file could have been created by another writer.
    delete_created_file = bool(current) and not record["existed_before"] and not prefix
    if current == prefix and not delete_created_file:
        return
    with _open_file(path, writing=True) as handle:
        checked = os.fstat(handle.fileno())
        if handle.read() != current or not _same_version(checked, os.fstat(handle.fileno())):
            raise ValueError("Canary target changed before removal.")
        if not delete_created_file:
            handle.truncate(len(prefix))
            handle.flush()
            os.fsync(handle.fileno())
            return
    # Windows cannot unlink an open file. Confirm that the name still identifies it.
    latest = _check_path(path)
    if latest is None or not _same_version(checked, latest):
        raise ValueError("Canary target changed before removal.")
    path.unlink()
    _sync_directory(path.parent)


def _same_version(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        os.path.samestat(before, after)
        and before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns
    )


def plant(kind: str, scope: str, project: Path | None = None, name: str = "") -> dict[str, Any]:
    """Persist recovery metadata before modifying the selected credential file."""
    if kind == "aws" and scope == "home":
        target = _canonical(HOME / ".aws" / "credentials")
    elif kind == "env" and project is not None and _canonical(project).is_dir():
        target = _canonical(project) / ".env"
    else:
        raise SystemExit("Choose an AWS home profile or an existing project directory for an env decoy.")

    from agentmetry.core.audit.dlp.loader import supports_canaries
    from agentmetry.core.audit.policy_settings import policy_settings

    if not supports_canaries(policy_settings().dlp_rules_path):
        raise SystemExit("Canaries require the bundled DLP manifest and an unmanaged DLP policy.")
    with _edit_records() as records:
        used = {_record_slot(record) for record in records}
        slot = next(index for index in range(1, len(records) + 2) if index not in used)
        decoy_name = name or f"{kind}-{scope}-{slot}"
        if not decoy_name.isprintable() or any(r["name"] == decoy_name for r in records):
            raise ValueError("Canary name must be unique and contain only printable characters.")
        previous = _snapshot(target)
        original = previous or b""
        if kind == "aws":
            key = f"agentmetry-canary-{slot}"
            duplicate = rf"^\s*\[\s*{key}\s*\]"
            values = ["AKIA" + _random_value(16, string.ascii_uppercase + string.digits), _random_value(40)]
        else:
            key = f"AGENTMETRY_CANARY_{slot}"
            duplicate = rf"""^\s*(?:export[ \t]+)?['"]?{key}['"]?\s*="""
            values = [f"{MARK}-{_random_value(24)}"]
        if re.search(duplicate.encode("ascii"), original.removeprefix(b"\xef\xbb\xbf"), re.MULTILINE):
            raise ValueError("A credential with the generated canary name already exists.")
        text = _block(kind, slot, values)
        if b"\r\n" in original or not original and os.linesep == "\r\n":
            text = text.replace("\n", "\r\n")
        record = {
            "name": decoy_name,
            "kind": kind,
            "scope": scope,
            "where": f"{target} [{key}]",
            "path": str(target),
            "values": values,
            "rule_id": f"canary_{decoy_name}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "appended": text,
            "existed_before": previous is not None,
            "previous_length": len(original),
            "previous_sha256": hashlib.sha256(original).hexdigest(),
            "pending": True,
        }
        _record_slot(record)
        records.append(record)
        _save_records(records)
        _write_append(target, previous, text.encode("ascii"))
        record["pending"] = False
        _save_records(records)
        return record


def list_planted() -> list[dict[str, Any]]:
    try:
        return read_records(STATE_FILE)
    except (OSError, ValueError):
        raise SystemExit("Cannot read canary inventory. Keep it for recovery.") from None


def _pop_record(name: str, *, restore: bool) -> dict[str, Any]:
    with _edit_records() as records:
        for index, record in enumerate(records):
            if record["name"] != name:
                continue
            if restore:
                _restore(_checked_target(record), record)
            records.pop(index)
            _save_records(records)
            return record
        raise SystemExit(f"no decoy named {name!r}")


def remove(name: str) -> dict[str, Any]:
    """Remove the planted bytes while preserving any original data."""
    return _pop_record(name, restore=True)


def forget(name: str) -> dict[str, Any]:
    """Drop bookkeeping only after an operator has handled the target."""
    return _pop_record(name, restore=False)
