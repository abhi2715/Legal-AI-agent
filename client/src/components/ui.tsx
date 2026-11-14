import { Loader2 } from 'lucide-react';
import type { ReactNode } from 'react';
import type { Risk } from '../lib/types';

export function RiskBadge({ risk }: { risk: Risk | string }) {
  const cls = risk === 'high' ? 'badge-high' : risk === 'medium' ? 'badge-medium' : risk === 'low' ? 'badge-low' : '';
  return <span className={`badge ${cls}`}>{risk === 'none' ? 'Info' : `${risk[0].toUpperCase()}${risk.slice(1)} risk`}</span>;
}

export function Switch({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return <button role="switch" aria-checked={on} aria-label={label} className={`switch ${on ? 'on' : ''}`} onClick={() => onChange(!on)} />;
}

export function Spinner({ size = 16 }: { size?: number }) {
  return <Loader2 size={size} className="spin" />;
}

export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      {icon}
      <h3>{title}</h3>
      {children && <div className="small">{children}</div>}
    </div>
  );
}

export function Gauge({ score, level }: { score: number; level: string | null }) {
  const color = score >= 60 ? 'var(--high)' : score >= 30 ? 'var(--medium)' : 'var(--ok)';
  return (
    <div className="gauge">
      <div className="gauge-ring" style={{ ['--p' as string]: score, ['--c' as string]: color }}>
        <span>{score}</span>
      </div>
      <div>
        <div className="section-title">Risk score</div>
        <div style={{ fontWeight: 600, color }}>{level ?? '—'} risk</div>
        <div className="tiny faint">Open findings, weighted by severity</div>
      </div>
    </div>
  );
}

export function Confidence({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = value >= 0.8 ? 'var(--ok)' : value >= 0.6 ? 'var(--medium)' : 'var(--high)';
  return (
    <span className="meter" title="Model-reported confidence, checked against your threshold">
      <span className="progress">
        <div style={{ width: `${pct}%`, background: color }} />
      </span>
      <span style={{ color }}>{pct}% confident</span>
    </span>
  );
}
