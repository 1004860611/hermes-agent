"""Enterprise user workspace routing for API-server turns."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from hermes_constants import get_hermes_home


_ADMIN_TYPES = {"admin", "administrator", "superadmin", "owner"}


def safe_workspace_key(value: Any) -> str:
    text = str(value or "").strip()
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._")
    return safe[:128] or "unknown"


@dataclass(frozen=True)
class EnterpriseWorkspace:
    user_id: str
    user_type: str
    role: str
    client_session_id: str
    safe_user_id: str
    safe_session_id: str
    profile_ref: str
    workspace_ref: str
    workspace_home: Path
    session_id: str
    memory_dir: Path
    state_db_path: Path
    kanban_db_path: Path

    def as_context(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "user_type": self.user_type,
            "enterprise_role": self.role,
            "profile_ref": self.profile_ref,
            "workspace_ref": self.workspace_ref,
            "workspace_home": str(self.workspace_home),
            "session_id": self.client_session_id,
            "hermes_session_id": self.session_id,
            "memory_dir": str(self.memory_dir),
            "state_db_path": str(self.state_db_path),
            "kanban_db_path": str(self.kanban_db_path),
        }


class EnterpriseWorkspaceManager:
    """Resolve deterministic, persistent workspaces for enterprise users."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else get_hermes_home() / "enterprise"

    @staticmethod
    def role_for_user(user: Dict[str, Any]) -> str:
        user_type = str(user.get("type") or "").strip().lower()
        explicit_role = str(user.get("role") or "").strip().lower()
        if user.get("isAdmin") is True or user_type in _ADMIN_TYPES or explicit_role in _ADMIN_TYPES:
            return "admin"
        return "user"

    def ensure_workspace(
        self,
        *,
        user_id: str,
        user_type: str,
        role: str,
        session_id: str,
        create_dirs: bool = True,
    ) -> EnterpriseWorkspace:
        safe_user_id = safe_workspace_key(user_id)
        safe_session_id = safe_workspace_key(session_id)
        bucket = "admins" if role == "admin" else "users"
        workspace_home = self.root / bucket / safe_user_id
        memory_dir = workspace_home / "memories"
        state_db_path = workspace_home / "state.db"
        kanban_db_path = workspace_home / "kanban.db"
        if create_dirs:
            for path in (workspace_home, memory_dir, workspace_home / "kanban" / "workspaces", workspace_home / "kanban" / "logs"):
                path.mkdir(parents=True, exist_ok=True)

        profile_ref = f"enterprise:{role}:{user_id}"
        workspace_ref = f"workspace:{role}:{user_id}"
        hermes_session_id = f"enterprise_{role}_{safe_user_id}__session_{safe_session_id}"
        return EnterpriseWorkspace(
            user_id=user_id,
            user_type=user_type,
            role=role,
            client_session_id=session_id,
            safe_user_id=safe_user_id,
            safe_session_id=safe_session_id,
            profile_ref=profile_ref,
            workspace_ref=workspace_ref,
            workspace_home=workspace_home,
            session_id=hermes_session_id,
            memory_dir=memory_dir,
            state_db_path=state_db_path,
            kanban_db_path=kanban_db_path,
        )
