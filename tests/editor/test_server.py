# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the editor's local server: the runs of the page's files, and what the
server answers and refuses.

The runs use the power and scenario test folders, sent as the page sends them,
and write the viewer into a temporary folder. The server runs in a thread, on a
free port. The saves write into a copy of the power test folder. The stop, and
the stop after a time with no request, end `serve`, in a thread of its own.
"""

import base64
import http.client
import json
import shutil
import threading
import time
from pathlib import Path

import pytest
import yaml

from quicksat.editor.__main__ import main
from quicksat.editor.server import (
    HOST,
    PORT,
    PREFIX,
    EditorServer,
    _write_inputs,
    design_files,
    file_hash,
    run_files,
    serve,
)

TESTS = Path(__file__).parent.parent
POWER = TESTS / "power" / "data"
SCENARIO = TESTS / "scenario" / "data"

NAMES = {
    "scenario": "scenario.yaml",
    "power": "power_system.yaml",
    "payload_consumption": "payload_consumption.csv",
    "platform_consumption": "platform_consumption.csv",
}


def page_files(folder: Path, kinds=tuple(NAMES)) -> list[dict]:
    """A folder's files as the page sends them: the model in base64, the rest as text."""
    files = [
        {"kind": kind, "name": NAMES[kind], "text": (folder / NAMES[kind]).read_text()}
        for kind in kinds
    ]
    data = yaml.safe_load(files[0]["text"])
    tle = data["orbit"]["tle_file"]
    files.append({"kind": "orbit", "name": tle, "text": (folder / tle).read_text()})
    model = data.get("3d_model")
    if model:
        name = model["file"] if isinstance(model, dict) else model
        glb = base64.b64encode((folder / name).read_bytes()).decode("ascii")
        files.append({"kind": "model", "name": name, "base64": glb})
    return files


# ---------------------------------------------------------------- the runs


def test_run_power(tmp_path):
    """A power folder's files give the power viewer, and every file passes."""
    result = run_files(page_files(POWER), tmp_path)
    assert result["ok"], result.get("error")
    assert result["page"] == "power_viewer.html"
    assert {p.name for p in tmp_path.iterdir()} == {
        "power_viewer.html",
        "power.js",
        "scenario.js",
    }
    assert [c["file"] for c in result["checks"]] == list(NAMES.values())
    assert all(c["ok"] for c in result["checks"])
    assert "Loads met" in result["report"]


def test_run_power_needs_both_consumption_files(tmp_path):
    """Without the platform's consumption file, the scenario runs alone."""
    files = page_files(POWER, ("scenario", "power", "payload_consumption"))
    result = run_files(files, tmp_path)
    assert result["ok"], result.get("error")
    assert result["page"] == "scenario_viewer.html"


def test_run_scenario(tmp_path):
    """A scenario with no power files gives the scenario viewer."""
    result = run_files(page_files(SCENARIO, ("scenario",)), tmp_path)
    assert result["ok"], result.get("error")
    assert result["page"] == "scenario_viewer.html"
    assert (tmp_path / "scenario.js").is_file()
    assert result["report"]


def test_run_with_satellite_targets(tmp_path):
    """A satellite target's file goes by its name, as the page sends it."""
    files = page_files(SCENARIO, ("scenario",))
    files[0]["text"] += "sat_targets:\n  RELAY-01: {tle_file: relays.tle}\n"
    relays = SCENARIO / "relays.tle"
    files.append(
        {"kind": "target:relays.tle", "name": "relays.tle", "text": relays.read_text()}
    )
    result = run_files(files, tmp_path)
    assert result["ok"], result.get("error")
    assert "Target RELAY-01:" in result["report"]


def test_run_uses_the_page_text(tmp_path):
    """The run reads the files as the page sends them, not as they are on disk."""
    files = page_files(POWER)
    files[0]["text"] = files[0]["text"].replace(
        "duration: 1 orbit", "duration: 2 orbits"
    )
    assert "duration: 2 orbits" in files[0]["text"]
    result = run_files(files, tmp_path)
    assert result["ok"], result.get("error")
    assert "duration: 2 orbits" in (tmp_path / "scenario.js").read_text()


def test_run_refused(tmp_path):
    """A file that quicksat cannot read stops the run, and its message has no temporary path."""
    files = page_files(POWER)
    files[1]["text"] += "\nno_such_key: 1\n"
    result = run_files(files, tmp_path)
    assert not result["ok"]
    assert "power_system.yaml" in result["error"]
    refused = [c for c in result["checks"] if not c["ok"]]
    assert [c["file"] for c in refused] == ["power_system.yaml"]
    assert "no_such_key" in refused[0]["message"]
    assert "quicksat_run_" not in refused[0]["message"]
    assert list(tmp_path.iterdir()) == []


def test_run_without_scenario(tmp_path):
    result = run_files(page_files(POWER)[1:], tmp_path)
    assert not result["ok"]
    assert "no scenario" in result["error"]


def test_inputs_outside_the_folder(tmp_path):
    """A model named from `..` lands where the scenario finds it, inside the run's folder."""
    files = [
        {"kind": "scenario", "name": "scenario.yaml", "text": "x"},
        {"kind": "model", "name": "../../models/sat.glb", "base64": "AAEC"},
        {"kind": "orbit", "name": "/somewhere/else.tle", "text": "not written"},
    ]
    base, names = _write_inputs(tmp_path, files)
    assert names == {"scenario": "scenario.yaml"}
    model = (base / "../../models/sat.glb").resolve()
    assert model.read_bytes() == b"\x00\x01\x02"
    assert model.is_relative_to(tmp_path.resolve())
    assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == [
        "sat.glb",
        "scenario.yaml",
    ]


@pytest.mark.parametrize(
    "name", ["../scenario.yaml", "data/scenario.yaml", "/tmp/s.yaml", "C:\\s.yaml", " "]
)
def test_inputs_refused(tmp_path, name):
    """The files quicksat reads must have plain names."""
    with pytest.raises(ValueError):
        _write_inputs(tmp_path, [{"kind": "scenario", "name": name, "text": "x"}])


# ---------------------------------------------------------------- the server


@pytest.fixture
def server(tmp_path):
    """The power test folder's editor, served in a thread."""
    server = EditorServer(POWER, tmp_path / "output")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def ask(server, method, path, body=None, headers=None):
    """A request to the server: the status, the body and the response."""
    connection = http.client.HTTPConnection(HOST, server.server_port, timeout=60)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response.status, data, response


def at(server, name: str, key: str | None = None) -> str:
    """The server's address for a name, such as `status`, with the key at its end."""
    return f"{PREFIX}{name}?key={server.key if key is None else key}"


def run_request(files) -> tuple[bytes, dict]:
    return json.dumps({"files": files}).encode("utf-8"), {
        "Content-Type": "application/json"
    }


def test_page(server):
    """The page is the editor, written now, with the server's address and folders."""
    status, body, response = ask(server, "GET", at(server, "editor"))
    assert status == 200
    assert response.getheader("Content-Type").startswith("text/html")
    assert response.getheader("Referrer-Policy") == "no-referrer"
    data = json.loads(
        body.decode("utf-8")
        .split('<script id="project" type="application/json">')[1]
        .split("</script>")[0]
    )
    assert data["server"]["base"] == "/quicksat/"
    assert data["server"]["key"] == server.key
    assert data["server"]["output"] == "output"
    assert (
        data["server"]["command"]
        == f"python -m quicksat.editor serve {POWER} {server.output}"
    )
    assert data["server"]["viewers"] == []
    assert data["server"]["idle_h"] == 48
    assert data["files"]["power"]["name"] == "power_system.yaml"


def test_url(server):
    assert (
        server.url
        == f"http://localhost:{server.server_port}/quicksat/editor?key={server.key}"
    )
    assert len(server.key) == 12
    assert PORT <= server.server_port < PORT + 20


def test_next_port(server):
    """A second server takes the next free port, and a port asked for must be free."""
    other = EditorServer(POWER, server.output)
    try:
        assert other.server_port != server.server_port
        assert other.key != server.key
    finally:
        other.server_close()
    with pytest.raises(OSError):
        EditorServer(POWER, server.output, port=server.server_port)


@pytest.mark.parametrize(
    "path", ["/", "/quicksat/editor", "/quicksat/status", "/editor"]
)
def test_without_the_key(server, path):
    status, body, _ = ask(server, "GET", path)
    assert status == 404
    assert b"key" in body


@pytest.mark.parametrize(
    "name", ["editor", "status", "designer", "viewer/power_viewer.html"]
)
def test_wrong_key(server, name):
    status, body, _ = ask(server, "GET", at(server, name, "k3Xq9vTzR2mA"))
    assert status == 404
    assert b"key" in body


@pytest.mark.parametrize(
    "host", ["example.com", "127.0.0.1", "127.0.0.1:1", "evil.localhost"]
)
def test_other_host(server, host):
    """A request that names another host is refused, so a site cannot point its name here."""
    status, _, _ = ask(server, "GET", at(server, "editor"), headers={"Host": host})
    assert status == 403


def test_localhost(server):
    status, _, _ = ask(
        server,
        "GET",
        at(server, "status"),
        headers={"Host": f"localhost:{server.server_port}"},
    )
    assert status == 200


def test_status(server):
    status, body, _ = ask(server, "GET", at(server, "status"))
    assert status == 200
    assert json.loads(body) == {"ok": True, "viewers": []}


def test_run_and_view(server):
    """A run writes the viewer, which the server then serves."""
    body, headers = run_request(page_files(POWER))
    status, answer, _ = ask(server, "POST", at(server, "run"), body, headers)
    assert status == 200
    result = json.loads(answer)
    assert result["ok"], result.get("error")
    assert (server.output / "power_viewer.html").is_file()
    _, status_body, _ = ask(server, "GET", at(server, "status"))
    assert json.loads(status_body)["viewers"] == ["power_viewer.html"]
    for name, kind in [
        ("power_viewer.html", "text/html"),
        ("scenario.js", "text/javascript"),
        ("power.js", "text/javascript"),
    ]:
        status, _, response = ask(server, "GET", at(server, f"viewer/{name}"))
        assert status == 200
        assert response.getheader("Content-Type").startswith(kind)
        assert response.getheader("Cache-Control") == "no-store"
    _, page, _ = ask(server, "GET", at(server, "viewer/power_viewer.html"))
    assert f'src="scenario.js?key={server.key}"'.encode() in page
    assert f'src="power.js?key={server.key}"'.encode() in page


@pytest.mark.parametrize(
    "name",
    [
        "missing.html",
        "..%2Fpower_system.yaml",
        "sub/x.js",
        ".hidden.js",
        "power_system.yaml",
    ],
)
def test_viewer_files_only(server, name):
    """The server serves the viewer's files in the output folder, and nothing else."""
    server.output.mkdir()
    (server.output / "power_system.yaml").write_text("x")
    (server.output / ".hidden.js").write_text("x")
    status, _, _ = ask(server, "GET", at(server, f"viewer/{name}"))
    assert status == 404


def test_run_from_another_page(server):
    """A run asked by a page from another origin is refused."""
    body, headers = run_request(page_files(POWER))
    status, _, _ = ask(
        server,
        "POST",
        at(server, "run"),
        body,
        {**headers, "Origin": "https://example.com"},
    )
    assert status == 403
    assert not server.output.exists()


def test_run_without_the_key(server):
    body, headers = run_request(page_files(POWER))
    status, _, _ = ask(server, "POST", "/quicksat/run", body, headers)
    assert status == 404


@pytest.mark.parametrize(
    "body, kind",
    [
        (b"not json", "application/json"),
        (b'{"nofiles": 1}', "application/json"),
        (b'{"files": []}', "text/plain"),
    ],
)
def test_not_a_run(server, body, kind):
    status, answer, _ = ask(
        server, "POST", at(server, "run"), body, {"Content-Type": kind}
    )
    assert status == 400
    assert not json.loads(answer)["ok"]


def test_one_run_at_a_time(server):
    body, headers = run_request(page_files(POWER))
    with server.run_lock:
        status, answer, _ = ask(server, "POST", at(server, "run"), body, headers)
    assert status == 409
    assert "going already" in json.loads(answer)["error"]


def test_serve_needs_a_scenario(tmp_path):
    with pytest.raises(SystemExit) as exit_info:
        main(["serve", str(tmp_path), str(tmp_path / "output"), "--no-browser"])
    assert exit_info.value.code == 1


# ---------------------------------------------------------------- the Activity Designer


def page_data(page: bytes) -> dict:
    """The run's data inside the designer's page."""
    script = page.decode("utf-8").split("<script>window.quicksat = {scenario: ")[1]
    return json.loads(script.split("};</script>")[0])


def design_request(files, repeat=False) -> tuple[bytes, dict]:
    return json.dumps({"files": files, "repeat": repeat}).encode("utf-8"), {
        "Content-Type": "application/json"
    }


def test_design_runs_the_scenario_once_without_the_power():
    files = page_files(POWER)
    result = design_files(files, repeat=False)
    assert result["ok"], result.get("error")
    assert [c["file"] for c in result["checks"]] == ["scenario.yaml"]
    data = result["data"]
    assert data["designer"]["repeat"] is False
    assert result["id"] == data["id"]
    assert result["pass_s"] == data["designer"]["pass_s"] < result["duration_s"]
    assert result["duration_s"] == data["grid"]["t_s"][-1]
    assert result["period_s"] == data["orbit"]["period_s"]
    assert result["warnings"] == data["warnings"]
    assert result["max_rate_deg_s"] == data["attitude"]["max_rate_deg_s"]
    activities = yaml.safe_load(files[0]["text"])["activities"]
    assert [row["number"] for row in result["rows"]] == list(
        range(1, len(activities) + 1)
    )
    for name in ("payload_mode", "platform_mode"):
        assert data["tracks"][name][-1]["value"] == "unplanned"


def test_design_with_repeats_plans_the_whole_run():
    result = design_files(page_files(SCENARIO, ("scenario",)), repeat=True)
    assert result["ok"], result.get("error")
    assert result["data"]["designer"]["repeat"] is True
    assert result["pass_s"] < result["duration_s"]
    tracks = result["data"]["tracks"]
    pieces = tracks["attitude"] + tracks["payload_mode"] + tracks["platform_mode"]
    assert all(p["value"] != "unplanned" for p in pieces)
    assert max(row["count"] for row in result["rows"]) > 1


def test_design_an_empty_list():
    files = page_files(SCENARIO, ("scenario",))
    files[0]["text"] = files[0]["text"].split("activities:")[0] + "activities: []\n"
    result = design_files(files, repeat=False)
    assert result["ok"], result.get("error")
    assert result["rows"] == []
    assert result["pass_s"] == 0
    assert [p["value"] for p in result["data"]["tracks"]["attitude"]] == ["unplanned"]


def test_design_refused():
    files = page_files(SCENARIO, ("scenario",))
    files[0]["text"] += "\nno_such_key: 1\n"
    result = design_files(files, repeat=False)
    assert not result["ok"]
    assert "no_such_key" in result["checks"][0]["message"]


def test_design_and_view(server):
    """The designer's run writes nothing, and its frame then shows it."""
    status, page, _ = ask(server, "GET", at(server, "designer"))
    assert status == 200
    assert b"Generate scenario" in page
    body, headers = design_request(page_files(POWER))
    status, answer, _ = ask(server, "POST", at(server, "design"), body, headers)
    assert status == 200
    result = json.loads(answer)
    assert result["ok"], result.get("error")
    assert "data" not in result
    assert not server.output.exists()
    status, page, response = ask(server, "GET", at(server, "designer"))
    assert status == 200
    assert response.getheader("Content-Type", "").startswith("text/html")
    assert response.getheader("Cache-Control") == "no-store"
    assert page_data(page)["id"] == result["id"]


def test_design_from_another_page(server):
    body, headers = design_request(page_files(POWER))
    status, _, _ = ask(
        server,
        "POST",
        at(server, "design"),
        body,
        {**headers, "Origin": "https://example.com"},
    )
    assert status == 403
    assert server.design_page is None


def test_one_design_at_a_time(server):
    """A design and a run share the lock, so one goes at a time."""
    body, headers = design_request(page_files(POWER))
    with server.run_lock:
        status, answer, _ = ask(server, "POST", at(server, "design"), body, headers)
    assert status == 409
    assert "going already" in json.loads(answer)["error"]


@pytest.fixture
def copy_server(tmp_path):
    """The editor of a copy of the power test folder, served in a thread."""
    folder = tmp_path / "data"
    shutil.copytree(POWER, folder)
    server = EditorServer(folder, tmp_path / "output")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def page_hashes(server) -> dict:
    """The hashes of the files that the editor's page was written from."""
    _, body, _ = ask(server, "GET", at(server, "editor"))
    data = json.loads(
        body.decode("utf-8")
        .split('<script id="project" type="application/json">')[1]
        .split("</script>")[0]
    )
    return data["server"]["sha256"]


def save(server, files, headers=None) -> tuple[int, dict]:
    """A save request: the status, and the answer when the server takes it."""
    body = json.dumps({"files": files}).encode("utf-8")
    status, answer, _ = ask(
        server,
        "POST",
        at(server, "save"),
        body,
        {"Content-Type": "application/json", **(headers or {})},
    )
    return status, json.loads(answer) if status == 200 else {}


def test_the_page_holds_the_hash_of_each_file(copy_server):
    assert page_hashes(copy_server) == {
        name: file_hash(copy_server.folder / name) for name in NAMES.values()
    }


def test_save_writes_the_file_and_gives_its_new_hash(copy_server):
    folder = copy_server.folder
    before = sorted(path.name for path in folder.iterdir())
    hashes = page_hashes(copy_server)
    path = folder / "scenario.yaml"
    text = path.read_text() + "# saved from the page\n"
    file = {"name": "scenario.yaml", "text": text, "sha256": hashes["scenario.yaml"]}
    status, result = save(copy_server, [file])
    assert status == 200
    assert result["ok"], result.get("error")
    assert path.read_text() == text
    assert result["files"] == [{"name": "scenario.yaml", "sha256": file_hash(path)}]
    # no temporary file is left behind
    assert sorted(path.name for path in folder.iterdir()) == before
    # the new hash lets the page save again
    file = {**file, "text": text + "# again\n", "sha256": result["files"][0]["sha256"]}
    status, result = save(copy_server, [file])
    assert result["ok"], result.get("error")


def test_save_refuses_a_file_changed_on_disk(copy_server):
    """A file changed since the page was written stops the save of every file."""
    folder = copy_server.folder
    hashes = page_hashes(copy_server)
    power = folder / "power_system.yaml"
    power.write_text(power.read_text() + "# changed by another program\n")
    scenario_text = (folder / "scenario.yaml").read_text()
    files = [
        {
            "name": "scenario.yaml",
            "text": "changed",
            "sha256": hashes["scenario.yaml"],
        },
        {
            "name": "power_system.yaml",
            "text": "changed",
            "sha256": hashes["power_system.yaml"],
        },
    ]
    status, result = save(copy_server, files)
    assert status == 200
    assert not result["ok"]
    assert "power_system.yaml changed on disk" in result["error"]
    assert (folder / "scenario.yaml").read_text() == scenario_text
    assert power.read_text().endswith("# changed by another program\n")


def test_save_a_new_file_only_where_there_is_none(copy_server):
    folder = copy_server.folder
    status, result = save(
        copy_server, [{"name": "notes.yaml", "text": "a: 1\n", "sha256": None}]
    )
    assert result["ok"], result.get("error")
    assert (folder / "notes.yaml").read_text() == "a: 1\n"
    # a file the page did not know of is not overwritten
    status, result = save(
        copy_server, [{"name": "notes.yaml", "text": "b: 2\n", "sha256": None}]
    )
    assert not result["ok"]
    assert (folder / "notes.yaml").read_text() == "a: 1\n"


@pytest.mark.parametrize(
    "name", ["../outside.yaml", "sub/../../outside.yaml", "/tmp/outside.yaml", "."]
)
def test_save_refuses_a_path_outside_the_folder(copy_server, name):
    status, result = save(copy_server, [{"name": name, "text": "x", "sha256": None}])
    assert status == 200
    assert not result["ok"]
    assert not (copy_server.folder.parent / "outside.yaml").exists()


def test_save_needs_the_key_and_this_page(copy_server):
    path = copy_server.folder / "scenario.yaml"
    text = path.read_text()
    file = {"name": "scenario.yaml", "text": "x", "sha256": file_hash(path)}
    body = json.dumps({"files": [file]}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    status, _, _ = ask(copy_server, "POST", "/quicksat/save", body, headers)
    assert status == 404
    status, _ = save(copy_server, [file], {"Origin": "https://example.com"})
    assert status == 403
    assert path.read_text() == text


@pytest.mark.parametrize("route", ["design", "save"])
def test_not_a_design_or_a_save(server, route):
    status, answer, _ = ask(
        server,
        "POST",
        at(server, route),
        b'{"files": 1}',
        {"Content-Type": "application/json"},
    )
    assert status == 400
    assert not json.loads(answer)["ok"]


# ---------------------------------------------------------------- the stop

STOP = b"{}", {"Content-Type": "application/json"}


def test_stop_ends_serve(tmp_path, capsys):
    """The page's Stop the server button ends `serve`, as Ctrl+C does."""
    server = EditorServer(POWER, tmp_path / "output")
    thread = threading.Thread(target=serve, args=(server, False), daemon=True)
    thread.start()
    status, answer, _ = ask(server, "POST", at(server, "stop"), *STOP)
    assert status == 200
    assert json.loads(answer) == {"ok": True}
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert capsys.readouterr().out.endswith("The server has stopped.\n")
    with pytest.raises(ConnectionRefusedError):
        ask(server, "GET", at(server, "status"))


def test_stop_needs_the_key_and_this_page(server):
    status, _, _ = ask(server, "POST", "/quicksat/stop", *STOP)
    assert status == 404
    body, headers = STOP
    status, _, _ = ask(
        server,
        "POST",
        at(server, "stop"),
        body,
        {**headers, "Origin": "https://example.com"},
    )
    assert status == 403
    status, _, _ = ask(server, "POST", at(server, "stop"), body, {})
    assert status == 400
    assert ask(server, "GET", at(server, "status"))[0] == 200


@pytest.mark.parametrize("busy", ["run", "save"])
def test_stop_waits_for_a_run_or_a_save(server, busy):
    with getattr(server, f"{busy}_lock"):
        status, answer, _ = ask(server, "POST", at(server, "stop"), *STOP)
    assert status == 409
    assert json.loads(answer)["error"].startswith(f"A {busy} is going")
    assert ask(server, "GET", at(server, "status"))[0] == 200
    # the refused stop gave back the lock it took
    assert server.run_lock.acquire(blocking=False)
    server.run_lock.release()


def test_idle_server_stops_by_itself(tmp_path, capsys):
    """With no request from a page for `idle_s`, the server stops, and `serve` ends."""
    server = EditorServer(POWER, tmp_path / "output", idle_s=0)
    thread = threading.Thread(target=serve, args=(server, False), daemon=True)
    thread.start()
    thread.join(timeout=10)
    assert not thread.is_alive()
    out = capsys.readouterr().out
    assert "stopping, as no editor page has been open for 0 h" in out
    assert out.endswith("The server has stopped.\n")


def test_a_request_with_the_key_keeps_the_server_going(server):
    before = time.monotonic() - 100
    server.last_request = before
    ask(server, "GET", "/quicksat/status")
    assert server.last_request == before
    ask(server, "GET", at(server, "status"))
    assert server.last_request > before


def test_no_idle_stop_during_a_run(tmp_path):
    """A run that takes longer than `idle_s` does not stop the server."""
    server = EditorServer(POWER, tmp_path / "output", idle_s=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    with server.run_lock:
        thread.start()
        time.sleep(1)
        assert thread.is_alive()
    thread.join(timeout=10)
    assert not thread.is_alive()
    server.server_close()
