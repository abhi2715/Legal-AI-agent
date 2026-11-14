import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowLeft,
  BadgeCheck,
  Bot,
  Check,
  CircleAlert,
  CircleHelp,
  GitBranch,
  Gavel,
  History,
  MessageSquarePlus,
  Pencil,
  Pin,
  RotateCcw,
  Send,
  Sparkles,
  ThumbsDown,
  Undo2,
  X,
} from 'lucide-react';
import { api, stream } from '../../../lib/api';
import { useApp } from '../../../lib/app-context';
import { Markdown } from '../../../lib/markdown';
import { STATUS_LABEL, timeAgo } from '../../../lib/format';
import type { Checkpoint, DocumentDetail, Hit, QAValues, RunState, ThreadDetail, TraceEntry, Verification } from '../../../lib/types';
import Pipeline, { type StepDef } from '../../../components/Pipeline';
import { Confidence, Empty, Spinner } from '../../../components/ui';
import type { Focus } from '../../../components/DocumentViewer';

const STEPS: StepDef[] = [
  { node: 'plan', label: 'Plan' },
  { node: 'clarify', label: 'Clarify with you', human: true },
  { node: 'retrieve', label: 'Retrieve clauses' },
  { node: 'draft', label: 'Draft answer' },
  { node: 'verify', label: 'Verify every quote' },
  { node: 'gate', label: 'Apply your review policy' },
  { node: 'human_review', label: 'Your review', human: true },
  { node: 'finalize', label: 'Finalize & learn' },
];

const SUGGESTIONS = [
  'How can we terminate this agreement, and what notice is required?',
  'What is our total liability exposure?',
  'Which obligations survive termination?',
  'Is there anything unusual compared with a standard agreement of this type?',
];

const ANSWER_TYPE: Record<string, [string, string]> = {
  answered: ['badge-ok', 'Answered from the contract'],
  partially_answered: ['badge-medium', 'Partially answered'],
  contract_silent: ['badge-low', 'Contract is silent'],
  needs_counsel: ['badge-high', 'Needs counsel'],
};

export default function AskTab({
  doc,
  reloadDoc,
  onFocus,
}: {
  doc: DocumentDetail;
  reloadDoc: () => Promise<void>;
  onFocus: (f: Omit<Focus, 'nonce'>) => void;
}) {
  const { toast } = useApp();
  const [openId, setOpenId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [live, setLive] = useState<{ trace: TraceEntry[]; question: string } | null>(null);

  const ask = async (question: string) => {
    if (!question.trim()) return;
    setDraft('');
    setLive({ trace: [], question });
    let finished: RunState | null = null;
    await stream(`/documents/${doc.id}/ask`, { question }, {
      onNode: (d) => setLive((l) => (l ? { ...l, trace: [...l.trace, ...d.trace] } : l)),
      onState: (s) => (finished = s),
      onError: (m) => toast(m, 'error'),
    });
    setLive(null);
    await reloadDoc();
    const tid = (finished as RunState | null)?.values?.thread_id as string | undefined;
    if (tid) setOpenId(tid);
  };

  if (openId) return <ThreadView threadId={openId} doc={doc} onBack={() => { setOpenId(null); reloadDoc(); }} onFocus={onFocus} />;

  return (
    <div className="stack stack-lg">
      <form
        className="card card-pad stack"
        onSubmit={(e) => {
          e.preventDefault();
          ask(draft);
        }}
      >
        <label className="label" htmlFor="ask">
          Ask about this contract
        </label>
        <textarea
          id="ask"
          className="textarea"
          style={{ minHeight: 64 }}
          placeholder="e.g. Can the other side terminate without cause?"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) ask(draft);
          }}
          disabled={!!live}
        />
        <div className="row spread row-wrap">
          <span className="tiny faint">Every answer quotes the contract, and every quote is checked against the text. ⌘↵ to send</span>
          <button className="btn btn-primary" disabled={!draft.trim() || !!live}>
            <Send size={14} /> Ask
          </button>
        </div>
        {!live && doc.threads.length === 0 && (
          <div className="row row-wrap">
            {SUGGESTIONS.map((s) => (
              <button type="button" key={s} className="chip" onClick={() => ask(s)}>
                <Sparkles size={12} /> {s}
              </button>
            ))}
          </div>
        )}
      </form>

      {live && (
        <div className="card card-pad stack">
          <div className="question-bubble">{live.question}</div>
          <Pipeline steps={STEPS} trace={live.trace} running />
        </div>
      )}

      <div className="stack">
        {doc.threads.length > 0 && <div className="section-title">Questions</div>}
        {doc.threads.length === 0 && !live && (
          <Empty icon={<MessageSquarePlus size={26} />} title="No questions yet">
            Answers go through your review policy before they count as final.
          </Empty>
        )}
        {doc.threads.map((t) => {
          const needsYou = t.status.startsWith('awaiting');
          return (
            <button key={t.id} className="card qa-thread stack stack-sm" style={{ textAlign: 'left' }} onClick={() => setOpenId(t.id)}>
              <div className="row spread">
                <span style={{ fontWeight: 600 }} className="truncate grow">
                  {t.question}
                </span>
                <span
                  className={`badge ${needsYou ? 'badge-human' : t.status === 'rejected' ? 'badge-high' : t.status.includes('approved') || t.status === 'edited' ? 'badge-ok' : ''}`}
                >
                  {needsYou && <Gavel size={11} />}
                  {STATUS_LABEL[t.status] ?? t.status}
                </span>
              </div>
              {t.answer && <div className="small muted truncate">{t.answer.replace(/[*_#>]/g, '')}</div>}
              <div className="tiny faint">{timeAgo(t.updated_at)}</div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── Thread ─────────────────────────────────────────────────────────────────

function ThreadView({
  threadId,
  doc,
  onBack,
  onFocus,
}: {
  threadId: string;
  doc: DocumentDetail;
  onBack: () => void;
  onFocus: (f: Omit<Focus, 'nonce'>) => void;
}) {
  const { toast } = useApp();
  const [thread, setThread] = useState<ThreadDetail | null>(null);
  const [liveTrace, setLiveTrace] = useState<TraceEntry[] | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const load = useCallback(async () => {
    try {
      setThread(await api<ThreadDetail>(`/threads/${threadId}`));
    } catch (e) {
      toast((e as Error).message, 'error');
    }
  }, [threadId, toast]);

  useEffect(() => {
    load();
  }, [load]);

  const run = async (path: string, body: unknown) => {
    setLiveTrace([...(thread?.run.values.trace ?? [])]);
    await stream(path, body, {
      onNode: (d) => setLiveTrace((t) => [...(t ?? []), ...d.trace]),
      onError: (m) => toast(m, 'error'),
    });
    setLiveTrace(null);
    setShowHistory(false);
    await load();
  };

  if (!thread) {
    return (
      <div className="row muted">
        <Spinner /> Loading…
      </div>
    );
  }

  const runState = thread.run as RunState<QAValues>;
  const v = runState.values;
  const intr = runState.interrupt?.value;
  const running = liveTrace !== null;
  const trace = liveTrace ?? v.trace ?? [];
  const waitingOn = !running && intr ? (intr.type === 'clarify' ? 'clarify' : 'human_review') : null;
  const titleOf = (id: string) => doc.clauses.find((c) => c.id === id)?.title ?? id;

  return (
    <div className="stack stack-lg">
      <div className="row spread">
        <button className="btn btn-ghost btn-sm" onClick={onBack}>
          <ArrowLeft size={14} /> All questions
        </button>
        <button className={`btn btn-sm ${showHistory ? 'btn-primary' : ''}`} onClick={() => setShowHistory((s) => !s)} disabled={running}>
          <History size={13} /> Time travel
        </button>
      </div>

      <div className="question-bubble">{v.question}</div>
      {v.clarification && (
        <div className="small muted">
          <b style={{ color: 'var(--human)' }}>You clarified:</b> {v.clarification}
        </div>
      )}

      {showHistory && <TimeTravel threadId={threadId} question={v.question} hits={v.hits ?? []} onRewind={(body) => run(`/threads/${threadId}/rewind`, body)} />}

      {!running && intr?.type === 'clarify' && (
        <ClarifyCard question={intr.question} options={intr.options} onAnswer={(answer) => run(`/threads/${threadId}/resume`, { action: 'answer', answer })} />
      )}

      {!running && intr?.type === 'answer_review' && (
        <AnswerReview
          key={runState.checkpoint_id ?? ''}
          intr={intr}
          pinned={v.pinned ?? []}
          excluded={v.excluded ?? []}
          titleOf={titleOf}
          onFocus={onFocus}
          onDecide={(body) => run(`/threads/${threadId}/resume`, body)}
        />
      )}

      {!running && runState.status === 'done' && v.final && <FinalAnswer v={v} titleOf={titleOf} onFocus={onFocus} />}

      <div className="card card-pad">
        <div className="section-title" style={{ marginBottom: 10 }}>
          How this answer was produced
        </div>
        <Pipeline steps={STEPS} trace={trace} running={running} waitingOn={waitingOn} engines={running ? undefined : v.engines} />
      </div>
    </div>
  );
}

function ClarifyCard({ question, options, onAnswer }: { question: string; options: string[]; onAnswer: (a: string) => void }) {
  const [text, setText] = useState('');
  return (
    <div className="human-card stack">
      <span className="human-label">
        <CircleHelp size={13} /> The assistant needs a clarification
      </span>
      <div style={{ fontWeight: 600 }}>{question}</div>
      <div className="small muted">Asking now is cheaper than guessing. Pick an option or type your own answer.</div>
      <div className="row row-wrap">
        {options.map((o) => (
          <button key={o} className="chip" onClick={() => onAnswer(o)}>
            {o}
          </button>
        ))}
      </div>
      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) onAnswer(text);
        }}
      >
        <input className="input" placeholder="Or answer in your own words…" value={text} onChange={(e) => setText(e.target.value)} />
        <button className="btn btn-primary" disabled={!text.trim()}>
          <Send size={14} />
        </button>
      </form>
    </div>
  );
}

function QuoteList({ verification, titleOf, onFocus }: { verification: Verification; titleOf: (id: string) => string; onFocus: (f: Omit<Focus, 'nonce'>) => void }) {
  if (!verification.claims.length) return null;
  return (
    <div className="stack stack-sm">
      {verification.claims.map((c, i) => (
        <div key={i} className="stack stack-sm">
          <div className="small" style={{ fontWeight: 500 }}>
            {c.statement}
          </div>
          {c.quotes.length === 0 && (
            <div className="quote bad" style={{ cursor: 'default' }}>
              <CircleAlert size={14} className="bad-icon" />
              <span style={{ fontFamily: 'var(--font)', fontSize: 12.5 }}>No supporting quote. Treat this claim as unverified.</span>
            </div>
          )}
          {c.quotes.map((q, j) => (
            <button
              key={j}
              className={`quote ${q.verified ? '' : 'bad'}`}
              onClick={() => onFocus({ clauseId: q.clause_id, start: q.start, end: q.end, quote: q.quote })}
              title={q.verified ? 'Found verbatim in the contract. Click to view.' : 'This text does not appear in the contract.'}
            >
              {q.verified ? <BadgeCheck size={14} className="ok-icon" /> : <CircleAlert size={14} className="bad-icon" />}
              <span className="grow">
                “{q.quote}”
                <span className="tiny faint" style={{ display: 'block', fontFamily: 'var(--font)', marginTop: 2 }}>
                  {titleOf(q.clause_id)}
                  {q.moved && ` (cited as ${q.cited_clause_id}, found in ${q.clause_id})`}
                  {q.fuzzy && ` · ${Math.round(q.match * 100)}% match`}
                  {!q.verified && ' · not found in the contract'}
                </span>
              </span>
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}

function AnswerReview({
  intr,
  pinned: initialPinned,
  excluded: initialExcluded,
  titleOf,
  onFocus,
  onDecide,
}: {
  intr: Extract<NonNullable<RunState['interrupt']>['value'], { type: 'answer_review' }>;
  pinned: string[];
  excluded: string[];
  titleOf: (id: string) => string;
  onFocus: (f: Omit<Focus, 'nonce'>) => void;
  onDecide: (body: Record<string, unknown>) => void;
}) {
  const { draft, verification, hits, gate, revisions, max_revisions } = intr;
  const [mode, setMode] = useState<'view' | 'edit' | 'revise' | 'reject'>('view');
  const [answer, setAnswer] = useState(draft.answer);
  const [feedback, setFeedback] = useState('');
  const [pinned, setPinned] = useState<string[]>(initialPinned);
  const [excluded, setExcluded] = useState<string[]>(initialExcluded);
  const [type, label] = ANSWER_TYPE[draft.answer_type] ?? ['', draft.answer_type];

  const toggle = (list: string[], set: (v: string[]) => void, id: string, other: string[], setOther: (v: string[]) => void) => {
    set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
    if (other.includes(id)) setOther(other.filter((x) => x !== id));
  };

  return (
    <div className="human-card stack">
      <div className="row spread row-wrap">
        <span className="human-label">
          <Gavel size={13} /> Review the draft
        </span>
        <div className="row">
          <span className={`badge ${type}`}>{label}</span>
          <Confidence value={draft.confidence} />
        </div>
      </div>
      <div className="alert alert-human small">
        <Bot size={15} />
        <div>
          <b>Why you're seeing this:</b> {gate.reason}
        </div>
      </div>

      {mode === 'edit' ? (
        <textarea className="textarea" style={{ minHeight: 200 }} value={answer} onChange={(e) => setAnswer(e.target.value)} autoFocus />
      ) : (
        <div className="answer-box">
          <Markdown text={draft.answer} />
          {draft.caveats.length > 0 && (
            <ul className="small muted" style={{ marginTop: 10, paddingLeft: 18 }}>
              {draft.caveats.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="row spread">
        <div className="section-title">Evidence</div>
        <span className="tiny faint">
          {verification.quotes_verified}/{verification.quotes_total} quotes verified verbatim
        </span>
      </div>
      <QuoteList verification={verification} titleOf={titleOf} onFocus={onFocus} />

      {mode === 'revise' && (
        <div className="stack stack-sm">
          <label className="label">What should the next draft do differently?</label>
          <textarea
            className="textarea"
            autoFocus
            placeholder="e.g. Also consider the survival clause. State the notice period in days."
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
          />
          <div className="section-title" style={{ marginTop: 4 }}>
            Steer the evidence
          </div>
          <div className="tiny faint">Pin clauses the answer must use and exclude ones that are irrelevant.</div>
          {[...hits, ...pinned.filter((p) => !hits.some((h: Hit) => h.clause_id === p)).map((p) => ({ clause_id: p, title: titleOf(p), score: 0, reason: 'pinned' }))].map((h) => (
            <div key={h.clause_id} className={`evidence ${pinned.includes(h.clause_id) ? 'pinned' : ''} ${excluded.includes(h.clause_id) ? 'excluded' : ''}`}>
              <button className="grow truncate" style={{ textAlign: 'left' }} onClick={() => onFocus({ clauseId: h.clause_id })}>
                <span className="mono faint">{h.clause_id}</span> {h.title}
              </button>
              <span className="tiny faint">{h.reason}</span>
              <button className="btn btn-ghost btn-sm btn-icon" title="Pin" onClick={() => toggle(pinned, setPinned, h.clause_id, excluded, setExcluded)}>
                <Pin size={13} />
              </button>
              <button className="btn btn-ghost btn-sm btn-icon" title="Exclude" onClick={() => toggle(excluded, setExcluded, h.clause_id, pinned, setPinned)}>
                <X size={13} />
              </button>
            </div>
          ))}
          <ClausePicker titleOf={titleOf} hits={hits} onPick={(id) => setPinned((p) => (p.includes(id) ? p : [...p, id]))} />
        </div>
      )}

      {mode === 'reject' && (
        <div className="stack stack-sm">
          <label className="label">Why is this wrong? The assistant learns from your reason.</label>
          <textarea className="textarea" autoFocus value={feedback} onChange={(e) => setFeedback(e.target.value)} />
        </div>
      )}

      <div className="row row-wrap">
        {mode === 'view' && (
          <>
            <button className="btn btn-ok" onClick={() => onDecide({ action: 'approve' })}>
              <Check size={14} /> Approve
            </button>
            <button className="btn" onClick={() => setMode('edit')}>
              <Pencil size={14} /> Edit
            </button>
            <button className="btn btn-human" onClick={() => setMode('revise')} disabled={revisions >= max_revisions}>
              <RotateCcw size={14} /> Revise
            </button>
            <button className="btn btn-danger" onClick={() => setMode('reject')}>
              <ThumbsDown size={14} /> Reject
            </button>
            {revisions > 0 && <span className="tiny faint">Revision {revisions}/{max_revisions}</span>}
          </>
        )}
        {mode === 'edit' && (
          <>
            <button className="btn btn-ok" disabled={!answer.trim()} onClick={() => onDecide({ action: 'edit', answer })}>
              <Check size={14} /> Approve my edit
            </button>
            <button className="btn btn-ghost" onClick={() => setMode('view')}>
              Cancel
            </button>
            <span className="tiny faint">Your edit is diffed and turned into a lesson for future answers.</span>
          </>
        )}
        {mode === 'revise' && (
          <>
            <button className="btn btn-human" disabled={!feedback.trim()} onClick={() => onDecide({ action: 'revise', feedback, pinned, excluded })}>
              <Send size={14} /> Send back
            </button>
            <button className="btn btn-ghost" onClick={() => setMode('view')}>
              Cancel
            </button>
          </>
        )}
        {mode === 'reject' && (
          <>
            <button className="btn btn-danger" disabled={!feedback.trim()} onClick={() => onDecide({ action: 'reject', feedback })}>
              <ThumbsDown size={14} /> Reject answer
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

function ClausePicker({ titleOf, hits, onPick }: { titleOf: (id: string) => string; hits: Hit[]; onPick: (id: string) => void }) {
  const [value, setValue] = useState('');
  return (
    <div className="row">
      <input
        className="input"
        placeholder="Pin another clause by id, e.g. c7"
        value={value}
        onChange={(e) => setValue(e.target.value.trim())}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && /^c\d+$/.test(value) && titleOf(value) !== value) {
            onPick(value);
            setValue('');
          }
        }}
      />
      <span className="tiny faint" style={{ whiteSpace: 'nowrap' }}>
        {hits.length} retrieved
      </span>
    </div>
  );
}

function FinalAnswer({ v, titleOf, onFocus }: { v: QAValues; titleOf: (id: string) => string; onFocus: (f: Omit<Focus, 'nonce'>) => void }) {
  const f = v.final!;
  const [showDiff, setShowDiff] = useState(false);
  const badge =
    f.status === 'rejected' ? 'badge-high' : f.status === 'auto_approved' ? 'badge-accent' : 'badge-ok';
  return (
    <div className="card card-pad stack">
      <div className="row spread row-wrap">
        <span className={`badge ${badge}`}>
          {f.status === 'rejected' ? <X size={11} /> : <Check size={11} />}
          {STATUS_LABEL[f.status]}
          {f.reviewer && ` by ${f.reviewer}`}
        </span>
        {v.draft && <Confidence value={v.draft.confidence} />}
      </div>
      {f.status === 'auto_approved' && v.gate && <div className="tiny faint">{v.gate.reason}</div>}
      {f.status === 'rejected' ? (
        <div className="small muted">
          Rejected. Feedback was recorded for future drafts. <s>{f.answer.slice(0, 200)}</s>
        </div>
      ) : f.diff && showDiff ? (
        <div className="answer-box diff" style={{ lineHeight: 1.7 }}>
          {f.diff.map((d, i) =>
            d.op === 'eq' ? <span key={i}>{d.text} </span> : d.op === 'ins' ? <ins key={i}>{d.text} </ins> : <del key={i}>{d.text} </del>,
          )}
        </div>
      ) : (
        <div className="answer-box">
          <Markdown text={f.answer} />
        </div>
      )}
      {f.diff && (
        <button className="btn btn-ghost btn-sm" style={{ alignSelf: 'flex-start' }} onClick={() => setShowDiff((d) => !d)}>
          {showDiff ? 'Show final answer' : 'Show what you changed'}
        </button>
      )}
      {f.lessons.length > 0 && (
        <div className="alert alert-ok small">
          <Sparkles size={14} />
          <div>
            <b>Learned:</b> {f.lessons[0]}{' '}
            <Link to="/app/memory" className="tiny">
              Manage
            </Link>
          </div>
        </div>
      )}
      {v.verification && f.status !== 'rejected' && <QuoteList verification={v.verification} titleOf={titleOf} onFocus={onFocus} />}
      {v.draft && v.draft.follow_up_questions.length > 0 && (
        <div className="small muted">Worth asking next: {v.draft.follow_up_questions.join(' · ')}</div>
      )}
    </div>
  );
}

function TimeTravel({
  threadId,
  question,
  hits,
  onRewind,
}: {
  threadId: string;
  question: string;
  hits: Hit[];
  onRewind: (body: Record<string, unknown>) => void;
}) {
  const { toast } = useApp();
  const [points, setPoints] = useState<Checkpoint[] | null>(null);
  const [target, setTarget] = useState<Checkpoint | null>(null);
  const [q, setQ] = useState(question);

  useEffect(() => {
    api<Checkpoint[]>(`/threads/${threadId}/history`)
      .then(setPoints)
      .catch((e) => toast((e as Error).message, 'error'));
  }, [threadId, toast]);

  return (
    <div className="card card-pad stack">
      <div className="row">
        <GitBranch size={15} style={{ color: 'var(--accent)' }} />
        <b>Rewind to any step</b>
      </div>
      <div className="small muted">
        Every step is checkpointed. Rewind to re-run from that point, or change the question and branch off. The original stays in the audit
        trail.
      </div>
      {!points ? (
        <Spinner />
      ) : (
        <div className="timeline" style={{ maxHeight: 260, overflowY: 'auto' }}>
          {points.map((p) => (
            <div key={p.checkpoint_id} className="tl-item" style={target?.checkpoint_id === p.checkpoint_id ? { background: 'var(--accent-soft)' } : undefined}>
              <span className={`tl-dot ${p.next === 'human_review' || p.next === 'clarify' ? 'human' : 'ai'}`} />
              <div>
                <div>{p.label}</div>
                <div className="tiny faint">
                  {p.revision ? `revision ${p.revision} · ` : ''}
                  {timeAgo(p.created_at)}
                </div>
              </div>
              <button className="btn btn-sm" onClick={() => setTarget(p)}>
                <Undo2 size={12} /> Rewind
              </button>
            </div>
          ))}
        </div>
      )}
      {target && (
        <div className="stack stack-sm">
          <label className="label">Question for the new branch</label>
          <input className="input" value={q} onChange={(e) => setQ(e.target.value)} />
          <div className="row">
            <button className="btn btn-primary btn-sm" onClick={() => onRewind({ checkpoint_id: target.checkpoint_id, question: q !== question ? q : undefined })}>
              <GitBranch size={13} /> {q !== question ? 'Branch with new question' : `Re-run from “${target.label.replace('Before: ', '')}”`}
            </button>
            <span className="tiny faint">{hits.length} clauses were retrieved originally</span>
          </div>
        </div>
      )}
    </div>
  );
}
