"""Score the classifier against Atomic Red Team test commands.

    git clone --depth 1 --filter=blob:none --sparse         https://github.com/redcanaryco/atomic-red-team.git art
    git -C art sparse-checkout set --no-cone '/atomics/T*/T*.yaml' '/LICENSE.txt'
    python tools/score_atomic_red_team.py . art [--misses N]

Run it somewhere endpoint protection does not scan in real time (a container,
WSL, a CI runner). The test definitions hold attack command strings as text,
and Microsoft Defender flags some of the YAML files as malware on Windows.
Nothing is executed: each `atomics/T*/T*.yaml` is parsed as data, input
arguments are filled with their defaults, and the script asks whether the
classifier puts the expected label on each command. Requires PyYAML.

Atomic Red Team is Copyright (c) 2018 Red Canary, Inc., MIT License.
"""

import collections
import glob
import os
import sys
code, art = sys.argv[1], sys.argv[2]
show = int(sys.argv[sys.argv.index("--misses") + 1]) if "--misses" in sys.argv else 3
sys.path.insert(0, code)
import yaml  # noqa: E402  (after the sys.path insert above)
try:
    from agentmetry.core.audit.detection.traits import classify_tool_call
except ImportError:  # master, before tool kinds existed
    from agentmetry.core.audit.detection.traits import classify_command
    def classify_tool_call(qualified, text):
        return classify_command(text)
from agentmetry.core.audit.mitre import get_mitre_mapping  # noqa: E402

# technique prefix -> what "seen" means for this sensor
EXPECT = {
    "T1552.001": lambda tr, m: "credential_access" in tr or m.startswith("T1552"),
    "T1552.004": lambda tr, m: "private_key" in tr or "credential_access" in tr or m.startswith("T1552"),
    "T1552.003": lambda tr, m: "credential_access" in tr or m.startswith("T1552"),   # bash history
    "T1552.007": lambda tr, m: "credential_access" in tr or m.startswith("T1552"),   # container API
    "T1560.001": lambda tr, m: m.startswith("T1560"),
    "T1560.002": lambda tr, m: m.startswith("T1560"),
    "T1567.002": lambda tr, m: m.startswith("T1567"),
    "T1567": lambda tr, m: m.startswith("T1567") or "net_egress" in tr,
    "T1048": lambda tr, m: "net_egress" in tr or m.startswith(("T1071", "T1567", "T1048")),
    "T1041": lambda tr, m: "net_egress" in tr or m.startswith(("T1071", "T1041")),
    "T1053.003": lambda tr, m: m.startswith("T1053.003"),
    "T1053.005": lambda tr, m: m.startswith("T1053.005"),
    "T1140": lambda tr, m: m.startswith("T1140") or "encoded_cmd" in tr,
    "T1105": lambda tr, m: bool({"fetch_to_file", "staging_fetch", "net_egress", "raw_ip_fetch"} & set(tr)),
    "T1070.004": lambda tr, m: "delete_cmd" in tr,
    "T1485": lambda tr, m: "delete_cmd" in tr or m.startswith("T1485"),
    "T1027": lambda tr, m: "encoded_cmd" in tr or m.startswith(("T1027", "T1140")),
    "T1046": lambda tr, m: m.startswith("T1046"),
    "T1595": lambda tr, m: m.startswith("T1595"),
    "T1059.004": None, "T1059.001": None,  # every shell call is this; not scored
}
EXEC_TOOL = {"sh": "Bash", "bash": "Bash", "powershell": "PowerShell", "command_prompt": "shell.run"}

def fill(cmd, args):
    for k, v in (args or {}).items():
        cmd = cmd.replace("#{%s}" % k, str((v or {}).get("default", "")))
    return cmd

rows = collections.defaultdict(lambda: [0, 0, []])
skipped = collections.Counter()
for path in sorted(glob.glob(os.path.join(art, "atomics", "T*", "T*.yaml"))):
    doc = yaml.safe_load(open(path, encoding="utf-8"))
    tech = str(doc.get("attack_technique") or "")
    key = next((k for k in EXPECT if tech == k or tech.startswith(k + ".")), None)
    if key is None or EXPECT[key] is None:
        continue
    for t in doc.get("atomic_tests") or []:
        ex = t.get("executor") or {}
        tool = EXEC_TOOL.get(ex.get("name"))
        cmd = ex.get("command")
        if not tool or not cmd:
            skipped[ex.get("name") or "none"] += 1
            continue
        cmd = fill(cmd, t.get("input_arguments"))
        traits = classify_tool_call(tool, cmd)
        m = (get_mitre_mapping(tool, cmd) or {}).get("technique_id") or ""
        r = rows[key]
        r[0] += 1
        if EXPECT[key](traits, m):
            r[1] += 1
        else:
            r[2].append((t.get("name"), ex.get("name"), " ".join(cmd.split())[:150], traits, m))
tot = sum(r[0] for r in rows.values())
seen = sum(r[1] for r in rows.values())
print(f"Atomic Red Team tests scored: {tot}, seen: {seen} ({100*seen/max(tot,1):.0f}%)  skipped executors: {dict(skipped)}")
for k in sorted(rows):
    n, s, miss = rows[k]
    print(f"  {k:10} {s:3}/{n:<3} {100*s/n:4.0f}%")
    for name, ex, cmd, tr, m in miss[:show]:
        print(f"       MISS [{ex}] {name[:60]}: {cmd!r} traits={tr} mitre={m}")
