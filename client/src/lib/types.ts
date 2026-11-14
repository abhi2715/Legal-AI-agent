export type Risk = 'none' | 'low' | 'medium' | 'high';
export type FindingStatus = 'pending' | 'accepted' | 'dismissed' | 'edited' | 'escalated';

export interface EngineStatus {
  online: boolean;
  model: string | null;
  engine: string;
  reason: string | null;
}

export interface Profile {
  id: string;
  name: string;
  role: string;
  expertise: 'plain' | 'professional' | 'expert';
  jurisdiction: string;
  review_policy: 'always' | 'smart' | 'never';
  confidence_threshold: number;
  privacy_redact: number;
  ask_clarifications: number;
  engine?: EngineStatus;
}

export interface Clause {
  id: string;
  index: number;
  title: string;
  text: string;
  start: number;
  end: number;
  page: number;
}

export interface Party {
  alias: string;
  name: string;
}

export interface Finding {
  id: string;
  doc_id: string;
  clause_id: string | null;
  category: string;
  title: string;
  risk: Risk;
  rationale: string;
  suggestion: string;
  source: 'ai' | 'playbook' | 'missing';
  rule_id: string | null;
  status: FindingStatus;
  reviewer_note: string;
  final_suggestion: string | null;
  decided_by: string | null;
  decided_at: string | null;
}

export interface Obligation {
  id: string;
  party: string;
  action: string;
  due: string;
  due_date: string | null;
  recurring: string;
  clause_id: string | null;
  done: number;
}

export interface PlaybookResult {
  rule_id: string;
  status: 'compliant' | 'deviation' | 'missing' | 'unverified' | 'not_applicable';
  clause_ids: string[];
  explanation: string;
  suggested_redline: string;
  title: string;
  requirement: string;
  severity: Risk;
  clause_type: string;
}

export interface TraceEntry {
  node: string;
  message: string;
  engine: string | null;
  at: string;
  actor?: 'human';
}

export interface RunState<V = Record<string, unknown>> {
  values: V & { trace?: TraceEntry[] };
  next: string[];
  interrupt: { id: string | null; value: InterruptValue } | null;
  checkpoint_id: string | null;
  status: 'interrupted' | 'running' | 'done';
  engine: EngineStatus;
}

export type InterruptValue =
  | { type: 'triage'; doc_id: string; pending: number; message: string }
  | { type: 'memo_review'; doc_id: string; memo: string; revisions: number; max_revisions: number }
  | { type: 'clarify'; question: string; options: string[] }
  | {
      type: 'answer_review';
      draft: Draft;
      verification: Verification;
      hits: Hit[];
      gate: Gate;
      revisions: number;
      max_revisions: number;
    };

export interface ThreadSummary {
  id: string;
  question: string;
  status: string;
  answer: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentSummary {
  id: string;
  name: string;
  created_at: string;
  status: string;
  risk_score: number | null;
  risk_level: string | null;
  perspective: string;
  counterparty: string;
  clause_count: number;
  findings: Partial<Record<FindingStatus, number>>;
  threads: number;
  memo_status: string | null;
}

export interface DocumentDetail {
  id: string;
  name: string;
  created_at: string;
  text: string;
  clauses: Clause[];
  defined_terms: Record<string, { definition: string; clause_id: string | null }>;
  parties: Party[];
  perspective: string;
  counterparty: string;
  status: string;
  risk_score: number | null;
  risk_level: string | null;
  summary: string | null;
  memo: string | null;
  memo_status: string | null;
  playbook: PlaybookResult[];
  redactions: Record<string, number>;
  engines: Record<string, string>;
  findings: Finding[];
  obligations: Obligation[];
  threads: ThreadSummary[];
  review: RunState | null;
}

export interface Quote {
  clause_id: string;
  quote: string;
}

export interface Draft {
  answer: string;
  answer_type: 'answered' | 'partially_answered' | 'contract_silent' | 'needs_counsel';
  claims: { statement: string; quotes: Quote[] }[];
  confidence: number;
  caveats: string[];
  follow_up_questions: string[];
}

export interface VerifiedQuote extends Quote {
  verified: boolean;
  match: number;
  start: number | null;
  end: number | null;
  cited_clause_id: string;
  moved?: boolean;
  fuzzy?: boolean;
}

export interface Verification {
  claims: { statement: string; quotes: VerifiedQuote[] }[];
  quotes_total: number;
  quotes_verified: number;
  unsupported_claims: number;
  grounded_ratio: number;
}

export interface Hit {
  clause_id: string;
  title: string;
  score: number;
  reason: string;
}

export interface Gate {
  required: boolean;
  reason: string;
  policy: string;
}

export interface QAValues {
  thread_id: string;
  question: string;
  clarification?: string;
  plan?: { question_type: string; search_queries: string[]; categories: string[] };
  hits?: Hit[];
  pinned?: string[];
  excluded?: string[];
  draft?: Draft;
  verification?: Verification;
  revisions?: number;
  gate?: Gate;
  final?: {
    status: 'approved' | 'edited' | 'rejected' | 'auto_approved';
    answer: string;
    reviewer: string | null;
    diff: { op: 'eq' | 'ins' | 'del'; text: string }[] | null;
    lessons: string[];
  };
  engines?: Record<string, string>;
}

export interface ThreadDetail extends ThreadSummary {
  run: RunState<QAValues>;
}

export interface Checkpoint {
  checkpoint_id: string;
  created_at: string;
  next: string;
  label: string;
  revision: number;
  question: string;
  has_draft: boolean;
}

export interface Rule {
  id: string;
  clause_type: string;
  title: string;
  requirement: string;
  severity: 'low' | 'medium' | 'high';
  enabled: number;
}

export interface Memory {
  id: string;
  kind: 'dismissal' | 'style' | 'correction' | 'instruction';
  scope: string;
  content: string;
  source_ref: string;
  active: number;
  uses: number;
  created_at: string;
}

export interface AuditEntry {
  id: string;
  doc_id: string | null;
  thread_id: string | null;
  actor: string;
  action: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface Insights {
  answers: Record<string, number>;
  answer_acceptance: number | null;
  findings: Record<string, number>;
  false_positive_rate: number | null;
  memories_active: number;
  memory_applications: number;
}
