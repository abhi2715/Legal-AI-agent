import { useState, type ReactNode } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { BookCheck, Brain, FileText, History, Menu, Scale, Settings, ServerCrash } from 'lucide-react';
import ThemeToggle from '../../components/ThemeToggle';
import { useApp } from '../../lib/app-context';
import { backendUrl } from '../../lib/api';

const NAV = [
  { to: '/app', icon: FileText, label: 'Contracts', end: true },
  { to: '/app/playbook', icon: BookCheck, label: 'My playbook' },
  { to: '/app/memory', icon: Brain, label: 'What it learned' },
  { to: '/app/audit', icon: History, label: 'Audit trail' },
  { to: '/app/settings', icon: Settings, label: 'Settings' },
];

export default function Shell({ children }: { children: ReactNode }) {
  const { profile, engine, serverDown, refreshProfile } = useApp();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const isWorkspace = location.pathname.startsWith('/app/doc/');

  return (
    <div className="shell">
      <div className="mobile-bar">
        <button className="btn btn-ghost btn-icon" onClick={() => setOpen(true)} aria-label="Open menu">
          <Menu size={18} />
        </button>
        <Link to="/app" className="brand" style={{ padding: 0 }}>
          <span className="brand-mark">
            <Scale size={16} />
          </span>
          LexiScan
        </Link>
      </div>
      <aside className={`sidebar ${open ? 'open' : ''}`} onClick={() => setOpen(false)}>
        <Link to="/" className="brand">
          <span className="brand-mark">
            <Scale size={16} />
          </span>
          LexiScan
        </Link>
        {NAV.map(({ to, icon: Icon, label, end }) => (
          <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
        <div className="sidebar-foot" onClick={(e) => e.stopPropagation()}>
          {engine && (
            <div className="engine-pill" title={engine.reason ?? 'Model connected'}>
              <span className={`engine-dot ${engine.online ? '' : 'off'}`} />
              <span className="truncate">{engine.online ? engine.model : 'Offline heuristics'}</span>
            </div>
          )}
          {profile && (
            <Link to="/app/settings" className="small muted truncate" style={{ padding: '0 4px' }}>
              Signed decisions as <b>{profile.name}</b>
            </Link>
          )}
          <ThemeToggle />
        </div>
      </aside>
      <main className="main" style={isWorkspace ? { overflow: 'hidden' } : undefined}>
        {serverDown ? (
          <div className="page">
            <div className="alert alert-error">
              <ServerCrash size={18} />
              <div className="grow">
                <b>Cannot reach the LexiScan API at {backendUrl}.</b>
                <div className="small">
                  Start it with <code>uvicorn main:app --port 5001</code> in <code>server/</code>, then retry.
                </div>
              </div>
              <button className="btn btn-sm" onClick={refreshProfile}>
                Retry
              </button>
            </div>
          </div>
        ) : (
          children
        )}
      </main>
    </div>
  );
}
