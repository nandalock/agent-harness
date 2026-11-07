import { GitBranch } from 'lucide-react';

import WorkflowDetailPage from '@/app/dashboard/workflow/[id]/page';
import WorkflowListPage from '@/app/dashboard/workflow/list/page';
import WorkflowPage from '@/app/dashboard/workflow/page';
import { definePlugin } from '@app/host';
import type { PluginContext } from '@app/host';

export default definePlugin({
  id: '@app/plugin-workflow',
  setup(ctx: PluginContext) {
    ctx.nav.add({
      id: 'workflow',
      label: '工作流',
      to: '/dashboard/workflow',
      icon: <GitBranch size={18} />,
      order: 70,
    });
    ctx.router.add('/dashboard/workflow', WorkflowPage, {
      shell: 'dashboard',
      layout: 'standard',
    });
    ctx.router.add('/dashboard/workflow/list', WorkflowListPage, {
      shell: 'dashboard',
      layout: 'standard',
    });
    ctx.router.add('/dashboard/workflow/[id]', WorkflowDetailPage, {
      shell: 'dashboard',
      layout: 'canvas',
      slots: {
        'workflow.inspector': { kind: 'single', description: 'Workflow inspector panel' },
      },
    });
  },
});
