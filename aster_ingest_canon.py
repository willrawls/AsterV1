#!/usr/bin/env python3
"""
Aster Seed Ingest - Canonical Export Edition
===========================================

Normalize Aster seed text, reject exact duplicates, store accepted seeds in
SQLite, optionally tag near-duplicates, and export canonical UTF-8 JSONL plus a
separate generated similarity index sidecar.

Usage:
    python aster_ingest_canonical.py --input seeds.jsonl
    python aster_ingest_canonical.py --input-folder ./imports
    python aster_ingest_canonical.py
        Imports all .json1 and .jsonl files in ./imports

    python aster_ingest_canonical.py --export-only
    python aster_ingest_canonical.py --validate-export

Input format:
    JSONL: one JSON object per line
    JSON array: [ {...}, {...} ]
    Single JSON object: { ... }

Canonical seed export fixes included:
    - UTF-8 JSONL with LF newlines
    - no log/header preamble in exported JSONL
    - typed tags/provenance arrays, not stringified JSON
    - repaired character-split provenance chains
    - schema_version field
    - lifecycle_state field
    - confidence is NULL when unset, not 0.0
    - deterministic generated anchors from fields
    - legacy_anchor preservation when an incoming anchor changed
    - minhash moved out of seed export into a generated sidecar index

Optional fuzzy matching:
    pip install datasketch

If datasketch is not installed, the script uses a pure-Python SimHash fallback.
"""

from __future__ import annotations

from datetime import datetime, timezone
import argparse
import base64
import hashlib
import json
from pathlib import Path
import pickle
import re
import sqlite3
import sys
import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

SCHEMA_VERSION = "aster.seed.v1"
DEFAULT_DB_PATH = "./exports/aster_seeds.db"
DEFAULT_EXPORT_DIR = "./exports"
VALID_LIFECYCLE_STATES = {"candidate", "reinforced", "canonical", "dormant", "retired"}

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
    schema_version: str = SCHEMA_VERSION
    lifecycle_state: str = "candidate"
    confidence: Optional[float] = None
    legacy_anchor: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any], *, anchor_policy: str = "generate") -> "Seed":
        """Create a canonical Seed from an input object, filling safe defaults."""
        if not isinstance(data, dict):
            raise TypeError(f"Seed input must be an object/dict, got {type(data).__name__}")

        created_at = coerce_created_at(data.get("created_at"))
        title = str(data.get("title") or "").strip()
        domain = canonical_segment(data.get("domain") or "Systems")
        phase = canonical_segment(data.get("phase") or "Aster")
        beat = canonical_segment(data.get("beat") or "Seed")
        signal = slugify(data.get("signal") or title or data.get("seed_id") or "seed")
        incoming_anchor = str(data.get("anchor") or "").strip()

        generated_anchor = make_anchor(domain, phase, beat, created_at, signal)
        if anchor_policy == "preserve" and incoming_anchor:
            anchor = incoming_anchor
            legacy_anchor = data.get("legacy_anchor")
        elif anchor_policy == "generate":
            anchor = generated_anchor
            legacy_anchor = data.get("legacy_anchor") or (incoming_anchor if incoming_anchor and incoming_anchor != generated_anchor else None)
        else:
            raise ValueError('anchor_policy must be "generate" or "preserve"')

        lifecycle_state = str(data.get("lifecycle_state") or "candidate").strip().lower()
        if lifecycle_state not in VALID_LIFECYCLE_STATES:
            lifecycle_state = "candidate"

        return cls(
            seed_id=str(data.get("seed_id") or str(uuid.uuid4())),
            title=title,
            anchor=anchor,
            domain=domain,
            phase=phase,
            beat=beat,
            signal=signal,
            seed_type=str(data.get("seed_type") or "concept").strip() or "concept",
            tags=normalize_tags(data.get("tags")),
            raw_text=str(data.get("raw_text") or ""),
            summary=str(data.get("summary") or ""),
            why_it_matters=str(data.get("why_it_matters") or ""),
            source=str(data.get("source") or ""),
            provenance_chain=normalize_provenance(data.get("provenance_chain")),
            created_at=created_at,
            schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
            lifecycle_state=lifecycle_state,
            confidence=normalize_confidence(data.get("confidence")),
            legacy_anchor=legacy_anchor,
        )


@dataclass
class IngestResult:
    status: str
    seed_id: Optional[str] = None
    reason: Optional[str] = None
    existing_seed_id: Optional[str] = None
    near_duplicate_of: Optional[str] = None
    confidence: Optional[float] = None
    merged_into: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {key: value for key, value in self.__dict__.items() if value is not None}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_now_year_month_day() -> str:
    return datetime.now(timezone.utc).date().isoformat().replace("-", "")


def coerce_created_at(value: Any) -> str:
    if value is None or str(value).strip() == "":
        return utc_now_iso()
    text = str(value).strip()
    # Keep already-valid-looking ISO strings as-is. This avoids silently changing
    # previously emitted timestamps.
    return text


def date_part(created_at: str) -> str:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", created_at or "")
    if match:
        return match.group(1)
    return datetime.now(timezone.utc).date().isoformat()


def slugify(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.strip().lower()
    text = re.sub(r"[\u200b-\u200d\ufeff]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "seed"


def canonical_segment(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        return "Seed"
    parts = re.split(r"[^A-Za-z0-9]+", text)
    cleaned = [p[:1].upper() + p[1:] for p in parts if p]
    return "".join(cleaned) or "Seed"


def make_anchor(domain: str, phase: str, beat: str, created_at: str, signal: str) -> str:
    return f"{canonical_segment(domain)}/{canonical_segment(phase)}/{canonical_segment(beat)}#{date_part(created_at)}@PT::{slugify(signal)}"


def maybe_json(value: Any) -> Any:
    """Decode strings that contain JSON arrays/objects; otherwise return value."""
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s:
        return value
    if (s.startswith("[") and s.endswith("]")) or (s.startswith("{") and s.endswith("}")):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return value
    return value


def normalize_tags(value: Any) -> List[str]:
    value = maybe_json(value)
    if value is None or value == "":
        return []
    if isinstance(value, str):
        # Accept comma-delimited legacy tags while preserving single tags.
        parts = [p.strip() for p in value.split(",")] if "," in value else [value.strip()]
    elif isinstance(value, list):
        parts = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, str) and "," in item:
                parts.extend(p.strip() for p in item.split(","))
            else:
                parts.append(str(item).strip())
    else:
        parts = [str(value).strip()]

    seen = set()
    tags: List[str] = []
    for part in parts:
        tag = slugify(part)
        if tag and tag not in seen:
            seen.add(tag)
            tags.append(tag)
    return tags


def normalize_provenance(value: Any) -> List[Dict[str, Any]]:
    """Normalize provenance into a list of objects and repair char-split strings."""
    value = maybe_json(value)

    if value is None or value == "":
        return []

    # Repair list("William → Aster") style bug.
    if isinstance(value, list) and value and all(isinstance(x, str) and len(x) == 1 for x in value):
        value = ["".join(value)]

    if isinstance(value, str):
        value = [value]
    elif isinstance(value, dict):
        value = [value]
    elif not isinstance(value, list):
        value = [str(value)]

    normalized: List[Dict[str, Any]] = []
    seen = set()
    for item in value:
        if item is None or item == "":
            continue
        if isinstance(item, dict):
            obj = dict(item)
            if not obj:
                continue
        elif isinstance(item, str):
            obj = {"source": item}
        else:
            obj = {"source": str(item)}

        key = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if key not in seen:
            seen.add(key)
            normalized.append(obj)
    return normalized


def normalize_confidence(value: Any) -> Optional[float]:
    """Use None for unset confidence. Reserve numeric values for actual scores."""
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f == 0.0:
        return None
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


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
        db_path: str = DEFAULT_DB_PATH,
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
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
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
                schema_version TEXT NOT NULL DEFAULT 'aster.seed.v1',
                title TEXT,
                anchor TEXT,
                legacy_anchor TEXT,
                domain TEXT,
                phase TEXT,
                beat TEXT,
                signal TEXT,
                seed_type TEXT,
                lifecycle_state TEXT NOT NULL DEFAULT 'candidate',
                confidence REAL DEFAULT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                raw_text TEXT NOT NULL,
                summary TEXT,
                why_it_matters TEXT,
                source TEXT,
                provenance_chain TEXT NOT NULL DEFAULT '[]',
                normalized_text TEXT NOT NULL,
                content_hash TEXT UNIQUE NOT NULL,
                near_duplicate_of TEXT,
                minhash BLOB,
                simhash TEXT
            )
            """
        )

        # Lightweight migrations for databases created by older versions.
        existing_cols = {row[1] for row in cur.execute("PRAGMA table_info(seeds)").fetchall()}
        migrations = {
            "schema_version": "ALTER TABLE seeds ADD COLUMN schema_version TEXT NOT NULL DEFAULT 'aster.seed.v1'",
            "lifecycle_state": "ALTER TABLE seeds ADD COLUMN lifecycle_state TEXT NOT NULL DEFAULT 'candidate'",
            "legacy_anchor": "ALTER TABLE seeds ADD COLUMN legacy_anchor TEXT",
        }
        for col, sql in migrations.items():
            if col not in existing_cols:
                cur.execute(sql)

        cur.execute("CREATE INDEX IF NOT EXISTS idx_content_hash ON seeds(content_hash)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON seeds(created_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_near_duplicate_of ON seeds(near_duplicate_of)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_anchor ON seeds(anchor)")
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

    def _append_provenance(self, seed_id: str, provenance_chain: Any) -> None:
        row = self.conn.execute(
            "SELECT provenance_chain FROM seeds WHERE seed_id = ?",
            (seed_id,),
        ).fetchone()

        if not row:
            return

        existing = normalize_provenance(row["provenance_chain"])
        incoming = normalize_provenance(provenance_chain)
        if not incoming:
            return

        existing.extend(incoming)
        self.conn.execute(
            "UPDATE seeds SET provenance_chain = ? WHERE seed_id = ?",
            (json.dumps(existing, ensure_ascii=False, separators=(",", ":")), seed_id),
        )
        self.conn.commit()

    def _find_near_duplicate_minhash(self, normalized_text: str) -> Tuple[Optional[str], Optional[float], Optional[bytes]]:
        if self.lsh is None:
            return None, None, None

        m = self._compute_minhash(normalized_text)
        if m is None:
            return None, None, None

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
        return near_duplicate_of, (best_confidence if near_duplicate_of else None), pickle.dumps(m)

    def _find_near_duplicate_simhash(self, normalized_text: str) -> Tuple[Optional[str], Optional[float], int]:
        current = simhash(normalized_text, token_size=self.ngram)
        rows = self.conn.execute(
            "SELECT seed_id, simhash FROM seeds WHERE simhash IS NOT NULL"
        ).fetchall()

        best_seed_id = None
        best_distance = 10**9

        for row in rows:
            try:
                distance = hamming_distance(current, int(row["simhash"]))
            except Exception:
                continue
            if distance < best_distance:
                best_distance = distance
                best_seed_id = row["seed_id"]

        if best_seed_id is not None and best_distance <= self.simhash_threshold:
            confidence = max(0.0, 1.0 - best_distance / 64.0)
            return best_seed_id, confidence, current

        return None, None, current

    def insert_seed(self, seed: Seed, policy: str = "conservative") -> Dict[str, Any]:
        if policy not in {"conservative", "aggressive"}:
            raise ValueError('policy must be "conservative" or "aggressive"')

        seed.tags = normalize_tags(seed.tags)
        seed.provenance_chain = normalize_provenance(seed.provenance_chain)
        seed.lifecycle_state = seed.lifecycle_state if seed.lifecycle_state in VALID_LIFECYCLE_STATES else "candidate"
        seed.signal = slugify(seed.signal or seed.title or seed.seed_id)
        seed.domain = canonical_segment(seed.domain or "Systems")
        seed.phase = canonical_segment(seed.phase or "Aster")
        seed.beat = canonical_segment(seed.beat or "Seed")
        seed.anchor = make_anchor(seed.domain, seed.phase, seed.beat, seed.created_at, seed.signal)

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

        near_duplicate_of: Optional[str] = None
        confidence: Optional[float] = None
        minhash_blob: Optional[bytes] = None
        simhash_value: Optional[int] = None

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

        # Import-time confidence is preserved only if supplied. Dedupe confidence is
        # stored only when a near-duplicate was actually found.
        stored_confidence = seed.confidence if seed.confidence is not None else confidence

        self.conn.execute(
            """
            INSERT INTO seeds (
                seed_id, created_at, schema_version, title, anchor, legacy_anchor,
                domain, phase, beat, signal, seed_type, lifecycle_state, confidence,
                tags, raw_text, summary, why_it_matters, source, provenance_chain,
                normalized_text, content_hash, near_duplicate_of, minhash, simhash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                seed.seed_id,
                seed.created_at or utc_now_iso(),
                seed.schema_version or SCHEMA_VERSION,
                seed.title,
                seed.anchor,
                seed.legacy_anchor,
                seed.domain,
                seed.phase,
                seed.beat,
                seed.signal,
                seed.seed_type,
                seed.lifecycle_state,
                stored_confidence,
                json.dumps(seed.tags, ensure_ascii=False, separators=(",", ":")),
                seed.raw_text,
                seed.summary,
                seed.why_it_matters,
                seed.source,
                json.dumps(seed.provenance_chain, ensure_ascii=False, separators=(",", ":")),
                normalized_text,
                content_hash,
                near_duplicate_of,
                minhash_blob,
                str(simhash_value) if simhash_value is not None else None,
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
            confidence=stored_confidence,
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

    def _canonical_seed_obj(self, row: sqlite3.Row) -> Dict[str, Any]:
        obj = dict(row)
        tags = normalize_tags(obj.get("tags"))
        provenance_chain = normalize_provenance(obj.get("provenance_chain"))
        confidence = normalize_confidence(obj.get("confidence"))
        created_at = coerce_created_at(obj.get("created_at"))
        domain = canonical_segment(obj.get("domain") or "Systems")
        phase = canonical_segment(obj.get("phase") or "Aster")
        beat = canonical_segment(obj.get("beat") or "Seed")
        signal = slugify(obj.get("signal") or obj.get("title") or obj.get("seed_id"))
        anchor = make_anchor(domain, phase, beat, created_at, signal)
        legacy_anchor = obj.get("legacy_anchor") or (obj.get("anchor") if obj.get("anchor") and obj.get("anchor") != anchor else None)

        out: Dict[str, Any] = {
            "schema_version": obj.get("schema_version") or SCHEMA_VERSION,
            "seed_id": obj.get("seed_id"),
            "created_at": created_at,
            "title": obj.get("title") or "",
            "anchor": anchor,
            "domain": domain,
            "phase": phase,
            "beat": beat,
            "signal": signal,
            "seed_type": obj.get("seed_type") or "concept",
            "lifecycle_state": obj.get("lifecycle_state") or "candidate",
            "confidence": confidence,
            "tags": tags,
            "raw_text": obj.get("raw_text") or "",
            "summary": obj.get("summary") or "",
            "why_it_matters": obj.get("why_it_matters") or "",
            "source": obj.get("source") or "",
            "provenance_chain": provenance_chain,
            "normalized_text": obj.get("normalized_text") or normalize(obj.get("raw_text") or ""),
            "content_hash": obj.get("content_hash") or sha256_hex(obj.get("normalized_text") or normalize(obj.get("raw_text") or "")),
            "near_duplicate_of": obj.get("near_duplicate_of"),
        }
        if legacy_anchor:
            out["legacy_anchor"] = legacy_anchor
        return out

    def export_jsonl(self, out_path: str) -> str:
        """Export canonical seed JSONL only. Generated minhash stays out."""
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        rows = self.conn.execute(
            """
            SELECT seed_id, created_at, schema_version, title, anchor, legacy_anchor,
                   domain, phase, beat, signal, seed_type, lifecycle_state,
                   confidence, tags, raw_text, summary, why_it_matters, source,
                   provenance_chain, normalized_text, content_hash, near_duplicate_of
            FROM seeds
            ORDER BY created_at, seed_id
            """
        ).fetchall()

        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            for row in rows:
                obj = self._canonical_seed_obj(row)
                f.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")

        return out_path

    def export_index_jsonl(self, out_path: str) -> str:
        """Export generated similarity/index data as a sidecar JSONL."""
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        rows = self.conn.execute(
            """
            SELECT seed_id, content_hash, near_duplicate_of, minhash, simhash
            FROM seeds
            ORDER BY created_at, seed_id
            """
        ).fetchall()

        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            for row in rows:
                minhash_blob = row["minhash"]
                obj: Dict[str, Any] = {
                    "seed_id": row["seed_id"],
                    "content_hash": row["content_hash"],
                    "near_duplicate_of": row["near_duplicate_of"],
                    "simhash": row["simhash"],
                    "minhash": None,
                }
                if minhash_blob is not None:
                    obj["minhash"] = {
                        "__type__": "bytes",
                        "encoding": "base64",
                        "value": base64.b64encode(minhash_blob).decode("ascii"),
                    }
                f.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")

        return out_path


def read_text_auto(filepath: str) -> str:
    data = Path(filepath).read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    # Last-resort replacement so we can emit a useful line-level JSON error.
    return data.decode("utf-8", errors="replace")


def iter_seed_objects(filepath: str) -> Iterator[Dict[str, Any]]:
    text = read_text_auto(filepath).strip()
    if not text:
        return

    # First try whole-file JSON. This supports arrays and single-object files.
    if text.startswith("[") or text.startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                yield parsed
                return
            if isinstance(parsed, list):
                for i, item in enumerate(parsed, start=1):
                    if not isinstance(item, dict):
                        raise ValueError(f"JSON array item {i} is not an object")
                    yield item
                return
        except json.JSONDecodeError:
            # Fall through to JSONL parsing for better line numbers.
            pass

    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on line {line_no}: {exc}") from exc
        if not isinstance(obj, dict):
            raise ValueError(f"JSONL line {line_no} is not an object")
        yield obj


def validate_canonical_jsonl(filepath: str) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    seen_ids = set()
    seen_hashes = set()
    text = read_text_auto(filepath)

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_no}: invalid JSON: {exc}")
            continue

        required = [
            "schema_version", "seed_id", "created_at", "title", "anchor", "domain",
            "phase", "beat", "signal", "seed_type", "lifecycle_state", "confidence",
            "tags", "raw_text", "summary", "why_it_matters", "source",
            "provenance_chain", "normalized_text", "content_hash", "near_duplicate_of",
        ]
        for key in required:
            if key not in obj:
                errors.append(f"line {line_no}: missing {key}")

        if not isinstance(obj.get("tags"), list):
            errors.append(f"line {line_no}: tags must be a list")
        if not isinstance(obj.get("provenance_chain"), list):
            errors.append(f"line {line_no}: provenance_chain must be a list")
        if obj.get("lifecycle_state") not in VALID_LIFECYCLE_STATES:
            errors.append(f"line {line_no}: invalid lifecycle_state")
        confidence = obj.get("confidence")
        if confidence is not None and not isinstance(confidence, (int, float)):
            errors.append(f"line {line_no}: confidence must be null or numeric")
        if "minhash" in obj:
            errors.append(f"line {line_no}: minhash belongs in sidecar index, not canonical seeds")

        normalized_text = obj.get("normalized_text")
        content_hash = obj.get("content_hash")
        if isinstance(normalized_text, str) and isinstance(content_hash, str):
            expected = sha256_hex(normalized_text)
            if content_hash != expected:
                errors.append(f"line {line_no}: content_hash does not match normalized_text")

        seed_id = obj.get("seed_id")
        if seed_id in seen_ids:
            errors.append(f"line {line_no}: duplicate seed_id {seed_id}")
        seen_ids.add(seed_id)

        if content_hash in seen_hashes:
            errors.append(f"line {line_no}: duplicate content_hash {content_hash}")
        seen_hashes.add(content_hash)

    return not errors, errors


def run_import(filepath: str, db_path: str, *, anchor_policy: str, policy: str, use_fuzzy: str) -> None:
    store = SeedStore(db_path=db_path, use_fuzzy=use_fuzzy)

    print("Aster Seed Ingestion:", filepath)
    print("======================")
    print(f"Fuzzy engine: {'MinHash/LSH' if HAS_DATASKETCH and use_fuzzy != 'never' else 'SimHash fallback' if use_fuzzy != 'never' else 'disabled'}")
    print()

    try:
        for raw_seed in iter_seed_objects(filepath):
            seed = Seed.from_dict(raw_seed, anchor_policy=anchor_policy)
            result = store.insert_seed(seed, policy=policy)
            print(f"{seed.seed_id}: {result}")
    finally:
        store.close()


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest and export canonical Aster seed JSONL.")
    parser.add_argument("--input", action="append", help="Input .jsonl/.json1 file. Can be supplied multiple times.")
    parser.add_argument("--input-folder", default=None, help="Import every .json1 file in this directory. Also accepts .jsonl unless --json1-only is used.")
    parser.add_argument("--imports-dir", default="./imports", help="Legacy alias/default directory scanned when --input and --input-folder are omitted.")
    parser.add_argument("--json1-only", action="store_true", help="When scanning a folder, import only .json1 files instead of .json1 and .jsonl files.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite database path.")
    parser.add_argument("--export", default=None, help="Canonical seed JSONL output path.")
    parser.add_argument("--index", default=None, help="Generated similarity sidecar JSONL output path.")
    parser.add_argument("--export-only", action="store_true", help="Skip imports and only export current database.")
    parser.add_argument("--validate-export", action="store_true", help="Validate the canonical JSONL after export.")
    parser.add_argument("--anchor-policy", choices=["generate", "preserve"], default="generate")
    parser.add_argument("--dedupe-policy", choices=["conservative", "aggressive"], default="conservative")
    parser.add_argument("--use-fuzzy", choices=["auto", "never", "always"], default="auto")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    export_dir = Path(DEFAULT_EXPORT_DIR)
    export_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now_year_month_day()
    export_path = args.export or str(export_dir / f"aster_seed_dump_{stamp}.canonical.jsonl")
    index_path = args.index or str(export_dir / f"aster_seed_index_{stamp}.jsonl")

    input_files: List[Path] = []
    if not args.export_only:
        if args.input and args.input_folder:
            print("ERROR: use either --input for specific files or --input-folder for a directory, not both.")
            return 1

        if args.input:
            input_files = [Path(p) for p in args.input]
        else:
            scan_dir = Path(args.input_folder or args.imports_dir)
            input_files = sorted(scan_dir.glob("*.json1"))
            if not args.json1_only:
                input_files += sorted(scan_dir.glob("*.jsonl"))

        if not input_files:
            scan_dir_display = args.input_folder or args.imports_dir
            wanted = "*.json1" if args.json1_only else "*.json1/.jsonl"
            print(f"ERROR: no input files found. Supply --input or place {wanted} files in {scan_dir_display}")
            return 1

        for filepath in input_files:
            if not filepath.exists():
                print(f"ERROR: input file not found: {filepath}")
                return 1

            print()
            print(f"---[ Importing: {filepath} ]-------------------")
            run_import(
                str(filepath),
                args.db,
                anchor_policy=args.anchor_policy,
                policy=args.dedupe_policy,
                use_fuzzy=args.use_fuzzy,
            )

    store = SeedStore(db_path=args.db, use_fuzzy=args.use_fuzzy)
    try:
        exported = store.export_jsonl(export_path)
        indexed = store.export_index_jsonl(index_path)
        print()
        print(f"Database written: {store.db_path}")
        print(f"Canonical JSONL export written: {exported}")
        print(f"Similarity index sidecar written: {indexed}")
    finally:
        store.close()

    if args.validate_export:
        ok, errors = validate_canonical_jsonl(export_path)
        if ok:
            print("Validation passed.")
        else:
            print("Validation failed:")
            for error in errors:
                print(" -", error)
            return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
