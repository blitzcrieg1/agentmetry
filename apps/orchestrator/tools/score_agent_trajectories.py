"""Replay public coding-agent trajectories through the classifier and the rules.

    python tools/score_agent_trajectories.py <orchestrator dir> <dataset> [--rows N] [--show N] [--cache DIR]

<dataset> is `swe-rebench` (nebius/SWE-rebench-openhands-trajectories, CC-BY-4.0)
or `swe-gym` (SWE-Gym/OpenHands-SFT-Trajectories, MIT). Rows are fetched from
the Hugging Face dataset viewer API as JSON, so no parquet reader is needed.

These are agents fixing GitHub issues in sandboxed repositories, so every
detection is a false positive by construction. That makes this the measure of
noise on agents other than the maintainer's: the dogfood trail is one person's
machine, and these are thousands of sessions nobody wrote to test a rule.

Each tool call becomes an Agentmetry tool event: `execute_bash` is `Bash`, and
`str_replace_editor` is `Read` (view), `Write` (create) or `Edit` (everything
else). Thinking and finish calls carry no action and are skipped.
"""
from __future__ import annotations

import collections
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import uuid

code, dataset = sys.argv[1], sys.argv[2]
rows_wanted = int(sys.argv[sys.argv.index("--rows") + 1]) if "--rows" in sys.argv else 200
show = int(sys.argv[sys.argv.index("--show") + 1]) if "--show" in sys.argv else 10
sys.path.insert(0, code)
try:
    import pydantic  # noqa: F401
except ImportError:
    # Only the opt-in off-hours rule reads settings, and it is off by default.
    # Without pydantic (a bare container), stand in for that one setting.
    import types

    _cfg = types.ModuleType("agentmetry.core.config")
    _cfg.settings = types.SimpleNamespace(detect_off_hours=False, business_tz="UTC", business_hours="09-18")
    sys.modules["agentmetry.core.config"] = _cfg
from agentmetry.core.audit.detection.engine import run_detections  # noqa: E402
from agentmetry.core.audit.mitre import get_mitre_mapping  # noqa: E402

try:
    from agentmetry.core.audit.detection.traits import classify_tool_call  # noqa: E402
except ImportError:  # master, before tool kinds existed
    from agentmetry.core.audit.detection.traits import classify_command  # noqa: E402

    def classify_tool_call(qualified, text):
        return classify_command(text)

SOURCES = {
    "swe-rebench": ("nebius/SWE-rebench-openhands-trajectories", "default", "train", 5),
    "swe-gym": ("SWE-Gym/OpenHands-SFT-Trajectories", "default", "train.success.oss", 50),
}
name, config, split, page = SOURCES[dataset]
_FN = re.compile(r"<function=([\w-]+)>(.*?)</function>", re.S)
_PARAM = re.compile(r"<parameter=([\w-]+)>(.*?)</parameter>", re.S)


CACHE = sys.argv[sys.argv.index("--cache") + 1] if "--cache" in sys.argv else ""


def fetch(offset, length):
    """One page of rows, from the local cache when --cache names a directory."""
    import os

    cached = os.path.join(CACHE, f"{dataset}-{offset}-{length}.json") if CACHE else ""
    if cached and os.path.exists(cached):
        with open(cached, encoding="utf-8") as fh:
            return json.load(fh)
    url = "https://datasets-server.huggingface.co/rows?" + urllib.parse.urlencode(
        {"dataset": name, "config": config, "split": split, "offset": offset, "length": length}
    )
    for attempt in range(8):
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                data = json.load(resp)
            if cached:
                os.makedirs(CACHE, exist_ok=True)
                with open(cached, "w", encoding="utf-8") as fh:
                    json.dump(data, fh)
            return data
        except Exception:
            time.sleep(5 + 10 * attempt)
    raise RuntimeError(f"could not fetch offset {offset}")


def calls(row):
    """(function name, arguments dict) for each tool call, in order."""
    if "trajectory" in row:
        for m in row["trajectory"] or []:
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    continue
                yield fn.get("name"), args
    else:
        for m in row.get("messages") or []:
            if m.get("role") != "assistant":
                continue
            for fm in _FN.finditer(m.get("content") or ""):
                yield fm.group(1), {k: v.strip() for k, v in _PARAM.findall(fm.group(2))}


def to_tool(fn, args):
    if fn == "execute_bash" and args.get("command"):
        return "Bash", str(args["command"])
    if fn == "str_replace_editor" and args.get("path"):
        sub = args.get("command")
        kind = "Read" if sub == "view" else "Write" if sub == "create" else "Edit"
        return kind, str(args["path"])
    return None


traits_seen = collections.Counter()
mitre_seen = collections.Counter()
rules = collections.Counter()
examples = collections.defaultdict(list)
n_rows = n_calls = 0
offset = 0
while n_rows < rows_wanted:
    data = fetch(offset, min(page, rows_wanted - n_rows))
    batch = [r["row"] for r in data.get("rows", [])]
    if not batch:
        break
    for row in batch:
        sid = str(uuid.uuid4())
        events = []
        for i, (fn, args) in enumerate(calls(row)):
            mapped = to_tool(fn, args)
            if not mapped:
                continue
            qualified, text = mapped
            traits = classify_tool_call(qualified, text)
            mitre = get_mitre_mapping(qualified, text)
            tool = {"qualified": qualified, "command": text, "traits": traits}
            if mitre:
                tool["mitre"] = mitre
                mitre_seen[mitre["technique_id"]] += 1
            traits_seen.update(traits)
            for t in traits:
                if t in ("credential_access", "private_key", "net_egress", "delete_cmd", "pipe_to_shell", "cloud_api") and len(examples[t]) < show:
                    examples[t].append(" ".join(text.split())[:140])
            events.append({
                "event_id": f"{sid}-{i}", "correlation_id": sid, "session_id": sid,
                "timestamp_utc": f"2026-01-01T00:{i // 60 % 60:02d}:{i % 60:02d}+00:00",
                "action": {"type": "tool_called", "outcome": "success"},
                "initiator": {"actor_type": "agent", "trigger": "manual"},
                "tool": tool,
            })
            n_calls += 1
        for det in run_detections(events):
            rules[(det.rule_id, det.severity)] += 1
            if len(examples["rule:" + det.rule_id]) < 3:
                ev = {e["event_id"]: e for e in events}
                examples["rule:" + det.rule_id].append(
                    " || ".join(" ".join(ev[e]["tool"]["command"].split())[:110] for e in det.event_ids[:2] if e in ev)
                )
        n_rows += 1
    offset += len(batch)

sessions_with = len(rules)
print(f"{dataset}: {n_rows} trajectories, {n_calls} tool calls")
print("detections by rule (all false positives here):")
for (rule, sev), n in rules.most_common():
    print(f"  {n:5}  {sev:8} {rule}")
crit_high = sum(n for (r, s), n in rules.items() if s in ("critical", "high"))
print(f"critical/high: {crit_high} across {n_rows} trajectories ({100 * crit_high / max(n_rows, 1):.1f} per 100)")
print("traits:", dict(traits_seen.most_common(12)))
print("mitre:", dict(mitre_seen.most_common(10)))
for k, v in sorted(examples.items()):
    print(f"-- {k}")
    for x in v:
        print("     ", x)
