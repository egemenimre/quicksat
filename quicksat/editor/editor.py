# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The editor: a web page that fills in and edits a folder of input files.

The folder holds a scenario file and, if it is a power folder, a power system
file and a consumption file, with the 3D model and any orbit file they name.
`write_editor` writes one page for it. The page opens from disk with a
double-click, and needs no Python and no server. `quicksat.editor.server` can
also serve the page from this computer. Its page then has a button that runs the
files and writes the viewer.

The page holds the folder's files inside itself. Python reads them here and
passes them to the page as JSON: each YAML file as YAML reads it, the CSV as rows
of text, the 3D model in base64, and an orbit file as text. The page turns them
into its own fields. The user can also open another folder, or one file, in the
page, which reads them in the same form. When the user saves, the page writes
the files again, as downloads: one by one, or as a zip.

Saving rewrites each file. The user's notes survive in the `comments` fields,
which every block of a file has. A `#` comment does not survive: the page writes
its own help as `#` lines, and replaces the rest. So this module also finds every
`#` comment, with the key it belongs to. The page lists the ones it did not
write, so that the user can move each into that key's comments before saving.

When the page is written, quicksat also reads the files with its own loaders.
The page shows what they said, because its own checks cover names, units and
ranges only.

"""

import base64
import csv
import io
import json
from datetime import date, datetime
from importlib.resources import files
from pathlib import Path

import yaml

from quicksat.power import CONSUMPTION_FILE, POWER_FILE
from quicksat.scenario import SCENARIO_FILE

FORMAT = "quicksat-editor"
"""The `format` field of the data the page holds."""

VERSION = 1
"""The `version` field of the data the page holds. It stays the same during
development, even when a field changes. It goes up only once older pages must
still be read."""

PAGE_FILE = "editor.html"
"""Name of the page written in the output folder."""

_PACKAGE = files("quicksat")
_TEMPLATES = _PACKAGE / "editor" / "templates"
_HELP = _PACKAGE / "editor" / "help"
_VENDOR = _PACKAGE / "scenario" / "templates" / "vendor"

_ORBIT_FILES = ("tle_file", "omm_file", "trajectory_file")
"""The orbit's keys that name a file."""

SHARED_SCRIPTS = ("base.js", "files.js", "open.js", "frame.js")
"""The scripts in `templates/shared/` that every editor page runs first: the
field controls, the file writing, the opening of files in the browser, and the
page's frame. `templates/shared/editor.css` holds the styles they share."""

SCRIPTS = (
    "elements.js",
    "project.js",
    "sections.js",
    "checks.js",
    "write.js",
    "run.js",
    "view3d.js",
    "views.js",
)
"""The scenario editor's own scripts in `templates/scenario/`, in the order they
run after the shared ones."""


def _json_default(value):
    """
    Turns what YAML reads but JSON cannot hold into text.

    Parameters
    ----------
    value
        A value that `json.dumps` cannot write

    Returns
    -------
    text : str
        A date or a time in ISO form

    Raises
    ------
    TypeError
        For anything else
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"cannot pass {value!r} to the page")


def _key_lines(text: str) -> list[tuple[int, int, list]]:
    """
    The place of every key and every list item in a YAML text, with its path.

    Parameters
    ----------
    text : str
        The YAML text

    Returns
    -------
    keys : list of tuple
        The line and the column, counted from 0, and the path, such as
        `["attitudes", "nadir"]` or `["activities", 2]`, in the order of the
        file. A key comes before the keys inside it, so the first entry of a line
        is the outermost.
    """
    found: list[tuple[int, int, list]] = []

    def walk(node, path: list) -> None:
        if isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                here = [*path, key.value]
                found.append((key.start_mark.line, key.start_mark.column, here))
                walk(value, here)
        elif isinstance(node, yaml.SequenceNode):
            for index, item in enumerate(node.value):
                here = [*path, index]
                found.append((item.start_mark.line, item.start_mark.column, here))
                walk(item, here)

    walk(yaml.compose(text), [])
    return found


def _inline_comment(line: str) -> str | None:
    """
    The comment at the end of a line of YAML, outside any quotes.

    Parameters
    ----------
    line : str
        A line that does not start with `#`

    Returns
    -------
    comment : str or None
        The text after the `#`, or None if the line has no comment
    """
    quote = None
    for index, char in enumerate(line):
        if quote is not None:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "#" and index > 0 and line[index - 1] in " \t":
            return line[index + 1 :].strip()
    return None


def comment_blocks(text: str) -> list[dict]:
    """
    Every `#` comment in a YAML text, with the key it belongs to.

    Comments go above what they describe. Lines of comment with nothing between
    them form one block. A block belongs to the first key below it, or to the
    file if no key follows. A block with a blank line between it and that key
    belongs to the section that holds the key, or to the file at the top level.
    A block that is indented more than that key closes a section, such as a
    comment after the last attitude: it belongs to the section of the keys at
    its own indent. A comment at the end of a line belongs to the outermost key
    on that line.

    Parameters
    ----------
    text : str
        The YAML text

    Returns
    -------
    blocks : list of dict
        `line`, the first line, counted from 1; `text`, the comment without its
        `#` signs, one line of text for each line of comment; `path`, the key's
        path, empty for the file; and `inline`, true for a comment at the end of
        a line
    """
    keys = _key_lines(text)
    blocks = []
    current = None
    for number, line in enumerate(text.splitlines()):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            body = stripped[1:]
            body = body[1:] if body.startswith(" ") else body
            if current is not None and current["end"] == number - 1:
                current["lines"].append(body)
                current["end"] = number
            else:
                indent = len(line) - len(stripped)
                current = {"start": number, "end": number, "lines": [body]}
                current["indent"] = indent
                blocks.append(current)
            continue
        current = None
        comment = _inline_comment(line)
        if comment is not None:
            path = next((path for line, _, path in keys if line == number), [])
            blocks.append(
                {"start": number, "end": number, "lines": [comment], "path": path}
            )
    lines = text.splitlines()
    out = []
    for block in blocks:
        path = block.get("path")
        inline = path is not None
        if not inline:
            path = _owner(keys, block, lines)
        out.append(
            {
                "line": block["start"] + 1,
                "text": "\n".join(block["lines"]).strip("\n"),
                "path": path,
                "inline": inline,
            }
        )
    return out


def _owner(keys: list[tuple[int, int, list]], block: dict, lines: list[str]) -> list:
    """
    The path of the key that a block of full-line comments belongs to.

    Parameters
    ----------
    keys : list of tuple
        The keys, from `_key_lines`
    block : dict
        The block, with its first and last lines and its indent
    lines : list of str
        The text's lines

    Returns
    -------
    path : list
        The first key below the block. If that key is less indented than the
        block, the section of the last key above the block at the block's own
        indent. If a blank line comes between the block and the key, the section
        that holds the key. Empty for the file.
    """
    below = next(
        ((line, col, path) for line, col, path in keys if line > block["end"]), None
    )
    if below is None:
        return []
    key_line, column, path = below
    if column < block["indent"]:
        siblings = [
            above
            for line, col, above in keys
            if line < block["start"] and col == block["indent"]
        ]
        if siblings:
            return siblings[-1][:-1]
    after = block["end"] + 1
    if after < key_line and not lines[after].strip():
        return path[:-1]
    return path


def _check(label: str, read) -> dict:
    """
    What one of quicksat's loaders says of a file, or of files read together.

    Parameters
    ----------
    label : str
        The file's name, such as `scenario.yaml`, or the files' names, such as
        `equipment.csv with mass_budget_config.yaml`
    read : callable
        Reads the files with the loader, and takes no argument

    Returns
    -------
    check : dict
        `file`, the label; `ok`; and `message`, the loader's error, or empty
    """
    try:
        read()
    except Exception as exc:  # the page shows any failure, whatever its kind
        return {"file": label, "ok": False, "message": str(exc)}
    return {"file": label, "ok": True, "message": ""}


def _yaml_file(path: Path) -> dict:
    """
    A YAML file for the page: its name, its data and its comments.

    Parameters
    ----------
    path : Path
        The file

    Returns
    -------
    file : dict
        `name`, `data` as YAML reads it, and `comments` from `comment_blocks`
    """
    text = path.read_text(encoding="utf-8")
    return {
        "name": path.name,
        "data": yaml.safe_load(text),
        "comments": comment_blocks(text),
    }


def _csv_file(path: Path) -> dict:
    """
    A CSV file for the page: its name, its header, and its rows of text.

    Parameters
    ----------
    path : Path
        The file

    Returns
    -------
    file : dict
        `name`, `header`, the first row, and `rows`, the others that are not empty
    """
    rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))
    return {
        "name": path.name,
        "header": rows[0] if rows else [],
        "rows": [row for row in rows[1:] if any(cell.strip() for cell in row)],
    }


def _referenced(folder: Path, name) -> Path | None:
    """
    A file that the scenario names, taken from the folder if relative.

    Parameters
    ----------
    folder : Path
        The scenario file's folder
    name
        The name as the file gives it, or None

    Returns
    -------
    path : Path or None
        The file, or None if no file is named or it does not exist
    """
    if not isinstance(name, str) or not name.strip():
        return None
    path = Path(name)
    path = path if path.is_absolute() else folder / path
    return path if path.is_file() else None


def editor_data(
    folder: str | Path,
    scenario_file: str = SCENARIO_FILE,
    power_file: str = POWER_FILE,
    consumption_file: str = CONSUMPTION_FILE,
) -> dict:
    """
    Everything the page needs from a folder of input files.

    Parameters
    ----------
    folder : str | Path
        The folder that holds the files
    scenario_file : str, optional
        The scenario file's name. It must exist.
    power_file, consumption_file : str, optional
        The power system file's and the consumption file's names. Either may be
        missing, as in a scenario folder.

    Returns
    -------
    data : dict
        `format`, `version` and `folder`, the folder's name. `label`, the
        folder as given when relative, such as `sample/power/data`, and its name
        otherwise, so that no local path goes into the page. `files`, with
        `scenario`, `power` and `consumption`, each None when missing. `model`,
        the 3D model in base64, and `orbit_file`, an orbit file as text, each
        None without one. `target_files`, the files that the satellite targets
        name, as text, once each, each with its `name` as the scenario gives it.
        `checks`, what quicksat's loaders said of each file.

    Raises
    ------
    FileNotFoundError
        If there is no scenario file
    """
    # here, so that the editor's imports stay light for the page alone
    from quicksat.power.config import PowerSystem
    from quicksat.power.consumption import PowerConsumption
    from quicksat.scenario.config import Scenario

    folder = Path(folder)
    scenario_path = folder / scenario_file
    if not scenario_path.is_file():
        raise FileNotFoundError(f"no scenario file: {scenario_path}")
    scenario = _yaml_file(scenario_path)
    checks = [
        _check(scenario_path.name, lambda: Scenario.from_yaml_file(scenario_path))
    ]
    raw = scenario["data"] if isinstance(scenario["data"], dict) else {}

    power = None
    power_path = folder / power_file
    if power_path.is_file():
        power = _yaml_file(power_path)
        checks.append(
            _check(power_path.name, lambda: PowerSystem.from_yaml_file(power_path))
        )

    consumption = None
    consumption_path = folder / consumption_file
    if consumption_path.is_file():
        consumption = _csv_file(consumption_path)
        checks.append(
            _check(
                consumption_path.name,
                lambda: PowerConsumption.from_csv(consumption_path),
            )
        )

    spacecraft = raw.get("3d_model")
    spacecraft = spacecraft.get("file") if isinstance(spacecraft, dict) else spacecraft
    model_path = _referenced(folder, spacecraft)
    model = None
    if model_path is not None:
        model = {
            "name": str(spacecraft),
            "glb_base64": base64.b64encode(model_path.read_bytes()).decode("ascii"),
        }

    orbit = raw.get("orbit")
    orbit = orbit if isinstance(orbit, dict) else {}
    orbit_file = None
    for key in _ORBIT_FILES:
        path = _referenced(folder, orbit.get(key))
        if path is not None:
            orbit_file = {"name": str(orbit[key]), "text": path.read_text("utf-8")}

    target_files = {}
    targets = raw.get("sat_targets")
    for target in (targets if isinstance(targets, dict) else {}).values():
        for key in _ORBIT_FILES:
            name = target.get(key) if isinstance(target, dict) else None
            path = _referenced(folder, name)
            if path is not None and str(name) not in target_files:
                target_files[str(name)] = path.read_text("utf-8")

    return {
        "format": FORMAT,
        "version": VERSION,
        "folder": folder.resolve().name,
        "label": folder.as_posix() if not folder.is_absolute() else folder.name,
        "files": {"scenario": scenario, "power": power, "consumption": consumption},
        "model": model,
        "orbit_file": orbit_file,
        "target_files": [
            {"name": name, "text": text} for name, text in target_files.items()
        ],
        "checks": checks,
    }


def _script_json(value) -> str:
    """
    JSON that is safe inside a script tag.

    Parameters
    ----------
    value
        The value to write

    Returns
    -------
    text : str
        Compact JSON, with every `</` written `<\\/` so that no text ends the
        tag early. JSON reads `\\/` as `/`.
    """
    text = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), default=_json_default
    )
    return text.replace("</", "<\\/")


def help_text(domains: tuple[str, ...]) -> dict:
    """
    The help of some domains, from their files in `help/`, for a page to hold.

    Each key is a step of the editor, a key of the files, or both. It holds the
    step's `title` and `info`, the information box, and the `file` help that the
    editor writes above the key when it saves. So the page and the files it saves
    read the same text.

    Parameters
    ----------
    domains : tuple of str
        The help files' names, such as `("scenario", "power")`

    Returns
    -------
    help : dict
        Each key's help, from all the domains

    Raises
    ------
    ValueError
        If two domains hold the same key
    """
    text = {}
    for domain in domains:
        found = yaml.safe_load((_HELP / f"{domain}.yaml").read_text(encoding="utf-8"))
        twice = text.keys() & found.keys()
        if twice:
            raise ValueError(f"the help of {domain} repeats {', '.join(sorted(twice))}")
        text |= found
    return text


def _vendor(name: str) -> str:
    """
    A library from the viewer's vendor folder, with its licence in front.

    Parameters
    ----------
    name : str
        The library's file, such as `three.min.js`. Its licence is the file of
        the same name before the first dot, with `.LICENSE`.

    Returns
    -------
    text : str
        The licence, as a comment that minifiers keep, then the library
    """
    notice = (_VENDOR / f"{name.split('.')[0]}.LICENSE").read_text(encoding="utf-8")
    return f"/*!\n{notice}*/\n" + (_VENDOR / name).read_text(encoding="utf-8")


def build_page(
    page: str,
    scripts: tuple[str, ...],
    data: dict,
    domains: tuple[str, ...],
    **parts: str,
) -> str:
    """
    An editor page, from its template, the shared parts and its own scripts.

    Parameters
    ----------
    page : str
        The page's folder in `templates/`, such as `scenario` or `sizing`. It
        holds the page's `editor.html` and its own scripts.
    scripts : tuple of str
        The page's own scripts, in the order they run, after the shared ones
    data : dict
        The folder's files, which go in the page as JSON
    domains : tuple of str
        The domains whose help the page holds, from `help_text`
    **parts : str
        Any other placeholder of the template and its text, such as
        `{"/*@three@*/": ...}`

    Returns
    -------
    page : str
        The page, as HTML text

    Raises
    ------
    ValueError
        If a placeholder is missing from the template or appears twice, or if a
        script holds text that would end its tag early
    """
    shared = _TEMPLATES / "shared"
    folder = _TEMPLATES / page
    code = [shared / name for name in SHARED_SCRIPTS] + [
        folder / name for name in scripts
    ]
    parts = {
        "/*@css@*/": (shared / "editor.css").read_text(encoding="utf-8"),
        "/*@yaml@*/": _vendor("js-yaml.min.js"),
        "/*@editor@*/": "\n".join(path.read_text(encoding="utf-8") for path in code),
        "@help@": _script_json(help_text(domains)),
        **parts,
        # last, so that no text of the user's can look like a later placeholder
        "@project@": _script_json(data),
    }
    html = (folder / "editor.html").read_text(encoding="utf-8")
    for placeholder, text in parts.items():
        if html.count(placeholder) != 1:
            raise ValueError(f"{placeholder} must appear once in the {page} template")
        if "</script" in text.lower():
            raise ValueError(f"the text for {placeholder} holds '</script'")
        html = html.replace(placeholder, text)
    return html


def editor_page(data: dict) -> str:
    """
    The scenario editor's page, with three.js and the folder's files.

    Parameters
    ----------
    data : dict
        The folder's files, from `editor_data`

    Returns
    -------
    page : str
        The page, as HTML text
    """
    return build_page(
        "scenario",
        SCRIPTS,
        data,
        ("scenario", "power"),
        **{"/*@three@*/": _vendor("three.min.js")},
    )


def write_editor(
    folder: str | Path,
    output: str | Path,
    scenario_file: str = SCENARIO_FILE,
    power_file: str = POWER_FILE,
    consumption_file: str = CONSUMPTION_FILE,
) -> Path:
    """
    Write the editor page for a folder of input files.

    The page holds the files as they are now. To edit them again after they
    change on disk, write the page again.

    Parameters
    ----------
    folder : str | Path
        The folder that holds the input files
    output : str | Path
        The folder to write the page in. It is made if it does not exist.
    scenario_file, power_file, consumption_file : str, optional
        The files' names, if not the usual ones. See `editor_data`.

    Returns
    -------
    page : Path
        The page written. Double-click it to open the editor.
    """
    data = editor_data(folder, scenario_file, power_file, consumption_file)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    page = output / PAGE_FILE
    page.write_text(editor_page(data), encoding="utf-8")
    return page
