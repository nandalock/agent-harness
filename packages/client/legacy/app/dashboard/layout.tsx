'use client';

import type { ReactNode } from 'react';

import { AppFrame } from '@app/host';

/**
 * Legacy import path kept for the shell plugin. Layout, navigation and design
 * tokens are owned by `AppFrame`; pages no longer live here.
 */
export default function DashboardLayout({ children }: { children: ReactNode }) {
  return <AppFrame>{children}</AppFrame>;
}
