"""Fixtures for the power tests.

The power tests read their inputs and reference results from
`tests/power/data/`. The directory is resolved from this file, so the suite
passes wherever pytest is invoked from.

- `scenario.yaml` and `power_system.yaml` use the power sample's model, with
  turning wings, fixed deck cells and one typed-in panel, over one orbit.
- `payload_consumption.csv` and `platform_consumption.csv` are copies of the
  power sample's consumption files, and `payload_thermal.yaml` of its thermal
  file.
- `short_run` is `scenario.yaml` cut to 30 min, shorter than one orbit.
- `six_faces_scenario.yaml` and `six_faces_power_system.yaml` are the Orekit case:
  six typed-in 1 m2 faces in nadir pointing, for one day.

The runs take a few seconds each, so each is made once per session.
"""

import json
from pathlib import Path

import matplotlib
import numpy as np
import pytest

matplotlib.use("Agg")

from quicksat.power.budget import BudgetRun, run_budget  # noqa: E402
from quicksat.power.config import PowerSystem  # noqa: E402
from quicksat.power.consumption import (  # noqa: E402
    ConsumptionRun,
    PowerConsumption,
    run_consumption,
)
from quicksat.power.generation import GenerationRun, run_generation  # noqa: E402
from quicksat.scenario.config import Scenario  # noqa: E402
from quicksat.scenario.run import ScenarioRun, run_scenario  # noqa: E402
from quicksat.thermal.account import ThermalRun, run_thermal  # noqa: E402
from quicksat.thermal.config import PayloadThermal  # noqa: E402


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
def power_system(data_dir) -> PowerSystem:
    """The power system of `power_system.yaml`.

    Returns
    -------
    PowerSystem
        The power system file
    """
    return PowerSystem.from_yaml_file(data_dir / "power_system.yaml")


@pytest.fixture(scope="session")
def generation_run(power_system, model_run) -> GenerationRun:
    """The generation of `power_system.yaml` over `model_run`.

    Returns
    -------
    GenerationRun
        The generation
    """
    return run_generation(power_system, model_run)


@pytest.fixture(scope="session")
def short_run(power_system, data_dir) -> GenerationRun:
    """The generation over 30 min of `scenario.yaml`, less than one orbit.

    Returns
    -------
    GenerationRun
        The generation
    """
    text = (data_dir / "scenario.yaml").read_text().replace("1 orbit", "30 min")
    run = run_scenario(Scenario.from_yaml_text(text, base_dir=data_dir))
    return run_generation(power_system, run)


@pytest.fixture(scope="session")
def six_faces_run(data_dir) -> GenerationRun:
    """The Orekit case: six 1 m2 faces in nadir pointing, for one day.

    Returns
    -------
    GenerationRun
        The generation
    """
    run = run_scenario(Scenario.from_yaml_file(data_dir / "six_faces_scenario.yaml"))
    faces = PowerSystem.from_yaml_file(data_dir / "six_faces_power_system.yaml")
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


@pytest.fixture(scope="session")
def consumption(data_dir) -> dict[str, PowerConsumption]:
    """The loads of `payload_consumption.csv` and `platform_consumption.csv`.

    Returns
    -------
    dict of str to PowerConsumption
        The consumption files, by the group's name
    """
    return {
        group: PowerConsumption.from_csv(data_dir / f"{group}_consumption.csv")
        for group in ("payload", "platform")
    }


@pytest.fixture(scope="session")
def consumption_run(consumption, model_run) -> ConsumptionRun:
    """The loads of the two consumption files over `model_run`.

    Returns
    -------
    ConsumptionRun
        The loads
    """
    return run_consumption(consumption, model_run)


@pytest.fixture(scope="session")
def thermal(data_dir) -> PayloadThermal:
    """The payload's thermal file, `payload_thermal.yaml`.

    Returns
    -------
    PayloadThermal
        The thermal file
    """
    return PayloadThermal.from_yaml_file(data_dir / "payload_thermal.yaml")


@pytest.fixture(scope="session")
def thermal_run(thermal, consumption, power_system, model_run) -> ThermalRun:
    """The payload's heat account over `model_run`.

    Returns
    -------
    ThermalRun
        The account
    """
    return run_thermal(thermal, consumption["payload"], power_system, model_run)


@pytest.fixture(scope="session")
def budget(power_system, generation_run, consumption_run) -> BudgetRun:
    """The power budget of `power_system.yaml` over `model_run`.

    Returns
    -------
    BudgetRun
        The budget
    """
    return run_budget(power_system, generation_run, consumption_run)
