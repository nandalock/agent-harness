import React from 'react';
import { createRoot } from 'react-dom/client';

import { disposePlugin, trackPluginEffect } from '../kernel/lifecycle';
import {
  getNavItems,
  isNavItemActive,
  registerNavItem,
  unregisterNavItem,
  useNavItems,
} from '../kernel/nav';
import {
  DEFAULT_ROUTE_OPTIONS,
  KeepAliveOutlet,
  matchRoute,
  navigate,
  notFound,
  redirect,
  registerRoute,
  RouterOutlet,
  useParams,
  usePathname,
  useRoute,
  useRouteMatch,
  useRouteMeta,
  useRouter,
  useSearchParams,
} from '../kernel/router';
import {
  clearSlots,
  declareSlot,
  getSlotDeclaration,
  getSlotEntries,
  getSlotEntryMeta,
  hasSlot,
  registerSlot,
  Slot,
  unregisterSlot,
} from '../kernel/slots';
import type { PluginContext } from '../kernel/types';
import { AppFrame, SHELL_SLOTS } from './app-frame';
import { S, T } from './theme';
import { EmptyState, Page, Panel, Toolbar } from './ui';

export {
  AppFrame,
  DEFAULT_ROUTE_OPTIONS,
  EmptyState,
  KeepAliveOutlet,
  Page,
  Panel,
  React,
  S,
  SHELL_SLOTS,
  Slot,
  T,
  Toolbar,
  clearSlots,
  declareSlot,
  getNavItems,
  getSlotDeclaration,
  getSlotEntries,
  getSlotEntryMeta,
  hasSlot,
  isNavItemActive,
  matchRoute,
  navigate,
  notFound,
  redirect,
  registerNavItem,
  registerRoute,
  registerSlot,
  RouterOutlet,
  unregisterNavItem,
  unregisterSlot,
  useNavItems,
  useParams,
  usePathname,
  useRoute,
  useRouteMatch,
  useRouteMeta,
  useRouter,
  useSearchParams,
};

export type { PluginContext };

export function createHostApi() {
  const slots = {
    declare: declareSlot,
    register: registerSlot,
  };
  const router = { add: registerRoute, navigate };
  const nav = { add: registerNavItem };

  return {
    slots,
    router,
    nav,
    context(id: string): PluginContext {
      const track = (dispose: () => void) => trackPluginEffect(id, dispose);
      return {
        id,
        slots: {
          declare: (name, declaration) => track(declareSlot(name, declaration)),
          register: (name, idOrOptions, component) =>
            track(registerSlot(name, idOrOptions, component)),
        },
        router: {
          add: (path, component, options) => track(registerRoute(path, component, options)),
          navigate,
        },
        nav: {
          add: (item) => track(registerNavItem(item)),
        },
        onDispose: (callback) => track(callback),
      };
    },
    disposePlugin,
  };
}

export function renderRoot(): void {
  const container = document.getElementById('root');
  if (!container) throw new Error('client-modules: #root not found');
  createRoot(container).render(React.createElement(Slot, { name: 'root' }));
}

export function definePlugin<T extends { id: string; setup(ctx: PluginContext): void | Promise<void> }>(
  plugin: T,
): T {
  return plugin;
}
