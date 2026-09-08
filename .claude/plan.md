# quicksat — Satellite Sizing Tool

## Context

A spartan, first-pass satellite sizing tool: mass budget, power subsystem and battery
sizing, and basic delta-V. Greenfield — nothing exists yet. It will live at
`/home/egemen/Projects/quicksat` and later go to GitHub alongside `opticks`.

The tool deliberately follows the conventions already established in
`/home/egemen/Projects/opticks`, since the same author maintains both.

**Status.** The mass budget is specified below and **implemented** — 27 tests passing, the
sample notebook runs end to end. The power/battery and delta-V modules are still awaiting
spec and will be added to this plan before implementation starts.

## Project scaffolding

Match opticks: flit build backend, ruff (line-length 88), tox, pytest, conda
`environment.yml`, GPL-3.0 header comment on every module, numpydoc-style docstrings,
`known-first-party` isort config.

```
quicksat/
  quicksat/
    __init__.py          # shared pint UnitRegistry, Q_ shorthand, __version__
    utils/
      parser_helpers.py  # PydanticQty for pint (ported from opticks)
    mass/
      equipment.py       # Equipment pydantic model
      budget.py          # MassBudget
  sample/                # data files and notebooks together
    equipment.csv
    budget_config.yaml
    mass_budget.ipynb
  tests/
  .claude/               # this plan file lives here, versioned with the project
  pyproject.toml  tox.ini  environment.yml  README.md  LICENSE.md  .gitignore
```

Dependencies: `pandas`, `pint`, `pydantic>=2.0`, `pyyaml`. Note the system Python is 3.14
with almost nothing installed — this needs its own conda env, as with the other projects.

## Units

pint, with a single shared `UnitRegistry` exported from `quicksat/__init__.py` and a `Q_`
shorthand, mirroring how opticks exports `u` and `Q_`.

Units are parsed at the load boundary and **stripped to canonical kg floats inside the
DataFrame**; quantities are re-attached only when formatting reports. Rationale: every
column in a mass budget is the same dimension, so unit dtype inside the frame buys little
while coupling the project to `pint-pandas` version compatibility.

`quicksat/utils/parser_helpers.py` is a port of
`opticks/utils/parser_helpers.py` — the same `Annotated[Quantity, BeforeValidator,
PlainSerializer]` idiom, with `astropy.units.Quantity` swapped for pint's.

## Mass budget

### Equipment CSV schema

| column | type | validation |
|---|---|---|
| `equipment_id` | str | no whitespace |
| `equipment_name` | str | free text, quoted |
| `location` | str | no whitespace |
| `responsibility` | str | no whitespace |
| `subsystem` | str | no whitespace |
| `unit_mass` | str | pint-parseable **and** mass-dimensioned (`"100 kg"`) |
| `equipment_margin` | float | `>= 0`, read as percent (`20` → 20%) |
| `number_of_units` | int | `>= 0` |
| `mass_class` | enum | `equipment` \| `propellant`; blank defaults to `equipment` |
| `comments` | str | may be empty |

Table-level rule: `(equipment_id, location)` pairs must be unique — the same equipment may
repeat across locations, but not within one.

Validation happens row-by-row through a pydantic `Equipment` model so errors name both the
offending row and field. This catches whitespace in the id/grouping fields, a wrong-dimension
typo such as `"100 W"` in the mass column, and negative margins or unit counts.

### Budget config YAML

Separate from the equipment CSV, loaded via a `from_yaml_file` classmethod in the opticks
style. Everything is keyed on **location** — one block per location, carrying its system
margin and its harness parameters:

```yaml
locations:
  Platform:
    system_margin: 20     # percent, applied to the location subtotal
    harness_fraction: 5   # percent of this location's equipment CBE
    harness_margin: 10    # percent, the harness's own equipment margin
  Payload:
    system_margin: 15
    harness_fraction: 3
    harness_margin: 10
```

`Launcher` is a **reserved location name** and needs no block. It defaults to
`system_margin: 0`, `harness_fraction: 0`, `harness_margin: 0` and `retained_in_orbit: false`
— i.e. launcher-side hardware carries no margins, generates no harness, and is dropped at
separation. An explicit `Launcher` block overrides those defaults if ever needed.

Every other location defaults to `retained_in_orbit: true`, and one present in the CSV but
absent from `locations` is a **validation error**, not a silent 0 — defaulting would quietly
understate the budget.

Location is the single computation axis: it drives both the harness percentage and the system
margin. `responsibility` and `subsystem` are pure reporting axes, used only for grouping.
Having one axis drive all the margin logic is what keeps the harness rows unambiguous.

### Mass classes and cases

Two independent switches — `case` (`ON_GROUND` / `IN_ORBIT`) and `with_propellant` — give the
four standard reporting masses:

| | `with_propellant=True` | `with_propellant=False` |
|---|---|---|
| **on ground** | launch mass | dry mass at launch |
| **in orbit** | separated wet mass | in-orbit dry mass |

Two things decide what survives each case:

```
location with retained_in_orbit: false → counted ON_GROUND, dropped IN_ORBIT
mass_class = propellant                → counted only when with_propellant, never margined
```

The separation interface is entered as **two ordinary equipment rows**, not as a split
factor: the satellite-side half at `location = Platform`, the launcher-side half at
`location = Launcher`. Both are `mass_class = equipment` — the adapter is ordinary hardware,
and it is the location that decides which half flies. Their real masses are typed directly
into the CSV, so no split config is needed and an asymmetric interface costs nothing extra.

### Computation

Per row:

```
cbe_kg = unit_mass_kg × number_of_units
```

Margins apply to hardware only — `propellant` enters at face value, since propellant
uncertainty is carried as ΔV reserve rather than mass contingency:

```
equipment  → mev_kg = cbe_kg × (1 + equipment_margin / 100)
propellant → mev_kg = cbe_kg
```

### Harness

Harness is not a CSV row — it is derived per location and injected as a **synthetic row**
before aggregation, carrying `subsystem = "Harness"`, `mass_class = equipment`, and that
location's `harness_margin` in its `equipment_margin` column:

```
base_L      = Σ cbe of equipment-class rows at location L
harness_cbe = harness_fraction[L] / 100 × base_L
harness_mev = harness_cbe × (1 + harness_margin[L] / 100)
```

The base deliberately excludes `propellant` rows — cabling scales with the boxes it connects,
not with propellant load. It also uses CBE, not margined mass, so the harness estimate doesn't
compound the equipment margins. Harness is computed per location, so a `Launcher` location
simply carries `harness_fraction: 0` and contributes none.

Because harness is a real row keyed on location, it needs no special-casing downstream: it
picks up the location's system margin like everything else, and appears as its own line in
`by_subsystem()`. It is identical across all four mass cases, which is physically right.

One consequence of deriving harness from location while `responsibility` stays free: a
harness row has no meaningful single responsibility when a location hosts mixed
responsibilities, so it is tagged `responsibility = "Harness"` rather than guessing. It
therefore appears as its own line in `by_responsibility()` too.

### Totals

Assembled per location, then summed:

```
subtotal_L = Σ mev of retained hardware rows at L  +  harness_mev_L
total_L    = subtotal_L × (1 + system_margin[L] / 100)
           + Σ cbe of retained propellant rows at L      # outside the system margin

total      = Σ_L total_L
```

Propellant sits outside the system-margin multiply, consistent with it taking no margins at
all. Everything else stays a linear per-row factor, so the class retention and the harness
injection compose without interfering.

### API

`MassBudget` is a thin wrapper over the validated DataFrame — no `Satellite` or `Subsystem`
classes. Location, responsibility and subsystem are cross-cutting axes; a class hierarchy
would have to privilege one of the three as the nesting axis and then express the other two
as side-tables. A flat table privileges none, and `groupby` gives all three for free.
`Equipment` earns its keep as the validation gate; a subsystem is a value in a column, not
an object with behaviour.

- `MassBudget.from_csv(csv_path, config_path)`
- `.total(case=IN_ORBIT, with_propellant=True)` → the case mass
- `.by_subsystem(case=..., with_propellant=...)` / `.by_location(...)` /
  `.by_responsibility(...)` → DataFrame with `cbe` and `total` columns per group
- `.equipment` — the underlying validated DataFrame, for ad-hoc queries

`case` and `with_propellant` are parameters on every query rather than state on the object,
so all four cases can be compared from a single `MassBudget` without reloading.

Report output re-attaches pint units for display.

Computation and reporting are driven from Jupyter notebooks — the package provides the
`MassBudget` API and the notebook in `sample/` is the worked example, carrying the four mass
cases and the three grouping views end to end.

### Tests

Sanity-level, matching the spartan intent:

- margin arithmetic on a hand-checked fixture, and propellant entering unmargined
- all three grouping views reconciling to the same grand total, in each of the four cases
- launch mass − in-orbit wet mass = the rows at non-retained locations, propellant held
  constant
- harness: derived from CBE not margined mass, excluding `propellant` from its base, and
  identical across all four cases
- validation failures: whitespace in id, wrong-dimension mass, duplicate id+location pair,
  unknown `mass_class`, location missing from the config

## Pending specification

- **Power subsystem and battery sizing** — awaiting spec.
- **Delta-V** — awaiting spec.

## Verification

- `conda env create -f environment.yml`, then `pip install -e .`
- `pytest` passes
- `sample/mass_budget.ipynb` runs top to bottom against `sample/equipment.csv`, and the three
  grouping views reconcile to the same grand total in each of the four cases
- `git init` and first commit; GitHub repo only once you're ready to publish
