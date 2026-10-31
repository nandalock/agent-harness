'use client';

import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react';
import { fetchHistoryPage, type ChatMessage, type HistoryPage } from '@/lib/chatHistory';

export function useOlderMessages(conversationId: number | null, setMessages: Dispatch<SetStateAction<ChatMessage[]>>) {
  const [page, setPage] = useState({ hasMore: false, cursor: null as number | null });
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [error, setError] = useState('');
  const request = useRef<AbortController | null>(null);
  const generation = useRef(0);
  useEffect(() => {
    generation.current++;
    request.current?.abort(); request.current = null;
    setPage({ hasMore: false, cursor: null }); setLoadingOlder(false); setError('');
    return () => { generation.current++; request.current?.abort(); };
  }, [conversationId]);
  function acceptPage(result: HistoryPage) {
    setPage({ hasMore: result.hasMore, cursor: result.cursor }); setError('');
  }
  async function loadOlder() {
    if (!conversationId || request.current) return;
    const controller = new AbortController();
    request.current = controller;
    const current = generation.current;
    setLoadingOlder(true); setError('');
    try {
      const result = await fetchHistoryPage(conversationId, controller.signal, page.cursor);
      if (current !== generation.current) return;
      setMessages(previous => {
        const existing = new Set(previous.filter(m => m.id != null).map(m => m.id));
        return [...result.messages.filter(m => !existing.has(m.id)), ...previous];
      });
      acceptPage(result);
    } catch {
      if (!controller.signal.aborted && current === generation.current) setError('历史加载失败');
    } finally {
      if (current === generation.current) { request.current = null; setLoadingOlder(false); }
    }
  }
  return { ...page, loadingOlder, error, loadOlder, acceptPage, setError };
}
