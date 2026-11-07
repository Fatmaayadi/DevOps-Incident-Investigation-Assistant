from incident_assistant import config
from incident_assistant.documents import (chunk_markdown, clean_text, document_metadata, is_useful_chunk,
                                          remove_repeated_lines)

CRASHLOOP = config.KNOWLEDGE_BASE_DIR / "markdown" / "kubernetes" / "k8s-crashloopbackoff.md"


def test_clean_text_removes_watermarks_and_hyphenation():
    text = "www.it-ebooks.info\nThe con-\ntainer   restarts.\n\n\n\nNext"
    assert clean_text(text) == "The container restarts.\n\nNext"


def test_short_or_table_of_contents_chunks_are_rejected():
    assert not is_useful_chunk("Too short")
    toc = "Chapter 1 . . . . . . . . . . 3\n" * 20
    assert not is_useful_chunk(toc)
    assert is_useful_chunk("A pod in CrashLoopBackOff keeps restarting because its main process exits. " * 4)


def test_repeated_headers_are_removed():
    pages = [f"Kubernetes Up and Running\nreal content of page {i}" for i in range(12)]
    cleaned = remove_repeated_lines(pages)
    assert all("Kubernetes Up and Running" not in page for page in cleaned)
    assert "real content of page 3" in cleaned[3]


def test_markdown_chunks_keep_section_and_skip_references():
    chunks = chunk_markdown(CRASHLOOP)
    sections = {c.metadata["section"] for c in chunks}
    assert "Possible Causes" in sections
    assert "References" not in sections and "Metadata" not in sections
    first = chunks[0]
    assert first.metadata["doc_id"] == "md-k8s-crashloopbackoff"
    assert first.page_content.startswith("Kubernetes Pod in CrashLoopBackOff > ")
    assert first.metadata["page"] is None


def test_document_metadata_for_markdown_and_pdf():
    md = document_metadata("md-k8s-crashloopbackoff")
    assert md["domain"] == "kubernetes" and md["references"]
    pdf = document_metadata("pdf-progit")
    assert pdf["kind"] == "pdf"
    assert "CC BY-NC-SA" in pdf["license"]
    assert document_metadata("does-not-exist") is None
