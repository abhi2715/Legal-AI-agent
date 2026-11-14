import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, BookCheck, CalendarDays, ClipboardCheck, History, MessagesSquare } from 'lucide-react';
import { api, stream } from '../../lib/api';
import { useApp } from '../../lib/app-context';
import { STATUS_LABEL } from '../../lib/format';
import type { DocumentDetail, Finding, Risk, TraceEntry } from '../../lib/types';
import DocumentViewer, { type Focus } from '../../components/DocumentViewer';
import { Spinner } from '../../components/ui';
import SetupCard from './doc/SetupCard';
import ReviewTab from './doc/ReviewTab';
import AskTab from './doc/AskTab';
import ObligationsTab from './doc/ObligationsTab';
import ComplianceTab from './doc/ComplianceTab';
import ActivityTab from './doc/ActivityTab';

type Tab = 'review' | 'ask' | 'obligations' | 'playbook' | 'activity';
const RANK: Record<Risk, number> = { none: 0, low: 1, medium: 2, high: 3 };

export default function DocumentWorkspace() {
  const { docId } = useParams();
  const { toast } = useApp();
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('review');
  const [focus, setFocus] = useState<Focus | null>(null);
  const [running, setRunning] = useState(false);
  const [liveTrace, setLiveTrace] = useState<TraceEntry[]>([]);
  const [version, setVersion] = useState(0);

  const load = useCallback(async () => {
    try {
      setDoc(await api<DocumentDetail>(`/documents/${docId}`));
      setVersion((v) => v + 1);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [docId]);

  useEffect(() => {
    load();
  }, [load]);

  const onFindingUpdated = useCallback(
    (f: Finding) => setDoc((d) => (d ? { ...d, findings: d.findings.map((x) => (x.id === f.id ? f : x)) } : d)),
    [],
  );

  const onFocus = useCallback((f: Omit<Focus, 'nonce'>) => setFocus({ ...f, nonce: Date.now() }), []);

  const runReview = useCallback(
    async (path: string, body: unknown) => {
      setRunning(true);
      setTab('review');
      setLiveTrace(path.endsWith('/resume') ? [...(doc?.review?.values.trace ?? [])] : []);
      await stream(path, body, {
        onNode: (d) => setLiveTrace((t) => [...t, ...d.trace]),
        onError: (m) => toast(m, 'error'),
      });
      setRunning(false);
      await load();
    },
    [doc, load, toast],
  );

  const startReview = async (perspective: string, counterparty: string) => {
    try {
      await api(`/documents/${docId}`, { method: 'PATCH', body: { perspective, counterparty } });
    } catch (e) {
      toast((e as Error).message, 'error');
      return;
    }
    await runReview(`/documents/${docId}/review`, {});
  };

  const riskByClause = useMemo(() => {
    const out: Record<string, Risk> = {};
    for (const f of doc?.findings ?? []) {
      if (!f.clause_id || f.status === 'dismissed') continue;
      if (!out[f.clause_id] || RANK[f.risk] > RANK[out[f.clause_id]]) out[f.clause_id] = f.risk;
    }
    return out;
  }, [doc?.findings]);

  if (error) {
    return (
      <div className="page">
        <div className="alert alert-error">{error}</div>
        <Link to="/app" className="btn" style={{ marginTop: 12 }}>
          <ArrowLeft size={14} /> Back to contracts
        </Link>
      </div>
    );
  }
  if (!doc) {
    return (
      <div className="page row muted">
        <Spinner /> Loading contract…
      </div>
    );
  }

  const needsSetup = !doc.review && !running;
  const awaitingReview = doc.review?.interrupt != null;
  const awaitingQA = doc.threads.some((t) => t.status.startsWith('awaiting'));

  const TABS: { id: Tab; label: string; icon: typeof ClipboardCheck; dot?: boolean; count?: number }[] = [
    { id: 'review', label: 'Review', icon: ClipboardCheck, dot: awaitingReview },
    { id: 'ask', label: 'Ask', icon: MessagesSquare, dot: awaitingQA },
    { id: 'obligations', label: 'Obligations', icon: CalendarDays, count: doc.obligations.filter((o) => !o.done).length },
    { id: 'playbook', label: 'Playbook', icon: BookCheck },
    { id: 'activity', label: 'Activity', icon: History },
  ];

  return (
    <div className="ws">
      <header className="ws-head">
        <Link to="/app" className="btn btn-ghost btn-icon btn-sm" aria-label="Back to contracts">
          <ArrowLeft size={16} />
        </Link>
        <div className="grow" style={{ minWidth: 160 }}>
          <h1 className="truncate">{doc.name}</h1>
          <div className="tiny faint">
            {doc.parties.map((p) => p.alias).join(' · ') || 'Parties not detected'}
            {doc.perspective && ` · reviewing for ${doc.perspective}`}
          </div>
        </div>
        <span className={`badge ${awaitingReview ? 'badge-human' : doc.status === 'reviewed' ? 'badge-ok' : ''}`}>
          {running ? 'Running…' : (STATUS_LABEL[doc.status] ?? doc.status)}
        </span>
      </header>
      <div className="ws-split">
        <DocumentViewer doc={doc} focus={focus} riskByClause={riskByClause} />
        <section className="panel" aria-label="Review panel">
          {needsSetup ? (
            <div className="panel-body">
              <SetupCard doc={doc} onStart={startReview} busy={running} />
            </div>
          ) : (
            <>
              <nav className="tabs" role="tablist">
                {TABS.map(({ id, label, icon: Icon, dot, count }) => (
                  <button key={id} role="tab" aria-selected={tab === id} className={`tab ${tab === id ? 'on' : ''}`} onClick={() => setTab(id)}>
                    <Icon size={14} />
                    {label}
                    {dot && <span className="dot" aria-label="needs your input" />}
                    {!!count && <span className="tiny faint">{count}</span>}
                  </button>
                ))}
              </nav>
              <div className="panel-body">
                {tab === 'review' && (
                  <ReviewTab doc={doc} reload={load} onFocus={onFocus} liveTrace={liveTrace} running={running} runReview={runReview} onFindingUpdated={onFindingUpdated} />
                )}
                {tab === 'ask' && <AskTab doc={doc} reloadDoc={load} onFocus={onFocus} />}
                {tab === 'obligations' && <ObligationsTab key={version} doc={doc} onFocus={onFocus} />}
                {tab === 'playbook' && <ComplianceTab doc={doc} onFocus={onFocus} />}
                {tab === 'activity' && <ActivityTab docId={doc.id} version={version} />}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
