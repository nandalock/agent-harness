import React from 'react';

import { S, T } from './theme';

/** Page-level vertical stack. Plugins compose pages from these primitives. */
export function Page({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
}): React.ReactElement {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: S.base, ...style }}>
      {children}
    </div>
  );
}

/** Horizontal action row. */
export function Toolbar({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
}): React.ReactElement {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: S.sm, ...style }}>
      {children}
    </div>
  );
}

/** Bordered surface used for cards and side panels. */
export function Panel({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
}): React.ReactElement {
  return (
    <section
      style={{
        background: T.surface,
        border: `1px solid ${T.border}`,
        borderRadius: 10,
        padding: S.base,
        ...style,
      }}
    >
      {children}
    </section>
  );
}

/** Empty state with a fixed visual language. */
export function EmptyState({
  title,
  hint,
}: {
  title: string;
  hint?: string;
}): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: S.xs,
        padding: S.xxxl,
        color: T.secondary,
      }}
    >
      <div style={{ fontSize: 14, fontWeight: 500, color: T.text }}>{title}</div>
      {hint ? <div style={{ fontSize: 13 }}>{hint}</div> : null}
    </div>
  );
}
