# How to add a manoeuvre

This guide adds a manoeuvre to the delta-V budget, and shows what it costs. Each manoeuvre is one row of `manoeuvres.csv`. quicksat works out the delta-V of the common ones from the orbit, and takes the rest as figures from mission analysis.

The guide adds two rows to the sample as examples. One is a raise from a rideshare drop-off, which quicksat works out. The other is ground-track maintenance, a figure brought from mission analysis.

You need a folder of sizing files first. [How to initialise a satellite](initialise_a_satellite.md) shows how to start one from the sample. You can edit the file in the Sizing Editor, as [how to edit and run the sizing files](edit_the_sizing_files.md) shows, or in a text editor.

## 1. Pick the type

The type decides how quicksat turns the row's `value` into a delta-V. Pick it from what the manoeuvre does:

| The manoeuvre | Type | `value` |
| --- | --- | --- |
| A raise or a lowering of a circular orbit: an injection correction, a raise from the drop-off orbit, drag make-up | `altitude_change` | the size of the change, such as `30 km` |
| A change of the orbit's plane: an injection trim, inclination maintenance | `inclination_change` | the angle, such as `0.05 deg` |
| A collision avoidance | `collision_avoidance` | the altitude offset, such as `200 m` |
| The disposal burn | `deorbit` | the perigee altitude to lower to: `250 km` for a decay orbit, `0 km` for a direct re-entry |
| Anything else: phasing, a node change, eccentricity control, formation keeping | `given` | the delta-V itself, such as `8 m/s` |

The first four use short closed forms for circular orbits, and start from the orbit in `mission.yaml`. They leave out perturbations, elliptical orbits and the length of the burns. When a manoeuvre needs any of these, have it worked out elsewhere, and enter the result as `given`.

A collision avoidance either returns to its orbit or not. `delta_v_config.yaml` sets this for all of them, with `return_burn`. When it returns, quicksat counts the delta-V twice.

## 2. Write the row

Add one line to `manoeuvres.csv`. The two example rows are:

```text
manoeuvre_id,manoeuvre_name,phase,manoeuvre_type,value,count,recurring,loss_factor,comments
rideshare_raise,Raise from the rideshare drop-off,Commissioning,altitude_change,30 km,1,false,1.0,The rideshare leaves the satellite 30 km below the mission orbit
ground_track,Ground-track maintenance,Operations,given,0.2 m/s,6,true,1.0,From Mission Analysis: holds the ground track within 1 km
```

- **`manoeuvre_id`** is a short name with no spaces. Give each row its own.
- **`manoeuvre_name`** is free text, for the tables.
- **`phase`** groups the rows in the totals. It takes no spaces, so write `EndOfLife` or `End-of-life`, not `End of life`. A new name adds a new group.
- **`value`** has the unit that its type needs: a length, an angle or a velocity.
- **`comments`** says where the figure came from. The next person to change the row needs to know.

An `altitude_change` starts from the mission orbit. So the raise from 470 km to 500 km is worked out as 500 km to 530 km: 16.55 m/s in place of 16.66 m/s. For a change of a few tens of kilometres, the difference is below 1 %.

## 3. Set how often it happens

`count` is how many times the manoeuvre happens.

- **Once, or a fixed number of times:** set `recurring` to `false`. The count is the total for the mission. The raise happens once.
- **Every year:** set `recurring` to `true`. The count is then per year, and quicksat multiplies it by the design life in `mission.yaml`. The ground-track maintenance happens 6 times a year, so 42 times over the sample's 7 years.

A count may be a fraction, such as `0.5` for once every two years. Keeping the yearly rate in the row means that a longer design life is one edit, to `mission.yaml`.

## 4. Allow for long burns, if they are long

The closed forms assume each burn is instant. A real burn takes time, and needs more delta-V than the closed form says. `loss_factor` multiplies the row's delta-V to allow for it: `1.0` for an instant burn, `1.03` for 3 % more. It cannot be below 1.0.

Long burns come from low thrust. The sample has four 1 N thrusters on a 470 kg satellite. Its 71 m/s deorbit burn would take more than two hours as a single burn. Operators split such a burn into several, and the loss depends on that split. quicksat cannot work it out, so take the factor from mission analysis, or leave it at 1.0 until you have one.

The margin in `delta_v_config.yaml` is for something else: the counts that are only estimates. Do not use one in place of the other.

## 5. Check the row

**In the Sizing Editor,** on the **Delta-V** tab, the page checks each row as you edit it. It flags a unit that does not suit the type, an id or a phase with a space, a count below 0, and a loss factor below 1.

**In the delta-V notebook,** run `delta_v_budget.ipynb`. A row that quicksat cannot read stops it with the file, the line and the reason:

```text
my_satellite/manoeuvres.csv, row 10:
1 validation error for Manoeuvre
  Value error, A 'inclination_change' manoeuvre needs an angle in its value column, got '0.2 m / s' ...
```

Row 10 is the tenth line of the file, counting the header.

The table after `resolve()` gives each row's delta-V once, its count over the mission, and its total. The two new rows are at the bottom:

```text
       manoeuvre_id   manoeuvre_type  deltav_each  occurrences  deltav_total
...
7   rideshare_raise  altitude_change        16.55         1.00         16.55
8      ground_track            given         0.20        42.00          8.40
```

Check that each figure is the size you expect. A delta-V far too small or too large usually means a wrong unit, such as `m` where `km` was meant.

## 6. See what it costs

The totals show where the new rows land. In the sample, with the 5 % margin:

| | Before | After |
| --- | --- | --- |
| Commissioning | 22.34 m/s | 39.71 m/s |
| Operations | 19.85 m/s | 28.67 m/s |
| Disposal | 74.32 m/s | 74.32 m/s |
| Total | 116.52 m/s | 142.71 m/s |
| Propellant required | 24.89 kg | 30.68 kg |

The sample loads 22.0 kg. It was 2.89 kg short before the two rows, and is now 8.68 kg short.

More propellant needs a larger tank, which adds mass, and the extra mass changes the other budgets. [How to close the sizing budgets](close_the_sizing_budgets.md) goes through those rounds.

Details: [`delta_v_ref.ipynb`](../../sizing/delta_v_ref.ipynb), sections "The manoeuvre file", "The closed forms" and "Counts, and the mission duration".
