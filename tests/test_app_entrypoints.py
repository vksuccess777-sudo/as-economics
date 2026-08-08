"""Guards against the failure that cost a week: screens that do not appear.

Streamlit builds its sidebar by globbing `pages/*.py` next to the entry script.
Nothing fails loudly when that glob comes back empty — you get a working app
with no navigation, which reads as "the feature was never built". These tests
fail loudly instead.

They now also fail on the opposite problem, which is what actually happened
next: a zip cannot delete files, so unzipping an increment leaves a merged-away
screen on disk and the sidebar shows it beside its replacement. The old version
of this file asked `EXPECTED_PAGES <= found` — a subset check, which is blind
to anything extra. 288 tests passed while two dead screens sat in the sidebar.
The set comparison below is exact for exactly that reason.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE_NAME = re.compile(r"^(\d+)_[A-Za-z0-9_\-]+\.py$")

EXPECTED_PAGES = {
    "1_MCQ_Practice.py",
    "2_Concept_Tutor.py",
    "3_Essay_Practice.py",
    "4_AI_Coach.py",
    "5_Knowledge_Base.py",
    "6_Worksheet_Helper.py",
    "7_Mock_Test.py",
}

# Screens folded into another one. Named so a failure can say "this is a
# leftover, delete it" instead of "unexpected file".
RETIRED_PAGES = {
    "4_Progress.py": "4_AI_Coach.py",
    "6_Coach.py": "4_AI_Coach.py",
    # Withdrawn rather than merged: Section A needs a registered dataset and
    # that was not wanted. Its engine and tests stay.
    "7_Data_Response.py": "nothing — the screen was withdrawn",
}


def _load_check_pages():
    """scripts/ is not a package, so load the module from its path."""
    path = ROOT / "scripts" / "check_pages.py"
    spec = importlib.util.spec_from_file_location("check_pages", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_pages_directory_exists_next_to_the_entry_script():
    assert (ROOT / "Home.py").exists()
    assert (ROOT / "pages").is_dir()


def test_every_screen_is_where_streamlit_looks_for_it():
    found = {p.name for p in (ROOT / "pages").glob("*.py")}
    assert EXPECTED_PAGES <= found, f"missing screens: {EXPECTED_PAGES - found}"


def test_no_retired_screen_left_on_disk():
    """A zip cannot delete. This is what an unzip-over-the-top leaves behind."""
    found = {p.name for p in (ROOT / "pages").glob("*.py")}
    leftover = sorted(found & set(RETIRED_PAGES))
    assert not leftover, (
        "these screens were merged away but are still in pages/, so the sidebar "
        "shows them: "
        + ", ".join(f"{n} (now part of {RETIRED_PAGES[n]})" for n in leftover)
        + " — run: python scripts/check_pages.py --remove-retired"
    )


def test_pages_directory_holds_nothing_but_the_expected_screens():
    found = {p.name for p in (ROOT / "pages").glob("*.py")}
    assert found == EXPECTED_PAGES, (
        f"unexpected: {sorted(found - EXPECTED_PAGES)}; "
        f"missing: {sorted(EXPECTED_PAGES - found)}"
    )


def test_no_two_screens_share_a_sidebar_position():
    """Duplicate numeric prefixes make sidebar order arbitrary."""
    numbers: dict[str, list[str]] = {}
    for page in (ROOT / "pages").glob("*.py"):
        match = PAGE_NAME.match(page.name)
        if match:
            numbers.setdefault(match.group(1), []).append(page.name)
    clashes = {num: sorted(names) for num, names in numbers.items() if len(names) > 1}
    assert not clashes, f"screens sharing a position: {clashes}"


def test_no_page_file_stranded_at_the_repo_root():
    """A flattened extraction leaves these beside Home.py, where they never load."""
    stray = [p.name for p in ROOT.glob("*.py") if PAGE_NAME.match(p.name)]
    assert not stray, f"page files outside pages/: {stray}"


def test_page_filenames_sort_into_sidebar_order():
    for name in EXPECTED_PAGES:
        assert PAGE_NAME.match(name), f"{name} will not order correctly in the sidebar"


def test_fallback_entry_point_points_at_real_files():
    """app_single.py must not drift from the files pages/ actually holds."""
    source = (ROOT / "app_single.py").read_text(encoding="utf-8")
    referenced = set(re.findall(r'"(pages/[^"]+\.py)"', source))
    assert referenced, "app_single.py references no screens"
    for rel in referenced:
        assert (ROOT / rel).exists(), f"app_single.py points at a missing screen: {rel}"
    assert {Path(r).name for r in referenced} == EXPECTED_PAGES


def test_home_page_links_only_to_screens_that_exist():
    """The landing cards are hand-written paths; a stale one is a dead link."""
    source = (ROOT / "Home.py").read_text(encoding="utf-8")
    referenced = set(re.findall(r'"(pages/[^"]+\.py)"', source))
    for rel in referenced:
        assert (ROOT / rel).exists(), f"Home.py links to a missing screen: {rel}"
    assert not {Path(r).name for r in referenced} & set(RETIRED_PAGES), (
        "Home.py still links to a retired screen"
    )


def test_the_checker_and_these_tests_agree_on_the_screen_list():
    """Two lists of the same thing drift. Assert they cannot."""
    check_pages = _load_check_pages()
    assert set(check_pages.EXPECTED) == EXPECTED_PAGES
    assert set(check_pages.RETIRED) == set(RETIRED_PAGES)


def test_remove_retired_deletes_only_retired_screens(tmp_path, monkeypatch):
    check_pages = _load_check_pages()
    pages = tmp_path / "pages"
    pages.mkdir()
    for name in list(EXPECTED_PAGES) + list(RETIRED_PAGES):
        (pages / name).write_text("# screen\n", encoding="utf-8")
    keep = pages / "notes.txt"
    keep.write_text("not a screen\n", encoding="utf-8")

    removed = check_pages.remove_retired(pages)

    assert sorted(removed) == sorted(RETIRED_PAGES)
    survivors = {p.name for p in pages.glob("*.py")}
    assert survivors == EXPECTED_PAGES
    assert keep.exists()


def test_remove_retired_is_safe_to_run_twice(tmp_path):
    """Second run finds nothing and says so, rather than raising.

    Deliberately operates on a temp directory. An earlier draft of this test
    pointed remove_retired() at the real pages/ folder and deleted files as a
    side effect of running the suite — a test that edits the repo it is testing
    is a trap, however convenient the assertion looks.
    """
    check_pages = _load_check_pages()
    pages = tmp_path / "pages"
    pages.mkdir()
    for name in RETIRED_PAGES:
        (pages / name).write_text("# screen\n", encoding="utf-8")

    assert sorted(check_pages.remove_retired(pages)) == sorted(RETIRED_PAGES)
    assert check_pages.remove_retired(pages) == []


# ---------------------------------------------------------------------------
# Collection safety
#
# `python -m pytest` aborted before a single test ran on Windows:
#
#   ERROR collecting pages/7_Mock_Test.py
#   AttributeError: st.session_state has no attribute "mock_flow"
#
# pytest collects `test_*.py` and `*_test.py` by default. Windows matches
# those case-insensitively and Linux does not, so `7_Mock_Test.py` — a
# Streamlit PAGE — was imported as a test module, ran outside `streamlit run`,
# found no session state and killed the run. A screen called `7_Mock_Exam.py`
# would never have shown it, which is exactly why a naming rule is the wrong
# guard and confining collection is the right one.
# ---------------------------------------------------------------------------

PYTEST_DEFAULT_PATTERNS = ("test_*.py", "*_test.py")


def _pages_matching_pytest_defaults() -> list[str]:
    """Page filenames pytest would collect on a case-insensitive filesystem."""
    import fnmatch

    return sorted(
        path.name
        for path in (ROOT / "pages").glob("*.py")
        if any(
            fnmatch.fnmatch(path.name.lower(), pattern)
            for pattern in PYTEST_DEFAULT_PATTERNS
        )
    )


def test_collection_is_confined_to_the_tests_directory():
    """Only required while a page name collides — but it always might."""
    colliding = _pages_matching_pytest_defaults()
    config = ROOT / "pytest.ini"
    assert config.exists(), (
        "pytest.ini is missing. Without it, pytest collects from the repo "
        f"root and would import these pages as test modules on Windows: "
        f"{colliding or 'none today, but any future *_Test.py page'}"
    )
    text = config.read_text(encoding="utf-8")
    assert re.search(r"^\s*testpaths\s*=\s*tests\s*$", text, re.MULTILINE), (
        "pytest.ini no longer confines collection to tests/. Pages named like "
        "test modules will be imported and abort the suite: "
        f"{colliding}"
    )


def test_the_collision_this_guard_exists_for_is_real():
    """Non-vacuity. If every page is renamed this can go, but say so out loud."""
    colliding = _pages_matching_pytest_defaults()
    if not colliding:
        import pytest

        pytest.skip("no page currently collides with pytest's default patterns")
    assert "7_Mock_Test.py" in colliding
