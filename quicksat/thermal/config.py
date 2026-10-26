# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The payload's optional thermal file, `payload_thermal.yaml`: its surfaces, its heat
flows and the Earth's values.

A surface is defined as a solar panel is. A heat flow is positive into the payload, as
one power or one per payload mode. `docs/power/payload_thermal_ref.ipynb`, under "The
thermal file", explains the file.

"""

from typing import Annotated, ClassVar

from astropy.units import Quantity
from pydantic import (
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    StrictBool,
    Tag,
    field_validator,
)

from quicksat import Q_, u
from quicksat.power.config import FlatItem
from quicksat.utils.parser_helpers import (
    Commented,
    FractionQty,
    TemperatureQty,
    UnitFractionQty,
    YamlFile,
    non_negative_quantity,
    signed_quantity,
    without_comments,
)

SignedPowerQty = signed_quantity(u.W, "power")
"""Annotated Quantity type for a power of either sign, such as `-3 W`."""

FluxQty = non_negative_quantity(u.W / u.m**2, "flux")
"""Annotated Quantity type for a flux, such as the Earth's `237 W/m2`."""

HeatFlow = Annotated[
    Annotated[SignedPowerQty, Tag("power")]
    | Annotated[dict[str, SignedPowerQty], Tag("by mode")],
    Discriminator(lambda value: "by mode" if isinstance(value, dict) else "power"),
]
"""A heat flow: a mapping is read as the powers by mode, and anything else as one
power."""

DEFAULT_ALBEDO = Q_(0.30, "")
"""The Earth's albedo if the file gives none, averaged over the globe."""

DEFAULT_INFRARED = Q_(237, "W/m2")
"""The Earth's infrared flux if the file gives none, averaged over the globe."""


class Surface(FlatItem):
    """
    A surface of the payload that absorbs and radiates heat, such as a radiator or an
    aperture, defined as a solar panel is.

    Parameters
    ----------
    part : str, optional
        The model's node that holds the surface
    normal : tuple of float, optional
        The direction it faces in body axes
    area : Quantity, optional
        Its area, positive
    absorptance : Quantity
        α, the share of sunlight it absorbs, for the year being sized
    emissivity : Quantity
        ε, the share of a black body's infrared it emits and absorbs
    temperature : Quantity
        Its design temperature, preferably in kelvin
    fixed_temperature : bool, optional
        Whether something else keeps it constant, for the equilibrium ΔT
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    kind: ClassVar[str] = "surface"
    part_hint: ClassVar[str] = "the name of its face in the 3D model"

    absorptance: UnitFractionQty
    emissivity: UnitFractionQty
    temperature: TemperatureQty
    fixed_temperature: StrictBool = False


class Earth(Commented):
    """
    The Earth's two values: the sunlight it reflects and its own infrared.

    Parameters
    ----------
    albedo : Quantity, optional
        The share of sunlight reflected, by default 0.30
    infrared : Quantity, optional
        The infrared flux, by default `237 W/m2`
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    albedo: FractionQty = DEFAULT_ALBEDO
    infrared: FluxQty = DEFAULT_INFRARED

    @field_validator("albedo")
    @classmethod
    def _albedo(cls, value: Quantity) -> Quantity:
        """Checks that the albedo is from 0 to 1."""
        if not 0 <= float(value.to(u.dimensionless_unscaled).value) <= 1:
            raise ValueError(f"albedo must be from 0 to 1 (100 %), got {value}")
        return value


class PayloadThermal(YamlFile):
    """
    The payload's thermal file: the surfaces, the heat flows and the Earth.

    Parameters
    ----------
    surfaces : dict of str to Surface
        The surfaces, by any names, at least one
    heat_flows : dict of str to Quantity or dict, optional
        The powers into the payload elsewhere than a surface, by any names: one power,
        or one per payload mode
    earth : Earth, optional
        The Earth's albedo and infrared
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    surfaces: Annotated[dict[str, Surface], BeforeValidator(without_comments)]
    heat_flows: Annotated[dict[str, HeatFlow], BeforeValidator(without_comments)] = (
        Field(default_factory=dict)
    )
    earth: Earth = Field(default_factory=Earth)

    @field_validator("surfaces")
    @classmethod
    def _name_surfaces(cls, surfaces: dict[str, Surface]) -> dict[str, Surface]:
        """Checks there is a surface, and no name is empty."""
        if not surfaces:
            raise ValueError("surfaces must define at least one surface")
        if any(not str(name).strip() for name in surfaces):
            raise ValueError("a surface's name must not be empty")
        return surfaces

    @field_validator("heat_flows")
    @classmethod
    def _name_flows(cls, flows: dict[str, HeatFlow]) -> dict[str, HeatFlow]:
        """Checks no name is empty, and a flow by mode has a mode."""
        for name, flow in flows.items():
            if not str(name).strip():
                raise ValueError("a heat flow's name must not be empty")
            if isinstance(flow, dict):
                if not flow:
                    raise ValueError(
                        f"heat flow '{name}' gives no mode: give one power, or a "
                        "power for each payload mode"
                    )
                if any(not str(mode).strip() for mode in flow):
                    raise ValueError(f"heat flow '{name}' has a mode with no name")
        return flows

    @property
    def flows_by_mode(self) -> dict[str, dict[str, Quantity]]:
        """
        The heat flows given by mode: each flow's power by mode, by the flow's name.
        """
        return {
            name: flow
            for name, flow in self.heat_flows.items()
            if isinstance(flow, dict)
        }

    def flow_watts(self, mode: str) -> dict[str, float]:
        """
        Each heat flow's power in one payload mode.

        Parameters
        ----------
        mode : str
            The payload mode, which each flow by mode must have

        Returns
        -------
        watts : dict of str to float
            In W, positive into the payload, by name
        """
        return {
            name: float((flow[mode] if isinstance(flow, dict) else flow).to_value(u.W))
            for name, flow in self.heat_flows.items()
        }
