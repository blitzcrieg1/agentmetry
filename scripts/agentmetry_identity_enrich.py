#!/usr/bin/env python3
"""Classify Agentmetry JSONL records by email domain and licence context.

Answers one question: is this agent session running under a personal identity or
a work one? Two independent signals, kept separate on purpose because they
disagree in the interesting cases.

  email_category   what the identifier looks like
                   PERSONAL_EMAIL / DISPOSABLE_EMAIL / OTHER_EMAIL / NO_EMAIL_FOUND
  license_context  which tenant the session ran in
                   CORPORATE_APPROVED / OTHER_ORG_SHADOW / LIKELY_PERSONAL_NO_ORG

A work address inside an unapproved org is shadow IT. A personal address inside
the approved org is usually a local install nobody configured. Collapsing them
into one verdict loses the distinction worth acting on.

There is deliberately no allowlist of corporate domains. Only consumer mail is
named, and everything unrecognised falls to `OTHER_EMAIL`. An allowlist has to
be right to be safe: miss an acquisition, a contractor domain or a regional
office and its traffic reads as untrusted, so the list decays into noise and
then into being ignored. Naming only the consumer providers inverts that. A
domain nobody has classified yet shows up as `OTHER_EMAIL`, which is an honest
"not sure", and the list only grows when a real consumer provider is missing.

THE TRAIL IS HASH-CHAINED. Every record is

    {"trail": {"seq": N, "prev_sha256": ..., "record_sha256": ...}, "event": {...}}

and `record_sha256 = sha256(prev_sha256 + "\\n" + canonical_event_json(event))`,
see `core/audit/trail_chain.py`. Adding a field inside `event` therefore breaks
`agentmetry verify` for that record and every record after it. This script never
touches `event` or `trail`. Enrichment goes in a sibling `enrichment` object,
and the two classifications are mirrored at top level so a SIEM can map them as
plain fields.

A note on where identity lives. The canonical event has no `user.id` and no
`organization.id`. Those are built by the ECS adapter, which sets `user.id` from
`actor.id` and `organization.id` from `fleet_id`. `fleet_id` is a value the
operator sets, not an upstream tenant id, so an allowlist of org ids only means
something if the fleet id is provisioned to match. The field paths below are
ordered to work on both shapes.

PII: the raw identifier is never printed and never added as a new field. What is
stored is the domain, which is what you query on, plus a salted SHA-256 of the
address so one person can be correlated across records without the address
itself. Set a salt, or the hash is a dictionary lookup away from the address.
`--show-emails` opts into extra log output and still never prints an address.

Usage:
    python scripts/agentmetry_identity_enrich.py --input-dir apps/orchestrator/data --follow
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import logging
import os
import re
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Sequence

LOG = logging.getLogger("identity-enrich")

# Deliberately not an RFC 5322 parser. This decides whether a string looks
# enough like an address to pull a domain out of, and nothing more.
_EMAIL = re.compile(
    r"(?P<local>[A-Za-z0-9._%+\-]+)@(?P<domain>[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)+)"
)

# Consumer mail. Extend by config rather than by editing this.
DEFAULT_PERSONAL_DOMAINS: tuple[str, ...] = (
    "gmail.com",
    "googlemail.com",
    "hotmail.com",
    "hotmail.co.uk",
    "hotmail.fr",
    "outlook.com",
    "live.com",
    "msn.com",
    "yahoo.com",
    "yahoo.co.uk",
    "ymail.com",
    "aol.com",
    "icloud.com",
    "me.com",
    "mac.com",
    "proton.me",
    "protonmail.com",
    "pm.me",
    "gmx.com",
    "gmx.de",
    "gmx.net",
    "web.de",
    "mail.com",
    "mail.ru",
    "yandex.com",
    "yandex.ru",
    "zoho.com",
    "tutanota.com",
    "tuta.io",
    "fastmail.com",
    "hey.com",
    "qq.com",
    "163.com",
    "126.com",
    "naver.com",
    "seznam.cz",
    "free.fr",
    "orange.fr",
    "libero.it",
    "t-online.de",
)

# Throwaway providers. A separate category because "personal" and "deliberately
# untraceable" are different findings and deserve different alerts.
DEFAULT_DISPOSABLE_DOMAINS: tuple[str, ...] = (
    "mailinator.com",
    "guerrillamail.com",
    "10minutemail.com",
    "yopmail.com",
    "temp-mail.org",
    "trashmail.com",
    "sharklasers.com",
    "dispostable.com",
    "getnada.com",
    "maildrop.cc",
)

# Providers that ignore dots and +tags in the local part, so one account wears
# many addresses. Folded before hashing or per-person correlation misses.
_DOT_FOLDING_DOMAINS = {"gmail.com", "googlemail.com"}


@dataclass
class Config:
    """Everything tunable. Load from JSON with `Config.load`."""

    # Where to look for the identifier, in order, first hit wins. Dotted paths.
    # `user.id` is the documented default and the field the ECS adapter emits.
    # The rest are where an identity actually lives in a canonical event.
    email_fields: tuple[str, ...] = (
        "user.id",
        "event.actor.id",
        "event.initiator.operator_id",
        "actor.id",
        "initiator.operator_id",
        "principal.user.userid",
    )
    org_fields: tuple[str, ...] = (
        "organization.id",
        "event.fleet_id",
        "fleet_id",
    )
    personal_domains: tuple[str, ...] = DEFAULT_PERSONAL_DOMAINS
    disposable_domains: tuple[str, ...] = DEFAULT_DISPOSABLE_DOMAINS
    org_allowlist: tuple[str, ...] = ()
    # Salt the address hash. Unsalted, a SHA-256 of an email is reversible for
    # any address somebody can enumerate, which is most work addresses.
    hash_salt: str = ""
    # Treat mail.gmail.com as gmail.com. Off means only an exact match counts.
    match_subdomains: bool = True
    classify_disposable: bool = True

    @classmethod
    def load(cls, path: Path | None) -> Config:
        cfg = cls()
        if path is None:
            return cfg
        raw = json.loads(path.read_text(encoding="utf-8"))
        known = set(cls.__dataclass_fields__)
        unknown = set(raw) - known
        if unknown:
            # Loud, because a typo in a config key silently means "no allowlist"
            # and then every session reads as shadow IT.
            raise ValueError(f"unknown config key(s): {sorted(unknown)}")
        for key, value in raw.items():
            setattr(cfg, key, tuple(value) if isinstance(value, list) else value)
        return cfg

    def normalised(self) -> Config:
        self.personal_domains = _clean_domains(self.personal_domains)
        self.disposable_domains = _clean_domains(self.disposable_domains)
        self.org_allowlist = tuple(str(o).strip() for o in self.org_allowlist if str(o).strip())
        return self


def _clean_domains(values: Sequence[str]) -> tuple[str, ...]:
    """Lowercase, strip, and tolerate a leading `@` in a config file."""
    return tuple(str(v).strip().lower().lstrip("@") for v in values if str(v).strip())


def _get_path(record: Any, dotted: str) -> Any:
    """Walk a dotted path. Tolerates a missing branch and a non-dict midway."""
    node = record
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
        if node is None:
            return None
    return node


def _first_present(record: dict[str, Any], paths: Sequence[str]) -> tuple[str, str] | None:
    """(path, value) for the first path holding a non-empty scalar."""
    for path in paths:
        value = _get_path(record, path)
        if value is None or isinstance(value, (dict, list)):
            continue
        text = str(value).strip()
        if text:
            return path, text
    return None


def _domain_matches(domain: str, candidates: Sequence[str], subdomains: bool) -> bool:
    """Exact domain, or a subdomain of one. Never a substring.

    `"gmail.com" in value` would classify `contractor@not-gmail.com.example.net`
    as personal, which is the whole trick. Match on the parsed domain instead.
    """
    for candidate in candidates:
        if domain == candidate:
            return True
        if subdomains and domain.endswith("." + candidate):
            return True
    return False


@dataclass
class EmailVerdict:
    category: str
    domain: str | None = None
    identifier_field: str | None = None
    address_sha256: str | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"email_category": self.category}
        if self.domain:
            out["email_domain"] = self.domain
        if self.identifier_field:
            out["identifier_field"] = self.identifier_field
        if self.address_sha256:
            out["address_sha256"] = self.address_sha256
        if self.notes:
            out["notes"] = self.notes
        return out


def fold_address(local: str, domain: str) -> str:
    """One account, one string. Subaddressing and dots folded where they are ignored."""
    folded = local.split("+", 1)[0]
    if domain in _DOT_FOLDING_DOMAINS:
        folded = folded.replace(".", "")
        domain = "gmail.com"
    return f"{folded}@{domain}"


def classify_email(record: dict[str, Any], cfg: Config) -> EmailVerdict:
    found = _first_present(record, cfg.email_fields)
    if found is None:
        return EmailVerdict("NO_EMAIL_FOUND")
    path, value = found

    match = _EMAIL.search(value)
    if match is None:
        # `user123`, `local`, a hostname. Not an address, and saying so plainly
        # is more useful than guessing at one.
        return EmailVerdict("NO_EMAIL_FOUND", identifier_field=path)

    domain = match.group("domain").lower().rstrip(".")
    local = match.group("local").lower()
    notes: list[str] = ["subaddressed"] if "+" in local else []
    digest = hashlib.sha256(
        f"{cfg.hash_salt}\n{fold_address(local, domain)}".encode("utf-8")
    ).hexdigest()

    if cfg.classify_disposable and _domain_matches(
        domain, cfg.disposable_domains, cfg.match_subdomains
    ):
        category = "DISPOSABLE_EMAIL"
    elif _domain_matches(domain, cfg.personal_domains, cfg.match_subdomains):
        category = "PERSONAL_EMAIL"
    else:
        category = "OTHER_EMAIL"

    return EmailVerdict(category, domain, path, digest, notes)


def classify_license(record: dict[str, Any], cfg: Config) -> dict[str, Any]:
    found = _first_present(record, cfg.org_fields)
    if found is None:
        return {"license_context": "LIKELY_PERSONAL_NO_ORG"}
    path, org_id = found
    context = "CORPORATE_APPROVED" if org_id in cfg.org_allowlist else "OTHER_ORG_SHADOW"
    return {"license_context": context, "organization_id": org_id, "organization_field": path}


def enrich(record: dict[str, Any], cfg: Config) -> dict[str, Any]:
    """Return a NEW record. `trail` and `event` are passed through untouched."""
    enrichment = {
        "schema": "identity-enrich/1",
        **classify_email(record, cfg).as_dict(),
        **classify_license(record, cfg),
    }
    out = dict(record)
    out["enrichment"] = enrichment
    # Mirrored at top level so a SIEM parser can map two flat fields without
    # having to know this object exists.
    out["email_category"] = enrichment["email_category"]
    out["license_context"] = enrichment["license_context"]
    return out


@dataclass
class Cursor:
    offset: int = 0
    inode: int | None = None
    size: int = 0


class Tailer:
    """Follow every matching file in a directory, surviving rotation.

    Rotation is an inode change, or the file shrinking, which is what truncate
    in place looks like. Either resets the cursor to 0 rather than seeking past
    the end of a fresh file and going quiet for the rest of the day.
    """

    def __init__(self, directory: Path, pattern: str, state_path: Path | None):
        self.directory = directory
        self.pattern = pattern
        self.state_path = state_path
        self.cursors: dict[str, Cursor] = {}
        self._load_state()

    def _load_state(self) -> None:
        if not self.state_path or not self.state_path.is_file():
            return
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            LOG.warning("state file unreadable, starting from the current end of each file")
            return
        for name, cur in (raw.get("cursors") or {}).items():
            self.cursors[name] = Cursor(
                offset=int(cur.get("offset", 0)),
                inode=cur.get("inode"),
                size=int(cur.get("size", 0)),
            )

    def save_state(self) -> None:
        if not self.state_path:
            return
        payload = {
            "cursors": {
                name: {"offset": c.offset, "inode": c.inode, "size": c.size}
                for name, c in self.cursors.items()
            }
        }
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp, self.state_path)
        except OSError as exc:
            LOG.warning("could not write state file: %s", exc)

    def _files(self) -> list[Path]:
        try:
            return sorted(
                p
                for p in self.directory.iterdir()
                if p.is_file() and fnmatch.fnmatch(p.name, self.pattern)
            )
        except OSError as exc:
            LOG.warning("cannot list %s: %s", self.directory, exc)
            return []

    def read_new(self, from_start: bool) -> Iterator[tuple[Path, str]]:
        for path in self._files():
            key = str(path)
            try:
                stat = path.stat()
            except OSError:
                continue
            cursor = self.cursors.get(key)
            if cursor is None:
                cursor = Cursor(offset=0 if from_start else stat.st_size)
                self.cursors[key] = cursor
            inode = getattr(stat, "st_ino", None) or None
            rotated = inode is not None and cursor.inode is not None and inode != cursor.inode
            if rotated or stat.st_size < cursor.size:
                LOG.info("%s rotated, rereading from the start", path.name)
                cursor.offset = 0
            cursor.inode = inode
            cursor.size = stat.st_size
            if cursor.offset >= stat.st_size:
                continue
            try:
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    handle.seek(cursor.offset)
                    for line in handle:
                        if not line.endswith("\n"):
                            # A partial write. Leave the cursor before it and
                            # take the whole line on the next pass.
                            break
                        cursor.offset += len(line.encode("utf-8"))
                        stripped = line.strip()
                        if stripped:
                            yield path, stripped
            except OSError as exc:
                LOG.warning("read failed on %s: %s", path, exc)


@dataclass
class Counters:
    read: int = 0
    written: int = 0
    malformed: int = 0

    def line(self) -> str:
        return f"read={self.read} written={self.written} malformed={self.malformed}"


def _open_sink(target: str):
    if target == "-":
        return sys.stdout, False
    return open(target, "a", encoding="utf-8", newline="\n"), True


def _config_from_args(args: argparse.Namespace) -> Config:
    cfg = Config.load(Path(args.config) if args.config else None)
    if args.email_field:
        cfg.email_fields = tuple(args.email_field)
    if args.org_field:
        cfg.org_fields = tuple(args.org_field)
    if args.personal_domain:
        cfg.personal_domains = cfg.personal_domains + tuple(args.personal_domain)
    if args.org_allow:
        cfg.org_allowlist = tuple(args.org_allow)
    if args.salt_env:
        cfg.hash_salt = os.environ.get(args.salt_env, cfg.hash_salt)
    return cfg.normalised()


def run(args: argparse.Namespace) -> int:
    cfg = _config_from_args(args)
    if not cfg.hash_salt:
        LOG.warning(
            "no hash salt set, so address_sha256 is guessable for any address somebody "
            "can enumerate. Set one via --salt-env or the config file."
        )
    if not cfg.org_allowlist:
        LOG.warning("org allowlist is empty, so every org will classify as OTHER_ORG_SHADOW")

    directory = Path(args.input_dir)
    if not directory.is_dir():
        LOG.error("not a directory: %s", directory)
        return 2

    tailer = Tailer(directory, args.glob, Path(args.state) if args.state else None)
    sink, close_sink = _open_sink(args.out)
    dead_letter = open(args.dead_letter, "a", encoding="utf-8") if args.dead_letter else None
    counters = Counters()
    stopping = {"now": False}

    def _stop(_signum: Any, _frame: Any) -> None:
        stopping["now"] = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _stop)
        except (ValueError, OSError):
            pass  # not the main thread, or unsupported here

    last_report = time.monotonic()
    try:
        while True:
            saw_any = False
            for path, line in tailer.read_new(args.from_start):
                saw_any = True
                counters.read += 1
                enriched = _enrich_line(line, cfg, path, counters, dead_letter)
                if enriched is None:
                    continue
                sink.write(json.dumps(enriched, ensure_ascii=False) + "\n")
                counters.written += 1
                if args.show_emails:
                    LOG.info(
                        "%s -> %s / %s",
                        enriched["enrichment"].get("identifier_field"),
                        enriched["email_category"],
                        enriched["license_context"],
                    )

            sink.flush()
            if dead_letter:
                dead_letter.flush()
            tailer.save_state()

            if stopping["now"] or not args.follow:
                break
            now = time.monotonic()
            if now - last_report >= args.report_every:
                LOG.info("%s", counters.line())
                last_report = now
            if not saw_any:
                time.sleep(args.poll_interval)
    finally:
        tailer.save_state()
        sink.flush()
        if close_sink:
            sink.close()
        if dead_letter:
            dead_letter.close()

    LOG.info("done: %s", counters.line())
    return 0


def _enrich_line(
    line: str, cfg: Config, path: Path, counters: Counters, dead_letter: Any
) -> dict[str, Any] | None:
    """One line in, one enriched record out, or None and a counted failure.

    A tail that dies on a malformed line stops recording, and a recorder that
    stops is worse than one that skips a record and says so.
    """

    def _reject(reason: str) -> None:
        counters.malformed += 1
        LOG.debug("skipping a line from %s: %s", path.name, reason)
        if dead_letter:
            dead_letter.write(line + "\n")

    try:
        record = json.loads(line)
    except json.JSONDecodeError as exc:
        _reject(f"malformed JSON: {exc}")
        return None
    if not isinstance(record, dict):
        _reject("top-level value is not an object")
        return None
    try:
        return enrich(record, cfg)
    except Exception as exc:  # noqa: BLE001 - one bad record must not stop the tail
        _reject(f"enrichment failed: {exc}")
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Classify Agentmetry JSONL by email domain and licence context."
    )
    parser.add_argument("--input-dir", required=True, help="directory of JSONL files")
    parser.add_argument("--glob", default="*.jsonl", help="filename pattern (default: *.jsonl)")
    parser.add_argument("--out", default="-", help="output file, or - for stdout (default: -)")
    parser.add_argument("--config", help="JSON config file")
    parser.add_argument(
        "--email-field", action="append", help="dotted path to the identifier, repeatable"
    )
    parser.add_argument(
        "--org-field", action="append", help="dotted path to the organisation id, repeatable"
    )
    parser.add_argument(
        "--personal-domain", action="append", help="extra consumer domain, repeatable"
    )
    parser.add_argument("--org-allow", action="append", help="allowlisted org id, repeatable")
    parser.add_argument(
        "--salt-env",
        default="IDENTITY_ENRICH_SALT",
        help="env var holding the hash salt (default: IDENTITY_ENRICH_SALT)",
    )
    parser.add_argument("--follow", action="store_true", help="keep tailing for new lines")
    parser.add_argument(
        "--from-start", action="store_true", help="read existing content, not just new lines"
    )
    parser.add_argument("--state", help="cursor file, so a restart does not re-emit")
    parser.add_argument("--dead-letter", help="append unparseable lines here")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--report-every", type=float, default=60.0)
    parser.add_argument(
        "--show-emails",
        action="store_true",
        help="log the matched field and verdict per record. Still never logs an address.",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
