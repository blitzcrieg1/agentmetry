"""Local honeytokens: decoy credentials whose use is a near-certain finding.

An opt-in `agentmetry canary` command plants credentials an agent should never
touch, each one unique and recognisably fake to a human. Every planted value
also becomes a DLP rule, so a read becomes a match at the tool boundary instead
of something a human has to notice later.

Design constraints (issue #293):

* **Local only.** Nothing here calls out. A decoy that phoned home would break
  local-first, so the detection is a DLP regex over what the agent already
  submitted, exactly like every other rule in the manifest.
* **The trail records the rule id, never the value.** Decoys are values, and
  values do not go into the trail; the scanner redacts matches the same way it
  redacts a real token.
* **Never overwrites a real credential.** If the target profile or key already
  exists, planting refuses rather than merging into it.
* **Off by default.** Nothing is planted until the operator runs the command,
  and `remove` puts every file back the way it was.
* **Removable.** Each plant records what it appended; removal deletes exactly
  that, and refuses if the file changed underneath it.

The rules live under ``~/.agentmetry/canary/rules.yaml`` and are picked up by
``load_dlp_rules`` the same way the built-in manifest is. Nothing in the frozen
detection files is touched.
"""

from __future__ import annotations

import json
import re
import secrets
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: Everything this feature owns. `rules.yaml` is loaded by `load_dlp_rules`
#: as an extra manifest; `state.json` is the inventory `list` and `remove` read.
#: `HOME` is a module attribute rather than a `Path.home()` call at each use so
#: tests can point the whole feature at a temporary directory.
HOME = Path.home()
STATE_DIR = HOME / ".agentmetry" / "canary"
STATE_FILE = STATE_DIR / "state.json"
RULES_FILE = STATE_DIR / "rules.yaml"

#: Prefixed so a human reading the value knows immediately what it is. The
#: prefix is also what makes the DLP pattern specific enough to be useful.
MARK = "AGENTMETRY-CANARY"

_ALNUM = string.ascii_letters + string.digits


def _random_value(length: int = 32) -> str:
    return "".join(secrets.choice(_ALNUM) for _ in range(length))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"decoys": []}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"decoys": []}
    if not isinstance(data, dict) or not isinstance(data.get("decoys"), list):
        return {"decoys": []}
    return data


def _save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _load_rules() -> dict[str, Any]:
    if not RULES_FILE.exists():
        return {"version": "1.0", "rules": []}
    import yaml  # local import: only `canary` needs it at runtime

    from agentmetry.core.audit.dlp.loader import SAFE_LOADER

    data = yaml.load(RULES_FILE.read_text(encoding="utf-8"), Loader=SAFE_LOADER) or {}  # noqa: S506 - a safe loader, same as loader.py
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        return {"version": "1.0", "rules": []}
    return data


def _save_rules(data: dict[str, Any]) -> None:
    import yaml

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    RULES_FILE.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def _rule_for(name: str, values: list[str], where: str) -> dict[str, Any]:
    """One rule per decoy, anchored on the planted values themselves.

    Anchoring on the exact value rather than on the MARK prefix keeps the rule
    narrow: a sentence that merely mentions "canary" does not match, only the
    value that was actually planted.
    """
    pattern = "|".join(re.escape(v) for v in values)
    return {
        "id": f"canary_{name}",
        "name": f"Agentmetry canary: {where}",
        "description": (
            "Decoy credential planted by `agentmetry canary`. Touching this value "
            "is close to certain proof an agent reached for credentials it should "
            "not have. Planted locally; the value never leaves this machine."
        ),
        "pattern": pattern,
        "category": "canary",
        "severity": "critical",
    }


# --------------------------------------------------------------------------
# targets
# --------------------------------------------------------------------------


def _aws_values() -> list[str]:
    """Two values in the shapes the built-in AWS rules already know."""
    return [
        "AKIA" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(16)),
        _random_value(40),
    ]


def _plant_aws_credentials(path: Path, profile: str, values: list[str]) -> dict[str, Any]:
    """Append a fake profile, refusing if it or a real one is already there."""
    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8", errors="replace")
        if f"[{profile}]" in existing:
            raise SystemExit(
                f"refusing: profile [{profile}] already exists in {path}. "
                "Remove it first, or pick a different profile name."
            )
    block = (
        f"\n[{profile}]\n"
        f"aws_access_key_id = {values[0]}\n"
        f"aws_secret_access_key = {values[1]}\n"
    )
    return {
        "path": str(path),
        "appended": block,
        "existed_before": path.exists(),
        "previous_length": len(existing),
    }


def _plant_env(path: Path, key: str, value: str) -> dict[str, Any]:
    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8", errors="replace")
        if re.search(rf"^\s*{re.escape(key)}\s*=", existing, re.MULTILINE):
            raise SystemExit(
                f"refusing: {key} already exists in {path}. "
                "Remove it first, or pick a different key name."
            )
    block = f"\n# {MARK}: decoy, never a real credential\n{key}={value}\n"
    return {
        "path": str(path),
        "appended": block,
        "existed_before": path.exists(),
        "previous_length": len(existing),
    }


def _write_append(meta: dict[str, Any]) -> None:
    path = Path(meta["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(meta["appended"])


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------


def plant(kind: str, scope: str, project: Path | None = None, name: str = "") -> dict[str, Any]:
    """Plant one decoy and register its DLP rule.

    ``kind`` is ``aws`` or ``env``; ``scope`` is ``home`` or ``project``.
    Returns the record written to the state file.
    """
    state = _load_state()
    decoy_name = name or f"{kind}-{scope}-{len(state['decoys']) + 1}"
    if any(d.get("name") == decoy_name for d in state["decoys"]):
        raise SystemExit(f"refusing: a decoy named {decoy_name!r} already exists")

    values: list[str]
    if kind == "aws":
        if scope != "home":
            raise SystemExit("refusing: an AWS decoy profile belongs in the home directory")
        target = HOME / ".aws" / "credentials"
        profile = f"agentmetry-canary-{len(state['decoys']) + 1}"
        values = _aws_values()
        meta = _plant_aws_credentials(target, profile, values)
        where = f"{target} [{profile}]"
    elif kind == "env":
        if project is None:
            raise SystemExit("refusing: an env decoy needs --project <dir>")
        target = Path(project) / ".env"
        key = f"AGENTMETRY_CANARY_{len(state['decoys']) + 1}"
        values = [f"{MARK}-{_random_value(24)}"]
        meta = _plant_env(target, key, values[0])
        where = f"{target} [{key}]"
    else:
        raise SystemExit(f"unknown decoy kind: {kind!r} (expected aws or env)")

    _write_append(meta)

    rule = _rule_for(decoy_name, values, where)
    rules = _load_rules()
    rules["rules"].append(rule)
    _save_rules(rules)

    record = {
        "name": decoy_name,
        "kind": kind,
        "scope": scope,
        "where": where,
        "values": values,
        "rule_id": rule["id"],
        "created_at": _now(),
        **meta,
    }
    state["decoys"].append(record)
    _save_state(state)
    return record


def list_planted() -> list[dict[str, Any]]:
    return _load_state()["decoys"]


def remove(name: str) -> dict[str, Any]:
    """Undo exactly what `plant` appended, refusing if the file moved on."""
    state = _load_state()
    record = next((d for d in state["decoys"] if d["name"] == name), None)
    if record is None:
        raise SystemExit(f"no decoy named {name!r}")

    path = Path(record["path"])
    if not path.exists():
        # Already gone; drop the bookkeeping rather than failing.
        pass
    else:
        current = path.read_text(encoding="utf-8", errors="replace")
        if not current.endswith(record["appended"]):
            raise SystemExit(
                f"refusing: {path} no longer ends with what canary planted "
                "(someone edited it since). Remove the block by hand, then run "
                f"`agentmetry canary forget {name}` to drop the bookkeeping."
            )
        trimmed = current[: -len(record["appended"])]
        if not record["existed_before"] and trimmed.strip() == "":
            path.unlink()
        else:
            path.write_text(trimmed, encoding="utf-8")

    rules = _load_rules()
    rules["rules"] = [r for r in rules["rules"] if r.get("id") != record["rule_id"]]
    _save_rules(rules)

    state["decoys"] = [d for d in state["decoys"] if d["name"] != name]
    _save_state(state)
    return record


def forget(name: str) -> dict[str, Any]:
    """Drop bookkeeping only. For the case where the file was edited by hand."""
    state = _load_state()
    record = next((d for d in state["decoys"] if d["name"] == name), None)
    if record is None:
        raise SystemExit(f"no decoy named {name!r}")
    rules = _load_rules()
    rules["rules"] = [r for r in rules["rules"] if r.get("id") != record["rule_id"]]
    _save_rules(rules)
    state["decoys"] = [d for d in state["decoys"] if d["name"] != name]
    _save_state(state)
    return record
