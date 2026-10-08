"""Verify that distributable archives contain the canonical project notices."""

import tarfile
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
names = ("LICENSE", "THIRD_PARTY_NOTICES.md")
for name in names:
    expected = (root / name).read_bytes()
    if (root / "backend" / name).read_bytes() != expected:
        raise SystemExit(f"backend/{name} differs from the canonical root file")
    if (root / "frontend/dist" / name).read_bytes() != expected:
        raise SystemExit(f"frontend/dist/{name} is missing or outdated")
wheels = list((root / "backend/dist").glob("*.whl"))
sdists = list((root / "backend/dist").glob("*.tar.gz"))
if not wheels or not sdists:
    raise SystemExit("Build both the backend wheel and source distribution first")
for wheel in wheels:
    with zipfile.ZipFile(wheel) as archive:
        for name in names:
            matches = [p for p in archive.namelist() if p.endswith(f".dist-info/licenses/{name}")]
            if len(matches) != 1 or archive.read(matches[0]) != (root / name).read_bytes():
                raise SystemExit(f"{wheel.name} does not include the current {name}")
for sdist in sdists:
    with tarfile.open(sdist) as archive:
        for name in names:
            matches = [
                m
                for m in archive.getmembers()
                if m.name.count("/") == 1 and m.name.endswith("/" + name)
            ]
            if len(matches) != 1 or not matches[0].isfile():
                raise SystemExit(f"{sdist.name} does not include {name}")
            with archive.extractfile(matches[0]) as source:
                if source.read() != (root / name).read_bytes():
                    raise SystemExit(f"{sdist.name} contains an outdated {name}")
for name in ("dependency-licenses.json", "THIRD_PARTY_LICENSES.txt"):
    if not (root / "frontend/dist" / name).is_file():
        raise SystemExit(f"The frontend build does not include {name}")
print("Release archives and frontend build contain the canonical license notices")
