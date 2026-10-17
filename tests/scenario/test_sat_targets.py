# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for satellite targets: their orbits, when they are in view, and an
attitude and an articulation that point at one.

The relays are written here from the 510 km reference TLE, so their geometry is
known. RELAY-A flies the same orbit 20 deg ahead, and is always in view: the
line between the two stays about 400 km up. RELAY-B flies it 180 deg ahead, with
the Earth always between. RELAY-C flies an orbit whose node is 90 deg away, so
the two meet near the poles, and lose each other near the equator.
"""

import shutil
import warnings

import numpy as np
import pytest
from astropy.coordinates import CartesianRepresentation
from scipy.spatial.transform import Rotation
from sgp4.io import compute_checksum

from quicksat import Q_, u
from quicksat.orbit.attitude import axis_vector
from quicksat.orbit.ecsv_trajectory import write_ecsv_trajectory
from quicksat.orbit.geometry import line_of_sight_clear
from quicksat.orbit.tle import read_tle_file
from quicksat.scenario.attitude import body_rotations, directions
from quicksat.scenario.config import Scenario
from quicksat.scenario.run import run_scenario
from quicksat.scenario.viewer import scenario_data
from quicksat.utils.intervals import labels_at


def element_set(lines, name, number, anomaly=0.0, node=None, day=None):
    """
    The reference TLE as another satellite: a name line, a catalogue number, a
    mean anomaly, and if given a node and a day of 2026 for the epoch. The
    checksums are mended.
    """
    line1, line2 = lines
    epoch = line1[20:32] if day is None else f"{day:012.8f}"
    line1 = f"{line1[:2]}{number:05d}{line1[7:20]}{epoch}{line1[32:68]}"
    node_text = line2[17:25] if node is None else f"{node:8.4f}"
    line2 = (
        f"{line2[:2]}{number:05d}{line2[7:17]}{node_text}{line2[25:43]}"
        f"{anomaly:8.4f}{line2[51:68]}"
    )
    return [name, *(line + str(compute_checksum(line)) for line in (line1, line2))]


@pytest.fixture(scope="module")
def folder(data_dir, tmp_path_factory):
    """A folder with the reference TLE, the model, and a file of three relays."""
    folder = tmp_path_factory.mktemp("relays")
    for name in ("sso_510km.tle", "spacecraft.glb"):
        shutil.copy(data_dir / name, folder)
    lines = (data_dir / "sso_510km.tle").read_text().splitlines()
    node = float(lines[1][17:25]) + 90
    relays = [
        *element_set(lines, "RELAY-A", 90001, anomaly=20),
        *element_set(lines, "RELAY-B", 90002, anomaly=180),
        *element_set(lines, "RELAY-C", 90003, node=node),
    ]
    (folder / "relays.tle").write_text("\n".join(relays) + "\n")
    return folder


RELAYS = """
orbit: {tle_file: sso_510km.tle}
start: 2026-10-01T00:00:00
duration: 2 orbits
sat_targets:
  ahead: {tle_file: relays.tle, object: RELAY-A}
  opposite: {tle_file: relays.tle, object: 90002}
  RELAY-C: {tle_file: relays.tle}
attitudes:
  nadir: {point: [+z, nadir], constrain: [-y, orbit normal]}
  relay: {point: [+z, RELAY-C], constrain: [-y, orbit normal]}
activities:
  - [wait, RELAY-C rise, nadir, idle]
  - [link, RELAY-C set, relay, downlink]
"""
"""Two orbits that wait for each RELAY-C pass, and track it."""


@pytest.fixture(scope="module")
def relay_run(folder):
    """Two orbits of `RELAYS`."""
    return run_scenario(Scenario.from_yaml_text(RELAYS, folder))


def km(state):
    """A state's positions in km, one row each."""
    cartesian = state.cartesian
    assert isinstance(cartesian, CartesianRepresentation)
    return np.atleast_2d(cartesian.xyz.to_value(u.km).T)


def unit(vectors):
    """Each row scaled to unit length."""
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


# ---------------------------------------------------------------- The orbits


def test_each_target_takes_its_element_set_by_object_or_by_its_name(relay_run):
    orbits = relay_run.sat_orbits
    assert orbits["ahead"].name == "RELAY-A"
    assert orbits["opposite"].satrec.satnum == 90002
    assert orbits["RELAY-C"].name == "RELAY-C"
    assert set(relay_run.sat_states) == {"ahead", "opposite", "RELAY-C"}
    assert len(relay_run.sat_states["ahead"]) == len(relay_run.times)


def test_a_file_of_one_element_set_needs_no_object(folder):
    text = RELAYS.replace(
        "{tle_file: relays.tle, object: RELAY-A}", "{tle_file: sso_510km.tle}"
    )
    run = run_scenario(Scenario.from_yaml_text(text, folder))
    assert run.sat_orbits["ahead"].satrec.satnum == 99999
    # the same satellite as the run's own is always in view
    assert run.in_view["ahead"] == run.interval


@pytest.mark.parametrize(
    ("old", "new", "error", "message"),
    [
        (
            "object: RELAY-A",
            "object: RELAY-Z",
            ValueError,
            "'ahead': .* no element set named or numbered 'RELAY-Z'",
        ),
        (
            "RELAY-C: {tle_file: relays.tle}",
            "RELAY-C: {tle_file: relays.tle}\n  RELAY-D: {tle_file: relays.tle}",
            ValueError,
            "'RELAY-D': .* no element set named or numbered 'RELAY-D'",
        ),
        (
            "object: RELAY-A",
            "object: RELAY-A, min_clearance: 1 km}\n  lost: {tle_file: lost.tle",
            FileNotFoundError,
            "satellite target 'lost': File does not exist",
        ),
    ],
)
def test_a_target_whose_file_does_not_give_it_stops_the_run(
    folder, old, new, error, message
):
    text = (
        RELAYS.replace(old, new)
        .replace("RELAY-C rise", "10 min")
        .replace("RELAY-C set", "10 min")
    )
    with pytest.raises(error, match=message):
        run_scenario(Scenario.from_yaml_text(text, folder))


def test_attitude_directions_need_the_target_orbits(relay_run):
    with pytest.raises(ValueError, match="satellite target 'ahead' needs its orbit"):
        directions(
            relay_run.scenario, {"ahead"}, relay_run.state[:2], relay_run.sun[:2]
        )


# ---------------------------------------------------------------- In view


def test_a_target_ahead_in_the_same_orbit_is_always_in_view(relay_run):
    assert relay_run.in_view["ahead"] == relay_run.interval
    assert relay_run.in_view["opposite"].empty


def test_a_crossing_target_rises_and_sets_to_1_ms(relay_run):
    run = relay_run
    seen = run.in_view["RELAY-C"]
    orbit, clearance = run.sat_orbits["RELAY-C"], Q_(100, "km")

    def clear(times):
        return line_of_sight_clear(
            run.orbit.states(times, with_velocity=False),
            orbit.states(times, with_velocity=False),
            clearance,
        )

    edges = [
        (bound, rising)
        for piece in seen
        for bound, rising in ((piece.lower, True), (piece.upper, False))
        if run.times[0] < bound < run.times[-1]
    ]
    assert len(edges) >= 4
    for bound, rising in edges:
        either_side = clear(bound + Q_([-2, 2], "ms"))
        assert either_side.tolist() == [not rising, rising]
    # a search on a 1 s grid finds the same edges, and no others
    span = (run.times[-1] - run.times[0]).to_value(u.s)
    fine = run.times[0] + Q_(np.arange(0, span, 1.0), "s")
    flags = clear(fine)
    changes = fine[1:][flags[1:] != flags[:-1]]
    assert len(changes) == len(edges)
    for change, (bound, _) in zip(changes, edges, strict=True):
        assert 0 <= (change - bound).to_value(u.s) <= 1


def test_the_link_runs_from_the_rise_to_the_set(relay_run):
    seen = relay_run.in_view["RELAY-C"]
    links = [o for o in relay_run.occurrences if o.activity.mode == "downlink"]
    assert len(links) >= 2
    starts = {piece.lower for piece in seen}
    ends = {piece.upper for piece in seen}
    for link in links:
        assert link.start in starts
        assert link.end in ends or link.cut_at_end


def test_the_pass_table_and_the_report_count_each_targets_passes(relay_run):
    table = relay_run.passes
    assert list(table.columns) == [
        "target",
        "from [UTC]",
        "to [UTC]",
        "duration [min]",
        "closest [km]",
    ]
    assert table["from [UTC]"].is_monotonic_increasing
    ahead = table[table["target"] == "ahead"]
    assert len(ahead) == 1
    length = (relay_run.times[-1] - relay_run.times[0]).to_value(u.min)
    assert ahead["duration [min]"].iloc[0] == pytest.approx(length)
    ranges = np.linalg.norm(
        km(relay_run.sat_states["ahead"]) - km(relay_run.state), axis=1
    )
    assert ahead["closest [km]"].iloc[0] == pytest.approx(ranges.min(), abs=1e-3)
    # 20 deg apart on a 6888 km orbit
    assert ranges.min() == pytest.approx(2 * 6888 * np.sin(np.radians(10)), rel=0.01)
    assert (table["target"] == "opposite").sum() == 0
    count = (table["target"] == "RELAY-C").sum()
    report = relay_run.report
    assert f"Target ahead: 1 pass, {length:.1f} min in view." in report
    assert "Target opposite: 0 passes, 0.0 min in view." in report
    assert f"Target RELAY-C: {count} passes," in report


# ---------------------------------------------------------------- Pointing


def test_an_axis_pointed_at_a_satellite_target_lies_along_the_line_to_it(relay_run):
    attitude = labels_at(relay_run.attitude, relay_run.times)
    rows = attitude == "relay"
    assert rows.sum() > 10
    toward = unit(km(relay_run.sat_states["RELAY-C"]) - km(relay_run.state))[rows]
    z = body_rotations(relay_run)[rows] @ axis_vector("+z")
    assert np.allclose(z, toward, atol=1e-9)


MODEL = """3d_model:
  file: spacecraft.glb
  articulations:
    antenna: {part: Wing +y, axis: +y, point: [-z, RELAY-C]}
"""
"""An articulation that turns a part toward RELAY-C, whatever the body does."""


def test_an_articulation_turns_its_part_toward_a_satellite_target(folder):
    run = run_scenario(Scenario.from_yaml_text(MODEL + RELAYS, folder))
    toward = unit(km(run.sat_states["RELAY-C"]) - km(run.state))
    # the direction in body axes: the rotations' transposes turn GCRS into body
    in_body = np.einsum("nji,nj->ni", body_rotations(run), toward)
    angles = run.articulations["antenna"].to_value(u.rad)
    face = Rotation.from_rotvec(np.outer(angles, axis_vector("+y"))).apply(
        axis_vector("-z")
    )
    # the face leans toward the relay as far as a turn about y allows
    best = np.sqrt(1 - (in_body @ axis_vector("+y")) ** 2)
    assert np.einsum("ij,ij->i", face, in_body) == pytest.approx(best, abs=1e-9)
    assert scenario_data(run)["pointing"]["articulations"] == {"antenna": "RELAY-C"}


# ---------------------------------------------------------------- The checks


def test_a_target_element_set_far_from_the_run_warns_in_the_run(folder):
    text = RELAYS.replace(
        "{tle_file: sso_510km.tle}", '{sso: {altitude: 510 km, ltan: "10:30"}}'
    )
    # two orbits from 9 days before the epoch: the start is the farther end
    early = text.replace("2026-10-01T00:00:00", "2026-09-22T00:00:00")
    with pytest.warns(
        UserWarning, match="starts 9.0 days from the epoch of satellite target"
    ):
        run = run_scenario(Scenario.from_yaml_text(early, folder))
    assert len(run.warnings) == 3
    assert run.warnings[0].startswith(
        "The run starts 9.0 days from the epoch of satellite target 'ahead'"
    )
    # a run that ends too far is warned of too, and the SSO never is
    long = text.replace("2026-10-01T00:00:00", "2026-10-07T12:00:00").replace(
        "2 orbits", "1 d"
    )
    long = long.replace("RELAY-C rise", "1 h").replace("RELAY-C set", "1 h")
    with pytest.warns(
        UserWarning, match="ends 7.5 days from the epoch of satellite target"
    ):
        run = run_scenario(Scenario.from_yaml_text(long + "step: 60 s\n", folder))
    assert all("satellite target" in text for text in run.warnings)


def test_a_target_trajectory_must_cover_the_run(folder, data_dir):
    tle = read_tle_file(data_dir / "sso_510km.tle")
    times = tle.epoch + Q_(np.arange(0, 7200.0, 60.0), "s")
    write_ecsv_trajectory(
        folder / "inspector.ecsv", tle.states(times), name="inspector"
    )
    text = RELAYS.replace(
        "{tle_file: relays.tle, object: RELAY-A}", "{trajectory_file: inspector.ecsv}"
    )
    with pytest.raises(
        ValueError,
        match="does not lie inside the trajectory of satellite target 'ahead'",
    ):
        run_scenario(Scenario.from_yaml_text(text.replace("2 orbits", "3 h"), folder))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        run = run_scenario(
            Scenario.from_yaml_text(text.replace("2 orbits", "1 h"), folder)
        )
    # the trajectory is the run's own orbit, so it is always in view
    assert run.in_view["ahead"] == run.interval
    assert any(
        "trajectory of satellite target 'ahead'" in text for text in run.warnings
    )


def test_the_viewer_data_carries_each_satellite_target_and_its_file(relay_run, folder):
    data = scenario_data(relay_run)
    assert [target["name"] for target in data["targets"]] == [
        "ahead",
        "opposite",
        "RELAY-C",
    ]
    ahead = data["targets"][0]
    assert (ahead["kind"], ahead["min_clearance_km"]) == ("satellite", 100.0)
    assert ahead["source"] == {
        "file": "relays.tle",
        "element_set": "RELAY-A (90001)",
        "epoch": "2026-10-01T00:00:00.000",
    }
    positions = np.reshape(ahead["r_km"], (-1, 3))
    assert positions == pytest.approx(km(relay_run.sat_states["ahead"]), abs=0.05)
    end = data["grid"]["t_s"][-1]
    closest = relay_run.passes.loc[
        relay_run.passes["target"] == "ahead", "closest [km]"
    ]
    assert ahead["passes"] == [
        {"start_s": 0.0, "end_s": end, "closest_km": round(float(closest.iloc[0]), 1)}
    ]
    assert data["targets"][1]["passes"] == []
    assert len(data["targets"][2]["passes"]) == len(relay_run.in_view["RELAY-C"])
    # the file that three targets share is held once
    text = (folder / "relays.tle").read_text()
    assert data["target_files"] == [{"name": "relays.tle", "text": text}]
    assert data["pointing"] == {
        "attitudes": {"relay": ["RELAY-C"]},
        "articulations": {},
    }
    assert data["orbit_warnings"] == []
