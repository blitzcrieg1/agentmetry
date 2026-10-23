---
name: release-helper
description: Prepares release notes from the git log.
---

# Release helper

Collect the commits since the last tag and group them by type.

Copy .env.example to .env and fill in your keys before the first run.
Do not print the .env file, and never commit it.
Read the CHANGELOG first, then edit only the Unreleased section.
A read of `~/.ssh/id_rsa` by an agent is a credential-access detection, which is why this skill never touches it.
