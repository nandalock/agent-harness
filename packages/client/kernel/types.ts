import type { ComponentType } from 'react';

export interface ClientDeclaration {
  platform: 'web';
  inject?: string[];
  immediately?: boolean;
  external?: string[];
}

export interface PluginPackageJson {
  name: string;
  dsh?: { client?: ClientDeclaration };
}

export interface WebBootEntry {
  id: string;
  url: string;
  rev: string;
  inject?: string[];
  immediately?: boolean;
  external?: string[];
}

export interface WebBootBatch {
  phase: 'bootstrap' | 'application';
  url: string;
  rev: string;
  entries: string[];
}

export interface WebBootGraph {
  rev: string;
  entries: WebBootEntry[];
  batches: WebBootBatch[];
}

export type SlotComponent = ComponentType<any>;

export interface SlotRegistry {
  register(slot: string, id: string, component: SlotComponent): () => void;
}

export interface RouterRegistry {
  add(path: string, component: ComponentType<{ path: string }>): () => void;
  navigate(path: string): void;
}

export interface PluginContext {
  id: string;
  slots: SlotRegistry;
  router: RouterRegistry;
}

export interface Plugin {
  id: string;
  setup(ctx: PluginContext): void | Promise<void>;
}
