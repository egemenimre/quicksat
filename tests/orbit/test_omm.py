# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for element sets in CCSDS OMM.

The files in `data/` hold NUSAT-8's elements as CelesTrak and Space-Track give
them: KVN from each, and JSON and XML. Two epochs appear among them, so the
files pair up: CelesTrak's KVN and XML hold one element set, and Space-Track's
KVN and the JSON hold the other. The rest are written here.
"""

import json

import numpy as np
import pytest

from quicksat import Q_
from quicksat.orbit.omm import read_omm_file, write_omm_file

from .conftest import vectors

NUSAT_8 = "NUSAT-8 (MARIE)"


def states_mm(tle, hours=(0.0, 1.0, 24.0)):
    """Positions [mm] at times after the epoch."""
    return vectors(tle.states(tle.epoch + Q_(np.array(hours), "h")))[0]


@pytest.mark.parametrize(
    ("name", "epoch"),
    [
        ("omm_celestrak.kvn", "2020-12-29T11:59:56.952"),
        ("omm_celestrak.xml", "2020-12-29T11:59:56.952"),
        ("omm_space_track.kvn", "2020-12-29T03:57:59.407"),
        ("omm_celestrak.json", "2020-12-29T03:57:59.407"),
    ],
)
def test_each_form_of_a_real_omm_reads(data_dir, name, epoch):
    tle = read_omm_file(data_dir / name)
    assert tle.name == NUSAT_8
    assert tle.epoch.utc.isot == epoch
    assert (tle.satrec.satnum, tle.satrec.intldesg) == (45018, "20003C")
    assert np.degrees(tle.satrec.inclo) == pytest.approx(97.297)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("omm_celestrak.kvn", "omm_celestrak.xml"),
        ("omm_space_track.kvn", "omm_celestrak.json"),
    ],
)
def test_one_element_set_in_two_forms_gives_the_same_states(data_dir, first, second):
    found = states_mm(read_omm_file(data_dir / first))
    expected = states_mm(read_omm_file(data_dir / second))
    assert np.array_equal(found, expected)


def test_a_csv_reads_as_its_json_does(data_dir, tmp_path):
    record = json.loads((data_dir / "omm_celestrak.json").read_text())[0]
    path = tmp_path / "nusat.csv"
    path.write_text(
        ",".join(record) + "\n" + ",".join(str(v) for v in record.values()) + "\n"
    )
    found = read_omm_file(path)
    assert found.name == NUSAT_8
    assert np.array_equal(
        states_mm(found), states_mm(read_omm_file(data_dir / "omm_celestrak.json"))
    )


@pytest.mark.parametrize("source", ["tle", "omm"])
def test_a_written_file_reads_back_to_the_same_elements(
    request, data_dir, tmp_path, source
):
    tle = (
        request.getfixturevalue("tle")
        if source == "tle"
        else read_omm_file(data_dir / "omm_space_track.kvn")
    )
    path = write_omm_file(tmp_path / "out.omm", tle, creation_date=tle.epoch)
    back = read_omm_file(path)
    assert back.lines == tle.lines
    assert np.array_equal(states_mm(back), states_mm(tle))


def changed(data_dir, tmp_path, old, new, name="omm_celestrak.kvn"):
    """A changed copy of a sample OMM."""
    text = (data_dir / name).read_text()
    assert old in text
    path = tmp_path / name
    path.write_text(text.replace(old, new))
    return path


@pytest.mark.parametrize(
    "epoch",
    ["2020-12-29T11:59:56.951808Z", "2020-364T11:59:56.951808", "2020-12-29T11:59:56"],
)
def test_an_epoch_may_end_in_z_be_a_day_of_the_year_or_have_no_fraction(
    data_dir, tmp_path, epoch
):
    path = changed(data_dir, tmp_path, "2020-12-29T11:59:56.951808", epoch)
    tle = read_omm_file(path)
    assert tle.epoch.utc.isot[:19] == "2020-12-29T11:59:56"


def test_the_bookkeeping_fields_may_be_left_out(data_dir, tmp_path):
    text = (data_dir / "omm_celestrak.kvn").read_text()
    kept = [
        line
        for line in text.splitlines()
        if not line.startswith(
            (
                "EPHEMERIS_TYPE",
                "CLASSIFICATION_TYPE",
                "NORAD_CAT_ID",
                "ELEMENT_SET_NO",
                "REV_AT_EPOCH",
                "MEAN_MOTION_D",
                "OBJECT_ID",
            )
        )
    ]
    path = tmp_path / "bare.kvn"
    path.write_text("\n".join(kept) + "\nOBJECT_ID = UNKNOWN\n")
    tle = read_omm_file(path)
    assert (tle.satrec.satnum, tle.satrec.elnum, tle.satrec.intldesg) == (0, 999, "")
    assert np.allclose(
        states_mm(tle),
        states_mm(read_omm_file(data_dir / "omm_celestrak.kvn")),
        atol=1.0,
    )


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "REF_FRAME      = TEME",
            "REF_FRAME = EME2000",
            "REF_FRAME = EME2000, but SGP4's elements need TEME",
        ),
        (
            "MEAN_ELEMENT_THEORY = SGP4",
            "MEAN_ELEMENT_THEORY = DSST",
            "MEAN_ELEMENT_THEORY = DSST",
        ),
        ("CENTER_NAME    = EARTH", "CENTER_NAME = MOON", "CENTER_NAME = MOON"),
        ("TIME_SYSTEM    = UTC", "TIME_SYSTEM = TAI", "TIME_SYSTEM = TAI"),
        (
            "MEAN_MOTION    = 15.27990594",
            "SEMI_MAJOR_AXIS = 6859.96",
            "gives SEMI_MAJOR_AXIS",
        ),
        ("BSTAR          = .83483E-4", "", "the OMM has no BSTAR"),
        (
            "MEAN_MOTION    = 15.27990594",
            "MEAN_MOTION = fast",
            "MEAN_MOTION = fast is not a number",
        ),
        (
            "EPOCH          = 2020-12-29T11:59:56.951808",
            "EPOCH = yesterday",
            "EPOCH = yesterday is not an epoch",
        ),
        (
            "OBJECT_NAME    = NUSAT-8 (MARIE)",
            "OBJECT_NAME NUSAT",
            r"line \d+: expected KEY = value",
        ),
    ],
)
def test_elements_sgp4_cannot_use_are_refused(data_dir, tmp_path, old, new, message):
    with pytest.raises(ValueError, match=message):
        read_omm_file(changed(data_dir, tmp_path, old, new))


def test_a_file_of_several_or_of_another_form_is_refused(data_dir, tmp_path):
    record = json.loads((data_dir / "omm_celestrak.json").read_text())[0]
    two = tmp_path / "two.json"
    two.write_text(json.dumps([record, record]))
    with pytest.raises(ValueError, match="exactly one element set here. Found 2"):
        read_omm_file(two)
    plain = tmp_path / "plain.txt"
    plain.write_text("1 45018U 20003C   20364.16527091\n")
    with pytest.raises(ValueError, match="not an OMM that quicksat reads"):
        read_omm_file(plain)
    broken = changed(
        data_dir, tmp_path, "<tleParameters>", "<other>", "omm_celestrak.xml"
    )
    broken.write_text(broken.read_text().replace("</tleParameters>", "</other>"))
    with pytest.raises(ValueError, match="the OMM cannot be read"):
        read_omm_file(broken)
    with pytest.raises(FileNotFoundError):
        read_omm_file(tmp_path / "nowhere.omm")
