# How to use a relay satellite

This guide plans a link to a data relay, another satellite that passes your data on. quicksat finds when each relay is in view, turns the body or an antenna toward one, and ends activities when it rises and sets. It gives the range to the relay too, for your link budget.

The example uses the scenario sample. Its folder holds `relays.tle`, ten made-up relays at 1200 km, and the sample links to `RELAY-01` after each eclipse. The guide goes through how that link is set up, and then makes it track the relay for the whole of each pass.

You need quicksat installed first. The README has the steps. [How to plan the activities](plan_the_activities.md) covers the Activity Designer in full, and [how to set up and run a scenario](set_up_a_scenario.md) covers each field of the scenario file.

## 1. Start the editor's server on a copy

Work on a copy of the sample, not on quicksat's own files:

```bash
python -m quicksat init my_project
python -m quicksat.editor serve my_project/scenario/data my_project/scenario/output
```

The Scenario Editor opens in your browser. Keep the terminal open while you work.

## 2. Get the relays' orbits

A satellite target takes its orbit from one file, as the scenario's own orbit does:

- **A TLE or OMM file.** CelesTrak and Space-Track give the element sets of a whole constellation in one file. quicksat picks each relay from it by name or by catalogue number.
- **A trajectory file,** in CCSDS OEM or ECSV, such as one from the relay's operator. It must cover the whole run.

Take element sets with epochs close to the run. An element set more than 7 days from either end of the run gets a warning, because SGP4 loses accuracy away from its epoch. For a run months ahead, the passes then show their pattern, but not their exact times.

## 3. Add the relays as targets

On the **Targets** tab, under **Satellite targets**, click **Add from a file…**, and choose the file. A file that holds a group lists its satellites, each with its name, its catalogue number and its epoch. Tick the relays you want, and click **add the chosen**, or **add all** for every one. Each target takes its name from the file. The page holds the file, and saves it with the scenario.

The sample has `RELAY-01` and `RELAY-06` already. In the scenario file, they read:

```yaml
sat_targets:
  RELAY-01: {tle_file: relays.tle}
  RELAY-06: {tle_file: relays.tle}
```

A relay is in view while the line between the two satellites keeps a **minimum clearance** above the Earth, 100 km by default, so that the link does not cross the atmosphere. Set a larger `min_clearance` for a link that needs more. Each target then gives two triggers, such as `RELAY-01 rise` and `RELAY-01 set`.

## 4. See when each relay is in view

Click the **Activities** tab, then **Generate scenario**. Under the timeline, **IN VIEW** has a row for each target, with a bar for each pass. To see the passes alone, run an empty list, as [step 3 of the planning guide](plan_the_activities.md#3-start-from-an-empty-list) shows.

In the sample's three orbits, `RELAY-01` comes into view 6 times, for 71.0 min in all, and `RELAY-06` 6 times, for 77.0 min. Each pass lasts between 5 and 17 min. Pick the relay whose passes fall where the link fits in your orbit. The sample links after each eclipse, when `RELAY-01` comes into view in each orbit.

In Python, `run.passes` lists every pass, with the closest range in each:

```text
  target              from [UTC]                to [UTC]  duration [min]  closest [km]
RELAY-06 2026-10-01T09:14:40.360 2026-10-01T09:31:19.978       16.660300       928.121
Svalbard 2026-10-01T09:16:55.330 2026-10-01T09:26:15.983        9.344217           NaN
RELAY-01 2026-10-01T09:21:54.794 2026-10-01T09:36:19.089       14.404917      2070.680
...
```

## 5. Point at the relay

The link's antenna must point at the relay through the link. Either the body turns, or the antenna turns on its own drive.

**The body turns,** with an attitude that points the antenna's axis at the relay. On the **Operations** tab, add it under **Attitudes**. The sample has the antenna on the -z side, which faces away from the Earth in nadir pointing:

```yaml
attitudes:
  track relay: {point: [-z, RELAY-01], constrain: [+x, velocity]}
```

Check the axis before you use it. Click **Show 3D**, and select the attitude. The arrow `-z → RELAY-01` must come out of the antenna's side of the model. [Step 9 of the 3D model guide](prepare_a_3d_model.md#9-check-the-body-axes-against-the-attitudes) explains the check.

**The antenna turns** on a one-axis drive, as an articulation. The body then stays free for other work, such as imaging. The antenna must be a part of the 3D model, with its origin on the drive axis:

```yaml
3d_model:
  file: spacecraft.glb
  articulations:
    relay antenna: {part: Relay antenna, axis: +x, point: [-z, RELAY-01]}
```

The sample's model has no antenna part, so this is only the form. One axis cannot follow every direction: where the relay lies off the plane that the drive can reach, the antenna points as close as it can.

## 6. End the activities at the relay's rise and set

The sample adds two activities after the eclipse:

| Title | Ends at | Attitude | Mode |
| --- | --- | --- | --- |
| wait for relay | `RELAY-01 rise` | nadir | idle |
| relay link | `RELAY-01 set` | track relay | downlink |

The slew into the link takes the end of the wait. So the body reaches `track relay` as the relay rises.

Click **Generate scenario**, and tick **Repeat the list** to see every orbit. Under each pass of `RELAY-01` in IN VIEW, a thin bar shows when the body points at it.

## 7. Keep the antenna on the relay until it sets

The thin bars stop short of the end of each pass. The slew out of the link, to sun pointing, takes the end of the link, as every slew takes the end of the activity before it. That turn takes up to 3.2 min, so the body leaves the relay before it sets. In the first pass, it tracks the relay for 10.58 min of the 13.78 min in view.

End the link a little after the relay sets, by more than the slew back takes. On the Activities tab, set the link's end to `RELAY-01 set + 4 min`, and generate again. The slew then takes those 4 minutes after the set, and the body tracks the relay through each pass:

| Pass | In view | Tracked, ending at `RELAY-01 set` | Tracked, ending at `RELAY-01 set + 4 min` |
| --- | --- | --- | --- |
| 10:13 UTC | 13.78 min | 10.58 min | 13.78 min |
| 11:55 UTC | 11.98 min | 9.28 min | 11.98 min |
| 13:37 UTC | 6.89 min | 6.89 min | 6.89 min |

The last pass is cut by the end of the run, so it has no slew after it. Read each row's results line too. The change must not push a later activity into the wrong light, or make a later slew start early. In the sample, every activity stays `ok`, except the last, which the run cuts at its end.

The sample's Svalbard downlink ends at `Svalbard set + 2 min` for the same reason.

## 8. Read the link in the viewer

Save into the folder, then click **Create the viewer** on the Files tab, and **Open the viewer**. Its **Targets** tab gives:

- **Passes:** every pass in time order, with its length, the time the attitude or a part points at the target, and the closest range.
- **Sources:** for each target, its file, its element set and its epoch, its passes and time in view, and how long the spacecraft points at it.
- **Targets now:** each target's range at the time cursor, and whether it is in view and pointed at.

The run's text report has a line for each target, such as `Target RELAY-01: 6 passes, 71.0 min in view.`

## 9. What quicksat leaves to you

- **The link budget.** quicksat gives the range, not the data rate. Check that the antennas close the link at the longest range of each pass.
- **The relay's side.** quicksat does not know whether the relay is free, or whether it has its own ground station in view.
- **The antenna's view.** An attitude points one axis exactly. quicksat does not check that the rest of the spacecraft leaves the antenna a clear view.
- **The data budget.** The sizing data budget counts its contacts by hand, in `pl_dataflow_model.yaml`. Add the relay links to its contacts per day and their mean length, from the tracked time above.

Details: [`scenario_ref.ipynb`](../../scenario/scenario_ref.ipynb), sections "Satellite targets" and "Articulations".
