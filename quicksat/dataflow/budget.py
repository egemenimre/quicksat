# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Data and downlink budget: what the payload generates against what the link sends.

`docs/sizing/data_budget_ref.ipynb` explains the chain and its limits.

"""

from pathlib import Path

from pydantic import ConfigDict, Field, field_validator

from quicksat import u
from quicksat.dataflow.report import tabulate
from quicksat.utils.checks import Check
from quicksat.utils.mission import Mission
from quicksat.utils.parser_helpers import (
    Commented,
    DataRateQty,
    DataVolumeQty,
    FractionQty,
    TimeQty,
    YamlFile,
)
from quicksat.utils.requirements import Requirements


class Generation(Commented):
    """
    What the payload produces.

    Parameters
    ----------
    raw_datarate : Quantity
        The instrument's output before compression
    compression_ratio : float
        Divides the raw rate, 1 for none
    duty_cycle : Quantity
        The share of each orbit spent generating
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    raw_datarate: DataRateQty
    compression_ratio: float = Field(ge=1)
    duty_cycle: FractionQty

    @field_validator("duty_cycle")
    @classmethod
    def _at_most_all_of_the_orbit(cls, value):
        """Checks the duty cycle is at most the whole orbit."""
        if value > 1:
            raise ValueError(f"Duty cycle must not exceed 100%, got '{value}'")
        return value


class Downlink(Commented):
    """
    What the link sends, counted per day as the contacts are.

    Parameters
    ----------
    rate : Quantity
        The achieved throughput, not the symbol rate
    contacts_per_day : float
        Usable ground contacts in a day
    avg_contact_duration : Quantity
        An average contact's length
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    rate: DataRateQty
    contacts_per_day: float = Field(ge=0)
    avg_contact_duration: TimeQty


class Storage(Commented):
    """
    The onboard memory. The orbits it must cover are in the requirements file.

    Parameters
    ----------
    capacity : Quantity
        The mass memory's usable capacity
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    capacity: DataVolumeQty


class DataFlowModel(YamlFile):
    """
    The payload dataflow model: generation, downlink and storage.

    Parameters
    ----------
    generation : Generation
        What the payload produces
    downlink : Downlink
        What the link sends
    storage : Storage
        The onboard memory
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    model_config = ConfigDict(extra="forbid")

    generation: Generation
    downlink: Downlink
    storage: Storage


class DataBudget:
    """
    A data and downlink budget for one satellite, compared per day.

    Parameters
    ----------
    model : DataFlowModel
        The payload dataflow model
    mission : Mission
        The shared mission, for the period and the orbits in a day
    requirements : Requirements, optional
        The shared requirements, for the orbits the memory must cover and its check
    """

    def __init__(
        self,
        model: DataFlowModel,
        mission: Mission,
        requirements: Requirements | None = None,
    ):
        self.model = model
        self.mission = mission
        self.requirements = requirements

    @classmethod
    def from_yaml_file(
        cls,
        model_path: str | Path,
        mission_path: str | Path,
        requirements_path: str | Path | None = None,
    ) -> "DataBudget":
        """
        Build a data budget from its files.

        Parameters
        ----------
        model_path, mission_path : str or Path
            The payload dataflow model and the shared mission
        requirements_path : str or Path, optional
            The shared requirements

        Returns
        -------
        budget : DataBudget
            The budget
        """
        return cls(
            DataFlowModel.from_yaml_file(Path(model_path)),
            Mission.from_yaml_file(Path(mission_path)),
            Requirements.from_yaml_file(Path(requirements_path))
            if requirements_path is not None
            else None,
        )

    @property
    def effective_datarate(self):
        """The data rate after compression, in Mbit/s."""
        generation = self.model.generation
        return (generation.raw_datarate / generation.compression_ratio).to("Mbit/s")

    @property
    def generation_duration(self):
        """The time spent generating in one orbit, in s."""
        duty = self.model.generation.duty_cycle.to(u.dimensionless_unscaled)
        return (duty * self.mission.period).to("s")

    @property
    def generated_per_orbit(self):
        """The data generated in one orbit, in GB."""
        return (self.effective_datarate * self.generation_duration).to("GB")

    @property
    def generated_per_day(self):
        """The data generated in one day, in GB."""
        return (self.generated_per_orbit * self.mission.orbits_per_day).to("GB")

    @property
    def contact_per_day(self):
        """The ground contact time in one day, in min."""
        downlink = self.model.downlink
        return (downlink.contacts_per_day * downlink.avg_contact_duration).to("min")

    @property
    def downlinked_per_day(self):
        """The data the downlink sends in one day, in GB."""
        return (self.model.downlink.rate * self.contact_per_day).to("GB")

    @property
    def downlinked_per_orbit(self):
        """The data the downlink sends in a day, over the orbits in it, in GB."""
        return (self.downlinked_per_day / self.mission.orbits_per_day).to("GB")

    @property
    def margin(self):
        """
        How much more the link sends than the payload generates, as a share: 0.12 is 12
        %.
        """
        return (self.downlinked_per_day / self.generated_per_day - 1).to(
            u.dimensionless_unscaled
        )

    def storage_required(self, orbits_without_downlink: float | None = None):
        """
        The memory needed to hold the data of some orbits with no downlink.

        It sizes for the gap between passes. With a negative margin, the backlog grows
        without limit.

        Parameters
        ----------
        orbits_without_downlink : float, optional
            The orbits to cover, by default the requirement's

        Returns
        -------
        volume : Quantity
            In GB

        Raises
        ------
        ValueError
            If no orbits are given and there is no data requirement
        """
        if orbits_without_downlink is None:
            orbits_without_downlink = self.required_orbits
            if orbits_without_downlink is None:
                raise ValueError(
                    "No orbits without downlink given, and no data requirement. Pass "
                    "the orbits, or build the data budget with requirements=... to "
                    "take them from there."
                )
        return (self.generated_per_orbit * orbits_without_downlink).to("GB")

    @property
    def required_orbits(self) -> float | None:
        """
        The orbits without downlink that the requirements ask the memory to cover, or
        None.
        """
        if self.requirements is None or self.requirements.data is None:
            return None
        return self.requirements.data.orbits_without_downlink

    def checks(self) -> list[Check]:
        """
        The checks: the downlink against the data generated, then the memory against the
        storage required.

        The storage check needs the data requirement.

        Returns
        -------
        checks : list of Check
            One or two checks
        """
        checks = [
            Check(
                "downlink",
                "The downlink sends the data generated each day",
                self.downlinked_per_day,
                self.generated_per_day,
            )
        ]
        orbits = self.required_orbits
        if orbits is not None:
            checks.append(
                Check(
                    "storage",
                    f"The mass memory holds the data of {orbits:g} orbits "
                    "without downlink",
                    self.model.storage.capacity.to("GB"),
                    self.storage_required(),
                )
            )
        return checks

    def tabulated_data(self):
        """
        The budget as a document: every quantity, with the assumption behind it.

        Returns
        -------
        report : Styler
            One row per quantity, with the frame as `.data`
        """
        return tabulate(self)
