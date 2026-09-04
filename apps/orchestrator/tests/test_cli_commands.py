"""The CLI surface, exercised through `main()` the way a deployment tool calls it.

The CLI was the least-covered large module in the package (28% of ~680
statements) while being the entire operator interface and, more to the point,
the interface an MDM deployment drives. `agentmetry hooks status` is wired into
Intune Remediations as a detection script; `doctor` gates an install; `verify`
is the flagship trust command. A regression in any of those is silent on a
developer machine and expensive on a fleet.

Tests go through `main(argv)` rather than calling the `cmd_*` functions with a
hand-built Namespace, because half the contract is the parser. A handler that
still works while its subparser stopped accepting a flag is broken from the
caller's point of view, and only the `main()` path notices.

Commands deliberately not covered here: `start`, `serve`, `stop`, `install`,
`uninstall`. They spawn processes or mutate the host, and a test that mocks
enough to make them safe would be asserting against the mocks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentmetry.cli import main
from agentmetry.core.audit.trail_chain import append_chained_line


# --------------------------------------------------------------------------
# parser and dispatch
# --------------------------------------------------------------------------


def test_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_unknown_command_is_a_usage_error():
    with pytest.raises(SystemExit) as exc:
        main(["definitely-not-a-command"])
    assert exc.value.code == 2


def test_no_command_is_a_usage_error():
    """argparse with required subparsers, so a bare invocation must not crash."""
    with pytest.raises(SystemExit):
        main([])


def test_every_handler_has_a_subparser():
    """A handler added without a subparser is unreachable and nothing says so.

    The reverse (a subparser with no handler) raises KeyError at dispatch, which
    at least fails loudly. This direction fails silently, so it is pinned.
    """
    import argparse
    import inspect

    from agentmetry import cli

    src = inspect.getsource(cli.main)
    handler_block = src[src.index("handlers = {") : src.index("return handlers[")]
    handler_names = set(__import__("re").findall(r'"([a-z-]+)":', handler_block))

    parser_names: set[str] = set()

    real_add_parser = argparse._SubParsersAction.add_parser

    def spy(self, name, *a, **kw):
        parser_names.add(name)
        return real_add_parser(self, name, *a, **kw)

    argparse._SubParsersAction.add_parser = spy
    try:
        with pytest.raises(SystemExit):
            cli.main(["--help"])
    finally:
        argparse._SubParsersAction.add_parser = real_add_parser

    assert handler_names, "could not parse the handler table"
    assert handler_names <= parser_names, (
        f"handlers with no subparser: {sorted(handler_names - parser_names)}"
    )


# --------------------------------------------------------------------------
# verify: the flagship trust command
# --------------------------------------------------------------------------


def test_verify_missing_file_returns_one(tmp_path: Path, capsys):
    assert main(["verify", str(tmp_path / "nope.jsonl")]) == 1
    assert "No such file" in capsys.readouterr().out


# `--anchors` rather than the environment variable: settings is a cached
# singleton, so setting AGENTMETRY_ANCHOR_LOG after import does not take, and a
# test that appears isolated but is not is worse than one that is obviously
# explicit. It also exercises the documented flag.
def _empty_anchor_log(tmp_path: Path) -> str:
    log = tmp_path / "anchors.jsonl"
    log.write_text("", encoding="utf-8")
    return str(log)


def test_verify_trail_reports_ok_head_and_merkle_root(tmp_path: Path, capsys):
    trail = tmp_path / "trail.jsonl"
    for i in range(3):
        append_chained_line(trail, {"event_id": f"e{i}", "action": {"type": "tool_called"}})

    assert main(["verify", "--trail", str(trail), "--anchors", _empty_anchor_log(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("OK")
    # The three facts an operator is told to record. If any stops printing, the
    # documented "compare the head on the next verify" workflow silently ends.
    assert "lines: 3 total" in out
    assert "head: seq" in out
    assert "merkle root:" in out
    assert "tree size: 3 (rfc6962-sha256)" in out


def test_verify_trail_fails_on_a_tampered_line(tmp_path: Path, capsys):
    trail = tmp_path / "trail.jsonl"
    for i in range(3):
        append_chained_line(trail, {"event_id": f"e{i}", "action": {"type": "tool_called"}})

    lines = trail.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["event"]["event_id"] = "rewritten"
    lines[1] = json.dumps(record)
    trail.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert main(["verify", "--trail", str(trail), "--anchors", _empty_anchor_log(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "first bad line" in out


def test_verify_rejects_a_pack_that_is_not_json(tmp_path: Path, capsys):
    pack = tmp_path / "pack.json"
    pack.write_text("{not json", encoding="utf-8")
    assert main(["verify", str(pack)]) == 1
    assert "Invalid JSON" in capsys.readouterr().out


def test_verify_reports_a_tampered_evidence_pack(tmp_path: Path, capsys):
    """Editing the body must break the integrity hash."""
    from datetime import date

    from agentmetry.core.audit.evidence_pack import build_evidence_pack

    pack_path = tmp_path / "pack.json"
    pack = build_evidence_pack(date(2000, 1, 1), date(2000, 1, 2))
    pack["events"] = [{"event_id": "planted", "action": {"type": "tool_called"}}]
    pack_path.write_text(json.dumps(pack), encoding="utf-8")

    assert main(["verify", str(pack_path)]) == 1
    assert "integrity mismatch" in capsys.readouterr().out


def test_verify_accepts_a_pack_whose_meta_was_edited(tmp_path: Path, capsys):
    """Documents a real gap rather than asserting the behaviour is right.

    `_integrity_hash` covers the body only, so `meta.producer`, `meta.date_from`
    and `meta.date_to` can all be rewritten and the pack still verifies. The
    date range is the one that matters: a pack can be relabelled to claim a
    period it does not cover. Tracked in blitzcrieg1/agentmetry#75; when that is
    fixed this test flips to asserting failure.
    """
    from datetime import date

    from agentmetry.core.audit.evidence_pack import build_evidence_pack

    pack_path = tmp_path / "pack.json"
    pack = build_evidence_pack(date(2000, 1, 1), date(2000, 1, 2))
    pack["meta"]["producer"] = "somebody-else/9.9.9"
    pack["meta"]["date_to"] = "2031-12-31"
    pack_path.write_text(json.dumps(pack), encoding="utf-8")

    assert main(["verify", str(pack_path)]) == 0, "gap closed? update this test and #75"


# --------------------------------------------------------------------------
# the commands a fleet install actually runs
# --------------------------------------------------------------------------


def test_doctor_returns_the_report_exit_code(capsys):
    from agentmetry.core.diagnostics.doctor import run_doctor

    expected = run_doctor().exit_code
    assert main(["doctor"]) == expected
    assert "Agentmetry doctor" in capsys.readouterr().out


def test_benchmark_passes_on_the_shipped_corpus(capsys):
    """The claim on the homepage, asserted from the CLI a stranger would run."""
    assert main(["benchmark"]) == 0
    out = capsys.readouterr().out
    assert "missed" in out
    assert "false positives" in out


def test_hooks_status_returns_a_documented_exit_code(capsys):
    """0 compliant, 1 remediable, 2 undeterminable. Intune reads this number."""
    assert main(["hooks", "status"]) in {0, 1, 2}
    assert capsys.readouterr().out != ""


def test_hooks_rejects_an_unknown_agent(capsys):
    assert main(["hooks", "install", "--agent", "notanagent"]) == 2
    assert "No installer for" in capsys.readouterr().err


def test_mcp_inventory_exits_zero_even_with_findings(capsys):
    """Findings describe a risk posture, not a broken install.

    A non-zero exit here would break a health check somebody wired into MDM, so
    the zero is a contract rather than an accident.
    """
    assert main(["mcp"]) == 0
    assert capsys.readouterr().out != ""


def test_dogfood_renders_a_report(capsys):
    assert main(["dogfood"]) in {0, 1}
    out = capsys.readouterr().out
    assert "Dogfood" in out or "dogfood" in out


# --------------------------------------------------------------------------
# commands that talk to a running orchestrator
# --------------------------------------------------------------------------


def test_status_reports_not_running_when_health_fails(monkeypatch, capsys):
    from agentmetry import cli

    monkeypatch.setattr(cli, "_fetch_health", lambda _port: None)
    assert main(["status"]) == 1
    assert "not running" in capsys.readouterr().out


def test_status_prints_mode_and_export_when_running(monkeypatch, capsys):
    from agentmetry import cli

    monkeypatch.setattr(
        cli,
        "_fetch_health",
        lambda _port: {
            "status": "ok",
            "mode": "siem",
            "audit_export": {"enabled": True, "path": "C:/agentmetry/data/trail.jsonl"},
        },
    )
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "ok" in out
    assert "Mode:" in out
    assert "enabled" in out


def test_stats_says_so_when_the_orchestrator_is_down(monkeypatch, capsys):
    from agentmetry import cli

    def boom(*_a, **_kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(cli.httpx, "get", boom)
    assert main(["stats"]) == 1
    assert "Not running" in capsys.readouterr().out


def test_stats_renders_the_window_counts(monkeypatch, capsys):
    from agentmetry import cli

    class Resp:
        @staticmethod
        def json():
            return {
                "enabled": True,
                "window_days": 7,
                "total_events": 9745,
                "sessions": 33,
                "detections": 27,
                "denied": 2,
                "dlp_matches": 1,
                "tool_policy_hits": 4,
                "tool_policy_blocks": 0,
                "by_source": {"claude": 20, "cursor": 13},
                "last_event_utc": "2026-08-21T10:00:00+00:00",
            }

    monkeypatch.setattr(cli.httpx, "get", lambda *_a, **_kw: Resp())
    assert main(["stats", "--days", "7"]) == 0
    out = capsys.readouterr().out
    assert "last 7 day(s)" in out
    assert "9745" in out
    assert "claude=20" in out


def test_stats_explains_a_disabled_export(monkeypatch, capsys):
    from agentmetry import cli

    class Resp:
        @staticmethod
        def json():
            return {"enabled": False}

    monkeypatch.setattr(cli.httpx, "get", lambda *_a, **_kw: Resp())
    assert main(["stats"]) == 1
    assert "disabled" in capsys.readouterr().out


def _api_detection(rule_id: str, severity: str, summary: str, seen: str) -> dict:
    return {
        "rule_id": rule_id,
        "title": rule_id.replace("-", " ").title(),
        "severity": severity,
        "summary": summary,
        "correlation_id": "session-7",
        "tactic_ids": [],
        "technique_ids": [],
        "event_ids": [],
        "first_seen_utc": seen,
        "last_seen_utc": seen,
        "disposition": None,
    }


def test_detections_prints_the_ranked_api_results(monkeypatch, capsys):
    from agentmetry import cli

    requested = []

    class Resp:
        @staticmethod
        def json():
            return {
                "detections": [
                    _api_detection(
                        "credential-exfil",
                        "critical",
                        "Credentials were read before network egress.",
                        "2026-08-31T01:00:00+00:00",
                    ),
                    _api_detection(
                        "guardrail-bypass",
                        "high",
                        "An agent modified its own instructions.",
                        "2026-08-31T01:02:00+00:00",
                    ),
                ],
                "correlation_id": "session-7",
                "enabled": True,
                "count": 2,
                "untriaged": 2,
            }

    def get(url, **_kwargs):
        requested.append(url)
        return Resp()

    monkeypatch.setattr(cli.httpx, "get", get)
    assert main(["detections", "session-7"]) == 0
    assert requested == ["http://127.0.0.1:8000/api/v1/audit/detections/session-7"]
    lines = capsys.readouterr().out.splitlines()
    assert "Rule" in lines[0] and "Severity" in lines[0] and "Summary" in lines[0]
    assert "credential-exfil" in lines[2]
    assert "critical" in lines[2]
    assert "Credentials were read before network egress." in lines[2]
    assert "guardrail-bypass" in lines[3]


def test_detections_reports_an_empty_session_cleanly(monkeypatch, capsys):
    from agentmetry import cli

    class Resp:
        @staticmethod
        def json():
            return {
                "detections": [],
                "correlation_id": "session-empty",
                "enabled": True,
                "count": 0,
                "untriaged": 0,
            }

    monkeypatch.setattr(cli.httpx, "get", lambda *_args, **_kwargs: Resp())
    assert main(["detections", "session-empty"]) == 0
    assert "No detections" in capsys.readouterr().out


def test_detections_explains_a_disabled_export(monkeypatch, capsys):
    from agentmetry import cli

    class Resp:
        @staticmethod
        def json():
            return {
                "detections": [],
                "correlation_id": "session-7",
                "enabled": False,
                "count": 0,
            }

    monkeypatch.setattr(cli.httpx, "get", lambda *_args, **_kwargs: Resp())
    assert main(["detections", "session-7"]) == 1
    out = capsys.readouterr().out
    assert "Audit export is disabled" in out
    assert "AGENTMETRY_AUDIT_EXPORT_ENABLED=1" in out


def test_detections_says_so_when_the_orchestrator_is_down(monkeypatch, capsys):
    from agentmetry import cli

    def boom(*_args, **_kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(cli.httpx, "get", boom)
    assert main(["detections", "session-7"]) == 1
    assert "Not running" in capsys.readouterr().out


def test_disposition_posts_the_closing_decision(monkeypatch, capsys):
    from agentmetry import cli

    calls = {}

    class Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"disposition": {"status": "resolved"}}

    def post(url, **kwargs):
        calls["url"] = url
        calls.update(kwargs)
        return Resp()

    monkeypatch.delenv("AGENTMETRY_URL", raising=False)
    monkeypatch.delenv("AGENTMETRY_API_KEY", raising=False)
    monkeypatch.setattr(cli.httpx, "post", post)

    assert main([
        "disposition",
        "sess-1",
        "credential-exfil",
        "--status",
        "resolved",
    ]) == 0

    assert calls["url"] == "http://127.0.0.1:8000/api/v1/audit/detections/disposition"
    assert calls["json"] == {
        "correlation_id": "sess-1",
        "rule_id": "credential-exfil",
        "status": "resolved",
        "note": "",
        "decided_by": "",
    }
    assert calls["headers"] == {}
    assert "sess-1 credential-exfil -> resolved" in capsys.readouterr().out


def test_disposition_uses_configured_url_and_api_key(monkeypatch):
    from agentmetry import cli

    calls = {}

    class Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"disposition": {"status": "risk_accepted"}}

    monkeypatch.setenv("AGENTMETRY_URL", "http://agentmetry.test/")
    monkeypatch.setenv("AGENTMETRY_API_KEY", "secret-token")
    monkeypatch.setattr(
        cli.httpx,
        "post",
        lambda url, **kwargs: calls.update({"url": url, **kwargs}) or Resp(),
    )

    assert main([
        "disposition",
        "sess-1",
        "session-tool-burst",
        "--status",
        "risk_accepted",
        "--note",
        "known load test",
        "--decided-by",
        "home-lab",
    ]) == 0

    assert calls["url"] == "http://agentmetry.test/api/v1/audit/detections/disposition"
    assert calls["headers"] == {"X-API-Key": "secret-token"}
    assert calls["json"]["note"] == "known load test"
    assert calls["json"]["decided_by"] == "home-lab"


def test_disposition_requires_a_note_for_non_resolved_closures(monkeypatch, capsys):
    from agentmetry import cli

    def post(*_a, **_kw):
        raise AssertionError("should validate before POST")

    monkeypatch.setattr(cli.httpx, "post", post)

    assert main([
        "disposition",
        "sess-1",
        "credential-exfil",
        "--status",
        "false_positive",
    ]) == 1
    assert "--note is required" in capsys.readouterr().out


def test_disposition_says_so_when_the_orchestrator_is_down(monkeypatch, capsys):
    from agentmetry import cli

    def boom(*_a, **_kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(cli.httpx, "post", boom)

    assert main([
        "disposition",
        "sess-1",
        "credential-exfil",
        "--status",
        "resolved",
    ]) == 1
    assert "Not running" in capsys.readouterr().out


def test_disposition_prints_server_errors(monkeypatch, capsys):
    from agentmetry import cli

    class Resp:
        status_code = 400
        text = "bad request"

        @staticmethod
        def json():
            return {"detail": "unknown rule_id 'typo'"}

    monkeypatch.setattr(cli.httpx, "post", lambda *_a, **_kw: Resp())

    assert main(["disposition", "sess-1", "typo", "--status", "resolved"]) == 1
    assert "unknown rule_id" in capsys.readouterr().out


# --------------------------------------------------------------------------
# small surfaces that still have an exit-code contract
# --------------------------------------------------------------------------


def test_logs_reports_a_missing_log_file(monkeypatch, tmp_path: Path, capsys):
    from agentmetry import cli

    monkeypatch.setattr(cli, "_DATA_DIR", tmp_path)
    assert main(["logs"]) == 1
    assert "No log file yet" in capsys.readouterr().out


def test_replay_requires_a_thread_id(capsys):
    assert main(["replay", "   "]) == 1
    assert "required" in capsys.readouterr().out


# --------------------------------------------------------------------------
# the evidence commands
#
# anchor, prove and export are what turn "we have a log" into "here is a thing
# an auditor can check". They were the least-covered part of the least-covered
# module, which is a bad combination for the feature the product argues from.
# --------------------------------------------------------------------------


def _trail(tmp_path: Path, n: int = 4) -> Path:
    trail = tmp_path / "trail.jsonl"
    for i in range(n):
        append_chained_line(trail, {"event_id": f"e{i}", "action": {"type": "tool_called"}})
    return trail


def test_anchor_publishes_a_checkpoint_and_names_the_ceiling(tmp_path: Path, capsys):
    trail = _trail(tmp_path)
    anchors = tmp_path / "anchors.jsonl"

    assert main(["anchor", str(trail), "--anchors", str(anchors)]) == 0
    out = capsys.readouterr().out
    assert "Anchored 4 record(s)" in out
    # The caveat is the feature. A checkpoint on the same disk as the trail buys
    # nothing against a host attacker, and an operator who never reads that
    # sentence believes it buys everything.
    assert "cannot write it" in out
    assert anchors.is_file()


def test_anchor_show_lists_checkpoints(tmp_path: Path, capsys):
    trail = _trail(tmp_path)
    anchors = tmp_path / "anchors.jsonl"
    main(["anchor", str(trail), "--anchors", str(anchors)])
    capsys.readouterr()

    assert main(["anchor", str(trail), "--anchors", str(anchors), "--show"]) == 0
    assert "1 checkpoint(s)" in capsys.readouterr().out


def test_anchor_show_on_an_empty_log_is_not_an_error(tmp_path: Path, capsys):
    trail = _trail(tmp_path)
    assert main(["anchor", str(trail), "--anchors", str(tmp_path / "none.jsonl"), "--show"]) == 0
    assert "No checkpoints" in capsys.readouterr().out


def test_anchor_print_only_emits_without_recording(tmp_path: Path, capsys):
    trail = _trail(tmp_path)
    anchors = tmp_path / "anchors.jsonl"

    assert main(["anchor", str(trail), "--anchors", str(anchors), "--print"]) == 0
    assert capsys.readouterr().out.strip() != ""
    assert not anchors.exists(), "--print must not write a checkpoint"


def test_anchor_verify_detects_a_rewritten_trail(tmp_path: Path, capsys):
    trail = _trail(tmp_path)
    anchors = tmp_path / "anchors.jsonl"
    main(["anchor", str(trail), "--anchors", str(anchors)])
    capsys.readouterr()

    # Rewrite a record and rebuild the chain around it, which is exactly the
    # attack `verify --trail` alone cannot see.
    from agentmetry.core.audit.trail_chain import append_chained_line as _app

    trail.unlink()
    (tmp_path / "trail.jsonl.chain").unlink(missing_ok=True)
    for i in range(4):
        _app(trail, {"event_id": "rewritten" if i == 1 else f"e{i}", "action": {"type": "tool_called"}})

    assert main(["anchor", str(trail), "--anchors", str(anchors), "--verify"]) == 1
    assert "TAMPERING" in capsys.readouterr().out


def test_anchor_missing_file_returns_one(tmp_path: Path, capsys):
    assert main(["anchor", str(tmp_path / "nope.jsonl")]) == 1
    assert "No such file" in capsys.readouterr().out


def test_prove_check_rejects_a_missing_proof(tmp_path: Path, capsys):
    trail = _trail(tmp_path)
    assert main(["prove", str(trail), "--check", str(tmp_path / "nope.json")]) == 1
    assert "No such proof file" in capsys.readouterr().out


def test_prove_check_rejects_a_file_that_is_not_a_proof(tmp_path: Path, capsys):
    trail = _trail(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text('{"not": "a proof"}', encoding="utf-8")
    assert main(["prove", str(trail), "--check", str(bad)]) == 1
    assert "Not a readable proof" in capsys.readouterr().out


def test_prove_missing_trail_returns_one(tmp_path: Path, capsys):
    assert main(["prove", str(tmp_path / "nope.jsonl")]) == 1
    assert "No such file" in capsys.readouterr().out


def test_export_without_a_mode_explains_itself(capsys):
    assert main(["export"]) == 1
    assert "--evidence" in capsys.readouterr().out


def test_export_requires_both_dates(capsys):
    assert main(["export", "--evidence", "--from", "2026-01-01"]) == 1
    assert "--from and --to are required" in capsys.readouterr().out


def test_export_rejects_an_unparseable_date(capsys):
    assert main(["export", "--evidence", "--from", "not-a-date", "--to", "2026-01-02"]) == 1
    assert "Invalid date" in capsys.readouterr().out


def test_export_writes_a_pack_that_verifies(tmp_path: Path, capsys):
    """The round trip the pilot page describes: export, then hand it over."""
    out = tmp_path / "pack.json"
    assert (
        main([
            "export", "--evidence",
            "--from", "2000-01-01", "--to", "2000-01-02",
            "--output", str(out),
        ])
        == 0
    )
    printed = capsys.readouterr().out
    assert "Evidence pack ->" in printed
    assert "integrity:" in printed
    assert out.is_file()

    assert main(["verify", str(out)]) == 0
    assert "OK" in capsys.readouterr().out
