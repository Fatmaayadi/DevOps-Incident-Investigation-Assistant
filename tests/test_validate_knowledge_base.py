"""Tests of scripts/validate_knowledge_base.py on small knowledge bases built in a temporary folder.
The real guides are never modified."""
import hashlib
from pathlib import Path

import pytest
import yaml

from scripts import validate_knowledge_base as vkb

PDF_BYTES = b"%PDF-1.4 test file"
SECTIONS_TEXT = "This paragraph explains the incident with enough detail for a reader to act on it safely. " * 4


def guide_meta(doc_id: str, domain: str, **changes) -> dict:
    meta = {
        "doc_id": doc_id, "title": f"Guide {doc_id}", "domain": domain, "technology": [domain],
        "category": "testing", "document_type": "troubleshooting_guide", "difficulty": "beginner",
        "keywords": ["test"], "error_messages": [], "source_type": "team_written_from_official_docs",
        "language": "en",
        "references": [{"id": "R1", "title": "Doc", "publisher": "Vendor", "url": "https://example.org/doc",
                        "accessed": "2026-11-11"}],
        "related_corpus_documents": [],
        "last_reviewed": "2026-11-11", "review_status": "test",
    }
    meta.update(changes)
    return {key: value for key, value in meta.items() if value is not ...}   # ... removes a field


def guide_body(meta: dict, link: str) -> str:
    parts = [f"# {meta['title']}", ""]
    for section in vkb.SECTIONS:
        parts += [f"## {section}", ""]
        if section == "Overview":
            parts += [f"{SECTIONS_TEXT} Source [R1]. See `{link}`.", ""]
        elif section == "References":
            parts += ["- [R1] Vendor - *Doc*. https://example.org/doc", ""]
        else:
            parts += [SECTIONS_TEXT, ""]
    return "\n".join(parts)


def write_guide(kb: Path, folder: str, name: str, meta: dict, body: str):
    path = kb / "markdown" / folder / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{yaml.safe_dump(meta, sort_keys=False)}---\n\n{body}", encoding="utf-8")
    return path


@pytest.fixture
def kb(tmp_path: Path) -> Path:
    """A valid knowledge base: one indexed PDF and two guides that link to each other."""
    kb = tmp_path / "knowledge_base"
    pdf = kb / "pdf" / "demo" / "demo.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(PDF_BYTES)
    manifest = {
        "summary": {"total_files": 1, "included_files": 1, "included_pages": 3, "excluded_files": 0},
        "reference_sources": [],
        "documents": [{
            "doc_id": "pdf-demo", "path": "pdf/demo/demo.pdf", "title": "Demo", "pages": 3,
            "sha256": hashlib.sha256(PDF_BYTES).hexdigest(), "included": True, "license": "CC BY 4.0",
            "provenance": "open_license", "official_url": "https://example.org/demo.pdf",
        }],
    }
    (kb / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    alpha = guide_meta("md-alpha", "docker", related_corpus_documents=[{"doc_id": "pdf-demo", "pages": "1-2"}])
    write_guide(kb, "docker", "alpha", alpha, guide_body(alpha, "md-beta"))
    beta = guide_meta("md-beta", "linux")
    write_guide(kb, "linux", "beta", beta, guide_body(beta, "md-alpha"))
    return kb


def messages(report: vkb.Report, level: str = "ERROR") -> str:
    return "\n".join(f"{i.location}: {i.message}" for i in report.issues if i.level == level)


def test_valid_knowledge_base_has_no_error_and_no_warning(kb, capsys):
    report = vkb.validate(kb)
    assert report.issues == []
    assert len(report.documents) == 3 and report.valid_documents == 3
    assert vkb.main(["--kb-dir", str(kb)]) == 0
    output = capsys.readouterr().out
    assert "Documents analysed : 3 (2 Markdown guides, 1 manifest entries)" in output
    assert "Result: PASSED" in output


def test_missing_indexed_file_is_an_error_unless_allowed(kb):
    (kb / "pdf" / "demo" / "demo.pdf").unlink()
    assert "indexed file not found: pdf/demo/demo.pdf" in messages(vkb.validate(kb))
    assert vkb.main(["--kb-dir", str(kb)]) == 1
    allowed = vkb.validate(kb, allow_missing_pdfs=True)
    assert allowed.errors == []
    assert "indexed file absent" in messages(allowed, "WARNING")


def test_modified_pdf_does_not_match_its_sha256(kb):
    (kb / "pdf" / "demo" / "demo.pdf").write_bytes(PDF_BYTES + b" changed")
    assert "file content differs from its sha256" in messages(vkb.validate(kb))


def test_duplicate_identifier_between_guides(kb):
    meta = guide_meta("md-alpha", "docker")
    write_guide(kb, "docker", "alpha-copy", meta, guide_body(meta, "md-beta"))
    errors = messages(vkb.validate(kb))
    assert "markdown/docker/alpha-copy.md: duplicate doc_id 'md-alpha'" in errors
    assert "markdown/docker/alpha.md: duplicate doc_id 'md-alpha'" in errors


def test_duplicate_identifier_and_path_in_the_manifest(kb):
    manifest = yaml.safe_load((kb / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["documents"].append(dict(manifest["documents"][0]))
    manifest["documents"].append(dict(manifest["documents"][0], doc_id="pdf-other", path="PDF/demo/demo.pdf"))
    (kb / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    errors = messages(vkb.validate(kb))
    assert "duplicate doc_id 'pdf-demo' in the manifest" in errors
    assert "duplicate path 'PDF/demo/demo.pdf'" in errors


def test_missing_metadata(kb):
    meta = guide_meta("md-alpha", "docker", references=..., review_status=...)
    del meta["domain"]
    write_guide(kb, "docker", "alpha", meta, guide_body(guide_meta("md-alpha", "docker"), "md-beta"))
    report = vkb.validate(kb)
    assert "alpha.md: missing required metadata: domain, references" in messages(report)
    assert "missing recommended metadata: review_status" in messages(report, "WARNING")
    assert report.valid_documents == 2


def test_empty_documents(kb):
    meta = guide_meta("md-alpha", "docker")
    headings_only = "\n\n".join([f"# {meta['title']}"] + [f"## {s}" for s in vkb.SECTIONS])
    write_guide(kb, "docker", "alpha", meta, headings_only)
    (kb / "markdown" / "linux" / "beta.md").write_text("", encoding="utf-8")
    errors = messages(vkb.validate(kb))
    assert "alpha.md: document is empty" in errors
    assert "beta.md: empty file" in errors


def test_broken_internal_link(kb):
    meta = guide_meta("md-beta", "linux")
    write_guide(kb, "linux", "beta", meta, guide_body(meta, "md-does-not-exist"))
    assert "broken internal link: `md-does-not-exist`" in messages(vkb.validate(kb))


def test_related_corpus_document_must_be_indexed(kb):
    meta = guide_meta("md-beta", "linux", related_corpus_documents=[{"doc_id": "pdf-unknown"}])
    write_guide(kb, "linux", "beta", meta, guide_body(meta, "md-alpha"))
    assert "'pdf-unknown' is not in manifest.yaml" in messages(vkb.validate(kb))


def test_missing_section_is_a_structure_error(kb):
    meta = guide_meta("md-beta", "linux")
    body = guide_body(meta, "md-alpha").replace("## Prevention\n", "")
    write_guide(kb, "linux", "beta", meta, body)
    assert "missing ['Prevention']" in messages(vkb.validate(kb))


@pytest.mark.parametrize("content, expected", [
    ("documents: [unclosed", "invalid YAML"),
    ("summary: {}\n", "must be a mapping with a 'documents' list"),
])
def test_invalid_manifest(kb, capsys, content, expected):
    (kb / "manifest.yaml").write_text(content, encoding="utf-8")
    report = vkb.validate(kb)
    assert expected in messages(report)
    assert "broken internal link" not in messages(report)   # the guides are still checked
    assert vkb.main(["--kb-dir", str(kb)]) == 1
    assert "Result: FAILED" in capsys.readouterr().out


@pytest.mark.skipif(not (vkb.DEFAULT_KB_DIR / "markdown").is_dir(), reason="no Markdown guides in this checkout")
def test_real_knowledge_base_has_no_error():
    """The PDFs are not versioned: their absence is accepted here, as in a fresh clone."""
    report = vkb.validate(allow_missing_pdfs=True)
    assert report.errors == [], messages(report)
    assert sum(kind == "guide" for kind in report.documents.values()) == 23
