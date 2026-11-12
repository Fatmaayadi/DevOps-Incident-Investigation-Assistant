"""Retrieval metrics, computed at document level: a retrieved passage is relevant when it
belongs to one of the expected documents of the question."""


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


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
