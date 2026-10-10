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

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from quicksat import u
from quicksat.dataflow.report import tabulate
from quicksat.utils.mission import Mission
from quicksat.utils.parser_helpers import DataRateQty, FractionQty, TimeQty


class Generation(BaseModel):
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
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

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


class Downlink(BaseModel):
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
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    rate: DataRateQty
    contacts_per_day: float = Field(ge=0)
    avg_contact_duration: TimeQty


class Storage(BaseModel):
    """
    The onboard memory sizing case.

    Parameters
    ----------
    orbits_without_contact : float
        Orbits the spacecraft may go without a usable pass
    """

    orbits_without_contact: float = Field(ge=0)


class DataFlowModel(BaseModel):
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
        The onboard memory sizing case
    """

    generation: Generation
    downlink: Downlink
    storage: Storage

    @classmethod
    def from_yaml_file(cls, file_path: str | Path) -> "DataFlowModel":
        """
        Initialise the dataflow model from a YAML file.

        Parameters
        ----------
        file_path : str | Path
            Filepath containing the payload dataflow model (YAML)

        Returns
        -------
        model : DataFlowModel
            Dataflow model from the input data
        """
        if not file_path:
            raise ValueError("Path is None. No file to be found.")
        elif not os.path.isfile(file_path):
            raise FileNotFoundError(f"File does not exist: {file_path}")
        else:
            with open(file_path, "rt") as file:
                return cls.from_yaml_text(file.read())

    @classmethod
    def from_yaml_text(cls, yaml_text: str) -> "DataFlowModel":
        """
        Initialise the dataflow model from YAML text.

        Parameters
        ----------
        yaml_text : str
            Text containing the payload dataflow model (YAML)

        Returns
        -------
        model : DataFlowModel
            Dataflow model from the input data
        """
        if not yaml_text:
            raise ValueError("Text content is None.")
        return cls(**yaml.safe_load(yaml_text))


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
    """

    def __init__(self, model: DataFlowModel, mission: Mission):
        self.model = model
        self.mission = mission

    @classmethod
    def from_yaml_file(
        cls, model_path: str | Path, mission_path: str | Path
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

        Returns
        -------
        budget : DataBudget
            The assembled budget
        """
        return cls(
            DataFlowModel.from_yaml_file(Path(model_path)),
            Mission.from_yaml_file(Path(mission_path)),
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

    def storage_required(self, orbits_without_contact: float | None = None):
        """
        Onboard storage needed to cover a run of orbits with no usable contact.

        This sizes the memory for the gap between passes, not for a backlog that grows
        from day to day. The two are the same only while the budget closes. With a
        negative margin, the backlog never clears, and the storage needed grows without
        limit.

        Parameters
        ----------
        orbits_without_contact : float, optional
            Orbits to cover. Defaults to the value in the dataflow model

        Returns
        -------
        volume : Quantity
        """
        if orbits_without_contact is None:
            orbits_without_contact = self.model.storage.orbits_without_contact
        return (self.generated_per_orbit * orbits_without_contact).to("GB")

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
