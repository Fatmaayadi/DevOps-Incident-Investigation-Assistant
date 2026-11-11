"""Quality checks of the knowledge base: knowledge_base/manifest.yaml (PDF corpus) and the
Markdown guides of knowledge_base/markdown/.

Run from the project root:
    python scripts/validate_knowledge_base.py
    python scripts/validate_knowledge_base.py --allow-missing-pdfs   # fresh clone: PDFs are not in Git
    python scripts/validate_knowledge_base.py --all-hashes           # also check excluded PDFs

Exit code: 0 when there is no error (warnings do not block), 1 when at least one error is found.
The rules follow the existing format (see knowledge_base/README.md); this script only reads files.
"""
import argparse
import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

DEFAULT_KB_DIR = Path(__file__).resolve().parent.parent / "knowledge_base"

# Manifest (PDF corpus)
MANIFEST_REQUIRED_FIELDS = ["doc_id", "path", "title", "included"]
INCLUDED_RECOMMENDED_FIELDS = ["sha256", "license", "provenance"]
# official_url may be null when no official source exists, provided url_check explains why.
SUMMARY_FIELDS = ["total_files", "included_files", "included_pages", "excluded_files"]

# Markdown guides
GUIDE_REQUIRED_FIELDS = ["doc_id", "title", "domain", "technology", "category", "document_type",
                         "difficulty", "keywords", "source_type", "references"]
GUIDE_RECOMMENDED_FIELDS = ["language", "error_messages", "last_reviewed", "review_status"]
GUIDE_LIST_FIELDS = ["technology", "keywords", "references", "error_messages", "related_corpus_documents"]
EXPECTED_SOURCE_TYPE = "team_written_from_official_docs"
SECTIONS = ["Overview", "Symptoms", "Possible Causes", "Investigation Steps", "Diagnostic Commands",
            "Interpretation of Results", "Possible Solutions", "Prevention", "Related Concepts",
            "References", "Metadata"]
MIN_BODY_WORDS = 300   # the shortest real guide has about 1,100 words

GUIDE_LINK = re.compile(r"`(md-[a-z0-9-]+)`")
CITATION = re.compile(r"\[(R\d+(?:\s*,\s*R\d+)*)\]")
DELIMITER = re.compile(r"^---[ \t]*$", re.MULTILINE)
SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class Issue:
    level: str        # "ERROR" or "WARNING"
    location: str     # file (and entry) concerned, relative to the knowledge base
    message: str


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    documents: dict[str, str] = field(default_factory=dict)   # location -> kind ("guide" or "manifest entry")

    def error(self, location: str, message: str):
        self.issues.append(Issue("ERROR", location, message))

    def warning(self, location: str, message: str):
        self.issues.append(Issue("WARNING", location, message))

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "ERROR"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "WARNING"]

    @property
    def valid_documents(self) -> int:
        with_errors = {i.location for i in self.errors}
        return sum(1 for location in self.documents if location not in with_errors)


@dataclass
class Guide:
    location: str
    meta: dict
    body: str


def is_empty(value) -> bool:
    return value is None or value == "" or value == [] or value == {}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def outside_code_blocks(text: str) -> list[str]:
    lines, inside = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            inside = not inside
        elif not inside:
            lines.append(line)
    return lines


# ---------------------------------------------------------------- manifest

def load_manifest(kb_dir: Path, report: Report) -> dict | None:
    path = kb_dir / "manifest.yaml"
    if not path.is_file():
        report.error("manifest.yaml", "file not found")
        return None
    try:
        manifest = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (yaml.YAMLError, UnicodeDecodeError) as error:
        report.error("manifest.yaml", f"invalid YAML: {' '.join(str(error).split())}")
        return None
    if not isinstance(manifest, dict) or not isinstance(manifest.get("documents"), list):
        report.error("manifest.yaml", "must be a mapping with a 'documents' list")
        return None
    return manifest


def check_manifest(kb_dir: Path, manifest: dict, report: Report, allow_missing_pdfs: bool,
                   all_hashes: bool) -> dict[str, dict]:
    """Check every entry; return the valid entries by doc_id."""
    entries, seen_paths, missing_excluded = {}, {}, []
    for number, entry in enumerate(manifest["documents"]):
        if not isinstance(entry, dict):
            report.error(f"manifest.yaml: documents[{number}]", "entry is not a mapping")
            continue
        location = f"manifest.yaml: {entry.get('doc_id') or f'documents[{number}]'}"
        report.documents[location] = "manifest entry"
        missing = [name for name in MANIFEST_REQUIRED_FIELDS if is_empty(entry.get(name))]
        if missing:
            report.error(location, f"missing required fields: {', '.join(missing)}")
            continue
        if not isinstance(entry["included"], bool):
            report.error(location, "'included' must be true or false")
            continue
        doc_id, rel_path = str(entry["doc_id"]), str(entry["path"])
        if doc_id in entries:
            report.error(location, f"duplicate doc_id '{doc_id}' in the manifest")
            continue
        entries[doc_id] = entry

        posix = PurePosixPath(rel_path.replace("\\", "/"))
        if posix.is_absolute() or ".." in posix.parts or re.match(r"^[A-Za-z]:", rel_path):
            report.error(location, f"path must be relative to knowledge_base/: {rel_path}")
            continue
        key = str(posix).lower()   # Windows and macOS file systems ignore case
        if key in seen_paths:
            report.error(location, f"duplicate path '{rel_path}' (also used by {seen_paths[key]})")
        seen_paths[key] = doc_id
        if posix.suffix.lower() != ".pdf":
            report.warning(location, f"the manifest describes PDFs, but this path is not a .pdf: {rel_path}")

        sha = entry.get("sha256")
        if sha is not None and not SHA256.match(str(sha)):
            report.error(location, "sha256 is not a 64-character hexadecimal digest")
            sha = None
        if entry["included"]:
            absent = [name for name in INCLUDED_RECOMMENDED_FIELDS if is_empty(entry.get(name))]
            if is_empty(entry.get("official_url")) and is_empty(entry.get("url_check")):
                absent.append("official_url (or url_check explaining its absence)")
            if absent:
                report.warning(location, f"indexed document without traceability fields: {', '.join(absent)}")
        elif is_empty(entry.get("exclusion_reasons")):
            report.warning(location, "excluded document without 'exclusion_reasons'")

        file = kb_dir / posix
        if not file.is_file():
            if not entry["included"]:
                missing_excluded.append(location)
            elif allow_missing_pdfs:
                report.warning(location, f"indexed file absent (allowed by --allow-missing-pdfs): {rel_path}")
            else:
                report.error(location, f"indexed file not found: {rel_path}")
            continue
        if sha and (entry["included"] or all_hashes) and sha256_of(file) != sha:
            (report.error if entry["included"] else report.warning)(
                location, "file content differs from its sha256 in the manifest")

    if missing_excluded:   # one warning: these files are not indexed, and absent from every fresh clone
        names = ", ".join(location.removeprefix("manifest.yaml: ") for location in missing_excluded[:3])
        more = f" and {len(missing_excluded) - 3} more" if len(missing_excluded) > 3 else ""
        report.warning("pdf/", f"{len(missing_excluded)} excluded PDF(s) not found (not needed for indexing): {names}{more}")

    check_summary(manifest, report)
    check_unlisted_pdfs(kb_dir, seen_paths, report)
    return entries


def check_summary(manifest: dict, report: Report):
    summary = manifest.get("summary")
    if not isinstance(summary, dict):
        report.warning("manifest.yaml: summary", "no 'summary' section")
        return
    documents = [d for d in manifest["documents"] if isinstance(d, dict)]
    included = [d for d in documents if d.get("included") is True]
    actual = {
        "total_files": len(documents),
        "included_files": len(included),
        "included_pages": sum(d.get("pages") or 0 for d in included if isinstance(d.get("pages"), int)),
        "excluded_files": len(documents) - len(included),
    }
    for name in SUMMARY_FIELDS:
        if name in summary and summary[name] != actual[name]:
            report.warning("manifest.yaml: summary", f"{name} = {summary[name]}, but the entries give {actual[name]}")


def check_unlisted_pdfs(kb_dir: Path, listed_paths: dict, report: Report):
    pdf_dir = kb_dir / "pdf"
    if not pdf_dir.is_dir():
        return
    for file in sorted(pdf_dir.rglob("*")):
        rel = file.relative_to(kb_dir).as_posix()
        if file.is_file() and file.suffix.lower() == ".pdf" and rel.lower() not in listed_paths:
            report.warning(rel, "PDF present on disk but not declared in manifest.yaml (never indexed)")


# ---------------------------------------------------------------- Markdown guides

def read_guide(kb_dir: Path, path: Path, report: Report) -> Guide | None:
    location = path.relative_to(kb_dir).as_posix()
    report.documents[location] = "guide"
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        report.error(location, "file is not valid UTF-8")
        return None
    parts = DELIMITER.split(text, maxsplit=2)
    if not text.strip():
        report.error(location, "empty file")
        return None
    if len(parts) < 3 or parts[0].strip():
        report.error(location, "no YAML front matter (the file must start with a '---' line)")
        return None
    try:
        meta = yaml.safe_load(parts[1])
    except yaml.YAMLError as error:
        report.error(location, f"invalid YAML front matter: {' '.join(str(error).split())}")
        return None
    if not isinstance(meta, dict):
        report.error(location, "the front matter must be a YAML mapping")
        return None
    return Guide(location, meta, parts[2])


def check_metadata(guide: Guide, report: Report):
    meta, location = guide.meta, guide.location
    missing = [name for name in GUIDE_REQUIRED_FIELDS if is_empty(meta.get(name))]
    if missing:
        report.error(location, f"missing required metadata: {', '.join(missing)}")
    absent = [name for name in GUIDE_RECOMMENDED_FIELDS if name not in meta]
    if absent:
        report.warning(location, f"missing recommended metadata: {', '.join(absent)}")
    for name in GUIDE_LIST_FIELDS:
        if name in meta and meta[name] is not None and not isinstance(meta[name], list):
            report.error(location, f"'{name}' must be a list")
    if meta.get("doc_id") and not str(meta["doc_id"]).startswith("md-"):
        report.error(location, f"doc_id of a guide must start with 'md-': {meta['doc_id']}")
    if meta.get("source_type") and meta["source_type"] != EXPECTED_SOURCE_TYPE:
        report.error(location, f"source_type must be '{EXPECTED_SOURCE_TYPE}'")
    folder = PurePosixPath(location).parent.name
    if meta.get("domain") and folder != meta["domain"]:
        report.warning(location, f"stored in folder '{folder}' but domain is '{meta['domain']}'")


def check_structure(guide: Guide, report: Report):
    body, location = guide.body, guide.location
    if sum(1 for line in body.splitlines() if line.lstrip().startswith("```")) % 2:
        report.error(location, "unclosed code block (odd number of ``` lines)")
    lines = outside_code_blocks(body)
    words = [w for line in lines if not line.startswith("#") for w in line.split()]
    if not words:
        report.error(location, "document is empty (no text outside the headings)")
        return
    if len(words) < MIN_BODY_WORDS:
        report.warning(location, f"document is short: {len(words)} words (minimum recommended {MIN_BODY_WORDS})")

    titles = [line[2:].strip() for line in lines if line.startswith("# ")]
    if len(titles) != 1:
        report.warning(location, f"expected one '# ' title, found {len(titles)}")
    elif guide.meta.get("title") and titles[0] != str(guide.meta["title"]).strip():
        report.warning(location, "the '# ' title differs from the 'title' metadata")

    sections = [line[3:].strip() for line in lines if line.startswith("## ")]
    if sections != SECTIONS:
        missing = [s for s in SECTIONS if s not in sections]
        extra = [s for s in sections if s not in SECTIONS]
        detail = f"missing {missing}" if missing else f"unexpected {extra}" if extra else "wrong order"
        report.error(location, f"sections must be the {len(SECTIONS)} standard '## ' sections in order: {detail}")
        return
    for name, content in split_sections(lines).items():
        if not any(line.strip() and not line.startswith("#") for line in content):
            report.warning(location, f"section '{name}' is empty")


def split_sections(lines: list[str]) -> dict[str, list[str]]:
    sections, current = {}, None
    for line in lines:
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current:
            sections[current].append(line)
    return sections


def check_references(guide: Guide, report: Report):
    references, location = guide.meta.get("references"), guide.location
    if not isinstance(references, list):
        return   # already reported by check_metadata
    declared = []
    for reference in references:
        if not isinstance(reference, dict) or not re.fullmatch(r"R\d+", str(reference.get("id", ""))):
            report.error(location, f"reference without a valid id (R1, R2...): {reference}")
            continue
        declared.append(reference["id"])
        if not str(reference.get("url", "")).startswith("https://"):
            report.error(location, f"{reference['id']}: url must start with https://")
        if is_empty(reference.get("accessed")):
            report.error(location, f"{reference['id']}: missing 'accessed' date")
        if is_empty(reference.get("title")):
            report.warning(location, f"{reference['id']}: missing title")
    duplicates = sorted({r for r in declared if declared.count(r) > 1})
    if duplicates:
        report.error(location, f"duplicate reference ids: {', '.join(duplicates)}")

    text, _, references_section = guide.body.partition("\n## References")
    cited = {r for group in CITATION.findall(text) for r in re.split(r"\s*,\s*", group)}
    if set(declared) - cited:
        report.error(location, f"references declared but never cited: {', '.join(sorted(set(declared) - cited))}")
    if cited - set(declared):
        report.error(location, f"citations without a declared reference: {', '.join(sorted(cited - set(declared)))}")
    listed = set(re.findall(r"^- \[(R\d+)\]", references_section.split("\n## Metadata")[0], re.MULTILINE))
    if references_section and listed != set(declared):
        report.warning(location, f"'References' section lists {sorted(listed)}, metadata declares {sorted(set(declared))}")


def check_links(guides: list[Guide], manifest_entries: dict[str, dict] | None, report: Report):
    """Links between guides; related_corpus_documents only when the manifest could be read (not None)."""
    guide_ids = {str(g.meta["doc_id"]) for g in guides if g.meta.get("doc_id")}
    linked = set()
    for guide in guides:
        for target in sorted(set(GUIDE_LINK.findall(guide.body))):
            if target not in guide_ids:
                report.error(guide.location, f"broken internal link: `{target}` is not the doc_id of any guide")
            elif target != guide.meta.get("doc_id"):
                linked.add(target)
        related = guide.meta.get("related_corpus_documents") or []
        if manifest_entries is None or not isinstance(related, list):
            continue
        for item in related:
            target = item.get("doc_id") if isinstance(item, dict) else None
            entry = manifest_entries.get(target)
            if entry is None:
                report.error(guide.location, f"related_corpus_documents: '{target}' is not in manifest.yaml")
            elif not entry.get("included"):
                report.error(guide.location, f"related_corpus_documents: '{target}' is excluded from the index")
    for guide in guides:
        if guide.meta.get("doc_id") and str(guide.meta["doc_id"]) not in linked:
            report.warning(guide.location, "no other guide links to this guide")


def check_duplicate_ids(guides: list[Guide], manifest: dict | None, report: Report):
    owners = {}
    for guide in guides:
        if guide.meta.get("doc_id"):
            owners.setdefault(str(guide.meta["doc_id"]), []).append(guide.location)
    if manifest:
        for item in (manifest.get("documents") or []) + (manifest.get("reference_sources") or []):
            if isinstance(item, dict) and item.get("doc_id"):
                owners.setdefault(str(item["doc_id"]), []).append("manifest.yaml")
    for doc_id, locations in owners.items():
        # duplicates inside the manifest alone are reported by check_manifest
        if len(locations) > 1 and any(loc != "manifest.yaml" for loc in locations):
            for location in set(locations) - {"manifest.yaml"}:
                others = [loc for loc in locations if loc != location] or [location]
                report.error(location, f"duplicate doc_id '{doc_id}' (also used in {', '.join(others)})")


def check_other_files(kb_dir: Path, report: Report):
    markdown_dir = kb_dir / "markdown"
    for file in sorted(kb_dir.rglob("*")):
        if not file.is_file():
            continue
        rel = file.relative_to(kb_dir).as_posix()
        inside_markdown = file.is_relative_to(markdown_dir)
        if inside_markdown and file.suffix.lower() != ".md":
            report.warning(rel, "file in markdown/ that is not a .md guide (never indexed)")
        elif not inside_markdown and file.suffix.lower() == ".md" and rel != "README.md":
            report.warning(rel, "Markdown file outside markdown/ (never indexed)")


# ---------------------------------------------------------------- entry points

def validate(kb_dir: Path = DEFAULT_KB_DIR, allow_missing_pdfs: bool = False, all_hashes: bool = False) -> Report:
    report = Report()
    kb_dir = Path(kb_dir)
    if not kb_dir.is_dir():
        report.error(str(kb_dir), "knowledge base folder not found")
        return report
    manifest = load_manifest(kb_dir, report)
    entries = check_manifest(kb_dir, manifest, report, allow_missing_pdfs, all_hashes) if manifest else {}

    markdown_dir = kb_dir / "markdown"
    paths = sorted(markdown_dir.rglob("*.md")) if markdown_dir.is_dir() else []
    if not paths:
        report.error("markdown/", "no Markdown guide found")
    guides = [g for g in (read_guide(kb_dir, p, report) for p in paths) if g]
    for guide in guides:
        check_metadata(guide, report)
        check_structure(guide, report)
        check_references(guide, report)
    check_duplicate_ids(guides, manifest, report)
    check_links(guides, entries if manifest else None, report)
    check_other_files(kb_dir, report)
    return report


def print_report(report: Report, kb_dir: Path):
    print(f"Knowledge base validation: {kb_dir}")
    for title, issues in (("Errors (blocking)", report.errors), ("Warnings (not blocking)", report.warnings)):
        if issues:
            print(f"\n{title}:")
            for issue in sorted(issues, key=lambda i: i.location):
                print(f"  [{issue.level}] {issue.location}: {issue.message}")
    guides = sum(1 for kind in report.documents.values() if kind == "guide")
    entries = len(report.documents) - guides
    print("\nSummary")
    print(f"  Documents analysed : {len(report.documents)} ({guides} Markdown guides, {entries} manifest entries)")
    print(f"  Valid documents    : {report.valid_documents}")
    print(f"  Errors             : {len(report.errors)}")
    print(f"  Warnings           : {len(report.warnings)}")
    print(f"\nResult: {'FAILED' if report.errors else 'PASSED'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the knowledge base (manifest.yaml and Markdown guides).")
    parser.add_argument("--kb-dir", type=Path, default=DEFAULT_KB_DIR, help="knowledge base folder (default: %(default)s)")
    parser.add_argument("--allow-missing-pdfs", action="store_true",
                        help="report absent PDFs as warnings (the PDFs are not versioned in Git)")
    parser.add_argument("--all-hashes", action="store_true",
                        help="also check the sha256 of excluded PDFs (slower; indexed PDFs are always checked)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    report = validate(args.kb_dir, args.allow_missing_pdfs, args.all_hashes)
    print_report(report, args.kb_dir)
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
