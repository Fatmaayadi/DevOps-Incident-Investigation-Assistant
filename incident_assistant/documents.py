"""Loading, cleaning and chunking of the knowledge base (PDF + Markdown)."""
import hashlib
import re
from collections import Counter
from pathlib import Path

import yaml
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from pypdf import PdfReader

from incident_assistant import config

# Watermarks and promotional lines found during the PDF audit.
NOISE_PATTERNS = [
    r"www\.it-ebooks\.info",
    r"www\.allitebooks\.com",
    r"https?://www\.nginx\.com/solutions/adc/",
]
# Sections of the Markdown guides that are bibliographic, not diagnostic content.
SKIPPED_SECTIONS = {"References", "Metadata"}

splitter = RecursiveCharacterTextSplitter(chunk_size=config.CHUNK_SIZE, chunk_overlap=config.CHUNK_OVERLAP)


def file_hash(path: Path) -> str:
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(1 << 20):
            sha256.update(block)
    return sha256.hexdigest()


def clean_text(text: str) -> str:
    for pattern in NOISE_PATTERNS:
        text = re.sub(pattern, " ", text)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)      # words cut by a hyphen at end of line
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def is_useful_chunk(text: str) -> bool:
    """Reject very short chunks and table-of-contents / index pages (mostly dots and numbers)."""
    if len(text) < config.MIN_CHUNK_CHARS:
        return False
    letters = sum(c.isalpha() for c in text)
    if letters / len(text) < 0.5:
        return False
    return text.count(". . .") < 5 and text.count("....") < 5


def remove_repeated_lines(pages: list[str]) -> list[str]:
    """Remove running headers/footers: short lines that appear on more than half of the pages."""
    if len(pages) < 10:
        return pages
    counts = Counter(line.strip() for page in pages for line in set(page.splitlines()) if 0 < len(line.strip()) < 80)
    repeated = {line for line, n in counts.items() if n > len(pages) / 2}
    return ["\n".join(l for l in page.splitlines() if l.strip() not in repeated) for page in pages]


def load_manifest() -> list[dict]:
    """PDF documents marked as included in the manifest."""
    manifest = yaml.safe_load(config.MANIFEST_PATH.read_text(encoding="utf-8"))
    return [doc for doc in manifest["documents"] if doc["included"]]


def chunk_pdf(path: Path, info: dict) -> list[Document]:
    """One PDF -> chunks. Each chunk keeps the PDF page number (1-based) for citations."""
    reader = PdfReader(path)
    pages = remove_repeated_lines([page.extract_text() or "" for page in reader.pages])
    chunks = []
    for page_number, page_text in enumerate(pages, start=1):
        for text in splitter.split_text(clean_text(page_text)):
            if is_useful_chunk(text):
                chunks.append(Document(page_content=text, metadata={
                    "doc_id": info["doc_id"],
                    "title": info["title"],
                    "source_path": "pdf/" + info["path"].removeprefix("pdf/"),
                    "source_type": info.get("source_type", "book"),
                    "domain": info["domain"],
                    "technology": info.get("technology", []),
                    "page": page_number,
                    "section": None,
                }))
    return chunks


def read_markdown(path: Path) -> tuple[dict, str]:
    """Split a Markdown guide into its YAML front matter and its body."""
    _, front_matter, body = path.read_text(encoding="utf-8").split("---", 2)
    return yaml.safe_load(front_matter), body


def chunk_markdown(path: Path) -> list[Document]:
    """One Markdown guide -> chunks, split by section. The title and section are repeated
    at the start of each chunk so that a passage stays understandable on its own."""
    meta, body = read_markdown(path)
    header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=[("##", "section"), ("###", "subsection")])
    chunks = []
    for part in header_splitter.split_text(body):
        section = part.metadata.get("section")
        if section is None or section in SKIPPED_SECTIONS:
            continue
        heading = f"{meta['title']} > {section}"
        if part.metadata.get("subsection"):
            heading += f" > {part.metadata['subsection']}"
        for text in splitter.split_text(clean_text(part.page_content)):
            chunks.append(Document(page_content=f"{heading}\n{text}", metadata={
                "doc_id": meta["doc_id"],
                "title": meta["title"],
                "source_path": str(path.relative_to(config.KNOWLEDGE_BASE_DIR)).replace("\\", "/"),
                "source_type": meta["source_type"],
                "domain": meta["domain"],
                "technology": meta["technology"],
                "page": None,
                "section": section,
            }))
    return chunks


def list_source_files() -> list[dict]:
    """All files that must be indexed, with their doc_id and SHA-256 hash."""
    files = []
    for info in load_manifest():
        path = config.KNOWLEDGE_BASE_DIR / info["path"]
        files.append({"doc_id": info["doc_id"], "path": path, "kind": "pdf", "info": info, "hash": file_hash(path)})
    for path in sorted((config.KNOWLEDGE_BASE_DIR / "markdown").rglob("*.md")):
        meta, _ = read_markdown(path)
        files.append({"doc_id": meta["doc_id"], "path": path, "kind": "markdown", "info": meta, "hash": file_hash(path)})
    return files


def chunk_file(source: dict) -> list[Document]:
    chunks = chunk_pdf(source["path"], source["info"]) if source["kind"] == "pdf" else chunk_markdown(source["path"])
    for number, chunk in enumerate(chunks):
        chunk.metadata["chunk_id"] = f"{source['doc_id']}#{number}"
        chunk.metadata["file_hash"] = source["hash"]
    return chunks


def document_metadata(doc_id: str) -> dict | None:
    """Document-level metadata (used by the MCP server and the citations)."""
    for source in list_source_files():
        if source["doc_id"] == doc_id:
            info = source["info"]
            return {
                "doc_id": doc_id,
                "title": info["title"],
                "kind": source["kind"],
                "path": str(source["path"].relative_to(config.KNOWLEDGE_BASE_DIR)).replace("\\", "/"),
                "domain": info.get("domain"),
                "technology": info.get("technology", []),
                "source_type": info.get("source_type") or info.get("provenance"),
                "document_type": info.get("document_type", "book" if source["kind"] == "pdf" else None),
                "references": info.get("references", []),
                "license": info.get("license"),
            }
    return None
