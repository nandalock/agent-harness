import DashboardPage from '@/app/dashboard/page';
import { definePlugin } from '@app/host';
import type { PluginContext } from '@app/host';

export default definePlugin({
  id: '@app/plugin-dashboard',
  setup(ctx: PluginContext) {
    ctx.router.add('/dashboard', DashboardPage);
  },
});
