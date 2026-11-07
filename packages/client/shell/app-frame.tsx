import React, { useCallback, useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';

import { isNavItemActive, useNavItems } from '../kernel/nav';
import { navigate, useRoute, useRouteMeta } from '../kernel/router';
import { Slot } from '../kernel/slots';
import type { SlotDeclaration } from '../kernel/types';
import { S, T } from './theme';

/** Slots the shell itself declares. Plugins register into these; they never create them. */
export const SHELL_SLOTS: Record<string, SlotDeclaration> = {
  root: { kind: 'single', description: 'Application root' },
  'sidebar.extra': { kind: 'list', description: 'Extra sidebar widgets below primary navigation' },
  'sidebar.footer': { kind: 'list', description: 'Sidebar footer area' },
  'page.header': { kind: 'list', description: 'Content header above the route body' },
  'page.actions': { kind: 'list', description: 'Page-level actions' },
  'page.overlay': { kind: 'list', description: 'Floating overlays over the route body' },
  'right.panel': { kind: 'single', description: 'Optional right-hand inspector panel' },
};

const COLLAPSED_W = 64;
const EXPANDED_W = 220;

interface NavColors {
  background: string;
  text: string;
  activeBackground: string;
  activeText: string;
  brandBackground: string;
  avatarBackground: string;
  avatarText: string;
}

function navColors(theme: 'default' | 'workspace'): NavColors {
  if (theme === 'workspace') {
    return {
      background: '#1B1B1C',
      text: '#ADB2B8',
      activeBackground: '#2C2C2E',
      activeText: '#F9FAFB',
      brandBackground: 'rgba(255,255,255,0.08)',
      avatarBackground: '#2C2C2E',
      avatarText: '#F9FAFB',
    };
  }
  return {
    background: T.sidebar,
    text: '#86909C',
    activeBackground: 'rgba(51,112,255,0.20)',
    activeText: '#fff',
    brandBackground: T.accent,
    avatarBackground: 'rgba(51,112,255,0.20)',
    avatarText: T.accent,
  };
}

function contentStyle(
  mode: 'standard' | 'flush' | 'immersive' | 'chat' | 'canvas' | 'split',
  padding: boolean,
): React.CSSProperties {
  switch (mode) {
    case 'standard':
      return {
        flex: 1,
        minWidth: 0,
        overflow: 'auto',
        padding: padding ? S.xl : 0,
        background: T.bg,
      };
    case 'flush':
    case 'immersive':
    case 'chat':
    case 'canvas':
      return { flex: 1, minWidth: 0, overflow: 'hidden' };
    case 'split':
      return { flex: 1, minWidth: 0, overflow: 'hidden', display: 'flex' };
    default:
      return { flex: 1, minWidth: 0, overflow: 'auto' };
  }
}

function NavLink({
  href,
  children,
  onClick,
  ...rest
}: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }): React.ReactElement {
  return (
    <a
      href={href}
      onClick={(event) => {
        onClick?.(event);
        if (event.defaultPrevented) return;
        if (rest.target && rest.target !== '_self') return;
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        navigate(href);
      }}
      {...rest}
    >
      {children}
    </a>
  );
}

function readCollapsedPreference(): boolean {
  try {
    return localStorage.getItem('sidebar_collapsed') === 'true';
  } catch {
    return false;
  }
}

function Sidebar({
  collapsed,
  path,
  onToggle,
}: {
  collapsed: boolean;
  path: string;
  onToggle: () => void;
}): React.ReactElement {
  const meta = useRouteMeta();
  const items = useNavItems();
  const colors = navColors(meta.layout.navTheme);
  const width = collapsed ? COLLAPSED_W : EXPANDED_W;

  return (
    <div
      data-sidebar={collapsed ? 'collapsed' : 'expanded'}
      style={{
        width,
        background: colors.background,
        display: 'flex',
        flexDirection: 'column',
        flexShrink: 0,
        transition: 'width .18s ease',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          padding: collapsed ? `${S.base}px ${S.sm}px` : `${S.lg}px ${S.xl}px ${S.base}px`,
          display: 'flex',
          alignItems: 'center',
          gap: S.sm,
        }}
      >
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: 8,
            background: colors.brandBackground,
            flexShrink: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 14,
            fontWeight: 700,
            color: '#F9FAFB',
          }}
        >
          AH
        </div>
        {!collapsed ? (
          <span style={{ fontSize: 16, fontWeight: 600, color: '#F9FAFB', whiteSpace: 'nowrap' }}>
            minidsh
          </span>
        ) : null}
      </div>

      <nav style={{ flex: 1, padding: `${S.sm}px ${S.xs}px`, display: 'flex', flexDirection: 'column', gap: 1 }}>
        {items.map((item) => {
          const active = isNavItemActive(item, path);
          return (
            <NavLink
              key={item.id}
              href={item.to}
              data-nav-id={item.id}
              title={collapsed ? item.label : undefined}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: collapsed ? '10px 0' : '10px 12px',
                borderRadius: 6,
                justifyContent: collapsed ? 'center' : 'flex-start',
                color: active ? colors.activeText : colors.text,
                textDecoration: 'none',
                fontSize: 14,
                fontWeight: active ? 500 : 400,
                background: active ? colors.activeBackground : 'transparent',
                whiteSpace: 'nowrap',
              }}
            >
              {item.icon}
              {!collapsed ? item.label : null}
            </NavLink>
          );
        })}
        <Slot name="sidebar.extra" path={path} collapsed={collapsed} />
      </nav>

      <Slot name="sidebar.footer" path={path} collapsed={collapsed} />

      <div style={{ padding: `0 ${S.xs}px ${S.xs}px` }}>
        <button
          onClick={onToggle}
          aria-label={collapsed ? '展开侧栏' : '收起侧栏'}
          style={{
            width: '100%',
            padding: '6px 0',
            borderRadius: 6,
            border: 'none',
            cursor: 'pointer',
            background: 'transparent',
            color: colors.text,
            display: 'flex',
            justifyContent: 'center',
          }}
        >
          {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
        </button>
      </div>

      <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)' }}>
        <div
          style={{
            padding: collapsed ? `${S.md}px 0` : `${S.md}px ${S.base}px`,
            fontSize: 13,
            color: colors.text,
            display: 'flex',
            alignItems: 'center',
            gap: S.sm,
            justifyContent: collapsed ? 'center' : 'flex-start',
          }}
        >
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: '50%',
              background: colors.avatarBackground,
              flexShrink: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 12,
              fontWeight: 600,
              color: colors.avatarText,
            }}
          >
            JK
          </div>
          {!collapsed ? <span>jk</span> : null}
        </div>
      </div>
    </div>
  );
}

/**
 * Shell-owned application frame. Visual tokens and the sidebar live here; the
 * matched route only declares a layout mode and optional child slots.
 */
export function AppFrame({ children }: { children: React.ReactNode }): React.ReactElement {
  const path = useRoute();
  const meta = useRouteMeta();
  const sidebarMode = meta.layout.sidebar;
  const [collapsed, setCollapsed] = useState(
    () => sidebarMode === 'collapsed' || readCollapsedPreference(),
  );

  useEffect(() => {
    if (sidebarMode === 'hidden') return;
    setCollapsed(sidebarMode === 'collapsed' ? true : readCollapsedPreference());
  }, [sidebarMode]);

  const toggle = useCallback(() => {
    setCollapsed((previous) => {
      const next = !previous;
      try {
        localStorage.setItem('sidebar_collapsed', String(next));
      } catch {
        // Storage may be unavailable (private mode); the toggle still works.
      }
      return next;
    });
  }, []);

  return (
    <div style={{ display: 'flex', height: '100vh' }}>
      {sidebarMode !== 'hidden' ? (
        <Sidebar collapsed={collapsed} path={path} onToggle={toggle} />
      ) : null}
      <div
        data-layout={meta.layout.mode}
        data-scroll={meta.layout.scroll}
        style={contentStyle(meta.layout.mode, meta.layout.padding)}
      >
        <Slot name="page.header" path={path} />
        <Slot name="page.actions" path={path} />
        {children}
        <Slot name="page.overlay" path={path} />
        <Slot name="right.panel" path={path} />
      </div>
    </div>
  );
}
