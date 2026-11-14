import { Link } from 'react-router-dom';
import {
  ArrowRight,
  BadgeCheck,
  BookCheck,
  Brain,
  CalendarPlus,
  Check,
  CircleSlash,
  EyeOff,
  GitBranch,
  Gavel,
  HelpCircle,
  History,
  Pencil,
  Scale,
  SlidersHorizontal,
  X,
} from 'lucide-react';
import ThemeToggle from '../components/ThemeToggle';

const FEATURES = [
  { icon: Gavel, human: true, title: 'Real approval gates', body: 'The workflow stops at checkpoints and waits for you, for minutes or days. Nothing reaches a memo or a final answer without your decision.' },
  { icon: BadgeCheck, title: 'Quotes that are checked', body: 'Every claim must quote the contract, and each quote is matched against the source text. Unverifiable quotes are flagged red and force a review.' },
  { icon: Brain, human: true, title: 'Learns from your corrections', body: 'Dismissals, edited redlines and rejected answers become plain-language preferences that you can read, edit or switch off.' },
  { icon: BookCheck, title: 'Your playbook, enforced', body: 'Encode your standards once. Each review checks for deviations and for protections that are missing entirely.' },
  { icon: Scale, title: 'Perspective-aware risk', body: 'Choose which party you represent. The same clause can be a risk or a protection depending on your side.' },
  { icon: GitBranch, human: true, title: 'Time travel', body: 'Rewind any answer to an earlier step, change the question or the evidence, and branch. Every step is checkpointed.' },
  { icon: SlidersHorizontal, human: true, title: 'An autonomy dial you control', body: 'Review everything, review only uncertain answers, or trust the assistant with a safety floor that cannot be turned off.' },
  { icon: EyeOff, title: 'Redaction before analysis', body: 'Emails, phone numbers, addresses and account numbers are replaced with placeholders before text reaches the model.' },
  { icon: CalendarPlus, title: 'Deadlines in your calendar', body: 'Obligations are extracted per party, and you can export your own deadlines as a calendar file with reminders.' },
];

const FLOW = [
  { t: 'Choose your side', d: 'Tell it which party you represent.' },
  { t: 'Parallel analysis', d: 'Clauses, playbook and obligations are analyzed at the same time.' },
  { t: 'You triage', d: 'Accept, edit, dismiss or escalate each finding.', human: true },
  { t: 'Memo drafted', d: 'Built only from findings you kept.' },
  { t: 'You approve', d: 'Approve, edit, or send it back with notes.', human: true },
];

export default function Landing() {
  return (
    <div className="landing">
      <nav className="l-nav">
        <Link to="/" className="brand" style={{ padding: 0 }}>
          <span className="brand-mark">
            <Scale size={16} />
          </span>
          LexiScan
        </Link>
        <div className="row">
          <ThemeToggle />
          <Link to="/app" className="btn btn-primary btn-sm">
            Open app <ArrowRight size={14} />
          </Link>
        </div>
      </nav>

      <div className="l-wrap">
        <section className="hero">
          <div>
            <span className="badge badge-human" style={{ marginBottom: 18 }}>
              <Gavel size={12} /> Human-in-the-loop contract review
            </span>
            <h1>
              The AI drafts.
              <br />
              <em>You decide.</em>
            </h1>
            <p className="lead">
              LexiScan reviews contracts from your side of the deal, checks them against your own playbook, and stops for your judgement at every
              point that matters. It also learns from each correction you make.
            </p>
            <div className="row row-wrap">
              <Link to="/app" className="btn btn-primary btn-lg">
                Review a contract <ArrowRight size={16} />
              </Link>
              <a href="#how" className="btn btn-lg">
                How it works
              </a>
            </div>
          </div>

          <div className="card hero-art stack" aria-hidden>
            <div className="row spread">
              <span className="human-label">
                <Gavel size={13} /> Your decision needed
              </span>
              <span className="tiny faint">3 of 7 decided</span>
            </div>
            <div className="progress">
              <div style={{ width: '43%', background: 'var(--human)' }} />
            </div>
            <div className="finding stack stack-sm selected">
              <div className="row" style={{ gap: 6 }}>
                <span className="badge badge-high">High risk</span>
                <span className="badge badge-outline">Playbook</span>
                <span className="tiny mono faint">c9</span>
              </div>
              <h4>Indemnities are one-sided</h4>
              <p>You indemnify for “any and all” losses; the other party gives no indemnity in return.</p>
              <div className="redline">Each party shall indemnify the other against third-party claims caused by its breach.</div>
              <div className="row">
                <span className="btn btn-ok btn-sm">
                  <Check size={13} /> Accept
                </span>
                <span className="btn btn-sm">
                  <Pencil size={13} /> Edit
                </span>
                <span className="btn btn-sm">
                  <X size={13} /> Dismiss
                </span>
              </div>
            </div>
            <div className="finding stack stack-sm decided">
              <div className="row" style={{ gap: 6 }}>
                <span className="badge badge-medium">Medium risk</span>
                <span className="badge badge-outline">Missing clause</span>
              </div>
              <h4>
                <CircleSlash size={13} style={{ verticalAlign: -2 }} /> No limitation of liability
              </h4>
            </div>
            <div className="quote">
              <BadgeCheck size={14} className="ok-icon" />
              <span>“…upon thirty (30) days written notice to the other Party.”</span>
            </div>
          </div>
        </section>

        <section className="l-section" id="how">
          <h2>A review you supervise</h2>
          <p className="muted">Built as a LangGraph state machine with persistent checkpoints. Each pause is a real interrupt, not a confirmation dialog.</p>
          <div className="flow">
            {FLOW.map((s, i) => (
              <div key={s.t} className={`card flow-step ${s.human ? 'human' : ''}`}>
                <span className="tiny faint">Step {i + 1}</span>
                <b>{s.t}</b>
                <span className="muted">{s.d}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="l-section">
          <h2>Built for the parts other tools skip</h2>
          <p className="muted">Grounding, accountability and your own standards are part of the core workflow.</p>
          <div className="feature-grid">
            {FEATURES.map(({ icon: Icon, title, body, human }) => (
              <div key={title} className="card feature">
                <div className={`feature-icon ${human ? 'human' : ''}`}>
                  <Icon size={18} />
                </div>
                <h3>{title}</h3>
                <p>{body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="l-section">
          <div className="row row-wrap spread">
            <div>
              <h2>Accountable by default</h2>
              <p className="muted" style={{ maxWidth: 560 }}>
                Every AI action and every human decision is written to an audit trail you can export, so you can show who approved what, when,
                and on which evidence.
              </p>
            </div>
            <div className="row row-wrap">
              <span className="badge badge-accent">
                <History size={11} /> Audit trail
              </span>
              <span className="badge badge-human">
                <HelpCircle size={11} /> Asks before guessing
              </span>
              <span className="badge badge-ok">
                <BadgeCheck size={11} /> Verified citations
              </span>
            </div>
          </div>
        </section>

        <footer className="l-foot">
          LexiScan assists qualified reviewers. It is not legal advice and does not replace a lawyer's judgement.
        </footer>
      </div>
    </div>
  );
}
