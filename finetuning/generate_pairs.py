"""Step 1 of the fine-tuning experiment: build (question, passage) training pairs from the
knowledge base. The LLM writes, for each sampled chunk, an incident description for which the
chunk is a relevant answer. The evaluation questions are never used.

Filters: duplicates, questions that copy the passage, questions too close to an evaluation
question (cosine similarity with the base embedding model), questions too short/long.
Split: by document (a validation document is never seen in training).

Usage: python -m finetuning.generate_pairs [--chunks 1500]
"""
import argparse
import json
import random
import time
from pathlib import Path

import numpy as np
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from incident_assistant import config
from incident_assistant.agents import get_llm
from incident_assistant.documents import chunk_file, list_source_files
from incident_assistant.indexing import get_dense_embeddings

DATA_DIR = Path(__file__).parent / "data"
EVAL_DATASET = config.ROOT_DIR / "evaluation" / "datasets" / "incidents_eval.json"
BATCH = 6
SEED = 42
PAUSE_SECONDS = 12
MAX_SIMILARITY_TO_EVAL = 0.85


class Questions(BaseModel):
    questions: list[str] = Field(description="Exactly one question per passage, in the same order")


PROMPT = ChatPromptTemplate.from_template("""You create training data for a DevOps troubleshooting search engine.
For EACH numbered passage, write one short incident description (1-2 sentences) that an engineer
could type when facing a problem for which this passage is a useful answer.
Describe the situation in the engineer's own words (symptoms, error messages, context).
Do not copy sentences from the passage. Return exactly {count} questions, in order.

{passages}""")


def copies_passage(question: str, passage: str) -> bool:
    """True when the beginning of the question is copied word for word from the passage."""
    q = question.lower().strip(" .?")
    return len(q) > 40 and q[:60] in passage.lower()


def sample_chunks(total: int) -> list:
    """All Markdown chunks + a proportional random sample of PDF chunks."""
    rng = random.Random(SEED)
    markdown, pdf = [], []
    for source in list_source_files():
        (markdown if source["kind"] == "markdown" else pdf).extend(chunk_file(source))
    pdf_sample = rng.sample(pdf, min(len(pdf), max(0, total - len(markdown))))
    return markdown + pdf_sample


def generate(chunks: list, raw_path: Path) -> list[dict]:
    """Generate questions for the chunks not yet in raw_path (the run can be resumed).
    A pause between batches keeps the run under the free tier limit of ~8,000 tokens per minute."""
    pairs = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines()] if raw_path.exists() else []
    done = {p["chunk_id"] for p in pairs}
    chunks = [c for c in chunks if c.metadata["chunk_id"] not in done]
    print(f"{len(pairs)} pairs already generated, {len(chunks)} chunks left")
    chain = PROMPT | get_llm(config.PAIR_MODEL).with_structured_output(Questions)
    for start in range(0, len(chunks), BATCH):
        time.sleep(PAUSE_SECONDS)
        batch = chunks[start:start + BATCH]
        passages = "\n\n".join(f"{i}. {c.page_content}" for i, c in enumerate(batch, start=1))
        try:
            result = chain.invoke({"count": len(batch), "passages": passages})
        except Exception as error:
            print(f"batch {start // BATCH}: failed ({str(error)[:100]})")
            continue
        if len(result.questions) != len(batch):
            print(f"batch {start // BATCH}: wrong number of questions, skipped")
            continue
        for chunk, question in zip(batch, result.questions):
            pairs.append({"question": question.strip(), "passage": chunk.page_content,
                          "doc_id": chunk.metadata["doc_id"], "chunk_id": chunk.metadata["chunk_id"]})
        raw_path.write_text("\n".join(json.dumps(p) for p in pairs), encoding="utf-8")
        print(f"{len(pairs)} pairs generated")
    return pairs


def filter_pairs(pairs: list[dict]) -> tuple[list[dict], dict]:
    stats = {"generated": len(pairs)}
    seen, kept = set(), []
    for p in pairs:
        key = p["question"].lower()
        n_words = len(p["question"].split())
        # "Related Concepts" sections are lists of links to other guides: the manual review showed
        # that questions generated from them do not match the passage.
        related_concepts = "> Related Concepts" in p["passage"].split("\n")[0]
        if key in seen or not 5 <= n_words <= 60 or copies_passage(p["question"], p["passage"]) or related_concepts:
            continue
        seen.add(key)
        kept.append(p)
    stats["after_duplicate_length_copy_filters"] = len(kept)

    # Remove questions too similar to any evaluation question (protects the benchmark).
    embeddings = get_dense_embeddings()
    eval_questions = [i["question"] for i in json.loads(EVAL_DATASET.read_text(encoding="utf-8"))["incidents"]]
    eval_vectors = np.array(embeddings.embed_documents(eval_questions))
    pair_vectors = np.array(embeddings.embed_documents([p["question"] for p in kept]))
    eval_vectors /= np.linalg.norm(eval_vectors, axis=1, keepdims=True)
    pair_vectors /= np.linalg.norm(pair_vectors, axis=1, keepdims=True)
    max_similarity = (pair_vectors @ eval_vectors.T).max(axis=1)
    kept = [p for p, sim in zip(kept, max_similarity) if sim < MAX_SIMILARITY_TO_EVAL]
    stats["after_eval_similarity_filter"] = len(kept)
    stats["max_similarity_threshold"] = MAX_SIMILARITY_TO_EVAL
    return kept, stats


def split_by_document(pairs: list[dict], validation_share: float = 0.1) -> tuple[list, list]:
    rng = random.Random(SEED)
    doc_ids = sorted({p["doc_id"] for p in pairs})
    rng.shuffle(doc_ids)
    validation_docs, count = set(), 0
    for doc_id in doc_ids:
        if count >= validation_share * len(pairs):
            break
        validation_docs.add(doc_id)
        count += sum(p["doc_id"] == doc_id for p in pairs)
    train = [p for p in pairs if p["doc_id"] not in validation_docs]
    val = [p for p in pairs if p["doc_id"] in validation_docs]
    return train, val


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks", type=int, default=1500)
    parser.add_argument("--no-generate", action="store_true", help="only filter and split the pairs already generated")
    args = parser.parse_args()
    DATA_DIR.mkdir(exist_ok=True)

    raw_path = DATA_DIR / "raw_pairs.jsonl"
    if args.no_generate:
        pairs = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines()]
    else:
        pairs = generate(sample_chunks(args.chunks), raw_path)

    kept, stats = filter_pairs(pairs)
    train, val = split_by_document(kept)
    stats.update({"train": len(train), "validation": len(val),
                  "validation_documents": sorted({p["doc_id"] for p in val})})
    for name, rows in (("train", train), ("validation", val)):
        (DATA_DIR / f"{name}.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    review_path = DATA_DIR / "review_sample.json"
    if not review_path.exists():   # never overwrite a review already done by hand
        review = random.Random(SEED).sample(kept, min(50, len(kept)))
        review_path.write_text(json.dumps(
            [{"question": r["question"], "passage": r["passage"], "chunk_id": r["chunk_id"], "verdict": None} for r in review],
            indent=2), encoding="utf-8")
    (DATA_DIR / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
