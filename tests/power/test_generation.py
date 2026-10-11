# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the power generation: the panels from the model, the power over a
run, the energy per orbit, and the Orekit case.

The Orekit case is described in `data/README.md`, with the agreement the
prototype reached. Orekit's shadow is a cylinder, and quicksat's has a penumbra
on WGS84, which moves each eclipse edge by seconds. So the whole-orbit means are
checked with the reference's lit flag, which isolates the geometry. The shadow
itself is checked against Orekit in `tests/orbit/test_geometry.py`.
"""

import numpy as np
import pytest

from quicksat import Q_, u
from quicksat.power.config import PowerGeneration
from quicksat.power.generation import (
    _energy_until,
    flat_panel,
    panel_geometry,
    panel_notes,
    turned_normals,
)
from quicksat.scenario.config import Scenario
from quicksat.utils.intervals import duration

# ------------------------------------------------------------- the panel shapes


SQUARE = np.array(
    [[[0, 0, 0], [1, 0, 0], [1, 1, 0]], [[0, 0, 0], [1, 1, 0], [0, 1, 0]]]
)
"""A 1 m2 square in the x-y plane, facing +z."""


def test_a_flat_part_gives_its_area_and_normal():
    area, normal = flat_panel(SQUARE.astype(float))
    assert area == pytest.approx(1.0)
    np.testing.assert_allclose(normal, [0, 0, 1])


def test_a_part_that_is_not_flat_is_refused():
    # one triangle tilted by 2 deg about x, more than the 1 deg allowed
    tilted = SQUARE.astype(float)
    tilted[1, 2, 2] = np.tan(np.radians(2))
    with pytest.raises(ValueError, match="is not flat"):
        flat_panel(tilted)
    # both faces of a thin plate face no one way
    plate = np.concatenate([SQUARE, SQUARE[:, ::-1]]).astype(float)
    with pytest.raises(ValueError, match="faces no one way"):
        flat_panel(plate)
    with pytest.raises(ValueError, match="has no area"):
        flat_panel(np.zeros((1, 3, 3)))


def test_the_panels_come_from_the_model(generation, model_run):
    panels, model = panel_geometry(generation, model_run.scenario)
    assert model is not None
    wing = panels["wing +y outer"]
    assert wing.area.to_value(u.m**2) == pytest.approx(0.4026, abs=1e-6)
    np.testing.assert_allclose(wing.normal, [0, 0, -1], atol=1e-12)
    assert wing.articulation == "wing +y"
    assert panels["wing -y inner"].articulation == "wing -y"
    deck = panels["deck"]
    assert deck.area.to_value(u.m**2) == pytest.approx(0.0716, abs=1e-6)
    assert deck.articulation is None
    assert deck.node is not None
    typed = panels["side +x"]
    assert typed.node is None
    np.testing.assert_allclose(typed.normal, [1, 0, 0])


def scenario_with(data_dir, articulations: str) -> Scenario:
    """`scenario.yaml` with other articulations."""
    text = (data_dir / "scenario.yaml").read_text()
    start = text.index("  articulations:")
    end = text.index("attitudes:")
    return Scenario.from_yaml_text(
        text[:start] + articulations + text[end:], base_dir=data_dir
    )


@pytest.mark.parametrize(
    ("part", "message"),
    [
        ("Solar array", "no node named 'Solar array'"),
        ("Spider", "2 nodes named 'Spider'"),
        ("Wing +y", "has no triangles"),
        ("Bus", "faces no one way"),
    ],
)
def test_a_part_that_does_not_suit_is_refused(model_run, part, message):
    text = f"cell_efficiency: 1\nloss_factor: 1\npanels:\n  only: {{part: {part}, fill_ratio: 1}}\n"
    with pytest.raises(ValueError, match=message):
        panel_geometry(PowerGeneration.from_yaml_text(text), model_run.scenario)


def test_a_part_without_a_model_is_refused(generation, six_faces_run):
    with pytest.raises(ValueError, match="has no 3D model"):
        panel_geometry(generation, six_faces_run.run.scenario)


def test_a_panel_turns_with_one_articulation_only(generation, data_dir):
    scenario = scenario_with(
        data_dir,
        "  articulations:\n"
        "    wing: {part: Wing +y, axis: +y, sun_axis: -z}\n"
        "    panel: {part: Wing +y inner cells, axis: +y, sun_axis: -z}\n",
    )
    with pytest.raises(ValueError, match="sits under 2 articulations"):
        panel_geometry(generation, scenario)


# ------------------------------------------------------------------ the notes


def panels_file(*lines: str, shading: bool = False) -> PowerGeneration:
    """A file with the panels in `lines`, each a name and its YAML mapping."""
    text = "cell_efficiency: 1\nloss_factor: 1\npanels:\n"
    text += "".join(f"  {line}\n" for line in lines)
    if shading:
        text += "self_shadowing: {enabled: true}\n"
    return PowerGeneration.from_yaml_text(text)


TYPED = "side: {normal: +x, area: 1 m2, fill_ratio: 1}"
PART = "deck: {part: Deck cells, fill_ratio: 1}"


def test_typed_in_panels_get_a_note():
    assert panel_notes(panels_file(PART), has_model=True) == []
    (mixed,) = panel_notes(panels_file(PART, TYPED), has_model=True)
    assert "typed in, not taken from the 3D model: side" in mixed
    (typed,) = panel_notes(panels_file(TYPED), has_model=True)
    assert typed.startswith("All panels are typed in")
    (no_model,) = panel_notes(panels_file(TYPED), has_model=False)
    assert no_model.startswith("The scenario has no 3D model")
    _, shading = panel_notes(panels_file(TYPED, shading=True), has_model=False)
    assert "Self-shadowing is on, but no panel comes from the 3D model" in shading
    assert len(panel_notes(panels_file(PART, TYPED, shading=True), True)) == 1


def test_the_run_carries_the_notes(generation_run):
    (note,) = generation_run.notes
    assert "side +x" in note


# --------------------------------------------------------------- the power


def test_a_normal_turns_right_handed():
    normals = turned_normals(
        np.array([0.0, 0.0, -1.0]), np.array([0.0, 1.0, 0.0]), Q_([0, 90, 180], "deg")
    )
    np.testing.assert_allclose(normals, [[0, 0, -1], [-1, 0, 0], [0, 0, 1]], atol=1e-15)


def test_a_wing_faces_the_sun_as_far_as_its_axis_allows(generation_run, model_run):
    # while it tracks, the cosine is the length of the sun's part across the axis
    cosine = generation_run.cosines["wing +y outer"]
    expected = np.sqrt(1 - model_run.sun_body[:, 1] ** 2)
    angles = model_run.articulations["wing +y"].to_value(u.deg)
    tracking = angles != 0
    assert tracking.sum() > 100
    np.testing.assert_allclose(cosine[tracking], expected[tracking], atol=1e-12)


def test_a_parked_wing_and_the_deck_face_minus_z(generation_run, model_run):
    facing = -model_run.sun_body[:, 2]
    parked = model_run.articulations["wing -y"].to_value(u.deg) == 0
    assert parked.sum() > 30
    np.testing.assert_allclose(
        generation_run.cosines["wing -y inner"][parked], facing[parked], atol=1e-12
    )
    np.testing.assert_allclose(generation_run.cosines["deck"], facing, atol=1e-12)
    np.testing.assert_allclose(
        generation_run.cosines["side +x"], model_run.sun_body[:, 0], atol=1e-15
    )


def test_the_power_is_the_product_of_its_factors(generation_run, model_run):
    flux = generation_run.flux.to_value(u.W / u.m**2)
    assert 1340 < flux.min() < flux.max() < 1420
    cosine = np.clip(generation_run.cosines["deck"], 0, None)
    expected = flux * 0.0716 * 0.80 * 0.30 * 0.80 * cosine * model_run.light
    np.testing.assert_allclose(
        generation_run.power["deck"].to_value(u.W), expected, rtol=1e-6
    )
    # no power in the umbra, and none from a panel with the sun behind it
    assert np.all(generation_run.total[model_run.light == 0] == 0)
    assert np.all(
        generation_run.power["side +x"][generation_run.cosines["side +x"] < 0] == 0
    )
    total = sum(power.to_value(u.W) for power in generation_run.power.values())
    np.testing.assert_allclose(generation_run.total.to_value(u.W), total)


# ------------------------------------------------------------------- the orbits


def test_the_energy_is_exact_for_a_power_that_changes_linearly():
    seconds = np.array([0.0, 10.0, 20.0, 25.0])
    power = 3.0 + 2.0 * seconds
    at = np.array([0.0, 4.0, 10.0, 17.5, 25.0])
    np.testing.assert_allclose(
        _energy_until(seconds, power, at), 3.0 * at + at**2, rtol=1e-14
    )


def test_one_orbit_gives_one_row(generation_run, model_run):
    (row,) = generation_run.orbit_table.to_dict("records")
    period = model_run.orbit.period.to_value(u.s)
    assert row["orbit"] == 1
    assert row["start [UTC]"] == model_run.times[0].utc.isot
    eclipse = duration(model_run.eclipses).to_value(u.min)
    assert row["eclipse [min]"] == pytest.approx(eclipse, abs=1e-6)
    assert row["energy [Wh]"] == pytest.approx(
        row["mean power [W]"] * period / 3600, rel=1e-12
    )
    # the panels generate only in sunlight and in the penumbra, so the mean over
    # the sunlit time is the higher one
    sunlit = (period / 60 - row["eclipse [min]"]) * 60
    assert row["sunlit mean power [W]"] * sunlit / 3600 <= row["energy [Wh]"]
    assert row["sunlit mean power [W]"] > row["mean power [W]"]


def test_the_panel_energies_add_up_to_the_total(generation_run):
    table = generation_run.panel_energy_table
    assert list(table.columns) == [
        "orbit",
        *[f"{name} [Wh]" for name in generation_run.power],
        "total [Wh]",
    ]
    panels = table.drop(columns=["orbit", "total [Wh]"]).sum(axis=1)
    np.testing.assert_allclose(panels, table["total [Wh]"], rtol=1e-12)
    np.testing.assert_allclose(
        table["total [Wh]"], generation_run.orbit_table["energy [Wh]"], rtol=1e-12
    )


def test_a_run_shorter_than_an_orbit_has_no_rows(short_run):
    assert short_run.orbits == []
    assert short_run.orbit_table.empty
    assert len(short_run.panel_energy_table) == 0


# -------------------------------------------------------------- the Orekit case


SAMPLES = 8640
"""The reference ends one step before the run's grid, which includes its end."""


def test_the_cosines_match_orekit(six_faces_run, case, reference):
    for row, face in enumerate(case["inputs"]["faces"]):
        cosine = six_faces_run.cosines[face][:SAMPLES]
        assert np.abs(cosine - reference["cos"][row]).max() < 2e-4, face


def test_the_sun_direction_matches_orekit(six_faces_run, reference):
    # Orekit's sun is geometric and seen from the centre of the Earth. Ours is
    # apparent, which adds 20.5 arcsec of aberration, and seen from the
    # satellite, which adds up to 9.5 arcsec of parallax.
    suns = six_faces_run.run.sun_body[:SAMPLES]
    cosines = np.einsum("ni,in->n", suns, reference["sun_body"])
    arcsec = np.degrees(np.arccos(np.clip(cosines, -1, 1))) * 3600
    assert arcsec.max() < 30


def test_the_flux_matches_the_reference(six_faces_run, reference):
    # the reference's distance is from the centre of the Earth, ours from the
    # satellite, up to 4.6e-5 of the distance away
    flux = six_faces_run.flux[:SAMPLES].to_value(u.W / u.m**2)
    assert np.abs(flux / reference["flux"] - 1).max() < 1e-4


def test_the_whole_orbit_means_match_orekit(six_faces_run, case, reference):
    whole = reference["whole"]
    expected = case["expected"]["face_mean_power_w_whole_orbits"]
    flux = six_faces_run.flux[:SAMPLES].to_value(u.W / u.m**2)
    for face, means in expected.items():
        cosine = np.clip(six_faces_run.cosines[face][:SAMPLES], 0, None)
        mean = (flux * cosine * reference["lit"])[whole].mean()
        if means["orekit"] == 0:
            assert mean == 0
            continue
        assert mean == pytest.approx(means["orekit"], rel=1e-3), face
        assert mean == pytest.approx(means["closed_form_circular"], rel=1e-2), face


def test_the_day_holds_fifteen_whole_orbits(six_faces_run):
    table = six_faces_run.orbit_table
    assert len(table) == 15
    # in nadir pointing, each orbit sees the same geometry, so the energy
    # changes by little from one orbit to the next
    energy = table["energy [Wh]"]
    assert energy.max() / energy.min() - 1 < 2e-3


def test_the_panel_table_lists_what_the_file_and_the_model_give(generation_run):
    table = generation_run.panel_table.set_index("panel")
    assert list(table.index) == list(generation_run.panels)
    deck = table.loc["deck"]
    assert deck["part"] == "Deck cells"
    assert deck["area [m2]"] == pytest.approx(0.0716, abs=1e-6)
    assert deck["fill ratio [%]"] == pytest.approx(80)
    assert deck["normal"] == "[+0.000, +0.000, -1.000]"
    assert deck["turns with"] == ""
    assert table.loc["wing -y outer", "turns with"] == "wing -y"
    assert table.loc["side +x", "part"] == ""
