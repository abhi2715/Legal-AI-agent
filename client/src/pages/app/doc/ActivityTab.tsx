import { useEffect, useState } from 'react';
import { History } from 'lucide-react';
import { api } from '../../../lib/api';
import { timeAgo } from '../../../lib/format';
import type { AuditEntry } from '../../../lib/types';
import { Empty, Spinner } from '../../../components/ui';
import { describe } from '../Audit';

export default function ActivityTab({ docId, version }: { docId: string; version: number }) {
  const [items, setItems] = useState<AuditEntry[] | null>(null);
  useEffect(() => {
    api<AuditEntry[]>(`/audit?doc_id=${docId}`).then(setItems).catch(() => setItems([]));
  }, [docId, version]);
  if (!items) return <Spinner />;
  if (!items.length) return <Empty icon={<History size={26} />} title="No activity yet" />;
  return (
    <div className="timeline">
      {items.map((a) => (
        <div key={a.id} className="tl-item">
          <span className={`tl-dot ${a.actor.startsWith('human') ? 'human' : 'ai'}`} />
          <div>
            <div>
              <b>{a.actor.startsWith('human:') ? a.actor.slice(6) : 'Assistant'}</b> {describe(a)}
            </div>
          </div>
          <span className="tiny faint" title={a.created_at}>
            {timeAgo(a.created_at)}
          </span>
        </div>
      ))}
    </div>
  );
}
