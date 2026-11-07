import { useSyncExternalStore } from 'react';

import type { NavItem } from './types';

const items = new Map<string, NavItem>();
const listeners = new Set<() => void>();
let snapshot: NavItem[] = [];

function rebuild(): void {
  snapshot = [...items.values()]
    .filter((item) => !item.hidden)
    .sort((left, right) => {
      const order = (left.order ?? 0) - (right.order ?? 0);
      return order !== 0 ? order : left.id.localeCompare(right.id);
    });
}

function emit(): void {
  rebuild();
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function readSnapshot(): NavItem[] {
  return snapshot;
}

function validate(item: NavItem): void {
  if (!item.id) throw new Error('nav item id must be a non-empty string');
  if (!item.label) throw new Error(`nav item "${item.id}" needs a label`);
  if (!item.to || !item.to.startsWith('/')) {
    throw new Error(`nav item "${item.id}" needs an absolute route path`);
  }
}

/** Register a primary navigation entry. Returns an idempotent disposer. */
export function registerNavItem(item: NavItem): () => void {
  validate(item);
  if (items.has(item.id)) {
    throw new Error(`nav item "${item.id}" is already registered`);
  }
  items.set(item.id, item);
  emit();
  return () => {
    if (items.get(item.id) !== item) return;
    items.delete(item.id);
    emit();
  };
}

/** Remove a navigation entry by id (diagnostics/tests). */
export function unregisterNavItem(id: string): void {
  if (!items.delete(id)) return;
  emit();
}

export function getNavItems(): readonly NavItem[] {
  return snapshot;
}

export function useNavItems(): readonly NavItem[] {
  return useSyncExternalStore(subscribe, readSnapshot, readSnapshot);
}

/** Whether `item` is the active entry for `path`. */
export function isNavItemActive(item: NavItem, path: string): boolean {
  if (item.match === 'exact') return path === item.to;
  if (item.to === '/dashboard') return path === '/dashboard';
  return path === item.to || path.startsWith(`${item.to}/`);
}
