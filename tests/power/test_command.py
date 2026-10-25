# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""Tests for `python -m quicksat.power`."""

import shutil

import pytest

from quicksat.power.__main__ import main
from quicksat.power.viewer import DATA_FILE, PAGE_FILE
from quicksat.scenario.viewer import DATA_FILE as SCENARIO_DATA_FILE

INPUTS = (
    "scenario.yaml",
    "power_system.yaml",
    "payload_consumption.csv",
    "platform_consumption.csv",
    "spacecraft.glb",
    "sso_510km.tle",
)
"""The files of the power test folder that the budget reads."""


def test_the_command_prints_the_results_and_writes_the_viewer(
    data_dir, budget, tmp_path, capsys
):
    folder = tmp_path / "case"
    folder.mkdir()
    for name in INPUTS:
        shutil.copy(data_dir / name, folder)
    main([str(folder), str(tmp_path / "out")])
    lines = capsys.readouterr().out.splitlines()
    # the folder's typed-in panel gives a note
    assert budget.generation.notes
    assert lines == [
        *budget.generation.run.report.splitlines(),
        *budget.generation.notes,
        *budget.consumption.notes,
        *(f"{check.status:<4} {check.name}: {check.detail}" for check in budget.checks),
        str(tmp_path / "out" / PAGE_FILE),
    ]
    assert {path.name for path in (tmp_path / "out").iterdir()} == {
        PAGE_FILE,
        DATA_FILE,
        SCENARIO_DATA_FILE,
    }


def test_a_file_it_cannot_read_stops_it_with_the_error(data_dir, tmp_path, capsys):
    folder = tmp_path / "case"
    folder.mkdir()
    for name in INPUTS:
        shutil.copy(data_dir / name, folder)
    power_file = folder / "power_system.yaml"
    text = power_file.read_text()
    power_file.write_text(
        text.replace("cell_efficiency: 30 %", "cell_efficiency: 130 %")
    )
    with pytest.raises(SystemExit) as stop:
        main([str(folder), str(tmp_path / "out")])
    assert stop.value.code == 1
    assert capsys.readouterr().err.startswith(
        "error: 1 validation error for PowerSystem\ncell_efficiency"
    )
    assert not (tmp_path / "out").exists()
