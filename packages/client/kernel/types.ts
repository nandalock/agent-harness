import type { ComponentType, ReactNode } from 'react';

export interface ClientDeclaration {
  platform: 'web';
  inject?: string[];
  immediately?: boolean;
  external?: string[];
  /** Canonical backend plugin name; the client loads only when it is enabled. */
  plugin?: string;
}

export interface PluginPackageJson {
  name: string;
  dsh?: { plugin?: string; client?: ClientDeclaration };
}

export interface WebBootEntry {
  id: string;
  url: string;
  rev: string;
  inject?: string[];
  immediately?: boolean;
  external?: string[];
  /** Canonical backend plugin name; absent means always load. */
  plugin?: string;
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

export type SlotKind = 'single' | 'list' | 'keyed' | 'chain';

/** Declared by the shell before any plugin may contribute to a slot. */
export interface SlotDeclaration {
  kind?: SlotKind;
  description?: string;
}

/** One contribution to a declared slot. */
export interface SlotEntryOptions {
  id: string;
  order?: number;
  priority?: number;
  /** Dispatch key for `keyed` slots. */
  key?: string;
  /** Router for `chain` slots: the first non-null result renders. */
  select?: (props: Record<string, unknown>) => unknown;
}

export interface SlotEntryMeta {
  id: string;
  key?: string;
  order: number;
  priority: number;
  sequence: number;
}

export interface SlotRegistry {
  /** Declare a slot and return its disposer. The shell owns declarations. */
  declare(name: string, declaration?: SlotDeclaration): () => void;
  /** Contribute a component. Accepts the legacy `(name, id, component)` form. */
  register(
    name: string,
    idOrOptions: string | SlotEntryOptions,
    component: SlotComponent,
  ): () => void;
}

export type LayoutMode = 'standard' | 'flush' | 'immersive' | 'chat' | 'canvas' | 'split';
export type SidebarMode = 'expanded' | 'collapsed' | 'hidden';
export type NavTheme = 'default' | 'workspace';
export type ShellKind = 'dashboard' | 'agents' | 'bare';

export interface RouteLayout {
  mode?: LayoutMode;
  sidebar?: SidebarMode;
  scroll?: 'page' | 'self' | 'none';
  padding?: boolean;
  navTheme?: NavTheme;
}

export interface ResolvedRouteLayout {
  mode: LayoutMode;
  sidebar: SidebarMode;
  scroll: 'page' | 'self' | 'none';
  padding: boolean;
  navTheme: NavTheme;
}

export interface RouteOptions {
  /** Which top-level shell renders this route. Defaults to `bare`. */
  shell?: ShellKind;
  layout?: LayoutMode | RouteLayout;
  /** Keep the page mounted after the user navigates away (chat, editors). */
  keepAlive?: boolean;
  /** Child slots declared by the route; other plugins may contribute to them. */
  slots?: Record<string, SlotDeclaration>;
}

export interface ResolvedRouteOptions {
  shell: ShellKind;
  layout: ResolvedRouteLayout;
  keepAlive: boolean;
  slots: Record<string, SlotDeclaration>;
}

export interface NavItem {
  id: string;
  label: string;
  to: string;
  icon?: ReactNode;
  order?: number;
  group?: string;
  match?: 'exact' | 'prefix';
  hidden?: boolean;
}

export interface NavRegistry {
  add(item: NavItem): () => void;
}

export interface RouterRegistry {
  add(
    path: string,
    component: ComponentType<{ path: string }>,
    options?: RouteOptions,
  ): () => void;
  navigate(path: string): void;
}

export interface PluginContext {
  id: string;
  slots: SlotRegistry;
  router: RouterRegistry;
  nav: NavRegistry;
  /** Register a cleanup callback. The kernel runs it when the plugin unloads. */
  onDispose(callback: () => void): () => void;
}

export interface Plugin {
  id: string;
  setup(ctx: PluginContext): void | Promise<void>;
}
