"""Workspace RPC request/response contracts (single source for TS generation)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkspaceProject(_Model):
    id: int
    key: str
    label: str
    path: str
    sort_order: float


class WorkspaceSession(_Model):
    session_id: str
    agent_key: str | None = None
    agent_name: str | None = None
    conversation_id: int
    title: str
    title_source: str | None = None
    project: WorkspaceProject | None = None
    label: str
    channel: str | None = None
    updated_at: str | None = None
    entries: int = 0


class WorkspaceProjectsListParams(_Model):
    pass


class WorkspaceProjectsListResult(_Model):
    items: list[WorkspaceProject]


class WorkspaceProjectCreateParams(_Model):
    path: str
    title: str | None = None


class WorkspaceProjectCreateResult(_Model):
    created: bool
    project: WorkspaceProject


class WorkspaceProjectUpdateParams(_Model):
    project_id: int
    title: str | None = None
    sort_order: float | None = None


class WorkspaceProjectUpdateResult(_Model):
    project: WorkspaceProject


class WorkspaceProjectDeleteParams(_Model):
    project_id: int


class WorkspaceProjectDeleteResult(_Model):
    deleted: bool
    project_id: int
    path: str


class WorkspaceSessionsListParams(_Model):
    pass


class WorkspaceSessionsListResult(_Model):
    items: list[WorkspaceSession]
    truncated: bool


class WorkspaceSessionRenameParams(_Model):
    session_id: str
    title: str


class WorkspaceSessionRenameResult(_Model):
    session_id: str
    title: str
    title_source: str


class WorkspaceSessionCreateParams(_Model):
    agent_key: str
    folder: str | None = None
    folder_path: str | None = None


class CreatedWorkspaceSession(_Model):
    session_id: str
    conversation_id: int
    agent_key: str
    agent_name: str
    label: str
    folder: str | None = None


class WorkspaceSessionCreateResult(_Model):
    session: CreatedWorkspaceSession


class WorkspaceFolderEnsureParams(_Model):
    name: str


class WorkspaceFolderEnsureResult(_Model):
    path: str
    host_path: str
    folder: str
    writable: bool


class WorkspaceFileEntry(_Model):
    name: str
    is_dir: bool
    size: int = 0
    mtime: str | None = None
    is_link: bool = False
    outside: bool = False
    writable: bool | None = None


class WorkspaceFilesListParams(_Model):
    session_id: str
    path: str = ""


class WorkspaceFilesListResult(_Model):
    entries: list[WorkspaceFileEntry]
    truncated: bool
    writable: bool


class WorkspaceFileCreateParams(_Model):
    session_id: str
    path: str = ""
    name: str
    type: str = Field(pattern="^(file|dir)$")


class WorkspaceFileCreateResult(_Model):
    entry: WorkspaceFileEntry
