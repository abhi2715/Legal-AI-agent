import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AlertTriangle, CheckCircle2, FileText, FlaskConical, Gavel, Trash2, Upload } from 'lucide-react';
import { api, upload } from '../../lib/api';
import { useApp } from '../../lib/app-context';
import { STATUS_LABEL, timeAgo } from '../../lib/format';
import type { DocumentDetail, DocumentSummary, Insights } from '../../lib/types';
import { Empty, Spinner } from '../../components/ui';

export default function Documents() {
  const { toast, engine } = useApp();
  const navigate = useNavigate();
  const [docs, setDocs] = useState<DocumentSummary[] | null>(null);
  const [samples, setSamples] = useState<{ id: string; name: string }[]>([]);
  const [insights, setInsights] = useState<Insights | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const [d, s, i] = await Promise.all([
        api<DocumentSummary[]>('/documents'),
        api<{ id: string; name: string }[]>('/samples'),
        api<Insights>('/insights'),
      ]);
      setDocs(d);
      setSamples(s);
      setInsights(i);
    } catch (e) {
      toast((e as Error).message, 'error');
    }
  }, [toast]);

  useEffect(() => {
    load();
  }, [load]);

  const handleFile = async (file: File | undefined) => {
    if (!file) return;
    setBusy('upload');
    try {
      const doc = await upload<DocumentDetail>('/documents', file);
      navigate(`/app/doc/${doc.id}`);
    } catch (e) {
      toast((e as Error).message, 'error');
    } finally {
      setBusy(null);
    }
  };

  const loadSample = async (id: string) => {
    setBusy(id);
    try {
      const doc = await api<DocumentDetail>(`/samples/${id}`, { method: 'POST' });
      navigate(`/app/doc/${doc.id}`);
    } catch (e) {
      toast((e as Error).message, 'error');
    } finally {
      setBusy(null);
    }
  };

  const remove = async (doc: DocumentSummary) => {
    if (!window.confirm(`Delete “${doc.name}” and its review history? The audit log is kept.`)) return;
    try {
      await api(`/documents/${doc.id}`, { method: 'DELETE' });
      load();
    } catch (e) {
      toast((e as Error).message, 'error');
    }
  };

  const needsYou = (d: DocumentSummary) =>
    ['awaiting_triage', 'awaiting_memo_approval'].includes(d.status) ? 1 : 0;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Contracts</h1>
          <p>Upload a contract, tell LexiScan which side you're on, and it drafts a review for you to decide on.</p>
        </div>
      </div>

      {engine && !engine.online && (
        <div className="alert alert-warn" style={{ marginBottom: 16 }}>
          <AlertTriangle size={16} />
          <div>
            <b>Running in offline mode.</b> Analysis uses deterministic pattern matching, so it flags and quotes but does
            not interpret. {engine.reason ?? 'Set GROQ_API_KEY on the server to enable AI analysis.'}
          </div>
        </div>
      )}

      <div className="home-grid">
        <div className="stack stack-lg">
          <div
            className={`dropzone ${over ? 'over' : ''}`}
            onClick={() => fileRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(false);
              handleFile(e.dataTransfer.files[0]);
            }}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => e.key === 'Enter' && fileRef.current?.click()}
          >
            <input ref={fileRef} type="file" hidden accept=".pdf,.docx,.txt,.md" onChange={(e) => handleFile(e.target.files?.[0])} />
            {busy === 'upload' ? <Spinner size={26} /> : <Upload size={26} />}
            <div style={{ fontWeight: 600, fontSize: 15 }}>{busy === 'upload' ? 'Reading document…' : 'Drop a contract here or click to upload'}</div>
            <div className="small faint">PDF, DOCX or TXT, up to 15 MB. Personal data is redacted before analysis (configurable).</div>
          </div>

          {samples.length > 0 && (
            <div className="row row-wrap">
              <span className="small muted row">
                <FlaskConical size={14} /> Try a sample:
              </span>
              {samples.map((s) => (
                <button key={s.id} className="chip" onClick={() => loadSample(s.id)} disabled={!!busy}>
                  {busy === s.id && <Spinner size={12} />}
                  {s.name.replace(/\.txt$/, '')}
                </button>
              ))}
            </div>
          )}

          <div className="stack">
            <div className="section-title">Your contracts</div>
            {docs === null ? (
              <div className="row muted">
                <Spinner /> Loading…
              </div>
            ) : docs.length === 0 ? (
              <div className="card">
                <Empty icon={<FileText size={28} />} title="No contracts yet">
                  Upload one above or try a sample.
                </Empty>
              </div>
            ) : (
              <div className="doc-list">
                {docs.map((d) => {
                  const pending = d.findings.pending ?? 0;
                  const decided = Object.entries(d.findings).reduce((n, [k, v]) => (k === 'pending' ? n : n + (v ?? 0)), 0);
                  const scoreColor =
                    d.risk_score == null ? 'var(--text-3)' : d.risk_score >= 60 ? 'var(--high)' : d.risk_score >= 30 ? 'var(--medium)' : 'var(--ok)';
                  return (
                    <Link key={d.id} to={`/app/doc/${d.id}`} className="card doc-row">
                      <div className="doc-icon">
                        <FileText size={18} />
                      </div>
                      <div className="grow">
                        <div className="truncate" style={{ fontWeight: 600 }}>
                          {d.name}
                        </div>
                        <div className="row row-wrap small muted" style={{ gap: 6, marginTop: 2 }}>
                          <span className={`badge ${needsYou(d) ? 'badge-human' : d.status === 'reviewed' ? 'badge-ok' : ''}`}>
                            {needsYou(d) ? <Gavel size={11} /> : d.status === 'reviewed' ? <CheckCircle2 size={11} /> : null}
                            {STATUS_LABEL[d.status] ?? d.status}
                          </span>
                          {d.perspective && <span>You: {d.perspective}</span>}
                          <span>· {d.clause_count} clauses</span>
                          {pending + decided > 0 && (
                            <span>
                              · {decided}/{pending + decided} findings decided
                            </span>
                          )}
                          {d.threads > 0 && <span>· {d.threads} questions</span>}
                          <span>· {timeAgo(d.created_at)}</span>
                        </div>
                      </div>
                      <div className="risk-num" style={{ color: scoreColor }} title="Risk score">
                        {d.risk_score ?? '—'}
                      </div>
                      <button
                        className="btn btn-ghost btn-icon btn-sm"
                        aria-label={`Delete ${d.name}`}
                        onClick={(e) => {
                          e.preventDefault();
                          remove(d);
                        }}
                      >
                        <Trash2 size={14} />
                      </button>
                    </Link>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        <aside className="stack">
          <div className="card card-pad stack">
            <div className="section-title">You and the assistant</div>
            {insights && (
              <>
                <div className="row" style={{ gap: 24 }}>
                  <div className="stat">
                    <span className="stat-num">{insights.answer_acceptance == null ? '—' : `${Math.round(insights.answer_acceptance * 100)}%`}</span>
                    <span className="tiny muted">answers accepted unedited</span>
                  </div>
                  <div className="stat">
                    <span className="stat-num">
                      {insights.false_positive_rate == null ? '—' : `${Math.round(insights.false_positive_rate * 100)}%`}
                    </span>
                    <span className="tiny muted">findings you dismissed</span>
                  </div>
                </div>
                <div className="divider" />
                <div className="small muted">
                  <Link to="/app/memory">
                    <b>{insights.memories_active}</b> learned preferences
                  </Link>{' '}
                  applied {insights.memory_applications} times. Every dismissal and edit you make teaches the assistant, and you can
                  inspect or undo all of it.
                </div>
              </>
            )}
          </div>
          <div className="card card-pad stack stack-sm small muted">
            <div className="section-title">How a review works</div>
            <div>1. You choose which party you represent.</div>
            <div>2. The AI analyzes clauses, checks your playbook and extracts deadlines in parallel.</div>
            <div>
              3. <b style={{ color: 'var(--human)' }}>You triage</b> every finding. Nothing reaches the memo without your decision.
            </div>
            <div>
              4. <b style={{ color: 'var(--human)' }}>You approve</b> the memo, or send it back with notes.
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
