import KnowledgePage from '@/app/dashboard/knowledge/page';
import { definePlugin } from '@app/host';
import type { PluginContext } from '@app/host';

export default definePlugin({
  id: '@app/plugin-knowledge',
  setup(ctx: PluginContext) {
    ctx.router.add('/dashboard/knowledge', KnowledgePage);
  },
});
