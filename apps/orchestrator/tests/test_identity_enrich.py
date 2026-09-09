"""Tests for scripts/agentmetry_identity_enrich.py.

Two properties matter more than the classification table, and both are the kind
that break silently.

The first is that enrichment must not touch the trail. Every record in the
canonical trail is chained, `record_sha256 = sha256(prev + canonical_event_json
(event))`, so a field added inside `event` invalidates that record and every
record after it. A pipeline that quietly voids `agentmetry verify` while
labelling sessions is worse than no pipeline.

The second is that domain matching is a substring away from being wrong.
`"gmail.com" in identifier` says `contractor@not-gmail.com.example.net` is
personal, and an attacker who picks their own domain gets to choose their
classification. So the parsed domain is matched exactly or as a subdomain, and
the near-misses are pinned here rather than described in a comment.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "scripts"))

import agentmetry_identity_enrich as ie  # noqa: E402


@pytest.fixture
def cfg() -> ie.Config:
    return ie.Config(
        org_allowlist=("ed8aaf44-3bc7-4041-a704-612428d0afc6",),
        hash_salt="test-salt",
    ).normalised()


def _chained(**event: object) -> dict:
    """A record in the real envelope shape, not a flat dict."""
    return {
        "trail": {"v": 1, "seq": 41, "prev_sha256": "9f2b", "record_sha256": "50cb"},
        "event": {
            "schema_version": "1.2.0",
            "host_id": "DEV-014",
            "action": {"type": "tool_called", "outcome": "success"},
            **event,
        },
    }


# --------------------------------------------------------------- chain safety


def test_enrichment_leaves_the_chained_event_untouched(cfg):
    """The whole reason enrichment is a sibling key and not a new field."""
    record = _chained(
        actor={"type": "user", "id": "dias@work.example"},
        fleet_id="ed8aaf44-3bc7-4041-a704-612428d0afc6",
    )
    before = json.dumps(record, sort_keys=True)
    out = ie.enrich(record, cfg)

    assert json.dumps(out["event"], sort_keys=True) == json.dumps(record["event"], sort_keys=True)
    assert out["trail"] == record["trail"]
    assert json.dumps(record, sort_keys=True) == before, "enrich mutated its input"


def test_enrichment_is_a_new_object_not_an_edit_in_place(cfg):
    record = _chained(actor={"id": "dias@gmail.com"})
    out = ie.enrich(record, cfg)
    assert out is not record
    assert "enrichment" not in record


def test_both_verdicts_are_mirrored_at_top_level(cfg):
    """A SIEM parser maps two flat fields without knowing the object exists."""
    out = ie.enrich(_chained(actor={"id": "x@gmail.com"}), cfg)
    assert out["email_category"] == out["enrichment"]["email_category"]
    assert out["license_context"] == out["enrichment"]["license_context"]


# ------------------------------------------------------------ email behaviour


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("dias@gmail.com", "PERSONAL_EMAIL"),
        ("dias@googlemail.com", "PERSONAL_EMAIL"),
        ("dias@hotmail.com", "PERSONAL_EMAIL"),
        ("dias@outlook.com", "PERSONAL_EMAIL"),
        ("dias@yahoo.co.uk", "PERSONAL_EMAIL"),
        ("dias@proton.me", "PERSONAL_EMAIL"),
        ("dias@mailinator.com", "DISPOSABLE_EMAIL"),
        ("dias@work.example", "OTHER_EMAIL"),
        ("dias@acme-partner.co.uk", "OTHER_EMAIL"),
        ("user123", "NO_EMAIL_FOUND"),
        ("local", "NO_EMAIL_FOUND"),
        ("", "NO_EMAIL_FOUND"),
    ],
)
def test_email_categories(cfg, identifier, expected):
    verdict = ie.classify_email({"user": {"id": identifier}}, cfg)
    assert verdict.category == expected


def test_a_work_domain_is_not_special_cased(cfg):
    """There is no corporate allowlist, deliberately.

    A list of approved domains has to be complete to be safe, and an acquisition
    or a contractor domain missing from it reads as untrusted. Naming only the
    consumer providers means an unknown domain lands on `OTHER_EMAIL`, which is
    an honest "not classified" rather than a false accusation.
    """
    assert ie.classify_email({"user": {"id": "dias@work.example"}}, cfg).category == "OTHER_EMAIL"
    assert ie.classify_email({"user": {"id": "dias@bank.example"}}, cfg).category == "OTHER_EMAIL"


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("dias@mail.gmail.com", "PERSONAL_EMAIL"),  # subdomain of a consumer host
        ("dias@not-gmail.com", "OTHER_EMAIL"),  # substring, and the whole trick
        ("dias@gmail.com.evil.net", "OTHER_EMAIL"),  # suffix attack
        ("dias@gmailxcom", "NO_EMAIL_FOUND"),  # not a domain at all
    ],
)
def test_domain_matching_is_not_a_substring_test(cfg, identifier, expected):
    assert ie.classify_email({"user": {"id": identifier}}, cfg).category == expected


def test_subdomain_matching_can_be_turned_off():
    strict = ie.Config(match_subdomains=False).normalised()
    assert ie.classify_email({"user": {"id": "d@mail.gmail.com"}}, strict).category == "OTHER_EMAIL"
    assert ie.classify_email({"user": {"id": "d@gmail.com"}}, strict).category == "PERSONAL_EMAIL"


def test_case_and_whitespace_do_not_change_the_verdict(cfg):
    verdict = ie.classify_email({"user": {"id": "  Dias.K@GMail.COM  "}}, cfg)
    assert verdict.category == "PERSONAL_EMAIL"
    assert verdict.domain == "gmail.com"


def test_an_address_embedded_in_a_longer_identifier_is_found(cfg):
    verdict = ie.classify_email({"user": {"id": "claude-code:dias@gmail.com:desktop"}}, cfg)
    assert verdict.category == "PERSONAL_EMAIL"
    assert verdict.domain == "gmail.com"


# ------------------------------------------------------------------- identity


def test_one_gmail_account_hashes_the_same_however_it_is_spelled(cfg):
    """Dots and +tags are ignored by the provider, so correlation must ignore them too."""
    spellings = ["dias.k@gmail.com", "diask@gmail.com", "d.i.a.s.k+ai@googlemail.com"]
    digests = {ie.classify_email({"user": {"id": s}}, cfg).address_sha256 for s in spellings}
    assert len(digests) == 1


def test_dot_folding_does_not_leak_to_other_providers(cfg):
    """Most providers treat dots as significant. Folding them everywhere would merge people."""
    a = ie.classify_email({"user": {"id": "dias.k@fastmail.com"}}, cfg).address_sha256
    b = ie.classify_email({"user": {"id": "diask@fastmail.com"}}, cfg).address_sha256
    assert a != b


def test_subaddressing_is_noted(cfg):
    assert "subaddressed" in ie.classify_email({"user": {"id": "d+ai@gmail.com"}}, cfg).notes
    assert ie.classify_email({"user": {"id": "d@gmail.com"}}, cfg).notes == []


def test_the_salt_changes_the_hash():
    salted = ie.Config(hash_salt="one").normalised()
    other = ie.Config(hash_salt="two").normalised()
    record = {"user": {"id": "d@gmail.com"}}
    assert (
        ie.classify_email(record, salted).address_sha256
        != ie.classify_email(record, other).address_sha256
    )


def test_no_raw_address_reaches_the_output(cfg):
    """The point of storing a domain and a digest instead of the address."""
    out = ie.enrich(_chained(actor={"id": "secret.person@gmail.com"}), cfg)
    rendered = json.dumps(out["enrichment"])
    assert "secret.person" not in rendered
    assert "@" not in rendered


# ------------------------------------------------------------- licence context


def test_allowlisted_org_is_approved(cfg):
    out = ie.enrich(_chained(fleet_id="ed8aaf44-3bc7-4041-a704-612428d0afc6"), cfg)
    assert out["license_context"] == "CORPORATE_APPROVED"


def test_an_unknown_org_is_shadow(cfg):
    out = ie.enrich(_chained(fleet_id="b71c9a30-77aa-4d1e-9f0c-5510cc2ab991"), cfg)
    assert out["license_context"] == "OTHER_ORG_SHADOW"
    assert out["enrichment"]["organization_field"] == "event.fleet_id"


def test_a_missing_org_reads_as_personal(cfg):
    assert ie.enrich(_chained(), cfg)["license_context"] == "LIKELY_PERSONAL_NO_ORG"


def test_an_empty_allowlist_does_not_silently_approve():
    """The failure that would matter: everything approved because nothing was configured."""
    empty = ie.Config().normalised()
    out = ie.enrich(_chained(fleet_id="anything-at-all"), empty)
    assert out["license_context"] == "OTHER_ORG_SHADOW"


def test_the_two_signals_are_independent(cfg):
    """A personal address inside the approved org is the case worth seeing."""
    out = ie.enrich(
        _chained(
            actor={"id": "dias@gmail.com"},
            fleet_id="ed8aaf44-3bc7-4041-a704-612428d0afc6",
        ),
        cfg,
    )
    assert out["email_category"] == "PERSONAL_EMAIL"
    assert out["license_context"] == "CORPORATE_APPROVED"


# --------------------------------------------------------------- field lookup


def test_field_order_is_honoured(cfg):
    """`user.id` first, because that is the documented default and the ECS shape."""
    record = {"user": {"id": "ecs@gmail.com"}, "event": {"actor": {"id": "canonical@work.example"}}}
    assert ie.classify_email(record, cfg).identifier_field == "user.id"


def test_it_falls_through_to_the_canonical_event_shape(cfg):
    record = _chained(initiator={"operator_id": "dias@gmail.com"})
    assert ie.classify_email(record, cfg).identifier_field == "event.initiator.operator_id"


def test_a_non_scalar_at_a_path_is_skipped_not_stringified(cfg):
    """`{"id": {...}}` must not become the string of a dict and match on punctuation."""
    record = {"user": {"id": {"nested": "dias@gmail.com"}}, "actor": {"id": "d@hotmail.com"}}
    verdict = ie.classify_email(record, cfg)
    assert verdict.identifier_field == "actor.id"
    assert verdict.category == "PERSONAL_EMAIL"


def test_a_path_through_a_non_dict_does_not_raise(cfg):
    assert ie.classify_email({"user": "a string"}, cfg).category == "NO_EMAIL_FOUND"


# ------------------------------------------------------------------- plumbing


def test_config_rejects_an_unknown_key(tmp_path):
    """A typo must not silently mean 'no allowlist', which reads as total shadow IT."""
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({"org_allow_list": ["x"]}), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown config key"):
        ie.Config.load(path)


def test_config_round_trips_lists_and_strips_at_signs(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(
        json.dumps({"personal_domains": ["@Example.COM "], "org_allowlist": ["a"]}),
        encoding="utf-8",
    )
    cfg = ie.Config.load(path).normalised()
    assert cfg.personal_domains == ("example.com",)
    assert ie.classify_email({"user": {"id": "d@example.com"}}, cfg).category == "PERSONAL_EMAIL"


def test_end_to_end_over_a_directory(tmp_path, capsys):
    """The real path: read a directory, skip a bad line, write enriched JSONL."""
    source = tmp_path / "in"
    source.mkdir()
    lines = [
        json.dumps(_chained(actor={"id": "dias@work.example"}, fleet_id="ed8aaf44")),
        json.dumps(_chained(actor={"id": "dias@gmail.com"})),
        '{"broken": ',
        json.dumps(["not", "an", "object"]),
    ]
    (source / "trail.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    dead = tmp_path / "dead.jsonl"

    code = ie.main(
        [
            "--input-dir",
            str(source),
            "--from-start",
            "--org-allow",
            "ed8aaf44",
            "--dead-letter",
            str(dead),
        ]
    )
    assert code == 0

    written = [json.loads(x) for x in capsys.readouterr().out.strip().splitlines()]
    assert [w["email_category"] for w in written] == ["OTHER_EMAIL", "PERSONAL_EMAIL"]
    assert [w["license_context"] for w in written] == ["CORPORATE_APPROVED", "LIKELY_PERSONAL_NO_ORG"]
    assert len(dead.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_a_restart_does_not_re_emit(tmp_path, capsys):
    """Without a cursor, every restart replays the file into the SIEM."""
    source = tmp_path / "in"
    source.mkdir()
    trail = source / "trail.jsonl"
    trail.write_text(json.dumps(_chained(actor={"id": "a@gmail.com"})) + "\n", encoding="utf-8")
    state = tmp_path / "state.json"
    args = ["--input-dir", str(source), "--from-start", "--state", str(state)]

    ie.main(args)
    assert len(capsys.readouterr().out.strip().splitlines()) == 1

    ie.main(args)
    assert capsys.readouterr().out.strip() == ""

    with trail.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_chained(actor={"id": "b@gmail.com"})) + "\n")
    ie.main(args)
    assert len(capsys.readouterr().out.strip().splitlines()) == 1


def test_a_partial_trailing_line_is_held_until_it_is_complete(tmp_path, capsys):
    """The writer is appending. Half a line now is a whole line in a moment."""
    source = tmp_path / "in"
    source.mkdir()
    trail = source / "trail.jsonl"
    complete = json.dumps(_chained(actor={"id": "a@gmail.com"}))
    trail.write_text(complete + "\n" + '{"event": {"act', encoding="utf-8")
    state = tmp_path / "state.json"
    args = ["--input-dir", str(source), "--from-start", "--state", str(state)]

    ie.main(args)
    assert len(capsys.readouterr().out.strip().splitlines()) == 1

    trail.write_text(complete + "\n" + json.dumps(_chained(actor={"id": "b@gmail.com"})) + "\n",
                     encoding="utf-8")
    ie.main(args)
    assert len(capsys.readouterr().out.strip().splitlines()) == 1
