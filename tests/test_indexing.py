"""Incremental indexing on a temporary Qdrant storage and a temporary knowledge base.
Fake embeddings keep these tests fast; the real index and the real registry are never opened."""
import json
from types import SimpleNamespace

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_qdrant import SparseEmbeddings, SparseVector
from qdrant_client import QdrantClient

from incident_assistant import config, indexing, retrieval

COLLECTION = "pytest_indexing"
REAL_STORAGE = config.STORAGE_DIR


class FakeSparse(SparseEmbeddings):
    def embed_query(self, text):
        tokens = sorted({sum(word.encode()) for word in text.lower().split()})
        return SparseVector(indices=tokens, values=[1.0] * len(tokens))

    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]


def write_guide(kb, doc_id, overview="The pod keeps restarting.", folder="kubernetes"):
    path = kb / "markdown" / folder / f"{doc_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ndoc_id: {doc_id}\ntitle: Guide {doc_id}\ndomain: {folder}\ntechnology: [{folder}]\n"
                    f"source_type: team_written_from_official_docs\n---\n# Guide\n\n## Overview\n{overview}\n\n"
                    "## Symptoms\nThe service returns errors.\n\n## References\nNot indexed.\n", encoding="utf-8")
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    kb = tmp_path / "knowledge_base"
    (kb / "markdown").mkdir(parents=True)
    (kb / "manifest.yaml").write_text("documents: []\n", encoding="utf-8")
    client = QdrantClient(path=str(tmp_path / "qdrant"))
    monkeypatch.setattr(config, "KNOWLEDGE_BASE_DIR", kb)
    monkeypatch.setattr(config, "MANIFEST_PATH", kb / "manifest.yaml")
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(config, "REGISTRY_PATH", tmp_path / "registry.json")
    monkeypatch.setattr(config, "COLLECTION_NAME", COLLECTION)
    monkeypatch.setattr(indexing, "get_client", lambda: client)
    monkeypatch.setattr(indexing, "get_dense_embeddings", lambda model_name=None: DeterministicFakeEmbedding(size=8))
    monkeypatch.setattr(indexing, "get_sparse_embeddings", FakeSparse)
    assert not config.REGISTRY_PATH.is_relative_to(REAL_STORAGE)

    def payloads():
        points, _ = client.scroll(COLLECTION, limit=1000, with_payload=True)
        return [point.payload["metadata"] for point in points]

    def point_ids():
        return sorted(str(point.id) for point in client.scroll(COLLECTION, limit=1000)[0])

    yield SimpleNamespace(kb=kb, client=client, payloads=payloads, point_ids=point_ids,
                          registry=indexing.load_registry)
    client.close()


def assert_index_matches_registry(env):
    """Each chunk is present exactly once, and the registry describes the collection."""
    ids = [meta["chunk_id"] for meta in env.payloads()]
    assert len(ids) == len(set(ids)), "duplicate chunks"
    expected = {f"{doc_id}#{n}" for doc_id, entry in env.registry().items() for n in range(entry["chunks"])}
    assert set(ids) == expected


def interrupt_while_adding(monkeypatch, doc_id):
    """The store writes the first chunk of doc_id, then the process fails."""
    real_get_store = indexing.get_vector_store

    def get_store(*args, **kwargs):
        store = real_get_store(*args, **kwargs)
        real_add = store.add_documents

        def add_documents(chunks, batch_size=64):
            if chunks and chunks[0].metadata["doc_id"] == doc_id:
                real_add(chunks[:1], batch_size=batch_size)
                raise RuntimeError("interrupted")
            return real_add(chunks, batch_size=batch_size)

        store.add_documents = add_documents
        return store

    monkeypatch.setattr(indexing, "get_vector_store", get_store)
    return lambda: monkeypatch.setattr(indexing, "get_vector_store", real_get_store)


def test_second_run_without_changes_touches_nothing(env):
    write_guide(env.kb, "md-a")
    write_guide(env.kb, "md-b")
    assert sorted(indexing.update_index()["added"]) == ["md-a", "md-b"]
    registry, points = env.registry(), env.point_ids()

    summary = indexing.update_index()

    assert sorted(summary["unchanged"]) == ["md-a", "md-b"]
    assert not summary["added"] and not summary["updated"] and not summary["removed"]
    assert env.registry() == registry and env.point_ids() == points


def test_modified_document_is_replaced_without_stale_chunks(env):
    path = write_guide(env.kb, "md-a", overview="Old text. " * 150)     # several chunks in Overview
    write_guide(env.kb, "md-b")
    indexing.update_index()
    before = env.registry()["md-a"]["chunks"]
    other = [meta for meta in env.payloads() if meta["doc_id"] == "md-b"]

    write_guide(env.kb, "md-a", overview="New text.")
    summary = indexing.update_index()

    assert summary["updated"] == ["md-a"]
    assert env.registry()["md-a"]["chunks"] < before
    assert_index_matches_registry(env)
    texts = [meta["file_hash"] for meta in env.payloads() if meta["doc_id"] == "md-a"]
    assert set(texts) == {env.registry()["md-a"]["hash"]} and path.exists()
    assert sorted(m["chunk_id"] for m in env.payloads() if m["doc_id"] == "md-b") == sorted(m["chunk_id"] for m in other)


def test_removed_document_leaves_the_collection_and_the_registry(env):
    write_guide(env.kb, "md-a")
    write_guide(env.kb, "md-b").unlink()
    indexing.update_index()
    write_guide(env.kb, "md-b")
    indexing.update_index()

    (env.kb / "markdown" / "kubernetes" / "md-b.md").unlink()
    assert indexing.update_index()["removed"] == ["md-b"]

    assert set(env.registry()) == {"md-a"}
    assert {meta["doc_id"] for meta in env.payloads()} == {"md-a"}
    assert_index_matches_registry(env)


def test_indexed_payload_is_what_the_retrieval_module_reads(env):
    write_guide(env.kb, "md-a", overview="CrashLoopBackOff restart loop.")
    indexing.update_index()

    passages = retrieval.search("crashloopbackoff", "bm25", collection=COLLECTION)

    passage = next(p for p in passages if p["section"] == "Overview")
    assert passage["doc_id"] == "md-a" and passage["chunk_id"].startswith("md-a#")
    assert passage["source_path"] == "markdown/kubernetes/md-a.md"
    assert passage["domain"] == "kubernetes" and passage["page"] is None
    assert passage["text"].startswith("Guide md-a > Overview\n")


def test_document_without_indexable_section_is_recorded_with_zero_chunks(env):
    path = write_guide(env.kb, "md-a")
    path.write_text(path.read_text(encoding="utf-8").split("## Overview")[0] + "## References\nOnly references.\n",
                    encoding="utf-8")
    assert indexing.update_index()["added"] == ["md-a"]
    assert env.registry()["md-a"]["chunks"] == 0
    assert indexing.update_index()["unchanged"] == ["md-a"]


def test_interrupted_new_document_is_not_duplicated_by_the_next_run(env, monkeypatch):
    write_guide(env.kb, "md-a")
    restore = interrupt_while_adding(monkeypatch, "md-a")
    with pytest.raises(RuntimeError):
        indexing.update_index()
    restore()

    indexing.update_index()

    assert_index_matches_registry(env)


def test_lost_registry_does_not_duplicate_the_collection(env):
    write_guide(env.kb, "md-a")
    indexing.update_index()
    count = len(env.point_ids())
    config.REGISTRY_PATH.unlink()

    indexing.update_index()

    assert len(env.point_ids()) == count
    assert_index_matches_registry(env)


def test_interrupted_rebuild_does_not_leave_documents_marked_as_indexed(env, monkeypatch):
    write_guide(env.kb, "md-a")
    write_guide(env.kb, "md-b")
    indexing.update_index()
    restore = interrupt_while_adding(monkeypatch, "md-b")
    with pytest.raises(RuntimeError):
        indexing.update_index(rebuild=True)
    restore()

    indexing.update_index()

    assert {meta["doc_id"] for meta in env.payloads()} == {"md-a", "md-b"}
    assert_index_matches_registry(env)


def test_rebuild_replaces_every_point(env):
    write_guide(env.kb, "md-a")
    indexing.update_index()
    old_points = env.point_ids()

    assert indexing.update_index(rebuild=True)["added"] == ["md-a"]

    assert not set(old_points) & set(env.point_ids())
    assert_index_matches_registry(env)


def test_created_collection_is_empty_even_if_files_of_a_deleted_one_remain(env):
    write_guide(env.kb, "md-a")
    indexing.update_index()
    env.client.delete_collection(COLLECTION)

    indexing.create_collection(env.client, COLLECTION)

    assert env.client.count(COLLECTION, exact=True).count == 0


def test_rebuild_does_not_touch_the_collection_when_a_source_is_unreadable(env, monkeypatch):
    write_guide(env.kb, "md-a")
    indexing.update_index()
    registry, points = env.registry(), env.point_ids()

    def missing_source():
        raise FileNotFoundError("pdf/missing.pdf")

    def forbidden_delete(*args, **kwargs):
        pytest.fail("the collection was deleted before the sources were read")

    monkeypatch.setattr(indexing, "list_source_files", missing_source)
    monkeypatch.setattr(env.client, "delete_collection", forbidden_delete)
    with pytest.raises(FileNotFoundError):
        indexing.update_index(rebuild=True)

    assert env.point_ids() == points and env.registry() == registry


def test_interrupted_update_is_finished_even_if_the_file_is_restored(env, monkeypatch):
    original = write_guide(env.kb, "md-a").read_text(encoding="utf-8")
    indexing.update_index()
    expected = env.registry()["md-a"]["chunks"]

    write_guide(env.kb, "md-a", overview="Edited text.")
    restore = interrupt_while_adding(monkeypatch, "md-a")
    with pytest.raises(RuntimeError):
        indexing.update_index()
    restore()
    (env.kb / "markdown" / "kubernetes" / "md-a.md").write_text(original, encoding="utf-8")

    indexing.update_index()

    assert env.registry()["md-a"]["chunks"] == expected
    assert_index_matches_registry(env)


def test_moved_file_updates_the_source_path_of_its_chunks(env):
    path = write_guide(env.kb, "md-a")
    indexing.update_index()
    moved = env.kb / "markdown" / "linux" / "md-a.md"
    moved.parent.mkdir()
    path.rename(moved)

    assert indexing.update_index()["updated"] == ["md-a"]

    assert {meta["source_path"] for meta in env.payloads()} == {"markdown/linux/md-a.md"}
    assert json.loads(config.REGISTRY_PATH.read_text())["md-a"]["path"] == "markdown/linux/md-a.md"
    assert_index_matches_registry(env)
