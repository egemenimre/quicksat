# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The power system file: the solar panels, the battery and the power conditioning.

The file is `power_system.yaml`. Each panel either names a part of the scenario's
3D model, which gives its area and its normal, or gives a normal and an area
itself:

    cell_efficiency: 30 %
    loss_factor: 0.80
    panels:
      wing +y inner: {part: Wing +y inner cells, fill_ratio: 85 %}
      side +x: {normal: +x, area: 0.2 m2, fill_ratio: 80 %}
    self_shadowing: {enabled: true, points: 512}
    battery:
      capacity: 1024 W h
      capacity_factor: 0.80
      max_depth_of_discharge: 30 %
    conditioning:
      array_regulator: 0.96
      battery_charge: 0.95
      battery_discharge: 0.95
      distribution: 0.97
    system_margin: 5 %

The losses sit in three places, so that none is counted twice. `loss_factor`
takes every loss up to the array's output. The conditioning's efficiencies take
the energy from there to the loads and through the battery, each on its own path.
The fixed overheads, such as the power unit's own electronics, are loads in the
consumption files.

This module reads and checks the file on its own. The parts are checked against
the scenario's model when the generation is worked out, in
`quicksat.power.generation`.

"""

import os
from pathlib import Path
from typing import Annotated

import numpy as np
import yaml
from astropy.units import Quantity
from pydantic import (
    BeforeValidator,
    ConfigDict,
    Field,
    PrivateAttr,
    StrictBool,
    ValidationInfo,
    field_validator,
    model_validator,
)

from quicksat import Q_, u
from quicksat.orbit.attitude import axis_vector
from quicksat.utils.parser_helpers import (
    AreaQty,
    Commented,
    EnergyQty,
    FractionQty,
    without_comments,
)

DEFAULT_POINTS = 512
"""Sample points on each panel for the self-shadowing, if the file gives none.
In the prototype, 512 points kept the lit fraction within 0.012 of the exact one,
and the energy within 0.01%."""

AXES = ("+x", "-x", "+y", "-y", "+z", "-z")
"""The signed body axes that a normal can be written as."""


def _read_normal(value) -> tuple[float, float, float] | None:
    """
    A panel's normal as a unit vector, from a signed body axis or three numbers.

    Parameters
    ----------
    value : str, list or None
        A signed body axis such as `+x`, or three numbers in body axes, such as
        `[0, 1, -1]`, scaled here to unit length

    Returns
    -------
    normal : tuple of float or None
        The unit vector, or None if no normal is given

    Raises
    ------
    ValueError
        If the value is neither form, or is three zeros
    """
    if value is None:
        return None
    if isinstance(value, str):
        axis = value.strip()
        if axis not in AXES:
            raise ValueError(
                f"normal must be a signed body axis, one of {list(AXES)}, or three "
                f"numbers, got '{value}'"
            )
        x, y, z = axis_vector(axis)
        return (float(x), float(y), float(z))
    try:
        vector = np.array(value, dtype=float)
    except (TypeError, ValueError):
        vector = np.empty(0)
    if vector.shape != (3,) or not np.all(np.isfinite(vector)):
        raise ValueError(
            f"normal must be a signed body axis, such as +x, or three numbers, "
            f"got {value!r}"
        )
    length = float(np.linalg.norm(vector))
    if length == 0:
        raise ValueError("normal must not be three zeros")
    x, y, z = vector / length
    return (float(x), float(y), float(z))


def _check_unit_fraction(value: Quantity, name: str) -> Quantity:
    """
    Checks that a fraction is above 0 and at most 1.

    Parameters
    ----------
    value : Quantity
        The fraction, dimensionless
    name : str
        The field's name, for the error message

    Returns
    -------
    value : Quantity
        The fraction, unchanged

    Raises
    ------
    ValueError
        If the fraction is 0, or above 1
    """
    if not 0 < float(value.to(u.dimensionless_unscaled).value) <= 1:
        raise ValueError(f"{name} must be above 0 and at most 1 (100 %), got {value}")
    return value


class Panel(Commented):
    """
    A solar panel: a part of the 3D model, or a normal and an area.

    A panel from the model takes its area and its normal from the part's
    triangles. It turns with an articulation above it in the model, and it can
    be shaded by the rest of the model. A typed-in panel stays fixed in body
    axes. It is never shaded and shades nothing.

    Parameters
    ----------
    part : str, optional
        The name of the model's node that holds the cells. Its triangles must all
        face one way. Give either `part`, or both `normal` and `area`.
    normal : tuple of float, optional
        The direction the cells face, in body axes: a signed body axis such as
        `+x`, or three numbers, scaled to unit length
    area : Quantity, optional
        The panel's area, positive
    fill_ratio : Quantity
        The share of the area that the cells cover, above 0 and at most 1
    comments : str, optional
        Your own notes on this block. quicksat keeps them and does not read them.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    part: str | None = None
    normal: Annotated[
        tuple[float, float, float] | None, BeforeValidator(_read_normal)
    ] = None
    area: AreaQty | None = None
    fill_ratio: FractionQty

    @field_validator("fill_ratio")
    @classmethod
    def _fraction(cls, value: Quantity, info: ValidationInfo) -> Quantity:
        """Checks that the fill ratio is above 0 and at most 1."""
        return _check_unit_fraction(value, str(info.field_name))

    @model_validator(mode="after")
    def _one_kind(self):
        """Checks that the panel is either a part, or a normal and an area."""
        typed = (self.normal is not None, self.area is not None)
        if self.part is not None:
            if any(typed):
                raise ValueError(
                    "a panel gives either part, or normal and area, not both: the "
                    "part gives its own normal and area"
                )
            if not self.part.strip():
                raise ValueError("part must not be empty")
        elif not all(typed):
            raise ValueError(
                "a panel needs either part, the name of its cells in the 3D model, "
                "or both normal and area"
            )
        elif self.area is not None and self.area.value == 0:
            raise ValueError("area must be above zero")
        return self

    @property
    def from_model(self) -> bool:
        """
        Whether the panel is a part of the 3D model.

        Returns
        -------
        from_model : bool
            True for a panel that names a part, False for a typed-in one
        """
        return self.part is not None


class SelfShadowing(Commented):
    """
    The switch for the self-shadowing, and how finely it samples each panel.

    Parameters
    ----------
    enabled : bool
        Whether parts of the model may shade the panels. Required.
    points : int, optional
        Sample points on each panel, 512 by default. More points give a finer
        lit fraction, and take longer.
    comments : str, optional
        Your own notes on this block. quicksat keeps them and does not read them.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool
    points: int = Field(DEFAULT_POINTS, gt=0)


class Battery(Commented):
    """
    The battery: its size, how much of it is left, and how deep it may go.

    Parameters
    ----------
    capacity : Quantity
        The energy the battery holds when new and full, such as `1024 W h`.
        Positive.
    capacity_factor : Quantity
        The share of the capacity left in the year being sized, after fade, such
        as `0.80`. Above 0 and at most 1.
    max_depth_of_discharge : Quantity
        The deepest the battery may go, as a share of what it holds, such as
        `30 %`. The power budget checks that the charge never falls below 1 less
        this. Above 0 and at most 1.
    initial_charge : Quantity, optional
        The charge at the start of the run, as a share of what it holds. Full,
        `100 %`, by default.
    comments : str, optional
        Your own notes on this block. quicksat keeps them and does not read them.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    capacity: EnergyQty
    capacity_factor: FractionQty
    max_depth_of_discharge: FractionQty
    initial_charge: FractionQty = Q_(100, "%")

    @field_validator("capacity")
    @classmethod
    def _positive(cls, value: Quantity) -> Quantity:
        """Checks that the capacity is above zero."""
        if value.value == 0:
            raise ValueError("capacity must be above zero")
        return value

    @field_validator("capacity_factor", "max_depth_of_discharge", "initial_charge")
    @classmethod
    def _fraction(cls, value: Quantity, info: ValidationInfo) -> Quantity:
        """Checks that each share is in (0, 1]."""
        return _check_unit_fraction(value, str(info.field_name))

    @property
    def usable(self) -> Quantity:
        """
        The energy the battery holds when full, in the year being sized.

        Returns
        -------
        usable : Quantity
            The capacity times the capacity factor, in W h
        """
        return (self.capacity * self.capacity_factor).to(u.W * u.h)


class Conditioning(Commented):
    """
    The efficiencies of the power conditioning, one for each path energy takes.

    Each is above 0 and at most 1. For a bus fed straight from the battery, with
    no charge and discharge regulators, give the cells' own efficiencies.

    Parameters
    ----------
    array_regulator : Quantity
        From the array to the bus, through the array regulator, such as a
        maximum power point tracker
    battery_charge : Quantity
        From the bus into the battery: the charge regulator and the cells
    battery_discharge : Quantity
        From the battery to the bus: the discharge regulator and the cells
    distribution : Quantity
        From the bus to the loads: the switches, the fuses and the harness
    comments : str, optional
        Your own notes on this block. quicksat keeps them and does not read them.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    array_regulator: FractionQty
    battery_charge: FractionQty
    battery_discharge: FractionQty
    distribution: FractionQty

    @field_validator(
        "array_regulator", "battery_charge", "battery_discharge", "distribution"
    )
    @classmethod
    def _fraction(cls, value: Quantity, info: ValidationInfo) -> Quantity:
        """Checks that each efficiency is in (0, 1]."""
        return _check_unit_fraction(value, str(info.field_name))


class PowerSystem(Commented):
    """
    The power system file: the panels, the battery and the conditioning.

    The power of a panel is the solar flux × its area × its fill ratio × the cell
    efficiency × the loss factor × the cosine of the sun's angle to its normal.
    It is scaled by the light from the sun that the Earth does not hide, and by
    the panel's lit fraction when the self-shadowing is on. That is the power at
    the array's output. The conditioning's efficiencies take it from there to the
    loads and the battery.

    The generation needs only the panels. The power budget also needs the
    battery, the conditioning and the system margin.

    Parameters
    ----------
    cell_efficiency : Quantity
        The cells' efficiency, at their rated temperature. Above 0 and at most 1,
        such as `30 %` or `0.30`.
    loss_factor : Quantity
        Every loss up to the array's output, as the share of the power left: the
        cells' temperature, ageing, mismatch between cells, UV, and the array's
        own wiring, for the year being sized. Above 0 and at most 1, such as
        `0.80`.
    panels : dict of str to Panel
        The panels, each under a name of your choice. At least one.
    self_shadowing : SelfShadowing, optional
        Whether the 3D model shades the panels. Off without it.
    battery : Battery, optional
        The battery, for the power budget
    conditioning : Conditioning, optional
        The efficiencies of the power conditioning, for the power budget
    system_margin : Quantity, optional
        The margin on all the loads together, on top of each equipment's own,
        such as `5 %`. For the power budget.
    comments : str, optional
        Your own notes on the whole file. quicksat keeps them and does not read
        them. The section `panels` may hold its own `comments` too, so no panel
        may take that name.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    cell_efficiency: FractionQty
    loss_factor: FractionQty
    panels: Annotated[dict[str, Panel], BeforeValidator(without_comments)]
    self_shadowing: SelfShadowing | None = None
    battery: Battery | None = None
    conditioning: Conditioning | None = None
    system_margin: FractionQty | None = None

    _source_file: Path | None = PrivateAttr(None)
    _source_text: str | None = PrivateAttr(None)

    @property
    def source_file(self) -> Path | None:
        """
        The file the power system was read from.

        Returns
        -------
        path : Path or None
            None when it was read from text
        """
        return self._source_file

    @property
    def source_text(self) -> str | None:
        """
        The text the power system was read from, as written.

        Returns
        -------
        text : str or None
            None when it was built in code
        """
        return self._source_text

    @property
    def shading(self) -> bool:
        """
        Whether the self-shadowing is on.

        Returns
        -------
        shading : bool
        """
        return self.self_shadowing is not None and self.self_shadowing.enabled

    @field_validator("cell_efficiency", "loss_factor")
    @classmethod
    def _fraction(cls, value: Quantity, info: ValidationInfo) -> Quantity:
        """Checks that the efficiency and the loss factor are in (0, 1]."""
        return _check_unit_fraction(value, str(info.field_name))

    @field_validator("panels")
    @classmethod
    def _name_panels(cls, panels: dict[str, Panel]) -> dict[str, Panel]:
        """Checks that there is a panel, and that no name is empty."""
        if not panels:
            raise ValueError("panels must define at least one panel")
        if any(not str(name).strip() for name in panels):
            raise ValueError("a panel's name must not be empty")
        return panels

    @classmethod
    def from_yaml_file(cls, file_path: str | Path) -> "PowerSystem":
        """
        Initialise the power system from a YAML file.

        Parameters
        ----------
        file_path : str | Path
            Path to the YAML file

        Returns
        -------
        power_system : PowerSystem
            The power system from the file

        Raises
        ------
        FileNotFoundError
            If there is no such file
        """
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File does not exist: {file_path}")
        path = Path(file_path)
        power_system = cls.from_yaml_text(path.read_text())
        power_system._source_file = path
        return power_system

    @classmethod
    def from_yaml_text(cls, yaml_text: str) -> "PowerSystem":
        """
        Initialise the power system from YAML text.

        Parameters
        ----------
        yaml_text : str
            Text containing the power system (YAML)

        Returns
        -------
        power_system : PowerSystem
            The power system from the text

        Raises
        ------
        ValueError
            If the text is empty, or is not a mapping of keys to values
        """
        if not yaml_text:
            raise ValueError("Text content is None.")
        data = yaml.safe_load(yaml_text)
        if not isinstance(data, dict):
            raise ValueError("A power system file must be a mapping of keys to values.")
        power_system = cls.model_validate(data)
        power_system._source_text = yaml_text
        return power_system
