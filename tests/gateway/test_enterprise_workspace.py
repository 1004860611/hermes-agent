from gateway.enterprise_workspace import EnterpriseWorkspaceManager


def test_enterprise_workspace_can_resolve_without_creating_dirs(tmp_path):
    manager = EnterpriseWorkspaceManager(root=tmp_path / "enterprise")

    workspace = manager.ensure_workspace(
        user_id="staff-1",
        user_type="user",
        role="user",
        session_id="session-1",
        create_dirs=False,
    )

    assert workspace.profile_ref == "enterprise:user:staff-1"
    assert workspace.workspace_home == tmp_path / "enterprise" / "users" / "staff-1"
    assert not workspace.workspace_home.exists()


def test_enterprise_workspace_creates_dirs_by_default(tmp_path):
    manager = EnterpriseWorkspaceManager(root=tmp_path / "enterprise")

    workspace = manager.ensure_workspace(
        user_id="staff-1",
        user_type="user",
        role="user",
        session_id="session-1",
    )

    assert workspace.workspace_home.exists()
    assert workspace.memory_dir.exists()
    assert (workspace.workspace_home / "kanban" / "workspaces").exists()
