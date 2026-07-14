# Data Residency & Local-First Statement

**Product:** Agentmetry (Obsidian-Cortex Agentic OS)  
**Version:** operator-deployed, local-first appliance  
**Last updated:** 2026-07-07

---

## Summary

Agentmetry processes business data **on infrastructure you control**. The Obsidian vault, run ledger, event outbox, and optional local LLM (Ollama) stay on your machine or your LAN. No multi-tenant cloud backend is required for core operation.

This supports GDPR data-minimization and deployer-side EU AI Act arguments around **data residency** and **human oversight** — not a guarantee of compliance.

---

## Data locations

| Data | Default location | Leaves device? |
|------|------------------|----------------|
| Vault notes, PDFs, archives | `vault/` on disk | Only if *you* sync Obsidian to cloud |
| Run audit log | `apps/orchestrator/data/runs.jsonl` | No |
| Event outbox | `apps/orchestrator/data/events.db` | No |
| Embeddings (RAG) | Local Qdrant or configured URL | Your choice |
| LLM inference | Provider-dependent | See below |

---

## LLM provider modes

| Provider | Config | Data path |
|----------|--------|-----------|
| **Ollama** | `AGENTMETRY_LLM_PROVIDER=ollama` | Prompts/responses stay on localhost |
| **Gemini** | `AGENTMETRY_LLM_PROVIDER=gemini` | Google API — review Google DPA / terms |
| **Mock** | Tests only | No external calls |

**Recommendation for regulated client work:** Ollama for sensitive drafting; Gemini optional for low-risk triage when client contract allows.

---

## DPIA pointer (operator task)

When using Agentmetry on client PII:

1. List processing purposes (email triage, contract summarization, meeting notes).
2. Document legal basis and retention (vault + `30-Archive/`).
3. Record subprocessors (Google if Gemini enabled; none if Ollama-only).
4. Describe HITL controls (`approval_threshold: 1.1`, draft-only Gmail).
5. Attach monthly `agentmetry export --evidence` as technical annex.

Use your jurisdiction's DPIA template — this document is input, not a completed DPIA.

---

## Contact

Operator-maintained deployment. For the open-source project: see repo README.
