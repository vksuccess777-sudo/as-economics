"""External sources: the licence registry, the link-out layer and datasets.

THIS PACKAGE NEVER FETCHES ANYTHING. There is no HTTP client here, and
`tests/test_reference.py` reads these files and fails if one appears. The
only thing that reaches the network in this project is the student's browser,
when they click a link, and `scripts/check_links.py --verify`, which lives
outside this package precisely so the rule stays true here.
"""
