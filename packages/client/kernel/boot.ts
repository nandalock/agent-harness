import * as ReactQuery from '@tanstack/react-query';
import React from 'react';
import * as ReactDOM from 'react-dom';
import { createRoot } from 'react-dom/client';
import * as jsxRuntime from 'react/jsx-runtime';
import * as jsxDevRuntime from 'react/jsx-dev-runtime';

import * as hostModule from '../shell/host-api';
import { disposePlugin, pluginEffectCount } from './lifecycle';
import {
  getNavItems,
  isNavItemActive,
  registerNavItem,
  unregisterNavItem,
} from './nav';
import { getRouteOptions, matchRoute, registerRoute } from './router';
import {
  clearSlots,
  declareSlot,
  getSlotDeclaration,
  getSlotEntries,
  getSlotEntryMeta,
  hasSlot,
  registerSlot,
  unregisterSlot,
} from './slots';
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
    ready.sort((left, right) => (order.get(left) ?? 0) - (order.get(right) ?? 0));
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

function installInspectionSurface(): void {
  if (!import.meta.env.DEV) return;
  (window as any).__DSH_KERNEL__ = {
    react: React,
    slots: {
      declare: declareSlot,
      register: registerSlot,
      unregister: unregisterSlot,
      has: hasSlot,
      declaration: getSlotDeclaration,
      entries: getSlotEntryMeta,
      raw: getSlotEntries,
      clear: clearSlots,
    },
    nav: {
      get: getNavItems,
      add: registerNavItem,
      remove: unregisterNavItem,
      active: isNavItemActive,
    },
    router: {
      match: matchRoute,
      options: getRouteOptions,
      add: registerRoute,
    },
    lifecycle: {
      dispose: disposePlugin,
      effectCount: pluginEffectCount,
    },
  };
}

/**
 * Read the backend's started-plugin set. `null` means the catalog is
 * unavailable (offline dev, headless or older backend), so every bundle loads.
 */
async function fetchEnabledPlugins(): Promise<Set<string> | null> {
  // Tests and embedded hosts may inject the catalog without an HTTP backend.
  const override = (window as any).__DSH_PLUGIN_CATALOG__;
  if (Array.isArray(override)) {
    return new Set(override.filter((name): name is string => typeof name === 'string'));
  }
  // Offline/dev mode: skip the round trip and load every bundle.
  if (import.meta.env.VITE_PLUGIN_CATALOG === 'off') return null;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 2000);
  try {
    const response = await fetch('/api/plugins', {
      signal: controller.signal,
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) return null;
    const payload = (await response.json()) as { plugins?: Array<{ name?: unknown }> };
    if (!Array.isArray(payload.plugins)) return null;
    return new Set(
      payload.plugins
        .map((plugin) => (typeof plugin?.name === 'string' ? plugin.name : ''))
        .filter(Boolean),
    );
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

export async function boot(): Promise<void> {
  const graph = (window as any).__DSH_BOOT__ as WebBootGraph | undefined;
  if (!graph?.entries?.length) {
    throw new Error('client-modules: window.__DSH_BOOT__ is missing');
  }

  installGlobalFacade();
  installInspectionSurface();
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

  const enabledPlugins = await fetchEnabledPlugins();
  if (import.meta.env.DEV) {
    (window as any).__DSH_KERNEL__.plugins = {
      enabled: enabledPlugins ? [...enabledPlugins] : null,
    };
  }
  const entries = sortEntries(
    graph.entries.filter(
      (entry) =>
        !entry.plugin || enabledPlugins === null || enabledPlugins.has(entry.plugin),
    ),
  );
  await Promise.all(entries.map((entry) => loadEntry(entry)));

  for (const entry of entries) {
    const plugin = materialize(entry.id) as Plugin;
    if (!plugin || typeof plugin.setup !== 'function') {
      throw new Error(`client-modules: ${entry.id} does not export a setup() plugin`);
    }
    try {
      await plugin.setup(hostApi.context(entry.id));
    } catch (error) {
      // One broken plugin must not take down the shell or its siblings.
      hostApi.disposePlugin(entry.id);
      console.error(`client-modules: ${entry.id} setup failed`, error);
    }
  }

  if (getSlotEntries('root').length === 0) {
    throw new Error('client-modules: no plugin registered the root slot');
  }

  hostModule.renderRoot();
}
