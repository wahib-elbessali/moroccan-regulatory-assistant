# Partition of the work

The building work is split into 7 parts of comparable load, developed in parallel thanks to the contracts and the fakes. Each part is owned by one group. The system overview, the layers and the flows are drawn in [`architecture.md`](architecture.md); each part's details are in its spec in [`specs/`](specs/).

---

## The 7 parts

### P1 · Ingestion — `src/ingestion/`

**Hard core:** clean extraction of Arabic text from PDFs, OCR when needed, splitting by article.

- Public corpus (~500 pages) + 5–6 fictional internal documents + sample private uploads
- Page-by-page extraction, quality check, OCR through `OCRClient`, extraction cache
- `normalize_ar` (invisible marks, diacritics, tatweel, alef forms, ى/ي, ة), used by P1, P2, P3, P4 and P6
- One chunk per article with its heading hierarchy, `total_chunks`, source and date; ingestion pipeline with statuses; `seed` command line

**PDF requirements:** F-ING-01, 02, 03, 06, 07 · F-SEC-03

### P2 · Retrieval — `src/retrieval/`

**Hard core:** hybrid search with the visibility filter applied inside both indexes, before the search.

- Qdrant (bge-m3) as the only store of chunks; BM25 rebuilt from Qdrant and re-checked against it
- RRF fusion, re-ranking, embedding text with the title and the headings
- Hide / show / change the rights of a document; `/search` route

**PDF requirements:** F-ING-04, 05 · F-RET-01, 02, 03 · F-SEC-04

### P3 · Orchestration — `src/agents/orchestrator/`

**Hard core:** the LangGraph graph — decomposition, grading, bounded corrective loop, live narration.

- **Planner:** sub-questions, need for the web
- **Grading and reformulation:** relevant passages, retry (at most 3 searches per sub-question)
- Token limits; calls the web agent with the question as typed
- `/ask` route and SSE stream (thinking, answer, error, done); `detect_language`

**PDF requirements:** F-AGT-01, 02, 03, 04, 07 · F-GEN-03

### P4 · Answer and verification — `src/agents/answer/`

**Hard core:** a Juge that checks every claim against an excerpt really present in the source.

- **Rédacteur:** answer with numbered citations, in French or standard Arabic
- **Juge:** verification, excerpt checked in the text, confidence, "I don't know"
- Web notice on answers that use the web
- **Narrator:** the sentences of the thinking block; defence against prompt injection (documents are data)

**PDF requirements:** F-AGT-05, 06 · F-GEN-01, 02 · F-UI-03 (texts)

### P5 · Identity and access — `src/api/`, `src/core/security.py`, `src/core/audit.py`, `src/core/db/`

**Hard core:** a reliable `UserContext` on every request; document rights published without ever being visible to the wrong role.

- FastAPI skeleton, `get_*` registry, test fixtures; PostgreSQL and migrations
- JWT + Argon2 authentication; roles `admin` / `editeur` / `lecteur`; account requests
- Upload, statuses, publication, deletion; web search switch per role; audit log
- Mandatory test (a) end to end: no chunk of another role or another user is ever retrieved

**PDF requirements:** F-SEC-01, 02, 05, 06, 07, 12a · T-07, T-08, T-13 → 15

### P6 · Sovereignty and web isolation — `src/core/llm/`, `src/core/leak/`, `src/agents/web/`, `services/`

**Hard core:** the leak filter on outgoing web queries.

- `docker compose`; `internal`, `front` and `egress` networks; `make models` for offline use
- LLMs, embeddings, re-ranker and OCR served locally; `LLMClient`, `ModelsClient`, `OCRClient`
- **Web agent:** three switches, generic query; `web-search` container + SearxNG
- Fingerprint index; mandatory test (b): no web query contains corpus text

**PDF requirements:** F-SEC-08 → 11, 12b · T-04, T-06, T-11, T-12, T-16

### P7 · Interface — `src/ui/`

**Hard core:** the live SSE stream, right-to-left display, no document text ever displayed as HTML.

- Chat with session history, thinking block, answer, clickable citations, confidence
- Web search toggle; upload and status follow-up; document list and deletion
- Account request form; administration screens
- Works without internet (Arabic font included); stack chosen by P7

**PDF requirements:** F-UI-01, 02, 03, 04

---

## Contracts between parts

| Contract | Provided by → used by | Fake until the real one is ready |
|---|---|---|
| `Chunk` · `sample_chunks.jsonl` (~20 chunks) | P1 → P2, every test | The sample chunks themselves |
| `Ingestion.ingest / delete` · `normalize_ar` | P1 → P5 · P2, P3, P4, P6 | `FakeIngestion` (loads the sample chunks) |
| `Retrieval.index / search / update_roles / hide / show / delete` | P2 → P1, P3, P5 | `FakeRetrieval` (JSONL file, word overlap, same filter) |
| `Orchestrator.run` → SSE events of `/ask` · `detect_language` | P3 → P7 · P1, P4 | `FakeOrchestrator` (3 thinking events, a fixed answer) |
| `ProcessEvent` (plan, search, grade, reformulate, web, write) | P3 → P4 (narrator) | — |
| `Writer.write(…, emit)` → `Answer` + `verify` event · `Narrator.narrate` | P4 → P3 | `FakeWriter`, `FakeNarrator` |
| `UserContext` · `DocumentRights` · `Audit` | P5 → everyone | Fixtures `lecteur_ctx`, `editeur_ctx`, `admin_ctx`, `other_lecteur_ctx` · `FakeDocumentRights`, `FakeAudit` |
| `LLMClient` · `ModelsClient` · `OCRClient` | P6 → P3, P4 · P2 · P1 | Fakes: scripted replies, deterministic vectors, fixed OCR sentence |
| `LeakIndex` · `WebAgent.lookup` | P6 → P1, P5 · P3 | `FakeLeakIndex`, `FakeWebAgent` (respects the three switches) |

---

## Outside the partition

- Repository management, handled separately.
- The evaluation set and metrics (F-EVA).

## PDF requirements not planned for these two weeks

All are S or C; every M requirement is covered.

- Conversational memory (F-AGT-08), routing between direct / simple / multi-step answers (F-AGT-09), agents in parallel (F-AGT-10)
- Word-by-word answer streaming (F-GEN-04): the answer is sent only after the Juge; the thinking is streamed live
- Metadata filters (F-RET-04), multi-query and HyDE (F-RET-05), GraphRAG (F-RET-06)
- URL ingestion (F-ING-08), thumbs up / down (F-UI-05), Langfuse dashboard (F-EVA-04)

## Partly covered (S)

- Audit log (F-SEC-07): who, which question, when — not the list of documents consulted
- Agent tools (F-AGT-07): corpus search and web search — no calculator, no full-page reading
- Answer language (F-GEN-03): French and Arabic; a question in English is answered in French
