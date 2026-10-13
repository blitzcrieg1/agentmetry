# Codex hook output schemas

Copied unchanged from [openai/codex](https://github.com/openai/codex) (Apache-2.0),
`codex-rs/hooks/schema/generated/`, at commit
`806d2d1cc194548170a606946aa6c68e99927e58` (2026-10-08).

`tests/test_hook_decision_format.py` validates every decision the hook prints
for Codex against these, because Codex parses hook output with
`deny_unknown_fields` and runs the tool when it cannot. When Codex changes its
schema, refresh both files from the same path and rerun that test.
