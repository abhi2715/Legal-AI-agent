import { useMemo, useState } from 'react';
import { CalendarDays, CalendarPlus, Repeat } from 'lucide-react';
import { api, download } from '../../../lib/api';
import { useApp } from '../../../lib/app-context';
import { daysUntil, formatDate } from '../../../lib/format';
import type { DocumentDetail, Obligation } from '../../../lib/types';
import { Empty } from '../../../components/ui';
import type { Focus } from '../../../components/DocumentViewer';

export default function ObligationsTab({ doc, onFocus }: { doc: DocumentDetail; onFocus: (f: Omit<Focus, 'nonce'>) => void }) {
  const { toast } = useApp();
  const [items, setItems] = useState<Obligation[]>(doc.obligations);
  const parties = useMemo(() => Array.from(new Set(items.map((o) => o.party))), [items]);
  const [who, setWho] = useState<string>(doc.perspective && parties.includes(doc.perspective) ? doc.perspective : 'all');
  const [showDone, setShowDone] = useState(false);

  const visible = items.filter(
    (o) => (who === 'all' || o.party === who || (o.party === 'Both parties' && who !== 'all')) && (showDone || !o.done),
  );

  const patch = async (o: Obligation, body: Partial<{ done: boolean; due_date: string }>) => {
    try {
      const updated = await api<Obligation>(`/obligations/${o.id}`, { method: 'PATCH', body });
      setItems((all) => all.map((x) => (x.id === o.id ? updated : x)));
    } catch (e) {
      toast((e as Error).message, 'error');
    }
  };

  if (!items.length) {
    return (
      <Empty icon={<CalendarDays size={26} />} title="No obligations yet">
        Obligations and deadlines are extracted when you run the review.
      </Empty>
    );
  }

  const dated = visible.filter((o) => o.due_date).length;

  return (
    <div className="stack">
      <div className="row spread row-wrap">
        <div className="seg">
          <button className={who === 'all' ? 'on' : ''} onClick={() => setWho('all')}>
            Everyone
          </button>
          {parties
            .filter((p) => p !== 'Both parties')
            .map((p) => (
              <button key={p} className={who === p ? 'on' : ''} onClick={() => setWho(p)}>
                {p === doc.perspective ? `${p} (you)` : p}
              </button>
            ))}
        </div>
        <div className="row">
          <label className="row small muted">
            <input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} /> Show done
          </label>
          <button
            className="btn btn-sm"
            disabled={!dated}
            title={dated ? 'Calendar file with 7-day reminders' : 'Add due dates to export'}
            onClick={() =>
              download(`/documents/${doc.id}/obligations.ics${who !== 'all' ? `?party=${encodeURIComponent(who)}` : ''}`, `${doc.name}-deadlines.ics`).catch((e) =>
                toast((e as Error).message, 'error'),
              )
            }
          >
            <CalendarPlus size={13} /> Add to calendar
          </button>
        </div>
      </div>
      <div className="tiny faint">
        Set a date on any obligation to put it in your calendar. Dates the AI computed should be checked against the clause.
      </div>
      {visible.map((o) => {
        const days = o.due_date ? daysUntil(o.due_date) : null;
        return (
          <div key={o.id} className="card card-pad stack stack-sm" style={{ padding: 14, opacity: o.done ? 0.6 : 1 }}>
            <div className="row" style={{ alignItems: 'flex-start' }}>
              <input
                type="checkbox"
                checked={!!o.done}
                onChange={(e) => patch(o, { done: e.target.checked })}
                aria-label="Mark done"
                style={{ marginTop: 4 }}
              />
              <div className="grow stack stack-sm">
                <div className="row row-wrap" style={{ gap: 6 }}>
                  <span className={`badge ${o.party === doc.perspective ? 'badge-accent' : ''}`}>{o.party}</span>
                  {o.recurring && (
                    <span className="badge badge-outline">
                      <Repeat size={10} /> {o.recurring}
                    </span>
                  )}
                  {days !== null && !o.done && (
                    <span className={`badge ${days < 0 ? 'badge-high' : days <= 14 ? 'badge-medium' : ''}`}>
                      {days < 0 ? `${-days}d overdue` : days === 0 ? 'Due today' : `in ${days}d`}
                    </span>
                  )}
                </div>
                <div style={{ textDecoration: o.done ? 'line-through' : undefined }}>{o.action}</div>
                <div className="row row-wrap small muted">
                  {o.due && <span>Timing: {o.due}</span>}
                  <input
                    type="date"
                    className="input"
                    style={{ width: 150, height: 28, padding: '2px 8px' }}
                    value={o.due_date ?? ''}
                    onChange={(e) => patch(o, { due_date: e.target.value })}
                    aria-label="Due date"
                  />
                  {o.due_date && <span>{formatDate(o.due_date)}</span>}
                  {o.clause_id && (
                    <button className="btn btn-ghost btn-sm" onClick={() => onFocus({ clauseId: o.clause_id! })}>
                      View clause {o.clause_id}
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
