# Decisions

The decisions that shaped quicksat, and the reasons for them. A decision belongs here when reversing it would take real work. It also belongs here when the code alone does not show the reasoning. That is the difference between this file and the module docstrings.

Newest first. When a decision replaces an earlier one, the earlier one is kept inside the new entry rather than deleted. Most of the value is in knowing what was tried, and why it was replaced.

---

## 10. Scenario is its own domain, and power depends on it

**2026-10-02. Settled.**

A third domain, `scenario`, sits next to `sizing` and `power`. It follows the layout in entry 9: `sample/scenario/`, `docs/scenario/`, `tests/scenario/` and `docs/guides/scenario/`, with the code in `quicksat/scenario/`.

The scenario holds the orbit, the start time, the duration and a list of activities. Each activity has an end trigger, an attitude, a mode and an optional constraint. The scenario file is `scenario.yaml`. The scenario notebook checks the activities against the orbit, for example their eclipse constraints.

**The dependency runs one way.** The scenario imports nothing from power. Power imports the scenario. The workflow follows from that:

1. Define the scenario.
2. Define a baseline power sizing: the solar panels and the batteries.
3. Verify that the sizing supports the scenario.

The reason is that a scenario of modes and attitudes is useful without a power model. Other domains may use it later, such as thermal, or agility along the scenario's real attitudes.

**Power keeps its own copies of the scenario files.** Power imports the scenario code, but it does not read the scenario domain's files. Each power data folder holds the scenario files it needs, so `sample/power/data/` never reads `sample/scenario/data/`. This keeps the rule in entry 9 that the domains do not share input files. One power setup can be checked against more than one scenario, such as winter and summer, so a power data folder may hold several scenario files.

**The scenario names the modes, and power defines them.** An activity says `idle` or `firing`. The power files say how much each mode draws. Power checks that every mode in the scenario has a consumption entry.

**An unsupported scenario is a power result.** A battery that runs flat is reported by power. It is not a scenario error. The scenario is invalid only for its own reasons, such as a violated constraint.

**Visualisation is not a domain.** Plots that compute a result stay in the notebook of the domain that owns the data. A scenario viewer is a separate front end. It reads a timeline file written by the library and, optionally, the power results. Which technology it uses is decided elsewhere.

---

## 9. Sizing, scenario and power are separate domains, each with its own files

**2026-10-01. Settled. Updated on 2026-10-08: entry 10 added the scenario as a third domain on 2026-10-02.**

The notebooks, their input files and the tests are split into domains. `sizing` holds the current four budgets: mass, data, delta-V and agility. `scenario` holds the orbit and the timeline of activities. `power` holds power generation. Each domain has the same three folders:

- `sample/<domain>/` for the worked examples, with their data in `data/`.
- `docs/<domain>/` for the reference notebooks, with their data in `data/`.
- `tests/<domain>/` for the tests, with their fixtures in `data/`.

The how-to guides follow the same split, under `docs/guides/<domain>/`. Project-wide documents stay at the top of `docs/`: this file and `reference/conventions.md`.

The reason is that the domains describe the satellite differently. Sizing uses a circular orbit and a flat equipment list. The scenario needs an epoch, a local time of the ascending node, and a TLE or an ephemeris. Power needs solar panels on named faces, and takes its orbit from the scenario. One set of files cannot serve them all without a domain carrying fields it never reads.

When this entry was written, there were two domains, sizing and power. The orbit and the epoch were then power's. Entry 10 moved them into the scenario.

**The domains do not share input files.** The rule in entry 2 applies within a domain: a fact that more than one module in that domain uses goes in that domain's shared file. The domains may share code, such as the orbit and sun geometry in `quicksat/orbit/`, but not data. The three copies in entry 5 are kept once per domain.

---

## 8. Earth constants are astropy's defaults

**2026-09-30. Settled. Replaces WGS-84 and EGM96, which the project used from the start.**

`R_EARTH` and `MU_EARTH` are now astropy's `R_earth` and `GM_earth`. By default these are the IAU 2015 nominal values, 6378.1 km and 398600.4 km³/s². Before, quicksat wrote out its own: the WGS-84 equatorial radius of 6378.137 km, and the EGM96 measured GM of 398600.4418 km³/s². astropy is now the one source of physical constants, as it already was for standard gravity.

The change is too small to matter for sizing. At 500 km, the orbital period moves by 0.05 s and the velocity by 0.02 m/s. One test checked the orbit radius to the metre, and it was updated. Every other figure in the tests, the README and the notebooks is unchanged at the precision it is quoted to.

`MU_EARTH` is still a GM rather than G times a mass. GM is the measured quantity, known to about nine significant figures. G is known to about five. astropy works the same way: it derives its `M_earth` from GM and G.

---

## 7. Orbit, attitude and sun geometry with astropy, not orekit

**2026-09-30. Settled, after measurement.**

The power budget needs the angle between a solar panel's normal and the sun. That angle needs a trajectory, an attitude, and the sun's position. The candidates were astropy, and Orekit through one of its two Python wrappers.

**astropy.** It supplies three of the four pieces. These are the sun (`get_sun`), the inertial and Earth-fixed frames (`GCRS`, `ITRS`, `TEME`), and a frame graph that chains rotations together. It supplies **no propagator and no attitude model**, so quicksat writes those. They take about 120 lines. `LVLH` and `Body` can be real `BaseCoordinateFrame` subclasses, with the spacecraft state as frame attributes. Then `get_sun(t).transform_to(body)` is the whole calculation.

**Orekit.** It supplies all four, and its domain objects are good, such as `NadirPointing`, `EcksteinHechlerPropagator`, `EclipseDetector` and `BoxAndSolarArraySpacecraft`. But it needs a JVM.

Both were installed and run on the same problem, and they agree. The eclipse fraction is 0.3776 against 0.3782, and the mean panel cosine is 0.3177 against 0.3169. The small difference has two causes. The astropy side used J2-only secular drift, against Eckstein-Hechler's J2 to J6. The two also use different sun ephemerides. Orekit's `NadirPointing` gave **exactly** the LVLH convention that had been chosen by hand. This was the most reassuring single result of the comparison.

**astropy was chosen because it is easier to install, and that is the deciding constraint.** Some users will install quicksat on Windows.

- Installing Java is *not* the problem. conda-forge installs a JVM automatically on every platform. The problem is **finding** the JVM. JPype searches `JAVA_HOME`, and then two registry keys that only an old Oracle JRE writes. Temurin, Adoptium and Microsoft OpenJDK write neither of them. conda sets `JAVA_HOME` only on `conda activate`. So an interpreter started without activation does not find the env's own JVM, and gives no clear reason. VS Code may start an interpreter this way, and so does Jupyter launched from a plain prompt. Each such user would need support, for a library that installed without an error.
- Orekit also needs `orekit-data`, which is 21 MB zipped and 37.7 MB unpacked. It is not a package on either channel, so it must be downloaded at setup.
- Performance would not have decided it. A power run covers one orbit to a day or two. One day at 10 s steps through SGP4 takes 1.9 s in astropy. Orekit takes 1.3 s for the loop, plus 1.1 s to start the JVM. astropy's one slow step is its TEME to GCRS transform for each sample. A single rotation per run could replace it, and would be 7 times faster. This is not done, on purpose. The code is not meant for long sweeps, and the gain does not matter at the scale it is meant for.

**If Orekit is ever needed, use `orekit_jpype`, never the classic JCC `orekit`.** The JCC wrapper has three problems. It rejects `np.float64`, and its error does not name the argument. It lacks methods that the Java API has: `Vector3D.normalize()`, for example, raises `AttributeError`. *Yet its own generated stubs list them*, so Pylance offers methods that fail at runtime. And it is pinned to Java 8. JPype also turned out to be the faster of the two, contrary to what is usually said.

The full assessment, the numbers and the working code are in `.claude/power_spike/`.

**Consequence.** `astropy` and `sgp4` join the dependencies. quicksat maintains its own orbit and attitude code. This is accepted, because the code has been checked against Orekit, rather than only looking plausible.

---

## 6. astropy.units, not pint

**2026-09-30. Implemented. Replaces pint, which the project used from the start.**

quicksat began with pint. `quicksat/__init__.py` exported a single `UnitRegistry`, with a `Q_` shorthand. Units were parsed when the files were loaded. Inside the DataFrames, they were stripped to floats in standard units. Every column in a mass budget has one dimension, so a unit dtype in the frame added little. It would also have tied the project to `pint-pandas` compatibility.

**astropy replaced it, because the power generation work needs astropy for the orbital mechanics** (decision 7). astropy.units comes with it, wanted or not. `get_sun`, every frame and every representation return an `astropy.units.Quantity`. So the choice was between two unit systems with a boundary between them, and one.

astropy is weaker in one place: offset units. pint's `Q_(25, "degC")` is unambiguous. astropy needs `u.deg_C`, which has its own handling. The radiator work will need offset units. This is known and accepted, and will be handled then.

Three conventions from the pint era carry over unchanged. None of them depends on which library holds the units. One is about how numpy dispatches, one about how a notebook reads, and one about where a plain number is allowed. They are in [conventions.md](../reference/conventions.md).

---

## 5. Three copies of the input files, one per audience

**2025-09. Settled.**

`sample/sizing/data/` belongs to the worked examples, and `docs/sizing/data/` to the reference notebooks. `tests/sizing/data/` holds the test fixtures. Before the split, changing the sample to make a budget close would also change a test's expected figure, with no warning. The cost is that a schema change has to be made three times. If one copy is missed, a reference documents a column that its own example file does not have.

---

## 4. The notebooks are the documentation

**2025-09. Settled.**

There are two notebooks per module. `sample/<domain>/<module>.ipynb` is the worked example, which takes one satellite from start to end. `docs/<domain>/<module>_ref.ipynb` is the reference. It covers every column and config key, and where the module stops. So the project needs no Sphinx.

Prose inside a notebook is stored in JSON, so its diffs are hard to read. Executed notebooks also put their outputs into the diff. In return, the explanation cannot go out of date unnoticed. Re-executing a notebook checks every claim it makes against the real code. This needs two habits. First, re-execute every notebook that a change can affect, not only the edited one. Second, check the stored output for tracebacks, because a notebook that ends in an error still saves without complaint.

---

## 3. Shared objects are passed in, never imported and constructed

**2025-09. Settled.**

A budget's constructor takes the object. Its `from_*` classmethod takes paths, for convenience. So a notebook can load `mission.yaml` once, and pass the same `Mission` to every budget. Otherwise each budget would read its own copy, and the copies would only happen to agree. The one link between budgets is `DeltaVBudget(..., mass_budget=None)`. It stays optional, one-way and read-only. A test checks that it is optional, so a later change cannot make it required without the test failing.

---

## 2. One shared mission file, and the rule for what goes in it

**2025-09. Settled.**

**A fact that more than one module can use goes in `mission.yaml`. A fact that only one module uses stays in that module's own config.** So the altitude is shared, and the Isp is not. The earlier rule was that *each module's own config holds only what is specific to it*. That rule had put the design life in `delta_v_config.yaml`. It said where a fact may go, but not which file holds a fact that two modules share.

`duration` is required. A file that says where the spacecraft is, but not how long it stays there, describes an orbit rather than a mission.

---

## 1. The orbit is circular, and stays that way

**2025-09. Settled.**

Nothing models eccentricity, perturbations or drag. This is a first-pass sizing tool.
