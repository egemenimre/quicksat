# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The power system file, `power_system.yaml`: the solar panels, the battery and the power
conditioning.

Each panel names a part of the 3D model, or gives a normal and an area. The losses sit
in three places, so none counts twice: `loss_factor` to the array's output, the
conditioning beyond it, and the fixed overheads as loads.
`docs/power/power_generation_ref.ipynb` and `docs/explanations/power_model.md` explain
the file and the model.

"""

from typing import Annotated, ClassVar

import numpy as np
from astropy.units import Quantity
from pydantic import (
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
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
    UnitFractionQty,
    YamlFile,
    without_comments,
)

DEFAULT_POINTS = 512
"""The sample points on each panel for the self-shadowing, if the file gives none."""

AXES = ("+x", "-x", "+y", "-y", "+z", "-z")
"""The signed body axes that a normal can be written as."""


def _read_normal(value) -> tuple[float, float, float] | None:
    """
    A panel's normal as a unit vector, from a signed body axis or three numbers, or
    None, refusing three zeros.
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


class FlatItem(Commented):
    """
    A flat item on the spacecraft, such as a solar panel or a thermal surface: a part of
    the 3D model, or a normal and an area.

    An item from the model turns with any articulation above it, and can be shaded. A
    typed-in item stays fixed, is never shaded and shades nothing.

    Parameters
    ----------
    part : str, optional
        The model's node that holds the item, whose triangles all face one way
    normal : tuple of float, optional
        The direction it faces in body axes, a signed axis or three numbers
    area : Quantity, optional
        Its area, positive
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    kind: ClassVar[str] = "item"
    """What the item is, for the error messages."""

    part_hint: ClassVar[str] = "the name of its part in the 3D model"
    """What the part holds, for the error messages."""

    part: str | None = None
    normal: Annotated[
        tuple[float, float, float] | None, BeforeValidator(_read_normal)
    ] = None
    area: AreaQty | None = None

    @model_validator(mode="after")
    def _one_kind(self):
        """Checks the item is either a part, or a normal and an area."""
        typed = (self.normal is not None, self.area is not None)
        if self.part is not None:
            if any(typed):
                raise ValueError(
                    f"a {self.kind} gives either part, or normal and area, not "
                    "both: the part gives its own normal and area"
                )
            if not self.part.strip():
                raise ValueError("part must not be empty")
        elif not all(typed):
            raise ValueError(
                f"a {self.kind} needs either part, {self.part_hint}, or both "
                "normal and area"
            )
        elif self.area is not None and self.area.value == 0:
            raise ValueError("area must be above zero")
        return self

    @property
    def from_model(self) -> bool:
        """Whether the item names a part of the 3D model."""
        return self.part is not None


class Panel(FlatItem):
    """
    A solar panel: a part of the 3D model, or a normal and an area, as a `FlatItem`.

    Parameters
    ----------
    part : str, optional
        The model's node that holds the cells
    normal : tuple of float, optional
        The direction the cells face in body axes
    area : Quantity, optional
        The panel's area, positive
    fill_ratio : Quantity
        The share of the area the cells cover
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    kind: ClassVar[str] = "panel"
    part_hint: ClassVar[str] = "the name of its cells in the 3D model"

    fill_ratio: UnitFractionQty


class SelfShadowing(Commented):
    """
    The switch for the self-shadowing, and how finely it samples each panel.

    Parameters
    ----------
    enabled : bool
        Whether the model's parts may shade the panels
    points : int, optional
        The sample points on each panel, by default 512
    comments : str, optional
        The user's notes, which quicksat does not read
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
        The energy when new and full, such as `1024 W h`
    capacity_factor : Quantity
        The share left after fade, in the year being sized
    max_depth_of_discharge : Quantity
        The deepest it may go, as a share of what it holds
    initial_charge : Quantity, optional
        The charge at the run's start, by default full
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    capacity: EnergyQty
    capacity_factor: UnitFractionQty
    max_depth_of_discharge: UnitFractionQty
    initial_charge: UnitFractionQty = Q_(100, "%")

    @field_validator("capacity")
    @classmethod
    def _positive(cls, value: Quantity) -> Quantity:
        """Checks the capacity is above zero."""
        if value.value == 0:
            raise ValueError("capacity must be above zero")
        return value

    @property
    def usable(self) -> Quantity:
        """
        The energy the battery holds when full in the year being sized: the capacity
        times its factor, in W h.
        """
        return (self.capacity * self.capacity_factor).to(u.W * u.h)


class Conditioning(Commented):
    """
    The power conditioning's efficiencies, one for each path the energy takes.

    For a bus fed straight from the battery, give the cells' own efficiencies.

    Parameters
    ----------
    array_regulator : Quantity
        From the array to the bus
    battery_charge : Quantity
        From the bus into the battery
    battery_discharge : Quantity
        From the battery to the bus
    distribution : Quantity
        From the bus to the loads
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    array_regulator: UnitFractionQty
    battery_charge: UnitFractionQty
    battery_discharge: UnitFractionQty
    distribution: UnitFractionQty


class PowerSystem(YamlFile):
    """
    The power system file: the panels, the battery and the conditioning.

    The generation needs only the panels. The power budget also needs the rest.

    Parameters
    ----------
    cell_efficiency : Quantity
        The cells' efficiency, at their rated temperature
    loss_factor : Quantity
        The share of the power left after every loss up to the array's output
    panels : dict of str to Panel
        The panels, by any names, at least one
    self_shadowing : SelfShadowing, optional
        Whether the 3D model shades the panels, by default off
    battery : Battery, optional
        The battery
    conditioning : Conditioning, optional
        The conditioning's efficiencies
    system_margin : Quantity, optional
        The margin on all the loads together, such as `5 %`
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    cell_efficiency: UnitFractionQty
    loss_factor: UnitFractionQty
    panels: Annotated[dict[str, Panel], BeforeValidator(without_comments)]
    self_shadowing: SelfShadowing | None = None
    battery: Battery | None = None
    conditioning: Conditioning | None = None
    system_margin: FractionQty | None = None

    @property
    def shading(self) -> bool:
        """Whether the self-shadowing is on."""
        return self.self_shadowing is not None and self.self_shadowing.enabled

    @field_validator("panels")
    @classmethod
    def _name_panels(cls, panels: dict[str, Panel]) -> dict[str, Panel]:
        """Checks there is a panel, and no name is empty."""
        if not panels:
            raise ValueError("panels must define at least one panel")
        if any(not str(name).strip() for name in panels):
            raise ValueError("a panel's name must not be empty")
        return panels
