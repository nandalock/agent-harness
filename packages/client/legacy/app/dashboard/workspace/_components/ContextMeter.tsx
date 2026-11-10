import { useState } from 'react';
import type { ContextUsage } from '@/lib/memory';
import { W } from '../theme';

const format = (value: number) => value.toLocaleString('zh-CN');

export default function ContextMeter({ usage, sessionId }: { usage?: ContextUsage; sessionId: string }) {
  const [open, setOpen] = useState(false);
  const percent = usage ? Math.round(100 * usage.used_tokens / usage.context_window) : 0;
  const color = usage && usage.used_tokens >= usage.compact_at ? W.warning : W.accent;
  return (
    <div style={{ position: 'relative', flexShrink: 0 }} onKeyDown={event => {
      if (event.key === 'Escape') setOpen(false);
    }}>
      <button type="button" className="ws-btn ws-round" aria-expanded={open}
        aria-label={usage ? `上下文用量 ${percent}%` : '上下文用量'}
        title={usage ? `上下文用量 ${percent}%` : '首次模型请求后显示上下文用量'}
        style={{ display: 'grid', placeItems: 'center', width: 28, height: 28 }}
        onClick={() => setOpen(value => !value)}>
        <svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true">
          <circle cx="10" cy="10" r="7" fill="none" stroke={W.dimmed} strokeWidth="2" opacity=".5" />
          {percent > 0 && <circle cx="10" cy="10" r="7" fill="none" stroke={color} strokeWidth="2"
            pathLength="100" strokeDasharray={`${Math.min(percent, 100)} 100`} strokeLinecap="round"
            transform="rotate(-90 10 10)" />}
        </svg>
      </button>
      {open && (
        <>
          <div onClick={() => setOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 40 }} />
          <div style={{ position: 'absolute', right: 0, bottom: 36, width: 235, zIndex: 50, padding: 12,
            background: W.overlay, color: W.text, borderRadius: 10, boxShadow: W.elevProminent, fontSize: 13 }}>
            <strong>上下文用量</strong>
            {usage ? (
              <>
                <div>约 {format(usage.used_tokens)} / {format(usage.context_window)} tokens（{percent}%）</div>
                <div>自动压缩阈值约 {format(usage.compact_at)} tokens</div>
                <div>已压缩 {usage.compactions} 次</div>
              </>
            ) : <p>首次模型请求后显示用量。</p>}
            <a href={`/dashboard/memory?session=${encodeURIComponent(sessionId)}`} style={{ color: W.accent }}>
              查看会话记忆
            </a>
          </div>
        </>
      )}
    </div>
  );
}
