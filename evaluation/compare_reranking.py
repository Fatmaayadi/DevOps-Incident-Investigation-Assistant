"""Compare, for one incident, the passages kept by the hybrid search (RRF order) and by the reranker.

  python -m evaluation.compare_reranking "pods restart in a loop and kubectl shows CrashLoopBackOff"

The benchmark (python -m evaluation.run_retrieval_benchmark) compares both strategies on the whole
evaluation dataset; this command shows the difference on a single question.
"""
import argparse

from incident_assistant import config, retrieval
from incident_assistant.indexing import get_client


def compare(query: str, top_k: int = config.FINAL_PASSAGES) -> dict:
    before = retrieval.hybrid_search([query], top_k=top_k)
    after = retrieval.hybrid_search([query], use_reranker=True, top_k=top_k)
    before_ids = [p["chunk_id"] for p in before]
    after_ids = [p["chunk_id"] for p in after]
    return {
        "before": before,
        "after": after,
        "added": [i for i in after_ids if i not in before_ids],
        "removed": [i for i in before_ids if i not in after_ids],
    }


def main():
    parser = argparse.ArgumentParser(description="Passages before and after reranking for one question.")
    parser.add_argument("query")
    parser.add_argument("--top-k", type=int, default=config.FINAL_PASSAGES)
    args = parser.parse_args()
    result = compare(args.query, args.top_k)

    print(f"{'#':>2}  {'RRF order':45}  {'after reranking (RRF rank, reranker score)':55}")
    for position in range(max(len(result["before"]), len(result["after"]))):
        before = result["before"][position]["chunk_id"] if position < len(result["before"]) else ""
        after = ""
        if position < len(result["after"]):
            passage = result["after"][position]
            after = f"{passage['chunk_id']} (RRF {passage['rrf_rank']}, {passage['rerank_score']:.2f})"
        print(f"{position + 1:>2}  {before:45}  {after:55}")
    print(f"\nBrought in by the reranker: {result['added'] or 'none'}")
    print(f"Left out by the reranker:   {result['removed'] or 'none'}")
    get_client().close()


if __name__ == "__main__":
    main()
