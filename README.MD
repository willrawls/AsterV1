Here’s a short, practical README for an **Aster seed ingest** script that saves, deduplicates, and audits your seeds with sane defaults and quick fixes.

---
# README - Build Guide v1.1.0
Start here: [BuildGuide_v1](articles\BuildGuide_v1.md)
Then here: [BuildGuide_v1.1](articles\BuildGuide_v1.1.md)
Current definitions for v1.1 tasks are in [Tasks](tasks/v1.1/)

# README — Aster seed ingest (short)

## Purpose

Store Aster “seeds” reliably with:

* deterministic text canonicalization,
* exact‑duplicate blocking (SHA‑256 of normalized text),
* optional near‑duplicate tagging (MinHash/SimHash),
* an auditable `provenance_chain` persisted in SQLite.

## Quick start

1. Save the script as `aster_ingest.py` and run:

```bash
python aster_ingest.py
```

This demo writes `./aster_export/aster_seeds.db`, performs three ingest attempts, and exports `./aster_export/aster_seeds_content_hashed_YEAR-MONTH-DAY_.jsonl`.

```bash
python dump_db.py
```
This will dump the entire contents of "./aster_export/aster_seeds.db" which can be quite long. Check the .py file for parameters to cull the output.

The idea being you can seed.json1 files and upload them to you AsterV1 ChatGPT folder.

2. For production, import and call:

```python
from aster_ingest import SeedStore
store = SeedStore(db_path="aster_seeds.db")
store.insert_seed(content="...", source="...", meta={"topic":"..."} )
```

## Dependencies

* **Minimal (built‑in only):** Python 3.9+ → uses SimHash fallback.
* **Optional (better fuzzy):**

  ```bash
  pip install datasketch
  ```

  Enables MinHash + MinHashLSH for stronger near‑duplicate detection.

## Important knobs (defaults)

* `use_fuzzy`: `'auto'` (use `datasketch` if installed) | `'always'` | `'never'`
* `ngram` (5): char n‑gram size for MinHash; higher = coarser similarity.
* `num_perm` (128): MinHash permutations; increase for bigger corpora.
* `lsh_threshold` (0.85): Jaccard cutoff for “near‑duplicate.”
* **SimHash** Hamming cutoff (6): lower = stricter; raise for noisy text.

## Policy notes

* **Conservative (default):** exact dupes rejected (provenance appended to the original); near‑dupes get tagged, not merged. Good for continuity logs and audit trails.
* **Aggressive:** if confidence > 0.95, auto‑merge into earlier seed (the code supports a simple merge path).

## Debugging quick checklist

* “**Why was my seed rejected?**”
  Check the hash match:

  ```bash
  sqlite3 aster_seeds.db \
  "SELECT seed_id, content_hash, provenance_chain FROM seeds \
   WHERE content_hash LIKE 'sha256:%'"
  ```
* “**Why no fuzzy hits?**”
  Ensure `datasketch` is installed or allow SimHash fallback; with MinHash keep `num_perm` consistent across restarts (schema stores binary sketches).
* **Rebuild LSH after manual DB edits:**
  Delete the DB (or let the script rebuild), then rerun; for large sets, consider a persistent LSH.
* **Export for audit:**

  ```python
  store.export_jsonl('my_export.jsonl')
  ```

## Performance tips

* **<100k seeds:** SQLite single file + in‑memory LSH is fine.
* **>100k seeds:** Use a persistent LSH (e.g., Redis or a vector DB) and store sketches outside SQLite or as referenced blobs.
* Enable SQLite WAL for concurrent writers:

  ```sql
  PRAGMA journal_mode=WAL;
  ```

  Use one connection per worker.

## Tuning examples

* **High‑precision near‑dedup (tight paraphrases only):**
  `lsh_threshold=0.92, num_perm=256, ngram=5`, keep **conservative** policy.
* **Broad grouping (topic clustering / willing to merge):**
  `lsh_threshold=0.7, num_perm=128, ngram=4` + `policy='aggressive'` (caution: may merge different contexts).

## One‑liners (troubleshooting)

* List recent seeds:

  ```bash
  sqlite3 aster_seeds.db \
  "SELECT seed_id, iso_date, content_hash, near_duplicate_of \
   FROM seeds ORDER BY iso_date DESC LIMIT 20;"
  ```
* Dump a seed by id:

  ```bash
  sqlite3 aster_seeds.db \
  "SELECT * FROM seeds WHERE seed_id = 'PUT_ID_HERE';"
  ```

## Why this matters for Aster

This turns your dedupe/provenance concept into a runnable ingest pipeline you can wire into the **Aster Seed Log** task. It enforces deterministic canonicalization, blocks accidental duplicates, tags near‑dupes, and keeps provenance attached so weekly logs stay compact and auditable.

---

If you want, I can generate a ready‑to‑run `aster_ingest.py` with `SeedStore`, the CLI demo, and the conservative/aggressive paths baked in.
