"""Load the knowledge base and the syllabus's own exclusions into the tutor.

Used by both the Streamlit page and `scripts/check_tutor.py`, so what the
diagnostic reports is exactly what the app searches. Two loaders would drift,
and the one that drifted would be the diagnostic — the one you trust.

Missing notes are not an error. The tutor worked on the spine alone before the
knowledge base existed and still does; it just matches less student phrasing.
"""

from __future__ import annotations

from ..notes.generator import as_vocabulary, out_of_scope_terms
from ..syllabus.models import SyllabusSpine
from .retriever import Document, note_documents, tokenise


def load_note_documents(
    store, spine: SyllabusSpine, *, subject: str = "economics"
) -> list[Document]:
    docs: list[Document] = []
    if store is None:
        return docs
    try:
        topic_codes = store.note_topics(subject=subject)
    except Exception:  # pragma: no cover - a DB without the note table
        return docs

    for code in topic_codes:
        row = store.note(code, subject=subject)
        if not row:
            continue
        topic = spine.topic(code)
        docs.extend(
            note_documents(
                row["body"],
                topic_code=code,
                topic_title=topic.title if topic else code,
            )
        )
    return docs


def excluded_phrases(spine: SyllabusSpine) -> list[list[str]]:
    """Phrases naming content the AS syllabus marks as not required.

    Cambridge excludes inline and in brackets — "injections and leakages
    (multiplier not required)" — so "multiplier" appears in the spine text and
    is therefore in the retriever's vocabulary, but teaching it would waste
    revision time on material Paper 1 and Paper 2 cannot ask about.

    Returned as token sequences and matched as whole phrases, never token by
    token. Splitting them was the obvious implementation and the wrong one:
    "marginal revenue product" would have retired the word "revenue" and
    "natural rate of unemployment" the word "natural", both of which a student
    needs for content that IS on the AS course.

    Derived from the same two functions the notes validator uses, so the tutor
    and the note builder cannot come to disagree about the syllabus.
    """
    return [tokenise(phrase) for phrase in out_of_scope_terms(spine) if phrase.strip()]
