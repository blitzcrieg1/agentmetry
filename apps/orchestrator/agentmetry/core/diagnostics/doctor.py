"""Agentmetry doctor - SIEM preflight (manifests, trail chain, hooks, health).

Vault/drivers checks are optional-runtime extras and can only warn.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from agentmetry.core.config import settings
from agentmetry.core.diagnostics.driver_paths import (
    default_python,
    entry_has_absolute_paths,
    normalize_drivers_file,
    orchestrator_root,
    resolve_driver_entry,
)
from agentmetry.core.drivers.spec import DriverSpec

Severity = Literal["ok", "warn", "fail"]


@dataclass
class Finding:
    severity: Severity
    code: str
    message: str


@dataclass
class DoctorReport:
    findings: list[Finding] = field(default_factory=list)

    def ok(self, code: str, message: str) -> None:
        self.findings.append(Finding("ok", code, message))

    def warn(self, code: str, message: str) -> None:
        self.findings.append(Finding("warn", code, message))

    def fail(self, code: str, message: str) -> None:
        self.findings.append(Finding("fail", code, message))

    @property
    def exit_code(self) -> int:
        if any(f.severity == "fail" for f in self.findings):
            return 1
        return 0


def _check_health_endpoint(report: DoctorReport) -> None:
    """Is the orchestrator up? A recorder that is not running records nothing."""
    import urllib.request

    url = settings.audit_ingest_url.rstrip("/") + "/api/v1/health"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            if resp.status == 200:
                report.ok("orchestrator_up", f"Orchestrator responding at {url}")
                return
            report.warn("orchestrator_up", f"Orchestrator returned HTTP {resp.status} at {url}")
    except Exception:
        report.warn(
            "orchestrator_up",
            f"Orchestrator not reachable at {url} - start it with `agentmetry start`",
        )


#: Bind addresses that keep the API on this machine.
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1", ""})


def _check_exposure(report: DoctorReport) -> None:
    """Is the API reachable by anyone who cannot already read the trail?

    `require_api_key` is deliberately a no-op when no key is set, which is the
    right default for a recorder bound to loopback. Combined with a non-loopback
    bind it is not a weak default, it is an open door: the ingest route accepts
    forged events into the tamper-evident trail, the export route hands over the
    whole evidence pack, and the disposition route lets a stranger close a
    finding as accepted risk - a decision that is then written into the trail as
    a legitimate human action.

    The enterprise MSI reached exactly that combination by setting
    AGENTMETRY_HOST=0.0.0.0 without setting a key, so this check fails rather
    than warns. Any future packaging that repeats the mistake trips it here.
    """
    if not settings.fleet_id.strip():
        report.warn(
            "fleet_id",
            "AGENTMETRY_FLEET_ID not set - fleet SIEM queries cannot scope to "
            "this org or business unit",
        )
    else:
        report.ok("fleet_id", f"Fleet id: {settings.fleet_id.strip()}")

    host = os.environ.get("AGENTMETRY_HOST", "127.0.0.1").strip()
    has_key = bool(settings.api_key.strip())

    if host in _LOOPBACK:
        detail = "loopback only" if has_key else "loopback only (no API key needed)"
        report.ok("exposure", f"API bound to {host or '127.0.0.1'} - {detail}")
        return

    if has_key:
        report.ok("exposure", f"API bound to {host} with an API key set")
        return

    report.fail(
        "exposure",
        f"API bound to {host} with NO API key. Anyone who can reach this host "
        "can read the trail, export evidence, inject events, and close "
        "detections. Set AGENTMETRY_API_KEY, or bind 127.0.0.1.",
    )


def _check_hooks_installed(report: DoctorReport) -> None:
    """Detect global hook installs. Absence is a warn: capture is opt-in per IDE."""
    targets = {
        "cursor": Path.home() / ".cursor" / "hooks.json",
        "claude": Path.home() / ".claude" / "settings.json",
    }
    installed: list[str] = []
    missing: list[str] = []
    for name, path in targets.items():
        try:
            if path.is_file() and "agentmetry_ingest" in path.read_text(encoding="utf-8"):
                installed.append(name)
            else:
                missing.append(name)
        except OSError:
            missing.append(name)
    if installed:
        report.ok("hooks", f"Hooks installed: {', '.join(installed)}")
    if missing:
        report.warn(
            "hooks",
            f"No hooks detected for: {', '.join(missing)} "
            "(installed at orchestrator boot, or run scripts/install_*_hooks.ps1)",
        )


def _check_trail(report: DoctorReport) -> None:
    trail = Path(settings.audit_export_path)
    if not trail.is_file():
        report.warn(
            "trail",
            f"No trail yet at {trail.name} - run `python scripts/demo.py` or capture a session",
        )
        return
    from agentmetry.core.audit.trail_chain import verify_trail_file

    result = verify_trail_file(trail)
    if result.ok:
        report.ok("trail", f"Trail chain verified: {result.message}")
    else:
        report.fail("trail", f"Trail chain BROKEN: {result.message}")
        return

    _check_anchors(report, trail)


def _check_anchors(report: DoctorReport, trail: Path) -> None:
    """Report anchor coverage, and stay quiet when there is none.

    Silence is the deliberate part. An unanchored trail is a legitimate
    configuration -- it is what every fresh install has, and the chain still
    does real work -- so a daily WARN saying so would be a nag about a choice
    rather than a report of a problem, and nags are what teach an operator to
    stop reading this output.

    The one case that does warrant a warning is a configured anchor log that is
    not there. That is not a choice, it is an intention that stopped working,
    and the operator believes they are covered when they are not.
    """
    from agentmetry.core.audit.trail_anchor import resolve_anchor_log, verify_anchors

    anchor_log, source = resolve_anchor_log(trail)

    if source == "config" and not anchor_log.is_file():
        report.warn(
            "anchor",
            f"AGENTMETRY_ANCHOR_LOG points at {anchor_log}, which does not exist. "
            "The trail is chain-verified but not anchored.",
        )
        return

    try:
        coverage = verify_anchors(trail, anchor_log, local_only=(source == "default"))
    except Exception as exc:  # a bad anchor log must not sink the whole report
        report.warn("anchor", f"Could not read anchor log {anchor_log}: {exc}")
        return

    if not coverage.checkpoints:
        return

    if not coverage.ok:
        report.fail(
            "anchor",
            "Trail contradicts a published anchor: "
            + "; ".join(f.message for f in coverage.failures),
        )
        return

    detail = f"Trail anchored through record {coverage.anchored_through}"
    if coverage.unanchored:
        detail += f" ({coverage.unanchored} newer chain-verified only)"
    if source == "default":
        detail += "; anchor log sits beside the trail, so copy it off this host"
    report.ok("anchor", detail)


def _check_mcp(report: DoctorReport) -> None:
    """What the agents on this machine are wired to.

    Agentmetry records what an agent did. This records what it was allowed to
    reach, which is the question a security reviewer asks first and the one the
    trail alone cannot answer.

    Never a FAIL. An unpinned MCP server is a risk posture, not a broken install,
    and failing the exit code over somebody else's packaging decision would make
    `doctor` unusable as a health check on the machines that most need it.
    """
    from agentmetry.core.diagnostics.mcp_inventory import collect

    try:
        inv = collect(Path.cwd())
    except Exception as exc:  # a config reader must not sink the report
        report.warn("mcp", f"Could not read MCP configuration: {exc}")
        return

    for path, exc in inv.unreadable:
        report.warn("mcp", f"Unreadable MCP config {Path(path).name}: {exc[:80]}")

    if not inv.servers:
        # Silence rather than an OK line. A machine with no MCP servers is the
        # common case and has nothing to report.
        return

    flagged = inv.flagged
    if flagged:
        report.warn(
            "mcp",
            f"{len(flagged)} of {len(inv.servers)} MCP server(s) resolve code at launch: "
            + "; ".join(f"{s.agent}/{s.name}" for s in flagged[:4])
            + (" ..." if len(flagged) > 4 else "")
            + ". Run `agentmetry mcp` for detail.",
        )
    else:
        report.ok(
            "mcp",
            f"{len(inv.servers)} MCP server(s) configured, all pinned "
            f"(config digest {inv.digest()[:16]})",
        )


def _check_triage(report: DoctorReport) -> None:
    """Surface the triage backlog without making the operator open the UI.

    A growing pile of undispositioned findings is the failure mode this product
    is most exposed to: detection keeps working, nobody answers it, and the
    evidence pack quietly says so. Warn, never fail - an untriaged detection is
    a task, not a broken install.
    """
    from agentmetry.core.audit.detection.disposition import CLOSED_STATUSES, get_disposition_store

    try:
        counts = get_disposition_store().counts()
    except Exception as exc:  # a missing store must not sink the whole report
        report.warn("triage", f"Could not read triage state: {exc}")
        return

    decided = sum(counts.values())
    if not decided:
        report.warn(
            "triage",
            "No detections have been dispositioned. Detections evidence that "
            "the system noticed, not that anyone acted.",
        )
        return

    open_findings = sum(n for s, n in counts.items() if s not in CLOSED_STATUSES)
    report.ok(
        "triage",
        f"{decided} detection(s) dispositioned; {open_findings} still open",
    )

    # A decision about a rule that no longer exists is still evidence somebody
    # reviewed something, so it is never dropped. It does need saying out loud,
    # or an auditor reads a retired rule as an unreviewed finding.
    try:
        orphans = get_disposition_store().orphaned()
    except Exception:
        return
    if orphans:
        rules = sorted({str(o["rule_id"]) for o in orphans})
        report.warn(
            "triage_orphans",
            f"{len(orphans)} disposition(s) reference rules that no longer exist "
            f"({', '.join(rules[:3])}). Kept as evidence; add a RULE_ALIASES "
            "entry if the rule was renamed rather than retired.",
        )


def _check_autostart(report: DoctorReport) -> None:
    """Say whether anything will restart the recorder without a human.

    `agentmetry install` has existed for a while and nothing ever mentioned it.
    On the machine where this check was written it had never been run, and the
    result was five days of agent activity sitting in the hook spool while the
    trail looked healthy. A capability nobody is told about is worth about as
    much as one that does not exist.

    A warning rather than a failure: running the recorder by hand is a
    legitimate choice, and doctor should not fail an operator for making it.

    A registration that exists but does not work is a different matter, and it
    does fail. Nobody chose that, it looks identical to working from the
    outside, and it is the state this check was in for a day: the task launched
    a module path a package rename had removed, exited 1 every minute, and
    doctor called it OK because something was registered.
    """
    from agentmetry.core.diagnostics import autostart

    state = autostart.status()
    if state.configured and state.healthy is False:
        report.fail("autostart", f"Autostart is broken ({state.backend}): {state.detail}")
        return
    if state.configured:
        report.ok("autostart", f"Starts automatically ({state.backend}): {state.detail}")
        return
    report.warn(
        "autostart",
        f"Nothing restarts the recorder ({state.backend}: {state.detail}). "
        "Hooks keep capturing to the spool while it is down, and spooled events "
        "expire after 7 days. Run `agentmetry install` to fix.",
    )


# A backlog this deep, or this old, is no longer "the orchestrator restarted a
# moment ago". It means capture is not reaching the trail, and for a flight
# recorder that is a failure, not a note.
_SPOOL_FAIL_DEPTH = 100
_SPOOL_FAIL_AGE_SECONDS = 24 * 3600


def _check_spool(report: DoctorReport) -> None:
    """Surface events the hooks captured but the trail has not accepted.

    A small spool is normal for a moment after a restart and drains on a timer.
    A large or old one means the orchestrator is not reachable from the hooks,
    and the operator would otherwise see a healthy-looking trail that is quietly
    missing sessions. Events past MAX_AGE_SECONDS stop being replayable, so the
    age is a countdown, not a statistic.
    """
    from agentmetry.core.audit.spool import (
        MAX_AGE_SECONDS,
        expired_path,
        spool_depth,
        spool_oldest_age_seconds,
    )

    depth = spool_depth()
    quarantined = expired_path()

    if depth == 0:
        if quarantined.is_file():
            report.warn(
                "spool",
                f"Spool empty, but past events were quarantined unreplayed: {quarantined}",
            )
        else:
            report.ok("spool", "No pending hook spool (capture is reaching the trail)")
        return

    age = spool_oldest_age_seconds() or 0.0
    hours = age / 3600
    message = f"{depth} event(s) pending replay; oldest {hours:.1f}h old"

    if depth >= _SPOOL_FAIL_DEPTH or age >= _SPOOL_FAIL_AGE_SECONDS:
        remaining = (MAX_AGE_SECONDS - age) / 3600
        if remaining <= 0:
            message += ". The oldest are past the replay window already"
        else:
            message += f". The oldest become unreplayable in {remaining:.0f}h"
        message += ". Is the orchestrator running and reachable at the hook's base URL?"
        report.fail("spool", message)
        return

    report.warn("spool", message)


def _check_manifests(report: DoctorReport) -> None:
    dlp_path = Path(settings.dlp_rules_path)
    if not dlp_path.is_file():
        report.fail("dlp", f"DLP manifest missing at {dlp_path}")
    else:
        try:
            from agentmetry.core.audit.dlp.loader import load_dlp_rules

            rules = load_dlp_rules(dlp_path)
            report.ok("dlp", f"{len(rules)} DLP rules load from {dlp_path.name}")
        except Exception as exc:
            report.fail("dlp", f"DLP manifest failed to load: {exc}")

    tp_path = Path(settings.tool_policy_path)
    if not tp_path.is_file():
        report.fail("tool_policy", f"Tool policy manifest missing at {tp_path}")
    else:
        try:
            from agentmetry.core.audit.tool_policy.loader import load_tool_policy

            rules, default = load_tool_policy(tp_path)
            report.ok(
                "tool_policy",
                f"{len(rules)} tool policy rules load (default: {default})",
            )
        except Exception as exc:
            report.fail("tool_policy", f"Tool policy manifest failed to load: {exc}")

    det_path = Path(settings.detection_rules_path)
    if not det_path.is_file():
        report.fail("detection", f"Detection manifest missing at {det_path}")
    else:
        try:
            from agentmetry.core.audit.detection.yaml_config import load_manifest

            manifest = load_manifest(reload=True)
            thresholds = manifest.get("thresholds") or {}
            count_rules = manifest.get("count_rules") or []
            report.ok(
                "detection",
                f"{len(count_rules)} YAML count rules + {len(thresholds)} thresholds from {det_path.name}",
            )
        except Exception as exc:
            report.fail("detection", f"Detection manifest failed to load: {exc}")

    report.ok(
        "hook_enforcement",
        f"Tool policy={settings.tool_policy_mode}, DLP={settings.dlp_mode} "
        "(set block in .env or install.ps1 -ToolPolicyBlock)",
    )


def _check_optional_vault(
    report: DoctorReport, vault: Path, *, fix_drivers: bool
) -> None:
    """Demo MCP vault checks - optional runtime, never a doctor failure.

    The SIEM records IDE hook traffic with no vault at all. These checks only
    run when a vault directory exists, and the worst they produce is a warn.
    """
    if not vault.is_dir():
        report.ok("vault", "Demo MCP vault not present (optional) - skipped")
        return

    report.ok("vault", f"Demo vault found at {vault} (optional runtime)")
    drivers_path = vault / ".system" / "drivers.json"
    example_path = vault / ".system" / "drivers.json.example"

    if not drivers_path.is_file():
        if fix_drivers and example_path.is_file():
            shutil.copy(example_path, drivers_path)
            report.ok("drivers", f"Created {drivers_path.name} from drivers.json.example")
        else:
            report.warn(
                "drivers",
                f"No {drivers_path.name} - demo MCP drivers disabled "
                "(copy drivers.json.example or run `agentmetry doctor --fix`)",
            )
            return

    try:
        raw = json.loads(drivers_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report.warn("drivers", f"drivers.json invalid JSON: {exc}")
        return

    drivers = raw.get("drivers") or []
    report.ok("drivers", f"{len(drivers)} driver entries in drivers.json")

    absolute_entries = [d.get("name", "?") for d in drivers if entry_has_absolute_paths(d)]
    if absolute_entries:
        if fix_drivers:
            if normalize_drivers_file(drivers_path, vault_path=vault):
                report.ok(
                    "drivers_portable",
                    "Rewrote drivers.json with {PYTHON}/{ORCHESTRATOR_ROOT}/{VAULT_PATH} tokens",
                )
                raw = json.loads(drivers_path.read_text(encoding="utf-8"))
                drivers = raw.get("drivers") or []
                absolute_entries = [
                    d.get("name", "?") for d in drivers if entry_has_absolute_paths(d)
                ]
            else:
                report.warn("drivers_portable", "Nothing to rewrite in drivers.json")
        if absolute_entries:
            report.warn(
                "drivers_absolute",
                f"Machine-specific paths in: {', '.join(absolute_entries)} "
                "(run `agentmetry doctor --fix`)",
            )
    else:
        report.ok("drivers_portable", "drivers.json uses portable path tokens")

    invalid: list[str] = []
    for entry in drivers:
        try:
            DriverSpec.model_validate(resolve_driver_entry(entry, vault_path=vault))
        except Exception:
            invalid.append(str(entry.get("name", "?")))
    if invalid:
        report.warn("drivers_schema", f"Invalid driver entries: {', '.join(invalid)}")
    else:
        report.ok("drivers_schema", "All driver entries validate")


def _check_extensions(report: DoctorReport) -> None:
    """Report enterprise extension packages (entry points) if installed."""
    from agentmetry.core.extensions import _iter_extension_entry_points, get_extension_registry

    registry = get_extension_registry()
    if registry.loaded:
        names = ", ".join(item.name for item in registry.loaded)
        report.ok("extensions", f"Enterprise extensions loaded: {names}")
        return

    eps = list(_iter_extension_entry_points())
    if not eps:
        report.ok("extensions", "Open-source core (no enterprise extensions installed)")
        return

    names = ", ".join(sorted(ep.name for ep in eps))
    report.ok(
        "extensions",
        f"Enterprise extension packages installed ({names}) - loaded on orchestrator start",
    )


def run_doctor(
    *,
    vault_path: Path | None = None,
    fix_drivers: bool = False,
) -> DoctorReport:
    """SIEM preflight. The recorder is the product; the demo vault is optional.

    Order and severity reflect that: a missing DLP manifest or a broken trail
    chain is a failure, a missing vault is not - the previous doctor hard-failed
    on vault/drivers.json and returned early, so a recorder-only install (the
    documented quick start) showed FAIL while capturing perfectly. Vault checks
    now run last and can only warn.
    """
    report = DoctorReport()
    orch = orchestrator_root()

    # --- SIEM flight recorder ------------------------------------------------
    # A source checkout has a pyproject next to the package; an installed one
    # does not, and never will. Failing on its absence told every pip user their
    # working install was broken as the first line of the first command they
    # run, which is a poor way to meet someone.
    if (orch / "pyproject.toml").is_file():
        report.ok("orchestrator", f"Orchestrator root {orch}")
    elif (Path(__file__).resolve().parents[2] / "__init__.py").is_file():
        report.ok("orchestrator", f"Installed package at {Path(__file__).resolve().parents[2]}")
    else:
        report.fail("orchestrator", f"Expected orchestrator at {orch}")

    py = Path(default_python())
    if py.is_file():
        report.ok("python", f"Python interpreter {py}")
    else:
        report.warn("python", f"Python not found at {py} - run pip install -e '.[dev]'")

    env_file = orch / ".env"
    if env_file.is_file():
        report.ok("env", f"Found {env_file.name} (secrets stay gitignored)")
    else:
        report.warn("env", f"No {env_file} - copy from .env.example if needed")

    data_dir = orch / "data"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        report.ok("data", f"Data directory writable: {data_dir}")
    except OSError as exc:
        report.fail("data", f"Data directory not writable ({data_dir}): {exc}")

    _check_manifests(report)
    _check_exposure(report)
    _check_trail(report)
    _check_triage(report)
    _check_spool(report)
    _check_autostart(report)
    _check_health_endpoint(report)
    _check_hooks_installed(report)
    _check_mcp(report)
    _check_extensions(report)

    # --- Optional governed runtime (demo vault) ------------------------------
    vault = Path(vault_path or settings.vault_path).resolve()
    _check_optional_vault(report, vault, fix_drivers=fix_drivers)

    return report


def format_report(report: DoctorReport) -> str:
    lines: list[str] = []
    for finding in report.findings:
        prefix = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}[finding.severity]
        lines.append(f"  [{prefix}] {finding.message}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="agentmetry-doctor")
    parser.add_argument("--fix", action="store_true", help="rewrite drivers.json to portable tokens")
    args = parser.parse_args(argv)
    report = run_doctor(fix_drivers=args.fix)
    print("Agentmetry doctor\n" + format_report(report))
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
