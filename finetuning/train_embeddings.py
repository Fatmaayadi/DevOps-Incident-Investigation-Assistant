"""Step 2 of the fine-tuning experiment: fine-tune all-MiniLM-L6-v2 on the generated pairs with
MultipleNegativesRankingLoss (the other passages of a batch are used as negatives).

Hyperparameters are fixed in advance (see the specification, section 21.6). The best epoch is
chosen on the validation split (documents never seen in training), never on the evaluation set.

Usage: python -m finetuning.train_embeddings
"""
import json
import random
import time
from pathlib import Path

from datasets import Dataset
from sentence_transformers import (SentenceTransformer, SentenceTransformerTrainer,
                                   SentenceTransformerTrainingArguments)
from sentence_transformers.evaluation import InformationRetrievalEvaluator
from sentence_transformers.losses import MultipleNegativesRankingLoss
from sentence_transformers.training_args import BatchSamplers

from incident_assistant import config
from incident_assistant.documents import chunk_file, list_source_files

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "output" / "minilm-devops"
RESULTS_DIR = Path(__file__).parent / "results"
SEED = 42
EPOCHS = 3
BATCH_SIZE = 32
LEARNING_RATE = 2e-5
WARMUP_RATIO = 0.1


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validation_evaluator(val_pairs: list[dict]) -> InformationRetrievalEvaluator:
    """Validation queries must find their own passage among the validation passages
    plus 1,000 random distractor chunks from the knowledge base."""
    corpus = {p["chunk_id"]: p["passage"] for p in val_pairs}
    all_chunks = [c for source in list_source_files() for c in chunk_file(source)]
    for chunk in random.Random(SEED).sample(all_chunks, 1000):
        corpus.setdefault(chunk.metadata["chunk_id"], chunk.page_content)
    queries = {str(i): p["question"] for i, p in enumerate(val_pairs)}
    relevant = {str(i): {p["chunk_id"]} for i, p in enumerate(val_pairs)}
    return InformationRetrievalEvaluator(queries, corpus, relevant, name="val", mrr_at_k=[10],
                                         accuracy_at_k=[1, 5, 10], precision_recall_at_k=[5, 10],
                                         ndcg_at_k=[10], map_at_k=[10])


def main():
    train_pairs = read_jsonl(DATA_DIR / "train.jsonl")
    val_pairs = read_jsonl(DATA_DIR / "validation.jsonl")
    print(f"{len(train_pairs)} training pairs, {len(val_pairs)} validation pairs")

    model = SentenceTransformer(config.EMBEDDING_MODEL)
    evaluator = validation_evaluator(val_pairs)
    before = evaluator(model)
    print("validation before fine-tuning:", {k: round(v, 4) for k, v in before.items() if "mrr" in k or "accuracy@5" in k})

    train_dataset = Dataset.from_list([{"anchor": p["question"], "positive": p["passage"]} for p in train_pairs])
    args = SentenceTransformerTrainingArguments(
        output_dir=str(OUTPUT_DIR / "checkpoints"),
        num_train_epochs=EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        learning_rate=LEARNING_RATE,
        warmup_ratio=WARMUP_RATIO,
        seed=SEED,
        batch_sampler=BatchSamplers.NO_DUPLICATES,   # avoid the same passage twice in a batch (false negatives)
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=1,
        load_best_model_at_end=True,
        metric_for_best_model="eval_val_cosine_mrr@10",
        logging_steps=10,
        report_to="none",
    )
    trainer = SentenceTransformerTrainer(model=model, args=args, train_dataset=train_dataset,
                                         loss=MultipleNegativesRankingLoss(model), evaluator=evaluator)
    start = time.perf_counter()
    trainer.train()
    minutes = round((time.perf_counter() - start) / 60, 1)

    after = evaluator(model)
    model.save(str(OUTPUT_DIR))
    RESULTS_DIR.mkdir(exist_ok=True)
    log = {
        "base_model": config.EMBEDDING_MODEL, "output_model": str(OUTPUT_DIR.relative_to(config.ROOT_DIR)),
        "train_pairs": len(train_pairs), "validation_pairs": len(val_pairs),
        "hyperparameters": {"epochs": EPOCHS, "batch_size": BATCH_SIZE, "learning_rate": LEARNING_RATE,
                            "warmup_ratio": WARMUP_RATIO, "seed": SEED, "loss": "MultipleNegativesRankingLoss"},
        "training_minutes": minutes, "device": str(model.device),
        "validation_before": {k: round(v, 4) for k, v in before.items()},
        "validation_after": {k: round(v, 4) for k, v in after.items()},
        "epoch_logs": [entry for entry in trainer.state.log_history if "eval_val_cosine_mrr@10" in entry],
    }
    (RESULTS_DIR / "training_log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(f"trained in {minutes} min; MRR@10 on validation {before['val_cosine_mrr@10']:.4f} -> {after['val_cosine_mrr@10']:.4f}")


if __name__ == "__main__":
    main()
