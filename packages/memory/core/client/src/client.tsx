import { Brain } from 'lucide-react';

import MemoryDebugPage from '@/app/dashboard/memory/debug/page';
import MemoryPage from '@/app/dashboard/memory/page';
import MemoryUserPage from '@/app/dashboard/memory/users/[user_id]/page';
import MemoryUsersPage from '@/app/dashboard/memory/users/page';
import { definePlugin } from '@app/host';
import type { PluginContext } from '@app/host';

export default definePlugin({
  id: '@app/plugin-memory',
  setup(ctx: PluginContext) {
    ctx.nav.add({
      id: 'memory',
      label: '记忆系统',
      to: '/dashboard/memory',
      icon: <Brain size={18} />,
      order: 60,
    });
    const options = { shell: 'dashboard', layout: 'standard' } as const;
    ctx.router.add('/dashboard/memory', MemoryPage, options);
    ctx.router.add('/dashboard/memory/users', MemoryUsersPage, options);
    ctx.router.add('/dashboard/memory/users/[user_id]', MemoryUserPage, options);
    ctx.router.add('/dashboard/memory/debug', MemoryDebugPage, options);
  },
});
