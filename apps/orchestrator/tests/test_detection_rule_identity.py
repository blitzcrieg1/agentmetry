"""A rule id is not an implementation detail once someone has triaged under it.

F4 from the 2026-07-25 review. `detection_key` was `correlation_id::rule_id`,
so renaming a rule orphaned every disposition recorded against it and deleting
one left decisions pointing at nothing. Both failures are silent and both make a
reviewed period read as unreviewed, which is the opposite of what the triage
loop exists to prove.

Three behaviours are pinned here:

* a rename carries the triage history forward, via a declared alias;
* a delete leaves the decision visible as an orphan, never dropped;
* a typo is refused at the write boundary, before it can become an orphan.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.audit.detection import rules as rules_module
from core.audit.detection.disposition import (
    DispositionError,
    detection_key,
    get_disposition_store,
    reset_disposition_store,
    validate_rule_id,
)
from core.audit.detection.rules import (
    BUILTIN_RULE_IDS,
    canonical_rule_id,
    historical_rule_ids,
    known_rule_ids,
)

_REPO_DOCS = Path(__file__).resolve().parents[3] / "docs"


@pytest.fixture
def store(tmp_path, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "detection_disposition_db_path", tmp_path / "d.db")
    reset_disposition_store()
    yield get_disposition_store()
    reset_disposition_store()


@pytest.fixture
def renamed(monkeypatch):
    """Pretend `credential-exfil` was renamed to `credential-exfiltration`."""
    monkeypatch.setattr(
        rules_module, "RULE_ALIASES", {"credential-exfil": "credential-exfiltration"}
    )
    monkeypatch.setattr(
        rules_module,
        "BUILTIN_RULE_IDS",
        (BUILTIN_RULE_IDS - {"credential-exfil"}) | {"credential-exfiltration"},
    )


# --- the declared id list cannot drift from the code -------------------------

def test_builtin_rule_ids_match_what_the_rules_actually_emit():
    """The set is written out by hand; this is what keeps it honest."""
    source = Path(rules_module.__file__).read_text(encoding="utf-8")
    emitted = set(re.findall(r'rule_id="([a-z0-9-]+)"', source))
    assert emitted == set(BUILTIN_RULE_IDS), {
        "missing from BUILTIN_RULE_IDS": sorted(emitted - set(BUILTIN_RULE_IDS)),
        "declared but never emitted": sorted(set(BUILTIN_RULE_IDS) - emitted),
    }


def test_known_rule_ids_includes_yaml_count_rules():
    from core.audit.detection.yaml_config import count_rules

    known = known_rule_ids()
    for spec in count_rules():
        assert str(spec["id"]) in known, "analyst-authored rules must be dispositionable"


def test_known_rule_ids_includes_the_host_rule():
    assert "host-subagent-swarm-burst" in known_rule_ids()


# --- rename -------------------------------------------------------------------

def test_without_an_alias_a_rule_id_is_itself():
    assert canonical_rule_id("credential-exfil") == "credential-exfil"
    assert historical_rule_ids("credential-exfil") == []


def test_an_alias_resolves_to_the_current_name(renamed):
    assert canonical_rule_id("credential-exfil") == "credential-exfiltration"
    assert historical_rule_ids("credential-exfiltration") == ["credential-exfil"]


def test_the_key_follows_the_rename(renamed):
    assert detection_key("s1", "credential-exfil") == detection_key(
        "s1", "credential-exfiltration"
    )


def test_triage_recorded_before_a_rename_is_still_found(store, renamed, monkeypatch):
    """The decision that matters: "we checked, it was our CI bot"."""
    # Recorded under the old name, before the rename existed.
    monkeypatch.setattr(rules_module, "RULE_ALIASES", {})
    store.record(
        correlation_id="s1",
        rule_id="credential-exfil",
        status="false_positive",
        note="our own CI bot",
    )

    # Rule renamed. Today's detections carry the new id.
    monkeypatch.setattr(
        rules_module, "RULE_ALIASES", {"credential-exfil": "credential-exfiltration"}
    )
    current = store.get("s1", "credential-exfiltration")
    assert current is not None, "rename orphaned the triage history"
    assert current["status"] == "false_positive"
    assert current["note"] == "our own CI bot"


def test_for_correlation_returns_renamed_rules_under_the_new_name(
    store, renamed, monkeypatch
):
    monkeypatch.setattr(rules_module, "RULE_ALIASES", {})
    store.record(correlation_id="s1", rule_id="credential-exfil", status="acknowledged")
    monkeypatch.setattr(
        rules_module, "RULE_ALIASES", {"credential-exfil": "credential-exfiltration"}
    )
    assert "credential-exfiltration" in store.for_correlation("s1")


def test_writing_after_a_rename_migrates_rather_than_forking(store, renamed, monkeypatch):
    """Two rows would read as one triaged finding plus one untriaged one."""
    monkeypatch.setattr(rules_module, "RULE_ALIASES", {})
    store.record(correlation_id="s1", rule_id="credential-exfil", status="acknowledged")

    monkeypatch.setattr(
        rules_module, "RULE_ALIASES", {"credential-exfil": "credential-exfiltration"}
    )
    store.record(
        correlation_id="s1", rule_id="credential-exfiltration", status="resolved"
    )

    rows = store.all()
    assert len(rows) == 1, "rename forked the disposition into two rows"
    assert rows[0]["detection_key"] == "s1::credential-exfiltration"
    # History survives the migration; that is the whole point.
    assert [h["status"] for h in rows[0]["history"]] == ["acknowledged", "resolved"]


def test_an_alias_chain_resolves_to_the_end(monkeypatch):
    monkeypatch.setattr(rules_module, "RULE_ALIASES", {"a": "b", "b": "c"})
    assert canonical_rule_id("a") == "c"


def test_a_circular_alias_does_not_hang(monkeypatch):
    monkeypatch.setattr(rules_module, "RULE_ALIASES", {"a": "b", "b": "a"})
    assert canonical_rule_id("a") in {"a", "b"}


# --- delete -------------------------------------------------------------------

def test_a_retired_rule_leaves_its_decisions_visible(store):
    """Deleting a rule must not delete the evidence someone reviewed it."""
    store.record(
        correlation_id="s1",
        rule_id="a-rule-since-retired",
        status="risk_accepted",
        note="accepted by the security team in March",
    )
    orphans = store.orphaned()
    assert [o["rule_id"] for o in orphans] == ["a-rule-since-retired"]
    assert orphans[0]["note"] == "accepted by the security team in March"


def test_live_rules_are_not_reported_as_orphans(store):
    store.record(correlation_id="s1", rule_id="credential-exfil", status="acknowledged")
    assert store.orphaned() == []


# --- typo ---------------------------------------------------------------------

def test_a_typo_is_refused_before_it_becomes_an_orphan():
    with pytest.raises(DispositionError) as excinfo:
        validate_rule_id("credential-exfill")
    assert "unknown rule_id" in str(excinfo.value)


def test_a_real_rule_validates():
    assert validate_rule_id("credential-exfil") == "credential-exfil"


def test_an_empty_rule_id_is_refused():
    with pytest.raises(DispositionError):
        validate_rule_id("   ")


def test_a_historical_name_still_validates(renamed):
    """An old dashboard or a replayed event may still use the old id."""
    assert validate_rule_id("credential-exfil") == "credential-exfiltration"


async def test_the_api_path_refuses_an_unknown_rule(store, tmp_path, monkeypatch):
    from core.audit.detection.disposition import apply_disposition
    from core.audit.trail_db import reset_trail_db
    from core.config import settings

    monkeypatch.setattr(settings, "audit_db_path", tmp_path / "audit.db")
    monkeypatch.setattr(settings, "audit_export_enabled", False)
    reset_trail_db()

    with pytest.raises(DispositionError):
        await apply_disposition(
            correlation_id="s1", rule_id="not-a-rule", status="acknowledged"
        )
    assert store.all() == []
    reset_trail_db()


# --- replay must stay permissive ---------------------------------------------

def test_the_store_still_accepts_a_retired_rule_on_replay(store):
    """The trail is the record. An event naming a retired rule still happened.

    Validation belongs at the write boundary, not on the way back in from the
    trail, or a rule retirement would make the index unrebuildable.
    """
    assert store.record(
        correlation_id="s1", rule_id="long-gone-rule", status="acknowledged"
    )


# --- the published rule table is part of the contract -------------------------

def test_every_rule_is_documented():
    """A rule nobody published is a rule nobody can tune or dispute.

    Found on 2026-07-26: `session-tool-burst` and `host-subagent-swarm-burst`
    had both shipped without ever reaching the public table, so the README
    understated coverage and the two rules an operator is most likely to want
    to tune were the two they could not read about.
    """
    doc = _REPO_DOCS / "detection-rules.md"
    documented = set(re.findall(r"^\| `([a-z0-9-]+)` \|", doc.read_text(encoding="utf-8"), re.M))
    assert set(BUILTIN_RULE_IDS) - documented == set(), (
        "rules missing from docs/detection-rules.md: "
        f"{sorted(set(BUILTIN_RULE_IDS) - documented)}"
    )


def test_the_docs_do_not_advertise_rules_that_do_not_exist():
    doc = _REPO_DOCS / "detection-rules.md"
    documented = set(re.findall(r"^\| `([a-z0-9-]+)` \|", doc.read_text(encoding="utf-8"), re.M))
    assert documented - set(BUILTIN_RULE_IDS) == set(), (
        f"documented but not implemented: {sorted(documented - set(BUILTIN_RULE_IDS))}"
    )
