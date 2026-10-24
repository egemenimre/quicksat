# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the editor's Python side: the comments it finds, the data it gives the
page, and the page it writes.

The page's own code runs in a browser, so it is not tested here. These tests
read the power and scenario test folders and never change them. A test that
needs a changed file works on a copy.
"""

import base64
import json
import re
import shutil
from importlib.resources import files
from pathlib import Path

import pytest

from quicksat.editor.__main__ import main
from quicksat.editor.editor import (
    FORMAT,
    PAGE_FILE,
    SCRIPTS,
    SHARED_SCRIPTS,
    comment_blocks,
    editor_data,
    editor_page,
    write_editor,
)

TESTS = Path(__file__).parent.parent

PACKAGE = files("quicksat")


@pytest.fixture(scope="module")
def power_dir() -> Path:
    """A power folder: a scenario, a power system, two consumption files and a model."""
    return TESTS / "power" / "data"


@pytest.fixture(scope="module")
def scenario_dir() -> Path:
    """A scenario folder, with no power files."""
    return TESTS / "scenario" / "data"


# ---------------------------------------------------------------- comments


COMMENTED = """# about the file

orbit:
  # the source
  sso: {altitude: 510 km, ltan: "13:30"}  # a sun-synchronous orbit
attitudes:
  nadir: {point: [+z, nadir], constrain: [-y, orbit normal]}
  # a spare one:
  # roll: {point: [+z, nadir]}
slew:
  max_rate: 0.7 deg/s   # the drive's "#1" limit
activities:
  - [a, 10 min, nadir, {payload_mode: idle, platform_mode: idle}]
  # the last one
  - [b, 10 min, nadir, {payload_mode: idle, platform_mode: idle}]
# the end
"""


def test_each_comment_belongs_to_the_key_it_describes():
    found = [
        (block["line"], block["path"], block["inline"])
        for block in comment_blocks(COMMENTED)
    ]
    assert found == [
        (1, [], False),  # above the first key, with a blank line after it
        (4, ["orbit", "sso"], False),
        (5, ["orbit", "sso"], True),
        (8, ["attitudes"], False),  # it closes the attitudes, so it is theirs
        (11, ["slew", "max_rate"], True),
        (14, ["activities", 1], False),
        (16, [], False),  # no key below it
    ]


def test_a_block_with_a_blank_line_below_it_belongs_to_the_section():
    text = (
        "attitudes:\n"
        "  # every attitude here points +z\n"
        "\n"
        "  # nadir's own\n"
        "  nadir: {point: [+z, nadir]}\n"
    )
    found = [(block["line"], block["path"]) for block in comment_blocks(text)]
    assert found == [(2, ["attitudes"]), (4, ["attitudes", "nadir"])]


def test_a_block_keeps_its_lines_and_a_hash_in_quotes_is_not_a_comment():
    blocks = comment_blocks(COMMENTED)
    assert blocks[3]["text"] == "a spare one:\nroll: {point: [+z, nadir]}"
    assert blocks[4]["text"] == 'the drive\'s "#1" limit'
    assert comment_blocks('title: "a #1 title"\n') == []


# ---------------------------------------------------------------- the data


def test_a_power_folder_gives_every_file(power_dir):
    data = editor_data(power_dir)
    assert data["format"] == FORMAT
    assert data["folder"] == "data"
    files = data["files"]
    assert files["scenario"]["name"] == "scenario.yaml"
    assert files["scenario"]["data"]["duration"] == "1 orbit"
    assert files["power"]["data"]["panels"]
    for kind in ("payload_consumption", "platform_consumption"):
        assert files[kind]["header"][0] == "equipment_id"
        assert len(files[kind]["rows"]) > 0
    assert (
        base64.b64decode(data["model"]["glb_base64"])
        == (power_dir / "spacecraft.glb").read_bytes()
    )
    assert data["orbit_file"]["name"] == "sso_510km.tle"
    assert data["orbit_file"]["text"] == (power_dir / "sso_510km.tle").read_text()
    assert [(check["file"], check["ok"]) for check in data["checks"]] == [
        ("scenario.yaml", True),
        ("power_system.yaml", True),
        ("payload_consumption.csv", True),
        ("platform_consumption.csv", True),
    ]


def test_the_satellite_targets_files_come_once_each(scenario_dir, tmp_path):
    folder = tmp_path / "relays"
    shutil.copytree(scenario_dir, folder)
    relays = (folder / "relays.tle").read_text()
    with open(folder / "scenario.yaml", "a") as file:
        file.write(
            "sat_targets:\n"
            "  RELAY-01: {tle_file: relays.tle}\n"
            "  relay: {tle_file: relays.tle, object: 90002}\n"
            "  lost: {tle_file: nowhere.tle}\n"
        )
    data = editor_data(folder)
    assert data["target_files"] == [{"name": "relays.tle", "text": relays}]
    assert editor_data(scenario_dir)["target_files"] == []


def test_a_scenario_folder_has_no_power_files(scenario_dir):
    data = editor_data(scenario_dir)
    assert data["files"]["power"] is None
    assert data["files"]["payload_consumption"] is None
    assert data["files"]["platform_consumption"] is None
    assert data["model"] is None  # its scenario names no model
    assert [check["file"] for check in data["checks"]] == ["scenario.yaml"]


def test_the_label_is_the_folder_as_given_or_only_its_name(power_dir, monkeypatch):
    monkeypatch.chdir(TESTS)
    assert editor_data(Path("power") / "data")["label"] == "power/data"
    assert editor_data(power_dir.resolve())["label"] == "data"


def test_a_file_that_quicksat_refuses_is_reported(power_dir, tmp_path):
    folder = tmp_path / "broken"
    shutil.copytree(power_dir, folder)
    text = (folder / "scenario.yaml").read_text().replace("step: 10 s", "step: -10 s")
    (folder / "scenario.yaml").write_text(text)
    check = editor_data(folder)["checks"][0]
    assert not check["ok"]
    assert "step" in check["message"]


def test_a_folder_without_a_scenario_file_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError, match="no scenario file"):
        editor_data(tmp_path)


# ---------------------------------------------------------------- the page


def page_data(page: str) -> dict:
    """The folder's data, as the page holds it."""
    match = re.search(
        r'<script id="project" type="application/json">(.*?)</script>', page, re.S
    )
    assert match is not None
    return json.loads(match.group(1))


def test_the_page_holds_its_scripts_and_the_folder(power_dir, tmp_path):
    page = write_editor(power_dir, tmp_path / "out")
    assert page == tmp_path / "out" / PAGE_FILE
    text = page.read_text(encoding="utf-8")
    assert not re.search(r"@(project|three|yaml|css|editor)@", text)
    templates = PACKAGE / "editor" / "templates"
    for folder, names in (("shared", SHARED_SCRIPTS), ("scenario", SCRIPTS)):
        for name in names:
            assert (templates / folder / name).read_text(encoding="utf-8") in text, name
    assert page_data(text)["files"]["scenario"]["name"] == "scenario.yaml"
    # the place search asks Nominatim, so the page holds no list of places
    assert 'id="places"' not in text
    assert "nominatim.openstreetmap.org" in text


def test_text_that_would_end_a_script_tag_is_escaped(power_dir):
    data = editor_data(power_dir)
    data["files"]["scenario"]["data"]["comments"] = "a </script> in a comment"
    page = editor_page(data)
    assert (
        page_data(page)["files"]["scenario"]["data"]["comments"]
        == "a </script> in a comment"
    )


def test_the_command_writes_the_page_and_names_it(power_dir, tmp_path, capsys):
    main([str(power_dir), str(tmp_path / "out")])
    assert capsys.readouterr().out.strip() == str(tmp_path / "out" / PAGE_FILE)
    assert (tmp_path / "out" / PAGE_FILE).is_file()
