# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the power consumption: the CSV file, its checks, and the loads over a
run, with the slews as a mode of their own.
"""

import numpy as np
import pandas as pd
import pytest

from quicksat import u
from quicksat.power.consumption import PowerConsumption, run_consumption
from quicksat.power.orbits import interval_pieces, whole_orbits
from quicksat.scenario.config import SLEW, Scenario
from quicksat.scenario.run import run_scenario
from quicksat.utils.intervals import labels_at

HEADER = "equipment_id,equipment_name,subsystem,units_on,eqpt_margin,idle,imaging"
"""The columns of the small files written here."""


def write(tmp_path, *rows: str, header: str = HEADER):
    """A consumption file with the given rows."""
    path = tmp_path / "power_consumption.csv"
    path.write_text("\n".join([header, *rows]) + "\n")
    return path


# ------------------------------------------------------------------ the file


def test_the_fixture_reads(consumption):
    assert consumption.modes == ["idle", "imaging", "downlink", "slew"]
    assert len(consumption.loads) == 16
    wheels = next(
        load for load in consumption.loads if load.equipment_id == "reaction_wheel"
    )
    assert wheels.units_on == 4
    assert wheels.watts("downlink", margin=False) == pytest.approx(60)
    assert wheels.watts("downlink") == pytest.approx(63)
    totals = consumption.mode_totals()
    assert list(totals.loc["without margins"]) == pytest.approx([188, 290, 293, 188])
    assert totals.loc["with equipment margins", "idle [W]"] == pytest.approx(207.55)


def test_the_mode_table_gives_each_row_its_units_together(consumption):
    table = consumption.mode_table().set_index("equipment_id")
    assert table.loc["star_tracker", "idle [W]"] == 12
    with_margins = consumption.mode_table(margin=True).set_index("equipment_id")
    assert with_margins.loc["focal_plane", "imaging [W]"] == pytest.approx(54)
    assert list(table.columns[:4]) == [
        "equipment_name",
        "subsystem",
        "units_on",
        "eqpt_margin [%]",
    ]


@pytest.mark.parametrize(
    ("rows", "header", "message"),
    [
        (
            ["a,A,OBDH,1,5,1 W,2 W"],
            "equipment_id,equipment_name,units_on,eqpt_margin,idle",
            "missing columns \\['subsystem'\\]",
        ),
        (
            ["a,A,OBDH,1,5"],
            "equipment_id,equipment_name,subsystem,units_on,eqpt_margin",
            "no mode columns",
        ),
        ([], HEADER, "no equipment rows"),
        (
            ["a,A,OBDH,1,5,1 W,"],
            HEADER,
            "row 2: no power for the modes \\['imaging'\\]",
        ),
        (["a,A,OBDH,1,5,1 kg,2 W"], HEADER, "(?s)row 2:.*power dimensions"),
        (["a,A,OBDH,-1,5,1 W,2 W"], HEADER, "(?s)row 2:.*units_on"),
        (["a b,A,OBDH,1,5,1 W,2 W"], HEADER, "(?s)row 2:.*equipment_id"),
        (
            ["a,A,OBDH,1,5,1 W,2 W", "a,B,OBDH,1,5,1 W,2 W"],
            HEADER,
            "used more than once: \\['a'\\]",
        ),
    ],
)
def test_a_file_that_does_not_suit_is_refused(tmp_path, rows, header, message):
    with pytest.raises(ValueError, match=message):
        PowerConsumption.from_csv(write(tmp_path, *rows, header=header))


def test_a_missing_file_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError):
        PowerConsumption.from_csv(tmp_path / "power_consumption.csv")


def test_comments_are_not_a_mode(tmp_path):
    path = write(tmp_path, "a,A,OBDH,1,5,1 W,2 W,spare", header=HEADER + ",comments")
    consumption = PowerConsumption.from_csv(path)
    assert consumption.modes == ["idle", "imaging"]
    assert consumption.loads[0].comments == "spare"


# --------------------------------------------------------------- over a run


def test_every_mode_of_the_run_needs_a_column(tmp_path, model_run):
    consumption = PowerConsumption.from_csv(
        write(
            tmp_path, "a,A,OBDH,1,5,1 W,2 W", header=HEADER.replace(",imaging", ",safe")
        )
    )
    with pytest.raises(ValueError, match="no column for the modes \\['imaging'\\]"):
        run_consumption(consumption, model_run)


def test_unused_mode_columns_are_noted(consumption_run):
    (note,) = consumption_run.notes
    assert "downlink, slew" in note


def test_the_load_follows_the_mode(consumption_run, model_run):
    modes = labels_at(model_run.mode, model_run.times)
    total = consumption_run.total.to_value(u.W)
    watts = consumption_run.mode_watts
    assert total[modes == "imaging"] == pytest.approx(watts["imaging"])
    assert total[modes == "idle"] == pytest.approx(watts["idle"])


def test_the_energy_is_exact_over_the_mode_intervals(consumption_run, model_run):
    watts = consumption_run.mode_watts
    pieces = [
        (start, end, mode)
        for interval, mode in model_run.mode.items()
        for start, end in interval_pieces(model_run, interval)
    ]
    expected = sum((end - start) * watts[mode] for start, end, mode in pieces)
    end = max(stop for _, stop, _ in pieces)
    assert consumption_run.energy_until(np.array([end]))[0] == pytest.approx(expected)
    # halfway through the first piece, half of it
    start, stop, mode = consumption_run.pieces[0]
    middle = (start + stop) / 2
    assert consumption_run.energy_until(np.array([middle]))[0] == pytest.approx(
        (middle - start) * watts[mode]
    )


def test_one_orbit_gives_one_row(consumption_run, model_run):
    (row,) = consumption_run.orbit_table.to_dict("records")
    ((start, end),) = whole_orbits(model_run)
    assert row["energy [Wh]"] == pytest.approx(
        row["mean load [W]"] * (end - start) / 3600
    )
    assert row["peak load [W]"] == pytest.approx(consumption_run.mode_watts["imaging"])
    # the eclipse falls in idle, so its energy is the idle power over its time
    eclipse = sum(b - a for a, b in interval_pieces(model_run, model_run.eclipses))
    assert row["in eclipse [Wh]"] == pytest.approx(
        consumption_run.mode_watts["idle"] * eclipse / 3600, rel=1e-6
    )


def test_a_slew_draws_the_slew_column(tmp_path, data_dir):
    # the wheels draw more in slews than idle, so a slew shows above idle
    text = (data_dir / "power_consumption.csv").read_text()
    text = text.replace(
        "Rockwell RSI 45,ADCS,4,5,10 W,12 W,15 W,10 W",
        "Rockwell RSI 45,ADCS,4,5,10 W,12 W,15 W,25 W",
    )
    path = tmp_path / "power_consumption.csv"
    path.write_text(text)
    slew = "slew: {max_rate: 0.7 deg/s, max_acceleration: 0.08 deg/s2, settling_time: 20 s}\n"
    run = run_scenario(
        Scenario.from_yaml_text(
            (data_dir / "scenario.yaml").read_text() + slew, data_dir
        )
    )
    loads = run_consumption(PowerConsumption.from_csv(path), run)
    modes = labels_at(run.mode, run.times)
    slewing = modes == SLEW
    assert slewing.any()
    total = np.asarray(loads.total.to_value(u.W))
    assert total[slewing] == pytest.approx(loads.mode_watts[SLEW])
    assert loads.mode_watts[SLEW] - loads.mode_watts["idle"] == pytest.approx(
        4 * 15 * 1.05
    )
    assert loads.notes == [
        "The consumption file has columns for modes this run does not have: "
        "downlink. They are not used."
    ]


def test_the_subsystems_add_up_to_the_total(consumption_run):
    by_subsystem = consumption_run.subsystem_power()
    assert list(by_subsystem) == ["OBDH", "ADCS", "EPS", "COMM", "Payload", "Thermal"]
    total = sum(power.to_value(u.W) for power in by_subsystem.values())
    np.testing.assert_allclose(total, consumption_run.total.to_value(u.W))


def test_a_run_shorter_than_an_orbit_has_no_rows(consumption, short_run):
    loads = run_consumption(consumption, short_run.run)
    assert loads.orbit_table.empty
    assert isinstance(loads.orbit_table, pd.DataFrame)
