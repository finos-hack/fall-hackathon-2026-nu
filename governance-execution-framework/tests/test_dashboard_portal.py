"""Left-menu portal: search, filters, expandable rows, 20-per-page pagination and cross-links."""
import re

from governance_execution.dashboard import portal


def _rows(n):
    return [{"id": f"X{i:03d}", "cells": [], "details": [], "facets": {"status": "A" if i % 2 else "B"}, "search": f"x{i:03d} item", "detail_url": None, "open": False}
            for i in range(n)]


def test_pagination_is_20_per_page():
    pg = portal.build_listing(_rows(45), {}, "/x", [("status", "Status")], page=3)
    assert (pg["total"], pg["pages"], pg["page"], len(pg["rows"]), pg["start"], pg["end"]) == (45, 3, 3, 5, 41, 45)
    assert portal.build_listing(_rows(45), {}, "/x", [], page=1)["rows"][0]["id"] == "X000"
    assert len(portal.build_listing(_rows(45), {}, "/x", [], page=2)["rows"]) == 20
    assert portal.build_listing(_rows(45), {}, "/x", [], page=99)["page"] == 3   # out of range is clamped


def test_search_filter_and_links_keep_state():
    pg = portal.build_listing(_rows(100), {"q": "x0", "status": "A"}, "/x", [("status", "Status")])
    assert pg["total"] == 50 and all(r["facets"]["status"] == "A" for r in pg["rows"])
    assert "q=x0" in pg["next"] and "status=A" in pg["next"] and "page=2" in pg["next"]


def test_focus_opens_the_right_page_even_when_a_filter_hides_it():
    pg = portal.build_listing(_rows(45), {"focus": "X033", "status": "B"}, "/x", [("status", "Status")])
    assert pg["page"] == 2 and [r["id"] for r in pg["rows"] if r["open"]] == ["X033"]

