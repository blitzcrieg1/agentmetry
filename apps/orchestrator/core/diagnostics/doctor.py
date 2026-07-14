"""Agentmetry doctor — preflight checks and drivers.json portability fixes."""

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


def run_doctor(
    *,
    vault_path: Path | None = None,
    fix_drivers: bool = False,
) -> DoctorReport:
    report = DoctorReport()
    vault = Path(vault_path or settings.vault_path).resolve()
    orch = orchestrator_root()
    drivers_path = vault / ".system" / "drivers.json"

    if vault.is_dir():
        report.ok("vault", f"Vault found at {vault}")
    else:
        report.fail("vault", f"Vault path missing: {vault}")
        return report

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

    example_path = vault / ".system" / "drivers.json.example"
    if not drivers_path.is_file():
        if fix_drivers and example_path.is_file():
            shutil.copy(example_path, drivers_path)
            report.ok("drivers", f"Created {drivers_path.name} from drivers.json.example")
        else:
            report.fail(
                "drivers",
                f"Missing {drivers_path.name} — copy vault/.system/drivers.json.example "
                f"to vault/.system/drivers.json (or run `agentmetry doctor --fix`)",
            )
            return report

    try:
        raw = json.loads(drivers_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report.fail("drivers", f"drivers.json invalid JSON: {exc}")
        return report

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
        report.fail("drivers_schema", f"Invalid driver entries: {', '.join(invalid)}")
    else:
        report.ok("drivers_schema", "All driver entries validate")

    data_dir = orch / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    report.ok("data", f"Data directory {data_dir}")

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
