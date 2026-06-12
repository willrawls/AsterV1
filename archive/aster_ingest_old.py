#!/usr/bin/env python3
"""
Aster Seed Ingest
=================

Normalize Aster seed text, reject exact duplicates, store accepted seeds in
SQLite, and optionally tag near-duplicates.

Usage:
    python aster_ingest.py --input seeds.jsonl
    python aster_ingest.py
        This usage will import all .json1 files in ./imports

Input format:
    One JSON object per line. Each object may contain the Seed fields shown in
    the Seed dataclass below.

Optional fuzzy matching: (Highly recommended)
    pip install datasketch

If datasketch is not installed, the script uses a pure-Python SimHash fallback.
"""

from __future__ import annotations

from datetime import datetime, timezone 
import hashlib
import json
import os
from pathlib import Path
import pickle
import re
import sqlite3
import sys
import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

json_output_path = ""

try:
    from datasketch import MinHash, MinHashLSH

    HAS_DATASKETCH = True
except Exception:
    HAS_DATASKETCH = False


@dataclass
class Seed:
    title: str
    anchor: str
    domain: str
    phase: str
    beat: str
    signal: str
    seed_type: str
    raw_text: str
    summary: str
    why_it_matters: str
    source: str
    tags: List[str] = field(default_factory=list)
    provenance_chain: List[Dict[str, Any]] = field(default_factory=list)
    seed_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = ""
    schema_version: str = "aster.seed.v1.1"
    lifecycle_state: str = "candidate"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Seed":
        """Create a Seed from a JSON object, filling safe defaults."""
        return cls(
            seed_id=data.get("seed_id") or str(uuid.uuid4()),
            title=data.get("title", ""),
            anchor=data.get("anchor", ""),
            domain=data.get("domain", ""),
            phase=data.get("phase", ""),
            beat=data.get("beat", ""),
            signal=data.get("signal", ""),
            seed_type=data.get("seed_type", ""),
            tags=list(data.get("tags") or []),
            raw_text=data.get("raw_text", ""),
            summary=data.get("summary", ""),
            why_it_matters=data.get("why_it_matters", ""),
            source=data.get("source", ""),
            provenance_chain=list(data.get("provenance_chain") or []),
            created_at=data.get("created_at") or utc_now_iso(),
            schema_version=data.get("schema_version", "aster.seed.v1.1"),
            lifecycle_state = data.get("lifecycle_state") or "candidate"
        )

@dataclass
class IngestResult:
    status: str
    seed_id: Optional[str] = None
    reason: Optional[str] = None
    existing_seed_id: Optional[str] = None
    near_duplicate_of: Optional[str] = None
    confidence: float = 0.0
    merged_into: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            key: value
            for key, value in self.__dict__.items()
            if value is not None and not (key == "confidence" and value == 0.0)
        }


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )

def utc_now_year_month() -> str:
    return datetime.now(timezone.utc).isoformat()[:7]

def normalize(text: str, max_len: int = 10_000) -> str:
    if text is None:
        text = ""

    t = unicodedata.normalize("NFKC", str(text))
    t = t.lower()
    t = re.sub(r"[\u200b-\u200d\uFEFF]", "", t)
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    t = t.replace("\u2018", "'").replace("\u2019", "'")
    t = re.sub(r"[^\w\s']+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:max_len]


def sha256_hex(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def char_ngrams(text: str, n: int) -> Iterable[str]:
    if not text:
        return []
    if len(text) <= n:
        return [text]
    return (text[i : i + n] for i in range(len(text) - n + 1))


def simhash(text: str, hash_bits: int = 64, token_size: int = 5) -> int:
    weights = [0] * hash_bits
    grams = list(char_ngrams(text, token_size))

    if not grams:
        return 0

    for gram in grams:
        h = int(hashlib.sha1(gram.encode("utf-8")).hexdigest(), 16)
        for bit_index in range(hash_bits):
            bit = (h >> bit_index) & 1
            weights[bit_index] += 1 if bit else -1

    fingerprint = 0
    for bit_index, weight in enumerate(weights):
        if weight > 0:
            fingerprint |= 1 << bit_index

    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


class SeedStore:
    def __init__(
        self,
        db_path: str = "./aster_export/aster_seeds.db",
        use_fuzzy: str = "auto",
        ngram: int = 5,
        num_perm: int = 128,
        lsh_threshold: float = 0.85,
        simhash_threshold: int = 6,
    ) -> None:
        if use_fuzzy not in {"auto", "never", "always"}:
            raise ValueError('use_fuzzy must be "auto", "never", or "always"')

        if use_fuzzy == "always" and not HAS_DATASKETCH:
            raise RuntimeError("use_fuzzy='always' requires: pip install datasketch")

        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.use_fuzzy = use_fuzzy
        self.ngram = ngram
        self.num_perm = num_perm
        self.lsh_threshold = lsh_threshold
        self.simhash_threshold = simhash_threshold
        self.lsh = None

        self._init_db()

        if use_fuzzy != "never" and HAS_DATASKETCH:
            self._init_lsh()

    def close(self) -> None:
        self.conn.close()

    def _init_db(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS seeds (
                seed_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                title TEXT,
                anchor TEXT,
                domain TEXT,
                phase TEXT,
                beat TEXT,
                signal TEXT,
                seed_type TEXT,
                tags TEXT,
                raw_text TEXT NOT NULL,
                summary TEXT,
                why_it_matters TEXT,
                source TEXT,
                provenance_chain TEXT,
                normalized_text TEXT NOT NULL,
                content_hash TEXT UNIQUE NOT NULL,
                near_duplicate_of TEXT,
                confidence REAL DEFAULT 0.0,
                schema_version TEXT,
                lifecycle_state TEXT,
                minhash BLOB,
                simhash TEXT
            )
            """
        )
        self.conn.commit()
        cur.close()

        cur = self.conn.cursor()
        cur.execute("CREATE INDEX IF NOT EXISTS idx_content_hash ON seeds(content_hash)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON seeds(created_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_near_duplicate_of ON seeds(near_duplicate_of)")
        self.conn.commit()
        cur.close()

    def _init_lsh(self) -> None:
        self.lsh = MinHashLSH(threshold=self.lsh_threshold, num_perm=self.num_perm)
        rows = self.conn.execute(
            "SELECT seed_id, minhash FROM seeds WHERE minhash IS NOT NULL"
        ).fetchall()

        for row in rows:
            try:
                m = pickle.loads(row["minhash"])
                self.lsh.insert(row["seed_id"], m)
            except Exception:
                continue

    def _compute_minhash(self, normalized_text: str):
        if not HAS_DATASKETCH:
            return None

        m = MinHash(num_perm=self.num_perm)
        for gram in char_ngrams(normalized_text, self.ngram):
            m.update(gram.encode("utf-8"))
        return m

    def _append_provenance(self, seed_id: str, provenance_chain: List[Dict[str, Any]]) -> None:
        row = self.conn.execute(
            "SELECT provenance_chain FROM seeds WHERE seed_id = ?",
            (seed_id,),
        ).fetchone()

        if not row:
            return

        try:
            existing = json.loads(row["provenance_chain"] or "[]")
        except Exception:
            existing = []

        existing.extend(provenance_chain)
        self.conn.execute(
            "UPDATE seeds SET provenance_chain = ? WHERE seed_id = ?",
            (json.dumps(existing, ensure_ascii=False), seed_id),
        )
        self.conn.commit()

    def _find_near_duplicate_minhash(self, normalized_text: str) -> Tuple[Optional[str], float, Optional[bytes]]:
        if self.lsh is None:
            return None, 0.0, None

        m = self._compute_minhash(normalized_text)
        if m is None:
            return None, 0.0, None

        candidates = list(self.lsh.query(m))
        best_seed_id = None
        best_confidence = 0.0

        for candidate_id in candidates:
            row = self.conn.execute(
                "SELECT minhash FROM seeds WHERE seed_id = ?",
                (candidate_id,),
            ).fetchone()

            if not row or not row["minhash"]:
                continue

            existing = pickle.loads(row["minhash"])
            score = float(m.jaccard(existing))

            if score > best_confidence:
                best_confidence = score
                best_seed_id = candidate_id

        near_duplicate_of = (
            best_seed_id if best_seed_id and best_confidence >= self.lsh_threshold else None
        )
        return near_duplicate_of, best_confidence, pickle.dumps(m)

    def _find_near_duplicate_simhash(self, normalized_text: str) -> Tuple[Optional[str], float, int]:
        current = simhash(normalized_text, token_size=self.ngram)
        rows = self.conn.execute(
            "SELECT seed_id, simhash FROM seeds WHERE simhash IS NOT NULL"
        ).fetchall()

        best_seed_id = None
        best_distance = 10**9

        for row in rows:
            distance = hamming_distance(current, int(row["simhash"]))
            if distance < best_distance:
                best_distance = distance
                best_seed_id = row["seed_id"]

        if best_seed_id is not None and best_distance <= self.simhash_threshold:
            confidence = max(0.0, 1.0 - best_distance / 64.0)
            return best_seed_id, confidence, current

        return None, 0.0, current

    def insert_seed(self, seed: Seed, policy: str = "conservative") -> Dict[str, Any]:
        if policy not in {"conservative", "aggressive"}:
            raise ValueError('policy must be "conservative" or "aggressive"')

        normalized_text = normalize(seed.raw_text)
        content_hash = sha256_hex(normalized_text)

        existing = self.conn.execute(
            "SELECT seed_id FROM seeds WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()

        if existing:
            self._append_provenance(existing["seed_id"], seed.provenance_chain)
            return IngestResult(
                status="rejected",
                reason="exact_duplicate",
                existing_seed_id=existing["seed_id"],
            ).as_dict()

        near_duplicate_of = None
        confidence = None
        minhash_blob = None
        simhash_value = None

        if self.use_fuzzy != "never":
            if self.lsh is not None:
                near_duplicate_of, confidence, minhash_blob = self._find_near_duplicate_minhash(
                    normalized_text
                )
            else:
                near_duplicate_of, confidence, simhash_value = self._find_near_duplicate_simhash(
                    normalized_text
                )

        if policy == "aggressive" and near_duplicate_of and (confidence is not None and confidence >= 0.95):
            self._append_provenance(near_duplicate_of, seed.provenance_chain)
            return IngestResult(
                status="merged",
                merged_into=near_duplicate_of,
                confidence=confidence,
            ).as_dict()

        self.conn.execute(
            """
            INSERT INTO seeds (
                seed_id, created_at, title, anchor, domain, phase, beat, signal,
                seed_type, tags, raw_text, summary, why_it_matters, source,
                provenance_chain, normalized_text, content_hash, near_duplicate_of,
                confidence, minhash, simhash, schema_version, lifecycle_state
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                seed.seed_id,
                seed.created_at or utc_now_iso(),
                seed.title,
                seed.anchor,
                seed.domain,
                seed.phase,
                seed.beat,
                seed.signal,
                seed.seed_type,
                json.dumps(seed.tags, ensure_ascii=False),
                seed.raw_text,
                seed.summary,
                seed.why_it_matters,
                seed.source,
                json.dumps(seed.provenance_chain, ensure_ascii=False),
                normalized_text,
                content_hash,
                near_duplicate_of,
                confidence,
                minhash_blob,
                str(simhash_value) if simhash_value is not None else None,
                seed.schema_version,
                seed.lifecycle_state
            ),
        )
        self.conn.commit()

        if self.lsh is not None and minhash_blob is not None:
            try:
                self.lsh.insert(seed.seed_id, pickle.loads(minhash_blob))
            except Exception:
                pass

        return IngestResult(
            status="accepted",
            seed_id=seed.seed_id,
            near_duplicate_of=near_duplicate_of,
            confidence=confidence,
        ).as_dict()

    def list_seeds(self, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM seeds
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def export_jsonl(self, out_path: str = json_output_path) -> str:
        rows = self.conn.execute(
            """
            SELECT seed_id, created_at, title, anchor, domain, phase, beat, signal,
                   seed_type, tags, raw_text, summary, why_it_matters, source,
                   provenance_chain, normalized_text, content_hash,
                   near_duplicate_of, confidence
            FROM seeds
            ORDER BY created_at
            """
        ).fetchall()

        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            for row in rows:
                obj = dict(row)
                obj["tags"] = json.loads(obj.get("tags") or "[]")
                obj["provenance_chain"] = json.loads(obj.get("provenance_chain") or "[]")
                f.write(json.dumps(obj, ensure_ascii=True) + "\n")

        return out_path


def iter_jsonl(filepath: str) -> Iterable[Dict[str, Any]]:
    with open(filepath, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_no}: {exc}") from exc

def run_import(filepath: str, db_path: str = "./aster_export/aster_seeds.db") -> None:
    store = SeedStore(db_path=db_path, use_fuzzy="auto")

    print("Aster Seed Ingestion:", filepath)
    print("======================")
    print(f"Fuzzy engine: {'MinHash/LSH' if HAS_DATASKETCH else 'SimHash fallback'}")
    print()

    try:
        for raw_seed in iter_jsonl(filepath):
            seed = Seed.from_dict(raw_seed)
            result = store.insert_seed(seed)
            print(f"{seed.seed_id}: {result}")
    finally:
        store.close()


def main() -> None:
    if "--input" in sys.argv:
        try:
            idx = sys.argv.index("--input")
            input_files = [Path(sys.argv[idx + 1])]
        except IndexError:
            print("ERROR: --input requires a filename")
            sys.exit(1)
    else:
        input_files = sorted(Path("./imports").glob("*.json1"))

    if not input_files:
        print("ERROR: no .json1 files found in ./imports")
        sys.exit(1)

    for filepath in input_files:
        if not filepath.exists():
            print(f"ERROR: input file not found: {filepath}")
            sys.exit(1)

        print()
        print('---[ Importing: ', filepath, ' ]-------------------')
        run_import(str(filepath))

    store = SeedStore()
    try:
        exported = store.export_jsonl(json_output_path)
        print()
        print(f"Database written: {store.db_path}")
        print(f"JSONL export written: {exported}")
    finally:
        store.close()

if __name__ == "__main__":
    json_output_path = f"./aster_export/aster_seeds_content_hashed_{utc_now_year_month()}.jsonl"
    main()
    