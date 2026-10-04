# 0014. numpy exact search instead of LanceDB; embeddings on CPU

- Status: Accepted
- Date: 2026-10-04
- Source: docs/DLENS_SPEC.md, Section 0, row 24
- Implemented in: S07 (B1)

## Context

Corpora have 400–20,000 chunks. Ollama keeps the 6 GB GPU busy during runs. LanceDB is a heavy dependency for real users.

## Decision

Dense vectors are stored as `.npy` and searched exactly with numpy. `bge-small-en-v1.5` embeddings run on CPU; the `retrieval` extra installs the CPU torch wheel.

## Consequences

- Search is milliseconds at this size, exact (no ANN recall loss), and deterministic.
- `lancedb` leaves the `retrieval` extra when B1 lands; until then pyproject still lists it.
- Past about 1M chunks this would need revisiting (v1.3+ scale work).

## Alternatives rejected

- LanceDB: extra dependency, no benefit at this size.
- FAISS: install pain on Windows/macOS for no gain over exact search.
- GPU embeddings: compete with Ollama for VRAM.
