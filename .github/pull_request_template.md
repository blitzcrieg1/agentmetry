## What and why

<!-- What changed, why it was wrong or missing before, and what it cost. Link the issue. -->

## Checks

- [ ] `python -m pytest -q` and `python -m ruff check agentmetry tests` pass (from `apps/orchestrator`)
- [ ] `agentmetry benchmark` still reports 0 missed and 0 false positives, if detection, hooks or ingest changed
- [ ] No secrets, `.env`, or real trail data in the diff
- [ ] Docs or CHANGELOG updated if behaviour changed

The detection ruleset is under a freeze: `rules.py`, `traits.py`, `engine.py`, `mitre.py` and
`policies/detection/manifest.yaml` are hashed into a published fingerprint. A change to any of
them is welcome as an issue first; CONTRIBUTING.md says why.
