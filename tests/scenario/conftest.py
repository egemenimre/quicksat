"""Fixtures for the scenario tests.

The tests read their inputs from `tests/scenario/data/`, not from
`sample/scenario/data/`. The sample changes with its notebook, and these files
change only with the tests that read them:

- `scenario.yaml` uses every kind of trigger, and every status is `ok` except
  the last activity's, which is cut at the end.
- `problems.yaml` makes each problem happen once: an activity outside its
  constraint, a negative duration, and an event that never comes.

`slew_run` is `scenario.yaml` again, with slews at the sizing sample's rate and
acceleration.

The runs take about a second each, so each is made once per session. matplotlib
draws without a display, so the plots can be tested anywhere.
"""

from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg")

from quicksat.scenario.config import Scenario  # noqa: E402
from quicksat.scenario.run import ScenarioRun, run_scenario  # noqa: E402


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


@pytest.fixture(scope="session")
def problem_run(data_dir) -> ScenarioRun:
    """Two orbits of `problems.yaml`, in which each problem happens once.

    Returns
    -------
    ScenarioRun
        The run
    """
    return run_scenario(Scenario.from_yaml_file(data_dir / "problems.yaml"))
