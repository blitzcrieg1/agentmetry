# Literal shell writes and policy limits

The shipped tool policy defaults to `log`. A policy match is enforced only by a
supported pre-hook in `block` mode. A post-hook records a match after execution
and cannot undo it. These rules are guardrails, not an operating-system boundary.

The recursive-delete rule recognizes `rm -rf`, `rm -fr`, separated `-r -f`
flags and `--recursive --force` in the option prefix. It does not claim to
recognize every deletion program, alias, wrapper or expansion.
The existing `rm -rf` substring match is retained and can match quoted examples.

The shell agent-config rule uses `shell_write_pattern` to match literal write
destinations rather than any occurrence of a filename. It recognizes ordinary
output redirects, `tee`, `truncate`, `touch`, remove/move operands, copy/install
destinations, and `sed` with an in-place option. Literal paths in short Python
`-c` programs are inspected for `open` with a write-capable mode, Path writes,
and selected remove/rename calls. No shell or embedded program is executed by
the evaluator. Reads, backups made with `cp`, and quoted examples stay allowed.
The existing file-edit rule still covers direct file-edit tools.

This is intentionally incomplete. Variable expansion, cwd tracking, aliases,
indirect paths, shell wrappers, concatenated quoting, scripts supplied through
heredocs and arbitrary programs are not resolved. PowerShell-specific mutation
commands are not parsed. A path match is an attempted policy violation, not proof
that a file was modified. Legitimate maintenance can also match a deny policy.

The git-hook path rule accepts whitespace before a relative `.git/hooks/...`
path. Its existing path-based behavior remains conservative and can also match
a shell read of a hook file. This change does not make that rule a full write
analyzer.

Agentmetry runs with the operator's privileges. Rules cannot stop arbitrary code
running as that user from disabling hooks, stopping the recorder or rewriting
local files. A separate recorder account is tracked in
[#313](https://github.com/blitzcrieg1/agentmetry/issues/313).
