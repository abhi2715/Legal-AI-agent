import { useEffect, useState } from 'react';
import { Download, History } from 'lucide-react';
import { api, download } from '../../lib/api';
import { useApp } from '../../lib/app-context';
import type { AuditEntry } from '../../lib/types';
import { Empty, Spinner } from '../../components/ui';

const VERBS: Record<string, string> = {
  'document.uploaded': 'uploaded the contract',
  'document.updated': 'updated document settings',
  'document.deleted': 'deleted the contract',
  'review.started': 'started the review',
  'review.triage_submitted': 'submitted triage',
  'review.completed': 'completed the review',
  'finding.decided': 'decided a finding',
  'finding.bulk_decided': 'decided findings in bulk',
  'memo.approve': 'approved the memo',
  'memo.edit': 'edited and approved the memo',
  'memo.revise': 'sent the memo back for revision',
  'memory.learned': 'learned preferences',
  'memory.updated': 'updated a learned preference',
  'memory.deleted': 'deleted a learned preference',
  'question.asked': 'asked a question',
  'answer.approve': 'approved an answer',
  'answer.edit': 'edited an answer',
  'answer.revise': 'requested a revision',
  'answer.reject': 'rejected an answer',
  'answer.rewound': 'rewound an answer to an earlier step',
  'answer.final.approved': 'finalized an approved answer',
  'answer.final.edited': 'finalized an edited answer',
  'answer.final.rejected': 'finalized a rejection',
  'answer.final.auto_approved': 'auto-approved an answer under your policy',
  'settings.updated': 'changed settings',
  'playbook.rule_added': 'added a playbook rule',
  'playbook.preset_applied': 'applied a playbook preset',
};

// eslint-disable-next-line react-refresh/only-export-components
export function describe(a: AuditEntry): string {
  const d = a.detail as Record<string, unknown>;
  const base = VERBS[a.action] ?? a.action;
  if (a.action === 'finding.decided' && d.status) return `marked “${d.finding}” as ${d.status}${d.reviewer_note ? `: ${d.reviewer_note}` : ''}`;
  if (a.action === 'question.asked') return `asked “${d.question}”`;
  if ((a.action === 'answer.revise' || a.action === 'memo.revise' || a.action === 'answer.reject') && d.feedback) return `${base}: “${d.feedback}”`;
  if (a.action === 'memory.learned') return `learned ${d.count} preference(s)`;
  return base;
}

export default function AuditPage() {
  const { toast } = useApp();
  const [items, setItems] = useState<AuditEntry[] | null>(null);
  const [who, setWho] = useState<'all' | 'human' | 'ai'>('all');

  useEffect(() => {
    api<AuditEntry[]>('/audit?limit=1000').then(setItems).catch((e) => toast((e as Error).message, 'error'));
  }, [toast]);

  const visible = (items ?? []).filter((a) => who === 'all' || (who === 'human' ? a.actor.startsWith('human') : !a.actor.startsWith('human')));

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Audit trail</h1>
          <p>An append-only record of what the assistant did and what you decided, with timestamps. Use it to show how an AI-assisted review was supervised.</p>
        </div>
        <button className="btn" onClick={() => download('/audit?format=csv&limit=5000', 'lexiscan-audit.csv').catch((e) => toast((e as Error).message, 'error'))}>
          <Download size={14} /> Export CSV
        </button>
      </div>
      <div className="seg" style={{ marginBottom: 14 }}>
        {(['all', 'human', 'ai'] as const).map((w) => (
          <button key={w} className={who === w ? 'on' : ''} onClick={() => setWho(w)}>
            {w === 'all' ? 'Everything' : w === 'human' ? 'Human decisions' : 'AI actions'}
          </button>
        ))}
      </div>
      {items === null ? (
        <Spinner />
      ) : visible.length === 0 ? (
        <div className="card">
          <Empty icon={<History size={26} />} title="Nothing recorded yet" />
        </div>
      ) : (
        <div className="card" style={{ overflowX: 'auto' }}>
          <table className="table">
            <thead>
              <tr>
                <th>When</th>
                <th>Who</th>
                <th>What</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((a) => (
                <tr key={a.id}>
                  <td className="small faint" style={{ whiteSpace: 'nowrap' }}>
                    {new Date(a.created_at).toLocaleString()}
                  </td>
                  <td>
                    <span className={`badge ${a.actor.startsWith('human') ? 'badge-human' : 'badge-accent'}`}>
                      {a.actor.startsWith('human:') ? a.actor.slice(6) : 'Assistant'}
                    </span>
                  </td>
                  <td className="small">{describe(a)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
