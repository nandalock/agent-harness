import React, { useSyncExternalStore } from 'react';

import type {
  SlotComponent,
  SlotDeclaration,
  SlotEntryMeta,
  SlotEntryOptions,
  SlotKind,
} from './types';

interface SlotEntry {
  id: string;
  key?: string;
  order: number;
  priority: number;
  sequence: number;
  component: SlotComponent;
  select?: (props: Record<string, unknown>) => unknown;
}

interface SlotRecord {
  declaration: Required<SlotDeclaration>;
  entries: SlotEntry[];
}

const records = new Map<string, SlotRecord>();
const listeners = new Set<() => void>();
let version = 0;
let sequence = 0;

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

function normalizeDeclaration(declaration: SlotDeclaration = {}): Required<SlotDeclaration> {
  return {
    kind: declaration.kind ?? 'list',
    description: declaration.description ?? '',
  };
}

function describeDeclaredSlots(): string {
  return [...records.keys()].sort().join(', ') || 'none';
}

function sortEntries(kind: SlotKind, entries: SlotEntry[]): SlotEntry[] {
  return [...entries].sort((left, right) => {
    if (left.priority !== right.priority) return left.priority - right.priority;
    if (left.order !== right.order) return left.order - right.order;
    return left.sequence - right.sequence;
  });
}

function normalizeEntry(
  idOrOptions: string | SlotEntryOptions,
  component: SlotComponent,
): SlotEntry {
  const options: SlotEntryOptions =
    typeof idOrOptions === 'string' ? { id: idOrOptions } : idOrOptions;
  if (!options.id || typeof options.id !== 'string') {
    throw new Error('slot entry id must be a non-empty string');
  }
  sequence += 1;
  return {
    id: options.id,
    ...(options.key === undefined ? {} : { key: options.key }),
    order: options.order ?? 0,
    priority: options.priority ?? 0,
    sequence,
    component,
    ...(options.select === undefined ? {} : { select: options.select }),
  };
}

function assertCellFree(kind: SlotKind, record: SlotRecord, entry: SlotEntry, name: string): void {
  if (kind === 'chain') return;
  const occupant = record.entries.find((candidate) => {
    if (candidate.priority !== entry.priority) return false;
    if (kind === 'single') return true;
    if (kind === 'keyed') return candidate.key === entry.key;
    return candidate.id === entry.id;
  });
  if (!occupant) return;
  const cell =
    kind === 'single'
      ? 'the slot'
      : kind === 'keyed'
        ? `key "${entry.key ?? ''}"`
        : `id "${entry.id}"`;
  throw new Error(
    `slot "${name}" already has an entry at ${cell} with priority ${entry.priority}` +
      ` (registered by "${occupant.id}"); use a different priority to shadow it`,
  );
}

/** Declare a slot. Only declared slots accept registrations. */
export function declareSlot(name: string, declaration: SlotDeclaration = {}): () => void {
  if (records.has(name)) {
    throw new Error(`slot "${name}" is already declared`);
  }
  records.set(name, { declaration: normalizeDeclaration(declaration), entries: [] });
  emit();
  return () => {
    if (!records.delete(name)) return;
    emit();
  };
}

export function hasSlot(name: string): boolean {
  return records.has(name);
}

export function getSlotDeclaration(name: string): Readonly<Required<SlotDeclaration>> | undefined {
  return records.get(name)?.declaration;
}

/** Contribute to a declared slot. Returns an idempotent disposer. */
export function registerSlot(
  name: string,
  idOrOptions: string | SlotEntryOptions,
  component: SlotComponent,
): () => void {
  const record = records.get(name);
  if (!record) {
    throw new Error(
      `slot "${name}" is not declared; declare it before registering` +
        ` (declared slots: ${describeDeclaredSlots()})`,
    );
  }
  const kind = record.declaration.kind;
  const entry = normalizeEntry(idOrOptions, component);
  if (kind === 'keyed' && entry.key === undefined) {
    throw new Error(`keyed slot "${name}" requires an entry key`);
  }
  if (kind === 'chain' && entry.select === undefined) {
    throw new Error(`chain slot "${name}" requires an entry selector`);
  }
  assertCellFree(kind, record, entry, name);
  record.entries = sortEntries(kind, [...record.entries, entry]);
  emit();
  return () => {
    const current = records.get(name);
    if (!current) return;
    const next = current.entries.filter((candidate) => candidate.sequence !== entry.sequence);
    if (next.length === current.entries.length) return;
    current.entries = next;
    emit();
  };
}

export function unregisterSlot(name: string, id: string): void {
  const record = records.get(name);
  if (!record) return;
  const next = record.entries.filter((entry) => entry.id !== id);
  if (next.length === record.entries.length) return;
  record.entries = next;
  emit();
}

/** Raw entries (components included) for renderers and diagnostics. */
export function getSlotEntries(name: string): readonly SlotEntry[] {
  return records.get(name)?.entries ?? [];
}

/** JSON-safe entry metadata for the dev inspection surface and tests. */
export function getSlotEntryMeta(name: string): SlotEntryMeta[] {
  return getSlotEntries(name).map((entry) => ({
    id: entry.id,
    ...(entry.key === undefined ? {} : { key: entry.key }),
    order: entry.order,
    priority: entry.priority,
    sequence: entry.sequence,
  }));
}

/** Remove every declaration and contribution. Intended for tests/HMR reset. */
export function clearSlots(): void {
  if (records.size === 0) return;
  records.clear();
  emit();
}

function entryKeyPrefix(entry: SlotEntry): string {
  return `${entry.id}:${entry.priority}:${entry.sequence}`;
}

/**
 * Render one declared slot.
 *
 * - `single`: the lowest-priority live entry.
 * - `list`: every live entry ordered by priority, order, registration.
 * - `keyed`: the lowest-priority entry whose `key` matches `entryKey`.
 * - `chain`: the first entry whose `select` returns non-null, else `fallback`.
 */
export function Slot({
  name,
  ...props
}: { name: string } & Record<string, unknown>): React.ReactElement | null {
  useSyncExternalStore(subscribe, snapshot, snapshot);
  const record = records.get(name);
  if (!record || record.entries.length === 0) return null;

  switch (record.declaration.kind) {
    case 'single': {
      const entry = record.entries[0];
      return React.createElement(entry.component, { key: entryKeyPrefix(entry), ...props });
    }
    case 'list':
      return (
        <>
          {record.entries.map((entry) =>
            React.createElement(entry.component, { key: entryKeyPrefix(entry), ...props }),
          )}
        </>
      );
    case 'keyed': {
      const { entryKey, ...owner } = props;
      const entry = record.entries.find((candidate) => candidate.key === entryKey);
      if (!entry) return null;
      return React.createElement(entry.component, { key: entryKeyPrefix(entry), ...owner });
    }
    case 'chain': {
      const { fallback, entryKey: _entryKey, ...owner } = props;
      for (const entry of record.entries) {
        const matched = entry.select?.(owner);
        if (matched === null || matched === undefined) continue;
        return React.createElement(entry.component, {
          key: entryKeyPrefix(entry),
          ...owner,
          matched,
        });
      }
      if (fallback === null || fallback === undefined || fallback === false) return null;
      return <>{fallback}</>;
    }
    default:
      return null;
  }
}
