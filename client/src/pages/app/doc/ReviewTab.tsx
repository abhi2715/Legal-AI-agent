import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertOctagon,
  ArrowUpRight,
  Check,
  CheckCheck,
  Copy,
  Download,
  EyeOff,
  FileSignature,
  Gavel,
  Keyboard,
  Pencil,
  RotateCcw,
  Send,
  ShieldCheck,
  X,
} from 'lucide-react';
import { api, saveBlob } from '../../../lib/api';
import { useApp } from '../../../lib/app-context';
import { Markdown } from '../../../lib/markdown';
import { pretty } from '../../../lib/format';
import type { DocumentDetail, Finding, FindingStatus, TraceEntry } from '../../../lib/types';
import Pipeline, { type StepDef } from '../../../components/Pipeline';
import { Gauge, RiskBadge } from '../../../components/ui';
import type { Focus } from '../../../components/DocumentViewer';

const STEPS: StepDef[] = [
  { node: 'prepare', label: 'Prepare & redact' },
  { node: 'analyze_clauses', label: 'Analyze clauses' },
  { node: 'extract_obligations', label: 'Extract obligations' },
  { node: 'check_playbook', label: 'Check your playbook' },
  { node: 'score', label: 'Score risk' },
  { node: 'human_triage', label: 'Your triage', human: true },
  { node: 'learn', label: 'Learn from your decisions' },
  { node: 'draft_memo', label: 'Draft memo' },
  { node: 'memo_review', label: 'Your approval', human: true },
  { node: 'finalize', label: 'Finalize' },
];

const SOURCE_LABEL: Record<Finding['source'], string> = { ai: 'AI review', playbook: 'Playbook', missing: 'Missing clause' };
const RISK_ORDER = { high: 0, medium: 1, low: 2, none: 3 };

type Filter = 'open' | 'all' | 'decided';

export default function ReviewTab({
  doc,
  reload,
  onFocus,
  liveTrace,
  running,
  runReview,
  onFindingUpdated,
}: {
  doc: DocumentDetail;
  reload: () => Promise<void>;
  onFocus: (f: Omit<Focus, 'nonce'>) => void;
  liveTrace: TraceEntry[];
  running: boolean;
  runReview: (path: string, body: unknown) => Promise<void>;
  onFindingUpdated: (f: Finding) => void;
}) {
  const review = doc.review;
  const interrupt = review?.interrupt?.value;
  const trace = running ? liveTrace : (review?.values.trace ?? []);
  const waitingOn = interrupt?.type === 'triage' ? 'human_triage' : interrupt?.type === 'memo_review' ? 'memo_review' : null;

  return (
    <div className="stack stack-lg">
      {doc.risk_score != null && (
        <div className="card card-pad stack">
          <div className="row spread row-wrap" style={{ alignItems: 'flex-start' }}>
            <Gauge score={doc.risk_score} level={doc.risk_level} />
            <div className="stack stack-sm" style={{ alignItems: 'flex-end' }}>
              {Object.keys(doc.redactions).length > 0 && (
                <span className="badge badge-ok" title="Redacted before any text was sent to the model">
                  <EyeOff size={11} />
                  {Object.entries(doc.redactions)
                    .map(([k, v]) => `${v} ${k.toLowerCase()}`)
                    .join(', ')}{' '}
                  redacted
                </span>
              )}
              {doc.perspective && <span className="badge badge-accent">Reviewing for {doc.perspective}</span>}
            </div>
          </div>
          {doc.summary && <p className="small muted">{doc.summary}</p>}
        </div>
      )}

      {interrupt?.type === 'triage' && !running && <Triage doc={doc} reload={reload} onFocus={onFocus} onFindingUpdated={onFindingUpdated} onSubmit={() => runReview(`/documents/${doc.id}/review/resume`, { action: 'submit' })} />}

      {interrupt?.type === 'memo_review' && !running && (
        <MemoReview
          key={interrupt.memo}
          memo={interrupt.memo}
          revisions={interrupt.revisions}
          maxRevisions={interrupt.max_revisions}
          onDecide={(body) => runReview(`/documents/${doc.id}/review/resume`, body)}
        />
      )}

      {review?.status === 'done' && doc.memo && <FinalMemo doc={doc} />}

      <div className="card card-pad stack">
        <div className="row spread">
          <div className="section-title">Workflow</div>
          {review && !running && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => {
                if (window.confirm('Re-run the review from scratch? Your current triage decisions on this contract will be cleared. Learned preferences are kept.'))
                  runReview(`/documents/${doc.id}/review`, {});
              }}
            >
              <RotateCcw size={13} /> Re-run
            </button>
          )}
        </div>
        <Pipeline steps={STEPS} trace={trace} running={running} waitingOn={running ? null : waitingOn} engines={running ? undefined : doc.engines} />
      </div>
    </div>
  );
}

// ── Triage ─────────────────────────────────────────────────────────────────

function Triage({
  doc,
  reload,
  onFocus,
  onSubmit,
  onFindingUpdated,
}: {
  doc: DocumentDetail;
  reload: () => Promise<void>;
  onFocus: (f: Omit<Focus, 'nonce'>) => void;
  onSubmit: () => void;
  onFindingUpdated: (f: Finding) => void;
}) {
  const { toast } = useApp();
  const findings = doc.findings;
  const [filter, setFilter] = useState<Filter>('open');
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [showKeys, setShowKeys] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const inFlight = useRef(false);

  const sorted = useMemo(
    () => [...findings].sort((a, b) => RISK_ORDER[a.risk] - RISK_ORDER[b.risk]),
    [findings],
  );
  const visible = sorted.filter((f) => (filter === 'all' ? true : filter === 'open' ? f.status === 'pending' : f.status !== 'pending'));
  const decided = findings.filter((f) => f.status !== 'pending').length;
  const blocking = findings.filter((f) => f.status === 'pending' && (f.risk === 'high' || f.risk === 'medium')).length;
  const pendingLow = findings.filter((f) => f.status === 'pending' && f.risk === 'low');

  const decide = useCallback(
    async (f: Finding, patch: { status?: FindingStatus; reviewer_note?: string; final_suggestion?: string }) => {
      if (inFlight.current) return false;
      inFlight.current = true;
      try {
        const updated = await api<Finding>(`/findings/${f.id}`, { method: 'PATCH', body: patch });
        onFindingUpdated(updated);
        setEditing(null);
        if (patch.status && patch.status !== 'pending') {
          const next = sorted.find((x) => x.status === 'pending' && x.id !== f.id);
          setSelected(next?.id ?? null);
        }
        return true;
      } catch (e) {
        toast((e as Error).message, 'error');
        return false;
      } finally {
        inFlight.current = false;
      }
    },
    [sorted, toast, onFindingUpdated],
  );

  const acceptLow = async () => {
    try {
      await api(`/documents/${doc.id}/findings/bulk`, { body: { ids: pendingLow.map((f) => f.id), status: 'accepted' } });
      await reload();
    } catch (e) {
      toast((e as Error).message, 'error');
    }
  };

  // Keyboard triage: j/k move, a accept, d dismiss, e edit, x escalate, u undo.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest('input, textarea, select, [contenteditable]') || e.metaKey || e.ctrlKey || e.altKey) return;
      const idx = visible.findIndex((f) => f.id === selected);
      const cur = visible[idx];
      const move = (d: number) => {
        const n = visible[Math.min(visible.length - 1, Math.max(0, idx + d))];
        if (n) {
          setSelected(n.id);
          if (n.clause_id) onFocus({ clauseId: n.clause_id });
          listRef.current?.querySelector(`[data-id="${n.id}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
      };
      if (e.key === 'j' || e.key === 'ArrowDown') move(1);
      else if (e.key === 'k' || e.key === 'ArrowUp') move(-1);
      else if (!cur) return;
      else if (e.key === 'a') decide(cur, { status: 'accepted' });
      else if (e.key === 'e') setEditing(cur.id);
      else if (e.key === 'x') decide(cur, { status: 'escalated' });
      else if (e.key === 'u') decide(cur, { status: 'pending' });
      else if (e.key === 'd') {
        if (cur.risk === 'high' && !cur.reviewer_note) setEditing(`${cur.id}:dismiss`);
        else decide(cur, { status: 'dismissed' });
      } else return;
      e.preventDefault();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [visible, selected, decide, onFocus]);

  return (
    <div className="stack" ref={listRef}>
      <div className="human-card stack">
        <div className="row spread">
          <span className="human-label">
            <Gavel size={13} /> Your decision needed
          </span>
          <button className="btn btn-ghost btn-sm" onClick={() => setShowKeys((s) => !s)}>
            <Keyboard size={13} /> Shortcuts
          </button>
        </div>
        <div>
          <b>Triage {findings.length} findings.</b>{' '}
          <span className="muted small">
            Only findings you accept, edit or escalate reach the memo. Dismissals teach the assistant what not to flag next time.
          </span>
        </div>
        {showKeys && (
          <div className="row row-wrap small muted" style={{ gap: 12 }}>
            <span><span className="kbd">j</span>/<span className="kbd">k</span> move</span>
            <span><span className="kbd">a</span> accept</span>
            <span><span className="kbd">e</span> edit redline</span>
            <span><span className="kbd">d</span> dismiss</span>
            <span><span className="kbd">x</span> escalate</span>
            <span><span className="kbd">u</span> undo</span>
          </div>
        )}
        <div className="progress">
          <div style={{ width: `${findings.length ? (decided / findings.length) * 100 : 100}%`, background: 'var(--human)' }} />
        </div>
        <div className="row row-wrap spread">
          <div className="seg">
            {(['open', 'all', 'decided'] as Filter[]).map((f) => (
              <button key={f} className={filter === f ? 'on' : ''} onClick={() => setFilter(f)}>
                {pretty(f)}{' '}
                <span className="faint">
                  {f === 'open' ? findings.length - decided : f === 'decided' ? decided : findings.length}
                </span>
              </button>
            ))}
          </div>
          <div className="row">
            {pendingLow.length > 0 && (
              <button className="btn btn-sm" onClick={acceptLow}>
                <CheckCheck size={13} /> Accept {pendingLow.length} low-risk
              </button>
            )}
            <button className="btn btn-primary btn-sm" disabled={blocking > 0} onClick={onSubmit} title={blocking ? `${blocking} medium/high findings still need a decision` : ''}>
              <Send size={13} /> {blocking ? `${blocking} left to decide` : 'Submit triage'}
            </button>
          </div>
        </div>
      </div>

      {visible.length === 0 && (
        <div className="alert alert-ok">
          <ShieldCheck size={16} />
          <div>{filter === 'open' ? 'Everything is decided. Submit your triage to draft the memo.' : 'Nothing here.'}</div>
        </div>
      )}

      {visible.map((f) => (
        <FindingCard
          key={f.id}
          f={f}
          selected={selected === f.id}
          editing={editing}
          setEditing={setEditing}
          onSelect={() => {
            setSelected(f.id);
            if (f.clause_id) onFocus({ clauseId: f.clause_id });
          }}
          decide={decide}
        />
      ))}
    </div>
  );
}

function FindingCard({
  f,
  selected,
  editing,
  setEditing,
  onSelect,
  decide,
}: {
  f: Finding;
  selected: boolean;
  editing: string | null;
  setEditing: (v: string | null) => void;
  onSelect: () => void;
  decide: (f: Finding, patch: { status?: FindingStatus; reviewer_note?: string; final_suggestion?: string }) => Promise<boolean>;
}) {
  const [redline, setRedline] = useState(f.final_suggestion ?? f.suggestion);
  const [note, setNote] = useState(f.reviewer_note);
  const isEditing = editing === f.id;
  const isDismissing = editing === `${f.id}:dismiss`;
  const decidedBadge: Record<FindingStatus, [string, string]> = {
    pending: ['', ''],
    accepted: ['badge-ok', 'Accepted'],
    edited: ['badge-ok', 'Accepted with edits'],
    dismissed: ['', 'Dismissed'],
    escalated: ['badge-human', 'Escalated'],
  };

  return (
    <div
      data-id={f.id}
      className={`finding stack stack-sm ${selected ? 'selected' : ''} ${f.status !== 'pending' ? 'decided' : ''}`}
      onClick={onSelect}
    >
      <div className="row spread" style={{ alignItems: 'flex-start' }}>
        <div className="stack stack-sm grow">
          <div className="row row-wrap" style={{ gap: 6 }}>
            <RiskBadge risk={f.risk} />
            <span className="badge badge-outline">{SOURCE_LABEL[f.source]}</span>
            <span className="tiny faint">{pretty(f.category)}</span>
            {f.clause_id && <span className="tiny mono faint">{f.clause_id}</span>}
          </div>
          <h4>{f.title}</h4>
        </div>
        {f.status !== 'pending' && (
          <span className={`badge ${decidedBadge[f.status][0]}`} title={f.decided_by ? `by ${f.decided_by}` : ''}>
            {decidedBadge[f.status][1]}
          </span>
        )}
      </div>
      <p>{f.rationale}</p>
      {!isEditing && (f.final_suggestion || f.suggestion) && (
        <div className="redline">
          <div className="tiny faint" style={{ fontFamily: 'var(--font)', marginBottom: 2 }}>
            {f.final_suggestion ? 'Your redline' : 'Suggested redline'}
          </div>
          {f.final_suggestion || f.suggestion}
        </div>
      )}
      {f.reviewer_note && !isEditing && !isDismissing && <div className="small muted">Your note: {f.reviewer_note}</div>}

      {isEditing && (
        <div className="stack stack-sm" onClick={(e) => e.stopPropagation()}>
          <label className="label">Redline you want to propose</label>
          <textarea className="textarea serif" value={redline} onChange={(e) => setRedline(e.target.value)} autoFocus />
          <input className="input" placeholder="Note for the memo (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="row">
            <button
              className="btn btn-ok btn-sm"
              onClick={() => decide(f, { status: 'edited', final_suggestion: redline, reviewer_note: note })}
              disabled={!redline.trim()}
            >
              <Check size={13} /> Save & accept
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => setEditing(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {isDismissing && (
        <div className="stack stack-sm" onClick={(e) => e.stopPropagation()}>
          <label className="label">Why is this not an issue? {f.risk === 'high' ? '(required for high risk)' : '(optional)'}</label>
          <input
            className="input"
            autoFocus
            placeholder="e.g. the obligation is mutual; we accept this standard"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (note.trim() || f.risk !== 'high')) decide(f, { status: 'dismissed', reviewer_note: note });
            }}
          />
          <div className="tiny faint">The assistant will remember this reason and stop flagging similar clauses.</div>
          <div className="row">
            <button
              className="btn btn-sm"
              disabled={f.risk === 'high' && !note.trim()}
              onClick={() => decide(f, { status: 'dismissed', reviewer_note: note })}
            >
              Dismiss
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => setEditing(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {!isEditing && !isDismissing && (
        <div className="row row-wrap" onClick={(e) => e.stopPropagation()}>
          {f.status === 'pending' ? (
            <>
              <button className="btn btn-ok btn-sm" onClick={() => decide(f, { status: 'accepted' })}>
                <Check size={13} /> Accept
              </button>
              <button className="btn btn-sm" onClick={() => setEditing(f.id)}>
                <Pencil size={13} /> Edit redline
              </button>
              <button className="btn btn-sm" onClick={() => setEditing(`${f.id}:dismiss`)}>
                <X size={13} /> Dismiss
              </button>
              <button className="btn btn-human btn-sm" onClick={() => decide(f, { status: 'escalated' })}>
                <ArrowUpRight size={13} /> Escalate
              </button>
            </>
          ) : (
            <button className="btn btn-ghost btn-sm" onClick={() => decide(f, { status: 'pending' })}>
              <RotateCcw size={13} /> Undo
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── Memo approval ──────────────────────────────────────────────────────────

function MemoReview({
  memo,
  revisions,
  maxRevisions,
  onDecide,
}: {
  memo: string;
  revisions: number;
  maxRevisions: number;
  onDecide: (body: { action: string; memo?: string; feedback?: string }) => void;
}) {
  const [mode, setMode] = useState<'view' | 'edit' | 'revise'>('view');
  const [text, setText] = useState(memo);
  const [feedback, setFeedback] = useState('');

  return (
    <div className="human-card stack">
      <div className="row spread">
        <span className="human-label">
          <FileSignature size={13} /> Approve the memo
        </span>
        {revisions > 0 && (
          <span className="tiny faint">
            Revision {revisions} of {maxRevisions}
          </span>
        )}
      </div>
      {mode === 'edit' ? (
        <textarea className="textarea" style={{ minHeight: 320, fontFamily: 'var(--mono)', fontSize: 12.5 }} value={text} onChange={(e) => setText(e.target.value)} />
      ) : (
        <div className="answer-box">
          <Markdown text={memo} />
        </div>
      )}
      {mode === 'revise' && (
        <div className="stack stack-sm">
          <label className="label">What should change?</label>
          <textarea
            className="textarea"
            autoFocus
            placeholder="e.g. Lead with the indemnity, drop the governing law point, make it shorter for the client."
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
          />
        </div>
      )}
      <div className="row row-wrap">
        {mode === 'view' && (
          <>
            <button className="btn btn-ok" onClick={() => onDecide({ action: 'approve' })}>
              <Check size={14} /> Approve
            </button>
            <button className="btn" onClick={() => setMode('edit')}>
              <Pencil size={14} /> Edit myself
            </button>
            <button className="btn btn-human" disabled={revisions >= maxRevisions} onClick={() => setMode('revise')}>
              <RotateCcw size={14} /> Request changes
            </button>
          </>
        )}
        {mode === 'edit' && (
          <>
            <button className="btn btn-ok" disabled={!text.trim()} onClick={() => onDecide({ action: 'edit', memo: text })}>
              <Check size={14} /> Approve my version
            </button>
            <button className="btn btn-ghost" onClick={() => setMode('view')}>
              Cancel
            </button>
          </>
        )}
        {mode === 'revise' && (
          <>
            <button className="btn btn-human" disabled={!feedback.trim()} onClick={() => onDecide({ action: 'revise', feedback })}>
              <Send size={14} /> Send back to the assistant
            </button>
            <button className="btn btn-ghost" onClick={() => setMode('view')}>
              Cancel
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function FinalMemo({ doc }: { doc: DocumentDetail }) {
  const { toast, profile } = useApp();
  const stamp = `\n\n---\n_AI-assisted draft. Reviewed and ${doc.memo_status === 'edited' ? 'edited' : 'approved'} by ${profile?.name ?? 'reviewer'} on ${new Date().toLocaleDateString()}._\n`;
  return (
    <div className="card card-pad stack">
      <div className="row spread row-wrap">
        <div className="row">
          <span className="badge badge-ok">
            <ShieldCheck size={11} /> Memo {doc.memo_status === 'edited' ? 'approved with your edits' : 'approved'}
          </span>
        </div>
        <div className="row">
          <button
            className="btn btn-sm"
            onClick={() => {
              navigator.clipboard.writeText(doc.memo! + stamp);
              toast('Memo copied');
            }}
          >
            <Copy size={13} /> Copy
          </button>
          <button className="btn btn-sm" onClick={() => saveBlob(new Blob([doc.memo! + stamp], { type: 'text/markdown' }), `${doc.name.replace(/\.\w+$/, '')}-memo.md`)}>
            <Download size={13} /> Download .md
          </button>
        </div>
      </div>
      <Markdown text={doc.memo!} />
      {doc.findings.some((f) => f.status === 'escalated') && (
        <div className="alert alert-human">
          <AlertOctagon size={16} />
          <div className="small">
            {doc.findings.filter((f) => f.status === 'escalated').length} issue(s) were escalated to senior counsel.
          </div>
        </div>
      )}
    </div>
  );
}

