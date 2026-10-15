# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""Tests for `python -m quicksat.scenario`."""

import pytest

from quicksat.scenario.__main__ import main
from quicksat.scenario.viewer import DATA_FILE, PAGE_FILE


def test_the_command_prints_the_report_and_writes_the_viewer(
    data_dir, run, tmp_path, capsys
):
    main([str(data_dir), str(tmp_path)])
    lines = capsys.readouterr().out.splitlines()
    assert lines == [*run.report.splitlines(), str(tmp_path / PAGE_FILE)]
    assert {path.name for path in tmp_path.iterdir()} == {PAGE_FILE, DATA_FILE}


def test_a_missing_file_stops_it_with_the_error(tmp_path, capsys):
    with pytest.raises(SystemExit) as stop:
        main([str(tmp_path / "nowhere"), str(tmp_path / "out")])
    assert stop.value.code == 1
    error = capsys.readouterr().err
    assert error.startswith("error: ") and "scenario.yaml" in error
    assert not (tmp_path / "out").exists()
