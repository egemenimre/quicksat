# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests that the help files hold what the editor's pages ask of them.

Each step's information box and each `#` help line of a saved file come from
`quicksat/editor/help/`. A key that a page asks for, and a help file lacks, would
show an empty box or write no help, with no error.
"""

import re
from importlib.resources import files

import pytest

from quicksat.editor.shared import help_text

TEMPLATES = files("quicksat") / "editor" / "templates"

PAGES = {"scenario": ("scenario", "power", "thermal"), "sizing": ("sizing",)}


def section_ids(page: str) -> list[str]:
    """The keys of a page's `SECTIONS`, each a step or a card with a box."""
    text = (TEMPLATES / page / "sections.js").read_text(encoding="utf-8")
    start = text.index("const SECTIONS = {")
    block = text[start : text.index("\n};\n", start)]
    return re.findall(r"^  (\w+): \{$", block, re.M)


def written_keys(page: str) -> set[str]:
    """The keys that a page's `write.js` names when it writes its help lines."""
    text = (TEMPLATES / page / "write.js").read_text(encoding="utf-8")
    return set(re.findall(r'helpLines\(lines, \d+, "(\w+)"\)', text))


@pytest.mark.parametrize("page", PAGES)
def test_each_step_has_its_box(page):
    help_ = help_text(PAGES[page])
    ids = section_ids(page)
    assert len(ids) > 10
    for name in ids:
        assert help_.get(name, {}).get("info"), name
        assert help_[name].get("title"), name


@pytest.mark.parametrize("page", PAGES)
def test_each_help_line_the_page_writes_is_there(page):
    help_ = help_text(PAGES[page])
    for key in written_keys(page):
        assert help_.get(key, {}).get("file"), key


@pytest.mark.parametrize("domain", ["scenario", "power", "thermal", "sizing"])
def test_each_entry_holds_only_the_known_parts(domain):
    for key, entry in help_text((domain,)).items():
        assert entry, key
        assert set(entry) <= {"title", "info", "file"}, key
        assert ("title" in entry) == ("info" in entry), key
        assert all(isinstance(text, str) and text.strip() for text in entry.values())


def test_two_domains_may_not_share_a_key():
    with pytest.raises(ValueError, match="repeats"):
        help_text(("scenario", "scenario"))
