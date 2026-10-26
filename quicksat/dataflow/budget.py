# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Data and downlink budget: what the payload generates against what the link sends.

Unlike the mass budget, there is nothing here to sum. This is one chain of calculations,
from a few assumptions to a single comparison. So the input is a config file rather than
a CSV. There is no `resolve()` and there are no `by_*` views, because there are no rows
to filter or group.

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
        Instrument output before compression
    compression_ratio : float
        Divides the raw rate. 1 means no compression
    duty_cycle : Quantity
        Fraction of each orbit spent generating
    comments : str, optional
        The user's notes on the block. quicksat does not read them
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    raw_datarate: DataRateQty
    compression_ratio: float = Field(ge=1)
    duty_cycle: FractionQty

    @field_validator("duty_cycle")
    @classmethod
    def _at_most_all_of_the_orbit(cls, value):
        """A payload cannot collect for more than the whole orbit."""
        if value > 1:
            raise ValueError(f"Duty cycle must not exceed 100%, got '{value}'")
        return value


class Downlink(Commented):
    """
    What the link sends.

    It is given per day rather than per orbit. Contacts are counted over the ground
    station's day, and the count does not divide evenly into orbits either.

    Parameters
    ----------
    rate : Quantity
        Achieved throughput, not the symbol rate
    contacts_per_day : float
        Usable ground contacts in a day, from Mission Analysis
    avg_contact_duration : Quantity
        How long an average contact lasts
    comments : str, optional
        The user's notes on the block. quicksat does not read them
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    rate: DataRateQty
    contacts_per_day: float = Field(ge=0)
    avg_contact_duration: TimeQty


class Storage(Commented):
    """
    The onboard memory.

    How long the memory must hold the data is a requirement, not a property of
    the memory. So it is in the requirements file, as `orbits_without_downlink`.

    Parameters
    ----------
    capacity : Quantity
        The mass memory's usable capacity, after any space kept for other data
    comments : str, optional
        The user's notes on the block. quicksat does not read them
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    capacity: DataVolumeQty


class DataFlowModel(YamlFile):
    """
    The payload dataflow model: generation, downlink and storage.

    They are in one file, because the budget exists to compare the first two. Splitting
    the two sides of a comparison across files would make it harder to read, not easier.

    Parameters
    ----------
    generation : Generation
        What the payload produces
    downlink : Downlink
        What the link sends
    storage : Storage
        The onboard memory
    comments : str, optional
        The user's notes on the block. quicksat does not read them
    """

    model_config = ConfigDict(extra="forbid")

    generation: Generation
    downlink: Downlink
    storage: Storage


class DataBudget:
    """
    A data and downlink budget for one satellite.

    Generation is counted per orbit, because the payload collects data for a fraction of
    each orbit. Downlink is counted per day, because the contacts follow the ground
    station's day. Each side is computed over its own period. The two are compared per
    day, and the margin is taken there.

    Parameters
    ----------
    model : DataFlowModel
        The payload dataflow model
    mission : Mission
        The shared mission, for the period and the orbits in a day
    requirements : Requirements, optional
        The shared requirements, for the orbits without downlink that the memory
        must cover. Without them, the storage needs its orbits passed in, and
        there is no storage check
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
        Build a data budget from a payload dataflow model and a mission file.

        Where several budgets share one mission, load it once with
        `Mission.from_yaml_file` and use the constructor instead.

        Parameters
        ----------
        model_path : str | Path
            Filepath of the payload dataflow model (YAML)
        mission_path : str | Path
            Filepath of the shared mission (YAML)
        requirements_path : str | Path, optional
            Filepath of the shared requirements (YAML)

        Returns
        -------
        budget : DataBudget
            The assembled budget
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
        """
        Generated data rate, after compression.

        Returns
        -------
        rate : Quantity
        """
        generation = self.model.generation
        return (generation.raw_datarate / generation.compression_ratio).to("Mbit/s")

    @property
    def generation_duration(self):
        """
        Time spent generating, per orbit.

        Returns
        -------
        duration : Quantity
        """
        duty = self.model.generation.duty_cycle.to(u.dimensionless_unscaled)
        return (duty * self.mission.period).to("s")

    @property
    def generated_per_orbit(self):
        """
        Data generated in one orbit.

        Returns
        -------
        volume : Quantity
        """
        return (self.effective_datarate * self.generation_duration).to("GB")

    @property
    def generated_per_day(self):
        """
        Data generated in one day.

        Returns
        -------
        volume : Quantity
        """
        return (self.generated_per_orbit * self.mission.orbits_per_day).to("GB")

    @property
    def contact_per_day(self):
        """
        Total ground contact time in one day.

        Returns
        -------
        duration : Quantity
        """
        downlink = self.model.downlink
        return (downlink.contacts_per_day * downlink.avg_contact_duration).to("min")

    @property
    def downlinked_per_day(self):
        """
        Data sent by the downlink in one day.

        Returns
        -------
        volume : Quantity
        """
        return (self.model.downlink.rate * self.contact_per_day).to("GB")

    @property
    def downlinked_per_orbit(self):
        """
        Data sent by the downlink, averaged over one orbit.

        Derived from the daily figure, since contacts are counted per day.

        Returns
        -------
        volume : Quantity
        """
        return (self.downlinked_per_day / self.mission.orbits_per_day).to("GB")

    @property
    def margin(self):
        """
        How much more the link sends than the payload generates.

        A positive margin means that each day's data is sent down the same day. A
        negative margin means data builds up until some is deleted or a pass is added.
        The margin is a ratio, so the byte convention does not affect it.

        Returns
        -------
        margin : Quantity
            Dimensionless, so 0.12 is a 12% margin
        """
        return (self.downlinked_per_day / self.generated_per_day - 1).to(
            u.dimensionless_unscaled
        )

    def storage_required(self, orbits_without_downlink: float | None = None):
        """
        Onboard storage needed to cover a run of orbits with no payload data downlink.

        This sizes the memory for the gap between passes, not for a backlog that grows
        from day to day. The two are the same only while the budget closes. With a
        negative margin, the backlog never clears, and the storage needed grows without
        limit.

        Parameters
        ----------
        orbits_without_downlink : float, optional
            Orbits to cover. Defaults to the requirement's

        Returns
        -------
        volume : Quantity

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
        The orbits without downlink that the requirements ask the memory to
        cover.

        Returns
        -------
        orbits : float or None
            None when there is no data requirement
        """
        if self.requirements is None or self.requirements.data is None:
            return None
        return self.requirements.data.orbits_without_downlink

    def checks(self) -> list[Check]:
        """
        The budget's checks: the downlink against the data generated, and the
        mass memory against the storage required.

        The downlink check needs no requirement: the link must send each day's
        data. The storage check needs the data requirement, and is left out
        without it.

        Returns
        -------
        checks : list of Check
            The downlink check, then the storage check
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
            One row per quantity, rendered for reading. The frame is available as
            `.data`, where every row has the `row_type` that the display hides.
        """
        return tabulate(self)
