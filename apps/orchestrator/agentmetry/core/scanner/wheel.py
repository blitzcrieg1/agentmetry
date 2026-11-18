"""Inspect Python startup declarations in a wheel without installing it."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import struct
import zipfile
import zlib
from dataclasses import asdict, dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any, BinaryIO

from agentmetry.core.scanner.preflight import _linked

MAX_ARCHIVE_BYTES = 128 * 1024**2
MAX_DIRECTORY_BYTES = 4 * 1024**2
MAX_MEMBERS = 4096
MAX_STARTUP_FILES = 128
MAX_STARTUP_BYTES = 64 * 1024
MAX_TOTAL_STARTUP_BYTES = 4 * 1024**2
MAX_PRINTED_LINES = 32
MAX_NOTICES = 64
EOCD = struct.Struct("<4s4H2IH")
EOCD_SIGNATURE = b"PK\x05\x06"
SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}")


class IncompleteWheel(ValueError):
    """A stable report code for a format or limit the scan cannot handle."""


@dataclass(frozen=True)
class StartupFile:
    member: str
    kind: str
    path_entries: int
    direct_imports: int
    indented_imports: int
    entry_points: int
    declaration_lines: list[int]

    @property
    def actionable(self) -> int:
        return self.direct_imports + self.indented_imports + self.entry_points


@dataclass
class WheelReport:
    target: str
    sha256: str | None = None
    hash_check: str = "not_requested"
    files: list[StartupFile] = field(default_factory=list)
    unobserved: list[dict[str, str]] = field(default_factory=list)
    omitted_notices: int = 0

    def note(self, reason: str, member: str | None = None) -> None:
        if len(self.unobserved) == MAX_NOTICES:
            self.omitted_notices += 1
            return
        entry = {"reason": reason}
        if member is not None:
            entry["member"] = member
        self.unobserved.append(entry)

    @property
    def needs_review(self) -> bool:
        return self.hash_check == "mismatch" or any(item.actionable for item in self.files)

    def exit_code(self) -> int:
        if self.unobserved or self.omitted_notices:
            return 2
        return 1 if self.needs_review else 0

    def to_json(self) -> dict[str, Any]:
        return {"mode": "wheel_startup", **asdict(self), "provenance": "not_verified",
                "review_recommended": self.needs_review,
                "coverage": "partial" if self.exit_code() == 2 else "supported_locations_inspected"}

    def lines(self) -> list[str]:
        out = [f"Agentmetry wheel startup check: {json.dumps(self.target)}",
               f"  SHA-256: {self.sha256 or 'unavailable'}",
               f"  Expected hash: {self.hash_check} | Publisher provenance: not verified"]
        for item in self.files:
            counts = (
                f"{item.direct_imports} import lines, {item.indented_imports} indented import lines, "
                f"{item.path_entries} path entries" if item.kind == "pth"
                else f"{item.entry_points} startup entry points"
            )
            markers = ", ".join(map(str, item.declaration_lines))
            where = f" | lines {markers}" if markers else ""
            if item.actionable > len(item.declaration_lines):
                where += f" (+{item.actionable - len(item.declaration_lines)} more)"
            out.append(f"  {json.dumps(item.member)} | {counts}{where}")
        for entry in self.unobserved:
            at = f" {json.dumps(entry['member'])}" if "member" in entry else ""
            out.append(f"  Unobserved:{at} | {entry['reason']}")
        if self.omitted_notices:
            out.append(f"  {self.omitted_notices} additional notices omitted")
        if self.needs_review:
            out.append("  Review the declared startup behavior or the expected hash mismatch.")
        out.append("  This check reads declarations. It does not establish what executes or whether the wheel is trusted.")
        return out


def _directory_size(stream: BinaryIO, size: int) -> int:
    """Bound the central directory before ZipFile indexes it."""
    max_tail = 65_535 + EOCD.size + 20
    stream.seek(max(0, size - max_tail))
    tail = stream.read(max_tail)
    at = tail.rfind(EOCD_SIGNATURE)
    if at < 0 or len(tail) - at < EOCD.size:
        raise IncompleteWheel("invalid_archive")
    _, disk, directory_disk, disk_count, count, byte_count, offset, comment_size = EOCD.unpack_from(tail, at)
    if at + EOCD.size + comment_size != len(tail):
        raise IncompleteWheel("invalid_archive")
    if disk or directory_disk or disk_count != count:
        raise IncompleteWheel("unsupported_archive_layout")
    # Zip64 may override the fields above. Decline it before ZipFile reads a
    # different directory. Ordinary wheels within these limits use classic ZIP.
    if at >= 20 and tail[at - 20:at - 16] == b"PK\x06\x07":
        raise IncompleteWheel("unsupported_archive_layout")
    if count > MAX_MEMBERS or byte_count > MAX_DIRECTORY_BYTES:
        raise IncompleteWheel("directory_limit_reached")
    if offset + byte_count != size - len(tail) + at:
        raise IncompleteWheel("unsupported_archive_layout")
    return count


def _member_parts(info: zipfile.ZipInfo) -> list[str] | None:
    raw = info.orig_filename
    name = raw[:-1] if raw.endswith("/") else raw
    parts = name.split("/")
    if (
        not name or len(name) > 512 or "\\" in name or ":" in name
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
        or any(part in ("", ".", "..") for part in parts)
    ):
        return None
    return parts


def _startup_kind(parts: list[str]) -> str | None:
    if len(parts) != 1 and not (
        len(parts) == 3 and parts[0].endswith(".data") and parts[1] in ("purelib", "platlib")
    ):
        return None
    name = parts[-1]
    if name.startswith("."):
        return None
    for extension in (".pth", ".start"):
        if name.endswith(extension):
            return extension[1:]
    return None


def _read_startup(archive: zipfile.ZipFile, item: zipfile.ZipInfo) -> str:
    if item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        raise IncompleteWheel("unsupported_member_compression")
    if item.flag_bits & 1:
        raise IncompleteWheel("encrypted_startup_member")
    mode = stat.S_IFMT(item.external_attr >> 16) if item.create_system == 3 else 0
    if mode not in (0, stat.S_IFREG):
        raise IncompleteWheel("non_regular_startup_member")
    with archive.open(item) as stream:
        raw = stream.read(item.file_size + 1)
    if len(raw) != item.file_size:
        raise IncompleteWheel("invalid_startup_member_size")
    return raw.decode("utf-8-sig")


def _count_lines(
    text: str, member: str, kind: str, report: WheelReport,
) -> StartupFile:
    paths = direct = indented = entry_points = 0
    marks: list[int] = []
    invalid_entry = False
    for number, line in enumerate(StringIO(text, newline=None), 1):
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            continue
        if kind == "start":
            module, separator, function = trimmed.partition(":")
            if not separator or not all(part.isidentifier() for part in (module + "." + function).split(".")):
                invalid_entry = True
                continue
            entry_points += 1
        elif line.startswith(("import ", "import\t")):
            direct += 1
        elif trimmed.startswith(("import ", "import\t")):
            # CPython 3.15 strips leading space before the prefix check.
            indented += 1
        else:
            paths += 1
            continue
        if len(marks) < MAX_PRINTED_LINES:
            marks.append(number)
    if invalid_entry:
        report.note("unsupported_start_entry", member)
    return StartupFile(member, kind, paths, direct, indented, entry_points, marks)


def _inspect_directory(
    archive: zipfile.ZipFile, count: int, prefix: str, report: WheelReport,
) -> None:
    members = archive.infolist()
    if len(members) != count or len(members) > MAX_MEMBERS:
        report.note("directory_count_mismatch")
        return
    seen: set[str] = set()
    startup: list[tuple[zipfile.ZipInfo, str]] = []
    for item in members:
        parts = _member_parts(item)
        if parts is None:
            report.note("invalid_member_path")
            continue
        if item.filename in seen:
            report.note("duplicate_member_path", item.filename)
            continue
        if item.is_dir():
            continue
        seen.add(item.filename)
        kind = _startup_kind(parts)
        if kind is not None:
            # pip also moves files from noncanonical .data directories.
            if len(parts) == 3 and parts[0] != prefix + ".data":
                report.note("unexpected_wheel_data_directory", item.filename)
            startup.append((item, kind))
    if not all(f"{prefix}.dist-info/{name}" in seen for name in ("METADATA", "WHEEL", "RECORD")):
        report.note("wheel_metadata_missing")
    if len(startup) > MAX_STARTUP_FILES:
        report.note("startup_file_limit_reached")
    remaining = MAX_TOTAL_STARTUP_BYTES
    for item, kind in sorted(startup, key=lambda row: row[0].filename)[:MAX_STARTUP_FILES]:
        if item.file_size > min(MAX_STARTUP_BYTES, remaining):
            report.note("startup_read_limit_reached", item.filename)
            continue
        remaining -= item.file_size
        try:
            text = _read_startup(archive, item)
        except UnicodeDecodeError:
            report.note("unknown_startup_text_encoding", item.filename)
        except IncompleteWheel as exc:
            report.note(str(exc), item.filename)
        except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error, EOFError, ValueError, struct.error):
            report.note("startup_member_unreadable", item.filename)
        else:
            report.files.append(_count_lines(text, item.filename, kind, report))


def inspect_wheel(target: Path, expected_sha256: str | None = None) -> WheelReport:
    report = WheelReport(str(target))
    if expected_sha256 is not None:
        report.hash_check = "unavailable"
        if not SHA256_PATTERN.fullmatch(expected_sha256):
            report.note("invalid_expected_sha256")
            return report
    fields = target.name.removesuffix(".whl").split("-")
    if target.suffix != ".whl" or len(fields) not in (5, 6) or not all(fields):
        report.note("expected_wheel_filename")
        return report
    try:
        info = target.lstat()
        if _linked(info) or not stat.S_ISREG(info.st_mode):
            report.note("expected_regular_wheel")
            return report
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(target, flags), "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or _linked(before):
                report.note("expected_regular_wheel")
                return report
            if before.st_size > MAX_ARCHIVE_BYTES:
                report.note("wheel_size_limit_reached")
                return report
            digest = hashlib.sha256()
            remaining = before.st_size
            while remaining:
                chunk = stream.read(min(remaining, 1024**2))
                if not chunk:
                    report.note("wheel_changed_during_scan")
                    return report
                digest.update(chunk)
                remaining -= len(chunk)
            report.sha256 = digest.hexdigest()
            if expected_sha256 is not None:
                report.hash_check = "match" if expected_sha256.lower() == report.sha256 else "mismatch"
            try:
                count = _directory_size(stream, before.st_size)
                with zipfile.ZipFile(stream) as archive:
                    _inspect_directory(archive, count, "-".join(fields[:2]), report)
            except IncompleteWheel as exc:
                report.note(str(exc))
            except (OSError, RuntimeError, ValueError, zipfile.BadZipFile, zlib.error, EOFError, struct.error):
                report.note("wheel_directory_unreadable")
            after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                report.sha256 = None
                if expected_sha256 is not None:
                    report.hash_check = "unavailable"
                report.files.clear()
                report.note("wheel_changed_during_scan")
    except OSError:
        report.note("wheel_unreadable")
    return report
