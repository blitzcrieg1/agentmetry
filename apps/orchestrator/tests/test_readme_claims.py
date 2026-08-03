"""The README quotes numbers. Numbers rot.

The README pastes a benchmark result and invites the reader to reproduce it from
a clean clone. That invitation is the whole point of the section, and it is only
worth anything while the pasted figures still match what the command prints.

They did not. The README advertised 17 cases while the corpus held 20, for the
same reason the landing page advertised 9 detection rules while the engine
shipped 15: someone pasted output once and the world moved.

`test_version.py` already solves this shape for the version string. This does the
same for the corpus, so the drift fails a test instead of embarrassing the
project in front of the first person who runs the command.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agentmetry.core.audit.detection.benchmark import load_corpus

README = Path(__file__).resolve().parents[3] / "README.md"


def _readme() -> str:
    if not README.is_file():
        pytest.skip(f"README not found at {README}")
    return README.read_text(encoding="utf-8")


def _quoted_benchmark_block(text: str) -> str:
    """The fenced block holding the pasted `cases ... false positives` output."""
    match = re.search(
        r"```\s*\n(\s*cases\s+\d+.*?false positives\s+\d+\s*)\n```",
        text,
        re.S,
    )
    assert match, "README no longer quotes a benchmark result; update this test or the README"
    return match.group(1)


def _number(block: str, label: str) -> int:
    match = re.search(rf"{re.escape(label)}\s+(\d+)", block)
    assert match, f"benchmark block has no {label!r} line"
    return int(match.group(1))


def test_readme_case_counts_match_the_corpus():
    block = _quoted_benchmark_block(_readme())
    cases = load_corpus()

    attack = sum(1 for c in cases if not getattr(c, "benign", False))
    benign = len(cases) - attack

    assert _number(block, "cases") == len(cases), (
        "README quotes a different case count than the corpus holds"
    )

    match = re.search(r"cases\s+\d+\s*\((\d+) attack, (\d+) benign\)", block)
    assert match, "README benchmark block lost its attack/benign split"
    assert (int(match.group(1)), int(match.group(2))) == (attack, benign), (
        f"README says {match.group(1)} attack / {match.group(2)} benign; "
        f"corpus holds {attack} / {benign}"
    )


def test_readme_expected_firings_match_the_corpus():
    """The claim a reader checks first, and the one that rots fastest: every
    added attack case moves it."""
    block = _quoted_benchmark_block(_readme())
    expected = sum(len(c.expect) for c in load_corpus())

    assert _number(block, "expected firings") == expected
    assert _number(block, "detected") == expected, (
        "README should quote a passing run: detected must equal expected firings"
    )


def test_readme_still_claims_a_clean_run():
    """If the corpus ever regresses, the README must not keep advertising zero."""
    block = _quoted_benchmark_block(_readme())
    assert _number(block, "missed") == 0
    assert _number(block, "false positives") == 0


def _cli_commands() -> set[str]:
    """Every subcommand argparse knows about, read from --help.

    Taken from the parser rather than a hand-kept list here, because a second
    list is a second thing to drift.
    """
    import contextlib
    import io as _io

    import agentmetry.cli as cli_module

    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.suppress(SystemExit):
        cli_module.main(["--help"])
    listed = re.search(r"\{([a-z,\-]+)\}", buf.getvalue())
    assert listed, "could not read the command list from --help"
    return set(listed.group(1).split(","))


def test_readme_documents_every_cli_command():
    """A command the README does not mention is a command nobody runs.

    `agentmetry install` is the one that keeps the recorder alive, and it was
    absent from this table long enough for five days of capture to pile up in a
    spool behind a recorder nobody had been told to start.
    """
    text = _readme()
    start = text.find("## CLI Reference")
    assert start != -1, "README lost its CLI Reference section"
    reference = text[start : text.find("\n## ", start + 1)]

    # The table groups related commands (`start` / `stop` / `status`), so match
    # on the bare command name inside the section rather than on a full
    # invocation string.
    undocumented = sorted(
        c for c in _cli_commands() if not re.search(rf"`[^`]*\b{re.escape(c)}\b", reference)
    )
    assert not undocumented, (
        f"CLI commands missing from the README CLI Reference: {undocumented}"
    )
