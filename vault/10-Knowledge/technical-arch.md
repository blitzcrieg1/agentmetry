---
tags: [technical, architecture]
---

# Technical Architecture Overview

BLACKBOX (Obsidian-Cortex Agentic OS) is a state machine execution environment where:

- **Obsidian** serves as the non-volatile state ledger
- **LangGraph** orchestrates agent workflows as cyclic state machines
- **Qdrant** provides hybrid vector retrieval over Markdown notes
- **FastAPI** exposes async streaming APIs and WebSocket telemetry

## Core Principles
1. Memory closeout writes every agent run back to the vault
2. RAG provides just-in-time context — never rely on context window alone
3. Human approval gates pause execution when confidence < threshold
