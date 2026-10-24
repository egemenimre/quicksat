# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the power consumption: the CSV files, their checks, and the loads over
a run, with the payload's and the platform's modes, and the slews as a platform
mode of their own.
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


def write(tmp_path, *rows: str, header: str = HEADER, name: str = "loads.csv"):
    """A consumption file with the given rows."""
    path = tmp_path / name
    path.write_text("\n".join([header, *rows]) + "\n")
    return path


def both_in(loads, mode: str) -> float:
    """The power of all the equipment with the payload and the platform in one mode."""
    return loads.watts({"payload": mode, "platform": mode})


# ------------------------------------------------------------------ the file


def test_the_fixture_reads(consumption):
    payload, platform = consumption["payload"], consumption["platform"]
    assert payload.modes == ["idle", "imaging", "downlink"]
    assert platform.modes == ["idle", "imaging", "ttc", "slew"]
    assert (len(payload.loads), len(platform.loads)) == (5, 11)
    wheels = next(
        load for load in platform.loads if load.equipment_id == "reaction_wheel"
    )
    assert wheels.units_on == 4
    assert wheels.watts("ttc", margin=False) == pytest.approx(60)
    assert wheels.watts("ttc") == pytest.approx(63)
    totals = payload.mode_totals()
    assert list(totals.loc["without margins"]) == pytest.approx([50, 150, 120])
    totals = platform.mode_totals()
    assert list(totals.loc["without margins"]) == pytest.approx([138, 140, 173, 138])
    assert totals.loc["with equipment margins", "idle [W]"] == pytest.approx(149.05)


def test_the_mode_table_gives_each_row_its_units_together(consumption):
    table = consumption["platform"].mode_table().set_index("equipment_id")
    assert table.loc["star_tracker", "idle [W]"] == 12
    payload = consumption["payload"].mode_table(margin=True)
    with_margins = payload.set_index("equipment_id")
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
        PowerConsumption.from_csv(tmp_path / "payload_consumption.csv")


def test_comments_are_not_a_mode(tmp_path):
    path = write(tmp_path, "a,A,OBDH,1,5,1 W,2 W,spare", header=HEADER + ",comments")
    consumption = PowerConsumption.from_csv(path)
    assert consumption.modes == ["idle", "imaging"]
    assert consumption.loads[0].comments == "spare"


# --------------------------------------------------------------- over a run


def test_every_mode_of_the_run_needs_a_column_in_its_group_file(
    tmp_path, consumption, model_run
):
    safe = PowerConsumption.from_csv(
        write(
            tmp_path,
            "a,A,OBDH,1,5,1 W,2 W",
            header=HEADER.replace(",imaging", ",safe"),
            name="payload_consumption.csv",
        )
    )
    with pytest.raises(
        ValueError,
        match="payload_consumption.csv has no column for the payload's modes "
        "\\['imaging'\\]",
    ):
        run_consumption(consumption | {"payload": safe}, model_run)
    with pytest.raises(ValueError, match="no consumption file for the platform"):
        run_consumption({"payload": consumption["payload"]}, model_run)


def test_unused_mode_columns_are_noted(consumption_run):
    payload, platform = consumption_run.notes
    assert payload.startswith("payload_consumption.csv")
    assert payload.endswith("the payload: downlink. They are not used.")
    assert "the platform: ttc, slew" in platform


def test_the_load_follows_each_group_mode(consumption_run, model_run):
    modes = {
        group: labels_at(row, model_run.times) for group, row in model_run.mode.items()
    }
    total = consumption_run.total.to_value(u.W)
    watts = consumption_run.mode_watts
    for mode in ("imaging", "idle"):
        both = (modes["payload"] == mode) & (modes["platform"] == mode)
        assert both.any()
        expected = watts["payload"][mode] + watts["platform"][mode]
        assert total[both] == pytest.approx(expected)
    assert both_in(consumption_run, "idle") == pytest.approx(207.55)


def test_the_energy_is_exact_over_the_mode_intervals(consumption_run, model_run):
    watts = consumption_run.mode_watts
    expected, end = 0.0, 0.0
    for group, row in model_run.mode.items():
        for interval, mode in row.items():
            for start, stop in interval_pieces(model_run, interval):
                expected += (stop - start) * watts[group][mode]
                end = max(end, stop)
    assert consumption_run.energy_until(np.array([end]))[0] == pytest.approx(expected)
    # halfway through the first piece, half of it
    start, stop, modes = consumption_run.pieces[0]
    middle = (start + stop) / 2
    assert consumption_run.energy_until(np.array([middle]))[0] == pytest.approx(
        (middle - start) * consumption_run.watts(modes)
    )


def test_the_pieces_cut_the_run_where_either_mode_changes(consumption_run):
    pieces = consumption_run.pieces
    assert pieces[0][0] == 0
    for (_, end, modes), (start, _, after) in zip(pieces, pieces[1:], strict=False):
        assert end == start
        assert modes != after
    assert all(set(modes) == {"payload", "platform"} for _, _, modes in pieces)


def test_one_orbit_gives_one_row(consumption_run, model_run):
    (row,) = consumption_run.orbit_table.to_dict("records")
    ((start, end),) = whole_orbits(model_run)
    assert row["energy [Wh]"] == pytest.approx(
        row["mean load [W]"] * (end - start) / 3600
    )
    assert row["peak load [W]"] == pytest.approx(both_in(consumption_run, "imaging"))
    # the eclipse falls in idle, so its energy is the idle power over its time
    eclipse = sum(b - a for a, b in interval_pieces(model_run, model_run.eclipses))
    assert row["in eclipse [Wh]"] == pytest.approx(
        both_in(consumption_run, "idle") * eclipse / 3600, rel=1e-6
    )


def test_a_slew_draws_the_platform_slew_column_and_the_payload_carries_on(
    tmp_path, data_dir, consumption
):
    # the wheels draw more in slews than idle, so a slew shows above idle
    text = (data_dir / "platform_consumption.csv").read_text()
    text = text.replace(
        "Rockwell RSI 45,ADCS,4,5,10 W,12 W,15 W,10 W",
        "Rockwell RSI 45,ADCS,4,5,10 W,12 W,15 W,25 W",
    )
    path = tmp_path / "platform_consumption.csv"
    path.write_text(text)
    slew = "slew: {max_rate: 0.7 deg/s, max_acceleration: 0.08 deg/s2, settling_time: 20 s}\n"
    run = run_scenario(
        Scenario.from_yaml_text(
            (data_dir / "scenario.yaml").read_text() + slew, data_dir
        )
    )
    files = consumption | {"platform": PowerConsumption.from_csv(path)}
    loads = run_consumption(files, run)
    platform, payload = loads.modes["platform"], loads.modes["payload"]
    slewing = platform == SLEW
    assert slewing.any()
    # the payload file has no slew column: the payload stays in its own mode
    assert SLEW not in payload
    total = np.asarray(loads.total.to_value(u.W))
    watts = loads.mode_watts
    expected = [watts["platform"][SLEW] + watts["payload"][mode] for mode in payload]
    assert total[slewing] == pytest.approx(np.array(expected)[slewing])
    assert watts["platform"][SLEW] - watts["platform"]["idle"] == pytest.approx(
        4 * 15 * 1.05
    )
    assert loads.notes == [
        "payload_consumption.csv has columns for modes that the run does not give "
        "the payload: downlink. They are not used.",
        "platform_consumption.csv has columns for modes that the run does not give "
        "the platform: ttc. They are not used.",
    ]


def test_the_subsystems_add_up_to_the_total(consumption_run):
    by_subsystem = consumption_run.subsystem_power()
    # the payload's file first; a subsystem in both files adds the two
    assert list(by_subsystem) == ["COMM", "OBDH", "Payload", "Thermal", "ADCS", "EPS"]
    total = sum(power.to_value(u.W) for power in by_subsystem.values())
    np.testing.assert_allclose(total, consumption_run.total.to_value(u.W))


def test_a_run_shorter_than_an_orbit_has_no_rows(consumption, short_run):
    loads = run_consumption(consumption, short_run.run)
    assert loads.orbit_table.empty
    assert isinstance(loads.orbit_table, pd.DataFrame)
