# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests that the page finds the same keys and comments as editor.py.

A page that opens files in the browser finds their `#` comments with its own
code, in `open.js`. It must give the same result as `comment_blocks`, which
reads PyYAML's nodes, or a comment would land in a different block depending on
how the folder was opened. These tests run `open.js` in Node.js, so they are
skipped where Node.js is not installed.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from quicksat.editor.editor import _key_lines, comment_blocks

NODE = shutil.which("node")

ROOT = Path(__file__).parent.parent.parent
OPEN_JS = ROOT / "quicksat" / "editor" / "templates" / "shared" / "open.js"

RUN = """
const fs = require("fs");
const vm = require("vm");
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);
const texts = JSON.parse(fs.readFileSync(0, "utf8"));
const out = texts.map((text) => {
  context.text = text;
  return vm.runInContext("[keyLines(text), commentBlocks(text)]", context);
});
process.stdout.write(JSON.stringify(out));
"""

AWKWARD = {
    "block scalars": (
        "comments: |-\n"
        "  # a line of the notes, not a comment\n"
        "  key: not a key\n"
        "\n"
        "  still the notes\n"
        "# above the orbit\n"
        "orbit:\n"
        "  comments: >-\n"
        "    folded\n"
        "    text\n"
        "  sso: {altitude: 510 km, ltan: '13:30'}\n"
    ),
    "lists": (
        "activities:\n"
        "# the first\n"
        "- [a, 10 min, nadir, idle]\n"
        "- title: b\n"
        "  # its trigger\n"
        "  end: 10 min\n"
        "- - nested\n"
        "  - list\n"
        "-\n"
        "  key: later\n"
        "next: 1\n"
    ),
    "flow over lines": (
        "attitudes:\n"
        "  nadir: {point: [+z, nadir],\n"
        "    # the second axis\n"
        '    constrain: [-y, "orbit normal"]}\n'
        "  # the sun\n"
        "  sun: {point: [-z, sun]}\n"
    ),
    "quoted keys and anchors": (
        "panels:\n"
        '  "Wing +y": &wing {part: "Wing +y cells", fill_ratio: 90 %}\n'
        "  'it''s': {part: x}\n"
        "  plain key: x  # the end\n"
        'text: "over\n'
        '  # two lines"\n'
        "after: 2\n"
    ),
    "only comments": "# nothing but a comment\n\n# and another\n",
    "empty": "",
}


def yaml_files() -> dict[str, str]:
    """quicksat's own YAML files: the samples, the docs' and the tests' data."""
    texts = {}
    for folder in ("sample", "docs", "tests"):
        for path in sorted((ROOT / folder).rglob("*.yaml")):
            texts[str(path.relative_to(ROOT))] = path.read_text(encoding="utf-8")
    return texts


def run_page(texts: list[str]) -> list:
    """The page's keys and comments for each text, from `open.js` in Node.js."""
    assert NODE is not None
    result = subprocess.run(
        [NODE, "-e", RUN, str(OPEN_JS)],
        input=json.dumps(texts),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.skipif(NODE is None, reason="needs Node.js")
@pytest.mark.parametrize("texts", [yaml_files(), AWKWARD], ids=["files", "awkward"])
def test_the_page_finds_the_same_keys_and_comments(texts):
    names = list(texts)
    for name, (keys, blocks) in zip(names, run_page(list(texts.values())), strict=True):
        text = texts[name]
        assert keys == [list(key) for key in _key_lines(text)], name
        assert blocks == comment_blocks(text), name
