'use client';

import { useEffect, useState } from 'react';

type RecoveryState = { can_resume: boolean; source_turn_start_seq: number | null };

export default function RecoveryBanner({ api, tenantId, sessionId, busy, onContinue }: {
  api: string; tenantId: number; sessionId: string | null; busy: boolean;
  onContinue: (sourceTurn: number) => void;
}) {
  const [recovery, setRecovery] = useState<RecoveryState | null>(null);
  useEffect(() => {
    setRecovery(null);
    if (!sessionId || busy) return;
    const controller = new AbortController();
    async function refresh() {
      try {
        const response = await fetch(`${api}/api/agents/sessions/${sessionId}/recovery`, {
          headers: { 'X-Tenant-ID': String(tenantId) }, signal: controller.signal,
        });
        if (response.ok && !controller.signal.aborted) setRecovery(await response.json());
      } catch { /* Recheck on the next interval after a temporary connection failure. */ }
    }
    void refresh();
    const interval = setInterval(refresh, 5000);
    return () => { controller.abort(); clearInterval(interval); };
  }, [api, tenantId, sessionId, busy]);

  if (!recovery?.can_resume || recovery.source_turn_start_seq == null) return null;
  const sourceTurn = recovery.source_turn_start_seq;
  return (
    <div role="status" style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px', border: '1px solid #d8b667', borderRadius: 8, background: '#fff9eb', color: '#725519', margin: '12px 16px', fontSize: 13 }}>
      <span style={{ flex: 1 }}>上次任务中断了，已保存的进度可以继续。</span>
      <button type="button" disabled={busy} onClick={() => onContinue(sourceTurn)} style={{ cursor: 'pointer', border: '1px solid #d8b667', borderRadius: 6, background: '#fff', padding: '6px 12px', color: 'inherit' }}>继续任务</button>
    </div>
  );
}
