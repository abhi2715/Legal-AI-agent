import { useState } from 'react';
import { Play, Scale, ShieldCheck, Users } from 'lucide-react';
import type { DocumentDetail } from '../../../lib/types';
import { useApp } from '../../../lib/app-context';

export default function SetupCard({
  doc,
  onStart,
  busy,
}: {
  doc: DocumentDetail;
  onStart: (perspective: string, counterparty: string) => void;
  busy: boolean;
}) {
  const { profile } = useApp();
  const [side, setSide] = useState(doc.perspective || '');
  const [custom, setCustom] = useState('');
  const parties = doc.parties;
  const chosen = side === '__custom' ? custom.trim() : side;
  const counterparty =
    side === '__neutral' ? '' : parties.find((p) => p.alias !== chosen)?.alias ?? '';

  return (
    <div className="setup stack stack-lg" style={{ paddingTop: 8 }}>
      <div>
        <div className="row" style={{ marginBottom: 6 }}>
          <Users size={18} style={{ color: 'var(--accent)' }} />
          <h2 style={{ fontSize: 18 }}>Whose side are you on?</h2>
        </div>
        <p className="muted small">
          Risk depends on perspective. An uncapped indemnity is a threat if you give it and a protection if you receive it.
          LexiScan analyzes every clause from the side you choose and checks it against your playbook.
        </p>
      </div>

      <div className="stack stack-sm">
        {parties.map((p) => (
          <button key={p.alias} className={`option-card ${side === p.alias ? 'on' : ''}`} onClick={() => setSide(p.alias)}>
            <Scale size={16} style={{ marginTop: 2, color: 'var(--accent)' }} />
            <div>
              <div style={{ fontWeight: 600 }}>I represent {p.alias}</div>
              <div className="small muted">{p.name}</div>
            </div>
          </button>
        ))}
        <button className={`option-card ${side === '__custom' ? 'on' : ''}`} onClick={() => setSide('__custom')}>
          <Scale size={16} style={{ marginTop: 2, color: 'var(--text-3)' }} />
          <div className="grow">
            <div style={{ fontWeight: 600 }}>{parties.length ? 'Someone else' : 'Name my side'}</div>
            {side === '__custom' && (
              <input
                autoFocus
                className="input"
                style={{ marginTop: 8 }}
                placeholder="e.g. Customer, Licensee, Employee"
                value={custom}
                onChange={(e) => setCustom(e.target.value)}
                onClick={(e) => e.stopPropagation()}
              />
            )}
          </div>
        </button>
        <button className={`option-card ${side === '__neutral' ? 'on' : ''}`} onClick={() => setSide('__neutral')}>
          <ShieldCheck size={16} style={{ marginTop: 2, color: 'var(--text-3)' }} />
          <div>
            <div style={{ fontWeight: 600 }}>Neutral review</div>
            <div className="small muted">Flag anything one-sided, for either party.</div>
          </div>
        </button>
      </div>

      {profile && (
        <div className="small faint">
          Review policy: <b>{profile.review_policy}</b> · Redaction {profile.privacy_redact ? 'on' : 'off'} · Writing for{' '}
          {profile.expertise === 'plain' ? 'non-lawyers' : 'legal professionals'}. Change these in Settings.
        </div>
      )}

      <button
        className="btn btn-primary btn-lg"
        disabled={busy || !side || (side === '__custom' && !custom.trim())}
        onClick={() => onStart(side === '__neutral' ? '' : chosen, counterparty)}
      >
        <Play size={16} /> Start review
      </button>
    </div>
  );
}
