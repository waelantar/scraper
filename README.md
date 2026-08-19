# The Polyglot Engine

> A multithreaded web crawler built in **pure Python (standard library only)** feeding a **TypeScript agent terminal**
> with a crash-safe, append-only **branching session tree**. Two runtimes, one SQLite contract.

<!-- CI badge goes here once GitHub Actions is set up (Phase D):
[![CI](https://github.com/<you>/polyglot-engine/actions/workflows/ci.yml/badge.svg)](../../actions) -->

**Status:** 🚧 In active development — see the [Roadmap](#roadmap).

---

## Overview

The Polyglot Engine is a two-process system that deliberately avoids heavy frameworks to demonstrate the
fundamentals underneath them:

- A **Python crawler** downloads and parses web pages concurrently using a **hand-built thread pool** and a
  **thread-safe bounded queue** (no `concurrent.futures`, no `requests`, no `scrapy`), caching results in
  SQLite.
- A **TypeScript agent terminal** reads that cache and provides an interactive, **forkable** conversation over the
  crawled data. The entire session is stored as an append-only JSONL journal with per-line checksums, so a
  crash mid-write is detected and recovered rather than silently corrupting state.

The two halves are fully decoupled: they communicate **only** through a shared SQLite schema.

## Architecture

```
┌────────────────────────────┐   writes    ┌────────────────────────────────┐
│   PYTHON CRAWLER            │────────────▶│   TypeScript CLI               │
│   (stdlib, multithreaded)   │   SQLite    │   (branching session tree)     │
│                            │  (shared    │                                │
│  seed URLs                 │  contract)  │  reads crawled pages           │
│    → thread-safe queue      │             │  interactive shell:            │
│    → custom thread pool      │             │   /query /view /fork /tree     │
│      ├─ fetcher threads     │             │  every turn appended to an     │
│      └─ parser threads      │             │  append-only JSONL journal     │
│    → SQLite page cache       │             │  (checksums + crash-safety)    │
└────────────────────────────┘             └────────────────────────────────┘
        Python process                            Node process
                    \________ SQLite is the only integration point ________/
```

## Tech Stack

| Side | Stack | Notable constraint |
|------|-------|--------------------|
| Crawler | Python 3.11+, **standard library only** | Concurrency primitives are hand-rolled |
| Agent terminal | TypeScript / Node.js 22+ | Unified terminal UI, SQLite reads, and tree persistence |
| Shared | SQLite | The integration contract |

## Project Structure

```
polyglot-engine/
├─ python_engine/          # Python crawler (stdlib only)
│   ├─ __init__.py
│   ├─ bounded_queue.py    # thread-safe bounded MPMC queue (two-condition)
│   ├─ thread_pool.py      # fixed-size worker pool built on the queue
│   ├─ fetcher.py          # URL fetcher (stdlib urllib) → FetchResult
│   ├─ parser.py           # HTML parser (stdlib html.parser) → ParsedPage
│   ├─ cache.py            # SQLite page cache (schema owner, thread-safe)
│   ├─ orchestrator.py     # Crawler: wires it all together (termination + dedup)
│   └─ politeness.py       # robots.txt checker + per-domain rate limiter
├─ ts-cli/                 # TypeScript CLI (Phase 2) — ESM, Node 20+
│   ├─ package.json        # tsx (dev) + tsc (build) scripts, "type": "module"
│   ├─ tsconfig.json       # NodeNext, strict
│   └─ src/
│       ├─ index.ts        # entry point (stub)
│       └─ smoke.ts        # cross-language check: reads the Python-written SQLite
├─ data/                   # Generated SQLite database (gitignored)
│   └─ .gitkeep
├─ tests/                  # Test suite
├─ .github/workflows/      # CI (Phase D)
├─ README.md
└─ LICENSE
```

## Getting Started

### Prerequisites
- Python 3.11+
- Node.js 22+ *(the CLI uses Node's built-in SQLite module)*

### One terminal, one product command

From the project root, run the launcher for your platform once to create the virtual environment and install the
development tools. Then run its short form to open the product directly.

| Platform | First time | Open the agent terminal |
|---|---|---|
| Windows | `.\polyglot.cmd setup` | `.\polyglot.cmd` |
| macOS / Linux | `sh ./polyglot setup` | `sh ./polyglot` |

On macOS/Linux, `./polyglot` also works after the file has executable permission (for example,
`chmod +x polyglot`). The repository keeps this script’s line endings as LF for shell compatibility.

The **Polyglot Engine** terminal opens with a command prompt. It dispatches crawler work to Python and reads
the SQLite cache plus branching journal through TypeScript, without requiring you to change terminals.

```text
crawl https://books.toscrape.com/ --max-depth 1 --max-urls 20
search travel
open <a URL returned by search>
This category pattern needs a second look.
tree
exit
```

Plain text is saved as a durable research note. `branch <message-id>` copies a path into a new branch;
`/query`, `/view`, `/fork`, `/tree`, `/status`, and `/exit` remain available as aliases.

To run a crawler without opening the terminal, use the matching launcher:

```powershell
# Windows
.\polyglot.cmd crawl --seed "https://books.toscrape.com/" --max-depth 2 --max-urls 100

# macOS / Linux
sh ./polyglot crawl --seed "https://books.toscrape.com/" --max-depth 2 --max-urls 100
```

## Testing

Run the complete terminal-first verification gate with:

```powershell
# Windows
.\polyglot.cmd check

# macOS / Linux
sh ./polyglot check
```

It runs the offline Python suite, TypeScript type-check, a clean TypeScript build, and the compiled Node suite.
The crawler itself still has zero runtime Python dependencies; `pytest` is a development dependency installed by
`.\polyglot.cmd setup`.

Two things worth calling out:

- **Concurrency is tested for real.** The queue suite includes a `maxsize=1` multi-consumer stress test that
  would deadlock (and hang) under a naive single-condition design — a regression guard, not just a happy path.
- **Network code is tested offline.** The fetcher's unit tests mock the `urllib` boundary, so they're fast,
  deterministic, and run without internet; a few live smoke tests sit behind a `network` marker that CI skips.

- **The TypeScript gate is separate from the runner.** `npm.cmd run type-check` and
  `npm.cmd run build` pass for the storage, tree, fork, CLI, and agent-terminal layers. The compiled suite
  passes with Node's native runner (`node --test dist\*.test.js`): 34 tests across command parsing, a scripted
  agent-terminal session, storage, tree, fork, data-model, REPL integration, and tree rendering.

## Design Decisions

The crawler owns the SQLite schema because it is the producer of that contract; the TypeScript side only
validates and reads it. Using the URL as the page primary key makes deduplication and upserts express the
domain identity directly, while SQLite keeps the two processes decoupled without introducing an API server.

The crawler's queue uses condition variables for real blocking and backpressure. It is not truly lock-free:
the GIL may make individual deque operations atomic in CPython, but coordination and shutdown still require
synchronization. The crawler also tracks in-flight work separately from queue emptiness, because a worker can
still enqueue children after it removes the last current URL.

The session journal is append-only JSONL so a new state transition does not rewrite the entire history. Each
line hashes the serialized payload with `checksum` excluded; loading stops at the first malformed or mismatched
line and truncates the remaining tail. A per-journal lock file created with the exclusive `wx` flag prevents
concurrent writers, and an age threshold provides a recovery path for locks left by a crashed process.

The tree engine keeps the flat journal useful by indexing entries by ID and following `parentId` links from the
persisted leaf to the root. A `leaf` entry records navigation explicitly, so reload does not confuse the latest
physical line with the current conversation position. `buildContext` is a pure projection of that path: it
filters the lineage to messages, rejects missing parents, and detects cycles instead of hanging on corrupt data.
`append()` returns the checksummed entry so the in-memory index and the durable JSONL record stay identical.

Forking is implemented as a same-journal branch operation for Core C12. The engine copies the selected
root→node path, re-mints every copied ID, rewrites each copied `parentId` through an old→new ID map, appends the
copies in order, and persists a new leaf at the copied tip. The original branch remains untouched. This is a
deliberate smaller scope than the reference study's new-session-file fork; the current implementation targets
message paths, while remapping metadata references such as `LabelEntry.targetId` is deferred.

The C13 CLI keeps the interactive layer thin. `index.ts` loads the journal and tree, while `Repl` owns the
readline loop and dispatches `/query`, `/view`, `/fork`, `/tree`, `/status`, and `/exit`. SQLite queries use
parameters, messages go through the tree engine's append operation, and the REPL closes both readline and its
lazy database connection in `finally`. `SESSION_PATH` and `DB_PATH` make the scripted integration test use
isolated temporary files without changing the normal shared `data/` defaults.

The C14 renderer is a pure projection: `renderTree(entries, leafId)` builds a parent→children lookup, treats
missing-parent entries as roots, orders roots and siblings by timestamp with an ID tie-breaker, and emits
`├─`/`└─` ASCII connectors. The current leaf receives a `*` marker, while `Repl` only adapts the returned string
for `/tree`. The reference study recommends flattening single-child chains; that presentation polish is explicitly
deferred while the core renderer focuses on complete, deterministic tree output.

The agent terminal is a presentation and dispatch layer above those core pieces, not a second implementation of
them. `agent.ts` starts `AgentConsole`; `crawl <url>` spawns `python -m python_engine crawl` in the project root
and streams its output back into the same terminal. Search, page preview, notes, forking, tree rendering, and
status use the existing SQLite and `TreeEngine` contracts. This keeps the product experience unified while the
language boundary remains explicit and testable. TTY sessions use a coloured wordmark and prompt; piped sessions
automatically use plain output, allowing the agent flow to be script-tested as well.

## What I Learned

- A checksum must exclude itself from the hashed payload, and append/load must use the same serialization
  shape or every reload becomes a false corruption.
- A partial JSONL tail must be truncated at a UTF-8 byte offset, not a JavaScript character offset; otherwise
  multibyte content can make recovery cut the valid prefix incorrectly.
- A lock test needs two storage instances. Locking twice through one instance only tests that the method is
  idempotent, not that another writer is excluded.
- `tsx` executes stripped TypeScript but does not replace `tsc`. When the local `tsx` launcher failed before
  loading tests with `uv_os_get_passwd returned ENOMEM`, the compiled JavaScript was still verified with Node's
  native test runner.
- A persisted leaf is an event, not an assumption about file order. Replaying the latest `leaf.targetId` keeps
  a branch jump durable even when later lines belong to another physical branch.
- Parent links need a visited set. A missing parent is a clear corruption error; a cycle must also fail clearly
  instead of turning a path reconstruction into an infinite loop.
- When a storage method returns a transformed record, callers should retain that returned record. Keeping the
  original entry with an empty checksum created an in-memory/disk mismatch, so C11 changed `append()` to return
  the checksummed entry.
- Forking is copying plus re-minting, not pointing at the same IDs. Reusing IDs would make the copied branch and
  original branch collide in the `Map` index and would make later parent traversal ambiguous.
- A fork test should verify both sides of the operation: the new branch's context and leaf, and the complete
  original path's IDs/content after the copy. The fork is only correct if the old branch remains independently
  addressable.
- A CLI integration test must exercise the process boundary, not only call helper methods. The test creates an
  isolated SQLite cache and journal, drives stdin through the compiled Node entry point, and verifies query,
  message append, fork, tree output, status, and clean exit together.
- ES modules do not provide CommonJS `__dirname`; test paths need to derive from `import.meta.url`. A fast child
  process can also emit `close` before a test attaches its listener, so lifecycle promises must be registered
  immediately after spawning the process.
- A renderer should not silently drop an entry whose parent is missing. Treating that entry as an orphan root keeps
  damaged or partially migrated data visible, while a separate `visited` set prevents repeated traversal.
- ASCII tree connectors depend on sibling position: every non-final root or child uses `├─`, and only the final
  one uses `└─`. Timestamp ordering with an ID tie-breaker keeps the display chronological but deterministic.
- Keeping tree rendering as a pure function makes branch layout easy to test without starting the CLI; the REPL
  can remain responsible only for fetching the entries and printing the result.

## Roadmap

**Core (must-ship):**
- [x] C1 — SQLite schema / integration contract
- [x] C2 — Thread-safe bounded queue
- [x] C3 — Custom thread pool
- [x] C4 — Fetcher worker
- [x] C5 — Parser worker
- [x] C6 — SQLite cache layer (upsert + skip-if-seen)
- [x] C7 — Crawler orchestrator + graceful shutdown
- [x] C8 — Politeness (robots.txt + rate limiting)
- [x] CROSS — TypeScript reads the Python-written SQLite (cross-language contract proven end-to-end)
- [x] C9 — TypeScript data model (discriminated-union entry types + type-level tests)
- [x] C10 — TypeScript JSONL storage (checksums, crash-tail truncation, single-writer lock)
- [x] C11 — Tree engine (path reconstruction, persisted leaf, context projection)
- [x] C12 — Fork (copy path, re-mint IDs, rewrite parents, move leaf)
- [x] C13 — Interactive CLI (query, view, fork, tree, status, journal-backed messages)
- [x] C14 — Tree render (ASCII branches, orphan roots, chronological siblings, current-leaf marker)
- [ ] C15 — Tests + documentation

**Stretch:** recursive crawl with dedup, branch summarization, snapshot+tail loading, WAL mode, packaging.

## License

Released under the [MIT License](LICENSE).
