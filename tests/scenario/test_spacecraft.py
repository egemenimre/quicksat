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

import numpy as np
import pytest

from quicksat.scenario.config import Scenario, SpacecraftModel
from quicksat.scenario.spacecraft import (
    TRIANGLE_FAN,
    TRIANGLE_STRIP,
    TRIANGLES,
    _triangle_corners,
    read_glb_json,
    read_model,
)
from quicksat.scenario.viewer import VERSION, scenario_data, viewer_page


def glb(gltf: dict) -> bytes:
    """A GLB file that holds only a JSON chunk."""
    text = json.dumps(gltf).encode()
    text += b" " * (-len(text) % 4)
    chunk = struct.pack("<I4s", len(text), b"JSON") + text
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunk)) + chunk


ASSET = {"asset": {"version": "2.0"}}


def glb_with_mesh(corners: np.ndarray, node: dict, buffer: dict | None = None) -> bytes:
    """
    A GLB file with one node and one mesh of unindexed triangles, from their corners,
    the node's transform, and any buffer entry to replace.
    """
    vertices = corners.astype(np.float32).reshape(-1, 3).tobytes()
    gltf = ASSET | {
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "Plate", "mesh": 0} | node],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(vertices) // 12,
                "type": "VEC3",
            }
        ],
        "bufferViews": [{"buffer": 0, "byteLength": len(vertices)}],
        "buffers": [buffer or {"byteLength": len(vertices)}],
    }
    text = json.dumps(gltf).encode()
    text += b" " * (-len(text) % 4)
    chunks = struct.pack("<I4s", len(text), b"JSON") + text
    chunks += struct.pack("<I4s", len(vertices), b"BIN\0") + vertices
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks


PLATE = np.array([[[0, 0, 0], [1, 0, 0], [0, 1, 0]]], dtype=float)
"""One triangle in the x-y plane, facing +z."""


def normal_of(triangles: np.ndarray) -> np.ndarray:
    """The normal of the first triangle."""
    a, b, c = triangles[0]
    normal = np.cross(b - a, c - a)
    return normal / np.linalg.norm(normal)


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


# ---------------------------------------------------------------- The triangles


def test_the_sample_model_gives_its_parts_in_body_axes(model):
    geometry = read_model(model)
    parts = {part.name: part for part in geometry.parts if part.name != "Spider"}
    # 17 nodes, less the two wing nodes, which have no mesh of their own
    assert len(geometry.parts) == 15
    cells = parts["Wing +y outer cells"]
    assert cells.triangles.shape == (2, 3, 3)
    np.testing.assert_allclose(normal_of(cells.triangles), [0, 0, -1], atol=1e-12)
    # the cells hang below the wing node, whose origin is on the drive axis
    gltf = read_glb_json(model)
    wing = [i for i, n in enumerate(gltf["nodes"]) if n.get("name") == "Wing +y"][0]
    assert cells.ancestors == (wing,)
    np.testing.assert_allclose(geometry.origins[wing], [0, 0.24, -0.2675])
    assert parts["Bus"].ancestors == ()
    # the bus's box keeps its size: 0.56 x 0.40 x 0.56 m
    corners = parts["Bus"].triangles.reshape(-1, 3)
    np.testing.assert_allclose(np.ptp(corners, axis=0), [0.56, 0.40, 0.56], atol=1e-6)


def test_strips_and_fans_become_triangles():
    indices = np.arange(5)
    np.testing.assert_array_equal(
        _triangle_corners(np.arange(7), TRIANGLES), [[0, 1, 2], [3, 4, 5]]
    )
    np.testing.assert_array_equal(
        _triangle_corners(indices, TRIANGLE_STRIP), [[0, 1, 2], [2, 1, 3], [2, 3, 4]]
    )
    np.testing.assert_array_equal(
        _triangle_corners(indices, TRIANGLE_FAN), [[0, 1, 2], [0, 2, 3], [0, 3, 4]]
    )


@pytest.mark.parametrize(
    ("node", "normal"),
    [
        ({}, [0, 0, 1]),
        # a turn of 90 deg about x takes +z to -y
        ({"rotation": [2**-0.5, 0, 0, 2**-0.5]}, [0, -1, 0]),
        # a mirror in x keeps the plate facing +z, with its winding turned round
        ({"scale": [-1, 1, 1]}, [0, 0, 1]),
        ({"matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, -1, 0, 0, 0, 0, 1]}, [0, 0, -1]),
    ],
)
def test_the_node_transforms_place_the_triangles(tmp_path, node, normal):
    path = tmp_path / "plate.glb"
    path.write_bytes(glb_with_mesh(PLATE, node))
    (part,) = read_model(path).parts
    assert part.name == "Plate"
    np.testing.assert_allclose(normal_of(part.triangles), normal, atol=1e-7)


def test_vertices_in_another_file_are_refused(tmp_path):
    path = tmp_path / "plate.glb"
    path.write_bytes(glb_with_mesh(PLATE, {}, {"byteLength": 36, "uri": "plate.bin"}))
    with pytest.raises(ValueError, match="keeps its vertices in another file"):
        read_model(path)


# ---------------------------------------------------------------- The scenario file


def test_a_plain_file_name_is_a_model_from_the_folder_of_the_file(text, data_dir):
    scenario = Scenario.from_yaml_text("3d_model: spacecraft.glb\n" + text, data_dir)
    assert scenario.spacecraft_model is not None
    assert scenario.spacecraft_model.file == data_dir / "spacecraft.glb"
    assert scenario.spacecraft_model.articulations == {}


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
    page = viewer_page()
    assert f"const PAGE_VERSION = {VERSION};" in page
    assert "GLTFLoader" in page
