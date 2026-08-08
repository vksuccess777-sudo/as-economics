"""The source policy, as tests.

The rules being defended here are not stylistic. Each one corresponds to a
way this feature could quietly turn into copyright infringement or into a
link that sends a student somewhere wrong.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.reference import dataset as dataset_mod
from src.reference.dataset import DatasetError, available_datasets, load_dataset, normalise_number
from src.reference.links import LinkSet, LinksError, load_links
from src.reference.registry import (
    OPEN_DATA_LICENCES,
    Registry,
    RegistryError,
    load_registry,
)

SRC_REFERENCE = Path(__file__).resolve().parents[1] / "src" / "reference"
SHIPPED_MANIFEST = Path(__file__).resolve().parents[1] / "data" / "reference" / "manifest.json"


# ---- the structural guarantee ------------------------------------------

FORBIDDEN_IMPORTS = ("requests", "httpx", "urllib.request", "http.client", "aiohttp")


def test_reference_package_cannot_fetch_anything():
    """The link-only policy is enforced by absence, not by discipline.

    If an HTTP client ever appears in this package, 'we never read those
    sites' stops being a property of the code and becomes a promise.
    """
    offenders = []
    for path in SRC_REFERENCE.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in FORBIDDEN_IMPORTS:
            if f"import {name}" in text or f"from {name}" in text:
                offenders.append((path.name, name))
        if "urlopen(" in text:
            offenders.append((path.name, "urlopen"))
    assert not offenders, f"src/reference must not fetch: {offenders}"


# ---- registry -----------------------------------------------------------


def test_shipped_manifest_loads():
    registry = load_registry(SHIPPED_MANIFEST)
    assert registry.get("khan_academy").use == "link_only"
    assert registry.get("world_bank").is_data


def test_every_data_source_carries_an_attribution_notice():
    registry = load_registry(SHIPPED_MANIFEST)
    for source in registry.data_sources():
        assert source.notice, f"{source.id} has no attribution line"
        assert source.licence in OPEN_DATA_LICENCES


def test_imf_is_not_recorded_as_creative_commons():
    """The IMF permits reuse under its own terms, not a CC licence. Recording
    it as CC would put a false licence on a stimulus."""
    imf = load_registry(SHIPPED_MANIFEST).get("imf")
    assert "CC" not in imf.licence
    assert imf.licence == "IMF Terms of Use"


def _manifest(tmp_path, sources):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"version": 1, "sources": sources}), encoding="utf-8")
    return path


BASE_LINK_ONLY = {
    "id": "example",
    "name": "Example",
    "use": "link_only",
    "licence": "All rights reserved",
    "home": "https://example.org/",
    "search_url": "https://example.org/s?q={query}",
}


def test_data_source_with_unknown_licence_is_refused(tmp_path):
    raw = dict(BASE_LINK_ONLY, use="data", licence="All rights reserved", notice="x")
    with pytest.raises(RegistryError, match="not in the allow-list"):
        load_registry(_manifest(tmp_path, [raw]))


def test_unexpected_key_is_refused(tmp_path):
    """The key set is closed so an 'excerpt' field cannot appear here."""
    raw = dict(BASE_LINK_ONLY, excerpt="Two paragraphs of someone else's writing")
    with pytest.raises(RegistryError, match="unexpected keys"):
        load_registry(_manifest(tmp_path, [raw]))


def test_search_url_must_have_a_placeholder(tmp_path):
    raw = dict(BASE_LINK_ONLY, search_url="https://example.org/search")
    with pytest.raises(RegistryError, match="placeholder"):
        load_registry(_manifest(tmp_path, [raw]))


def test_link_only_source_cannot_be_read(tmp_path):
    registry = load_registry(_manifest(tmp_path, [BASE_LINK_ONLY]))
    with pytest.raises(RegistryError, match="may be linked to, never read"):
        registry.require_data_source("example")


# ---- links --------------------------------------------------------------


@pytest.fixture
def registry():
    return load_registry(SHIPPED_MANIFEST)


TOPICS = {"1.1", "3.2", "4.1"}


def _links_file(tmp_path, links):
    path = tmp_path / "links.json"
    path.write_text(json.dumps({"version": 1, "links": links}), encoding="utf-8")
    return path


GOOD_LINK = {
    "topic": "3.2",
    "source": "khan_academy",
    "title": "Price controls",
    "url": "https://www.khanacademy.org/economics-finance-domain/x/price-controls",
}


def test_curated_link_loads(tmp_path, registry):
    linkset = load_links(registry, TOPICS, _links_file(tmp_path, [GOOD_LINK]))
    assert linkset.curated_for("3.2")[0].title == "Price controls"


def test_link_to_a_topic_outside_the_spine_is_refused(tmp_path, registry):
    bad = dict(GOOD_LINK, topic="9.9")
    with pytest.raises(LinksError, match="not in the parsed syllabus spine"):
        load_links(registry, TOPICS, _links_file(tmp_path, [bad]))


def test_link_whose_host_contradicts_its_source_is_refused(tmp_path, registry):
    """Otherwise the attribution printed under the link would be a lie."""
    bad = dict(GOOD_LINK, url="https://not-khan.example.com/page")
    with pytest.raises(LinksError, match="attribution under it would be wrong"):
        load_links(registry, TOPICS, _links_file(tmp_path, [bad]))


def test_link_with_extra_keys_is_refused(tmp_path, registry):
    bad = dict(GOOD_LINK, summary="A helpful three paragraph summary of the page")
    with pytest.raises(LinksError, match="unexpected keys"):
        load_links(registry, TOPICS, _links_file(tmp_path, [bad]))


def test_long_title_is_refused(tmp_path, registry):
    bad = dict(GOOD_LINK, title="x" * 200)
    with pytest.raises(LinksError, match="summary of it"):
        load_links(registry, TOPICS, _links_file(tmp_path, [bad]))


def test_search_links_exist_with_no_curated_links(registry):
    """The shipped state: links.json is empty and every topic still offers
    somewhere to go."""
    linkset = LinkSet(registry=registry, links=())
    rows = linkset.go_deeper("3.2", "Price controls")
    assert rows and all(r.is_search for r in rows)
    assert all(r.url.startswith("https://") for r in rows)
    assert "Price+controls" in rows[0].url


def test_curated_link_replaces_the_search_link_for_that_source(tmp_path, registry):
    linkset = load_links(registry, TOPICS, _links_file(tmp_path, [GOOD_LINK]))
    rows = linkset.go_deeper("3.2", "Price controls")
    khan = [r for r in rows if r.source_name == "Khan Academy"]
    assert len(khan) == 1 and khan[0].kind == "curated"


def test_khan_notice_is_surfaced(registry):
    rows = LinkSet(registry=registry, links=()).go_deeper("3.2", "Price controls")
    notices = LinkSet.notices(rows)
    assert any("khanacademy.org" in n for n in notices), (
        "Khan's licence requires that line wherever its material is surfaced"
    )


def test_shipped_links_file_is_valid(registry):
    """It is empty on purpose, but it must still parse."""
    from src.reference.links import DEFAULT_LINKS

    load_links(registry, TOPICS, DEFAULT_LINKS)


# ---- datasets -----------------------------------------------------------

CSV = "Year,GDP growth (%),Inflation (%)\n2019,2.4,1.8\n2020,-9.3,0.9\n2021,7.6,2.6\n2022,4.1,9.1\n"


def _dataset_dir(tmp_path, manifest, csv=CSV):
    root = tmp_path / "datasets" / manifest["slug"]
    root.mkdir(parents=True)
    (root / "data.csv").write_text(csv, encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path / "datasets"


MANIFEST = {
    "slug": "demo",
    "title": "Demo indicators",
    "source": "world_bank",
    "url": "https://data.worldbank.org/indicator/DEMO",
    "licence": "CC BY 4.0",
    "accessed_on": "2026-08-06",
    "region": "Testland",
}


def test_dataset_loads_and_attributes(tmp_path, registry):
    root = _dataset_dir(tmp_path, MANIFEST)
    ds = load_dataset("demo", datasets_dir=root, registry=registry)
    assert ds.headers[0] == "Year"
    assert "CC BY 4.0" in ds.attribution()
    assert "2026-08-06" in ds.attribution()


def test_dataset_without_manifest_is_unusable(tmp_path, registry):
    root = tmp_path / "datasets" / "orphan"
    root.mkdir(parents=True)
    (root / "data.csv").write_text(CSV, encoding="utf-8")
    with pytest.raises(DatasetError, match="no manifest"):
        load_dataset("orphan", datasets_dir=tmp_path / "datasets", registry=registry)


def test_dataset_attributed_to_a_link_only_source_is_refused(tmp_path, registry):
    """This is the load-bearing one: it is what stops ZNotes becoming a corpus."""
    root = _dataset_dir(tmp_path, dict(MANIFEST, source="znotes"))
    with pytest.raises(RegistryError, match="never read"):
        load_dataset("demo", datasets_dir=root, registry=registry)


def test_dataset_url_must_match_its_claimed_source(tmp_path, registry):
    root = _dataset_dir(tmp_path, dict(MANIFEST, url="https://somewhere-else.example.com/x"))
    with pytest.raises(DatasetError, match="Attribute it to where it actually came from"):
        load_dataset("demo", datasets_dir=root, registry=registry)


def test_ragged_csv_is_refused(tmp_path, registry):
    root = _dataset_dir(tmp_path, MANIFEST, csv="Year,A\n2020,1\n2021,2,3\n")
    with pytest.raises(DatasetError, match="ragged"):
        load_dataset("demo", datasets_dir=root, registry=registry)


def test_available_datasets_skips_broken_ones(tmp_path, registry):
    root = _dataset_dir(tmp_path, MANIFEST)
    broken = root / "broken"
    broken.mkdir()
    (broken / "data.csv").write_text(CSV, encoding="utf-8")
    assert available_datasets(root, registry) == ["demo"]


def test_table_trims_to_the_most_recent_rows(tmp_path, registry):
    root = _dataset_dir(tmp_path, MANIFEST)
    ds = load_dataset("demo", datasets_dir=root, registry=registry)
    table = ds.table(columns=["Year", "Inflation (%)"], max_rows=2)
    assert table.headers == ("Year", "Inflation (%)")
    assert table.rows[-1][0] == "2022"
    assert len(table.rows) == 2


def test_normalise_number_ignores_formatting():
    assert normalise_number("1,234.50") == normalise_number("1234.5")
    assert normalise_number("9.1%") == "9.1"
    assert normalise_number("n/a") is None
