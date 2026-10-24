# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the viewer: the page built from its template, and the data file.

The data file is checked against the contract in the plan: the fields, their
lengths, the tracks and the occurrences, and that the same run writes the same
bytes. Nothing here runs the page's JavaScript.

The Activity Designer's data is checked on `once_run`, a single pass of the
list that leaves the rest of the run unplanned.
"""

import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from quicksat.orbit.omm import write_omm_file
from quicksat.orbit.tle import read_tle_file
from quicksat.scenario import viewer
from quicksat.scenario.config import UNPLANNED, Scenario
from quicksat.scenario.viewer import (
    DATA_FILE,
    FORMAT,
    PAGE_FILE,
    VERSION,
    activity_rows,
    designer_page,
    scenario_data,
    viewer_page,
    write_scenario_js,
    write_scenario_viewer,
)

PREFIX = "window.quicksat.scenario = "


def read_data(path):
    """The JSON part of a `scenario.js` file."""
    for line in path.read_text().splitlines():
        if line.startswith(PREFIX):
            return json.loads(line[len(PREFIX) : -1])
    raise AssertionError(f"{path} sets no window.quicksat.scenario")


@pytest.fixture(scope="module")
def data(run):
    """The viewer's data for the fixture run."""
    return scenario_data(run)


# ---------------------------------------------------------------- The data


def test_the_data_names_its_format_and_source(data, data_dir):
    assert data["format"] == FORMAT
    assert data["version"] == VERSION
    assert data["scenario_file"] == "scenario.yaml"
    assert data["scenario_text"] == (data_dir / "scenario.yaml").read_text()
    assert data["start"] == "2026-10-01T00:00:00.000"
    assert data["orbit"]["tle"] == (data_dir / "sso_510km.tle").read_text().splitlines()
    # the orbit's file itself, so that the viewer holds every input of its run
    assert data["orbit_file"] == "sso_510km.tle"
    assert data["orbit_text"] == (data_dir / "sso_510km.tle").read_text()


def test_an_omm_file_is_held_as_written_and_an_sso_has_no_file(data_dir, tmp_path):
    write_omm_file(tmp_path / "leo.omm", read_tle_file(data_dir / "sso_510km.tle"))
    text = (data_dir / "scenario.yaml").read_text()
    sources = {
        "omm_file: leo.omm": ("leo.omm", (tmp_path / "leo.omm").read_text()),
        'sso: {altitude: 510 km, ltan: "13:30"}': (None, None),
    }
    for source, expected in sources.items():
        scenario = Scenario.from_yaml_text(
            text.replace("tle_file: sso_510km.tle", source), base_dir=tmp_path
        )
        found = viewer._orbit_file(SimpleNamespace(scenario=scenario))
        assert (found["orbit_file"], found["orbit_text"]) == expected


def test_every_grid_field_has_a_value_per_step(data, run):
    steps = len(run.times)
    per_step = {key: len(values) / steps for key, values in data["grid"].items()}
    assert per_step == {
        "t_s": 1,
        "r_km": 3,
        "v_km_s": 3,
        "sun": 3,
        "lat_deg": 1,
        "lon_deg": 1,
        "beta_deg": 1,
        "light": 1,
        "q_body": 4,
        "q_earth": 4,
    }


def test_the_light_is_a_fraction_and_the_illumination_has_three_states(data):
    light = np.array(data["grid"]["light"])
    assert np.all((light >= 0) & (light <= 1))
    assert {0.0, 1.0} <= set(light)
    values = {piece["value"] for piece in data["tracks"]["illumination"]}
    assert values == {"sunlit", "penumbra", "umbra"}


def test_the_unit_vectors_and_quaternions_have_unit_length(data):
    grid = data["grid"]
    for key, size in (("sun", 3), ("q_body", 4), ("q_earth", 4)):
        lengths = np.linalg.norm(np.reshape(grid[key], (-1, size)), axis=1)
        assert np.allclose(lengths, 1.0, atol=1e-5)


def test_each_track_covers_the_run_in_order(data):
    end = data["grid"]["t_s"][-1]
    for pieces in data["tracks"].values():
        assert pieces[0]["start_s"] == 0
        assert pieces[-1]["end_s"] == pytest.approx(end)
        for before, after in zip(pieces[:-1], pieces[1:], strict=True):
            assert after["start_s"] == before["end_s"]
            assert after["value"] != before["value"]


def test_the_occurrences_follow_the_activity_table(data, run):
    occurrences = data["occurrences"]
    assert len(occurrences) == len(run.occurrences)
    assert occurrences[0]["trigger"] == "ascending node"
    assert occurrences[-1]["statuses"] == ["cut at end"]
    assert occurrences[2]["constraint"] == "sunlit"
    assert occurrences[0]["constraint"] is None
    assert occurrences[0]["outside_s"] is None
    assert all(o["slew_s"] is None for o in occurrences)
    assert [o["title"] for o in occurrences] == [
        o.activity.title for o in run.occurrences
    ]


def test_each_slew_is_a_piece_that_names_its_target(slew_run):
    track = scenario_data(slew_run)["tracks"]["attitude"]
    slews = [piece for piece in track if piece["value"] == "slew"]
    assert len(slews) == len(slew_run.slews)
    assert [piece["target"] for piece in slews] == [w.target for w in slew_run.slews]
    # the track still covers the run, and each slew leads into its target
    for before, after in zip(track[:-1], track[1:], strict=True):
        assert after["start_s"] == before["end_s"]
        if before["value"] == "slew" and after["value"] != "slew":
            assert after["value"] == before["target"]
    assert all("target" not in piece for piece in track if piece["value"] != "slew")


def test_the_track_holds_together_when_a_slew_replaces_another(slow_run):
    track = scenario_data(slow_run)["tracks"]["attitude"]
    assert all(piece["end_s"] > piece["start_s"] for piece in track)
    for before, after in zip(track[:-1], track[1:], strict=True):
        assert after["start_s"] == before["end_s"]


def test_the_occurrences_carry_their_slews(slew_run):
    data = scenario_data(slew_run)
    slews = [o["slew_s"] for o in data["occurrences"] if o["slew_s"] is not None]
    assert slews == [window.duration.to_value("s") for window in slew_run.slews]
    values = {piece["value"] for piece in data["tracks"]["attitude"]}
    assert values == {"nadir", "sun pointing", "slew"}


def test_the_id_is_the_hash_of_the_rest(data):
    rest = {key: value for key, value in data.items() if key != "id"}
    text = json.dumps(rest, allow_nan=False, separators=(",", ":"))
    assert data["id"] == hashlib.sha256(text.encode()).hexdigest()[:16]


def test_a_negative_duration_ends_before_it_starts(problem_run):
    occurrences = scenario_data(problem_run)["occurrences"]
    negative = [o for o in occurrences if "negative duration" in o["statuses"]]
    assert len(negative) == 1
    assert negative[0]["end_s"] < negative[0]["start_s"]


# ---------------------------------------------------------------- The files


def test_the_data_file_reads_back_and_a_rerun_writes_the_same_bytes(
    run, data, tmp_path
):
    first = write_scenario_js(run, tmp_path / "one")
    second = write_scenario_js(run, tmp_path / "two")
    assert first.name == DATA_FILE
    assert first.read_bytes() == second.read_bytes()
    assert read_data(first) == data
    lines = first.read_text().splitlines()
    assert lines[1] == "window.quicksat = window.quicksat || {};"


def test_the_page_is_built_with_everything_inside():
    page = viewer_page()
    for placeholder in viewer._PAGE_PARTS:
        assert placeholder not in page
    assert '<script src="scenario.js"></script>' in page
    assert "three.js authors" in page
    assert "Leon Sorokin" in page


def test_the_viewer_folder_holds_the_page_and_the_data(run, tmp_path):
    page = write_scenario_viewer(run, tmp_path / "viewer")
    assert page.name == PAGE_FILE
    assert sorted(path.name for path in page.parent.iterdir()) == [DATA_FILE, PAGE_FILE]
    assert page.read_text(encoding="utf-8") == viewer_page()


def test_a_template_without_a_placeholder_is_refused(monkeypatch, tmp_path):
    parts = dict(viewer._PAGE_PARTS)
    parts["@missing@"] = (tmp_path / "missing.js", None)
    monkeypatch.setattr(viewer, "_PAGE_PARTS", parts)
    with pytest.raises(ValueError, match="@missing@ must appear once"):
        viewer_page()


def test_a_library_that_would_end_its_script_tag_is_refused(monkeypatch, tmp_path):
    bad = tmp_path / "bad.js"
    bad.write_text("var x = '</script>';")
    parts = dict(viewer._PAGE_PARTS)
    parts["/*@three@*/"] = (bad, None)
    monkeypatch.setattr(viewer, "_PAGE_PARTS", parts)
    with pytest.raises(ValueError, match="ends its tag"):
        viewer_page()


# ---------------------------------------------------------------- The designer


@pytest.fixture(scope="module")
def design(once_run):
    """The Activity Designer's data for one pass of the list."""
    return scenario_data(once_run, designer=True)


def test_the_designer_data_leaves_out_the_body(design):
    assert design["format"] == FORMAT
    assert design["version"] == VERSION
    assert design["grid"]["q_body"] is None
    attitude = design["attitude"]
    for key in ("roll_deg", "pitch_deg", "yaw_deg", "files"):
        assert attitude[key] is None
    model = design["model"]
    assert model["glb_base64"] is None
    # the page finds when a part points at a target from its park modes
    wings = {joint["name"]: joint for joint in model["articulations"]}
    assert wings["wing +y"]["park_modes"] == ["downlink"]
    assert all(joint["angle_deg"] is None for joint in wings.values())


def test_the_designer_data_keeps_the_rates_for_the_turn_rate_bands(design, once_run):
    attitude = design["attitude"]
    assert attitude["max_rate_deg_s"] == pytest.approx(0.05)
    rates = attitude["rate_deg_s"]
    assert len(rates) == len(design["grid"]["t_s"])
    end = design["designer"]["pass_s"]
    times = design["grid"]["t_s"]
    after = [rate for t, rate in zip(times, rates, strict=True) if t >= end]
    assert after and all(rate is None for rate in after)
    assert max(rate for rate in rates if rate is not None) > 0.05
    assert design["warnings"] == once_run.warnings
    assert design["warnings"]


def test_the_designer_tracks_end_in_the_unplanned_time(design):
    end = design["grid"]["t_s"][-1]
    for name in ("attitude", "payload_mode", "platform_mode"):
        pieces = design["tracks"][name]
        assert pieces[-1] == {
            "value": UNPLANNED,
            "start_s": design["designer"]["pass_s"],
            "end_s": end,
        }
        assert [p["value"] for p in pieces].count(UNPLANNED) == 1


def test_the_designer_data_gives_the_pass(design, once_run):
    last = once_run.occurrences[-1]
    seconds = (last.end - once_run.times[0]).to_value("s")
    assert design["designer"] == {"repeat": False, "pass_s": round(seconds, 3)}


def test_only_the_designer_data_has_the_designer_field(data):
    assert "designer" not in data


def test_the_normal_viewer_refuses_an_unplanned_run(once_run):
    with pytest.raises(ValueError, match="no activity plans the run"):
        scenario_data(once_run)


def test_each_activity_has_a_row_of_results(once_run):
    rows = activity_rows(once_run)
    assert [row["number"] for row in rows] == list(range(1, 9))
    assert all(row["count"] == 1 for row in rows)
    excesses = once_run.rate_excesses
    assert sum(row["excesses"] for row in rows) == len(excesses)
    for row, occurrence in zip(rows, once_run.occurrences, strict=True):
        own = [e for e in excesses if e.occurrence.number == row["number"]]
        if own:
            peak = max(e.peak_rate.to_value("deg/s") for e in own)
            assert row["peak_rate_deg_s"] == pytest.approx(peak, abs=1e-5)
            assert row["peak_rate_deg_s"] > 0.05
        else:
            assert row["peak_rate_deg_s"] is None
        problems = [status for status in occurrence.statuses if status != "ok"]
        assert row["statuses"] == dict.fromkeys(problems, 1)
        constraint = occurrence.activity.constraint
        assert (row["outside_s"] is None) == (constraint is None)
        slew = occurrence.slew
        assert row["slew_s"] == (None if slew is None else round(slew.to_value("s"), 3))


def test_the_rows_count_the_repeats_and_the_statuses(run):
    rows = activity_rows(run)
    assert sum(row["count"] for row in rows) == len(run.occurrences)
    last = run.occurrences[-1]
    assert rows[last.number - 1]["statuses"] == {"cut at end": 1}
    assert sum(len(row["statuses"]) for row in rows) == 1


def page_data(page):
    """The data that a designer page holds."""
    script = page.split("<script>window.quicksat = {scenario: ")[1]
    return json.loads(script.split("};</script>")[0])


def test_the_designer_page_holds_its_data(design):
    page = designer_page(design)
    assert '<script src="scenario.js"></script>' not in page
    assert '<script src="power.js"></script>' not in page
    assert page_data(page) == design


def test_no_text_of_the_scenario_ends_the_script_early(design):
    text = "comments: a note that says </script><script>alert(1)</script>\n"
    page = designer_page(design | {"scenario_text": text})
    assert "</script><script>alert" not in page
    assert page_data(page)["scenario_text"] == text
