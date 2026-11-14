"""Retrieval and context metrics.

Two levels, never mixed:
  - document level (recall_at_k, precision_at_k, reciprocal_rank, hit_rate_at_k): a retrieved
    passage is relevant when it belongs to one of the expected documents of the question;
  - evidence level (evidence_*, context_*): a retrieved passage is relevant when it contains
    one of the evidence passages listed in the benchmark (see passage_matches_unit).
"""
import re
import unicodedata

# A passage cut by a chunk boundary is matched by its beginning or its end (see passage_matches_unit).
MIN_FRAGMENT_CHARS = 60


def recall_at_k(passage_doc_ids: list[str], relevant: set[str], k: int) -> float:
    """Share of the expected documents found among the first k passages."""
    if not relevant:
        return 0.0
    return len(relevant & set(passage_doc_ids[:k])) / len(relevant)


def precision_at_k(passage_doc_ids: list[str], relevant: set[str], k: int) -> float:
    """Share of the first k passages that come from an expected document."""
    top = passage_doc_ids[:k]
    if not top:
        return 0.0
    return sum(doc in relevant for doc in top) / k


def reciprocal_rank(passage_doc_ids: list[str], relevant: set[str]) -> float:
    """1 / rank of the first passage from an expected document (0 if none)."""
    for rank, doc in enumerate(passage_doc_ids, start=1):
        if doc in relevant:
            return 1.0 / rank
    return 0.0


def hit_rate_at_k(passage_doc_ids: list[str], relevant: set[str], k: int) -> float:
    """1 if at least one expected document is among the first k passages, else 0."""
    return float(bool(relevant & set(passage_doc_ids[:k])))


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# ---------------------------------------------------------------- evidence level

def normalize_text(text: str) -> str:
    """Comparable form of a passage: Unicode NFKC, words cut by a hyphen (U+2010) at the end of
    a PDF line joined again, dashes and quotes unified, and all whitespace removed (the PDF text
    extraction sometimes drops or adds spaces)."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub("‐\\s+", "", text)
    for old, new in (("‐", "-"), ("‑", "-"), ("–", "-"), ("—", "-"),
                     ("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"')):
        text = text.replace(old, new)
    return re.sub(r"\s+", "", text)


def evidence_units(incident: dict) -> dict[tuple, list[str]]:
    """Evidence units of a benchmark question: (doc_id, physical page) for a PDF, (doc_id, section)
    for a Markdown guide, each with the normalized evidence passages it must contain.
    Several passages on the same page (or in the same section) form one unit."""
    units: dict[tuple, list[str]] = {}
    for evidence in incident.get("evidence", []):
        place = evidence["page_number"] if evidence.get("page_number") is not None else evidence["section"]
        units.setdefault((evidence["doc_id"], place), []).append(normalize_text(evidence["exact_evidence_passage"]))
    return units


def _longest_part(passage: str, text: str, from_end: bool) -> int:
    """Length of the longest beginning (or end) of passage contained in text (binary search:
    if a beginning of length n is contained, every shorter beginning is too)."""
    low, high = 0, len(passage)
    while low < high:
        middle = (low + high + 1) // 2
        part = passage[-middle:] if from_end else passage[:middle]
        if part in text:
            low = middle
        else:
            high = middle - 1
    return low


def passage_matches_unit(passage: dict, unit: tuple, evidence_texts: list[str]) -> bool:
    """A retrieved passage matches an evidence unit when:
      1. it comes from the same document (doc_id);
      2. it comes from the same physical PDF page (metadata 'page'), or from the same Markdown
         section (metadata 'section');
      3. its normalized text contains one of the evidence passages entirely, or a beginning or an
         end of it of at least min(length, MIN_FRAGMENT_CHARS) characters. Chunks overlap by
         CHUNK_OVERLAP characters, so a passage cut by a chunk boundary starts in one chunk and
         ends in the next: both chunks match.
    chunk_id is never used: it is positional and changes when the index is rebuilt."""
    doc_id, place = unit
    if passage.get("doc_id") != doc_id:
        return False
    location = passage.get("page") if isinstance(place, int) else passage.get("section")
    if location != place:
        return False
    text = normalize_text(passage.get("text", ""))
    for evidence in evidence_texts:
        needed = min(len(evidence), MIN_FRAGMENT_CHARS)
        if evidence in text or _longest_part(evidence, text, False) >= needed or _longest_part(evidence, text, True) >= needed:
            return True
    return False


def _matching_units(passage: dict, units: dict[tuple, list[str]]) -> set[tuple]:
    return {unit for unit, texts in units.items() if passage_matches_unit(passage, unit, texts)}


def evidence_recall_at_k(passages: list[dict], units: dict[tuple, list[str]], k: int) -> float:
    """Share of the evidence units covered by at least one of the first k passages."""
    if not units:
        return 0.0
    covered = set().union(*(_matching_units(p, units) for p in passages[:k]))
    return len(covered) / len(units)


def evidence_precision_at_k(passages: list[dict], units: dict[tuple, list[str]], k: int) -> float:
    """Share of the first k passages that match an evidence unit (divided by k, as precision_at_k).
    Lower bound: the evidence list of the benchmark is not exhaustive, so a relevant passage that
    is not referenced counts as a miss."""
    if not passages[:k]:
        return 0.0
    return sum(bool(_matching_units(p, units)) for p in passages[:k]) / k


def evidence_reciprocal_rank(passages: list[dict], units: dict[tuple, list[str]]) -> float:
    """1 / rank of the first passage that matches an evidence unit (0 if none)."""
    for rank, passage in enumerate(passages, start=1):
        if _matching_units(passage, units):
            return 1.0 / rank
    return 0.0


def context_precision(passages: list[dict], units: dict[tuple, list[str]]) -> float | None:
    """Share of the passages given to the investigation agent that match an evidence unit
    (lower bound, see evidence_precision_at_k). None when no passage was given."""
    if not passages:
        return None
    return sum(bool(_matching_units(p, units)) for p in passages) / len(passages)


def context_recall(passages: list[dict], units: dict[tuple, list[str]]) -> float | None:
    """Share of the evidence units covered by the passages given to the investigation agent.
    None when the question has no evidence unit (out-of-scope question, historical dataset)."""
    if not units:
        return None
    covered = set().union(*(_matching_units(p, units) for p in passages)) if passages else set()
    return len(covered) / len(units)
