'use client';

import { useEffect, useRef, useState } from 'react';

// Inspired by DeepSeek Harness's shared viewport observer: one observer for
// every code block, released when no targets remain.
let observer: IntersectionObserver | null = null;
const targets = new Map<Element, () => void>();
function observe(element: Element, activate: () => void) {
  if (typeof IntersectionObserver === 'undefined') { activate(); return () => {}; }
  if (!observer) observer = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const callback = targets.get(entry.target);
      targets.delete(entry.target); observer?.unobserve(entry.target); callback?.();
    }
    if (!targets.size) { observer?.disconnect(); observer = null; }
  }, { rootMargin: '200px' });
  targets.set(element, activate); observer.observe(element);
  return () => {
    targets.delete(element); observer?.unobserve(element);
    if (!targets.size) { observer?.disconnect(); observer = null; }
  };
}

const grammars = {
  javascript: () => import('highlight.js/lib/languages/javascript'),
  typescript: () => import('highlight.js/lib/languages/typescript'),
  python: () => import('highlight.js/lib/languages/python'),
  json: () => import('highlight.js/lib/languages/json'),
  bash: () => import('highlight.js/lib/languages/bash'),
  sql: () => import('highlight.js/lib/languages/sql'),
  css: () => import('highlight.js/lib/languages/css'),
  xml: () => import('highlight.js/lib/languages/xml'),
  yaml: () => import('highlight.js/lib/languages/yaml'),
  go: () => import('highlight.js/lib/languages/go'),
  rust: () => import('highlight.js/lib/languages/rust'),
  java: () => import('highlight.js/lib/languages/java'),
  cpp: () => import('highlight.js/lib/languages/cpp'),
  ini: () => import('highlight.js/lib/languages/ini'),
};
const aliases: Record<string, keyof typeof grammars> = {
  js: 'javascript', jsx: 'javascript', ts: 'typescript', tsx: 'typescript', py: 'python',
  sh: 'bash', shell: 'bash', yml: 'yaml', html: 'xml', svg: 'xml', c: 'cpp', rs: 'rust', toml: 'ini',
};
const loaded = new Map<string, Promise<typeof import('highlight.js/lib/core')['default']>>();
function highlighter(language: keyof typeof grammars) {
  let promise = loaded.get(language);
  if (!promise) {
    promise = Promise.all([import('highlight.js/lib/core'), grammars[language]()]).then(([core, grammar]) => {
      core.default.registerLanguage(language, grammar.default);
      return core.default;
    });
    loaded.set(language, promise);
    promise.catch(() => loaded.delete(language));
  }
  return promise;
}

export default function LazyCode({ raw, lang }: { raw: string; lang?: string | null }) {
  const ref = useRef<HTMLElement>(null);
  const [active, setActive] = useState(false);
  const [highlighted, setHighlighted] = useState<{ raw: string; language: string; html: string } | null>(null);
  const input = lang?.toLowerCase() ?? '';
  const language = aliases[input] ?? input;
  const supported = Object.prototype.hasOwnProperty.call(grammars, language);
  useEffect(() => {
    if (!supported || active || !ref.current) return;
    return observe(ref.current, () => setActive(true));
  }, [supported, active]);
  useEffect(() => {
    // Unknown/unlabelled or oversized blocks remain escaped React text; avoid
    // scanning all grammars and blocking the main thread on giant source files.
    if (!active || !supported || raw.length > 100_000) return;
    let cancelled = false;
    highlighter(language as keyof typeof grammars).then(hljs => {
      if (cancelled) return;
      const html = hljs.highlight(raw, { language }).value;
      setHighlighted({ raw, language, html });
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [active, supported, language, raw]);
  return highlighted?.raw === raw && highlighted?.language === language
    ? <code ref={ref} data-highlighted="true" dangerouslySetInnerHTML={{ __html: highlighted.html }} />
    : <code ref={ref}>{raw}</code>;
}
