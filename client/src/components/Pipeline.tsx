import { Check, Circle, Gavel, Loader2 } from 'lucide-react';
import type { TraceEntry } from '../lib/types';

export interface StepDef {
  node: string;
  label: string;
  human?: boolean;
}

export default function Pipeline({
  steps,
  trace,
  running,
  waitingOn,
  engines,
}: {
  steps: StepDef[];
  trace: TraceEntry[];
  running: boolean;
  waitingOn?: string | null;
  engines?: Record<string, string>;
}) {
  const lastByNode: Record<string, TraceEntry> = {};
  for (const t of trace) lastByNode[t.node] = t;
  const doneIdx = steps.reduce((acc, s, i) => (lastByNode[s.node] ? i : acc), -1);

  return (
    <div className="pipeline">
      {steps.map((s, i) => {
        const entry = lastByNode[s.node];
        const isWaiting = waitingOn === s.node;
        const state = isWaiting ? 'human' : entry ? 'done' : running && i === doneIdx + 1 ? 'active' : i < doneIdx ? 'skipped' : 'todo';
        const engine = engines?.[s.node] ?? entry?.engine;
        return (
          <div key={s.node} className={`pipe-step ${state}`} style={state === 'skipped' ? { opacity: 0.5 } : undefined}>
            <div className="pipe-dot">
              {state === 'done' ? (
                <Check size={12} />
              ) : state === 'active' ? (
                <Loader2 size={12} className="spin" />
              ) : state === 'human' || s.human ? (
                <Gavel size={11} />
              ) : (
                <Circle size={8} />
              )}
            </div>
            <div>
              <div className="pipe-name">
                {s.label}
                {engine && <span className="engine-tag">{engine}</span>}
                {isWaiting && (
                  <span className="badge badge-human" style={{ marginLeft: 8 }}>
                    Waiting for you
                  </span>
                )}
              </div>
              {entry && <div className="pipe-msg">{entry.message}</div>}
              {state === 'skipped' && <div className="pipe-msg faint">Not needed for this run</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
