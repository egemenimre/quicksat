# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
What both editor pages share: the page built from its template, the help, the files read
for the page, and what quicksat's loaders say of them.

The page writes its own help as `#` lines and replaces the rest when it saves. So
`comment_blocks` finds the user's `#` comments, for the page to list before a save.

"""

import csv
import io
import json
from datetime import date, datetime
from importlib.resources import files
from pathlib import Path

import yaml

PAGE_FILE = "editor.html"
"""The name of the page written in the output folder."""

_PACKAGE = files("quicksat")


_TEMPLATES = _PACKAGE / "editor" / "templates"


_HELP = _PACKAGE / "editor" / "help"


_VENDOR = _PACKAGE / "scenario" / "templates" / "vendor"


SHARED_SCRIPTS = ("base.js", "files.js", "open.js", "frame.js", "server.js")
"""The scripts in `templates/shared/` that every editor page runs first, with their
styles in `editor.css`."""


def _json_default(value):
    """A date or a time that YAML reads as ISO text, which JSON can hold."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"cannot pass {value!r} to the page")


def _key_lines(text: str) -> list[tuple[int, int, list]]:
    """
    The line, column and path of every key and list item in a YAML text, outermost
    first.
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
    """The comment at the end of a line of YAML, outside any quotes, or None."""
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

    A block of comment lines belongs to the first key below it, or to that key's section
    after a blank line, or to the file. A comment at a line's end belongs to the
    outermost key on it.

    Parameters
    ----------
    text : str
        The YAML text

    Returns
    -------
    blocks : list of dict
        Each block's first `line`, from 1, its `text`, its key's `path`, empty for the
        file, and whether it is `inline`
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
    The path of the key that a block of full-line comments belongs to, empty for the
    file.
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


def loader_check(label: str, read) -> dict:
    """
    What one of quicksat's loaders says of a file, or of files read together.

    Parameters
    ----------
    label : str
        The files' names, such as `scenario.yaml`
    read : callable
        Reads the files with the loader

    Returns
    -------
    check : dict
        `file`, `ok`, and the error's `message`, or empty
    """
    try:
        read()
    except Exception as exc:  # the page shows any failure, whatever its kind
        return {"file": label, "ok": False, "message": str(exc)}
    return {"file": label, "ok": True, "message": ""}


def yaml_file(path: Path) -> dict:
    """
    A YAML file for the page: its name, its data and its comments.

    Parameters
    ----------
    path : Path
        The file

    Returns
    -------
    file : dict
        `name`, `data`, and `comments` from `comment_blocks`
    """
    text = path.read_text(encoding="utf-8")
    return {
        "name": path.name,
        "data": yaml.safe_load(text),
        "comments": comment_blocks(text),
    }


def csv_file(path: Path) -> dict:
    """
    A CSV file for the page: its name, its header, and its rows of text.

    Parameters
    ----------
    path : Path
        The file

    Returns
    -------
    file : dict
        `name`, `header`, and the `rows` that are not empty
    """
    rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))
    return {
        "name": path.name,
        "header": rows[0] if rows else [],
        "rows": [row for row in rows[1:] if any(cell.strip() for cell in row)],
    }


def _script_json(value) -> str:
    """Compact JSON that is safe inside a script tag, with every `</` escaped."""
    text = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), default=_json_default
    )
    return text.replace("</", "<\\/")


def help_text(domains: tuple[str, ...]) -> dict:
    """
    The help of some domains, from their files in `help/`, so the page and the files it
    saves read the same text.

    Parameters
    ----------
    domains : tuple of str
        The help files' names, such as `("scenario", "power")`

    Returns
    -------
    help : dict
        Each key's `title`, `info` and `file` help, from all the domains

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


def vendor_text(name: str) -> str:
    """
    A library from the viewer's vendor folder, with its licence in front as a comment.

    Parameters
    ----------
    name : str
        The library's file, such as `three.min.js`, beside its `.LICENSE`

    Returns
    -------
    text : str
        The licence, then the library
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
        The page's folder in `templates/`, such as `scenario`
    scripts : tuple of str
        The page's own scripts, in order, after the shared ones
    data : dict
        The folder's files, as JSON in the page
    domains : tuple of str
        The domains whose help the page holds
    **parts : str
        Any other placeholder of the template, with its text

    Returns
    -------
    page : str
        The page, as HTML

    Raises
    ------
    ValueError
        If a placeholder is missing or doubled, or a script would end its tag early
    """
    shared = _TEMPLATES / "shared"
    folder = _TEMPLATES / page
    code = [shared / name for name in SHARED_SCRIPTS] + [
        folder / name for name in scripts
    ]
    parts = {
        "/*@css@*/": (shared / "editor.css").read_text(encoding="utf-8"),
        "/*@yaml@*/": vendor_text("js-yaml.min.js"),
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
