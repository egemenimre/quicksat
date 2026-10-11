"""Fixtures for the power tests.

The power tests read their inputs and reference results from
`tests/power/data/`. The directory is resolved from this file, so the suite
passes wherever pytest is invoked from.

- `scenario.yaml` and `power_generation.yaml` use the power sample's model, with
  turning wings, fixed deck cells and one typed-in panel, over one orbit.
- `short_run` is `scenario.yaml` cut to 30 min, shorter than one orbit.
- `six_faces_scenario.yaml` and `six_faces_generation.yaml` are the Orekit case:
  six typed-in 1 m2 faces in nadir pointing, for one day.

The runs take a few seconds each, so each is made once per session.
"""

import json
from pathlib import Path

import matplotlib
import numpy as np
import pytest

matplotlib.use("Agg")

from quicksat.power.config import PowerGeneration  # noqa: E402
from quicksat.power.generation import GenerationRun, run_generation  # noqa: E402
from quicksat.scenario.config import Scenario  # noqa: E402
from quicksat.scenario.run import ScenarioRun, run_scenario  # noqa: E402


@pytest.fixture(scope="session")
def data_dir() -> Path:
    """The directory holding the power test data.

    Returns
    -------
    Path
        Absolute path to `tests/power/data`, independent of the working directory.
    """
    return Path(__file__).parent / "data"


@pytest.fixture(scope="session")
def model_run(data_dir) -> ScenarioRun:
    """One orbit of `scenario.yaml`, with the 3D model and its turning wings.

    Returns
    -------
    ScenarioRun
        The run
    """
    return run_scenario(Scenario.from_yaml_file(data_dir / "scenario.yaml"))


@pytest.fixture(scope="session")
def generation(data_dir) -> PowerGeneration:
    """The panels of `power_generation.yaml`.

    Returns
    -------
    PowerGeneration
        The power generation file
    """
    return PowerGeneration.from_yaml_file(data_dir / "power_generation.yaml")


@pytest.fixture(scope="session")
def generation_run(generation, model_run) -> GenerationRun:
    """The generation of `power_generation.yaml` over `model_run`.

    Returns
    -------
    GenerationRun
        The generation
    """
    return run_generation(generation, model_run)


@pytest.fixture(scope="session")
def short_run(generation, data_dir) -> GenerationRun:
    """The generation over 30 min of `scenario.yaml`, less than one orbit.

    Returns
    -------
    GenerationRun
        The generation
    """
    text = (data_dir / "scenario.yaml").read_text().replace("1 orbit", "30 min")
    run = run_scenario(Scenario.from_yaml_text(text, base_dir=data_dir))
    return run_generation(generation, run)


@pytest.fixture(scope="session")
def six_faces_run(data_dir) -> GenerationRun:
    """The Orekit case: six 1 m2 faces in nadir pointing, for one day.

    Returns
    -------
    GenerationRun
        The generation
    """
    run = run_scenario(Scenario.from_yaml_file(data_dir / "six_faces_scenario.yaml"))
    faces = PowerGeneration.from_yaml_file(data_dir / "six_faces_generation.yaml")
    return run_generation(faces, run)


@pytest.fixture(scope="session")
def case(data_dir) -> dict:
    """The Orekit case's inputs and expected results, `scenario.json`.

    Returns
    -------
    dict
        The case
    """
    return json.loads((data_dir / "scenario.json").read_text())


@pytest.fixture(scope="session")
def reference(data_dir) -> dict[str, np.ndarray]:
    """Orekit's results for each sample of the case, `reference_orekit.npz`.

    Returns
    -------
    dict of str to ndarray
        The arrays, by name
    """
    with np.load(data_dir / "reference_orekit.npz") as data:
        return {name: data[name] for name in data.files}
