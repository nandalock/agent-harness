import * as ReactQuery from '@tanstack/react-query';
import React from 'react';
import * as ReactDOM from 'react-dom';
import { createRoot } from 'react-dom/client';
import * as jsxRuntime from 'react/jsx-runtime';
import * as jsxDevRuntime from 'react/jsx-dev-runtime';

import * as hostModule from '../shell/host-api';
import { installGlobalFacade, installPlatformModules, loadEntry, materialize } from './module-loader';
import type { Plugin, WebBootEntry, WebBootGraph } from './types';

function sortEntries(entries: WebBootEntry[]): WebBootEntry[] {
  const byId = new Map(entries.map((entry) => [entry.id, entry]));
  const indegree = new Map(entries.map((entry) => [entry.id, 0]));
  const outgoing = new Map<string, string[]>(entries.map((entry) => [entry.id, []]));

  for (const entry of entries) {
    for (const dependency of entry.inject ?? []) {
      if (!byId.has(dependency)) continue;
      indegree.set(entry.id, (indegree.get(entry.id) ?? 0) + 1);
      outgoing.get(dependency)!.push(entry.id);
    }
  }

  const order = new Map(entries.map((entry, index) => [entry.id, index]));
  const ready = entries
    .filter((entry) => indegree.get(entry.id) === 0)
    .map((entry) => entry.id);
  const result: WebBootEntry[] = [];

  while (ready.length > 0) {
    ready.sort((a, b) => (order.get(a) ?? 0) - (order.get(b) ?? 0));
    const id = ready.shift()!;
    result.push(byId.get(id)!);
    for (const dependent of outgoing.get(id) ?? []) {
      const next = (indegree.get(dependent) ?? 0) - 1;
      indegree.set(dependent, next);
      if (next === 0) ready.push(dependent);
    }
  }

  if (result.length !== entries.length) {
    throw new Error('client-modules: dependency cycle in boot graph');
  }
  return result;
}

export async function boot(): Promise<void> {
  const graph = (window as any).__DSH_BOOT__ as WebBootGraph | undefined;
  if (!graph?.entries?.length) {
    throw new Error('client-modules: window.__DSH_BOOT__ is missing');
  }

  installGlobalFacade();
  const hostApi = hostModule.createHostApi();
  installPlatformModules({
    react: React,
    'react-dom': ReactDOM,
    'react-dom/client': { createRoot },
    'react/jsx-runtime': jsxRuntime,
    'react/jsx-dev-runtime': jsxDevRuntime,
    '@app/host': hostModule,
    '@tanstack/react-query': ReactQuery,
  });

  const entries = sortEntries(graph.entries);
  await Promise.all(entries.map((entry) => loadEntry(entry)));

  for (const entry of entries) {
    const plugin = materialize(entry.id) as Plugin;
    if (!plugin || typeof plugin.setup !== 'function') {
      throw new Error(`client-modules: ${entry.id} does not export a setup() plugin`);
    }
    await plugin.setup(hostApi.context(entry.id));
  }

  hostModule.renderRoot();
}
