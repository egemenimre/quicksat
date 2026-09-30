# Decisions

The decisions that shaped quicksat, and why. A decision belongs here when
reversing it would cost real work, or when the reasoning is not recoverable
from the code — which is what separates this file from the module docstrings.

Newest first. When a decision replaces an earlier one, the earlier one is
folded into it rather than deleted, because knowing what was tried and why it
lost is most of the value.

---

## 8. Earth constants are astropy's defaults

**2026-09-30. Settled. Replaces WGS-84 and EGM96, which the project used from
the start.**

`R_EARTH` and `MU_EARTH` are now astropy's `R_earth` and `GM_earth`. By default
these are the IAU 2015 nominal values, 6378.1 km and 398600.4 km³/s². Before,
quicksat wrote out its own: the WGS-84 equatorial radius of 6378.137 km, and the
EGM96 measured GM of 398600.4418 km³/s². astropy is now the one source of
physical constants, as it already was for standard gravity.

The change is too small to matter for sizing. At 500 km, the orbital period
moves by 0.05 s and the velocity by 0.02 m/s. One test checked the orbit radius
to the metre, and it was updated. Every other figure in the tests, the README
and the notebooks is unchanged at the precision it is quoted to.

`MU_EARTH` is still a GM rather than G times a mass. GM is the measured
quantity, known to about nine significant figures. G is known to about five.
astropy works the same way: it derives its `M_earth` from GM and G.

---

## 7. Orbit, attitude and sun geometry with astropy, not orekit

**2026-09-30. Settled, after measurement.**

The power budget needs the angle between a solar panel normal and the sun,
which needs a trajectory, an attitude, and the sun. The candidates were astropy
and Orekit through one of its two Python wrappers.

**astropy.** Supplies three of the four pieces: the sun (`get_sun`), the
inertial and Earth-fixed frames (`GCRS`, `ITRS`, `TEME`), and a frame graph
that composes rotations. It supplies **no propagator and no attitude model**,
so those are ours — about 120 lines, since `LVLH` and `Body` can be written as
real `BaseCoordinateFrame` subclasses carrying the spacecraft state as frame
attributes. Then `get_sun(t).transform_to(body)` is the whole calculation.

**Orekit.** Supplies all four, and its domain objects are good —
`NadirPointing`, `EcksteinHechlerPropagator`, `EclipseDetector`,
`BoxAndSolarArraySpacecraft`. It costs a JVM.

Both were installed and run on the same problem. They agree: eclipse fraction
0.3776 against 0.3782, mean panel cosine 0.3177 against 0.3169, the residual
being J2-only secular drift against Eckstein-Hechler's J2–J6 plus a different
sun ephemeris. Orekit's `NadirPointing` produced **exactly** the LVLH
convention that had been chosen by hand, which is the most reassuring single
result of the exercise.

**astropy wins on installability, which is the binding constraint.** Some users
will install this on Windows.

- Installing Java is *not* the problem: conda-forge pulls a JVM automatically
  on every platform. The problem is JVM **discovery**. JPype searches
  `JAVA_HOME` and then two registry keys that only an old Oracle JRE
  populates — Temurin, Adoptium and Microsoft OpenJDK write none of them. And
  conda sets `JAVA_HOME` only on `conda activate`, so an unactivated
  interpreter (VS Code picking it, or Jupyter launched from a plain prompt)
  silently misses the env's own JVM. That is a support ticket per user, for a
  library that installed successfully.
- Orekit also needs `orekit-data`, 21 MB zipped and 37.7 MB unpacked, which is
  not a package on either channel and must be fetched at setup.
- Performance would not have decided it. A power run is an orbit to a day or
  two, and one day at 10 s through SGP4 takes 1.9 s in astropy against 1.3 s
  of Orekit loop plus 1.1 s of JVM start-up. astropy's one expensive step, its
  per-sample TEME to GCRS transform, could be replaced by a single rotation per
  run for a 7x gain; it is deliberately not, because this code is not meant
  for long sweeps and the gain buys nothing at the scale it is meant for.

**If Orekit is ever needed, it is `orekit_jpype`, never the classic JCC
`orekit`.** The JCC wrapper rejects `np.float64` and names no argument when it
does; it is missing methods the Java API has (`Vector3D.normalize()` raises
`AttributeError`) *while its own generated stubs promise them*, so Pylance
autocompletes what the runtime refuses; and it is pinned to Java 8. JPype also
turned out to be the faster of the two, against the usual lore.

The full assessment, the numbers and the working code are in
`.claude/power_spike/`.

**Consequence.** `astropy` and `sgp4` join the dependencies. The hand-rolled
orbit and attitude are ours to maintain — accepted, because they are now
validated against Orekit rather than merely plausible.

---

## 6. astropy.units, not pint

**2026-09-30. Implemented. Replaces pint, which the project used from the
start.**

quicksat began on pint: a single `UnitRegistry` exported from
`quicksat/__init__.py` with a `Q_` shorthand, units parsed at the load boundary
and stripped to canonical floats inside the DataFrames — every column in a mass
budget is the same dimension, so unit dtype inside the frame bought little
while coupling the project to `pint-pandas` compatibility.

**astropy trumps it, because the power generation work needs astropy for the
orbital mechanics** (decision 7), and astropy.units arrives with it whether or
not it is wanted: `get_sun`, every frame and every representation returns an
`astropy.units.Quantity`. So the choice was two unit systems with a boundary
between them, or one.

The one place astropy is weaker
is offset units — pint's `Q_(25, "degC")` is unambiguous, where astropy needs
`u.deg_C` with its own handling — and the radiator work will meet that. Known,
accepted, to be handled when it arrives.

Three conventions from the pint era carry over unchanged, because none of them
is about which library carries the units: one is about how numpy dispatches,
one about how a notebook reads, one about where a plain number is allowed. They
are in [conventions.md](../reference/conventions.md).

---

## 5. Three copies of the input files, one per audience

**2025-09. Settled.**

`sample/data/` belongs to the worked examples, `docs/data/` to the reference
notebooks, `tests/data/` is a fixture. Before the split, retuning the sample to
make a budget close would silently move a test's expected figure. The cost is
that a schema change has to be applied three times, and missing one leaves a
reference documenting a column its own example file does not have.

---

## 4. The notebooks are the documentation

**2025-09. Settled.**

Two per module: `sample/<module>.ipynb` is the worked example, one satellite
carried end to end; `docs/<module>_ref.ipynb` is the reference, every column
and config key and where the module stops. This removes any need for Sphinx.

Prose inside a notebook lives in JSON, so it diffs badly, and executed
notebooks carry their outputs into the diff too. What that buys is an
explanation that cannot quietly go stale: re-executing runs every claim the
notebook makes against the real code. Two habits keep the promise honest —
re-execute every notebook a change can reach, not only the edited one, and
check the stored output for tracebacks, since a notebook that ends in an error
still saves cleanly.

---

## 3. Shared objects are passed in, never imported and constructed

**2025-09. Settled.**

A budget's constructor takes the object; its `from_*` classmethod takes paths
and is the convenience. That is what lets a notebook load `mission.yaml` once
and hand the same `Mission` to every budget, rather than several parses that
merely agree today. The one cross-budget link, `DeltaVBudget(...,
mass_budget=None)`, stays optional, one-directional and read-only, and a test
asserts the optionality so it cannot rot.

---

## 2. One shared mission file, and the rule for what goes in it

**2025-09. Settled.**

**A fact more than one module can use lives in `mission.yaml`; a fact only one
module can use stays in that module's own config.** So the altitude is shared
and the Isp is not. The earlier rule — *each module's own config holds only
what is specific to it* — is what had put the design life in
`delta_v_config.yaml`: it described where a fact may live without saying which
file owns a fact two modules share.

`duration` is required, not optional: a file that says where the spacecraft is
but not how long it stays there describes an orbit rather than a mission.

---

## 1. The orbit is circular, and stays that way

**2025-09. Settled.**

Nothing models eccentricity, perturbations or drag. This is a first-pass sizing
tool.
