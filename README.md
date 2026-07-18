# The Polyglot Engine

> A multithreaded web crawler built in **pure Python (standard library only)** feeding a **TypeScript CLI**
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
- A **TypeScript CLI** reads that cache and provides an interactive, **forkable** conversation over the
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
| CLI | TypeScript / Node.js 20+ | Tree & persistence logic self-contained |
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
│   └─ orchestrator.py     # Crawler: wires it all together (termination + dedup)
├─ ts-cli/                 # TypeScript CLI (Phase 2)
│   └─ src/
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
- Node.js 20+ *(for the CLI, Phase 2)*

### Setup
```bash
# clone, then from the project root:
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
```
No `pip install` is required — the crawler uses only the standard library.

### Run
The crawler runs entirely on the standard library. From the project root:

```python
from python_engine.orchestrator import Crawler

crawler = Crawler(
    seed_urls=["https://books.toscrape.com/"],
    db_path="data/pages.db",
    num_workers=4,
    max_depth=1,          # seed + one hop of links
    same_domain=True,     # stay on books.toscrape.com
    max_urls=50,          # politeness cap while learning
)
crawler.crawl()           # blocks until the frontier is drained
print(crawler.get_stats())  # {crawled, errors, visited, ...}
```

Crawled pages land in the SQLite `pages` table, ready for the TypeScript CLI (Phase 2) to read.

## Testing

The test suite uses **pytest** (a dev dependency only — the crawler itself has zero runtime deps).

```bash
pip install -r requirements-dev.txt   # first time only
python -m pytest                       # fast, offline unit tests (network tests skipped by default)
python -m pytest -m network            # opt in to the live-network integration tests
```

Two things worth calling out:

- **Concurrency is tested for real.** The queue suite includes a `maxsize=1` multi-consumer stress test that
  would deadlock (and hang) under a naive single-condition design — a regression guard, not just a happy path.
- **Network code is tested offline.** The fetcher's unit tests mock the `urllib` boundary, so they're fast,
  deterministic, and run without internet; a few live smoke tests sit behind a `network` marker that CI skips.

## Design Decisions

<!--
  TODO — WRITE THIS YOURSELF. This section is the most valuable part of the README for a portfolio,
  and it's your interview prep. For each decision, write 2-3 sentences on WHY you made it and what the
  alternative was. Prompts to answer:

  - Why is `url` the PRIMARY KEY of the pages table (instead of a surrogate auto-increment id)?
  - Why SQLite as the boundary between the two processes, rather than a REST API or a JSON file?
  - Why an append-only JSONL journal for session state instead of editing records in place?
  - Why per-line checksums and a single-writer lock?
  - Is the "lock-free" queue truly lock-free? What role does the GIL play?
  - Why does the bounded queue use TWO condition variables on ONE lock instead of a single condition?
    (What concurrency bug does that prevent, and how did you prove it?)
  - Why does the thread pool's `submit()` never hold a lock while calling `put()`? (What deadlock does that
    avoid under backpressure?) And why are the workers non-daemon?
  - Why does `fetch()` return a `FetchResult` instead of raising on errors? (How does that simplify the worker
    threads that call it?) And how do you test network code without hitting the network?
  - How does the parser resolve links, and what's the difference between a root-relative (`/x`) and a
    path-relative (`x`) href? Why filter by the resolved URL scheme instead of the raw href?
  - How is the SQLite cache made thread-safe when many worker threads write at once? (Why a connection per
    call instead of one shared connection + lock?) Why must the `pages` schema have a single owning module?
  - How does the crawler know when it's *finished*, given that an empty queue doesn't mean done? (Explain the
    in-flight counter.) Why are `attempted`, `crawled`, and `errors` three separate counters?

  Write these in your own words. If you can't yet, that means the concept isn't solid — revisit it.
-->

## What I Learned

<!--
  TODO — WRITE THIS YOURSELF as you go. A short, honest list of the concepts this project taught you
  (concurrency, the GIL, append-only logs, crash safety, TDD, git workflow...). Recruiters love this
  section; it signals self-awareness and growth.
-->

## Roadmap

**Core (must-ship):**
- [x] C1 — SQLite schema / integration contract
- [x] C2 — Thread-safe bounded queue
- [x] C3 — Custom thread pool
- [x] C4 — Fetcher worker
- [x] C5 — Parser worker
- [x] C6 — SQLite cache layer (upsert + skip-if-seen)
- [x] C7 — Crawler orchestrator + graceful shutdown
- [ ] C8 — Politeness (robots.txt + rate limiting)
- [ ] C9–C14 — TypeScript CLI: data model, JSONL storage, tree engine, fork, commands, rendering
- [ ] C15 — Tests + documentation

**Stretch:** recursive crawl with dedup, branch summarization, snapshot+tail loading, WAL mode, packaging.

## License

Released under the [MIT License](LICENSE).
