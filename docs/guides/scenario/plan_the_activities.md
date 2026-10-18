# How to plan the activities

This guide builds a list of activities in the Activity Designer, from an empty list to a plan for the whole run. You add one activity at a time, run the list, and read what the run made of it. The designer shows the result above the list in a second or two, so you can try a change and see it at once.

The example plans the power sample's spacecraft: it waits for the sun after each eclipse, downlinks to Svalbard, and images from 45° north. The same steps work for any scenario folder.

You need quicksat installed first. The README has the steps. What each field of the scenario file means is in [how to set up and run a scenario](set_up_a_scenario.md). The rest of the editor is in [how to edit, run and view a scenario](edit_and_view_a_scenario.md).

## 1. Start the editor's server on a copy

The designer runs quicksat through the editor's server, which runs on your computer only. Work on a copy of the sample, not on quicksat's own files:

```bash
python -m quicksat init my_project
python -m quicksat.editor serve my_project/power/data my_project/power/output
```

The Scenario Editor opens in your browser. Keep the terminal open while you work.

## 2. Open the Activity Designer

Click the **Activities** tab. The run sits above the list of activities:

- the **orbit** in 3D, coloured as the ground track is. Drag to turn it, scroll to zoom, and click **Reset view** to go back. The spacecraft is its red marker. On a narrow screen, the map's **3D Orbit View** button hides it, to give the map its width;
- the **ground track**, with the current data beside it: the time, the orbits since the start, the activity under way, its mode and attitude, the light and the targets in view;
- the **timeline**, with the illumination, the attitude and the mode, and a dashed line at each whole orbit;
- **IN VIEW**, under it: a row for each target, with a bar for each pass, and a thin bar for the time the spacecraft points at it.

The tab runs the list once by itself. The first run after the server starts takes about 20 s, while astropy loads its tables. Later runs take a second or two.

Drag the bar between the run and the list to share the height. The browser remembers it.

## 3. Start from an empty list

Delete every activity with its **delete** button, then click **Generate scenario**. The designer runs an empty list, and shows what does not depend on the activities: the orbit, the eclipses and the passes over Svalbard. The attitude and mode rows are grey: no activity plans the run yet.

Read the bar above the list. It gives the run's length, such as "4 h 45 min, 3.00 orbits". Then look for the events that you will end activities at: where the eclipses start and end, and when each target comes into view.

An empty list is fine in the designer, but a saved file needs at least one activity.

## 4. Add an activity, and run it

Click **+ activity**, then set its fields:

- **title:** what it is for, such as `idle until eclipse exit`;
- **ends at:** the trigger that ends it;
- **attitude** and **mode:** chosen from the names that the Operations tab defines;
- **expects:** the light it needs, or `anything`.

Each activity starts where the one before ends. So the trigger decides when the next one starts. The triggers:

| Ends at | When to use it |
| --- | --- |
| after a duration | A fixed time, such as an image strip of 8 min. |
| eclipse entry, eclipse exit | The edges of the shadow, penumbra included. Use them to switch to and from charging. |
| umbra entry, umbra exit | The edges of the full shadow. |
| ascending node, descending node | The equator crossings, once per orbit each. |
| latitude crossing | A latitude, going north, south or either. Use it to start imaging over a region. |
| a target rises, a target sets | When a ground station or another satellite comes into view, and goes out of it. Use them to start and end a downlink with a pass. |

An event can take an offset, such as `eclipse entry - 2 min`, to end an activity a little before or after it.

Click **Generate scenario** after each activity. The list runs once, so the grey time after it shows how far the list reaches. The bar gives the length of one pass of the list, in time and in orbits.

For the power sample, build this list one row at a time:

| # | Title | Ends at | Attitude | Mode | Expects |
|---|---|---|---|---|---|
| 1 | idle until eclipse exit | eclipse exit | sun pointing | idle | anything |
| 2 | idle until Svalbard rise | Svalbard rise | sun pointing | idle | anything |
| 3 | downlink until Svalbard set | Svalbard set | track Svalbard | downlink | anything |
| 4 | idle until latitude 45 deg | latitude 45 deg ascending | sun pointing | idle | anything |
| 5 | image from latitude 45 deg | 8 min | yaw steering | imaging | sunlit |

After row 3, the IN VIEW row shows the thin bar under the Svalbard pass: the spacecraft tracks the station through it.

## 5. Read what the run made of each activity

Under each title, a line says what the last run made of the activity. First comes how many times it came, such as `once`. Each problem then has a line of its own. A failure is red, and starts with **FAIL**. A warning is amber, and starts with **WARNING**. A row that you change since the run reads *changed since the last run*, until you generate again.

| Line | What to do |
| --- | --- |
| FAIL: outside constraint | The activity spends time in the wrong light. End the activity before it at the shadow edge, or change what it expects. |
| FAIL: negative duration | An offset ends the activity before it starts. Make the offset smaller, or end it at another event. |
| WARNING: event never came | The event does not happen in the run, such as a pass that never comes. Pick another event, or run longer. |
| WARNING: slew starts early | The turn into this activity takes longer than the activity before it. Lengthen that activity, or raise the slew limits if the satellite can turn faster. |
| WARNING: turns faster than the slew limits | The attitude turns the body faster than the slew block allows, as tracking does near the zenith of a pass. |
| cut at end | The run ends during the activity. That is normal for the last one. |

In the power sample, row 3 reads "WARNING: turns faster than the slew limits once: 0.84 deg/s, limit 0.7 deg/s". The same warning, in full, shows above the list, and an amber band marks the time on the timeline. Over a station near the zenith of a pass, the line of sight turns faster than the sample's slew block allows. Raise the limits on the Operations tab if the satellite can turn that fast. Or raise the station's minimum elevation, on the Targets tab, so that the downlink ends before the steepest part of the pass.

## 6. Find an activity in the run

Select a row. Each occurrence of its activity gets a box on the timeline. Its part of the track turns thick and bright, on the map and on the orbit, with the rest dimmed. The other way round, click the timeline, or the track on the map: the time cursor moves there, and the activity under way then is selected in the list.

Use **Full**, **1 orbit** and **30 min**, over the timeline, to zoom. Drag across the timeline to zoom in on a stretch, and double-click to zoom out. The view stays where it is from one run to the next.

## 7. Repeat the list

Once one pass of the list covers about an orbit, tick **Repeat the list**. The list then repeats until the run ends, as the scenario file does. Each row's line now counts its repeats, such as `3 times`.

Read the lines again: an event can move from one orbit to the next. A pass over Svalbard can come later in the orbit, or not at all, and a list that worked once can fail in a later repeat. The last activity of the run is usually `cut at end`.

## 8. Save, and run the power

Click **Save into the folder**. After a confirm, the server writes the scenario file into `my_project/power/data/`. It refuses a file that changed on disk since the page read it: reload the page then, to see the file as it is now. The `#` comments that you wrote by hand in the file are lost on saving: move them into `comments` fields first, as [step 4 of the editing guide](edit_and_view_a_scenario.md#4-move-your--comments-into-comments-fields) says.

The designer runs the scenario alone. For the power with your new list, click **Create the viewer** on the Files tab, then **Open the viewer**. Or run the notebook or the command, as [step 6 of the editing guide](edit_and_view_a_scenario.md#6-run) says.
