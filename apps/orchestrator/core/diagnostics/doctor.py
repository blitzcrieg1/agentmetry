"""Agentmetry doctor — SIEM preflight (manifests, trail chain, hooks, health).

Vault/drivers checks are optional-runtime extras and can only warn.
"""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from core.config import settings
from core.diagnostics.driver_paths import (
    default_python,
    entry_has_absolute_paths,
    normalize_drivers_file,
    orchestrator_root,
    resolve_driver_entry,
)
from core.drivers.spec import DriverSpec

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
            f"Orchestrator not reachable at {url} — start it with `agentmetry start`",
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
            f"No trail yet at {trail.name} — run `python scripts/demo.py` or capture a session",
        )
        return
    from core.audit.trail_chain import verify_trail_file

    result = verify_trail_file(trail)
    if result.ok:
        report.ok("trail", f"Trail chain verified: {result.message}")
    else:
        report.fail("trail", f"Trail chain BROKEN: {result.message}")


def _check_manifests(report: DoctorReport) -> None:
    dlp_path = Path(settings.dlp_rules_path)
    if not dlp_path.is_file():
        report.fail("dlp", f"DLP manifest missing at {dlp_path}")
    else:
        try:
            from core.audit.dlp.loader import load_dlp_rules

            rules = load_dlp_rules(dlp_path)
            report.ok("dlp", f"{len(rules)} DLP rules load from {dlp_path.name}")
        except Exception as exc:
            report.fail("dlp", f"DLP manifest failed to load: {exc}")

    tp_path = Path(settings.tool_policy_path)
    if not tp_path.is_file():
        report.fail("tool_policy", f"Tool policy manifest missing at {tp_path}")
    else:
        try:
            from core.audit.tool_policy.loader import load_tool_policy

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
            from core.audit.detection.yaml_config import load_manifest

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
    """Demo MCP vault checks — optional runtime, never a doctor failure.

    The SIEM records IDE hook traffic with no vault at all. These checks only
    run when a vault directory exists, and the worst they produce is a warn.
    """
    if not vault.is_dir():
        report.ok("vault", "Demo MCP vault not present (optional) — skipped")
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
                f"No {drivers_path.name} — demo MCP drivers disabled "
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
    from core.extensions import _iter_extension_entry_points, get_extension_registry

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
        f"Enterprise extension packages installed ({names}) — loaded on orchestrator start",
    )


def run_doctor(
    *,
    vault_path: Path | None = None,
    fix_drivers: bool = False,
) -> DoctorReport:
    """SIEM preflight. The recorder is the product; the demo vault is optional.

    Order and severity reflect that: a missing DLP manifest or a broken trail
    chain is a failure, a missing vault is not — the previous doctor hard-failed
    on vault/drivers.json and returned early, so a recorder-only install (the
    documented quick start) showed FAIL while capturing perfectly. Vault checks
    now run last and can only warn.
    """
    report = DoctorReport()
    orch = orchestrator_root()

    # --- SIEM flight recorder ------------------------------------------------
    if (orch / "pyproject.toml").is_file():
        report.ok("orchestrator", f"Orchestrator root {orch}")
    else:
        report.fail("orchestrator", f"Expected orchestrator at {orch}")

    py = Path(default_python())
    if py.is_file():
        report.ok("python", f"Python interpreter {py}")
    else:
        report.warn("python", f"Python not found at {py} — run pip install -e '.[dev]'")

    env_file = orch / ".env"
    if env_file.is_file():
        report.ok("env", f"Found {env_file.name} (secrets stay gitignored)")
    else:
        report.warn("env", f"No {env_file} — copy from .env.example if needed")

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
    _check_trail(report)
    _check_health_endpoint(report)
    _check_hooks_installed(report)
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
