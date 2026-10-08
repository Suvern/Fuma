"""Scan project files without opening local dotenv files or traversing Git history."""

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from urllib.request import urlopen

VERSION = "8.30.1"
ARCHIVES = {
    ("Linux", "x86_64"): (
        "linux_x64",
        "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb",
    ),
    ("Darwin", "arm64"): (
        "darwin_arm64",
        "b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5",
    ),
}
root = Path(__file__).resolve().parents[1]
tracked = set(subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0"))
untracked = set(
    subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=root)
    .decode()
    .split("\0")
)
system = (platform.system(), platform.machine())
if system not in ARCHIVES:
    raise SystemExit(
        "The pinned scanner supports Linux x86_64 and macOS arm64; "
        "add and verify a platform checksum first"
    )
target, digest = ARCHIVES[system]
with tempfile.TemporaryDirectory(prefix="fuma-secret-scan-") as temporary:
    temp = Path(temporary)
    snapshot = temp / "source"
    snapshot.mkdir()
    copied = 0
    for name in sorted((tracked | untracked) - {""}):
        relative = Path(name)
        if any(p == ".env" or p.startswith(".env.") or p.endswith(".env") for p in relative.parts):
            if name in tracked and relative.name != ".env.example":
                raise SystemExit(f"A real dotenv file is tracked: {name}; its content was not read")
            continue
        # Reject links before copying, so a link cannot bypass the dotenv exclusion.
        if any(
            (root / Path(*relative.parts[:i])).is_symlink()
            for i in range(1, len(relative.parts) + 1)
        ):
            raise SystemExit(f"Review symlink before scanning: {name}")
        source = root / relative
        if not source.exists():
            continue
        destination = snapshot / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        copied += 1
    archive_path = temp / "gitleaks.tar.gz"
    url = f"https://github.com/gitleaks/gitleaks/releases/download/v{VERSION}/gitleaks_{VERSION}_{target}.tar.gz"
    with urlopen(url, timeout=60) as response, archive_path.open("wb") as output:
        shutil.copyfileobj(response, output)
    if hashlib.sha256(archive_path.read_bytes()).hexdigest() != digest:
        raise SystemExit("Gitleaks archive checksum mismatch")
    executable = temp / "gitleaks"
    with tarfile.open(archive_path) as archive:
        member = archive.getmember("gitleaks")
        if not member.isfile():
            raise SystemExit("Invalid scanner archive")
        with archive.extractfile(member) as source, executable.open("wb") as output:
            shutil.copyfileobj(source, output)
    executable.chmod(0o700)
    report = temp / "report.json"
    scanner_env = dict(os.environ)
    scanner_env.pop("GITLEAKS_CONFIG", None)
    scanner_env.pop("GITLEAKS_CONFIG_TOML", None)
    result = subprocess.run(
        [
            str(executable),
            "dir",
            str(snapshot),
            "--redact=100",
            "--no-banner",
            "--report-format=json",
            "--report-path",
            str(report),
        ],
        cwd=temp,
        env=scanner_env,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        if report.exists():
            for finding in json.loads(report.read_text()):
                # Do not print matched lines, secrets, descriptions, or raw scanner output.
                location = Path(finding["File"])
                if location.is_absolute():
                    location = location.relative_to(snapshot)
                print(f"{finding['RuleID']}: {location}:{finding['StartLine']}")
        raise SystemExit("Secret scan failed; inspect the reported locations privately")
    print(
        f"Gitleaks {VERSION}: {copied} files scanned, no findings; "
        "dotenv files and history excluded"
    )
