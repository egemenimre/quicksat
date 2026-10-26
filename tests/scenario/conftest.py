"""
Fixtures for the scenario tests, from `tests/scenario/data/`, which change only with the
tests.

- `scenario.yaml` uses every kind of trigger, and every status is `ok` but the last
  activity's, cut at the end.
- `problems.yaml` makes each problem happen once.
- `relays.tle` is a copy of `docs/scenario/data/relays.tle`, ten relays in one file.

`slew_run` adds slews at the sizing sample's limits, and `articulated_run` the 3D model
and two wings. `slow_run` has slews too slow for nadir, and `once_run` runs its list
once, as the Activity Designer does. Each run is made once per session, and matplotlib
draws without a display.
"""

from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg")

from quicksat.scenario.config import Scenario  # noqa: E402
from quicksat.scenario.run import ScenarioRun, run_scenario  # noqa: E402


def both(mode: str) -> dict[str, str]:
    """
    An activity's modes as the file writes them, with the payload and the platform in
    the same mode.
    """
    return {"payload_mode": mode, "platform_mode": mode}


@pytest.fixture(scope="session")
def data_dir() -> Path:
    """The scenario test data's folder, from this file."""
    return Path(__file__).parent / "data"


@pytest.fixture(scope="session")
def run(data_dir) -> ScenarioRun:
    """Three orbits of `scenario.yaml`, with every trigger kind."""
    return run_scenario(Scenario.from_yaml_file(data_dir / "scenario.yaml"))


SLEW = (
    "slew: {max_rate: 0.7 deg/s, max_acceleration: 0.08 deg/s2, settling_time: 20 s}\n"
)
"""The slew block added to `scenario.yaml` for `slew_run`."""


@pytest.fixture(scope="session")
def slew_run(data_dir) -> ScenarioRun:
    """Three orbits of `scenario.yaml`, with slews between the attitudes."""
    text = (data_dir / "scenario.yaml").read_text() + SLEW
    return run_scenario(Scenario.from_yaml_text(text, base_dir=data_dir))


ARTICULATED_MODEL = """3d_model:
  file: spacecraft.glb
  articulations:
    wing +y: {part: Wing +y, axis: +y, point: [-z, sun], park: {downlink: 45 deg}}
    wing -y: {part: Wing -y, axis: -y, point: [-z, sun], range: [-30 deg, 60 deg]}
"""
"""The model block added to `scenario.yaml` for `articulated_run`."""


@pytest.fixture(scope="session")
def articulated_run(data_dir) -> ScenarioRun:
    """
    Three orbits of `scenario.yaml`, with slews and two wings: `wing +y` tracks the sun
    and parks in `downlink`, and `wing -y` turns about `-y` within a range.
    """
    text = ARTICULATED_MODEL + (data_dir / "scenario.yaml").read_text() + SLEW
    return run_scenario(Scenario.from_yaml_text(text, base_dir=data_dir))


@pytest.fixture(scope="session")
def problem_run(data_dir) -> ScenarioRun:
    """Two orbits of `problems.yaml`, in which each problem happens once."""
    return run_scenario(Scenario.from_yaml_file(data_dir / "problems.yaml"))


SLOW = (
    "slew: {max_rate: 0.05 deg/s, max_acceleration: 0.08 deg/s2, settling_time: 20 s}\n"
)
"""A slew block whose rate limit nadir passes, at about the orbit's 0.063 deg/s, for the
turn rate warnings."""


@pytest.fixture(scope="session")
def slow_run(data_dir) -> ScenarioRun:
    """
    Three orbits of `scenario.yaml`, with slews so slow that some must start before the
    slew before them.
    """
    text = (data_dir / "scenario.yaml").read_text() + SLOW
    return run_scenario(Scenario.from_yaml_text(text, data_dir))


@pytest.fixture(scope="session")
def once_text(data_dir) -> str:
    """`scenario.yaml` with the two wings, and slews that nadir turns too fast for."""
    return ARTICULATED_MODEL + (data_dir / "scenario.yaml").read_text() + SLOW


@pytest.fixture(scope="session")
def once_run(once_text, data_dir) -> ScenarioRun:
    """
    One pass of the list of `once_text`, as the designer runs it, unplanned after its
    last activity.
    """
    scenario = Scenario.from_yaml_text(once_text, data_dir, designer=True)
    return run_scenario(scenario, repeat=False)
