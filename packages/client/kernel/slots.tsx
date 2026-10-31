import React, { useSyncExternalStore } from 'react';
import type { SlotComponent } from './types';

const slots = new Map<string, Map<string, SlotComponent>>();
const listeners = new Set<() => void>();
let version = 0;

function emit(): void {
  version += 1;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function snapshot(): number {
  return version;
}

export function registerSlot(name: string, id: string, component: SlotComponent): () => void {
  let slot = slots.get(name);
  if (!slot) {
    slot = new Map();
    slots.set(name, slot);
  }
  slot.set(id, component);
  emit();
  return () => {
    slot?.delete(id);
    if (slot && slot.size === 0) slots.delete(name);
    emit();
  };
}

export function unregisterSlot(name: string, id: string): void {
  const slot = slots.get(name);
  if (!slot) return;
  slot.delete(id);
  if (slot.size === 0) slots.delete(name);
  emit();
}

export function getSlot(name: string): SlotComponent[] {
  return [...(slots.get(name)?.values() ?? [])];
}

export function Slot({ name, ...props }: { name: string } & Record<string, unknown>): React.ReactElement | null {
  useSyncExternalStore(subscribe, snapshot, snapshot);
  const components = getSlot(name);
  if (components.length === 0) return null;
  return (
    <>
      {components.map((Component, index) => (
        <Component key={`${name}:${index}`} {...props} />
      ))}
    </>
  );
}
