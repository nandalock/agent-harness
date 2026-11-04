'use client';

// ResizeHandle —— 工作区大组件之间的竖向拖拽条。
//
// 只做指针捕获 + rAF 节流，把 dx 交给父组件；宽度的 clamp / 持久化归父组件。
// 和 DSH AppFrame 的 DragHandle 同一套语义：拖动开始时的宽度是基准，dx 不累加。
// 键盘左右键按 8px 步进，让不可用鼠标时也能调整。

import { useCallback, useEffect, useRef, useState } from 'react';

interface Props {
  side: 'left' | 'right';
  label: string;
  onStart: () => void;
  onDrag: (dx: number) => void;
  onEnd: () => void;
}

export default function ResizeHandle({ side, label, onStart, onDrag, onEnd }: Props) {
  const [dragging, setDragging] = useState(false);
  const origin = useRef(0);
  const latest = useRef(0);
  const frame = useRef<number | null>(null);
  const capture = useRef<{ element: HTMLDivElement; id: number } | null>(null);
  const callbacks = useRef({ onStart, onDrag, onEnd });
  callbacks.current = { onStart, onDrag, onEnd };

  const endDrag = useCallback(() => {
    const active = capture.current;
    if (active === null) return;
    capture.current = null;
    if (frame.current !== null) { cancelAnimationFrame(frame.current); frame.current = null; }
    if (active.element.hasPointerCapture(active.id)) active.element.releasePointerCapture(active.id);
    setDragging(false);
    callbacks.current.onEnd();
  }, []);

  useEffect(() => endDrag, [endDrag]);

  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    if (e.button !== 0 || capture.current !== null) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    capture.current = { element: e.currentTarget, id: e.pointerId };
    origin.current = e.clientX;
    latest.current = e.clientX;
    callbacks.current.onStart();
    setDragging(true);
  }

  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (capture.current?.id !== e.pointerId) return;
    latest.current = e.clientX;
    frame.current ??= requestAnimationFrame(() => {
      frame.current = null;
      callbacks.current.onDrag(latest.current - origin.current);
    });
  }

  function onPointerUp(e: React.PointerEvent<HTMLDivElement>) {
    if (capture.current?.id !== e.pointerId) return;
    callbacks.current.onDrag(e.clientX - origin.current);
    endDrag();
  }

  function onPointerCancel(e: React.PointerEvent<HTMLDivElement>) {
    if (capture.current?.id === e.pointerId) endDrag();
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      tabIndex={0}
      className="ws-resize"
      data-side={side}
      data-dragging={dragging || undefined}
      title={`${label}（拖动调整宽度）`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      onLostPointerCapture={onPointerCancel}
      onKeyDown={e => {
        if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
        e.preventDefault();
        callbacks.current.onStart();
        callbacks.current.onDrag(e.key === 'ArrowLeft' ? -8 : 8);
        callbacks.current.onEnd();
      }}
    />
  );
}
