# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The cases for the Node test of the page's element set reader, and Python's answers.

The Scenario Editor lists the satellites of a satellite target's file with its
own code, in `elements.js`: their names, catalogue numbers and epochs. It must
find what `read_tle_sets` and `read_omm_sets` find, or the page would offer a
satellite that the run cannot pick.

Node cannot call Python, so the answers are kept in `js/element_cases.json`:
quicksat's own TLE and OMM files, and groups written here from them, each with
Python's element sets. `js/elements.test.js` checks `elements.js` against them,
in the CI's Node job. The test here checks that the answers are still Python's.
After a change to the readers, write the cases again with:

    python -m tests.editor.test_elements_js
"""

import json
import re
import tempfile
from pathlib import Path

from quicksat.orbit.omm import read_omm_sets
from quicksat.orbit.tle import read_tle_sets

ROOT = Path(__file__).parent.parent.parent
CASES = Path(__file__).parent / "js" / "element_cases.json"
ORBIT_DATA = ROOT / "tests" / "orbit" / "data"

FILES = {
    "sso_510km.tle": ORBIT_DATA / "sso_510km.tle",
    "relays.tle": ROOT / "docs" / "scenario" / "data" / "relays.tle",
    "omm_celestrak.json": ORBIT_DATA / "omm_celestrak.json",
    "omm_celestrak.kvn": ORBIT_DATA / "omm_celestrak.kvn",
    "omm_celestrak.xml": ORBIT_DATA / "omm_celestrak.xml",
    "omm_space_track.kvn": ORBIT_DATA / "omm_space_track.kvn",
}
"""quicksat's own files, by the name the cases give them."""


def written() -> dict[str, str]:
    """Groups written from quicksat's files: Space-Track's form, JSON, CSV, a day of the year."""
    relays = FILES["relays.tle"].read_text().splitlines()
    space_track = [
        f"0 {line}   " if not line.startswith(("1 ", "2 ")) else line for line in relays
    ]
    record = json.loads(FILES["omm_celestrak.json"].read_text())[0]
    group = [
        record | {"OBJECT_NAME": f"RELAY {n}", "NORAD_CAT_ID": 90000 + n}
        for n in (1, 2, 3)
    ]
    csv = [",".join(group[0])] + [
        ",".join(str(value) for value in item.values()) for item in group
    ]
    kvn = FILES["omm_celestrak.kvn"].read_text()
    ordinal = re.sub(r"^(EPOCH\s*=\s*)2020-12-29T", r"\g<1>2020-364T", kvn, flags=re.M)
    assert ordinal != kvn
    return {
        "space_track.tle": "\n".join(space_track) + "\n",
        "group.json": json.dumps(group),
        "group.csv": "\n".join(csv) + "\n",
        "ordinal.kvn": ordinal,
    }


def answers(name: str, text: str) -> list[dict]:
    """Python's element sets for a file's text: each one's name, number and epoch."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / name
        path.write_text(text, encoding="utf-8")
        reader = read_tle_sets if name.endswith(".tle") else read_omm_sets
        return [
            {
                "name": tle.name,
                "number": int(tle.satrec.satnum),
                "epoch": tle.epoch.utc.isot,
            }
            for tle in reader(path)
        ]


def texts() -> dict[str, str]:
    """Every case's text, by its name."""
    own = {name: path.read_text(encoding="utf-8") for name, path in FILES.items()}
    return own | written()


def write_cases() -> None:
    """Write the cases, one a line, with Python's answers."""
    cases = [
        {"name": name, "text": text, "sets": answers(name, text)}
        for name, text in texts().items()
    ]
    lines = ",\n".join(json.dumps(case, ensure_ascii=False) for case in cases)
    CASES.write_text(f"[\n{lines}\n]\n", encoding="utf-8")


def read_cases() -> list[dict]:
    """The cases, as the Node test reads them."""
    return json.loads(CASES.read_text(encoding="utf-8"))


def test_the_cases_hold_python_s_answers():
    cases = read_cases()
    assert [case["name"] for case in cases] == list(texts())
    for case in cases:
        assert case["text"] == texts()[case["name"]], case["name"]
        assert case["sets"] == answers(case["name"], case["text"]), (
            f"{case['name']}: write the cases again with "
            "python -m tests.editor.test_elements_js"
        )


if __name__ == "__main__":
    write_cases()
