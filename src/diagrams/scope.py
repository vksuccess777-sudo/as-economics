"""Which diagrams are AS content — decided by the spine, not by this file.

The previous diagram list was hand-written from memory and offered external
cost and external benefit diagrams as AS content. They are A Level (topic 7.4)
in the 2026-2028 syllabus: "externality" appears nowhere in the AS spine, and
Unit 3 at AS is public goods, merit and demerit goods and price control. A
student could have been shown a diagram off their course, and the essay marker
could have capped AO2 for not drawing one.

So nothing here asserts what is examinable. A catalogue entry declares the
terms it depends on; this module checks them against the AS text of the parsed
syllabus and drops any entry whose subject the syllabus does not mention. The
same mechanism the notes validator and the tutor already use — when Cambridge
revises the syllabus, regenerating the spine changes what is offered with no
code change.
"""

from __future__ import annotations

from ..notes.generator import as_vocabulary
from ..syllabus.models import SyllabusSpine
from . import catalogue as _catalogue
from .catalogue import DiagramEntry


def in_scope(spine: SyllabusSpine) -> tuple[DiagramEntry, ...]:
    """Catalogue entries whose subject the AS syllabus actually names."""
    vocabulary, excluded = as_vocabulary(spine)
    haystack = vocabulary.lower()
    excluded_lower = {term.lower() for term in excluded}
    kept = []
    # Read through the module, not a name bound at import time: a test that
    # appends an entry to the catalogue has to actually reach this loop, or it
    # asserts nothing and passes forever.
    for entry in _catalogue.CATALOGUE:
        if any(term.lower() not in haystack for term in entry.requires):
            continue
        if any(term.lower() in excluded_lower for term in entry.requires):
            continue
        kept.append(entry)
    return tuple(kept)


def for_topic(spine: SyllabusSpine, topic_code: str) -> tuple[DiagramEntry, ...]:
    """Diagrams a student revising this topic should see.

    Matches on the topic's own code and on its chapter, so 4.3.2 finds the
    AD/AS diagram registered against 4.3.
    """
    if not topic_code:
        return ()
    code = str(topic_code)
    chapter = code.split(".")[0]
    matches = []
    for entry in in_scope(spine):
        for registered in entry.topics:
            if code == registered or code.startswith(registered + "."):
                matches.append(entry)
                break
            if registered.startswith(chapter + ".") and registered == code:
                matches.append(entry)
                break
    return tuple(matches)


def out_of_scope_keys(spine: SyllabusSpine) -> tuple[str, ...]:
    """Catalogue entries the spine rules out. Empty today, and that is fine —
    the guard earns its place the next time Cambridge moves a topic."""
    kept = {entry.key for entry in in_scope(spine)}
    return tuple(e.key for e in _catalogue.CATALOGUE if e.key not in kept)


def rank_for_question(
    entries: tuple[DiagramEntry, ...], question: str
) -> tuple[DiagramEntry, ...]:
    """Put the diagram the question is actually about first.

    Topic 3.2 alone carries five diagrams — tax, subsidy, maximum price,
    minimum price, buffer stock. Taking them in catalogue order means "what is
    a maximum price" shows the tax diagram, which is a worse answer than
    showing nothing. Scored on how much of an entry's own label the question
    uses, so no list of keywords is maintained by hand.
    """
    text = (question or "").lower()
    stop = {"and", "the", "of", "a", "in", "its", "curve", "scheme", "policy"}

    def score(entry: DiagramEntry) -> tuple[int, int]:
        words = [
            w for w in entry.label.lower().replace("-", " ").split()
            if w not in stop and len(w) > 2
        ]
        hits = sum(1 for w in words if w in text)
        key_hit = 1 if entry.key.replace("_", " ") in text else 0
        return (-(hits + key_hit), 0)

    return tuple(sorted(entries, key=score))
