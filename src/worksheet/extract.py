"""Get the text out of whatever the school handed over.

Four routes, chosen by extension, all of them free of new dependencies:

  .pdf            pdfplumber, already required for the syllabus parser
  .docx           the stdlib — a .docx is a zip holding XML, and pulling the
                  text runs of every paragraph and table cell out of it is
                  twenty lines. python-docx would be a dependency for that.
  .png .jpg ...   the Gemini transcriber already used for handwritten essays
  .txt .md        read it

The image route is injected as a callable rather than imported here, so the
whole module is testable without a key and without a network call.

A scanned PDF — pages that are pictures of text, with no text layer — is the
one case that cannot be handled silently, and it is common with worksheets
because schools photocopy. It is detected and named, with the fix, instead of
returning three characters of whitespace and letting segmentation report an
empty worksheet.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

TEXT_SUFFIXES = {".txt", ".md", ".text"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | IMAGE_SUFFIXES | {".pdf", ".docx"}

# Below this many characters per page, a PDF has no usable text layer.
MIN_CHARS_PER_PAGE = 40

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass
class Extraction:
    text: str
    kind: str  # pdf | docx | text | image
    pages: int = 0
    warnings: list[str] = field(default_factory=list)
    ok: bool = True

    @property
    def char_count(self) -> int:
        return len(self.text.strip())


def suffix_of(name: str) -> str:
    return Path(name).suffix.lower()


def is_supported(name: str) -> bool:
    return suffix_of(name) in SUPPORTED_SUFFIXES


def extract(
    name: str,
    data: bytes,
    *,
    transcriber=None,
    mime_type: str | None = None,
) -> Extraction:
    """Read `data` into text. `transcriber(bytes, mime) -> str` handles images."""
    suffix = suffix_of(name)

    if suffix == ".pdf":
        return _from_pdf(data)
    if suffix == ".docx":
        return _from_docx(data)
    if suffix in IMAGE_SUFFIXES:
        return _from_image(data, suffix, transcriber, mime_type)
    if suffix in TEXT_SUFFIXES or not suffix:
        return Extraction(text=_decode(data), kind="text")

    return Extraction(
        text="",
        kind="unknown",
        ok=False,
        warnings=[
            f"{suffix or 'This file'} is not a format I can read. Supported: "
            + ", ".join(sorted(SUPPORTED_SUFFIXES))
            + ". A .doc (old Word format) needs saving as .docx first."
        ],
    )


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _from_pdf(data: bytes) -> Extraction:
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover - dependency is in requirements.txt
        return Extraction(
            text="", kind="pdf", ok=False,
            warnings=["pdfplumber is not installed — pip install -r requirements.txt"],
        )

    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")

    text = "\n".join(pages).strip()
    result = Extraction(text=text, kind="pdf", pages=len(pages))

    if pages and len(text) < MIN_CHARS_PER_PAGE * len(pages):
        result.ok = False
        result.warnings.append(
            "This PDF has almost no text layer — it is a scan or photo of a page "
            "rather than a document. Photograph the worksheet with your phone and "
            "upload the image instead: that route reads the page with a vision "
            "model, which handles scans."
        )
    return result


def _from_docx(data: bytes) -> Extraction:
    """Pull text runs out of the document XML. No third-party library.

    Paragraph breaks become newlines and table cells are joined with a tab,
    which is what segmentation expects: mark allocations in worksheet tables
    sit in their own cell and would otherwise merge into the question text.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError):
        return Extraction(
            text="", kind="docx", ok=False,
            warnings=[
                "This file is not readable as a .docx. If it is an old .doc, open "
                "it in Word and Save As .docx."
            ],
        )

    root = ElementTree.fromstring(xml)
    lines: list[str] = []
    for paragraph in root.iter(f"{W_NS}p"):
        pieces: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{W_NS}t" and node.text:
                pieces.append(node.text)
            elif node.tag in (f"{W_NS}tab",):
                pieces.append("\t")
            elif node.tag in (f"{W_NS}br", f"{W_NS}cr"):
                pieces.append("\n")
        line = "".join(pieces).strip()
        lines.append(line)

    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return Extraction(text=text, kind="docx")


def _from_image(
    data: bytes, suffix: str, transcriber, mime_type: str | None
) -> Extraction:
    if transcriber is None:
        return Extraction(
            text="", kind="image", ok=False,
            warnings=[
                "Reading a photo needs GEMINI_API_KEY in your .env — Groq and "
                "Mistral's free tiers here are text-only. Either add the key or "
                "type the questions into the paste box."
            ],
        )
    mime = mime_type or f"image/{'jpeg' if suffix in {'.jpg', '.jpeg'} else suffix.lstrip('.')}"
    text = (transcriber(data, mime) or "").strip()
    result = Extraction(text=text, kind="image")
    if not text:
        result.ok = False
        result.warnings.append(
            "Nothing readable came back from the photo. A flatter angle and more "
            "light usually fixes it; otherwise paste the questions as text."
        )
    return result


TRANSCRIBE_WORKSHEET_PROMPT = """Transcribe this worksheet page exactly as printed.

Rules:
- Keep every question number, part letter and mark allocation exactly as shown,
  including brackets: 3, (a), (ii), [4], (6 marks).
- Put each question, part and multiple-choice option on its own line.
- Keep the wording verbatim. Do not answer anything, do not summarise, do not
  correct spelling or grammar, do not skip a question because it looks like a
  repeat.
- Transcribe table contents row by row.
- If a question refers to a diagram or graph you can see, transcribe the
  question and then add a line: [diagram: <short description of what is drawn,
  including axis labels and curve labels>].
- Output the text only, with no commentary."""
