"""Ordinary English words that carry no subject meaning.

WHAT THIS IS NOT
----------------
This is not a claim about the syllabus. It never says a concept is in the AS
course and it never says one is out. The syllabus authority remains
`data/syllabus_spine.json`, parsed from Cambridge's own PDF, exactly as before.

WHAT IT IS FOR
--------------
The scope guard has to answer one question: when a word in a student's question
is missing from the AS vocabulary, is that evidence the question is off-syllabus?

For "indifference" the answer is yes — it is a technical term, and its absence
is the whole signal. For "affect", "happens", "increases" or "meant" the answer
is obviously no, but the old guard could not tell the two cases apart. It
counted every unknown content word equally, so

    "how does a subsidy affect the market"

failed on "affect" and was refused as out of syllabus. Listing the ordinary
words is what lets the guard fire on the technical unknown only.

DIRECTION OF ERROR
------------------
A word in this list can only ever *widen* what the tutor will answer; it can
never cause a refusal. So the failure mode of a missing word is a false refusal
(annoying, visible, easy to fix by adding the word) and the failure mode of a
wrong word is that one off-topic question reaches the retriever — where the
relevance floor still has to be cleared. That asymmetry is why a plain list is
safe here.

Economics terms are deliberately absent. "demand", "supply", "cost" and their
kind belong to the spine, not here.
"""

from __future__ import annotations

# Question framing, ordinary verbs, quantity words, school/exam vocabulary.
# Stored unstemmed; `general_words()` stems them with the same function the
# corpus uses, so the two sides can never drift.
_RAW = """
about above actual actually add advantage advantages affect affects again
against ahead all allow allowed almost along already also alternative always
amount amounts another answer answers any anyone anything apart apply approach
area areas argue argument arguments around ask asked asking aspect aspects
assume assumed assumption assumptions available avoid away back bad based
basic basically because become becomes been before begin behind being below
benefit benefits best better between big bit both bring called cannot case
cases cause caused causes certain chance change changed changes changing
chapter check choose chose class clear clearly come comes coming common
compare compared comparison complete completely concept concepts concern
conclusion conclusions confused confusing connect consequence consequences
consider consist contain context continue correct could count couple course
cover create created creates data day days deal decide decided decrease
decreased decreases decreasing definition definitions depend depends describe
detail details did differ different difficult direction disadvantage
disadvantages discuss does doing done down draw drawing drawn drop due during
each earlier easier easy effect effects either else end enough entire equal
error errors especially essay essays even ever every exact exactly exam exams
example examples except exercise exist expect explain explained explaining
extent fact factor factors fail failure fall fallen falling falls far fast
few figure figures find first fit five focus follow following follows form
found four full further gain general generally get give given gives giving
goes going good got great greater group grow growing grown grows guess had
half hand happen happened happening happens hard has have having help helps
here high higher highest hold home hope hour hours how however huge idea ideas
identify impact impacts important improve include included includes including
increase increased increases increasing indeed inside instead into issue issues
its itself just keep kept key kind know known lack large larger largest last
late later lead leading leads learn learning least leave left less lesson let
level levels like likely limit limited line link linked list little live long
longer look looking looks lose loss losses lost lot low lower lowest made main
mainly major make makes making many mark marker marking marks matter may maybe
mean meaning means meant measure measured measures method might mind minute
minutes miss mistake mistakes more most move moved movement moves moving much
must name named near nearly need needed needs never new next nice night nine
none normal normally not note notes nothing notice now number numbers occur
occurs off offer often okay once one only open opposite option options order
other others our out outcome outcomes over overall own paper papers paragraph
paragraphs part particular parts pass past people per percent perhaps period
person picture piece place plan play please point points poor position possible
practice prefer prepare present pretty prevent previous probably problem
problems process produce produced product products provide provided put
question questions quick quickly quite raise raised range rate rates rather
reach read reading real really reason reasons recent reduce reduced reduces
refer relate related relation relationship remain remains remember repeat
report require required requires respond response rest result results revise
revision right rise risen rises rising role rule rules run same say says school
score second section see seem seems seen sense sentence separate series serious
set several shall share short should show showing shown shows side significant
similar simple simply since single situation six size slightly small smaller
solution solve some someone something sometimes soon sort sound source sources
specific spend stage stand start started state statement stay step steps still
stop story straight strong stronger structure student students study subject
such suddenly suggest suitable summary support suppose sure system table take
taken takes taking talk teach teacher tell ten term terms test tests than thank
that their them themselves then theory there therefore they thing things think
third those though thought three through throughout thus time times today
together told too took top topic topics total toward towards tried try trying
turn twice two type types typical under understand understanding unit units
unless until upon use used useful uses using usually value values various very
view want was watch way ways week weeks well went were what whatever when where
whether which while who whole whom whose why wide will wish with within without
won word words work worked working works world worse worst would write writing
written wrong wrote year years yes yet you your yourself
"""

# Added after running real student phrasing through the gate: diagram talk,
# contractions the tokeniser strips apostrophes out of, and ordinary verbs
# that a syllabus written in noun phrases never needs.
_RAW += """
apostrophe axes axis bake bread cake confuse contain contains contrast
diagram diagrams downward downwards draws exact flat flatter hello hey
impose imposed imposes imposing introduce introduced introduces label
labelled labels okay please raises reduce remove removed removes shape
sloping slope slopes steep steeper stuck thanks tomorrow upward upwards
vertical horizontal
fix fixed fixes worth cheap cheaper expensive buy buys buying bought
sell sells selling sold pay pays paying paid earn earns
distribution distributed distribute differentiate differentiates
differentiated preparation preparing description explanation
comparison combination selection separation collection connection
introduction conclusion discussion instruction interpretation
arent cant cannot couldnt didnt doesnt dont hasnt havent hows ill
isnt ive lets shouldnt thats theres theyre wasnt werent whats wont
wouldnt youre youve weve
"""

# Anaphora and follow-up markers. Kept separate because they are also the
# signal that a short message is a follow-up rather than a new question.
FOLLOW_UP_MARKERS = frozenset(
    {
        "again", "another", "detail", "eli", "elaborate", "example", "examples",
        "expand", "further", "him", "her", "it", "its", "more", "one", "point",
        "previous", "same", "shorter", "simpler", "simply", "so", "still",
        "that", "them", "then", "these", "this", "those", "why",
    }
)


def general_words(stem) -> frozenset[str]:
    """Stem the list with the caller's own stemmer so the two cannot drift."""
    words = {w for w in _RAW.split() if w}
    return frozenset({stem(w) for w in words} | {stem(w) for w in FOLLOW_UP_MARKERS})
