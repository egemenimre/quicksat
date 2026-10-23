# How to close the sizing budgets

This guide shows how to make every sizing budget pass at the same time. The budgets share their inputs, so a change that closes one budget can make another fail. More propellant closes the delta-V budget, but it adds mass, and a heavier spacecraft turns more slowly.

quicksat writes nothing back from one budget to another. So you carry each result into the input files by hand, work out every budget again, and repeat. You stop when a whole round passes every check and needs no change to any file.

The Sizing Editor's Budgets tab works out every budget at once. With the editor's server, it does so after each change, so a round is a change in the editor and a look at the tab. The notebooks work out one budget each, and show each step.

The guide works through one example on the sample satellite: a direct re-entry at the end of life. It takes four rounds to close.

You need a folder of sizing files first. [How to initialise a satellite](initialise_a_satellite.md) shows how to start one from the sample. [How to edit and run the sizing files](edit_the_sizing_files.md) shows how to edit the files in the Sizing Editor and run the notebooks.

## 1. Know what links the budgets

Some links are read when you run a notebook. The others are figures that you copy across yourself.

| From | To | What travels | How |
| --- | --- | --- | --- |
| `mission.yaml` | delta-V | the orbit's velocity and radius, and the design life for the recurring manoeuvres | read when the notebook runs |
| `mission.yaml` | data | the orbital period, for the storage between contacts | read when the notebook runs |
| `mission.yaml` | agility | the ground track speed, for the ground passed during a slew | read when the notebook runs |
| `requirements.yaml` | data | the orbits without downlink that the mass memory must cover | read when the notebook runs |
| `requirements.yaml` | agility | the slews the mission needs, and the time each may take | read when the notebook runs |
| mass budget | delta-V | the in-orbit dry mass, for the rocket equation | read when the notebook runs |
| mass budget | agility | the in-orbit mass, at the case's share of propellant, for the inertia of an estimated case such as `first_guess` | read when the notebook runs |
| delta-V | `equipment.csv` | the propellant required, against the propellant row | by hand |
| delta-V | `equipment.csv` | a tank big enough for the propellant | by hand |
| agility | `equipment.csv` | the reaction wheels' mass, for the wheels that `agility_config.yaml` describes | by hand |
| data | `equipment.csv` | the mass of a memory and a radio that match the capacity and the rate in `pl_dataflow_model.yaml` | by hand |

"Read when the notebook runs" means that the notebook reads the current file each time you run it. A notebook you do not run keeps showing the old figures.

An inertia case with a stated inertia, such as `measured_bol`, takes no mass from the mass budget. It does not follow your changes. Update it when a new mass properties report comes in.

## 2. Work out every budget

**In the Sizing Editor.** Serve the folder, and open the Budgets tab:

```bash
python -m quicksat.editor serve my_satellite
```

Its overview lists every check below, with its spare and its margin, and the tab's title counts the budgets with a failing check. Each budget's page has its tables, as the notebook shows them. The budgets follow each change on the page, saved or not, so each round below is an edit on the page. Save the files once a round closes, and put them back in the folder.

**In the notebooks.** Run them in this order, because each one reads what the ones before it check:

1. `mass_budget.ipynb`
2. `delta_v_budget.ipynb`
3. `agility_roll.ipynb` and `agility_pitch.ipynb`
4. `data_budget.ipynb`

Run all of them in each round, even those you expect not to change.

Either way, note the figures that decide whether the design closes:

| Budget | It closes when |
| --- | --- |
| Delta-V | its check passes: the propellant loaded is at least the propellant required. |
| Agility | its checks pass: each slew in `requirements.yaml` fits its time, for the selected inertia case. The sample asks for a 40° slew in 90 s about each axis. |
| Data | its checks pass: the margin is zero or above, and the mass memory holds the storage required. |
| Mass | the launch mass is within the launcher's capability. quicksat holds no launcher limit, so compare it yourself. |

The Budgets tab's overview, and the delta-V, agility and data notebooks, show the checks in a table, with each check's spare, margin and verdict. Write these figures down for each round. A small table, one row per round, shows the changes from round to round. In the Sizing Editor, the Budgets tab's **Export to Excel** button writes every budget into a workbook, so you can keep one for each round.

## 3. Make the change, and run the first round

The sample as it ships is already 2.89 kg short of propellant: it loads 22.0 kg and needs 24.89 kg. In this example, a new requirement makes that much worse. The satellite must make a direct re-entry at the end of its life, in place of the 500 × 250 km decay orbit.

In `manoeuvres.csv`, set the deorbit row's `value`, the perigee altitude, from `250 km` to `0 km`, and update its comment. Then run every budget.

The delta-V rises from 116.52 to 194.39 m/s, and the propellant required from 24.89 to 42.30 kg. The other budgets do not change yet, because the equipment has not changed.

**The fix.** Load more propellant, and fit a tank that holds it. In `equipment.csv`, set the hydrazine row to `42.0 kg`, close to the propellant required. Set the tank from `8.8 kg` to `13.0 kg`. The tank masses here are made up for the example. Take yours from the supplier's range.

## 4. Run every budget again

Round 2 shows the two side effects of the fix.

- **The delta-V budget is still short.** The larger tank raised the dry mass from 448.62 to 454.67 kg. More dry mass needs more propellant, so the propellant required rose to 42.87 kg, 0.87 kg above the load.
- **The agility has suffered.** `first_guess` takes the wet mass at full tanks, 496.67 kg in place of 470.62 kg. The roll inertia rose from 262.3 to 276.8 kg m². The 40° roll slew now takes 86.2 s, and its margin against 90 s fell from 8.2 % to 4.4 %.

**The fix.** Load a little more than the requirement, to cover the next round's growth: hydrazine `44.0 kg`, and the tank `13.5 kg`.

To try a dry mass before you edit any file, pass it to the delta-V budget in its notebook. The figure is not written anywhere:

```python
from quicksat import u

dv_data.propellant_mass(dry_mass=460 * u.kg)  # 43.37 kg in this example
```

Round 3 closes the delta-V budget. The propellant required is 42.94 kg, and the 44.0 kg load leaves 1.06 kg to spare. The roll margin is 4.0 %, and the pitch margin 7.4 %. The data budget has not changed, at 12.0 %, because nothing in it depends on the mass.

Every budget now passes, but the roll margin has halved. You choose whether to accept that, or to buy the margin back. This example buys it back with larger wheels: 5.0 N m s in place of 4.0 N m s, at 7.8 kg each in place of 7.0 kg. Set `momentum` in `agility_config.yaml`, and the wheel row's `unit_mass` and name in `equipment.csv`. The wheel figures are made up for the example too.

Round 4 checks the new wheels. The roll margin is back to 16.0 %, and the pitch margin is 19.3 %. The four wheels add 4.4 kg to the dry mass, with their margins and harness. So the propellant required rose again, to 43.35 kg, and the spare fell to 0.65 kg. The delta-V budget still closes.

| Round | Change | In-orbit dry mass | Propellant required / loaded | Roll, 40° in 90 s | Pitch, 40° in 90 s |
| --- | --- | --- | --- | --- | --- |
| 0 | the sample as it ships | 448.62 kg | 24.89 / 22.0 kg | +8.2 % | +11.6 % |
| 1 | direct re-entry | 448.62 kg | 42.30 / 22.0 kg | +8.2 % | +11.6 % |
| 2 | 42.0 kg loaded, 13.0 kg tank | 454.67 kg | 42.87 / 42.0 kg | +4.4 % | +7.8 % |
| 3 | 44.0 kg loaded, 13.5 kg tank | 455.39 kg | 42.94 / 44.0 kg | +4.0 % | +7.4 % |
| 4 | 5.0 N m s wheels at 7.8 kg | 459.80 kg | 43.35 / 44.0 kg | +16.0 % | +19.3 % |

The launch mass rose from 487.34 to 520.52 kg over the four rounds. Check it against the launcher.

## 5. Stop when a round changes nothing

The design has closed when one round passes every check, and you change no file after it. Round 4 is that round in the example.

Each round's change should be smaller than the one before. In the example, the shortfall went from 20.30 kg to 0.87 kg, then to a spare. If a change grows from round to round instead, more mass will not close the budget. For example, each kilogram of propellant may need so much more tank and structure that the propellant required grows faster than the load. Then change something larger: the engine's Isp, the requirement, or the design.

When the design has closed:

- **Save the files.** If you worked in the Sizing Editor, save the files from the page, and put them back in the folder. Then run the notebooks once, so that their stored figures match the files.
- **Update each notebook's change-log cell.** Set `LAST_CHANGE` and `CHANGE_NOTE` in every notebook whose inputs changed, so that its figures can be read against the change that produced them.
- **Save the notebooks with their outputs.** Then the stored figures match the files.

## 6. Carry the results beyond sizing

The scenario and the power budget take some sizing results by hand too. After a change that closes the sizing budgets, check these:

- **The slew limits.** The scenario's `slew` block takes the maximum rate and acceleration from the agility budget. New wheels change both. Copy the slower axis's figures across, as step 5 of [how to set up and run a scenario](../scenario/set_up_a_scenario.md) explains.
- **The power drawn.** New equipment, such as larger wheels, may draw more power. Update the consumption file, and run the power budget again.
- **The battery and the panels.** A larger battery or more panels add mass. Put them in `equipment.csv`, and run the sizing budgets again.

## A change of orbit

A change to `mission.yaml` reaches three budgets at once. Run the same rounds after it, but first update the inputs that depend on the orbit and that quicksat does not work out:

- **The drag make-up.** quicksat does not model drag. The drag make-up row in `manoeuvres.csv` is your figure for the altitude and the solar activity. A lower orbit needs more of it, but the budget shows this only once you change the row. Without it, a lower orbit looks cheaper, because the deorbit burn is smaller.
- **The collision avoidance count.** The number of manoeuvres each year depends on the debris at that altitude.
- **The contacts.** The contacts per day and their mean length, in `pl_dataflow_model.yaml`, depend on the altitude and the ground stations.
- **The scenario's orbit.** The scenario reads its own orbit, in `scenario.yaml`, not `mission.yaml`. Keep the two in step.

The data generated each day does not depend on the altitude. The payload collects for its duty cycle of each orbit, so a shorter period gives more orbits, each with less data. The period changes only the storage needed between contacts. The ground track speed changes the ground passed during a slew, but not the slew's time.
