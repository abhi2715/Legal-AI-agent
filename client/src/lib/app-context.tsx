import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { api } from './api';
import type { EngineStatus, Profile } from './types';

interface Toast {
  id: number;
  text: string;
  kind: 'info' | 'error';
}

interface AppContextValue {
  profile: Profile | null;
  engine: EngineStatus | null;
  serverDown: boolean;
  refreshProfile: () => Promise<void>;
  updateProfile: (patch: Partial<Profile>) => Promise<void>;
  toast: (text: string, kind?: 'info' | 'error') => void;
}

const Ctx = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [serverDown, setServerDown] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const toast = useCallback((text: string, kind: 'info' | 'error' = 'info') => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === 'error' ? 6000 : 3200);
  }, []);

  const refreshProfile = useCallback(async () => {
    try {
      setProfile(await api<Profile>('/me'));
      setServerDown(false);
    } catch {
      setServerDown(true);
    }
  }, []);

  const updateProfile = useCallback(
    async (patch: Partial<Profile>) => {
      try {
        const body: Record<string, unknown> = { ...patch };
        for (const k of ['privacy_redact', 'ask_clarifications'] as const) {
          if (k in body) body[k] = Boolean(body[k]);
        }
        const updated = await api<Profile>('/me', { method: 'PATCH', body });
        setProfile((p) => ({ ...updated, engine: p?.engine }));
      } catch (e) {
        toast((e as Error).message, 'error');
      }
    },
    [toast],
  );

  useEffect(() => {
    refreshProfile();
  }, [refreshProfile]);

  return (
    <Ctx.Provider value={{ profile, engine: profile?.engine ?? null, serverDown, refreshProfile, updateProfile, toast }}>
      {children}
      <div className="toast-wrap" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind === 'error' ? 'error' : ''}`}>
            {t.text}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useApp() {
  const v = useContext(Ctx);
  if (!v) throw new Error('useApp outside AppProvider');
  return v;
}
