import MemoryDebugPage from '@/app/dashboard/memory/debug/page';
import MemoryPage from '@/app/dashboard/memory/page';
import MemoryUserPage from '@/app/dashboard/memory/users/[user_id]/page';
import MemoryUsersPage from '@/app/dashboard/memory/users/page';
import { definePlugin } from '@app/host';
import type { PluginContext } from '@app/host';

export default definePlugin({
  id: '@app/plugin-memory',
  setup(ctx: PluginContext) {
    ctx.router.add('/dashboard/memory', MemoryPage);
    ctx.router.add('/dashboard/memory/users', MemoryUsersPage);
    ctx.router.add('/dashboard/memory/users/[user_id]', MemoryUserPage);
    ctx.router.add('/dashboard/memory/debug', MemoryDebugPage);
  },
});
