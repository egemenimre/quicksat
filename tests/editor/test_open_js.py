# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The cases for the Node test of the page's comment finder, and Python's answers.

A page that opens files in the browser finds their `#` comments with its own
code, in `open.js`. It must give the same result as `comment_blocks`, which
reads PyYAML's nodes, or a comment would land in a different block depending on
how the folder was opened.

Node cannot call Python, so the answers are kept in `js/open_cases.json`: some
awkward layouts and a copy of quicksat's own YAML files, each with its keys and
comment blocks from Python. `js/open.test.js` checks `open.js` against them, in
the CI's Node job. The test here checks that the answers are still Python's.
After a change to `editor.py`'s readers, or to add the newest YAML files, write
the cases again with:

    python -m tests.editor.test_open_js
"""

import json
from pathlib import Path

from quicksat.editor.editor import _key_lines, comment_blocks

ROOT = Path(__file__).parent.parent.parent
CASES = Path(__file__).parent / "js" / "open_cases.json"


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
        "- [a, 10 min, nadir, {payload_mode: idle, platform_mode: idle}]\n"
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
    """
    quicksat's own YAML files: the samples, the docs' and the tests' data.

    Many files are copies of a sample file, so a text is taken only the first
    time it comes. A second copy would be a second case with the same answers.
    """
    texts = {}
    for folder in ("sample", "docs", "tests"):
        for path in sorted((ROOT / folder).rglob("*.yaml")):
            text = path.read_text(encoding="utf-8")
            if text not in texts.values():
                texts[str(path.relative_to(ROOT))] = text
    return texts


def answers(text: str) -> dict:
    """Python's keys and comment blocks for a text, as the cases hold them."""
    return {
        "keys": [list(key) for key in _key_lines(text)],
        "blocks": comment_blocks(text),
    }


def write_cases() -> None:
    """Write the cases: the awkward layouts, then quicksat's own YAML files."""
    texts = {f"awkward: {name}": text for name, text in AWKWARD.items()} | yaml_files()
    cases = [
        {"name": name, "text": text, **answers(text)} for name, text in texts.items()
    ]
    # one case a line, so that a change shows as the cases it touches
    lines = ",\n".join(json.dumps(case, ensure_ascii=False) for case in cases)
    CASES.write_text(f"[\n{lines}\n]\n", encoding="utf-8")


def read_cases() -> list[dict]:
    """The cases, as the Node test reads them."""
    return json.loads(CASES.read_text(encoding="utf-8"))


def test_the_cases_hold_python_s_answers():
    for case in read_cases():
        assert {"keys": case["keys"], "blocks": case["blocks"]} == answers(
            case["text"]
        ), (
            f"{case['name']}: write the cases again with python -m tests.editor.test_open_js"
        )


def test_the_cases_hold_each_awkward_layout():
    names = {case["name"] for case in read_cases()}
    assert {f"awkward: {name}" for name in AWKWARD} <= names


if __name__ == "__main__":
    write_cases()
