# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Trajectory files, told apart by what they hold.

quicksat reads two formats: ECSV, in `quicksat.orbit.ecsv_trajectory`, and
CCSDS OEM in KVN, in `quicksat.orbit.oem_trajectory`. OEM files come named
`.oem`, `.txt` or `.kvn`, so the name says too little. The first line that is
neither blank nor a comment tells instead: `# %ECSV` starts an ECSV file, and
`CCSDS_OEM_VERS` an OEM. An XML OEM is refused.

"""

from pathlib import Path

from quicksat.orbit.ecsv_trajectory import read_ecsv_trajectory
from quicksat.orbit.oem_trajectory import read_oem_trajectory
from quicksat.orbit.trajectory import Trajectory

ECSV = "ECSV"
OEM = "OEM"


def trajectory_format(path: str | Path) -> str:
    """
    The format of a trajectory file, from its first line that says anything.

    Parameters
    ----------
    path : str | Path
        Filepath of the trajectory file

    Returns
    -------
    format : str
        `ECSV` or `OEM`

    Raises
    ------
    FileNotFoundError
        If the file does not exist
    ValueError
        If the file is an XML OEM, or neither format
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"File does not exist: {path}")
    with open(path, errors="replace") as file:
        for raw in file:
            line = raw.strip()
            if not line or line.startswith("COMMENT"):
                continue
            if line.startswith("# %ECSV"):
                return ECSV
            if line.startswith("CCSDS_OEM_VERS"):
                return OEM
            if line.startswith("<"):
                raise ValueError(
                    f"{path}: an XML OEM is not read. Convert it to KVN, the "
                    "plain-text form."
                )
            break
    raise ValueError(
        f"{path}: not a trajectory file quicksat reads. An ECSV file starts with "
        "'# %ECSV', and a CCSDS OEM in KVN with CCSDS_OEM_VERS."
    )


def read_trajectory_file(path: str | Path) -> Trajectory:
    """
    Read a trajectory file in either format.

    Parameters
    ----------
    path : str | Path
        Filepath of the trajectory file

    Returns
    -------
    trajectory : Trajectory
        The trajectory, in GCRS
    """
    if trajectory_format(path) == ECSV:
        return read_ecsv_trajectory(path)
    return read_oem_trajectory(path)
