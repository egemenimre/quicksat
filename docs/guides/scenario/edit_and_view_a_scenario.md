# How to edit, run and view a scenario

This guide takes you round the loop of the scenario and power work. You edit the input files in the editor, run them, read the results, and look at the run in the viewer. Then you change something, and go round again.

The loop is the same for a scenario folder and for a power folder. A power folder holds its own copy of the scenario, so its editor edits the scenario, the power system and the consumption together.

There are two ways round the loop. The editor's server runs the files from the page: edit, click **Create the viewer**, and look. Its Activity Designer shows the run above the list of activities as you build it. Or open a page on disk, save the files, put them back in the folder, and run a command. Step 2 starts either one.

You need quicksat installed first. The README has the steps. The sizing files have an editor of their own: see [how to edit and run the sizing files](../sizing/edit_the_sizing_files.md). What each field of the files means is in the other two guides: [how to set up and run a scenario](set_up_a_scenario.md) and [how to set up and run a power budget](../power/set_up_a_power_budget.md).

## 1. Pick a folder

To try the loop, use a sample folder: `sample/scenario/data/` or `sample/power/data/`. Their editor pages are written already, so you can skip step 2. When you are done, `git restore sample/` puts the samples back as they were.

For real work, copy a sample folder into your own project folder, outside quicksat, as the other guides say:

```bash
cp -r path/to/quicksat/sample/power/data my_project/winter
```

The steps below use `my_project/winter`.

## 2. Open the editor

### With the editor's server

```bash
python -m quicksat.editor serve my_project/winter my_project/winter/output
```

The server opens the editor in your browser, with the folder's files. The second folder is where it writes the viewer. Keep the terminal window open while you work. When you are done, click **Stop the server** at the top right of the page, or press Ctrl+C in the terminal. The server also stops by itself after 48 h with no editor page open.

Only your computer can reach the server. Its address looks like `http://localhost:8780/quicksat/editor?key=k3Xq9vTzR2mA`. The port is 8780, or the next free one if another program has it. The key at the end is a random password, new at each start, which keeps other websites out. So open the address that the server prints. A reload of the page reads the folder's files again, with quicksat's full check. A reload also loses the changes you have not saved.

### As a page on disk

```bash
python -m quicksat.editor my_project/winter my_project/winter/editor
```

This writes `my_project/winter/editor/editor.html`. Python reads the folder's files and puts them inside the page, with the 3D model and any orbit file that the scenario names. It also reads the files with quicksat's own loaders: the full check.

This page needs no Python and no server. Double-click it to open it in a browser. It cannot run the files: its **Create the viewer** button is greyed out, and says how to start the server.

A page you have already can open the folder instead: click **Open a folder…** on its first Setup step, and pick `my_project/winter`. Or drop the folder, or its files, onto the page. A single file dropped on a tab's bar replaces that tab's file. The page reads every file it knows there, and fills every step. quicksat's loaders do not read a folder opened this way, so its files have only the page's simple check, and their full check shows *not run*.

## 3. Edit

The page has two ways in, and both edit the same data:

- **Setup** takes you through every file, step by step, from the orbit to the consumption. The small **i** by a step's title opens its explanation: why the fields matter, the options and what follows from them. Each card on the other tabs has the same sign, and a section's explanation stays open or closed in both places. Back and Next are at the top.
- **The other tabs** hold the same fields by theme: orbit and time, spacecraft, targets, operations, activities, power and consumption. Use them to change one thing without going through every step. A bar at the top of each tab names its file, says where it came from and whether you have changed it, and has **Open** and **download** for that file.

The first Setup step lists the folder's files: where each came from, whether it has changed, and two checks. The **simple check** is the page's own, on names, units and ranges, as you type. The **full check** is what quicksat's loaders said when Python wrote the page. The Files tab shows both under each file.

**Ground targets** has a search box. It asks OpenStreetMap's Nominatim, so it needs a connection, and it sends the text you search for to openstreetmap.org. It finds towns, addresses and many ground stations, such as SvalSat. Press Enter or **search**, then click a result to add it. Nominatim gives no altitude, so set it yourself, or it is 0 m. Without a connection, type the position in.

**Satellite targets** adds them from a file, with **Add from a file…** or a drop: a TLE or OMM file of one satellite or of a group, or a trajectory file. A group lists its satellites, with their epochs, for you to choose from. The page holds each file, and saves and runs it with the scenario. Each target's epoch shows against the start, in amber when it is more than 7 days away.

Names are chosen from lists. An activity picks its attitude and its mode, and an articulation picks its part of the model. Renaming an attitude, a target or a mode changes every use of it. Deleting one that is in use asks again, and says what uses it.

**Show 3D**, at the top right, opens the 3D panel. It shows the model, its parts and the body axes. Click a row, such as a panel, an articulation or an attitude, to see it there: a panel's normal and area, an articulation's axis with a slider to turn it, or an attitude's two axes. The panel starts open on the steps that need it, and you can hide it on any step or tab.

The chip at the top right counts the problems that the page finds: a missing value, a name that does not exist, a percentage out of range. Click it for the list. A red count on a tab, or a red step number, shows where each problem is. The page cannot tell whether a trigger ever comes, or whether the battery lasts. Only the run can.

The page keeps no draft. Save before you close it or reload it, or your changes are lost.

### Design the activities, with the server

With the server, the Activities tab is the **Activity Designer**. The run sits above the list of activities: the orbit in 3D and the ground track, with the current data beside them, and the timeline with the illumination, the attitude, the mode and each target's passes. A dashed line marks each whole orbit.

**Generate scenario** runs the scenario as it is on the page, and shows the result above the list. It writes nothing. The first run after the server starts takes about 20 s. Later ones take a second or two for the samples. The tab runs once by itself when you first open it.

At first the list runs once, with no repeats. The time after its last activity is unplanned, and grey. The bar above the list gives the run's length and one pass of the list, in time and in orbits. Once the list covers an orbit, tick **Repeat the list**. The list then repeats until the run ends, as it does in the scenario file.

The list may be empty here. So start from nothing, to see the orbit, the eclipses and the passes first. Then add the activities one at a time, and generate after each. For the power sample, a list could start like this:

| # | Title | Ends at | Attitude | Mode | Expects |
|---|---|---|---|---|---|
| 1 | idle until eclipse exit | eclipse exit | sun pointing | idle | anything |
| 2 | idle until Svalbard rise | Svalbard rise | sun pointing | idle | anything |
| 3 | downlink until Svalbard set | Svalbard set | track Svalbard | downlink | anything |
| 4 | idle until latitude 45 deg | latitude 45 deg ascending | sun pointing | idle | anything |
| 5 | image from latitude 45 deg | 8 min | yaw steering | imaging | sunlit |

Under each title, a line says what the last run made of the activity: how many times it came, any problem, and any turn faster than the slew block allows. In the power sample, the downlink tracks Svalbard at up to 0.84 deg/s, past the slew block's 0.7 deg/s. An amber band marks that on the timeline, and the warning shows above the list. A row that you change reads *changed since the last run* until you generate again.

Select a row to see its activity in the run: a box round each of its occurrences on the timeline, and its part of the track thicker and brighter, on the map and on the orbit. A click on the timeline, or on the track, selects the activity under way there, and brings its row into view. Drag the bar between the run and the list to share the height. The browser remembers it.

**Save into the folder** writes the scenario file into the folder that the server reads, after a confirm. It refuses an empty list, and a file that changed on disk since the page read it. Reload the page then, to see the file as it is now. The other files save as step 5 says.

[How to plan the activities](plan_the_activities.md) builds a plan in the designer, step by step, and says what to do about each warning.

## 4. Move your `#` comments into `comments` fields

Saving rewrites each file. It writes the editor's own help as `#` lines, and drops every other `#` comment. Your notes are kept only in the `comments` fields that every block of a file has.

If the files hold `#` comments that the editor did not write, a banner under the header says so. Click **review them**, or open the Files tab. Each comment is listed with its file, its line, and the block it belongs to:

- **move** puts it in that block's `comments` field;
- **drop** lets it go;
- **move all** and **drop all** do the same for every comment left.

Do this before you first save a file that you wrote by hand. The samples' explanations show up here too: they are `#` comments. Each comment goes to the block below it, so write your own `#` comments on the lines above what they describe.

## 5. Save, and put the files back

With the server, you can skip this step until you want to keep your changes: step 6 runs the files as they are on the page. The server writes into the folder only when you click **Save into the folder** on the Activities tab.

Open the Files tab to see each file as it will be written. Then save, from there or from the last Setup step:

- **download the zip** gives the whole folder in one file;
- **download** next to a file, or on a tab's bar, gives that file alone.

A saved file shows as *downloaded*, or *saved into the folder*, until you change it again.

The browser puts the downloads in its downloads folder. Copy the files over the ones in `my_project/winter/`. Check their names: a browser can add a number, such as `scenario (1).yaml`, to a file it has downloaded before.

Until you save, the page keeps your changes in the browser's storage, on this computer only. When you reload the page, or open it again, a bar offers this draft: **restore** puts the changes back, and **discard** drops them. A change on the page discards the draft too. The bar says if a file in the folder has changed on disk since. The draft goes once every file is saved.

## 6. Run

**With the server,** click **Create the viewer**. It is in the Files tab, under the download button, and on the last Setup step, **Save and view**. The run uses the files as they are on the page, saved or not. It writes the viewer into the output folder you gave the server, and does not change the folder's files. The button reads *Running…* until the run ends, a few seconds for the samples.

When it ends, the panel says where the viewer went, and **The run's results** shows what the command line would print. A file that quicksat cannot read stops the run. The panel then shows quicksat's message, and the file's full check reads *refused*. Fix the file, and click again: the button now reads **Update the viewer**.

If the server has stopped, the button is greyed out, with the command that starts it again.

**Without the server,** run the folder from the command line. For a power folder:

```bash
python -m quicksat.power my_project/winter my_project/winter/output
```

For a scenario folder, with no power files, use `python -m quicksat.scenario` in the same way. Either prints the results, writes the viewer into the output folder, and prints the page's path. A file that quicksat cannot read stops the run with an error that names the problem, and nothing is written. Fix it in the editor, and save again.

For the tables and the plots, run a notebook instead. For a sample folder, that is [`sample/scenario/scenario.ipynb`](../../../sample/scenario/scenario.ipynb), or [`sample/power/power_budget.ipynb`](../../../sample/power/power_budget.ipynb) for the power. For your own folder, run the code in step 8 of the [scenario guide](set_up_a_scenario.md#8-run-the-scenario), or in step 6 of the [power guide](../power/set_up_a_power_budget.md#6-run-the-budget), with your folder's path.

## 7. Read the results

- **The scenario:** the summary line and the `status` column of the activity table. Every status should be `ok`, or `cut at end` for the last activity. Step 9 of the [scenario guide](set_up_a_scenario.md#9-check-the-activities) says what to do about each other status.
- **The power:** the three checks, and each orbit's energy in `orbit_table`. Step 7 of the [power guide](../power/set_up_a_power_budget.md#7-check-the-budget) says what to do when a check fails.

## 8. Open the viewer

The run writes the viewer's page into the output folder: `scenario_viewer.html` for a scenario, and `power_viewer.html` for a power budget. With the server, click **Open the viewer** by the button. It opens the viewer in a browser tab of its own, and each click opens it in the same tab again. Without the server, double-click the page. It shows the run in 3D, with the ground track, the timeline and the activity table, and the power if there is one. Its Attitude tab shows the roll, pitch and yaw, the turn rate and the acceleration, and the warnings, and offers the attitude files for download.

If the page is open already, reload it after each run. It then reads the new run.

## 9. Go round again

With the server, keep editing on the same page, and click **Update the viewer** after each change. Then reload the viewer's tab, or click **Open the viewer** again. Save the files when you want to keep them, as step 5 says. One round is then: edit, update the viewer, read, view.

Without the server, if the page is still open, keep editing: it holds your changes. If you closed it, open it again and click **Open a folder…** to read the folder's files as they are now. Or write the page again, to have quicksat's loaders check the files too:

```bash
python -m quicksat.editor my_project/winter my_project/winter/editor
```

Then reload the page in the browser. One round is then: edit, save, put the files back, run, read, view, and open the folder again.
