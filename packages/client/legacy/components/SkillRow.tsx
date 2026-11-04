'use client';

import { BookOpen } from 'lucide-react';
import type { TrajSkillNode } from '@/lib/trajectory';

/** 展示记录中的加载事实；完整指令保留在会话日志中。 */
export default function SkillRow({ node }: { node: TrajSkillNode }) {
  return <div data-testid="skill-loaded" style={{ display: 'flex', alignItems: 'center', gap: 6,
    padding: '3px 6px', fontSize: 13, lineHeight: '20px', color: node.status === 'error' ? '#f87171' : 'inherit', opacity: 0.8 }}>
    <BookOpen size={14} />
    <span>{node.status === 'error' ? '技能无法加载' : '已加载技能'} · {node.name}</span>
    {node.arguments && <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={node.arguments}>{node.arguments}</span>}
  </div>;
}
