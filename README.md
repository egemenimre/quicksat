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
| `eqpt_margin` | per-item contingency, percent |
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

| | `propellant=100` | `propellant=0` |
|---|---|---|
| `in_orbit=False` | launch mass | dry mass at launch |
| `in_orbit=True` | separated wet mass | in-orbit dry mass |

The separation interface is entered as two ordinary equipment rows — the satellite-side half at `location: Platform`, the launcher-side half at `location: Launcher` — with their real masses. There is no split factor to configure, and an asymmetric interface costs nothing extra.

## Usage

Every query takes the same four flags, all defaulting to `True`, so the common question is a bare call and each deviation is one explicit switch:

| flag | when `True` |
|---|---|
| `propellant` | percentage of the propellant load counted: 100 at start of life, 0 at end |
| `sys_margin` | the location's system margin is applied |
| `eqpt_margin` | the per-item equipment margin is applied |
| `in_orbit` | hardware at locations that do not survive separation is dropped |

```python
from quicksat.mass.budget import MassBudget

budget = MassBudget.from_csv("sample/data/equipment.csv", "sample/data/budget_config.yaml")

budget.in_orbit_mass()                      # separated wet mass
budget.on_ground_mass(propellant=0)         # dry mass at launch
budget.in_orbit_mass(propellant=50)         # half-way through the mission
budget.total_mass(sys_margin=False)         # everything, before system margin
budget.platform_mass()                      # the bus
budget.payload_mass(by_responsibility=True)  # payload, summed on responsibility
budget.subsystem_mass("ADCS")               # one subsystem, no system margin
budget.propellant_mass()                    # propellant, at face value
```

All of these return a pint `Quantity` in kg. `total_mass` is the generic query; the rest are presets over it with a filter applied.

`platform_mass` and `payload_mass` take a `by_responsibility` switch because Platform and Payload name both a location and a responsibility — an item can sit physically on the payload while belonging to the platform team, and the two axes then disagree. `subsystem_mass` carries no system margin, since margins of that kind are held at the platform and payload level and cannot be attributed to a subsystem.

### Aggregation

The same rows can be summed over any of the three cross-cutting axes. Each view takes the same flags and returns a DataFrame indexed by the axis value with a single `mass` column, and all three reconcile to the same total.

```python
budget.by_location()                        # per location
budget.by_responsibility()                  # per responsibility
budget.by_subsystem(propellant=0)           # per subsystem, dry
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

`tabulated_mass()` returns the whole budget as a table rather than a single figure: every item, grouped into subsystem blocks within each location, then the location subtotal before and after its system margin, and finally the dry mass, the propellant, and the wet mass.

```python
budget.tabulated_mass(in_orbit=True)                          # the document view
budget.tabulated_mass(subsystem_subtotals=True)               # add per-subsystem lines
budget.tabulated_mass(comments=True)                          # show the CSV's comments
budget.tabulated_mass().data                                  # the numbers, as a frame
```

What comes back is a pandas `Styler`, so cells that do not apply to a row come out blank rather than `NaN`, the masses print at a fixed number of decimals, and the summary lines are bold. The frame is still available as `.data`. Per-subsystem subtotal lines are off by default because they crowd the table; the grouping by subsystem stays either way. The equipment file's `comments` column is hidden by default for the same reason, though it is worth turning on to see the derived harness rows explain where their mass came from. The `location` column is hidden outright, since every subtotal and total row already names the location it closes. All three stay in `.data` regardless.

Each row reads as the same three-step progression, whichever level it sits at: `total_mass`, then `margin_pct`, then `total_mass_with_margin`. On an item row that margin is the equipment contingency; on a location total it is the system margin applied to the subtotal above. Items carry both an `equipment_id` and a `name`, since neither alone identifies them — the id says what a thing is (`magnetorquer`), the name which one it is (`ZARM MT30`). Subtotal captions sit in the `name` column with the id blank, so they indent one column in from the items above.

Propellant appears once, at the bottom, and is left out of the blocks above it, so every subtotal on the way down is a dry mass and the column adds up as it reads. One consequence worth knowing: the Propulsion subsystem subtotal in this table is dry, while `subsystem_mass("Propulsion")` is wet — they answer different questions.

Every row carries a `row_type` in `.data` — `equipment`, `subsystem_subtotal`, `location_subtotal`, `location_total`, `dry_total`, `propellant`, `wet_total` — so the report can be filtered or exported. It is hidden in the rendered table.

`sample/mass_budget.ipynb` works through the whole thing against the sample data.

## Installation

```bash
conda env create -f environment.yml
conda activate quicksat
pip install -e .
```

## License

GPL-3.0-or-later. See `LICENSE.md`.
