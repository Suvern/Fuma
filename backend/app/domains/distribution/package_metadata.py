"""Read cached package build numbers through the existing credential-free parser."""

import json
import os
import shutil
from datetime import datetime, timedelta
from uuid import uuid5

from app.domains.auth.service import utcnow
from app.domains.distribution.packages import cache_path
from app.domains.library.models import PackageRecord


def notification_build_number(db, settings, entry, event_id, started_at):
    """Return (build number, pending). Missing metadata never blocks distribution forever."""
    if entry.persistent_package_id:
        package = db.get(PackageRecord, entry.persistent_package_id)
        if package and package.app_id == entry.app_id and package.sha256 == entry.sha256:
            return package.build_number, False
    if entry.build_number:
        return entry.build_number, False
    if not entry.sha256:
        return None, False
    job = str(uuid5(event_id, f"notification-metadata:{entry.id}:{entry.sha256}"))
    request = settings.parser_inbox / (job + ".json")
    source = request.with_suffix(".bin")
    temporary = request.with_suffix(".tmp")
    result = settings.parser_outbox / (job + ".json")

    def cleanup():
        for path in (request, source, temporary, result):
            path.unlink(missing_ok=True)

    try:
        if result.is_file():
            if result.stat().st_size > 32768:
                cleanup()
                return None, False
            value = json.loads(result.read_text())
            metadata = value.get("metadata") if isinstance(value, dict) else None
            number = metadata.get("build_number") if isinstance(metadata, dict) else None
            if (
                value.get("ok") is True
                and value.get("sha256") == entry.sha256
                and isinstance(number, str)
                and 0 < len(number.strip()) <= 100
                and not any(ord(c) < 32 for c in number)
            ):
                entry.build_number = number.strip()
                entry.revision += 1
            cleanup()
            return entry.build_number, False
        if utcnow() - datetime.fromisoformat(started_at) > timedelta(minutes=2):
            cleanup()
            return None, False
        if not request.is_file():
            cached = cache_path(settings, entry)
            if not cached.is_file() or cached.is_symlink():
                return None, False
            settings.parser_inbox.mkdir(parents=True, exist_ok=True)
            settings.parser_outbox.mkdir(parents=True, exist_ok=True)
            # The parser sees a copy, never a mutable cache path or application credentials.
            shutil.copyfile(cached, temporary)
            os.replace(temporary, source)
            temporary.write_text(json.dumps({"platform": entry.platform, "sha256": entry.sha256}))
            os.replace(temporary, request)
        return None, True
    except (OSError, ValueError, AttributeError):
        # Parsing is supplementary; retain the normal download and notification path.
        try:
            cleanup()
        except OSError:
            pass
        return None, False
