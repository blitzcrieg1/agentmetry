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


# ----------------------------------------------------------------------
# The attribution paragraph
#
# The README used to say a shared-key holder could post events "claiming any
# host_id, any fleet_id, and any user identity". That was never what the code
# did, and the overstatement travelled: three separate external audits repeated
# it back as the project's fatal flaw. Overstating a weakness costs the same
# credibility as overstating a strength, and it is harder to notice because it
# sounds like honesty.
#
# The corrected paragraph makes a claim about the code, so the code checks it.
# ----------------------------------------------------------------------


def test_ingest_body_takes_no_identity_from_the_caller():
    """The README says a client cannot claim to be another machine."""
    from agentmetry.api.routes.audit import ExternalIngestBody

    fields = set(ExternalIngestBody.model_fields)
    assert "host_id" not in fields
    assert "fleet_id" not in fields
    # Nothing user-shaped either. If an identity field is ever added to this
    # body, the README paragraph becomes false in the direction that matters.
    assert not [f for f in fields if "user" in f or "operator" in f], sorted(fields)


def test_identity_is_stamped_from_the_receiving_host():
    from agentmetry.core.audit.identity import identity_fields

    fields = identity_fields()
    assert "host_id" in fields and fields["host_id"], fields
    # fleet_id is omitted rather than emitted empty, so only assert the shape.
    assert set(fields) <= {"host_id", "fleet_id"}, fields


def test_readme_does_not_reintroduce_the_overstatement():
    """Guards the correction itself, not just the code behind it.

    The old sentence is quoted inside the corrected paragraph on purpose, so
    this checks it never appears as an assertion again: once as a quotation is
    expected, twice means somebody pasted the old text back.
    """
    text = _readme()
    assert text.count("claiming any `host_id`") <= 1, (
        "the overstated attribution claim appears more than once; the paragraph "
        "quotes it exactly once while correcting it"
    )
    # The correction names the two files a reader can check. If either rename
    # happens without updating the README, the invitation stops working.
    assert "agentmetry/api/routes/audit.py" in text
    assert "agentmetry/core/audit/identity.py" in text

def test_readme_rule_count_matches_the_registry():
    """0.7.0 delisted a rule and the README kept saying fifteen.

    That release existed to make published claims true. It fixed
    `detection-rules.md`, the Sigma pack and the whitepaper, and missed the most
    read document in the repository, where the number sat spelled out as a word
    and so matched no numeric search.
    """
    from agentmetry.core.audit.detection.rules import BUILTIN_RULE_IDS

    text = _readme().lower()
    words = {
        12: "twelve", 13: "thirteen", 14: "fourteen",
        15: "fifteen", 16: "sixteen", 17: "seventeen",
    }
    published = len(BUILTIN_RULE_IDS)
    correct = words[published]

    for count, word in words.items():
        if count == published:
            continue
        for phrase in (f"{word} built-in rules", f"{word} published rules", f"{count} built-in rules"):
            assert phrase not in text, (
                f"README says {phrase!r} but the registry publishes {published}. "
                f"Use {correct!r}, and remember an experimental rule is not published."
            )


def test_readme_sigma_count_matches_the_pack():
    """The pack is generated, so its size moves without anyone editing prose."""
    import re

    sigma_dir = Path(__file__).resolve().parents[3] / "docs" / "integrations" / "sigma"
    if not sigma_dir.is_dir():
        pytest.skip("sigma pack not present")
    shipped = len(list(sigma_dir.glob("*.yml")))

    match = re.search(r"Sigma pack\]\([^)]+\)\s*\((\d+) rules\)", _readme())
    assert match, "README no longer states a Sigma rule count; update this test or the README"
    assert int(match.group(1)) == shipped, (
        f"README claims {match.group(1)} Sigma rules, pack ships {shipped}"
    )
