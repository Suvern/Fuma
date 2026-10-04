"""Current-role checkpoints for human-started tasks, inherited by child work."""

from app.core.errors import AppError


def check_task_authorization(db, task=None):
    if task is None:
        task = db.info.get("active_task")
    if task is None:
        return
    db.info["actor_app_id"] = task.app_id
    if task.created_actor_id is None:
        # CI/scheduler and pre-upgrade tasks retain their existing business gates.
        # No browser or user receives authority from this compatibility path.
        db.info.pop("actor_user_id", None)
        db.info.pop("actor_permission_revision", None)
        return
    from app.domains.access.authorization import require_actor_permission

    try:
        user = require_actor_permission(db, task.created_actor_id, task.app_id, lock=True)
    except AppError:
        raise AppError(
            403,
            "TASK_AUTHORIZATION_REVOKED",
            "任务发起者已失去管理权限，已停止后续操作；已提交的第三方请求仍需核对结果",
        ) from None
    db.info["actor_user_id"] = user.id
    db.info["actor_permission_revision"] = user.permission_revision
