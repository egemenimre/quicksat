# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the Budgets tab's results, and for the Sizing Editor's server that
works them out after each change on the page.

The results come from a copy of the sizing test folder, with a small mass
budget added. The server runs in a thread, on a free port.
"""

import http.client
import json
import shutil
import threading
from pathlib import Path

import pytest

from quicksat.editor.__main__ import main
from quicksat.editor.budgets import budget_results
from quicksat.editor.server import HOST, PREFIX, EditorServer, budget_files
from quicksat.editor.sizing import NAMES, sizing_data

TESTS = Path(__file__).parent.parent
SIZING = TESTS / "sizing" / "data"

EQUIPMENT = """equipment_id,equipment_name,location,responsibility,subsystem,unit_mass,eqpt_margin,number_of_units,mass_class,comments
bus,Bus,Platform,Platform,Structure,400 kg,10,1,equipment,the whole platform
fuel,Hydrazine,Platform,Platform,Propulsion,30 kg,0,1,propellant,
"""

MASS = """locations:
  Platform: {system_margin: 20, harness_fraction: 0, harness_margin: 0}
"""


@pytest.fixture
def folder(tmp_path) -> Path:
    """A copy of the sizing test folder, with a mass budget of its own."""
    folder = tmp_path / "sizing"
    shutil.copytree(SIZING, folder)
    (folder / NAMES["equipment"]).write_text(EQUIPMENT)
    (folder / NAMES["mass"]).write_text(MASS)
    return folder


def texts(results) -> list:
    """Every text that the results hold, to check that they are all text."""
    if isinstance(results, dict):
        return [text for value in results.values() for text in texts(value)]
    if isinstance(results, list):
        return [text for value in results for text in texts(value)]
    return [results]


# ---------------------------------------------------------------- the results


def test_every_budget_is_worked_out(folder):
    results = budget_results(folder)
    assert all(
        budget is not None and "error" not in budget
        for budget in results["budgets"].values()
    )
    assert [(check["budget"], check["check"]) for check in results["checks"]] == [
        ("deltav", "propellant"),
        ("data", "downlink"),
        ("data", "storage"),
        ("agility", "roll_40"),
        ("agility", "pitch_40"),
    ]
    assert results["notes"] == []


def test_the_figures_and_the_tables_are_text(folder):
    """The page formats no number of its own: each figure and each cell is text."""
    results = budget_results(folder)
    for key in ("budgets", "overview"):
        assert all(isinstance(text, (str, bool)) for text in texts(results[key]))


def test_the_mass_table_is_the_notebook_s(folder):
    """With the same headings and decimals as `tabulated_mass`."""
    mass = budget_results(folder)["budgets"]["mass"]
    table = mass["tables"]["budget"]["10"]
    assert [column["title"] for column in table["columns"]][:2] == ["Item", "Name"]
    wet = [row for row in table["rows"] if row["type"] == "wet_total"]
    # 400 kg and 10 %, with a system margin of 20 %, and 30 kg of propellant
    assert wet[0]["cells"][-2] == "558.00"
    assert set(mass["tables"]["budget"]) == {"10", "11", "00", "01"}


def test_a_check_says_where_its_limit_comes_from(folder):
    checks = {check["check"]: check for check in budget_results(folder)["checks"]}
    assert checks["propellant"]["files"] == ["manoeuvres.csv", "equipment.csv"]
    assert checks["storage"]["files"] == ["requirements.yaml", "pl_dataflow_model.yaml"]
    assert checks["roll_40"]["description"].endswith("for the inertia case first_guess")


def test_the_agility_tables_cover_the_selected_case_about_each_axis(folder):
    """The other cases are compared in the table of cases only."""
    agility = budget_results(folder)["budgets"]["agility"]
    assert agility["selected"] == "first_guess"
    assert set(agility["variants"]) == {"roll|0", "roll|1", "pitch|0", "pitch|1"}
    assert set(agility["variants"]["roll|0"]["tables"]) == {"", "roll_40"}
    assert [figure["label"] for figure in agility["figures"]] == ["roll_40", "pitch_40"]
    rows = agility["tables"]["cases"]["rows"]
    assert [row["cells"][0] for row in rows] == [
        "first_guess (selected)",
        "measured_bol",
        "measured_eol",
    ]


def test_a_budget_without_its_files_has_no_results():
    """The sizing test folder has no mass files, so the envelope case needs a mass."""
    results = budget_results(SIZING)
    assert results["budgets"]["mass"] is None
    agility = results["budgets"]["agility"]
    assert "needs a mass" in agility["variants"]["roll|0"]["error"]
    # a stated case needs no mass, so the table of cases still has its inertia
    measured = agility["tables"]["cases"]["rows"][1]["cells"]
    assert measured[:3] == ["measured_bol", "stated", "264.7"]
    # the selected case cannot be worked out, so it gives no check
    assert not [check for check in results["checks"] if check["budget"] == "agility"]


def test_a_refused_file_stops_its_budget_only(folder):
    data = folder / NAMES["data"]
    data.write_text(data.read_text().replace("capacity: 2 TB", "capacity: 2 km"))
    budgets = budget_results(folder)["budgets"]
    assert "data volume" in budgets["data"]["error"]
    assert "error" not in budgets["deltav"]


def test_a_refused_mission_stops_the_budgets_that_read_it(folder):
    mission = folder / NAMES["mission"]
    mission.write_text(mission.read_text().replace("duration:", "durration:"))
    results = budget_results(folder)
    assert "error" not in results["budgets"]["mass"]
    for key in ("deltav", "data", "agility"):
        assert results["budgets"][key] == {"error": "mission.yaml cannot be read."}
    assert results["notes"][0].startswith("mission.yaml: ")


def test_without_requirements_only_the_propellant_and_the_downlink_are_checked(folder):
    (folder / NAMES["requirements"]).unlink()
    results = budget_results(folder)
    assert [check["check"] for check in results["checks"]] == ["propellant", "downlink"]
    labels = [figure["label"] for figure in results["overview"]]
    assert "Mass memory" in labels and "Storage needed" not in labels


def test_the_page_holds_the_results(folder):
    assert sizing_data(folder)["results"]["budgets"]["mass"] is not None


# ---------------------------------------------------------------- the server


def page_files(folder: Path) -> list[dict]:
    """The folder's files as the page sends them for the budgets, by kind."""
    return [
        {"kind": kind, "text": (folder / name).read_text()}
        for kind, name in NAMES.items()
        if (folder / name).is_file()
    ]


def test_budget_files_work_out_the_page_s_texts(folder):
    files = page_files(folder)
    for file in files:
        if file["kind"] == "equipment":
            file["text"] = file["text"].replace("30 kg", "10 kg")
    files.append({"kind": "model", "text": "not a sizing file"})
    result = budget_files(files)
    assert result["ok"]
    propellant = result["results"]["checks"][0]
    assert propellant["check"] == "propellant" and propellant["design"] == "10.00 kg"


def test_budget_files_need_text():
    result = budget_files([{"kind": "mission", "text": 1}])
    assert not result["ok"] and "mission.yaml" in result["error"]


@pytest.fixture
def server(folder):
    """The Sizing Editor for the folder, served in a thread."""
    server = EditorServer(folder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def ask(server, method, name, body=None):
    """A request to the server, with its key: the status and the body."""
    connection = http.client.HTTPConnection(HOST, server.server_port, timeout=60)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    connection.request(method, f"{PREFIX}{name}?key={server.key}", body, headers)
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response.status, data


def test_a_folder_of_sizing_files_gets_the_sizing_editor(server):
    assert server.sizing and server.output is None
    status, body = ask(server, "GET", "editor")
    assert status == 200
    page = body.decode("utf-8")
    assert "<title>quicksat Sizing Editor</title>" in page
    data = json.loads(
        page.split('<script id="project" type="application/json">')[1].split(
            "</script>"
        )[0]
    )
    assert (
        data["server"]["command"] == f"python -m quicksat.editor serve {server.folder}"
    )
    assert data["results"]["budgets"]["mass"] is not None
    assert json.loads(ask(server, "GET", "status")[1]) == {"ok": True, "viewers": []}


def test_the_server_works_out_the_budgets(server, folder):
    body = json.dumps({"files": page_files(folder)}).encode("utf-8")
    status, answer = ask(server, "POST", "budgets", body)
    assert status == 200
    result = json.loads(answer)
    assert result["ok"]
    assert len(result["results"]["checks"]) == 5


@pytest.mark.parametrize("route", ["run", "design", "save"])
def test_the_sizing_server_runs_no_scenario(server, route):
    status, _ = ask(server, "POST", route, b'{"files": []}')
    assert status == 404


def test_the_scenario_server_works_out_no_budgets(tmp_path):
    server = EditorServer(TESTS / "scenario" / "data", tmp_path / "output")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert not server.sizing
        status, _ = ask(server, "POST", "budgets", b'{"files": []}')
        assert status == 404
    finally:
        server.shutdown()
        server.server_close()


def test_the_scenario_editor_needs_an_output_folder():
    with pytest.raises(ValueError, match="output folder"):
        EditorServer(TESTS / "scenario" / "data")
    with pytest.raises(SystemExit) as exit_info:
        main(["serve", str(TESTS / "scenario" / "data"), "--no-browser"])
    assert exit_info.value.code == 1
