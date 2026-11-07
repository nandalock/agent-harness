import React, { useSyncExternalStore } from 'react';

import { declareSlot } from './slots';
import type { ResolvedRouteOptions, RouteOptions } from './types';

export type RouteComponent = React.ComponentType<{ path: string }>;
export type RouteParams = Record<string, string>;

export interface RouteRecord {
  pattern: string;
  segments: string[];
  component: RouteComponent;
  options: ResolvedRouteOptions;
  score: number;
}

export interface RouteMatch {
  record: RouteRecord;
  params: RouteParams;
}

export const DEFAULT_ROUTE_OPTIONS: ResolvedRouteOptions = {
  shell: 'bare',
  keepAlive: false,
  slots: {},
  layout: {
    mode: 'standard',
    sidebar: 'expanded',
    scroll: 'page',
    padding: true,
    navTheme: 'default',
  },
};

function resolveOptions(options: RouteOptions = {}): ResolvedRouteOptions {
  const layout = typeof options.layout === 'string' ? { mode: options.layout } : (options.layout ?? {});
  const mode = layout.mode ?? 'standard';
  return {
    shell: options.shell ?? 'bare',
    keepAlive: options.keepAlive ?? false,
    slots: options.slots ?? {},
    layout: {
      mode,
      sidebar:
        layout.sidebar ??
        (mode === 'immersive' || mode === 'canvas' ? 'collapsed' : 'expanded'),
      scroll: layout.scroll ?? (mode === 'standard' ? 'page' : 'none'),
      padding: layout.padding ?? mode === 'standard',
      navTheme:
        layout.navTheme ?? (mode === 'immersive' ? 'workspace' : 'default'),
    },
  };
}

const routes = new Map<string, RouteRecord>();
const listeners = new Set<() => void>();

function normalize(path: string): string {
  if (!path) return '/';
  const withoutQuery = path.split('?')[0].split('#')[0];
  if (withoutQuery.length > 1 && withoutQuery.endsWith('/')) {
    return withoutQuery.slice(0, -1);
  }
  return withoutQuery || '/';
}

function split(path: string): string[] {
  return path.split('/').filter(Boolean);
}

function score(segments: string[]): number {
  return segments.reduce((total, segment) => total + (segment.startsWith('[') ? 0 : 10), 0);
}

function matchPattern(record: RouteRecord, path: string): RouteParams | null {
  const parts = split(path);
  const pattern = record.segments;
  const params: RouteParams = {};

  for (let index = 0; index < pattern.length; index += 1) {
    const segment = pattern[index];
    if (segment.startsWith('[...') && segment.endsWith(']')) {
      const name = segment.slice(4, -1);
      params[name] = parts.slice(index).map(decodeURIComponent).join('/');
      return params;
    }
    if (index >= parts.length) return null;
    if (segment.startsWith('[') && segment.endsWith(']')) {
      params[segment.slice(1, -1)] = decodeURIComponent(parts[index]);
      continue;
    }
    if (segment !== decodeURIComponent(parts[index])) return null;
  }
  return pattern.length === parts.length ? params : null;
}

function resolve(path: string): RouteMatch | null {
  const exact = routes.get(path);
  if (exact) return { record: exact, params: {} };

  const candidates = [...routes.values()]
    .filter((record) => record.pattern !== '*' && record.pattern !== path)
    .sort((left, right) => right.score - left.score || right.segments.length - left.segments.length);

  for (const record of candidates) {
    const params = matchPattern(record, path);
    if (params) return { record, params };
  }

  const fallback = routes.get('*');
  return fallback ? { record: fallback, params: {} } : null;
}

let currentPath = normalize(window.location.pathname);
let currentSearch = new URLSearchParams(window.location.search);
let currentParams: RouteParams = resolve(currentPath)?.params ?? {};

function emit(): void {
  for (const listener of listeners) listener();
}

function refreshFromLocation(): void {
  const url = new URL(window.location.href);
  currentPath = normalize(url.pathname);
  currentSearch = new URLSearchParams(url.search);
  currentParams = resolve(currentPath)?.params ?? {};
  emit();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function pathSnapshot(): string {
  return currentPath;
}

function paramsSnapshot(): RouteParams {
  return currentParams;
}

function searchSnapshot(): URLSearchParams {
  return currentSearch;
}

window.addEventListener('popstate', refreshFromLocation);

export function registerRoute(
  pattern: string,
  component: RouteComponent,
  options: RouteOptions = {},
): () => void {
  const normalized = pattern === '*' ? '*' : normalize(pattern);
  if (routes.has(normalized)) {
    throw new Error(`route "${normalized}" is already registered`);
  }
  const segments = split(normalized);
  const resolved = resolveOptions(options);
  const declarations = Object.entries(resolved.slots).map(([name, declaration]) =>
    declareSlot(name, declaration),
  );
  const record: RouteRecord = {
    pattern: normalized,
    segments,
    component,
    options: resolved,
    score: score(segments),
  };
  routes.set(normalized, record);
  currentParams = resolve(currentPath)?.params ?? {};
  emit();
  return () => {
    if (routes.get(normalized) !== record) return;
    routes.delete(normalized);
    for (const dispose of declarations) dispose();
    currentParams = resolve(currentPath)?.params ?? {};
    emit();
  };
}

export function navigate(target: string): void {
  const url = new URL(target, window.location.href);
  const nextPath = normalize(url.pathname);
  if (nextPath === currentPath && url.search === window.location.search) return;
  window.history.pushState({}, '', url.pathname + url.search + url.hash);
  currentPath = nextPath;
  currentSearch = new URLSearchParams(url.search);
  currentParams = resolve(currentPath)?.params ?? {};
  emit();
}

export function redirect(target: string): never {
  navigate(target);
  throw new Error(`redirect:${target}`);
}

export function notFound(): never {
  throw new Error('not-found');
}

/** Resolve a path without reading the hook state. Used by diagnostics and tests. */
export function matchRoute(path: string): RouteMatch | null {
  return resolve(normalize(path));
}

export function getRouteOptions(path: string): ResolvedRouteOptions {
  return resolve(normalize(path))?.record.options ?? DEFAULT_ROUTE_OPTIONS;
}

export function useRoute(): string {
  return useSyncExternalStore(subscribe, pathSnapshot, pathSnapshot);
}

export function usePathname(): string {
  return useRoute();
}

export function useParams<T extends RouteParams = RouteParams>(): T {
  return useSyncExternalStore(subscribe, paramsSnapshot, paramsSnapshot) as T;
}

export function useSearchParams(): URLSearchParams {
  return useSyncExternalStore(subscribe, searchSnapshot, searchSnapshot);
}

/** Layout/shell metadata of the matched route. */
export function useRouteMeta(): ResolvedRouteOptions {
  const path = useRoute();
  return resolve(path)?.record.options ?? DEFAULT_ROUTE_OPTIONS;
}

/** The matched route record and params, or null for an unmatched path. */
export function useRouteMatch(): RouteMatch | null {
  const path = useRoute();
  return resolve(path);
}

const router = {
  push: (target: string) => navigate(target),
  replace: (target: string) => navigate(target),
  back: () => window.history.back(),
  forward: () => window.history.forward(),
  refresh: () => {},
  prefetch: () => {},
};

export function useRouter(): typeof router {
  return router;
}

interface MountedRoute {
  component: RouteComponent;
  path: string;
}

interface RouteErrorBoundaryProps {
  routeKey: string;
  children: React.ReactNode;
}

interface RouteErrorBoundaryState {
  error: Error | null;
}

/**
 * Contains a page crash to its route. Without this, a render-time exception
 * unmounts the whole React tree and the dark body background shows through —
 * i.e. the "black page" users see when one plugin's data shape is unexpected.
 */
class RouteErrorBoundary extends React.Component<RouteErrorBoundaryProps, RouteErrorBoundaryState> {
  state: RouteErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): RouteErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    console.error(`[route:${this.props.routeKey}] render failed`, error, info);
  }

  componentDidUpdate(previous: RouteErrorBoundaryProps): void {
    if (previous.routeKey !== this.props.routeKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render(): React.ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div
        data-route-error={this.props.routeKey}
        style={{
          maxWidth: 720,
          margin: '80px auto',
          padding: '24px 28px',
          border: '1px solid #F53F3F33',
          borderRadius: 10,
          background: '#F53F3F0F',
          color: '#1D2129',
          fontFamily: "system-ui,-apple-system,'Segoe UI',sans-serif",
        }}
      >
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>
          页面加载失败
        </div>
        <div style={{ fontSize: 13, color: '#4E5969', lineHeight: 1.6, wordBreak: 'break-word' }}>
          {error.message || '插件渲染时发生未知错误'}
        </div>
        <button
          type="button"
          onClick={() => this.setState({ error: null })}
          style={{
            marginTop: 16,
            padding: '6px 14px',
            borderRadius: 6,
            border: '1px solid #E5E6EB',
            background: '#FFFFFF',
            color: '#1D2129',
            fontSize: 12,
            cursor: 'pointer',
            fontFamily: 'inherit',
          }}
        >
          重试
        </button>
      </div>
    );
  }
}

/**
 * Renders the matched route and keeps `keepAlive` routes mounted after leave.
 * The hidden page stays in the tree with `display: none`, preserving state.
 */
export function KeepAliveOutlet(): React.ReactElement | null {
  const path = useRoute();
  const match = resolve(path);
  const mounted = React.useRef(new Map<string, MountedRoute>());

  if (match?.record.options.keepAlive && !mounted.current.has(match.record.pattern)) {
    mounted.current.set(match.record.pattern, {
      component: match.record.component,
      path,
    });
  }

  const nodes: React.ReactNode[] = [];
  for (const [pattern, mountedRoute] of mounted.current) {
    const active = match?.record.pattern === pattern;
    nodes.push(
      <div
        key={`keep:${pattern}`}
        data-keepalive={pattern}
        style={{ display: active ? 'contents' : 'none' }}
      >
        <RouteErrorBoundary routeKey={pattern}>
          {React.createElement(mountedRoute.component, { path: mountedRoute.path })}
        </RouteErrorBoundary>
      </div>,
    );
  }

  if (match && !match.record.options.keepAlive) {
    nodes.push(
      <React.Fragment key={`route:${match.record.pattern}`}>
        <RouteErrorBoundary routeKey={match.record.pattern}>
          {React.createElement(match.record.component, { path })}
        </RouteErrorBoundary>
      </React.Fragment>,
    );
  }

  return nodes.length === 0 ? null : <>{nodes}</>;
}

export function RouterOutlet(): React.ReactElement | null {
  const path = useRoute();
  const match = resolve(path);
  if (!match) return null;
  const Component = match.record.component;
  return <Component path={path} />;
}
