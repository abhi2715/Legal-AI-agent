export function timeAgo(iso: string): string {
  const then = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`).getTime();
  const s = Math.max(0, (Date.now() - then) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)}d ago`;
  return new Date(then).toLocaleDateString();
}

export function formatDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

export function daysUntil(iso: string): number {
  const d = new Date(`${iso}T00:00:00`).getTime();
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((d - today.getTime()) / 86400000);
}

export const pretty = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());

export const STATUS_LABEL: Record<string, string> = {
  uploaded: 'Not reviewed',
  analyzing: 'Analyzing',
  awaiting_triage: 'Needs your triage',
  drafting_memo: 'Drafting memo',
  awaiting_memo_approval: 'Memo awaiting approval',
  reviewed: 'Reviewed',
  running: 'Running',
  awaiting_clarification: 'Needs clarification',
  awaiting_review: 'Needs your review',
  approved: 'Approved',
  edited: 'Approved with edits',
  rejected: 'Rejected',
  auto_approved: 'Auto-approved',
};
