"""What the hook pays before it does anything (#171).

The hook runs in front of every tool call, and on a blocking hook the agent waits
for it. It cost 626 ms cold on the maintainer's machine, and a third of that was
pydantic, imported because the DLP scanner and the tool-policy evaluator read
five settings through `core.config`. Measured after the fix: 376 ms.

The millisecond count depends on the machine and is not pinned here. What is
pinned is the cause: which modules the hook's import pulls in. A latency budget
nobody asserts drifts back, and the next heavy import would land silently.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from agentmetry.core.audit import policy_settings as ps
from agentmetry.core.config import Settings, settings

#: Third-party top-level modules the hook may load, and why.
ALLOWED_THIRD_PARTY = {
    "yaml": "the DLP and tool-policy manifests are YAML",
    "cython_runtime": "created by PyYAML's libyaml extension when it loads",
}

_PROBE = """
import json, sys
before = set(sys.modules)
import agentmetry.hooks.ingest
added = sorted(set(sys.modules) - before)
print(json.dumps(added))
"""


def _modules_the_hook_adds() -> list[str]:
    out = subprocess.run([sys.executable, "-c", _PROBE], capture_output=True,
                         text=True, timeout=60, check=True)
    return json.loads(out.stdout)


def test_the_hook_does_not_import_pydantic():
    added = set(_modules_the_hook_adds())
    assert "pydantic" not in added
    assert "pydantic_settings" not in added
    assert "agentmetry.core.config" not in added, (
        "something on the hook path imports core.config again; read the setting "
        "through core/audit/policy_settings.py instead"
    )


def test_no_new_third_party_import_lands_on_the_hook_path():
    tops = {m.split(".")[0] for m in _modules_the_hook_adds()}
    third_party = sorted(
        t for t in tops
        if t not in sys.stdlib_module_names and not t.startswith("_") and t != "agentmetry"
    )
    unexpected = [t for t in third_party if t not in ALLOWED_THIRD_PARTY]
    assert not unexpected, (
        f"new third-party import on the hook path: {unexpected}. Every tool call "
        "pays for it. Import it lazily, or add it to ALLOWED_THIRD_PARTY with the reason."
    )


# --------------------------------------------- the two resolvers must agree

_FIELDS = ("dlp_mode", "dlp_rules_path", "dlp_pii", "tool_policy_mode", "tool_policy_path")
_ENV_NAMES = (
    "AGENTMETRY_DLP_MODE", "AGENTMETRY_DLP_RULES_PATH", "AGENTMETRY_DLP_PII",
    "AGENTMETRY_TOOL_POLICY_MODE", "AGENTMETRY_TOOL_POLICY_PATH",
)


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """No inherited AGENTMETRY_* for these five, and a .env both resolvers read."""
    import os

    for key in list(os.environ):
        if key.upper() in _ENV_NAMES:
            monkeypatch.delenv(key)
    monkeypatch.setattr(ps, "_ORCHESTRATOR_ROOT", tmp_path)
    monkeypatch.setattr(ps, "_DOTENV_CACHE", (None, {}))
    return tmp_path


def _both(env_file: Path) -> tuple[dict, dict]:
    real = Settings(_env_file=env_file if env_file.exists() else None)
    light = ps.resolve()
    return (
        {f: (Path(v) if "path" in f else v) for f in _FIELDS for v in [getattr(real, f)]},
        {f: getattr(light, f) for f in _FIELDS},
    )


@pytest.mark.parametrize("env", [
    {},
    {"AGENTMETRY_DLP_MODE": "block"},
    {"AGENTMETRY_TOOL_POLICY_MODE": "disable"},
    {"AGENTMETRY_DLP_PII": "off"},
    {"AGENTMETRY_DLP_PII": "0"},
    {"AGENTMETRY_DLP_PII": "Yes"},
    {"AGENTMETRY_DLP_PII": "TRUE"},
    {"AGENTMETRY_DLP_MODE": ""},
    {"AGENTMETRY_DLP_RULES_PATH": "/etc/agentmetry/dlp.yaml",
     "AGENTMETRY_TOOL_POLICY_PATH": "/etc/agentmetry/tool.yaml"},
])
def test_environment_resolves_the_same_both_ways(isolated, monkeypatch, env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    real, light = _both(isolated / ".env")
    assert light == real


@pytest.mark.parametrize("dotenv", [
    "AGENTMETRY_DLP_MODE=block\n",
    "export AGENTMETRY_DLP_MODE=block\n",
    'AGENTMETRY_DLP_MODE="block"\n',
    "AGENTMETRY_DLP_MODE='block'\n",
    "AGENTMETRY_DLP_MODE=block # enforce at the hook\n",
    "agentmetry_tool_policy_mode=block\n",
    "# AGENTMETRY_DLP_MODE=block\nAGENTMETRY_DLP_PII=false\n",
    "AGENTMETRY_DLP_MODE = block\n",
])
def test_dotenv_resolves_the_same_both_ways(isolated, dotenv):
    (isolated / ".env").write_text(dotenv, encoding="utf-8")
    real, light = _both(isolated / ".env")
    assert light == real


def test_the_environment_beats_dotenv_both_ways(isolated, monkeypatch):
    (isolated / ".env").write_text("AGENTMETRY_DLP_MODE=log\n", encoding="utf-8")
    monkeypatch.setenv("AGENTMETRY_DLP_MODE", "block")
    real, light = _both(isolated / ".env")
    assert light == real
    assert light["dlp_mode"] == "block"


def test_a_typo_keeps_the_default_in_the_hook():
    """Settings refuses to start on `AGENTMETRY_DLP_PII=maybe`. The hook must not
    fail a tool call over it, so it keeps the default."""
    assert ps._bool("maybe", True) is True


def test_where_settings_is_loaded_it_is_what_is_read(monkeypatch):
    """The orchestrator and the suite read the real object, so a monkeypatch of
    `settings.dlp_mode` still reaches the scanner."""
    monkeypatch.setattr(settings, "dlp_mode", "block")
    monkeypatch.setattr(settings, "tool_policy_mode", "disable")
    resolved = ps.policy_settings()
    assert resolved.dlp_mode == "block"
    assert resolved.tool_policy_mode == "disable"


# ------------------------------------------------------------ the YAML loader


@pytest.mark.parametrize("manifest", ["dlp", "tool"])
def test_the_fast_yaml_loader_reads_the_manifests_identically(manifest):
    """libyaml and the pure-Python parser share SafeConstructor. Checked on the
    files the hook actually loads, not assumed."""
    from agentmetry.core.audit.dlp.loader import SAFE_LOADER

    path = Path(ps._PACKAGE_ROOT) / "policies" / manifest / "manifest.yaml"
    text = path.read_text(encoding="utf-8")
    assert yaml.load(text, Loader=SAFE_LOADER) == yaml.load(text, Loader=yaml.SafeLoader)  # noqa: S506


def test_the_fast_loader_is_a_safe_one():
    from agentmetry.core.audit.dlp.loader import SAFE_LOADER

    assert SAFE_LOADER in (getattr(yaml, "CSafeLoader", None), yaml.SafeLoader)
    with pytest.raises(yaml.YAMLError):
        yaml.load("!!python/object/apply:os.system ['echo no']", Loader=SAFE_LOADER)  # noqa: S506
