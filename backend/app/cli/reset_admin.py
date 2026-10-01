"""Server operator recovery. Password is read from TTY, never arguments or output."""

import getpass
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domains.audit.service import record_audit
from app.domains.auth.models import User
from app.domains.auth.service import password_hasher, revoke_user_sessions
from app.infrastructure.database import build_engine


def main() -> None:
    if not sys.stdin.isatty():
        raise SystemExit("请在服务器交互终端执行，不支持管道输入密码。")
    password = getpass.getpass("输入新管理员密码（12–128 字符）：")
    confirmation = getpass.getpass("确认密码：")
    if not 12 <= len(password) <= 128 or password != confirmation:
        raise SystemExit("密码长度或确认不符合要求。")
    engine = build_engine(Settings())
    try:
        with Session(engine) as db:
            user = db.scalar(select(User).where(User.username == "admin").with_for_update())
            if user is None:
                raise SystemExit("管理员尚未初始化。")
            user.password_hash = password_hasher.hash(password)
            user.must_change_password = False
            revoke_user_sessions(db, user.id)
            record_audit(
                db,
                action="admin.reset",
                resource_type="account",
                actor_kind="system",
                resource_id=str(user.id),
                request_id="operator-cli",
                summary="服务器操作员重置管理员密码并撤销全部会话",
            )
            db.commit()
        print("管理员密码已重置，已有管理员会话已撤销。")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
