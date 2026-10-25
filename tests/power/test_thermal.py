# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the payload's heat account: the view factor to the Earth, the heat the
surfaces absorb and emit, the checks on the files, the sums by activity, mode and
orbit, the equilibrium ΔT and the balancing heater power.

The view factor is checked against a numerical integral over the Earth's disk.
The account is checked by hand at one step, and its sums against each other.
"""

import numpy as np
import pytest
from astropy.coordinates import CartesianRepresentation
from astropy.tests.helper import assert_quantity_allclose
from astropy.units import Quantity

from quicksat import Q_, R_EARTH, u
from quicksat.power.config import SelfShadowing
from quicksat.power.consumption import PowerConsumption
from quicksat.power.generation import solar_flux
from quicksat.power.orbits import run_seconds
from quicksat.scenario.attitude import attitude_names
from quicksat.scenario.config import Scenario
from quicksat.scenario.run import run_scenario
from quicksat.thermal.account import (
    TERMS,
    check_files,
    equilibrium_dt,
    payload_pieces,
    run_thermal,
)
from quicksat.thermal.config import PayloadThermal
from quicksat.thermal.surfaces import (
    STEFAN_BOLTZMANN,
    earth_angular_radius,
    surface_powers,
    view_factor,
)

# ---------------------------------------------------------------- view factor


def integrated(cosine: float, radius: Quantity, count: int = 2000) -> float:
    """The view factor as a numerical integral of cos θ / π over the Earth's disk.

    The disk is the cone of directions within the angular radius of the centre.
    The midpoint rule covers the angle from the centre, and even steps the angle
    around it.
    """
    rho = float(radius.to(u.rad).value)
    alpha = (np.arange(count) + 0.5) * rho / count
    weights = np.sin(alpha) * rho / count
    phi = np.linspace(0, 2 * np.pi, 2 * count, endpoint=False)
    sine = np.sqrt(1 - cosine**2)
    plate = (
        sine * np.sin(alpha)[:, None] * np.cos(phi)[None]
        + cosine * np.cos(alpha)[:, None]
    )
    inner = np.clip(plate, 0, None).sum(axis=1) * (2 * np.pi / len(phi))
    return float(weights @ inner) / np.pi


RADII = [Q_(67.8, "deg"), Q_(30, "deg"), Q_(85, "deg")]
"""The Earth's angular radius at 510 km, and from further and nearer."""


@pytest.mark.parametrize("radius", RADII, ids=lambda r: f"rho {r.value:g}")
@pytest.mark.parametrize("tilt", [0, 15, 40, 60, 80, 90, 100, 120, 150, 170, 180])
def test_the_view_factor_matches_the_integral_over_the_disk(radius, tilt):
    cosine = float(np.cos(np.radians(tilt)))
    expected = integrated(cosine, radius)
    assert view_factor(np.array([cosine]), radius)[0] == pytest.approx(
        expected, abs=2e-6
    )


@pytest.mark.parametrize("radius", RADII, ids=lambda r: f"rho {r.value:g}")
def test_the_view_factor_has_three_cases(radius):
    rho = radius.to_value(u.rad)
    full = view_factor(np.array([1.0, np.sin(rho) + 1e-6]), radius)
    np.testing.assert_allclose(
        full, np.array([1.0, np.sin(rho) + 1e-6]) * np.sin(rho) ** 2
    )
    assert view_factor(np.array([-1.0, -np.sin(rho) - 1e-6]), radius) == pytest.approx(
        [0, 0]
    )
    edge_on = (rho - np.sin(rho) * np.cos(rho)) / np.pi
    assert view_factor(np.array([0.0]), radius)[0] == pytest.approx(edge_on)


@pytest.mark.parametrize("radius", RADII, ids=lambda r: f"rho {r.value:g}")
def test_the_view_factor_joins_its_cases_smoothly(radius):
    # the partial view meets the full view and the no view with no step
    for join in (np.sin(radius), -np.sin(radius)):
        below, above = view_factor(np.array([join - 1e-9, join + 1e-9]), radius)
        assert above == pytest.approx(below, abs=1e-7)


def test_the_earth_angular_radius_follows_the_distance(model_run):
    radius = earth_angular_radius(model_run)
    cartesian = model_run.state.cartesian
    assert isinstance(cartesian, CartesianRepresentation)
    distance = np.linalg.norm(cartesian.xyz.to_value(u.km), axis=0)
    np.testing.assert_allclose(
        np.sin(radius.to_value(u.rad)), R_EARTH.to_value(u.km) / distance
    )
    assert radius.min() > Q_(67, "deg") and radius.max() < Q_(69, "deg")


# --------------------------------------------------------------- the surfaces


def test_the_surfaces_come_from_the_model(thermal_run):
    surfaces = thermal_run.surfaces.surfaces
    assert_quantity_allclose(surfaces["radiator"].area, Q_(0.2, "m2"), rtol=1e-6)
    np.testing.assert_allclose(surfaces["radiator"].normal, [0, 1, 0], atol=1e-12)
    np.testing.assert_allclose(surfaces["aperture"].normal, [0, 0, 1], atol=1e-12)
    assert thermal_run.notes == [
        "payload_thermal.yaml: the heat flow 'x-band rf' has powers for modes that "
        "the run does not give the payload: downlink. They are not used."
    ]


def test_a_surface_absorbs_and_emits_as_the_formulas_say(thermal_run, model_run):
    surfaces = thermal_run.surfaces
    normal = np.array([0.0, 1.0, 0.0])
    flux = np.asarray(solar_flux(model_run).to(u.W / u.m**2).value)
    sun = np.clip(model_run.sun_body @ normal, 0, None) * model_run.light
    step = int(np.argmax(sun))
    # the test run's 10:30 LTAN puts the sun on the +y side, at a beta of -19 deg
    assert sun[step] > 0.3
    area, alpha, epsilon = 0.2, 0.20, 0.85
    rho = Q_(np.asarray(earth_angular_radius(model_run).to(u.deg).value)[step], "deg")
    factor = view_factor(np.array([model_run.nadir_body[step] @ normal]), rho)[0]
    zenith = max(model_run.sun_zenith_cosine[step], 0)
    assert surfaces.lit["radiator"][step] == 1  # no self-shadowing in the test file
    assert surfaces.absorbed["sun"]["radiator"][step] == pytest.approx(
        flux[step] * alpha * area * sun[step], rel=1e-6
    )
    assert surfaces.absorbed["albedo"]["radiator"][step] == pytest.approx(
        flux[step] * 0.30 * factor * alpha * area * zenith, rel=1e-6
    )
    assert surfaces.absorbed["infrared"]["radiator"][step] == pytest.approx(
        237 * factor * epsilon * area, rel=1e-6
    )
    sigma = STEFAN_BOLTZMANN.to_value(u.W / u.m**2 / u.K**4)
    assert surfaces.emitted["radiator"] == pytest.approx(
        -epsilon * sigma * area * 273**4, rel=1e-6
    )


def test_the_sun_edge_on_counts_as_no_sun(thermal_run, model_run):
    # +y lies across the sun in sun pointing, so the radiator sees it in nadir only
    names = attitude_names(model_run)
    cosines = thermal_run.surfaces.sun_cosines["radiator"]
    edge_on = (names == "sun pointing") & (model_run.light > 0)
    assert np.abs(cosines[edge_on]).max() < 1e-9
    sees = ((names == "nadir") & (model_run.light > 0)).astype(float)
    seconds = run_seconds(model_run)
    nadir_minutes = float(np.diff(seconds) @ ((sees[:-1] + sees[1:]) / 2)) / 60
    table = thermal_run.surface_table.set_index("surface")
    assert table.loc["radiator", "in sun [min]"] == pytest.approx(nadir_minutes)


def test_the_albedo_is_zero_over_the_night_side(thermal_run, model_run):
    night = model_run.sun_zenith_cosine < 0
    assert night.any()
    for name in thermal_run.thermal.surfaces:
        assert np.all(thermal_run.surfaces.absorbed["albedo"][name][night] == 0)


def test_the_surfaces_follow_the_self_shadowing_switch(
    thermal, power_system, model_run
):
    assert not power_system.shading
    lit = surface_powers(thermal, power_system, model_run).lit
    assert all(np.all(fraction == 1) for fraction in lit.values())
    shaded = power_system.model_copy(
        update={"self_shadowing": SelfShadowing(enabled=True, points=128)}
    )
    powers = surface_powers(thermal, shaded, model_run)
    # the spider and the secondary mirror stand on the aperture
    sunny = (powers.sun_cosines["aperture"] > 0) & (model_run.light > 0)
    assert sunny.any()
    assert np.all(powers.lit["aperture"][sunny] < 1)
    assert np.all(powers.lit["aperture"][~sunny] == 1)


# ---------------------------------------------------------------- the checks


def write_payload(tmp_path, consumption, edit) -> PowerConsumption:
    """The payload's consumption file with its lines changed by `edit`."""
    source = consumption["payload"].source_file
    lines = edit(source.read_text().splitlines())
    path = tmp_path / "payload_consumption.csv"
    path.write_text("\n".join(lines) + "\n")
    return PowerConsumption.from_csv(path)


def test_the_payload_file_needs_the_thermal_column(
    tmp_path, thermal, consumption, model_run
):
    bare = write_payload(
        tmp_path,
        consumption,
        lambda lines: [line.rsplit(",", 1)[0] for line in lines],
    )
    with pytest.raises(ValueError, match="has no 'thermal' column"):
        check_files(thermal, bare, payload_pieces(model_run))


def test_every_payload_row_needs_a_thermal_value(
    tmp_path, thermal, consumption, model_run
):
    blank = write_payload(
        tmp_path,
        consumption,
        lambda lines: [*lines[:2], lines[2].rsplit(",", 1)[0] + ",", *lines[3:]],
    )
    with pytest.raises(
        ValueError, match="no 'thermal' value for the rows \\['mass_memory'\\]"
    ):
        check_files(thermal, blank, payload_pieces(model_run))


def test_a_flow_by_mode_needs_every_mode_of_the_run(thermal, consumption, model_run):
    text = thermal.source_text
    assert text is not None
    partial = PayloadThermal.from_yaml_text(
        text.replace("{idle: 0 W, imaging: 0 W, downlink: -5 W}", "{idle: 0 W}")
    )
    with pytest.raises(
        ValueError,
        match="'x-band rf' has no power for the payload's modes \\['imaging'\\]",
    ):
        check_files(partial, consumption["payload"], payload_pieces(model_run))


def test_the_payload_file_needs_a_column_for_each_mode_of_the_run(
    tmp_path, thermal, consumption, model_run
):
    renamed = write_payload(
        tmp_path,
        consumption,
        lambda lines: [lines[0].replace("imaging", "science"), *lines[1:]],
    )
    with pytest.raises(
        ValueError, match="no column for the payload's modes \\['imaging'\\]"
    ):
        check_files(thermal, renamed, payload_pieces(model_run))


# ---------------------------------------------------------------- the account


def test_the_terms_add_up_to_the_net_at_each_step(thermal_run):
    total = sum(thermal_run.terms[term].to_value(u.W) for term in TERMS)
    np.testing.assert_allclose(thermal_run.net.to_value(u.W), total)
    assert set(thermal_run.terms) == set(TERMS)


def test_the_modes_give_the_dissipation_and_the_heaters_without_margins(thermal_run):
    # idle: the mass memory's 10 W and the video unit's 5 W; imaging adds the
    # focal plane and more of each. The heater row is 22.1 W in idle and 0 W in
    # imaging and downlink.
    assert thermal_run.mode_watts["idle"] == {
        "dissipation": 15.0,
        "heaters": 22.1,
        "heat flows": -3.0,
    }
    assert thermal_run.mode_watts["imaging"]["dissipation"] == 115.0
    table = thermal_run.mode_table.set_index("payload mode")
    assert table.loc["idle", "dissipation [W]"] == pytest.approx(15)
    assert table.loc["imaging", "heaters [W]"] == pytest.approx(0)


def test_the_sums_agree_with_each_other(thermal_run, model_run):
    total = thermal_run.running_energy[-1].to_value(u.W * u.h)
    assert thermal_run.mode_table["net [Wh]"].sum() == pytest.approx(total)
    assert thermal_run.activity_table["net [Wh]"].sum() == pytest.approx(total)
    length = run_seconds(model_run)[-1] / 60
    assert thermal_run.mode_table["time [min]"].sum() == pytest.approx(length)
    assert thermal_run.activity_table["time [min]"].sum() == pytest.approx(length)
    orbit = thermal_run.orbit_table
    assert len(orbit) == 1
    assert orbit.loc[0, "net [Wh]"] == pytest.approx(total, rel=1e-3)


def test_the_net_energy_is_the_running_energy_at_the_end(thermal_run, model_run):
    seconds = run_seconds(model_run)
    energies = thermal_run.energies(0.0, float(seconds[-1]))
    assert sum(energies.values()) / 3600 == pytest.approx(
        thermal_run.running_energy[-1].to_value(u.W * u.h)
    )
    # the emission is steady, so its energy is its power times the time
    emitted = sum(thermal_run.surfaces.emitted.values())
    assert energies["emitted"] == pytest.approx(emitted * seconds[-1])


def test_a_mode_balancing_heater_power_brings_its_net_to_zero(
    tmp_path, thermal, consumption, power_system, model_run, thermal_run
):
    table = thermal_run.mode_table.set_index("payload mode")
    assert table.loc["imaging", "net [W]"] > table.loc["imaging", "heaters [W]"]
    assert table.loc["imaging", "balancing heater [W]"] == 0
    balancing = table.loc["idle", "balancing heater [W]"]
    assert balancing > 0
    balanced = write_payload(
        tmp_path,
        consumption,
        lambda lines: [
            line.replace("22.1 W,0 W,0 W", f"{balancing} W,0 W,0 W") for line in lines
        ],
    )
    again = run_thermal(
        thermal, balanced, power_system, model_run, thermal_run.surfaces
    ).mode_table.set_index("payload mode")
    assert again.loc["idle", "net [W]"] == pytest.approx(0, abs=1e-9)
    assert again.loc["idle", "balancing heater [W]"] == pytest.approx(balancing)


def test_the_surfaces_heat_must_come_from_the_same_run(
    thermal, consumption, power_system, thermal_run, data_dir
):
    other = run_scenario(Scenario.from_yaml_file(data_dir / "scenario.yaml"))
    with pytest.raises(ValueError, match="same scenario run"):
        run_thermal(
            thermal, consumption["payload"], power_system, other, thermal_run.surfaces
        )


def test_an_activity_takes_the_slew_into_it(
    thermal, consumption, power_system, data_dir
):
    text = (data_dir / "scenario.yaml").read_text() + (
        "slew: {max_rate: 0.7 deg/s, max_acceleration: 0.08 deg/s2, settling_time: 20 s}\n"
    )
    run = run_scenario(Scenario.from_yaml_text(text, base_dir=data_dir))
    account = run_thermal(thermal, consumption["payload"], power_system, run)
    slew = run.slews[0]
    title = run.occurrences[slew.into].activity.title
    starts = [start for start, _ in account.activity_spans[title]]
    seconds = (slew.start - run.times[0]).to_value(u.s)
    assert min(abs(start - seconds) for start in starts) < 1e-6
    table = account.activity_table
    assert table["time [min]"].sum() == pytest.approx(run_seconds(run)[-1] / 60)
    titles = [occurrence.activity.title for occurrence in run.occurrences]
    assert list(table["occurrences"]) == [
        titles.count(title) for title in table["activity"]
    ]


def test_the_surface_table_gives_each_surface(thermal_run):
    table = thermal_run.surface_table.set_index("surface")
    assert list(table.index) == ["radiator", "aperture"]
    assert table.loc["radiator", "part"] == "Radiator"
    assert table.loc["aperture", "fixed"]
    radiator = table.loc["radiator"]
    assert (
        0
        <= radiator["lowest sun angle [deg]"]
        <= radiator["highest sun angle [deg]"]
        <= 180
    )
    assert radiator["peak sun [W]"] >= radiator["mean sun [W]"] >= 0
    # the aperture faces nadir, and the radiator the horizon, in nadir pointing
    assert 0 < radiator["mean view factor"] < table.loc["aperture", "mean view factor"]
    assert radiator["in sun [min]"] > 0
    assert radiator["emitted [W]"] < 0


# ---------------------------------------------------------- equilibrium ΔT


def surfaces_file(lines: str) -> PayloadThermal:
    """A thermal file with the surfaces given, typed in."""
    return PayloadThermal.from_yaml_text("surfaces:\n" + lines)


def emission(thermal: PayloadThermal) -> dict[str, float]:
    """Each surface's emission at its design temperature, in W."""
    return {
        name: -float(
            (s.emissivity * STEFAN_BOLTZMANN * s.area * s.temperature**4).to_value(u.W)
        )
        for name, s in thermal.surfaces.items()
    }


def test_one_floating_surface_balances_at_the_closed_form():
    thermal = surfaces_file(
        "  r: {normal: +x, area: 0.5 m2, absorptance: 0.2, emissivity: 0.8, "
        "temperature: 290 K}\n"
    )
    emitted = emission(thermal)
    sigma = STEFAN_BOLTZMANN.to_value(u.W / u.m**2 / u.K**4)
    for heat_in in (50.0, -emitted["r"], 300.0):
        dt, reason = equilibrium_dt(thermal, emitted, heat_in)
        assert reason == ""
        assert dt == pytest.approx(
            (heat_in / (0.8 * sigma * 0.5)) ** 0.25 - 290, abs=1e-6
        )
    assert equilibrium_dt(thermal, emitted, -emitted["r"])[0] == pytest.approx(
        0, abs=1e-6
    )


def test_a_fixed_surface_keeps_its_emission():
    thermal = surfaces_file(
        "  r: {normal: +x, area: 0.5 m2, absorptance: 0.2, emissivity: 0.8, "
        "temperature: 290 K}\n"
        "  a: {normal: +z, area: 0.1 m2, absorptance: 0.9, emissivity: 0.9, "
        "temperature: 293 K, fixed_temperature: true}\n"
    )
    emitted = emission(thermal)
    sigma = STEFAN_BOLTZMANN.to_value(u.W / u.m**2 / u.K**4)
    heat_in = 200.0
    dt, _ = equilibrium_dt(thermal, emitted, heat_in)
    left = heat_in + emitted["a"]
    assert dt == pytest.approx((left / (0.8 * sigma * 0.5)) ** 0.25 - 290, abs=1e-6)


def test_two_floating_surfaces_move_by_the_same_dt():
    thermal = surfaces_file(
        "  cold: {normal: +x, area: 0.5 m2, absorptance: 0.2, emissivity: 0.8, "
        "temperature: 250 K}\n"
        "  warm: {normal: -x, area: 0.2 m2, absorptance: 0.2, emissivity: 0.9, "
        "temperature: 300 K}\n"
    )
    emitted = emission(thermal)
    sigma = STEFAN_BOLTZMANN.to_value(u.W / u.m**2 / u.K**4)
    dt, _ = equilibrium_dt(thermal, emitted, 150.0)
    assert dt is not None
    out = sigma * (0.8 * 0.5 * (250 + dt) ** 4 + 0.9 * 0.2 * (300 + dt) ** 4)
    assert out == pytest.approx(150.0, rel=1e-9)


def test_no_dt_when_every_surface_is_fixed():
    thermal = surfaces_file(
        "  a: {normal: +z, area: 0.1 m2, absorptance: 0.9, emissivity: 0.9, "
        "temperature: 293 K, fixed_temperature: true}\n"
    )
    dt, reason = equilibrium_dt(thermal, emission(thermal), 100.0)
    assert dt is None
    assert "fixed temperature" in reason


def test_no_dt_when_more_heat_leaves_than_comes_in():
    thermal = surfaces_file(
        "  r: {normal: +x, area: 0.5 m2, absorptance: 0.2, emissivity: 0.8, "
        "temperature: 290 K}\n"
        "  a: {normal: +z, area: 0.1 m2, absorptance: 0.9, emissivity: 0.9, "
        "temperature: 293 K, fixed_temperature: true}\n"
    )
    emitted = emission(thermal)
    for heat_in in (-10.0, -emitted["a"]):
        dt, reason = equilibrium_dt(thermal, emitted, heat_in)
        assert dt is None
        assert "no temperature balances it" in reason


def test_the_tables_give_the_dt_or_why_not(thermal_run):
    for table in (
        thermal_run.activity_table,
        thermal_run.mode_table,
        thermal_run.orbit_table,
    ):
        assert table["ΔT [K]"].notna().all()
        assert (table["ΔT note"] == "").all()
