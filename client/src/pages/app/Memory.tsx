import { useEffect, useState } from 'react';
import { Brain, Check, Pencil, Plus, Trash2 } from 'lucide-react';
import { api } from '../../lib/api';
import { useApp } from '../../lib/app-context';
import { pretty, timeAgo } from '../../lib/format';
import type { Memory } from '../../lib/types';
import { Empty, Spinner, Switch } from '../../components/ui';

const KIND: Record<Memory['kind'], [string, string]> = {
  dismissal: ['Don’t flag', 'From a finding you dismissed'],
  style: ['Redline style', 'From a redline you edited'],
  correction: ['Answer lesson', 'From an answer you edited or rejected'],
  instruction: ['Your instruction', 'Added by you'],
};

export default function MemoryPage() {
  const { toast } = useApp();
  const [items, setItems] = useState<Memory[] | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [text, setText] = useState('');
  const [newRule, setNewRule] = useState('');

  useEffect(() => {
    api<Memory[]>('/memories').then(setItems).catch((e) => toast((e as Error).message, 'error'));
  }, [toast]);

  const call = async (p: Promise<Memory[]>) => {
    try {
      setItems(await p);
      setEditing(null);
    } catch (e) {
      toast((e as Error).message, 'error');
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>What it learned from you</h1>
          <p>
            Every dismissal, edit and rejection becomes a plain-language preference that shapes later drafts. Nothing is hidden in model
            weights. You can read, edit, pause or delete each one.
          </p>
        </div>
      </div>

      <form
        className="card card-pad row"
        style={{ marginBottom: 20 }}
        onSubmit={(e) => {
          e.preventDefault();
          call(api<Memory[]>('/memories', { body: { content: newRule } })).then(() => setNewRule(''));
        }}
      >
        <Plus size={16} className="faint" />
        <input
          className="input grow"
          placeholder="Teach it directly, e.g. Always state notice periods in calendar days."
          value={newRule}
          onChange={(e) => setNewRule(e.target.value)}
        />
        <button className="btn btn-primary" disabled={newRule.trim().length < 3}>
          Add
        </button>
      </form>

      {items === null ? (
        <Spinner />
      ) : items.length === 0 ? (
        <div className="card">
          <Empty icon={<Brain size={28} />} title="Nothing learned yet">
            Dismiss a finding with a reason, edit a redline, or correct an answer, and it will appear here.
          </Empty>
        </div>
      ) : (
        <div className="stack">
          {items.map((m) => (
            <div key={m.id} className="card card-pad row" style={{ alignItems: 'flex-start', opacity: m.active ? 1 : 0.55 }}>
              <Switch on={!!m.active} label="Active" onChange={(v) => call(api(`/memories/${m.id}`, { method: 'PATCH', body: { active: v } }))} />
              <div className="grow stack stack-sm">
                <div className="row row-wrap">
                  <span className="badge badge-human">{KIND[m.kind]?.[0] ?? m.kind}</span>
                  <span className="badge badge-outline">{pretty(m.scope)}</span>
                  <span className="tiny faint">
                    {KIND[m.kind]?.[1]} · {timeAgo(m.created_at)} · applied {m.uses}×
                  </span>
                </div>
                {editing === m.id ? (
                  <div className="row">
                    <input className="input" value={text} onChange={(e) => setText(e.target.value)} autoFocus />
                    <button className="btn btn-sm btn-primary" onClick={() => call(api(`/memories/${m.id}`, { method: 'PATCH', body: { content: text } }))}>
                      <Check size={13} />
                    </button>
                  </div>
                ) : (
                  <div>{m.content}</div>
                )}
              </div>
              <button
                className="btn btn-ghost btn-icon btn-sm"
                aria-label="Edit"
                onClick={() => {
                  setEditing(m.id);
                  setText(m.content);
                }}
              >
                <Pencil size={14} />
              </button>
              <button className="btn btn-ghost btn-icon btn-sm" aria-label="Delete" onClick={() => call(api(`/memories/${m.id}`, { method: 'DELETE' }))}>
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
