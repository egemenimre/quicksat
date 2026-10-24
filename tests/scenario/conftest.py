"""Fixtures for the scenario tests.

The tests read their inputs from `tests/scenario/data/`, not from
`sample/scenario/data/`. The sample changes with its notebook, and these files
change only with the tests that read them:

- `scenario.yaml` uses every kind of trigger, and every status is `ok` except
  the last activity's, which is cut at the end.
- `problems.yaml` makes each problem happen once: an activity outside its
  constraint, a negative duration, and an event that never comes.
- `relays.tle` is a copy of `docs/scenario/data/relays.tle`, ten relays in
  one file. The editor tests read it as a satellite target's file.

`slew_run` is `scenario.yaml` again, with slews at the sizing sample's rate and
acceleration. `articulated_run` adds the 3D model and two wings to it.
`slow_run` has slews too slow for nadir, so some must start before the slew
before them.
`once_run` runs the list of `once_text` once, as the Activity Designer does:
the wings, and slews whose rate limit nadir passes.

The runs take about a second each, so each is made once per session. matplotlib
draws without a display, so the plots can be tested anywhere.
"""

from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg")

from quicksat.scenario.config import Scenario  # noqa: E402
from quicksat.scenario.run import ScenarioRun, run_scenario  # noqa: E402


def both(mode: str) -> dict[str, str]:
    """An activity's modes, written as the file writes them, with the payload and
    the platform in the same mode."""
    return {"payload_mode": mode, "platform_mode": mode}


@pytest.fixture(scope="session")
def data_dir() -> Path:
    """The directory holding the scenario test data.

    Returns
    -------
    Path
        Absolute path to `tests/scenario/data`, independent of the working directory.
    """
    return Path(__file__).parent / "data"


@pytest.fixture(scope="session")
def run(data_dir) -> ScenarioRun:
    """Three orbits of `scenario.yaml`, in which every trigger kind appears.

    Returns
    -------
    ScenarioRun
        The run
    """
    return run_scenario(Scenario.from_yaml_file(data_dir / "scenario.yaml"))


SLEW = (
    "slew: {max_rate: 0.7 deg/s, max_acceleration: 0.08 deg/s2, settling_time: 20 s}\n"
)
"""The slew block added to `scenario.yaml` for `slew_run`."""


@pytest.fixture(scope="session")
def slew_run(data_dir) -> ScenarioRun:
    """Three orbits of `scenario.yaml`, turning between attitudes in slews.

    Returns
    -------
    ScenarioRun
        The run
    """
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
    """Three orbits of `scenario.yaml`, with slews and two articulations.

    `wing +y` tracks the sun and parks in `downlink`. `wing -y` turns about `-y`
    within a range, so the sign and the clamp are both tested. Its name has a
    space and a sign, so the name of its attitude file is tested too.

    Returns
    -------
    ScenarioRun
        The run
    """
    text = ARTICULATED_MODEL + (data_dir / "scenario.yaml").read_text() + SLEW
    return run_scenario(Scenario.from_yaml_text(text, base_dir=data_dir))


@pytest.fixture(scope="session")
def problem_run(data_dir) -> ScenarioRun:
    """Two orbits of `problems.yaml`, in which each problem happens once.

    Returns
    -------
    ScenarioRun
        The run
    """
    return run_scenario(Scenario.from_yaml_file(data_dir / "problems.yaml"))


SLOW = (
    "slew: {max_rate: 0.05 deg/s, max_acceleration: 0.08 deg/s2, settling_time: 20 s}\n"
)
"""A slew block whose rate limit nadir passes, at about the orbit's 0.063 deg/s,
so that there are turn rate warnings."""


@pytest.fixture(scope="session")
def slow_run(data_dir) -> ScenarioRun:
    """Three orbits of `scenario.yaml`, with slews too slow for nadir.

    Some activities are shorter than the slews around them, so some slews must
    start before the slew before them.

    Returns
    -------
    ScenarioRun
        The run
    """
    text = (data_dir / "scenario.yaml").read_text() + SLOW
    return run_scenario(Scenario.from_yaml_text(text, data_dir))


@pytest.fixture(scope="session")
def once_text(data_dir) -> str:
    """`scenario.yaml` with the two wings, and slews that nadir turns too fast for.

    Returns
    -------
    str
        The scenario file's text
    """
    return ARTICULATED_MODEL + (data_dir / "scenario.yaml").read_text() + SLOW


@pytest.fixture(scope="session")
def once_run(once_text, data_dir) -> ScenarioRun:
    """One pass of the list of `once_text`, read and run as the designer does.

    Returns
    -------
    ScenarioRun
        The run, unplanned after the list's last activity
    """
    scenario = Scenario.from_yaml_text(once_text, data_dir, designer=True)
    return run_scenario(scenario, repeat=False)
