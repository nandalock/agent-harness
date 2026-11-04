import WorkspacePage from '@/app/dashboard/workspace/page';
import { definePlugin } from '@app/host';
import type { PluginContext } from '@app/host';

export default definePlugin({
  id: '@app/plugin-workspace',
  setup(ctx: PluginContext) {
    ctx.router.add('/dashboard/workspace', WorkspacePage);
  },
});
