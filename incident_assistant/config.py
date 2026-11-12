"""Project settings. Values can be overridden in the .env file."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

KNOWLEDGE_BASE_DIR = ROOT_DIR / "knowledge_base"
MANIFEST_PATH = KNOWLEDGE_BASE_DIR / "manifest.yaml"
STORAGE_DIR = ROOT_DIR / "storage"
QDRANT_PATH = STORAGE_DIR / "qdrant"
REGISTRY_PATH = STORAGE_DIR / "registry.json"

QDRANT_URL = os.getenv("QDRANT_URL", "")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "devops_kb")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
SPARSE_MODEL = "Qdrant/bm25"
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L6-v2")

LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
# Each agent can use its own model; when not set, both use LLM_MODEL (the default setting).
# Query rewriting uses the analyzer's model.
ANALYZER_MODEL = os.getenv("ANALYZER_MODEL") or LLM_MODEL
INVESTIGATOR_MODEL = os.getenv("INVESTIGATOR_MODEL") or LLM_MODEL
# The judge is from another model family than the agents (less self-preference bias).
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "qwen/qwen3.8-27b")
# Model used to generate the fine-tuning pairs (separate daily token quota on Groq).
PAIR_MODEL = os.getenv("PAIR_MODEL", "openai/gpt-oss-20b")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
MIN_CHUNK_CHARS = 200

RRF_K = 60
CANDIDATES_PER_SEARCH = 20   # results kept from each dense / BM25 search
RERANK_CANDIDATES = 20       # fused results given to the reranker
FINAL_PASSAGES = 6           # passages given to the investigation agent

# Evidence is "sufficient" when at least EVIDENCE_MIN_PASSAGES passages get a reranker score
# >= EVIDENCE_MIN_SCORE. Chosen on a validation set separate from the test set
# (evaluation/results/evidence_tuning.json). An earlier rule (-0.22, 2 passages) was too strict.
EVIDENCE_MIN_SCORE = float(os.getenv("EVIDENCE_MIN_SCORE", "-2.86"))
EVIDENCE_MIN_PASSAGES = int(os.getenv("EVIDENCE_MIN_PASSAGES", "3"))
MAX_REWRITES = 2
