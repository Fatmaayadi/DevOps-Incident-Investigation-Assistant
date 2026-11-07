"""Qdrant collection, embeddings and incremental indexing of the knowledge base.

Run:  python -m incident_assistant.indexing            (add / update / remove changed files)
      python -m incident_assistant.indexing --rebuild  (delete the collection and index everything)
"""
import argparse
import json
from datetime import datetime, timezone
from functools import lru_cache

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_qdrant import FastEmbedSparse, QdrantVectorStore, RetrievalMode
from qdrant_client import QdrantClient, models

from incident_assistant import config
from incident_assistant.documents import chunk_file, list_source_files

DENSE_VECTOR = "dense"
SPARSE_VECTOR = "bm25"


@lru_cache
def get_client() -> QdrantClient:
    if config.QDRANT_URL:
        return QdrantClient(url=config.QDRANT_URL)
    config.QDRANT_PATH.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(config.QDRANT_PATH))


@lru_cache
def get_dense_embeddings(model_name: str = config.EMBEDDING_MODEL) -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(model_name=model_name)


@lru_cache
def get_sparse_embeddings() -> FastEmbedSparse:
    return FastEmbedSparse(model_name=config.SPARSE_MODEL)


def create_collection(client: QdrantClient, collection: str = config.COLLECTION_NAME, model_name: str = config.EMBEDDING_MODEL):
    """One collection with two vectors per chunk: a dense embedding and a sparse BM25 vector.
    The IDF modifier is required for real BM25 scoring: without it, Qdrant ignores term rarity
    (langchain-qdrant does not set it by default)."""
    size = len(get_dense_embeddings(model_name).embed_query("dimension probe"))
    client.create_collection(
        collection_name=collection,
        vectors_config={DENSE_VECTOR: models.VectorParams(size=size, distance=models.Distance.COSINE)},
        sparse_vectors_config={SPARSE_VECTOR: models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )


def get_vector_store(mode: RetrievalMode, collection: str = config.COLLECTION_NAME,
                     model_name: str = config.EMBEDDING_MODEL) -> QdrantVectorStore:
    return QdrantVectorStore(
        client=get_client(),
        collection_name=collection,
        embedding=get_dense_embeddings(model_name),
        sparse_embedding=get_sparse_embeddings(),
        retrieval_mode=mode,
        vector_name=DENSE_VECTOR,
        sparse_vector_name=SPARSE_VECTOR,
    )


def load_registry() -> dict:
    if config.REGISTRY_PATH.exists():
        return json.loads(config.REGISTRY_PATH.read_text(encoding="utf-8"))
    return {}


def save_registry(registry: dict):
    config.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    config.REGISTRY_PATH.write_text(json.dumps(registry, indent=2), encoding="utf-8")


def delete_document(client: QdrantClient, doc_id: str, collection: str = config.COLLECTION_NAME):
    client.delete(
        collection_name=collection,
        points_selector=models.FilterSelector(filter=models.Filter(
            must=[models.FieldCondition(key="metadata.doc_id", match=models.MatchValue(value=doc_id))]
        )),
    )


def update_index(rebuild: bool = False) -> dict:
    """Compare the files with the registry of indexed hashes and apply the differences."""
    client = get_client()
    collection = config.COLLECTION_NAME
    if rebuild and client.collection_exists(collection):
        client.delete_collection(collection)
    if not client.collection_exists(collection):
        create_collection(client, collection)
        registry = {}
    else:
        registry = load_registry()

    sources = {s["doc_id"]: s for s in list_source_files()}
    summary = {"added": [], "updated": [], "removed": [], "unchanged": []}
    store = get_vector_store(RetrievalMode.HYBRID, collection=collection)  # HYBRID mode computes both vectors when adding

    for doc_id in [d for d in registry if d not in sources]:
        delete_document(client, doc_id, collection)
        del registry[doc_id]
        summary["removed"].append(doc_id)

    for doc_id, source in sources.items():
        previous = registry.get(doc_id)
        if previous and previous["hash"] == source["hash"]:
            summary["unchanged"].append(doc_id)
            continue
        if previous:
            delete_document(client, doc_id, collection)
        chunks = chunk_file(source)
        store.add_documents(chunks, batch_size=64)
        registry[doc_id] = {
            "hash": source["hash"],
            "path": str(source["path"].relative_to(config.KNOWLEDGE_BASE_DIR)).replace("\\", "/"),
            "chunks": len(chunks),
            "indexed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        summary["updated" if previous else "added"].append(doc_id)
        print(f"{'updated' if previous else 'added':8} {doc_id} ({len(chunks)} chunks)")
        save_registry(registry)  # saved after each file, so an interruption loses little work

    save_registry(registry)
    return summary


def build_experiment_collection(collection: str, model_name: str):
    """Index everything into a separate collection with another embedding model
    (used to compare the fine-tuned model; no registry, always a full rebuild)."""
    client = get_client()
    if client.collection_exists(collection):
        client.delete_collection(collection)
    create_collection(client, collection, model_name)
    store = get_vector_store(RetrievalMode.HYBRID, collection=collection, model_name=model_name)
    for source in list_source_files():
        chunks = chunk_file(source)
        store.add_documents(chunks, batch_size=64)
        print(f"added    {source['doc_id']} ({len(chunks)} chunks)")


def main():
    parser = argparse.ArgumentParser(description="Index the knowledge base into Qdrant.")
    parser.add_argument("--rebuild", action="store_true", help="delete the collection and index everything again")
    parser.add_argument("--collection", help="build a separate experiment collection (full rebuild)")
    parser.add_argument("--model", default=config.EMBEDDING_MODEL, help="embedding model for --collection")
    args = parser.parse_args()
    if args.collection:
        build_experiment_collection(args.collection, args.model)
        return
    summary = update_index(rebuild=args.rebuild)
    print({key: len(value) for key, value in summary.items()})
    total = sum(entry["chunks"] for entry in load_registry().values())
    print(f"Index contains {len(load_registry())} documents and {total} chunks.")
    get_client().close()


if __name__ == "__main__":
    main()
