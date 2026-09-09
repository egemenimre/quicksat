# quicksat

Basic satellite sizing tool: mass budget, power subsystem and battery sizing, and basic delta-V. Deliberately spartan — the aim is a first-pass sizing, not a full systems engineering environment.

## Status

- **Mass budget** — implemented.
- **Power and battery sizing** — not yet specified.
- **Delta-V** — not yet specified.

## Mass budget

The satellite is described by a flat equipment CSV plus a config YAML. Nothing is nested: `location`, `responsibility` and `subsystem` are cross-cutting axes, so any of them can be summed over independently.

### Equipment CSV

| column | meaning |
|---|---|
| `equipment_id` | short identifier, no whitespace (`star_tracker`) |
| `equipment_name` | full name, free text (`Jena Astro HP`) |
| `location` | where it sits — the computation axis |
| `responsibility` | who owns it — reporting only |
| `subsystem` | `ADCS`, `EPS`, ... — reporting only |
| `unit_mass` | mass of one unit, with its unit (`100 kg`, `750 g`) |
| `equipment_margin` | per-item contingency, percent |
| `number_of_units` | how many are flown |
| `mass_class` | `equipment` or `propellant`; blank means `equipment` |
| `comments` | free text |

Masses are parsed with [pint](https://pint.readthedocs.io/), so a dimensionally wrong entry such as `100 W` in the mass column is rejected on load rather than quietly becoming a number.

### Config YAML

Margins and harness are keyed on location:

```yaml
locations:
  Platform:
    system_margin: 20     # percent, applied to the location subtotal
    harness_fraction: 5   # percent of this location's equipment mass, before margin
    harness_margin: 10    # percent, the harness's own contingency
  Payload:
    system_margin: 15
    harness_fraction: 3
    harness_margin: 10
```

`Launcher` is a reserved location name and needs no entry: it defaults to no margins, no harness, and being dropped at separation. Any *other* location used in the CSV but missing from the config is an error rather than a silent zero.

### Harness

Harness is not entered by hand. One row per location is derived as `harness_fraction` of that location's equipment mass, given its own `harness_margin`, and injected before aggregation. The base excludes propellant, and uses the mass before margin rather than after, so the estimate does not compound the equipment margins.

The derived row takes its location's name as its `responsibility`, so it is counted whichever axis you sum on, while keeping `Harness` as its `subsystem` so it stays a visible line of its own.

### Mass cases

Two of the query flags give the four standard reporting masses:

| | `wet=True` | `wet=False` |
|---|---|---|
| `in_orbit=False` | launch mass | dry mass at launch |
| `in_orbit=True` | separated wet mass | in-orbit dry mass |

The separation interface is entered as two ordinary equipment rows — the satellite-side half at `location: Platform`, the launcher-side half at `location: Launcher` — with their real masses. There is no split factor to configure, and an asymmetric interface costs nothing extra.

## Usage

Every query takes the same four flags, all defaulting to `True`, so the common question is a bare call and each deviation is one explicit switch:

| flag | when `True` |
|---|---|
| `wet` | propellant is counted |
| `sys_margin` | the location's system margin is applied |
| `eqpt_margin` | the per-item equipment margin is applied |
| `in_orbit` | hardware at locations that do not survive separation is dropped |

```python
from quicksat.mass.budget import MassBudget

budget = MassBudget.from_csv("sample/data/equipment.csv", "sample/data/budget_config.yaml")

budget.in_orbit_mass()                      # separated wet mass
budget.on_ground_mass(wet=False)            # dry mass at launch
budget.total_mass(sys_margin=False)         # everything, before system margin
budget.platform_mass()                      # the bus
budget.payload_mass(by_location=False)      # payload, summed on responsibility
budget.subsystem_mass("ADCS")               # one subsystem, no system margin
budget.propellant_mass()                    # propellant, at face value
```

All of these return a pint `Quantity` in kg. `total_mass` is the generic query; the rest are presets over it with a filter applied.

`platform_mass` and `payload_mass` take a `by_location` switch because Platform and Payload name both a location and a responsibility — an item can sit physically on the payload while belonging to the platform team, and the two axes then disagree. `subsystem_mass` carries no system margin, since margins of that kind are held at the platform and payload level and cannot be attributed to a subsystem.

### Aggregation

The same rows can be summed over any of the three cross-cutting axes. Each view takes the same flags and returns a DataFrame indexed by the axis value with a single `mass` column, and all three reconcile to the same total.

```python
budget.by_location()                        # per location
budget.by_responsibility()                  # per responsibility
budget.by_subsystem(wet=False)              # per subsystem, dry
```

Because the margin flags apply here too, the three margin layers are the same call three times:

```python
pd.DataFrame({
    "eqpt_total_mass":  budget.by_subsystem(eqpt_margin=False, sys_margin=False)["mass"],
    "with_margin":      budget.by_subsystem(sys_margin=False)["mass"],
    "with_sys_margin":  budget.by_subsystem()["mass"],
})
```

`location` also drives the computation — system margin, harness and separation — while `responsibility` and `subsystem` are reporting axes, so the per-responsibility and per-location views are two cuts of the identical total.

### The budget as a document

`tabulated_mass()` returns the whole budget as a table rather than a single figure: every item, grouped into subsystem blocks within each location, subtotalled, then the location subtotal before and after its system margin, and finally the dry mass, the propellant, and the wet mass.

```python
budget.tabulated_mass(in_orbit=True)
```

Propellant appears once, at the bottom, and is left out of the blocks above it, so every subtotal on the way down is a dry mass and the column adds up as it reads. One consequence worth knowing: the Propulsion subsystem subtotal in this table is dry, while `subsystem_mass("Propulsion")` is wet — they answer different questions.

Every row carries a `row_type` — `equipment`, `subsystem_subtotal`, `location_subtotal`, `system_margin`, `location_total`, `dry_total`, `propellant`, `wet_total` — so the frame can be styled, filtered or exported.

`sample/mass_budget.ipynb` works through the whole thing against the sample data.

## Installation

```bash
conda env create -f environment.yml
conda activate quicksat
pip install -e .
```

## License

GPL-3.0-or-later. See `LICENSE.md`.
