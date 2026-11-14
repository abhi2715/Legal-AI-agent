import { Link } from 'react-router-dom';
import { BookCheck, CircleSlash, HelpCircle, ShieldAlert, ShieldCheck, ShieldQuestion } from 'lucide-react';
import type { DocumentDetail, PlaybookResult } from '../../../lib/types';
import { Empty, RiskBadge } from '../../../components/ui';
import type { Focus } from '../../../components/DocumentViewer';

const STATUS: Record<PlaybookResult['status'], { label: string; cls: string; icon: typeof ShieldCheck }> = {
  compliant: { label: 'Meets your standard', cls: 'badge-ok', icon: ShieldCheck },
  deviation: { label: 'Deviates', cls: 'badge-high', icon: ShieldAlert },
  missing: { label: 'Missing from contract', cls: 'badge-medium', icon: CircleSlash },
  unverified: { label: 'Check manually', cls: 'badge-low', icon: ShieldQuestion },
  not_applicable: { label: 'Not applicable', cls: '', icon: HelpCircle },
};
const ORDER = ['deviation', 'missing', 'unverified', 'compliant', 'not_applicable'];

export default function ComplianceTab({ doc, onFocus }: { doc: DocumentDetail; onFocus: (f: Omit<Focus, 'nonce'>) => void }) {
  if (!doc.playbook.length) {
    return (
      <Empty icon={<BookCheck size={26} />} title="No playbook results yet">
        Run the review to check this contract against <Link to="/app/playbook">your playbook</Link>.
      </Empty>
    );
  }
  const rows = [...doc.playbook].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status));
  const counts = rows.reduce<Record<string, number>>((m, r) => ({ ...m, [r.status]: (m[r.status] ?? 0) + 1 }), {});
  return (
    <div className="stack">
      <div className="row row-wrap">
        {ORDER.filter((s) => counts[s]).map((s) => (
          <span key={s} className={`badge ${STATUS[s as PlaybookResult['status']].cls}`}>
            {counts[s]} {STATUS[s as PlaybookResult['status']].label.toLowerCase()}
          </span>
        ))}
        <span className="grow" />
        <Link to="/app/playbook" className="small">
          Edit playbook
        </Link>
      </div>
      {rows.map((r) => {
        const s = STATUS[r.status];
        const Icon = s.icon;
        return (
          <div key={r.rule_id} className="card card-pad stack stack-sm" style={{ padding: 14 }}>
            <div className="row spread" style={{ alignItems: 'flex-start' }}>
              <div className="row">
                <Icon size={16} style={{ color: `var(--${s.cls.replace('badge-', '') || 'text-3'})` }} />
                <b>{r.title}</b>
              </div>
              <div className="row">
                <RiskBadge risk={r.severity} />
                <span className={`badge ${s.cls}`}>{s.label}</span>
              </div>
            </div>
            <div className="small faint">Your standard: {r.requirement}</div>
            <div className="small">{r.explanation}</div>
            {r.suggested_redline && <div className="redline">{r.suggested_redline}</div>}
            {r.clause_ids.length > 0 && (
              <div className="row row-wrap">
                {r.clause_ids.map((id) => (
                  <button key={id} className="btn btn-ghost btn-sm" onClick={() => onFocus({ clauseId: id })}>
                    View {id}
                  </button>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
