import { useEffect, useState } from 'react';
import { Bot, EyeOff, Gavel, HelpCircle, Sparkles, User } from 'lucide-react';
import { useApp } from '../../lib/app-context';
import ThemeToggle from '../../components/ThemeToggle';
import { Spinner, Switch } from '../../components/ui';
import type { Profile } from '../../lib/types';

const POLICIES: { id: Profile['review_policy']; title: string; body: string }[] = [
  { id: 'always', title: 'Review everything', body: 'Every answer waits for your approval. Best when the stakes are high or you are still building trust.' },
  { id: 'smart', title: 'Review when it matters', body: 'Auto-approve only when confidence clears your threshold, every quote verifies and the question is not about interpretation.' },
  { id: 'never', title: 'Trust, with a floor', body: 'Auto-approve answers, except unverifiable quotes or questions that turn on outside law. Those always come to you.' },
];

export default function SettingsPage() {
  const { profile, updateProfile, engine } = useApp();
  const [name, setName] = useState('');
  const [role, setRole] = useState('');
  const [jurisdiction, setJurisdiction] = useState('');
  const [threshold, setThreshold] = useState(0.8);

  useEffect(() => {
    if (profile) {
      setName(profile.name);
      setRole(profile.role);
      setJurisdiction(profile.jurisdiction);
      setThreshold(profile.confidence_threshold);
    }
  }, [profile]);

  if (!profile) return <div className="page"><Spinner /></div>;

  return (
    <div className="page" style={{ maxWidth: 820 }}>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p>Decide how much the assistant may do on its own, and how it should write for you.</p>
        </div>
      </div>

      <div className="stack stack-lg">
        <section className="card card-pad stack">
          <b className="row"><User size={15} /> You</b>
          <div className="row row-wrap" style={{ alignItems: 'flex-start' }}>
            <div className="grow" style={{ minWidth: 200 }}>
              <label className="label">Name on decisions</label>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} onBlur={() => name.trim() && name !== profile.name && updateProfile({ name: name.trim() })} />
              <div className="hint">Recorded in the audit trail for every approval.</div>
            </div>
            <div className="grow" style={{ minWidth: 200 }}>
              <label className="label">Role</label>
              <input className="input" value={role} onChange={(e) => setRole(e.target.value)} onBlur={() => role !== profile.role && updateProfile({ role })} />
            </div>
          </div>
          <div className="row row-wrap" style={{ alignItems: 'flex-start' }}>
            <div className="grow" style={{ minWidth: 200 }}>
              <label className="label">Write answers for</label>
              <div className="seg">
                {(['plain', 'professional', 'expert'] as const).map((x) => (
                  <button key={x} className={profile.expertise === x ? 'on' : ''} onClick={() => updateProfile({ expertise: x })}>
                    {x === 'plain' ? 'Non-lawyer' : x === 'professional' ? 'Professional' : 'Expert counsel'}
                  </button>
                ))}
              </div>
            </div>
            <div className="grow" style={{ minWidth: 200 }}>
              <label className="label">Jurisdiction of interest</label>
              <input className="input" placeholder="e.g. California, England & Wales" value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)} onBlur={() => jurisdiction !== profile.jurisdiction && updateProfile({ jurisdiction })} />
            </div>
          </div>
        </section>

        <section className="card card-pad stack">
          <b className="row"><Gavel size={15} style={{ color: 'var(--human)' }} /> Review policy for answers</b>
          <div className="small muted">Contract reviews always need your triage and memo approval. This policy controls Q&A answers.</div>
          <div className="stack stack-sm">
            {POLICIES.map((p) => (
              <button key={p.id} className={`option-card ${profile.review_policy === p.id ? 'on' : ''}`} onClick={() => updateProfile({ review_policy: p.id })}>
                <input type="radio" readOnly checked={profile.review_policy === p.id} style={{ marginTop: 3 }} />
                <div>
                  <div style={{ fontWeight: 600 }}>{p.title}</div>
                  <div className="small muted">{p.body}</div>
                </div>
              </button>
            ))}
          </div>
          {profile.review_policy !== 'always' && (
            <div>
              <label className="label">
                Confidence threshold: {Math.round(threshold * 100)}%
              </label>
              <input
                type="range"
                min={0.5}
                max={0.95}
                step={0.05}
                value={threshold}
                onChange={(e) => setThreshold(Number(e.target.value))}
                onMouseUp={() => updateProfile({ confidence_threshold: threshold })}
                onKeyUp={() => updateProfile({ confidence_threshold: threshold })}
                onTouchEnd={() => updateProfile({ confidence_threshold: threshold })}
                style={{ width: '100%', accentColor: 'var(--accent)' }}
              />
              <div className="hint">Answers below this confidence always come to you.</div>
            </div>
          )}
        </section>

        <section className="card card-pad stack">
          <b className="row"><Sparkles size={15} /> Assistant behaviour</b>
          <label className="row spread">
            <span>
              <span className="row" style={{ fontWeight: 500 }}><EyeOff size={14} /> Redact personal data before analysis</span>
              <span className="small muted">Emails, phone numbers, addresses, account and ID numbers are swapped for placeholders before any text leaves the server, then restored for you.</span>
            </span>
            <Switch on={!!profile.privacy_redact} label="Redact personal data" onChange={(v) => updateProfile({ privacy_redact: Number(v) })} />
          </label>
          <div className="divider" />
          <label className="row spread">
            <span>
              <span className="row" style={{ fontWeight: 500 }}><HelpCircle size={14} /> Ask me when a question is ambiguous</span>
              <span className="small muted">The assistant pauses and asks instead of guessing.</span>
            </span>
            <Switch on={!!profile.ask_clarifications} label="Ask clarifying questions" onChange={(v) => updateProfile({ ask_clarifications: Number(v) })} />
          </label>
        </section>

        <section className="card card-pad stack">
          <b>Appearance</b>
          <ThemeToggle withLabels />
        </section>

        {engine && (
          <section className="card card-pad stack small">
            <b className="row"><Bot size={15} /> Engine</b>
            <div>
              {engine.online ? (
                <>Connected to <code>{engine.model}</code>. Contract text is sent with prompt caching, so follow-up questions on the same contract reuse the cached document.</>
              ) : (
                <>Offline heuristics. {engine.reason}</>
              )}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
