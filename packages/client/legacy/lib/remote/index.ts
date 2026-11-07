'use client';

// Typed JSON-RPC client. Pages call remote.<namespace>.<method>(params); they do
// not assemble REST URLs or duplicate request/response shapes.

import type { RpcMethods } from './contracts.generated';
export type * from './contracts.generated';

const DEFAULT_API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export class RemoteError extends Error {
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly httpStatus: number | null;

  constructor(
    code: string,
    message: string,
    details: Record<string, unknown> = {},
    httpStatus: number | null = null,
  ) {
    super(message);
    this.name = 'RemoteError';
    this.code = code;
    this.details = details;
    this.httpStatus = httpStatus;
  }
}

type CallOptions = { signal?: AbortSignal };

export class RpcClient {
  constructor(
    private readonly baseUrl: string = DEFAULT_API,
    private readonly tenantId: number = 1,
  ) {}

  async call<M extends keyof RpcMethods>(
    method: M,
    params: RpcMethods[M]['params'],
    options: CallOptions = {},
  ): Promise<RpcMethods[M]['result']> {
    const id = globalThis.crypto?.randomUUID?.() ?? `req-${Date.now()}-${Math.random()}`;
    const response = await fetch(`${this.baseUrl}/api/rpc`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Tenant-ID': String(this.tenantId),
      },
      body: JSON.stringify({ jsonrpc: '2.0', id, method, params }),
      signal: options.signal,
    });
    if (!response.ok) {
      throw new RemoteError(
        `transport/http-${response.status}`,
        `RPC transport failed with HTTP ${response.status}`,
        {},
        response.status,
      );
    }
    const payload = await response.json();
    if (payload === null || typeof payload !== 'object' || Array.isArray(payload)) {
      throw new RemoteError('rpc/invalid-response', 'Invalid JSON-RPC response');
    }
    if (payload.jsonrpc !== '2.0' || payload.id !== id) {
      throw new RemoteError('rpc/id-mismatch', 'JSON-RPC response id mismatch');
    }
    if (payload.error) {
      const error = payload.error as {
        code?: number;
        message?: string;
        data?: { code?: string; details?: Record<string, unknown> };
      };
      throw new RemoteError(
        error.data?.code ?? `rpc/${error.code ?? 'error'}`,
        error.message ?? 'RPC call failed',
        error.data?.details ?? {},
      );
    }
    return payload.result as RpcMethods[M]['result'];
  }
}

export function createRemote(baseUrl: string = DEFAULT_API, tenantId: number = 1) {
  const client = new RpcClient(baseUrl, tenantId);
  return {
    workspace: {
      projects: {
        list: () => client.call('workspace.projects.list', {}),
        create: (params: RpcMethods['workspace.projects.create']['params']) =>
          client.call('workspace.projects.create', params),
        update: (params: RpcMethods['workspace.projects.update']['params']) =>
          client.call('workspace.projects.update', params),
        remove: (params: RpcMethods['workspace.projects.delete']['params']) =>
          client.call('workspace.projects.delete', params),
      },
      sessions: {
        list: () => client.call('workspace.sessions.list', {}),
        create: (params: RpcMethods['workspace.sessions.create']['params']) =>
          client.call('workspace.sessions.create', params),
        rename: (params: RpcMethods['workspace.sessions.rename']['params']) =>
          client.call('workspace.sessions.rename', params),
      },
      folder: {
        ensure: (params: RpcMethods['workspace.folder.ensure']['params']) =>
          client.call('workspace.folder.ensure', params),
      },
      files: {
        list: (params: RpcMethods['workspace.files.list']['params']) =>
          client.call('workspace.files.list', params),
        create: (params: RpcMethods['workspace.files.create']['params']) =>
          client.call('workspace.files.create', params),
      },
    },
    agent: {
      list: () => client.call('agent.list', {}),
      create: (params: RpcMethods['agent.create']['params']) => client.call('agent.create', params),
      getConfig: (params: RpcMethods['agent.getConfig']['params']) =>
        client.call('agent.getConfig', params),
      saveConfig: (params: RpcMethods['agent.saveConfig']['params']) =>
        client.call('agent.saveConfig', params),
    },
    session: {
      recovery: (params: RpcMethods['session.recovery']['params']) =>
        client.call('session.recovery', params),
      trajectory: (params: RpcMethods['session.trajectory']['params']) =>
        client.call('session.trajectory', params),
      sandboxMode: {
        get: (params: RpcMethods['session.sandboxMode.get']['params']) =>
          client.call('session.sandboxMode.get', params),
        set: (params: RpcMethods['session.sandboxMode.set']['params']) =>
          client.call('session.sandboxMode.set', params),
      },
    },
  };
}

export const remote = createRemote();

export { RpcClient as client };