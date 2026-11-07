"""Workspace controller plugin: registers workspace.* RPC methods."""
from agent_platform_plugin_sdk import (
    DATABASE,
    PluginContext,
    PluginSpec,
    SdkModel,
    ServiceRequirement,
)
from agent_platform_rpc_gateway import RPC_GATEWAY, RpcMethodContract
from agent_platform_session_persistence import SESSION_PERSISTENCE
from agent_platform_session_title import SESSION_TITLE

from .models import (
    WorkspaceFileCreateParams,
    WorkspaceFileCreateResult,
    WorkspaceFilesListParams,
    WorkspaceFilesListResult,
    WorkspaceFolderEnsureParams,
    WorkspaceFolderEnsureResult,
    WorkspaceProjectCreateParams,
    WorkspaceProjectCreateResult,
    WorkspaceProjectDeleteParams,
    WorkspaceProjectDeleteResult,
    WorkspaceProjectUpdateParams,
    WorkspaceProjectUpdateResult,
    WorkspaceProjectsListParams,
    WorkspaceProjectsListResult,
    WorkspaceSessionCreateParams,
    WorkspaceSessionCreateResult,
    WorkspaceSessionRenameParams,
    WorkspaceSessionRenameResult,
    WorkspaceSessionsListParams,
    WorkspaceSessionsListResult,
)
from .service import WorkspaceService
from .services import WORKSPACE_CONTROLLER

METHODS = (
    RpcMethodContract("workspace.sessions.list", WorkspaceSessionsListParams, WorkspaceSessionsListResult),
    RpcMethodContract("workspace.sessions.create", WorkspaceSessionCreateParams, WorkspaceSessionCreateResult),
    RpcMethodContract("workspace.sessions.rename", WorkspaceSessionRenameParams, WorkspaceSessionRenameResult),
    RpcMethodContract("workspace.projects.list", WorkspaceProjectsListParams, WorkspaceProjectsListResult),
    RpcMethodContract("workspace.projects.create", WorkspaceProjectCreateParams, WorkspaceProjectCreateResult),
    RpcMethodContract("workspace.projects.update", WorkspaceProjectUpdateParams, WorkspaceProjectUpdateResult),
    RpcMethodContract("workspace.projects.delete", WorkspaceProjectDeleteParams, WorkspaceProjectDeleteResult),
    RpcMethodContract("workspace.folder.ensure", WorkspaceFolderEnsureParams, WorkspaceFolderEnsureResult),
    RpcMethodContract("workspace.files.list", WorkspaceFilesListParams, WorkspaceFilesListResult),
    RpcMethodContract("workspace.files.create", WorkspaceFileCreateParams, WorkspaceFileCreateResult),
)


class WorkspaceConfig(SdkModel):
    pass


class WorkspaceControllerPlugin:
    spec = PluginSpec(
        name="agent-platform.api-workspace",
        web_package=__package__,
        version="0.1.0",
        provides=(WORKSPACE_CONTROLLER.ref,),
        requires=(
            ServiceRequirement(service=RPC_GATEWAY.ref),
            ServiceRequirement(service=DATABASE.ref),
            ServiceRequirement(service=SESSION_PERSISTENCE.ref),
            ServiceRequirement(service=SESSION_TITLE.ref),
        ),
    )
    config_model = WorkspaceConfig

    async def setup(self, ctx: PluginContext, config: WorkspaceConfig) -> None:
        service = WorkspaceService(
            ctx.require(DATABASE),
            ctx.require(SESSION_PERSISTENCE),
            ctx.require(SESSION_TITLE),
        )
        ctx.provide(WORKSPACE_CONTROLLER, service)
        gateway = ctx.require(RPC_GATEWAY)
        contracts = {contract.method: contract for contract in METHODS}

        async def sessions_list(params, context):
            items, truncated = await service.list_sessions(context.tenant_id)
            return WorkspaceSessionsListResult(items=items, truncated=truncated)

        async def sessions_create(params, context):
            session = await service.create_session(
                context.tenant_id, params.agent_key, params.folder, params.folder_path,
            )
            return WorkspaceSessionCreateResult(session=session)

        async def sessions_rename(params, context):
            snapshot = await service.rename_session(
                context.tenant_id, params.session_id, params.title,
            )
            return WorkspaceSessionRenameResult(
                session_id=params.session_id,
                title=snapshot.title,
                title_source=snapshot.source,
            )

        async def projects_list(params, context):
            return WorkspaceProjectsListResult(items=await service.list_projects(context.tenant_id))

        async def projects_create(params, context):
            created, project = await service.create_project(
                context.tenant_id, params.path, params.title,
            )
            return WorkspaceProjectCreateResult(created=created, project=project)

        async def projects_update(params, context):
            project = await service.update_project(
                context.tenant_id, params.project_id, params.title, params.sort_order,
            )
            return WorkspaceProjectUpdateResult(project=project)

        async def projects_delete(params, context):
            path = await service.delete_project(context.tenant_id, params.project_id)
            return WorkspaceProjectDeleteResult(
                deleted=True, project_id=params.project_id, path=path,
            )

        async def folder_ensure(params, context):
            return WorkspaceFolderEnsureResult(**await service.ensure_folder(params.name))

        async def files_list(params, context):
            entries, truncated, writable = await service.list_files(
                context.tenant_id, params.session_id, params.path,
            )
            return WorkspaceFilesListResult(entries=entries, truncated=truncated, writable=writable)

        async def files_create(params, context):
            entry = await service.create_file(
                context.tenant_id, params.session_id, params.path, params.name, params.type,
            )
            return WorkspaceFileCreateResult(entry=entry)

        handlers = {
            "workspace.sessions.list": sessions_list,
            "workspace.sessions.create": sessions_create,
            "workspace.sessions.rename": sessions_rename,
            "workspace.projects.list": projects_list,
            "workspace.projects.create": projects_create,
            "workspace.projects.update": projects_update,
            "workspace.projects.delete": projects_delete,
            "workspace.folder.ensure": folder_ensure,
            "workspace.files.list": files_list,
            "workspace.files.create": files_create,
        }
        for method, handler in handlers.items():
            ctx.track(gateway.register(contracts[method], handler))


plugin = WorkspaceControllerPlugin()
