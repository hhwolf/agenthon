"""Corpus loading, prioritisation and chunking (docs/TEXT_LAYER.md §2, §6)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import constants as C

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_DATE_RE = re.compile(r"(20\d{2}|19\d{2})[-_]?(\d{2})[-_]?(\d{2})")
_STOPWORDS = {
    "that", "this", "with", "from", "have", "will", "which", "their", "there", "about", "would",
    "could", "should", "been", "were", "they", "them", "then", "than", "into", "over", "under",
    "after", "before", "where", "when", "what", "your", "unit", "value", "price", "true", "false",
    "also", "more", "most", "such", "text", "corpus", "panel", "horizon", "asof", "card", "target",
    "targets", "series", "date", "dates", "days", "signal", "whether", "between", "against",
}


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / C.CHARS_PER_TOKEN))


def normalise(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    text = _CONTROL_RE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@dataclass(frozen=True)
class CorpusDoc:
    doc_id: str
    timestamp: str
    source: str
    doc_type: str
    file: str
    text: str
    score: float = 0.0  # lower = higher priority (set by prioritise)

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


@dataclass(frozen=True)
class Segment:
    doc_id: str
    timestamp: str
    doc_type: str
    part: int
    n_parts: int
    text: str

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)

    @property
    def label(self) -> str:
        return self.doc_id if self.n_parts == 1 else f"{self.doc_id} (part {self.part}/{self.n_parts})"


@dataclass
class Chunk:
    index: int
    segments: list[Segment] = field(default_factory=list)

    @property
    def tokens(self) -> int:
        return sum(s.tokens for s in self.segments)

    @property
    def doc_ids(self) -> list[str]:
        seen: list[str] = []
        for s in self.segments:
            if s.doc_id not in seen:
                seen.append(s.doc_id)
        return seen


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    m = _DATE_RE.search(str(value))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def load_corpus(unit_dir: Path, asof: date, notes: list[str] | None = None) -> list[CorpusDoc]:
    """Read ``text/corpus_index.json`` (or fall back to ``text/*.txt``) under ``unit_dir``.

    Documents dated after ``asof`` are dropped defensively; the staging gates should make
    that impossible, and a dropped document is recorded in ``notes``.
    """
    notes = notes if notes is not None else []
    text_dir = Path(unit_dir) / "text"
    if not text_dir.is_dir():
        notes.append(f"no text directory at {text_dir}")
        return []
    entries: list[dict] = []
    index_path = text_dir / "corpus_index.json"
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            notes.append(f"corpus_index.json unreadable ({type(exc).__name__}); falling back to *.txt")
            index = None
        documents = index.get("documents") if isinstance(index, dict) else None
        if isinstance(documents, list):
            entries = [e for e in documents if isinstance(e, dict)]
        elif index is not None:
            notes.append("corpus_index.json has no 'documents' list; falling back to *.txt")
    if not entries:
        for p in sorted(text_dir.glob("*.txt")):
            d = _parse_date(p.stem)
            entries.append({"doc_id": p.stem, "timestamp": d.isoformat() if d else "",  # unknown date stays unknown
                            "source": "", "doc_type": "unknown", "file": p.name})
    docs: list[CorpusDoc] = []
    seen_text: dict[str, str] = {}
    seen_ids: set[str] = set()
    for e in entries:
        doc_id = str(e.get("doc_id") or Path(str(e.get("file", ""))).stem or "").strip()
        file = str(e.get("file") or "").strip()
        if not doc_id or not file:
            notes.append("index entry without doc_id/file skipped")
            continue
        if doc_id in seen_ids:
            notes.append(f"{doc_id}: duplicate doc_id in the index (file {file}); first entry kept")
            continue
        path = text_dir / file
        if not path.is_file():
            notes.append(f"{doc_id}: file {file} missing")
            continue
        ts = str(e.get("timestamp") or "")
        d = _parse_date(ts)
        if d is not None and d > asof:
            notes.append(f"{doc_id}: dated {ts} after as-of {asof}; dropped")
            continue
        try:
            text = normalise(path.read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            notes.append(f"{doc_id}: unreadable ({type(exc).__name__})")
            continue
        if not text:
            notes.append(f"{doc_id}: empty")
            continue
        key = hashlib.sha1(text.encode("utf-8")).hexdigest()
        if key in seen_text:
            notes.append(f"{doc_id}: duplicate of {seen_text[key]}; dropped")
            continue
        seen_text[key] = doc_id
        seen_ids.add(doc_id)
        docs.append(CorpusDoc(doc_id=doc_id, timestamp=ts or (d.isoformat() if d else ""),
                              source=str(e.get("source") or ""), doc_type=str(e.get("doc_type") or "unknown"),
                              file=file, text=text))
    return docs


def card_keywords(*texts: str, assets: tuple[str, ...] = ()) -> set[str]:
    words: set[str] = set()
    for t in texts:
        for w in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", t or ""):
            w = w.lower()
            if w not in _STOPWORDS:
                words.add(w)
    for a in assets:
        words.add(a.lower())
    return words


def prioritise(docs: list[CorpusDoc], asof: date, keywords: set[str], relevance: dict | None = None) -> list[CorpusDoc]:
    """Decisions/statements before minutes before speeches; recent first; card keywords and BM25
    relevance to the assets help; documents with no asset/bank term at all sort last (off-topic)."""
    scored: list[CorpusDoc] = []
    for d in docs:
        level = C.DOC_TYPE_PRIORITY.get(d.doc_type, C.DEFAULT_DOC_TYPE_PRIORITY)
        ts = _parse_date(d.timestamp)
        days = (asof - ts).days if ts else 365
        sample = d.text[:20000].lower()
        hits = sum(1 for k in keywords if len(k) >= 4 and k in sample)
        score = level * C.PRIORITY_DAYS_PER_LEVEL + max(days, 0) - C.KEYWORD_BONUS_DAYS * min(hits, 3)
        rel = (relevance or {}).get(d.doc_id)
        if rel is not None:
            score -= C.RELEVANCE_BONUS_DAYS * float(rel.normalised)
            if rel.off_topic and level >= C.OFF_TOPIC_MIN_PRIORITY:
                score += C.OFF_TOPIC_PENALTY_DAYS
        scored.append(CorpusDoc(**{**d.__dict__, "score": float(score)}))
    return sorted(scored, key=lambda d: (d.score, d.doc_id))


def segment(doc: CorpusDoc, max_tokens: int = C.MAX_SEGMENT_TOKENS) -> list[Segment]:
    """Split a long document at paragraph boundaries into pieces of at most ``max_tokens``."""
    limit_chars = int(max_tokens * C.CHARS_PER_TOKEN)
    if len(doc.text) <= limit_chars:
        return [Segment(doc.doc_id, doc.timestamp, doc.doc_type, 1, 1, doc.text)]
    pieces: list[str] = []
    current: list[str] = []
    size = 0
    for para in doc.text.split("\n\n"):
        while len(para) > limit_chars:  # a single oversized paragraph: hard split at a space
            cut = para.rfind(" ", 0, limit_chars)
            cut = cut if cut > limit_chars // 2 else limit_chars
            head, para = para[:cut], para[cut:].lstrip()
            if current:
                pieces.append("\n\n".join(current))
                current, size = [], 0
            pieces.append(head)
        if current and size + len(para) + 2 > limit_chars:
            pieces.append("\n\n".join(current))
            current, size = [], 0
        current.append(para)
        size += len(para) + 2
    if current:
        pieces.append("\n\n".join(current))
    pieces = [p for p in pieces if p.strip()]
    n = len(pieces)
    return [Segment(doc.doc_id, doc.timestamp, doc.doc_type, i + 1, n, p) for i, p in enumerate(pieces)]


def pack(segments: list[Segment], *, chunk_tokens: int, max_chunks: int) -> tuple[list[Chunk], list[Segment]]:
    """First-fit packing in priority order. Segments that do not fit into ``max_chunks`` are dropped."""
    chunks: list[Chunk] = []
    dropped: list[Segment] = []
    for seg in segments:
        placed = False
        for ch in chunks:
            if ch.tokens + seg.tokens <= chunk_tokens:
                ch.segments.append(seg)
                placed = True
                break
        if placed:
            continue
        if len(chunks) < max_chunks:
            chunks.append(Chunk(len(chunks), [seg]))
        else:
            dropped.append(seg)
    return chunks, dropped


def plan_chunks(docs: list[CorpusDoc], *, max_chunks: int,
                chunk_tokens: int | None = None) -> tuple[list[Chunk], list[Segment]]:
    """Segment prioritised documents and pack them into at most ``max_chunks`` extraction requests."""
    budget = chunk_tokens if chunk_tokens is not None else C.MAX_INPUT_TOKENS_PER_CALL - C.PROMPT_OVERHEAD_TOKENS
    segment_tokens = min(C.MAX_SEGMENT_TOKENS, max(C.MIN_SEGMENT_TOKENS, budget // 2))
    segments: list[Segment] = []
    for d in docs:
        segments.extend(segment(d, segment_tokens))
    return pack(segments, chunk_tokens=budget, max_chunks=max(0, max_chunks))


def render_segment(seg: Segment) -> str:
    safe = seg.doc_id.replace('"', "'")
    part = f' part="{seg.part}/{seg.n_parts}"' if seg.n_parts > 1 else ""
    return (f'<<<DOC id="{safe}" timestamp="{seg.timestamp}" type="{seg.doc_type}"{part}>>>\n'
            f"{seg.text}\n<<<END DOC>>>")


def render_chunk(chunk: Chunk) -> str:
    return "\n\n".join(render_segment(s) for s in chunk.segments)
