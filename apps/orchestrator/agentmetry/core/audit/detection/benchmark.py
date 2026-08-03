"""Replay a corpus of recorded sessions and score the detection rules.

Two things this exists for.

**Catching the bugs unit tests cannot.** On 2026-07-25 two real defects shipped
past 546 passing tests: sequence ordering was decided by a random UUID on a
timestamp tie, and off-hours detection silently used UTC on Windows. Both were
invisible because every unit test hand-builds events with distinct timestamps in
a clean environment. A corpus of whole sessions, including the awkward ones,
exercises the pipeline the way real traffic does.

**Making the central claim falsifiable.** "Our sequence rules detect credential
exfiltration" is unfalsifiable marketing until someone can run it. This produces
a number a skeptic can reproduce from a clean clone: which rules fired on which
recorded sessions, and how often they fired on benign ones. A false-positive
count you publish is worth more than a detection count you assert.

The corpus is data, not code. Sessions are canonical JSONL exactly as the trail
stores them, so a case can be re-recorded from a real session rather than
invented. Expectations live in `corpus.yaml` beside them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Inside the package, not under tests/. `agentmetry benchmark` is the command
# the README tells a stranger to run to check the false-positive claim, and a
# corpus that ships only in the git repo makes that claim uncheckable for
# anyone who installed from PyPI.
DEFAULT_CORPUS_DIR = Path(__file__).resolve().parent / "corpus"


@dataclass
class Case:
    """One recorded session and what the rules are expected to say about it."""

    name: str
    path: Path
    expect: set[str]
    note: str = ""
    #: Benign cases exist to measure false positives; `expect` is normally empty.
    benign: bool = False

    @property
    def events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events


@dataclass
class CaseResult:
    case: Case
    fired: set[str]

    @property
    def missed(self) -> set[str]:
        """Expected but silent. A rule that does not fire is the whole product."""
        return self.case.expect - self.fired

    @property
    def spurious(self) -> set[str]:
        """Fired but not expected. On a benign case this is a false positive."""
        return self.fired - self.case.expect

    @property
    def passed(self) -> bool:
        return not self.missed and not self.spurious


@dataclass
class BenchmarkReport:
    results: list[CaseResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def attack_cases(self) -> list[CaseResult]:
        return [r for r in self.results if not r.case.benign]

    @property
    def benign_cases(self) -> list[CaseResult]:
        return [r for r in self.results if r.case.benign]

    @property
    def expected_firings(self) -> int:
        return sum(len(r.case.expect) for r in self.results)

    @property
    def detected(self) -> int:
        return sum(len(r.case.expect & r.fired) for r in self.results)

    @property
    def missed(self) -> int:
        return sum(len(r.missed) for r in self.results)

    @property
    def false_positives(self) -> int:
        """Spurious firings across the whole corpus, benign sessions included."""
        return sum(len(r.spurious) for r in self.results)

    @property
    def rules_covered(self) -> set[str]:
        covered: set[str] = set()
        for result in self.results:
            covered |= result.case.expect
        return covered


def load_corpus(corpus_dir: Path | None = None) -> list[Case]:
    """Read `corpus.yaml` and the session files it names."""
    root = Path(corpus_dir or DEFAULT_CORPUS_DIR)
    manifest_path = root / "corpus.yaml"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"No detection corpus manifest at {manifest_path}")

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    cases: list[Case] = []
    for raw in manifest.get("cases") or []:
        name = str(raw.get("name") or "").strip()
        session = str(raw.get("session") or "").strip()
        if not name or not session:
            raise ValueError(f"corpus case needs a name and a session file: {raw!r}")
        path = root / session
        if not path.is_file():
            raise FileNotFoundError(f"corpus case {name!r} names a missing file: {path}")
        cases.append(
            Case(
                name=name,
                path=path,
                expect=set(raw.get("expect") or []),
                note=str(raw.get("note") or ""),
                benign=bool(raw.get("benign", False)),
            )
        )
    if not cases:
        raise ValueError(f"{manifest_path} defines no cases")
    return cases


def run_benchmark(corpus_dir: Path | None = None) -> BenchmarkReport:
    """Replay every case through the real rule engine."""
    from agentmetry.core.audit.detection import run_detections

    report = BenchmarkReport()
    for case in load_corpus(corpus_dir):
        fired = {d.rule_id for d in run_detections(case.events)}
        report.results.append(CaseResult(case=case, fired=fired))
    return report


def render_report(report: BenchmarkReport) -> str:
    """Human-readable summary, deliberately leading with what went wrong."""
    lines = [
        "Agentmetry detection benchmark",
        "",
        f"  cases            {len(report.results)} "
        f"({len(report.attack_cases)} attack, {len(report.benign_cases)} benign)",
        f"  rules covered    {len(report.rules_covered)}",
        f"  expected firings {report.expected_firings}",
        f"  detected         {report.detected}",
        f"  missed           {report.missed}",
        f"  false positives  {report.false_positives}",
        "",
    ]

    failures = [r for r in report.results if not r.passed]
    if not failures:
        lines.append("  All cases behaved as recorded.")
        return "\n".join(lines) + "\n"

    lines.append("  Failures:")
    for result in failures:
        lines.append(f"    {result.case.name}")
        if result.missed:
            lines.append(f"      missed:   {', '.join(sorted(result.missed))}")
        if result.spurious:
            label = "FALSE POSITIVE" if result.case.benign else "unexpected"
            lines.append(f"      {label}: {', '.join(sorted(result.spurious))}")
        if result.case.note:
            lines.append(f"      note:     {result.case.note}")
    return "\n".join(lines) + "\n"
