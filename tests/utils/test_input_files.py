# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for reading the input files: the YAML files through `YamlFile`, the CSV
files through `read_csv_rows` and `validated_rows`, and the fractions.
"""

import pytest
from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from quicksat import Q_
from quicksat.utils.parser_helpers import (
    UnitFractionQty,
    YamlFile,
    read_csv_rows,
    validated_rows,
)


class _File(YamlFile):
    """A YAML file with one name, which notes the folder it was read from."""

    model_config = ConfigDict(extra="forbid")

    name: str

    @field_validator("name")
    @classmethod
    def _folder(cls, name: str, info: ValidationInfo) -> str:
        """Appends the folder from the validation context, when there is one."""
        base_dir = (info.context or {}).get("base_dir")
        return name if base_dir is None else f"{name} in {base_dir.name}"


class _Optional(YamlFile):
    """A YAML file whose every key may be left out."""

    _EMPTY_ALLOWED = True

    name: str | None = None


class _Row(BaseModel):
    """One row of a CSV file."""

    count: int


class _Fraction(BaseModel):
    """A fraction, read as a file's field is."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    efficiency: UnitFractionQty


def test_a_file_keeps_its_path_and_its_text(tmp_path):
    text = "name: héliostat  # 20 °C\n"
    path = tmp_path / "file.yaml"
    path.write_text(text, encoding="utf-8")
    model = _File.from_yaml_file(path)
    assert model.name == f"héliostat in {tmp_path.name}"
    assert model.source_file == path
    assert model.source_text == text


def test_text_keeps_its_text_and_has_no_folder():
    model = _File.from_yaml_text("name: radiator\n")
    assert model.name == "radiator"
    assert model.source_file is None
    assert model.source_text == "name: radiator\n"


@pytest.mark.parametrize("text", ["- radiator\n- aperture\n", "radiator\n"])
def test_text_that_is_not_a_mapping_is_refused(text):
    with pytest.raises(ValueError, match="mapping of keys to values"):
        _File.from_yaml_text(text)


def test_empty_text_is_refused():
    with pytest.raises(ValueError, match="empty"):
        _File.from_yaml_text("")


@pytest.mark.parametrize("text", ["", "# only a note\n"])
def test_empty_text_may_read_with_every_key_left_out(text):
    assert _Optional.from_yaml_text(text).name is None


def test_a_missing_file_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError, match="does not exist"):
        _File.from_yaml_file(tmp_path / "missing.yaml")


def test_the_spaces_after_a_comma_are_taken_out(tmp_path):
    path = tmp_path / "rows.csv"
    path.write_text("name, count\nradiator, 2\n")
    frame = read_csv_rows(path, ["name", "count"])
    assert list(frame.columns) == ["name", "count"]
    assert frame.to_dict("records") == [{"name": "radiator", "count": "2"}]


def test_a_missing_column_is_named(tmp_path):
    path = tmp_path / "rows.csv"
    path.write_text("name\nradiator\n")
    with pytest.raises(ValueError, match=r"rows.csv: missing columns \['count'\]"):
        read_csv_rows(path, ["name", "count"])


def test_a_row_that_does_not_read_names_its_file_and_line():
    records = [{"count": "2"}, {"count": "two"}]
    with pytest.raises(ValueError, match="rows.csv, row 3"):
        validated_rows(_Row, records, "rows.csv")


@pytest.mark.parametrize("text", ["100 %", "0.5", "1"])
def test_a_fraction_up_to_one_is_read(text):
    assert 0 < _Fraction.model_validate({"efficiency": text}).efficiency <= Q_(1, "")


@pytest.mark.parametrize("text", ["0", "120 %", "1.2"])
def test_a_fraction_of_zero_or_above_one_is_refused(text):
    with pytest.raises(ValueError, match="efficiency must be above 0 and at most 1"):
        _Fraction.model_validate({"efficiency": text})
