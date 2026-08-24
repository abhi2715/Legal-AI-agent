import { useState, useRef, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  Upload,
  FileText,
  Send,
  Loader2,
  AlertCircle,
  X,
  ChevronRight,
  Shield,
  BookOpen,
  ArrowLeft,
  Briefcase,
  Gavel,
  FileSignature
} from 'lucide-react';
import './AnalyzePage.css';

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:5001';

type AgenticResponse = {
  answer: string;
  citations: Array<{ source: string; chunk_id?: number; location?: string }>;
  reasoning_steps: string[];
  status: 'Pending Review' | 'Approved' | 'Rejected';
  source: string;
};

type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
  agentData?: AgenticResponse;
};

const SUGGESTED_QUESTIONS = [
  'Is the termination clause enforceable?',
  'What are the legal precedents for confidentiality limits?',
  'Does the liability cap violate statutory codes?',
];

export default function AnalyzePage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [questionDraft, setQuestionDraft] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [fileText, setFileText] = useState<string>('');
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [activeTab, setActiveTab] = useState<'document' | 'suggestions'>('document');

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch(`${BACKEND_URL}/health`)
      .then((r) => setBackendOk(r.ok))
      .catch(() => setBackendOk(false));
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleFileDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files[0];
    processFile(f);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null;
    processFile(f);
  };

  const processFile = (f: File | null) => {
    if (f && (f.name.endsWith('.pdf') || f.name.endsWith('.txt'))) {
      setFile(f);
      setMessages([]);
      setQuestionDraft('');
      
      // Attempt to preview text if it's a txt file for the document sidebar
      if (f.name.endsWith('.txt')) {
        const reader = new FileReader();
        reader.onload = (e) => setFileText(e.target?.result as string);
        reader.readAsText(f);
      } else {
        setFileText('PDF Preview not available in this demo. Proceed to query.');
      }
    } else {
      setFile(null);
      setFileText('');
    }
  };

  const runAsk = async (question: string) => {
    if (!file) {
      setError('A target contract must be mounted in the workspace.');
      return;
    }
    if (!question.trim()) return;

    setError(null);
    setIsLoading(true);
    setMessages((m) => [...m, { role: 'user', content: question }]);

    try {
      const formData = new FormData();
      formData.set('file', file);
      formData.set('question', question);

      const resp = await fetch(`${BACKEND_URL}/contracts/`, {
        method: 'POST',
        body: formData,
      });

      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `Request failed with status ${resp.status}`);
      }

      const data = await resp.json();

      if (typeof data === 'string') {
        setMessages((m) => [...m, { role: 'assistant', content: data }]);
      } else {
        setMessages((m) => [
          ...m,
          {
            role: 'assistant',
            content: data.answer,
            agentData: data as AgenticResponse,
          },
        ]);
      }
    } catch (e: unknown) {
      const errMsg = e instanceof Error ? e.message : 'System Error';
      setError(errMsg);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const q = questionDraft;
    setQuestionDraft('');
    runAsk(q);
  };

  const updateMessageStatus = (msgIndex: number, newStatus: AgenticResponse['status']) => {
    setMessages((prev) => {
      const newMessages = [...prev];
      const msg = newMessages[msgIndex];
      if (msg.agentData) {
        msg.agentData = { ...msg.agentData, status: newStatus };
      }
      return newMessages;
    });
  };

  const allCitations = messages
    .filter((m) => m.role === 'assistant' && m.agentData)
    .flatMap((m) => m.agentData?.citations ?? []);

  return (
    <div className="workspace">
      {/* Navbar */}
      <nav className="workspace-nav">
        <div className="nav-left">
          <Link to="/" className="nav-back-btn">
            <ArrowLeft size={16} />
          </Link>
          <div className="nav-divider" />
          <Shield size={18} className="nav-icon" />
          <span className="nav-brand">LexiScan Enterprise</span>
        </div>
        <div className="nav-right">
          <span className={`status-badge ${backendOk ? 'status-ok' : 'status-err'}`}>
            {backendOk ? 'System Operational' : 'System Degraded'}
          </span>
        </div>
      </nav>

      {/* Main Grid Layout */}
      <div className="workspace-grid">
        
        {/* LEFT SIDEBAR: Document Source */}
        <aside className="panel doc-panel">
          <header className="panel-header">
            <div className="panel-title">
              <FileSignature size={16} /> Data Source
            </div>
          </header>
          
          <div className="panel-content">
            <div
              className={`dropzone ${dragOver ? 'dropzone-active' : ''} ${file ? 'dropzone-loaded' : ''}`}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleFileDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <input ref={fileInputRef} type="file" accept=".pdf,.txt" onChange={handleFileSelect} hidden />
              {file ? (
                <div className="file-info">
                  <div className="file-icon"><FileText size={20} /></div>
                  <div className="file-meta">
                    <div className="file-name">{file.name}</div>
                    <div className="file-size">{Math.round(file.size / 1024)} KB Mounted</div>
                  </div>
                  <button className="file-remove" onClick={(e) => { e.stopPropagation(); setFile(null); setFileText(''); }}>
                    <X size={14} />
                  </button>
                </div>
              ) : (
                <div className="dropzone-empty">
                  <Upload size={24} />
                  <span>Mount Target Document</span>
                </div>
              )}
            </div>

            <div className="doc-tabs">
              <button className={`doc-tab ${activeTab === 'document' ? 'active' : ''}`} onClick={() => setActiveTab('document')}>Preview</button>
              <button className={`doc-tab ${activeTab === 'suggestions' ? 'active' : ''}`} onClick={() => setActiveTab('suggestions')}>Queries</button>
            </div>

            <div className="doc-body">
              {activeTab === 'document' && (
                <div className="doc-preview">
                  {fileText ? <pre className="doc-text">{fileText}</pre> : <div className="doc-placeholder">No document mounted for preview.</div>}
                </div>
              )}
              {activeTab === 'suggestions' && (
                <div className="query-suggestions">
                  {SUGGESTED_QUESTIONS.map(q => (
                    <button key={q} className="query-btn" onClick={() => runAsk(q)} disabled={isLoading || !file}>
                      <ChevronRight size={14} /> {q}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </aside>

        {/* CENTER: Orchestration Workflow */}
        <main className="panel orchestrator-panel">
          <header className="panel-header">
            <div className="panel-title">
              <Briefcase size={16} /> LangGraph Orchestrator
            </div>
          </header>

          <div className="orchestrator-canvas">
            {messages.length === 0 && (
              <div className="canvas-empty">
                <Shield size={32} />
                <h3>Awaiting Instructions</h3>
                <p>Deploy the multi-agent orchestration by submitting a query below.</p>
              </div>
            )}

            {messages.map((m, idx) => (
              <div key={idx} className={`workflow-node ${m.role === 'user' ? 'node-user' : 'node-agent'}`}>
                {m.role === 'user' ? (
                  <div className="node-content user-query">
                    <span className="node-label">USER QUERY</span>
                    <p>{m.content}</p>
                  </div>
                ) : (
                  <div className="node-content agent-execution">
                    <div className="execution-header">
                      <span className="node-label">AGENTIC EXECUTION</span>
                      <span className="agent-route">{m.agentData?.source || 'SYSTEM'}</span>
                    </div>
                    
                    {m.agentData && (
                      <div className="reasoning-timeline">
                        {m.agentData.reasoning_steps.map((step, i) => (
                          <div key={i} className="timeline-step">
                            <div className="timeline-dot" />
                            <div className="timeline-text">{step}</div>
                          </div>
                        ))}
                      </div>
                    )}
                    
                    <div className="execution-result">
                      <strong>Final Output:</strong>
                      <p>{m.content}</p>
                    </div>

                    {m.agentData && (
                      <div className="human-loop">
                        <div className="approval-status">
                          <Gavel size={14} /> Human-in-the-Loop: 
                          <span className={`status-pill status-${m.agentData.status.replace(' ', '-').toLowerCase()}`}>
                            {m.agentData.status}
                          </span>
                        </div>
                        {m.agentData.status === 'Pending Review' && (
                          <div className="approval-actions">
                            <button className="btn-approve" onClick={() => updateMessageStatus(idx, 'Approved')}>Approve Draft</button>
                            <button className="btn-reject" onClick={() => updateMessageStatus(idx, 'Rejected')}>Reject</button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}

            {isLoading && (
              <div className="workflow-node node-agent">
                 <div className="node-content agent-execution execution-loading">
                    <Loader2 size={16} className="spin" />
                    <span>Orchestrating multi-agent state graph...</span>
                 </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="orchestrator-input">
            {error && (
              <div className="error-bar">
                <AlertCircle size={14} /> {error}
              </div>
            )}
            <form onSubmit={handleSubmit} className="input-form">
              <input
                type="text"
                value={questionDraft}
                onChange={(e) => setQuestionDraft(e.target.value)}
                placeholder="Instruct the agentic orchestrator..."
                disabled={isLoading}
              />
              <button type="submit" disabled={isLoading || !questionDraft.trim()}>
                {isLoading ? <Loader2 size={16} className="spin" /> : <Send size={16} />}
              </button>
            </form>
          </div>
        </main>

        {/* RIGHT SIDEBAR: Evidence & Citations */}
        <aside className="panel evidence-panel">
          <header className="panel-header">
            <div className="panel-title">
              <BookOpen size={16} /> Audit Trail & Evidence
            </div>
          </header>
          <div className="panel-content">
            {allCitations.length === 0 ? (
              <div className="evidence-empty">
                No evidence retrieved for current workflow.
              </div>
            ) : (
              <div className="citation-list">
                {allCitations.map((c, i) => (
                  <div key={i} className="citation-card">
                    <div className="citation-source">Source: {c.source}</div>
                    {c.location && <div className="citation-loc">{c.location}</div>}
                    <div className="citation-rel">Relevance: High</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
