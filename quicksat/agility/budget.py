# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Attitude agility: how long a rest-to-rest slew takes, and whether it fits.

`docs/sizing/agility_ref.ipynb` explains the model and its limits.

"""

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

import numpy as np
import pandas as pd
from pydantic import BeforeValidator, ConfigDict, Field, model_validator

from quicksat import Q_, u
from quicksat.agility.report import tabulate

if TYPE_CHECKING:  # type annotations only, so quicksat.mass stays unimported
    from quicksat.mass.budget import MassBudget
    from quicksat.utils.requirements import Requirements
from quicksat.utils.checks import Check
from quicksat.utils.mission import Mission
from quicksat.utils.parser_helpers import (
    AngleQty,
    Commented,
    FractionQty,
    InertiaQty,
    LengthQty,
    MomentumQty,
    TimeQty,
    TorqueQty,
    YamlFile,
    without_comments,
)

DEFAULT_SLEW_ANGLES = (5, 10, 15, 20, 40, 45, 60, 90)
"""Slew angles reported by `slew_table` when none are given, in degrees."""


class Axis(str, Enum):
    """The axis a slew is flown about."""

    ROLL = "roll"
    """Across track. Inertia from the cross-track and nadir dimensions."""

    PITCH = "pitch"
    """Along track. Inertia from the along-track and nadir dimensions."""


class Profile(str, Enum):
    """Which limit applies, and so which rate profile the slew follows."""

    TRIANGULAR = "triangular"
    """Torque limited: accelerate to the midpoint, decelerate to the end."""

    TRAPEZOIDAL = "trapezoidal"
    """Momentum limited: the wheels saturate and the slew coasts at max rate."""


class Body(Commented):
    """
    A bus envelope, as a uniform rectangular box.

    Parameters
    ----------
    x : Quantity
        Along-track dimension
    y : Quantity
        Cross-track dimension
    z : Quantity
        Nadir dimension
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    x: LengthQty
    y: LengthQty
    z: LengthQty


class PerAxis(Commented):
    """
    A value for each slew axis.

    Parameters
    ----------
    roll, pitch : Quantity or float
        The figure about each axis
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    roll: InertiaQty | Annotated[float, Field(ge=1.0)]
    pitch: InertiaQty | Annotated[float, Field(ge=1.0)]


class InertiaCase(Commented):
    """
    One spacecraft's mass properties: an envelope estimate or a stated inertia.

    A case is one or the other, never both. `docs/sizing/agility_ref.ipynb`, under
    "Inertia cases", says why.

    Parameters
    ----------
    body : Body, optional
        The bus envelope, for an envelope case
    appendage_factor : PerAxis, optional
        The inertia factor of the arrays, radiator and booms, for an envelope case
    propellant : Quantity
        The share of the propellant on board, at which the mass budget is read
    inertia : PerAxis, optional
        The stated inertia, for a stated case
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    body: Body | None = None
    appendage_factor: PerAxis | None = None
    propellant: FractionQty = Q_(100, "percent")
    inertia: PerAxis | None = None

    @property
    def is_envelope(self) -> bool:
        """Whether this case estimates its inertia from a box."""
        return self.inertia is None

    @model_validator(mode="after")
    def _exactly_one_shape(self):
        """
        Checks the case is an envelope or a stated inertia, naming the keys it found.
        """
        envelope = [
            name
            for name in ("body", "appendage_factor")
            if getattr(self, name) is not None
        ]
        if self.inertia is not None:
            if envelope:
                raise ValueError(
                    f"A case states an inertia and also carries {envelope}. It has "
                    "to be one or the other: a stated inertia does not follow the "
                    "mass, so the two would disagree the moment the mass moved"
                )
        elif len(envelope) < 2:
            missing = sorted({"body", "appendage_factor"} - set(envelope))
            raise ValueError(
                f"A case needs either a stated 'inertia' or a full envelope. "
                f"Found {envelope or 'nothing'}, missing {missing}"
            )
        return self


class WheelAssembly(Commented):
    """
    A pyramid of reaction wheels, symmetry axis along yaw.

    Parameters
    ----------
    count : int
        Number of wheels
    elevation : Quantity
        Each wheel's angle above the pyramid's base plane
    momentum, torque : Quantity
        Each wheel's nameplate momentum and torque
    momentum_use_factor, torque_derating : Quantity
        The share of each that slewing may use
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    count: Annotated[int, Field(ge=1)]
    elevation: AngleQty
    momentum: MomentumQty
    torque: TorqueQty
    momentum_use_factor: FractionQty
    torque_derating: FractionQty


class AgilityConfig(YamlFile):
    """
    The agility inputs. The time a slew may take is in the requirements file.

    Parameters
    ----------
    selected_case : str
        The inertia case that the budget sizes and checks
    inertia_cases : dict of str to InertiaCase
        The mass properties cases, by any names
    wheels : WheelAssembly
        The wheel pyramid and its use policy
    settling_time : Quantity
        The time after a slew before the payload can work
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    selected_case: str
    inertia_cases: Annotated[dict[str, InertiaCase], BeforeValidator(without_comments)]
    wheels: WheelAssembly
    settling_time: TimeQty

    @model_validator(mode="after")
    def _selects_a_listed_case(self):
        """Checks that the selected case is one of the inertia cases."""
        if self.selected_case not in self.inertia_cases:
            known = ", ".join(sorted(self.inertia_cases)) or "none"
            raise ValueError(
                f"The selected case '{self.selected_case}' is not one of the "
                f"inertia cases. Configured: {known}"
            )
        return self

    def for_case(self, name: str) -> InertiaCase:
        """
        Mass properties for one named case.

        Parameters
        ----------
        name : str
            The case's name

        Returns
        -------
        case : InertiaCase
            The case

        Raises
        ------
        KeyError
            If no case has that name
        """
        case = self.inertia_cases.get(name)
        if case is None:
            known = ", ".join(sorted(self.inertia_cases)) or "none"
            raise KeyError(f"No inertia case named '{name}'. Configured: {known}")
        return case


class AgilityBudget:
    """
    Rest-to-rest slew performance about one axis, for one mass properties case.

    Each capability takes `degraded`: one failed wheel halves the momentum and the
    torque about the axis.

    Parameters
    ----------
    config : AgilityConfig
        The agility inputs
    mission : Mission
        The shared mission, for the ground track speed
    axis : Axis
        The axis of the slews
    case : str, optional
        The inertia case, by default the config's selected case
    mass_budget : MassBudget, optional
        The source of an envelope case's mass
    mass : Quantity, optional
        A mass that overrides the mass budget's
    requirements : Requirements, optional
        The shared requirements, for the checks

    Raises
    ------
    KeyError
        If no case has that name
    """

    def __init__(
        self,
        config: AgilityConfig,
        mission: Mission,
        axis: Axis,
        case: str | None = None,
        mass_budget: "MassBudget | None" = None,
        mass=None,
        requirements: "Requirements | None" = None,
    ):
        self.config = config
        self.mission = mission
        self.axis = Axis(axis)
        self.case_name = config.selected_case if case is None else case
        self.case = config.for_case(self.case_name)
        self.mass_budget = mass_budget
        self._mass = mass
        self.requirements = requirements

    @property
    def mass(self):
        """
        The mass an envelope case slews: the `mass` passed in, or the mass budget's in
        orbit at the case's propellant share, in kg.
        """
        if self._mass is not None:
            return self._mass
        if self.mass_budget is not None:
            return self.mass_budget.in_orbit_mass(
                propellant=self.case.propellant.to_value("percent")
            )
        raise ValueError(
            f"Case '{self.case_name}' estimates its inertia from an envelope, so "
            "it needs a mass. Attach a mass_budget, pass mass=, or use a case "
            "that states its inertia outright."
        )

    @classmethod
    def from_yaml_file(
        cls,
        config_path: str | Path,
        mission_path: str | Path,
        axis: Axis,
        case: str | None = None,
        mass_budget: "MassBudget | None" = None,
        mass=None,
        requirements_path: str | Path | None = None,
    ) -> "AgilityBudget":
        """
        Build an agility budget from its files.

        Parameters
        ----------
        config_path, mission_path : str or Path
            The agility config and the shared mission
        axis : Axis
            The axis of the slews
        case : str, optional
            The inertia case, by default the config's selected case
        mass_budget : MassBudget, optional
            The source of an envelope case's mass
        mass : Quantity, optional
            A mass that overrides the mass budget's
        requirements_path : str or Path, optional
            The shared requirements

        Returns
        -------
        budget : AgilityBudget
            The budget
        """
        # here, as the requirements module reads `Axis` from this one
        from quicksat.utils.requirements import Requirements

        return cls(
            AgilityConfig.from_yaml_file(Path(config_path)),
            Mission.from_yaml_file(Path(mission_path)),
            axis,
            case,
            mass_budget,
            mass,
            Requirements.from_yaml_file(Path(requirements_path))
            if requirements_path is not None
            else None,
        )

    @property
    def inertia(self):
        """
        The moment of inertia about the axis: stated, or a uniform box times the
        appendage factor, in kg*m**2.
        """
        if not self.case.is_envelope:
            return cast(Q_, getattr(self.case.inertia, self.axis.value)).to("kg * m**2")
        body = cast(Body, self.case.body)
        first, second = (body.y, body.x)[self.axis is Axis.PITCH], body.z
        factor = getattr(self.case.appendage_factor, self.axis.value)
        box = self.mass / 12 * (first**2 + second**2)
        return (box * factor).to("kg * m**2")

    @property
    def projection(self):
        """
        The share of a wheel's capability about roll or pitch: cos(elevation) cos(45°).
        """
        elevation = self.config.wheels.elevation
        return (np.cos(elevation) * np.cos(Q_(45, "deg"))).to(u.dimensionless_unscaled)

    @property
    def usable_momentum_per_wheel(self):
        """The momentum one wheel gives after the use factor, in N*m*s."""
        wheels = self.config.wheels
        return (wheels.momentum * wheels.momentum_use_factor).to("N * m * s")

    @property
    def usable_torque_per_wheel(self):
        """The torque one wheel gives after derating, in N*m."""
        wheels = self.config.wheels
        return (wheels.torque * wheels.torque_derating).to("N * m")

    @property
    def yaw_momentum(self):
        """The momentum about yaw, the pyramid's weak axis, in N*m*s."""
        wheels = self.config.wheels
        return (
            wheels.count * self.usable_momentum_per_wheel * np.sin(wheels.elevation)
        ).to("N * m * s")

    def _wheels_used(self, degraded: bool) -> float:
        """The wheel count, halved when one has failed."""
        return self.config.wheels.count / 2 if degraded else self.config.wheels.count

    def axis_momentum(self, degraded: bool = False):
        """
        Momentum the wheels can apply about the axis.

        Parameters
        ----------
        degraded : bool
            One wheel failed

        Returns
        -------
        momentum : Quantity
            In N*m*s
        """
        used = self._wheels_used(degraded)
        return (used * self.usable_momentum_per_wheel * self.projection).to("N * m * s")

    def axis_torque(self, degraded: bool = False):
        """
        Torque the wheels can apply about the axis.

        Parameters
        ----------
        degraded : bool
            One wheel failed

        Returns
        -------
        torque : Quantity
            In N*m
        """
        used = self._wheels_used(degraded)
        return (used * self.usable_torque_per_wheel * self.projection).to("N * m")

    def max_rate(self, degraded: bool = False):
        """
        Fastest the spacecraft can turn before the wheels saturate.

        Parameters
        ----------
        degraded : bool
            One wheel failed

        Returns
        -------
        rate : Quantity
            In deg/s
        """
        # momentum over inertia is 1/s. The radian is implied, and astropy needs it
        # stated
        return (self.axis_momentum(degraded) / self.inertia).to(
            "deg / s", equivalencies=u.dimensionless_angles()
        )

    def max_acceleration(self, degraded: bool = False):
        """
        Angular acceleration the available torque produces.

        Parameters
        ----------
        degraded : bool
            One wheel failed

        Returns
        -------
        acceleration : Quantity
            In deg/s**2
        """
        return (self.axis_torque(degraded) / self.inertia).to(
            "deg / s**2", equivalencies=u.dimensionless_angles()
        )

    def crossover_angle(self, degraded: bool = False):
        """
        Slew angle at which torque limiting gives way to momentum limiting.

        Parameters
        ----------
        degraded : bool
            One wheel failed

        Returns
        -------
        angle : Quantity
            In degrees
        """
        rate, acceleration = self.max_rate(degraded), self.max_acceleration(degraded)
        return (rate**2 / acceleration).to("deg")

    def profile(self, angle, degraded: bool = False) -> Profile:
        """
        Which limit applies to a slew of this size.

        Parameters
        ----------
        angle : Quantity
            Slew angle
        degraded : bool
            One wheel failed

        Returns
        -------
        profile : Profile
            `TRIANGULAR` when torque limited, `TRAPEZOIDAL` when momentum limited
        """
        if angle <= self.crossover_angle(degraded):
            return Profile.TRIANGULAR
        return Profile.TRAPEZOIDAL

    def slew_time(self, angle, degraded: bool = False):
        """
        Rest-to-rest slew time, settling excluded.

        Parameters
        ----------
        angle : Quantity
            Slew angle
        degraded : bool
            One wheel failed

        Returns
        -------
        time : Quantity
            In seconds
        """
        rate, acceleration = self.max_rate(degraded), self.max_acceleration(degraded)
        if self.profile(angle, degraded) is Profile.TRIANGULAR:
            return (2 * (angle / acceleration) ** 0.5).to("s")
        return (angle / rate + rate / acceleration).to("s")

    def peak_rate(self, angle, degraded: bool = False):
        """
        Fastest the spacecraft turns during the slew.

        Parameters
        ----------
        angle : Quantity
            Slew angle
        degraded : bool
            One wheel failed

        Returns
        -------
        rate : Quantity
            In deg/s
        """
        if self.profile(angle, degraded) is Profile.TRIANGULAR:
            return ((angle * self.max_acceleration(degraded)) ** 0.5).to("deg / s")
        return self.max_rate(degraded)

    def momentum_used(self, angle, degraded: bool = False):
        """
        Fraction of the axis momentum that the slew uses: 1 past the crossover.

        Parameters
        ----------
        angle : Quantity
            Slew angle
        degraded : bool
            One wheel failed

        Returns
        -------
        fraction : Quantity
            Dimensionless
        """
        peak = (self.inertia * self.peak_rate(angle, degraded)).to(
            "N * m * s", equivalencies=u.dimensionless_angles()
        )
        return (peak / self.axis_momentum(degraded)).to(u.dimensionless_unscaled)

    def slew_table(self, angles=None, degraded: bool = False) -> pd.DataFrame:
        """
        One row per slew angle, with the time, profile and momentum used.

        Parameters
        ----------
        angles : iterable of Quantity, optional
            Slew angles. Defaults to `DEFAULT_SLEW_ANGLES`, in degrees
        degraded : bool
            One wheel failed

        Returns
        -------
        frame : pd.DataFrame
            Angles in degrees, times in seconds, rates in deg/s
        """
        if angles is None:
            angles = [Q_(value, "deg") for value in DEFAULT_SLEW_ANGLES]
        records = [
            {
                "angle": angle.to_value("deg"),
                "profile": self.profile(angle, degraded).value,
                "slew_time": self.slew_time(angle, degraded).to_value("s"),
                "total_time": self.total_time(angle, degraded).to_value("s"),
                "peak_rate": self.peak_rate(angle, degraded).to_value("deg / s"),
                "momentum_used": self.momentum_used(angle, degraded).to_value(
                    u.dimensionless_unscaled
                ),
            }
            for angle in angles
        ]
        return pd.DataFrame(records)

    def total_time(self, angle, degraded: bool = False):
        """
        Slew time plus the settling allowance, applied once at the end.

        Parameters
        ----------
        angle : Quantity
            Slew angle
        degraded : bool
            One wheel failed

        Returns
        -------
        time : Quantity
            In seconds
        """
        settling = self.config.settling_time
        return (self.slew_time(angle, degraded) + settling).to("s")

    def time_margin(self, angle, target_duration, degraded: bool = False):
        """
        The share of a target duration left over, against the time needed.

        Parameters
        ----------
        angle : Quantity
            Slew angle
        target_duration : Quantity
            The time allowed for the whole manoeuvre
        degraded : bool
            One wheel failed

        Returns
        -------
        margin : Quantity
            Dimensionless, negative when the slew does not fit
        """
        needed = self.total_time(angle, degraded)
        return ((target_duration - needed) / needed).to(u.dimensionless_unscaled)

    def achievable_angle(self, target_duration, degraded: bool = False):
        """
        The largest slew that fits the time allowed, settling included.

        Parameters
        ----------
        target_duration : Quantity
            The time allowed for the whole manoeuvre
        degraded : bool
            One wheel failed

        Returns
        -------
        angle : Quantity
            In degrees
        """
        slewing = target_duration - self.config.settling_time
        rate, acceleration = self.max_rate(degraded), self.max_acceleration(degraded)
        coasting = slewing - rate / acceleration
        if coasting <= Q_(0, "s"):
            return (acceleration * (slewing / 2) ** 2).to("deg")
        return (rate * coasting).to("deg")

    def ground_distance(self, time):
        """
        How far the ground track moves in a time, unimaged during a slew.

        Parameters
        ----------
        time : Quantity
            Duration

        Returns
        -------
        distance : Quantity
            In km
        """
        return (self.mission.ground_track_speed * time).to("km")

    def checks(self) -> list[Check]:
        """
        The checks: each slew that the requirements ask about this axis, against its
        time.

        Returns
        -------
        checks : list of Check
            Empty without agility requirements
        """
        if self.requirements is None or self.requirements.agility is None:
            return []
        return [
            Check(
                name,
                f"A {slew.angle.to_value('deg'):g}° {self.axis.value} slew within "
                f"{slew.duration.to_value('s'):g} s, settling included, for the "
                f"inertia case {self.case_name}",
                self.total_time(slew.angle).to("s"),
                slew.duration.to("s"),
                at_most=True,
            )
            for name, slew in self.requirements.agility.slews.items()
            if slew.axis == self.axis
        ]

    def tabulated_agility(
        self, angles=None, degraded: bool = False, target_duration=None
    ):
        """
        The slew table as a document.

        Parameters
        ----------
        angles : iterable of Quantity, optional
            Slew angles, by default `DEFAULT_SLEW_ANGLES`
        degraded : bool
            One wheel failed
        target_duration : Quantity, optional
            The time allowed, which adds whether each slew fits

        Returns
        -------
        report : Styler
            One row per slew angle
        """
        return tabulate(self.slew_table(angles, degraded), target_duration)
