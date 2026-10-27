# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for `python -m quicksat.thermal`, which runs the power budget too, and writes the
viewer with the heat account.
"""

import json
import shutil

import pytest

from quicksat.power.folder import summary as power_summary
from quicksat.power.viewer import DATA_FILE, PAGE_FILE
from quicksat.scenario.viewer import DATA_FILE as SCENARIO_DATA_FILE
from quicksat.thermal import THERMAL_FILE
from quicksat.thermal.__main__ import main
from quicksat.thermal.folder import NO_THERMAL_FILE, run_folder, summary
from quicksat.thermal.viewer import thermal_data


def read_power_js(folder) -> dict:
    """The data of the viewer's `power.js` in a folder."""
    text = (folder / DATA_FILE).read_text()
    return json.loads(text[text.index(" = {") + 3 :].rstrip().rstrip(";"))


def test_the_command_prints_the_budget_and_the_heat_account(
    data_dir, budget, thermal_run, tmp_path, capsys
):
    main([str(data_dir), str(tmp_path)])
    text = capsys.readouterr().out
    assert (
        summary(budget, thermal_run) + "\n" + str(tmp_path / PAGE_FILE) + "\n" == text
    )
    # the power command's text comes first
    assert text.startswith(power_summary(budget) + "\n\n")
    lines = text.splitlines()
    start = lines.index("Payload heat account, by activity:")
    assert lines[start + 1].split()[:2] == ["activity", "occurrences"]
    assert "By payload mode:" in lines
    assert "balancing heater [W]" in text
    # every ΔT of the test folder balances, so the column of reasons is left out
    assert "ΔT note" not in text
    assert lines[-2] == thermal_run.notes[-1]
    assert {path.name for path in tmp_path.iterdir()} == {
        PAGE_FILE,
        DATA_FILE,
        SCENARIO_DATA_FILE,
    }
    # the viewer's Thermal tab shows the account as the editor's tab does
    expected = json.loads(json.dumps(thermal_data(thermal_run), allow_nan=False))
    assert read_power_js(tmp_path)["thermal"] == expected


def test_the_viewer_s_account_holds_the_thermal_file(thermal, thermal_run):
    data = thermal_data(thermal_run)
    assert data["file"] == THERMAL_FILE
    assert data["text"] == thermal.source_text
    assert [row["payload mode"] for row in data["modes"]] == ["idle", "imaging"]
    assert len(data["t_min"]) == len(data["energy_wh"]) == len(thermal_run.run.times)
    assert data["bands"][-1]["end_min"] == pytest.approx(data["t_min"][-1])
    json.dumps(data, allow_nan=False)


def test_the_account_takes_the_budget_s_run(data_dir):
    budget, account = run_folder(data_dir)
    assert account is not None
    assert account.run is budget.generation.run


def test_without_the_thermal_file_it_gives_the_power_budget_alone(
    data_dir, budget, tmp_path, capsys
):
    folder = tmp_path / "case"
    shutil.copytree(data_dir, folder)
    (folder / THERMAL_FILE).unlink()
    main([str(folder), str(tmp_path / "out")])
    note = NO_THERMAL_FILE.format(name=THERMAL_FILE)
    assert note == "No payload_thermal.yaml in the folder, so the power budget alone."
    page = tmp_path / "out" / PAGE_FILE
    assert capsys.readouterr().out == f"{power_summary(budget)}\n\n{note}\n{page}\n"
    # so the viewer has no Thermal tab
    assert read_power_js(tmp_path / "out")["thermal"] is None


def test_a_thermal_file_it_cannot_read_stops_it_before_the_run(
    data_dir, tmp_path, capsys
):
    folder = tmp_path / "case"
    shutil.copytree(data_dir, folder)
    path = folder / THERMAL_FILE
    path.write_text(path.read_text().replace("emissivity: 0.85", "emissivity: 1.85"))
    with pytest.raises(SystemExit) as stop:
        main([str(folder), str(tmp_path / "out")])
    assert stop.value.code == 1
    assert capsys.readouterr().err.startswith("error: 1 validation error for")
    assert not (tmp_path / "out").exists()
