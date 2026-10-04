"""Single offline parser consumer. Mount only parser inbox and outbox, never credentials."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID

INBOX = Path("/inbox")
OUTBOX = Path("/outbox")


def process(request_path, outbox=OUTBOX):
    job = str(UUID(request_path.stem))
    request = json.loads(request_path.read_text())
    if set(request) != {"platform", "sha256"} or request["platform"] not in {"android", "ios"}:
        return
    output = outbox / (job + ".json")
    if output.exists():
        return
    source = request_path.with_suffix(".bin")
    if not source.is_file() or source.is_symlink():
        return
    temp = output.with_suffix(".tmp")
    try:
        with temp.open("wb") as stream:
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    str(Path(__file__).with_name("parse_package.py")),
                    str(source),
                    request["platform"],
                ],
                stdout=stream,
                stderr=subprocess.DEVNULL,
                env={"PATH": "/usr/bin:/bin"},
                start_new_session=True,
            )
            try:
                if child.wait(timeout=90) != 0:
                    raise ValueError("parser failed")
            finally:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
        if temp.stat().st_size > 32768:
            raise ValueError("oversized result")
        result = json.loads(temp.read_text())
        if result.get("ok") and result.get("sha256") != request["sha256"]:
            raise ValueError("content changed")
    except Exception:
        temp.write_text(
            json.dumps({"ok": False, "error_message": "解析超时、资源超限或文件内容改变"})
        )
    os.replace(temp, output)


if __name__ == "__main__":
    OUTBOX.mkdir(parents=True, exist_ok=True)
    while True:
        for request in INBOX.glob("*.json"):
            try:
                process(request)
            except (ValueError, OSError):
                pass
        time.sleep(2)
