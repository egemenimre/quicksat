# How to edit and run the sizing files

This guide takes you round the loop of the sizing work. You edit the input files in the Sizing Editor, and its Budgets tab shows every budget as quicksat works it out. With the editor's server, the budgets follow each change you make. The notebooks show the same budgets, step by step. Then you change something, and go round again.

The Sizing Editor edits the mission, the requirements, and the files of the four sizing budgets: mass, data, delta-V and agility. The scenario and power files have an editor of their own: see [how to edit, run and view a scenario](../scenario/edit_and_view_a_scenario.md).

You need quicksat installed first. The README has the steps. What each file holds, and how to load it in Python, is in [how to initialise a satellite for analysis](initialise_a_satellite.md).

## 1. Pick a folder

To try the loop, use the sample folder, `sample/sizing/data/`. Its editor page is written already, so you can skip step 2. When you are done, `git restore sample/` puts the sample back as it was.

For real work, copy the sample folder into your own project folder, outside quicksat:

```bash
cp -r path/to/quicksat/sample/sizing/data my_satellite
```

The steps below use `my_satellite`. The folder need not hold every budget's files. The page starts any that are missing, as new, for you to fill in.

## 2. Write the editor page, or serve it

```bash
python -m quicksat.editor my_satellite my_satellite/editor
```

This writes `my_satellite/editor/editor.html`. Python reads the folder's files and puts them inside the page. It also reads the files with quicksat's own loaders: the full check. The command picks the editor from the files: a folder with a `scenario.yaml` gets the Scenario Editor, and a folder of sizing files gets the Sizing Editor.

The page needs no Python and no server. Double-click it to open it in a browser. Its Budgets tab shows the budgets as quicksat worked them out when Python wrote the page.

To have the budgets follow your changes, serve the page instead:

```bash
python -m quicksat.editor serve my_satellite
```

The server opens the editor in your browser, from your own computer. If it does not, open the address that the server prints, such as `http://localhost:8780/quicksat/editor?key=...`. The page then sends its files to the server a moment after each change, and the server works out every budget again, in about a second. It writes nothing into the folder. Keep the terminal open while you work. When you are done, click **Stop the server** at the top right of the page, or press Ctrl+C in the terminal. The server also stops by itself after 48 h with no editor page open.

A page you have already can open the folder instead: click **Open a folder…** on its first Setup step, and pick `my_satellite`. Or drop the folder, or its files, onto the page. A single file dropped on a tab's bar replaces that tab's file. The page reads every sizing file it finds there. quicksat's loaders do not read a folder opened this way, so its files have only the page's simple check, and their full check shows *not run*.

## 3. Edit

The page has two ways in, and both edit the same data:

- **Setup** takes you through every file, step by step: the mission, then each budget in turn. The small **i** by a step's title opens its explanation: why the fields matter, the options and what follows from them. Back and Next are at the top.
- **The other tabs** hold one file or one budget each: Mission, Requirements, Mass, Equipment, Data, Delta-V and Agility. Use them to change one thing without going through every step. A bar at the top of each tab names its file, says where it came from and whether you have changed it, and has **Open** and **download** for that file.

The first Setup step lists the files by budget. The mission file comes first, because the data, delta-V and agility budgets all read it. The requirements file follows, because the data and agility budgets check their figures against it. Each file shows where it came from, whether it has changed, and two checks. The **simple check** is the page's own, on names, units and ranges, as you type. The **full check** is what quicksat's loaders said when Python wrote the page. The Files tab shows both under each file.

The Mission step, and each budget's first step, have a box for your comments on the file as a whole. They go in the `comments` field at the top of the file.

Some steps work out figures from the fields as you type. The Mission step gives the orbital period, the orbits a day, the orbital speed and the ground track speed. The data generation step gives the data rate after compression. These are first figures only: the notebooks give the budgets' own.

**The Equipment tab** holds the equipment list as a table. The box above it shows only the rows that hold its text, in the id, the name, the location or another column. The location is chosen from the locations of the Mass tab. The totals under the table add the rows by location, as entered and with the equipment margins. The notebook also adds the harness and the system margins, so its totals are larger.

Renaming a location changes every row that uses it. Deleting one that is in use asks again, and says what uses it.

The chip at the top right counts the problems that the page finds: a missing value, a location that does not exist, a percentage out of range. Click it for the list. A red count on a tab, or a red step number, shows where each problem is. The page cannot tell whether the satellite meets its needs. Only the notebooks can.

The page keeps no draft. Save before you close it or reload it, or your changes are lost.

## 4. Read the budgets

The **Budgets** tab, after Setup, shows every budget as quicksat works it out, with the same methods as the notebooks. A list on its left holds the overview and the four budgets, each with a mark: ✓ when its checks pass, ✕ when one fails, and – when it has no check. The tab's title shows how many budgets have a failing check, so you see the effect of a change from any tab.

- **Overview** gives each budget's deciding figures, and every check: what is checked, the design's figure, the limit, the spare, the margin, and the files that the limit comes from.
- **Mass, Delta-V, Data and Agility** each give the budget's table, the one its notebook shows, with the smaller tables beside it. The controls match the notebook's options, such as the mass in orbit or on the ground, the axis, the inertia case, and one wheel failed. The agility checks use the selected inertia case, which the Agility tab sets.

A page that the server sent says when it last worked out the budgets. A page opened from a file shows the figures from when Python wrote it. Once you change a file, it names the files changed since, and greys the figures, as they may be out of date.

A budget whose files the folder lacks has no figures. A budget that quicksat cannot work out shows its error in place of its tables, such as a file that quicksat refuses.

## 5. Move your `#` comments into `comments` fields

Saving rewrites each file. It writes the editor's own help as `#` lines, and drops every other `#` comment. Your notes are kept only in the `comments` fields that every block of a YAML file has. A CSV file has a `comments` column instead, which the page keeps as written.

If the files hold `#` comments that the editor did not write, a banner under the header says so. Click **review them**, or open the Files tab. Each comment is listed with its file, its line, and the block it belongs to:

- **move** puts it in that block's `comments` field;
- **drop** lets it go;
- **move all** and **drop all** do the same for every comment left.

Do this before you first save a file that you wrote by hand. The sample's explanations show up here too: they are `#` comments. Each comment goes to the block below it, so write your own `#` comments on the lines above what they describe.

## 6. Save, and put the files back

Open the Files tab to see each file as it will be written. Then save, from there or from the last Setup step:

- **download my_satellite.zip**, named after the folder, gives the whole folder in one file;
- **download** next to a file, or on a tab's bar, gives that file alone.

The page always saves every budget's files. A saved file shows as *downloaded* until you change it again. To leave out the `#` help lines, untick **write the # help lines** before you save.

The browser puts the downloads in its downloads folder. Copy the files over the ones in `my_satellite/`. Check their names: a browser can add a number, such as `mission (1).yaml`, to a file it has downloaded before.

Until you save, the page keeps your changes in the browser's storage, on this computer only. When you reload the page, or open it again, a bar offers this draft: **restore** puts the changes back, and **discard** drops them. A change on the page discards the draft too. The bar says if a file in the folder has changed on disk since. The draft goes once every file is saved.

## 7. Run the notebooks

The notebooks show each budget step by step, with what each figure means, and let you try a case that the files do not hold. The sizing budgets have no command-line run. Run each one in its notebook:

- [`sample/sizing/mass_budget.ipynb`](../../../sample/sizing/mass_budget.ipynb)
- [`sample/sizing/data_budget.ipynb`](../../../sample/sizing/data_budget.ipynb)
- [`sample/sizing/delta_v_budget.ipynb`](../../../sample/sizing/delta_v_budget.ipynb)
- [`sample/sizing/agility_roll.ipynb`](../../../sample/sizing/agility_roll.ipynb) and [`sample/sizing/agility_pitch.ipynb`](../../../sample/sizing/agility_pitch.ipynb)

Each notebook reads its files from `DATA`, which is `sample/sizing/data` in the samples. For your own folder, copy the notebook into your project, and set `DATA` to your folder's path:

```python
DATA = Path("my_satellite")
```

Or load the budgets in a notebook of your own, with the code in step 3 of [how to initialise a satellite](initialise_a_satellite.md#3-load-the-satellite).

A file that quicksat cannot read stops the notebook with an error that names the file, the row and the field. Fix it in the editor, and save again. Step 4 of [how to initialise a satellite](initialise_a_satellite.md#4-check-that-it-loaded) lists the most common causes.

## 8. Go round again

With the server, one round is: edit, and read the Budgets tab. Save the files once the budgets close, and put them back in the folder.

Without the server, if the page is still open, keep editing: it holds your changes. If you closed it, open it again and click **Open a folder…** to read the folder's files as they are now. Or write the page again, to have quicksat's loaders check the files and work out the budgets again:

```bash
python -m quicksat.editor my_satellite my_satellite/editor
```

Then reload the page in the browser. One round is then: edit, save, put the files back, write the page again or run the notebooks, read the results, and open the folder again.

[How to close the sizing budgets](close_the_sizing_budgets.md) says which results to carry into the files after each round, and when to stop.
