import React, { useSyncExternalStore } from 'react';

export type RouteComponent = React.ComponentType<{ path: string }>;
export type RouteParams = Record<string, string>;

interface RouteRecord {
  pattern: string;
  segments: string[];
  component: RouteComponent;
  score: number;
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

function resolve(path: string): { record: RouteRecord; params: RouteParams } | null {
  const exact = routes.get(path);
  if (exact) return { record: exact, params: {} };

  const candidates = [...routes.values()]
    .filter((record) => record.pattern !== '*' && record.pattern !== path)
    .sort((a, b) => b.score - a.score || b.segments.length - a.segments.length);

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

export function registerRoute(pattern: string, component: RouteComponent): () => void {
  const normalized = pattern === '*' ? '*' : normalize(pattern);
  const segments = split(normalized);
  routes.set(normalized, {
    pattern: normalized,
    segments,
    component,
    score: score(segments),
  });
  currentParams = resolve(currentPath)?.params ?? {};
  emit();
  return () => {
    routes.delete(normalized);
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

export function RouterOutlet(): React.ReactElement | null {
  const path = useRoute();
  const match = resolve(path);
  if (!match) return null;
  const Component = match.record.component;
  return <Component path={path} />;
}
