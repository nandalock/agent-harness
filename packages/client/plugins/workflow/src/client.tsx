import WorkflowDetailPage from '@/app/dashboard/workflow/[id]/page';
import WorkflowListPage from '@/app/dashboard/workflow/list/page';
import WorkflowPage from '@/app/dashboard/workflow/page';
import { definePlugin } from '@app/host';
import type { PluginContext } from '@app/host';

export default definePlugin({
  id: '@app/plugin-workflow',
  setup(ctx: PluginContext) {
    ctx.router.add('/dashboard/workflow', WorkflowPage);
    ctx.router.add('/dashboard/workflow/list', WorkflowListPage);
    ctx.router.add('/dashboard/workflow/[id]', WorkflowDetailPage);
  },
});
