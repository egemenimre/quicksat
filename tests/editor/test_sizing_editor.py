# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the sizing editor's Python side: the data it gives the page, the
page it writes, and the command that picks the page for a folder.

These tests read the sizing test folder and never change it. A test that needs
a changed or a fuller folder works on a copy.
"""

import json
import re
import shutil
from importlib.resources import files
from pathlib import Path

import pytest

from quicksat.editor.__main__ import main
from quicksat.editor.editor import PAGE_FILE, SHARED_SCRIPTS
from quicksat.editor.sizing import (
    FORMAT,
    SCRIPTS,
    sizing_data,
    sizing_page,
    write_sizing_editor,
)

TESTS = Path(__file__).parent.parent
TEMPLATES = files("quicksat") / "editor" / "templates"

EQUIPMENT = """equipment_id,equipment_name,location,responsibility,subsystem,unit_mass,eqpt_margin,number_of_units,mass_class,comments
obc,On-board computer,Platform,Platform,OBDH,3.2 kg,5,2,equipment,
"""

MASS = """locations:
  Platform: {system_margin: 20, harness_fraction: 4, harness_margin: 25}
"""


@pytest.fixture(scope="module")
def sizing_dir() -> Path:
    """The sizing test folder: the mission, data, delta-V and agility files, and no mass files."""
    return TESTS / "sizing" / "data"


@pytest.fixture
def full_dir(sizing_dir, tmp_path) -> Path:
    """A copy of the sizing test folder, with the mass budget's two files added."""
    folder = tmp_path / "full"
    shutil.copytree(sizing_dir, folder)
    (folder / "equipment.csv").write_text(EQUIPMENT)
    (folder / "mass_budget_config.yaml").write_text(MASS)
    return folder


def page_data(page: str) -> dict:
    """The folder's data, as the page holds it."""
    match = re.search(
        r'<script id="project" type="application/json">(.*?)</script>', page, re.S
    )
    assert match is not None
    return json.loads(match.group(1))


def test_the_data_holds_each_file_or_none(sizing_dir):
    data = sizing_data(sizing_dir)
    assert data["format"] == FORMAT
    present = {kind for kind, file in data["files"].items() if file}
    assert present == {"mission", "data", "deltav", "manoeuvres", "agility"}
    assert data["files"]["mission"]["data"]["altitude"] == "500 km"
    assert data["files"]["manoeuvres"]["header"][0] == "manoeuvre_id"
    assert [(check["file"], check["ok"]) for check in data["checks"]] == [
        ("mission.yaml", True),
        ("pl_dataflow_model.yaml", True),
        ("manoeuvres.csv with delta_v_config.yaml", True),
        ("agility_config.yaml", True),
    ]


def test_the_mass_files_are_checked_together(full_dir):
    checks = {check["file"]: check["ok"] for check in sizing_data(full_dir)["checks"]}
    assert checks["equipment.csv with mass_budget_config.yaml"] is True


def test_a_file_that_quicksat_refuses_is_reported(full_dir):
    mission = full_dir / "mission.yaml"
    mission.write_text(mission.read_text().replace("duration:", "durration:"))
    check = sizing_data(full_dir)["checks"][0]
    assert check["file"] == "mission.yaml" and not check["ok"]
    assert "durration" in check["message"]


def test_a_folder_without_a_sizing_file_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError, match="no sizing file"):
        sizing_data(tmp_path)


def test_the_page_holds_its_scripts_and_the_folder(sizing_dir, tmp_path):
    page = write_sizing_editor(sizing_dir, tmp_path / "out")
    assert page == tmp_path / "out" / PAGE_FILE
    text = page.read_text(encoding="utf-8")
    assert not re.search(r"@(project|yaml|css|editor)@", text)
    for folder, names in (("shared", SHARED_SCRIPTS), ("sizing", SCRIPTS)):
        for name in names:
            assert (TEMPLATES / folder / name).read_text(encoding="utf-8") in text, name
    assert page_data(text)["files"]["mission"]["name"] == "mission.yaml"
    # the scenario page's 3D library and places are not needed here
    assert "GLTFLoader" not in text and 'id="places"' not in text
    assert sizing_page(sizing_data(sizing_dir)) == text


def test_the_command_picks_the_page_for_the_folder(full_dir, tmp_path, capsys):
    main([str(full_dir), str(tmp_path / "sizing")])
    page = (tmp_path / "sizing" / PAGE_FILE).read_text(encoding="utf-8")
    assert "<title>quicksat Sizing Editor</title>" in page
    main([str(TESTS / "scenario" / "data"), str(tmp_path / "scenario")])
    page = (tmp_path / "scenario" / PAGE_FILE).read_text(encoding="utf-8")
    assert "<title>quicksat Scenario Editor</title>" in page
    assert capsys.readouterr().out.split() == [
        str(tmp_path / "sizing" / PAGE_FILE),
        str(tmp_path / "scenario" / PAGE_FILE),
    ]


def test_the_command_refuses_a_folder_of_neither_kind(tmp_path):
    with pytest.raises(SystemExit):
        main([str(tmp_path), str(tmp_path / "out")])
