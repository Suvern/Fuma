"""Explicit management route scopes; unknown operations remain administrator-only.

Resource ownership always comes from persisted rows, never body/query app IDs.
Global lists apply their own SQL scope before counting/pagination.
"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from app.api.dependencies import DB, require_user
from app.core.errors import AppError
from app.domains.access.authorization import (
    manageable_app_ids,
    require_app_permission,
    require_manager,
)
from app.domains.applications.models import AppRecord
from app.domains.auth.service import AuthContext
from app.domains.distribution.models import (
    DebugRecord,
    DeliveryRecord,
    EventRecord,
    PackageIngestionRecord,
    RuleRecord,
    TaskRecord,
)
from app.domains.library.models import PackageRecord, PublicationRecord, UploadRecord, VersionRecord

LIST_OPERATIONS = {"list_notifications", "list_apps", "list_audit_events", "list_tasks"}
RESOURCE_OPERATIONS = {
    "get_release_notification_template": AppRecord,
    "update_release_notification_template": AppRecord,
    "get_apps": AppRecord,
    "update_apps": AppRecord,
    "get_app_archive_impact": AppRecord,
    "archive_app": AppRecord,
    "restore_app": AppRecord,
    "create_upload": AppRecord,
    "list_uploads": AppRecord,
    "list_packages": AppRecord,
    "create_version": AppRecord,
    "list_versions": AppRecord,
    "import_package": AppRecord,
    "get_release_default": AppRecord,
    "set_release_default": AppRecord,
    "get_app_distribution_statistics": AppRecord,
    "list_debug_entries": AppRecord,
    "create_debug_entries": AppRecord,
    "list_github_releases": AppRecord,
    "refresh_github_releases": AppRecord,
    "get_release_policy": AppRecord,
    "update_release_policy": AppRecord,
    "preview_release_import": AppRecord,
    "import_release_matches": AppRecord,
    "list_actions_rules": AppRecord,
    "list_build_events": AppRecord,
    "get_upload": UploadRecord,
    "put_upload_part": UploadRecord,
    "cancel_upload": UploadRecord,
    "complete_upload": UploadRecord,
    "retry_upload": UploadRecord,
    "get_package": PackageRecord,
    "update_package_notes": PackageRecord,
    "package_deletion_impact": PackageRecord,
    "delete_package": PackageRecord,
    "get_version": VersionRecord,
    "update_version": VersionRecord,
    "create_publication": VersionRecord,
    "list_publications": VersionRecord,
    "get_publication": PublicationRecord,
    "publish_publication": PublicationRecord,
    "unpublish_publication": PublicationRecord,
    "archive_publication": PublicationRecord,
    "restore_publication": PublicationRecord,
    "retry_publication_access": PublicationRecord,
    "persist_legacy_package": DebugRecord,
    "get_debug_entry": DebugRecord,
    "update_debug_entry": DebugRecord,
    "precache_debug_entry": DebugRecord,
    "get_actions_rule": RuleRecord,
    "update_actions_rule": RuleRecord,
    "delete_actions_rule": RuleRecord,
    "rotate_actions_token": RuleRecord,
    "revoke_actions_token": RuleRecord,
    "get_build_event": EventRecord,
    "get_package_ingestion": PackageIngestionRecord,
    "list_package_ingestions": AppRecord,
    "import_cos_package": AppRecord,
    "list_cos_package_objects": AppRecord,
    "retry_package_ingestion": PackageIngestionRecord,
    "publish_package_ingestion": PackageIngestionRecord,
    "retry_build_event": EventRecord,
    "get_task": TaskRecord,
    "retry_task": TaskRecord,
    "get_notification": DeliveryRecord,
    "retry_notification": DeliveryRecord,
    "list_available_storage": AppRecord,
    "get_app_package_storage": AppRecord,
    "update_app_package_storage": AppRecord,
}


def require_scoped_manager(
    request: Request,
    db: DB,
    context: Annotated[AuthContext, Depends(require_user)],
) -> AuthContext:
    lock = request.method not in {"GET", "HEAD", "OPTIONS"}
    require_manager(db, context, lock=lock)
    operation = getattr(request.scope.get("route"), "operation_id", None)
    db.info.pop("actor_app_id", None)
    if operation in LIST_OPERATIONS:
        return context
    model = RESOURCE_OPERATIONS.get(operation)
    if model is None:
        if manageable_app_ids(db, context) is not None:
            raise AppError(403, "ADMIN_REQUIRED", "此操作需要管理员权限")
        return context
    try:
        id = UUID(str(request.path_params["id"]))
    except (KeyError, ValueError) as exc:
        raise AppError(422, "VALIDATION_ERROR", "资源标识不合法") from exc
    if model is AppRecord:
        app_id = id
    else:
        resource = db.get(model, id)
        if resource is None:
            raise AppError(404, "RESOURCE_NOT_AVAILABLE", "资源不存在或不可用")
        app_id = resource.app_id
    if app_id is None:
        if manageable_app_ids(db, context) is not None:
            raise AppError(403, "ADMIN_REQUIRED", "此资源仅供管理员管理")
    else:
        require_app_permission(db, context, app_id, lock=lock)
        db.info["actor_app_id"] = app_id
    return context


ScopedManager = Annotated[AuthContext, Depends(require_scoped_manager)]
