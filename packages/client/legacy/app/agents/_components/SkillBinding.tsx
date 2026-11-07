'use client';

import { useEffect, useState } from 'react';
import type { SkillEntry } from '@/components/SlashSkills';
import { T, S } from '@/app/theme';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface SkillBindingConfig {
  skills_enabled: boolean;
  enabled_skills: string[] | null;
}

interface CatalogEntry extends SkillEntry {
  source: string;
  model_invocable: boolean;
  user_invocable: boolean;
  package_key?: string;
  package_name?: string;
  binding_key?: string;
  aliases?: string[];
}

interface SkillPackage {
  key: string;
  name: string;
  members: CatalogEntry[];
}

interface Props {
  agentKey: string;
  value: SkillBindingConfig;
  onChange: (value: SkillBindingConfig) => void;
  toolRevision?: number;
  tenantId?: number;
}

function matches(entry: CatalogEntry, name: string) {
  return name === entry.binding_key || name === entry.key || name === entry.name
    || name === entry.key.slice(entry.key.indexOf(':') + 1) || !!entry.aliases?.includes(name);
}

function packagesFor(entries: CatalogEntry[]): SkillPackage[] {
  const packages = new Map<string, SkillPackage>();
  for (const entry of entries) {
    const key = entry.binding_key || entry.key;
    const group = packages.get(key);
    if (group) group.members.push(entry);
    else packages.set(key, { key, name: entry.package_name || entry.name, members: [entry] });
  }
  return [...packages.values()];
}

export default function SkillBinding({ agentKey, value, onChange, toolRevision = 0, tenantId = 1 }: Props) {
  const [entries, setEntries] = useState<CatalogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [available, setAvailable] = useState(true);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    setEntries([]);
    fetch(`${API}/api/agents/${encodeURIComponent(agentKey)}/skills/catalog`, {
      headers: { 'X-Tenant-ID': String(tenantId) }, signal: controller.signal,
    }).then(async response => {
      if (!response.ok) throw new Error(`技能目录加载失败（HTTP ${response.status}）`);
      const data = await response.json();
      if (!Array.isArray(data.skills)) throw new Error('技能目录格式异常');
      if (!controller.signal.aborted) {
        setEntries(data.skills);
        setAvailable(data.available !== false);
      }
    }).catch(reason => {
      if (!controller.signal.aborted) setError(reason.message || '技能目录加载失败');
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [agentKey, tenantId, toolRevision, revision]);

  const all = value.enabled_skills === null;
  const packages = packagesFor(entries);
  const memberSelected = (entry: CatalogEntry) => all || value.enabled_skills!.some(name => matches(entry, name));
  const selected = (group: SkillPackage) => group.members.every(memberSelected);
  const missing = (value.enabled_skills || []).filter(name => !entries.some(entry => matches(entry, name)));
  const selectedCount = packages.filter(selected).length;

  function explicitSelection() {
    const next = new Set(value.enabled_skills ?? packages.map(group => group.key));
    // Canonicalize fully selected packages while retaining old partial bindings
    // and unavailable packages until the user explicitly changes them.
    for (const group of packages.filter(selected)) {
      for (const name of next) if (group.members.some(entry => matches(entry, name))) next.delete(name);
      next.add(group.key);
    }
    return next;
  }

  function toggle(group: SkillPackage, enabled: boolean) {
    const next = explicitSelection();
    for (const name of next) if (group.members.some(entry => matches(entry, name))) next.delete(name);
    if (enabled) next.add(group.key);
    onChange({ ...value, enabled_skills: [...next] });
  }

  const textButton = { background: 'transparent', border: 0, padding: 0, color: T.accent, fontSize: 11, cursor: 'pointer' };
  return (
    <section aria-label="技能绑定" style={{ display: 'flex', flexDirection: 'column', gap: S.sm }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 11, fontWeight: 600, color: T.secondary }}>技能绑定</span>
        {!loading && !error && <span style={{ fontSize: 11, color: T.tertiary }}>已选 {selectedCount}/{packages.length} 包</span>}
      </div>
      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: T.text }}>
        <input type="checkbox" checked={value.skills_enabled}
          onChange={event => onChange({ ...value, skills_enabled: event.target.checked })} style={{ accentColor: T.accent }} />
        启用技能
      </label>
      <div style={{ fontSize: 11, color: T.tertiary, lineHeight: 1.6 }}>保存后整包启用，并自动绑定包声明的工具；取消技能会解除其自动绑定。</div>
      {loading ? <div role="status" style={{ fontSize: 12, color: T.secondary }}>正在加载技能…</div>
        : error ? <div role="alert" style={{ fontSize: 12, color: T.danger }}>
          {error} <button type="button" onClick={() => setRevision(current => current + 1)} style={textButton}>重试</button>
        </div> : !available ? <div role="status" style={{ fontSize: 12, color: T.secondary }}>技能插件未启用，请先启用技能服务与工具插件。</div>
          : <fieldset disabled={!value.skills_enabled} style={{ margin: 0, padding: 0, border: 0, minWidth: 0 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12, color: T.text }}>
              <label><input type="radio" name={`skills-mode-${agentKey}`} checked={all}
                onChange={() => onChange({ ...value, enabled_skills: null })} style={{ accentColor: T.accent }} /> 全部技能包（含新增）</label>
              <label><input type="radio" name={`skills-mode-${agentKey}`} checked={!all}
                onChange={() => onChange({ ...value, enabled_skills: [...explicitSelection()] })} style={{ accentColor: T.accent }} /> 指定技能包</label>
            </div>
            <div style={{ display: 'flex', gap: 12, marginTop: S.sm, marginBottom: S.sm }}>
              <button type="button" disabled={!value.skills_enabled} style={textButton}
                onClick={() => onChange({ ...value, enabled_skills: [...packages.map(group => group.key), ...missing] })}>全选当前技能包</button>
              <button type="button" disabled={!value.skills_enabled} style={textButton}
                onClick={() => onChange({ ...value, enabled_skills: [] })}>清空选择</button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 320, overflowY: 'auto' }}>
              {packages.map(group => {
                const checked = selected(group);
                const partial = !checked && group.members.some(memberSelected);
                const bundled = group.members.length > 1;
                const first = group.members[0];
                return <div key={group.key} role="group" aria-label={`${group.name} 技能包`}
                  style={{ padding: 8, border: `1px solid ${T.border}`, borderRadius: 6,
                    background: T.surface, minWidth: 0, fontSize: 12, lineHeight: 1.6, overflowWrap: 'anywhere' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                    <input type="checkbox" checked={checked} aria-checked={partial ? 'mixed' : checked}
                      ref={element => { if (element) element.indeterminate = partial; }}
                      onChange={event => toggle(group, event.target.checked)} style={{ accentColor: T.accent }} />
                    <span style={{ fontWeight: 600, color: T.text }}>{group.name}</span>
                  </label>
                  <div style={{ paddingLeft: 22 }}>
                    <div style={{ color: T.tertiary, fontSize: 11 }}>来源：{[...new Set(group.members.map(entry => entry.source))].join('、')}</div>
                    {partial && <div style={{ color: T.warning, fontSize: 11 }}>原配置仅启用了部分内容，勾选后整包生效。</div>}
                    {bundled ? <>
                      {group.members.some(entry => entry.unavailable_reason) && <div style={{ color: T.warning, fontSize: 11 }}>部分工具尚未加载，展开查看。</div>}
                      <details>
                        <summary style={{ cursor: 'pointer', color: T.secondary }}>包含 {group.members.length} 项能力</summary>
                        <ul style={{ margin: '6px 0 0', paddingLeft: 16 }}>
                          {group.members.map(entry => <li key={entry.key} style={{ marginBottom: 8 }}>
                            <span style={{ color: T.text }}>{entry.name}</span>
                            <div title={entry.description} style={{ color: T.secondary, display: '-webkit-box',
                              WebkitBoxOrient: 'vertical', WebkitLineClamp: 2, overflow: 'hidden' }}>{entry.description}</div>
                            {entry.unavailable_reason && <div style={{ color: T.warning, fontSize: 11 }}>{entry.unavailable_reason}</div>}
                          </li>)}
                        </ul>
                      </details>
                    </> : <>
                      <div title={first.description} style={{ color: T.secondary, display: '-webkit-box',
                        WebkitBoxOrient: 'vertical', WebkitLineClamp: 2, overflow: 'hidden' }}>{first.description}</div>
                      {first.unavailable_reason && <div style={{ color: T.warning, fontSize: 11 }}>{first.unavailable_reason}</div>}
                    </>}
                  </div>
                </div>;
              })}
              {missing.map(name => <label key={name} style={{ fontSize: 12, color: T.tertiary }}>
                <input type="checkbox" checked onChange={() => onChange({ ...value,
                  enabled_skills: value.enabled_skills!.filter(item => item !== name) })} style={{ accentColor: T.accent }} />
                {name.startsWith('@package/') ? `未发现技能包：${name.slice(9)}` : `未发现：${name}`}（来源暂不可用，已保留选择）
              </label>)}
              {!entries.length && <div style={{ fontSize: 12, color: T.tertiary }}>暂无技能，请配置技能目录或安装技能。</div>}
              {!all && !value.enabled_skills!.length && <div style={{ fontSize: 11, color: T.tertiary }}>未选择技能包，保存后此智能体不使用任何技能。</div>}
            </div>
          </fieldset>}
    </section>
  );
}
