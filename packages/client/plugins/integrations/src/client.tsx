import IntegrationsPage from '@/app/dashboard/integrations/page';
import { definePlugin } from '@app/host';
import type { PluginContext } from '@app/host';

export default definePlugin({
  id: '@app/plugin-integrations',
  setup(ctx: PluginContext) {
    ctx.router.add('/dashboard/integrations', IntegrationsPage);
  },
});
