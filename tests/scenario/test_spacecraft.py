# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the spacecraft's 3D model: the GLB check, the `3d_model` key, and the
model in the viewer's data and page.

`data/spacecraft.glb` is a copy of the sample's model. The broken files are
built here.
"""

import base64
import dataclasses
import json
import struct
from importlib.resources import files

import pytest

from quicksat.scenario.config import Scenario, SpacecraftModel
from quicksat.scenario.spacecraft import read_glb_json
from quicksat.scenario.viewer import VERSION, scenario_data, viewer_page


def glb(gltf: dict) -> bytes:
    """A GLB file that holds only a JSON chunk."""
    text = json.dumps(gltf).encode()
    text += b" " * (-len(text) % 4)
    chunk = struct.pack("<I4s", len(text), b"JSON") + text
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunk)) + chunk


ASSET = {"asset": {"version": "2.0"}}


@pytest.fixture(scope="module")
def model(data_dir):
    """The sample's model."""
    return data_dir / "spacecraft.glb"


@pytest.fixture(scope="module")
def text(data_dir):
    """The fixture scenario file, which names no model."""
    return (data_dir / "scenario.yaml").read_text()


# ---------------------------------------------------------------- The GLB check


def test_the_sample_model_reads(model):
    gltf = read_glb_json(model)
    assert gltf["asset"]["version"] == "2.0"
    names = [node["name"] for node in gltf["nodes"]]
    assert "Bus" in names
    assert "Wing +y inner cells" in names
    # each wing is one node, with its panels as children, so that it can turn
    wing = gltf["nodes"][names.index("Wing +y")]
    children = [gltf["nodes"][i]["name"] for i in wing["children"]]
    assert "Wing +y inner cells" in children


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"solid cube\nendsolid cube\n", "not a GLB file"),
        (struct.pack("<4sII", b"glTF", 1, 20) + bytes(8), "version 1"),
        (glb(ASSET)[:-4], "damaged: its header gives"),
        (
            struct.pack("<4sII", b"glTF", 2, 24)
            + struct.pack("<I4s", 4, b"BIN\0")
            + bytes(4),
            "first chunk is not JSON",
        ),
        (
            glb(ASSET | {"extensionsRequired": ["KHR_draco_mesh_compression"]}),
            "needs Draco compression",
        ),
    ],
)
def test_a_file_the_viewer_cannot_read_is_refused(tmp_path, content, message):
    path = tmp_path / "model.glb"
    path.write_bytes(content)
    with pytest.raises(ValueError, match=message):
        read_glb_json(path)


def test_an_extension_the_viewer_decodes_is_accepted(tmp_path):
    path = tmp_path / "model.glb"
    path.write_bytes(glb(ASSET | {"extensionsRequired": ["KHR_materials_unlit"]}))
    assert read_glb_json(path)["extensionsRequired"] == ["KHR_materials_unlit"]


# ---------------------------------------------------------------- The scenario file


def test_the_model_is_taken_from_the_folder_of_the_file(text, data_dir):
    scenario = Scenario.from_yaml_text("3d_model: spacecraft.glb\n" + text, data_dir)
    assert scenario.spacecraft_model is not None
    assert scenario.spacecraft_model.file == data_dir / "spacecraft.glb"


def test_without_a_model_there_is_none(run):
    assert run.scenario.spacecraft_model is None


@pytest.mark.parametrize(
    ("name", "message"),
    [("missing.glb", "no such file"), ("scenario.yaml", "not a GLB file")],
)
def test_a_missing_or_unreadable_model_stops_the_load(text, data_dir, name, message):
    with pytest.raises(ValueError, match=f"3d_model\n.*{message}"):
        Scenario.from_yaml_text(f"3d_model: {name}\n" + text, data_dir)


# ---------------------------------------------------------------- The viewer


def test_without_a_model_the_data_has_none(run):
    assert scenario_data(run)["model"] is None


def test_the_data_carries_the_model_byte_for_byte(run, model):
    scenario = run.scenario.model_copy(
        update={"spacecraft_model": SpacecraftModel(file=model)}
    )
    data = scenario_data(dataclasses.replace(run, scenario=scenario))
    assert data["model"]["name"] == "spacecraft.glb"
    assert base64.b64decode(data["model"]["glb_base64"]) == model.read_bytes()


def test_the_page_reads_this_version_and_carries_the_loader():
    template = files("quicksat") / "scenario" / "templates" / "viewer.html"
    assert f"const PAGE_VERSION = {VERSION};" in template.read_text(encoding="utf-8")
    assert "GLTFLoader" in viewer_page()
