import React from 'react';
import { createRoot } from 'react-dom/client';

import {
  navigate,
  notFound,
  redirect,
  registerRoute,
  RouterOutlet,
  useParams,
  usePathname,
  useRoute,
  useRouter,
  useSearchParams,
} from '../kernel/router';
import { registerSlot, Slot, unregisterSlot } from '../kernel/slots';
import type { PluginContext } from '../kernel/types';
import { S, T } from './theme';

export {
  React,
  S,
  Slot,
  T,
  navigate,
  notFound,
  redirect,
  registerRoute,
  registerSlot,
  RouterOutlet,
  unregisterSlot,
  useParams,
  usePathname,
  useRoute,
  useRouter,
  useSearchParams,
};

export type { PluginContext };

export function createHostApi() {
  const slots = { register: registerSlot };
  const router = { add: registerRoute, navigate };
  return {
    slots,
    router,
    context(id: string): PluginContext {
      return { id, slots, router };
    },
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
