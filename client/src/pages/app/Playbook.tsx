import { useEffect, useState } from 'react';
import { BookCheck, Plus, Trash2, Wand2 } from 'lucide-react';
import { api } from '../../lib/api';
import { useApp } from '../../lib/app-context';
import { pretty } from '../../lib/format';
import type { Rule } from '../../lib/types';
import { Empty, Spinner, Switch } from '../../components/ui';

const CLAUSE_TYPES = [
  'liability', 'indemnification', 'termination', 'renewal', 'payment', 'confidentiality', 'ip', 'non_compete',
  'exclusivity', 'governing_law', 'dispute_resolution', 'warranty', 'insurance', 'assignment', 'data_protection',
  'force_majeure', 'audit', 'other',
];
const PRESETS = [
  { id: 'saas_customer', label: 'Buying software (SaaS customer)' },
  { id: 'vendor', label: 'Selling services (vendor)' },
  { id: 'employee', label: 'Signing an employment contract' },
  { id: 'nda', label: 'Reviewing an NDA' },
];

export default function PlaybookPage() {
  const { toast } = useApp();
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [draft, setDraft] = useState({ clause_type: 'liability', title: '', requirement: '', severity: 'medium' as Rule['severity'] });

  useEffect(() => {
    api<Rule[]>('/playbook').then(setRules).catch((e) => toast((e as Error).message, 'error'));
  }, [toast]);

  const call = async (p: Promise<Rule[]>) => {
    try {
      setRules(await p);
    } catch (e) {
      toast((e as Error).message, 'error');
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>My playbook</h1>
          <p>
            Your negotiation standards. Every review checks the contract against these rules and flags deviations and missing clauses. These
            gaps are the ones most AI tools miss.
          </p>
        </div>
      </div>

      <div className="card card-pad stack" style={{ marginBottom: 20 }}>
        <div className="row">
          <Wand2 size={15} style={{ color: 'var(--accent)' }} />
          <b>Start from a preset</b>
        </div>
        <div className="row row-wrap">
          {PRESETS.map((p) => (
            <button
              key={p.id}
              className="chip"
              onClick={() => {
                const replace = window.confirm(`Replace your current rules with “${p.label}”?\n\nOK replaces them. Cancel adds the preset to your existing rules.`);
                call(api<Rule[]>(`/playbook/presets/${p.id}?replace=${replace}`, { method: 'POST' }));
              }}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <div className="stack">
        {rules === null ? (
          <Spinner />
        ) : rules.length === 0 ? (
          <div className="card">
            <Empty icon={<BookCheck size={26} />} title="No rules">
              Add one below or start from a preset.
            </Empty>
          </div>
        ) : (
          rules.map((r) => (
            <div key={r.id} className="card card-pad row" style={{ alignItems: 'flex-start', opacity: r.enabled ? 1 : 0.55 }}>
              <Switch on={!!r.enabled} label={`Enable ${r.title}`} onChange={(v) => call(api(`/playbook/${r.id}`, { method: 'PATCH', body: { enabled: v } }))} />
              <div className="grow stack stack-sm">
                <div className="row row-wrap">
                  <b>{r.title}</b>
                  <span className="badge badge-outline">{pretty(r.clause_type)}</span>
                </div>
                <div className="small muted">{r.requirement}</div>
              </div>
              <select
                className="select"
                style={{ width: 110 }}
                value={r.severity}
                onChange={(e) => call(api(`/playbook/${r.id}`, { method: 'PATCH', body: { severity: e.target.value } }))}
                aria-label="Severity"
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
              <button className="btn btn-ghost btn-icon btn-sm" aria-label="Delete rule" onClick={() => call(api(`/playbook/${r.id}`, { method: 'DELETE' }))}>
                <Trash2 size={14} />
              </button>
            </div>
          ))
        )}

        <form
          className="card card-pad stack"
          onSubmit={(e) => {
            e.preventDefault();
            call(api<Rule[]>('/playbook', { body: draft })).then(() => setDraft((d) => ({ ...d, title: '', requirement: '' })));
          }}
        >
          <b className="row">
            <Plus size={15} /> Add a rule
          </b>
          <div className="row row-wrap">
            <select className="select" style={{ width: 200 }} value={draft.clause_type} onChange={(e) => setDraft({ ...draft, clause_type: e.target.value })}>
              {CLAUSE_TYPES.map((c) => (
                <option key={c} value={c}>
                  {pretty(c)}
                </option>
              ))}
            </select>
            <select className="select" style={{ width: 120 }} value={draft.severity} onChange={(e) => setDraft({ ...draft, severity: e.target.value as Rule['severity'] })}>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
            <input className="input grow" placeholder="Short name, e.g. Mutual indemnity" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
          </div>
          <textarea
            className="textarea"
            placeholder="The standard in plain words, e.g. Indemnities must be mutual and limited to third-party claims."
            value={draft.requirement}
            onChange={(e) => setDraft({ ...draft, requirement: e.target.value })}
          />
          <div>
            <button className="btn btn-primary" disabled={draft.title.trim().length < 2 || draft.requirement.trim().length < 5}>
              Add rule
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
