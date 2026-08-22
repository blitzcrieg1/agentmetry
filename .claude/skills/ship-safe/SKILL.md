---
name: ship-safe
description: Pre-flight a change before opening a pull request on Agentmetry. Use before committing or opening a PR, when the user says ship it, or to check whether a change is safe to land during the detection freeze.
---

# Ship safe

Five checks. The first one is the one that matters, because it is the only
failure here that costs four weeks instead of four minutes.

## 1. Did this touch a frozen file?

```bash
git diff --name-only master... | grep -E "detection/(rules|traits|engine)\.py|audit/mitre\.py|policies/detection/manifest\.yaml"
```

Any output means **stop and tell the user**. Those files are hashed into the
ruleset fingerprint; changing one restarts the dogfood clock, which is at 2 of 4
with an earliest close of 2026-09-04. The freeze lifts 2026-09-05.

Confirm the fingerprint independently, because a file can be touched without the
grep catching a rename:

```bash
cd apps/orchestrator && .venv/Scripts/python.exe -c "from agentmetry.core.audit.dogfood import ruleset_fingerprint; print(ruleset_fingerprint()[:16])"
# expect 56ad3de1ad8533cf
```

## 2. Tests, lint, benchmark

From `apps/orchestrator`:

```bash
.venv/Scripts/python.exe -m ruff check agentmetry tests
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m agentmetry.cli benchmark
```

The benchmark must report **0 missed and 0 false positives**. A release that
cannot detect what it claims to detect is the one release worth blocking.

If the dashboard changed, also `cd apps/dashboard && npm run lint && npm run test && npm run build`.

## 3. Secrets and local files

```bash
git diff --cached --name-only
```

Reject: `.env`, `drivers.json`, anything under `apps/orchestrator/data/`, any
`.jsonl` trail, `.coverage`. `.agents/hooks.json` holds machine-specific
absolute paths and is usually dirty; do not stage it unless the task is hooks.

Scan the diff itself for anything key-shaped before pushing. CI runs gitleaks,
but a secret caught after it reaches the remote is already a rotation.

## 4. Claims still true?

If the change touches a number that appears in `README.md`, the site, or
`docs/`, check the claim tests still pass. `tests/test_readme_claims.py` pins
corpus counts, CLI coverage of the docs, and the attribution paragraph.

If the change adds a public claim about the code, add a test that checks it. The
README once overstated its own weakness for weeks and three audits repeated it.

## 5. Then open a PR

`master` is protected: five required checks, `enforce_admins` on, so a direct
push is rejected. Branch, push, open a PR.

Match the commit-message voice in `git log`: what changed, what was wrong
before, what that cost. Not a summary of the diff, which the diff already is.

**No em-dashes** in anything that will be read publicly.

## Rule

**Commit only when the user asks.** Run the checks, report the result, wait.
