import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Search } from 'lucide-react';
import type { Clause, DocumentDetail, Risk } from '../lib/types';

export interface Focus {
  clauseId: string;
  start?: number | null;
  end?: number | null;
  quote?: string;
  nonce: number;
}

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

type Range = [number, number];

function mergeRanges(ranges: Range[]): Range[] {
  const sorted = [...ranges].sort((a, b) => a[0] - b[0]);
  const out: Range[] = [];
  for (const r of sorted) {
    const last = out[out.length - 1];
    if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
    else out.push([...r] as Range);
  }
  return out;
}

export default function DocumentViewer({
  doc,
  focus,
  riskByClause,
}: {
  doc: DocumentDetail;
  focus: Focus | null;
  riskByClause: Record<string, Risk>;
}) {
  const [query, setQuery] = useState('');
  const [matchIdx, setMatchIdx] = useState(0);
  const refs = useRef<Record<string, HTMLDivElement | null>>({});

  const terms = doc.defined_terms;
  const termRe = useMemo(() => {
    const names = Object.keys(terms).sort((a, b) => b.length - a.length);
    return names.length ? new RegExp(`\\b(${names.map(escapeRe).join('|')})\\b`, 'g') : null;
  }, [terms]);

  const searchMatches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q.length < 2) return [] as { clauseId: string; range: Range }[];
    const out: { clauseId: string; range: Range }[] = [];
    for (const c of doc.clauses) {
      const low = c.text.toLowerCase();
      let i = low.indexOf(q);
      while (i !== -1) {
        out.push({ clauseId: c.id, range: [i, i + q.length] });
        i = low.indexOf(q, i + q.length);
      }
    }
    return out;
  }, [query, doc.clauses]);

  useEffect(() => {
    if (!focus) return;
    refs.current[focus.clauseId]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [focus]);

  useEffect(() => {
    const m = searchMatches[matchIdx];
    if (m) refs.current[m.clauseId]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [matchIdx, searchMatches]);

  const withTerms = (text: string, key: string): ReactNode[] => {
    if (!termRe) return [text];
    const out: ReactNode[] = [];
    let last = 0;
    let i = 0;
    for (const m of text.matchAll(termRe)) {
      const idx = m.index ?? 0;
      if (idx > last) out.push(text.slice(last, idx));
      const def = terms[m[0]];
      out.push(
        <span key={`${key}-t${i++}`} className="term" tabIndex={0}>
          {m[0]}
          <span className="term-tip" role="tooltip">
            <b>{m[0]}</b>: {def?.definition}
          </span>
        </span>,
      );
      last = idx + m[0].length;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  };

  const rangesFor = (c: Clause): Range[] => {
    const ranges: Range[] = searchMatches.filter((m) => m.clauseId === c.id).map((m) => m.range);
    if (focus && focus.clauseId === c.id) {
      if (focus.start != null && focus.end != null && focus.start >= c.start && focus.end <= c.end) {
        ranges.push([focus.start - c.start, focus.end - c.start]);
      } else if (focus.quote) {
        const q = focus.quote.replace(/^["“]|["”]$/g, '').trim().toLowerCase();
        const idx = q ? c.text.toLowerCase().indexOf(q) : -1;
        if (idx !== -1) ranges.push([idx, idx + q.length]);
      }
    }
    return mergeRanges(ranges);
  };

  const renderClause = (c: Clause) => {
    const ranges = rangesFor(c);
    const parts: ReactNode[] = [];
    let last = 0;
    ranges.forEach(([s, e], i) => {
      if (s > last) parts.push(...withTerms(c.text.slice(last, s), `${c.id}-${i}a`));
      parts.push(<mark key={`${c.id}-m${i}`}>{c.text.slice(s, e)}</mark>);
      last = e;
    });
    if (last < c.text.length) parts.push(...withTerms(c.text.slice(last), `${c.id}-end`));
    return parts;
  };

  return (
    <section className="viewer" aria-label="Contract text">
      <div className="viewer-bar">
        <Search size={14} className="faint" />
        <input
          className="input"
          placeholder="Find in contract…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setMatchIdx(0);
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && searchMatches.length) setMatchIdx((i) => (i + (e.shiftKey ? -1 : 1) + searchMatches.length) % searchMatches.length);
          }}
        />
        {query.trim().length >= 2 && (
          <span className="tiny faint">
            {searchMatches.length ? `${matchIdx + 1}/${searchMatches.length}` : 'No matches'}
          </span>
        )}
        <span className="grow" />
        <span className="tiny faint">
          {doc.clauses.length} clauses · {Object.keys(terms).length} defined terms
        </span>
      </div>
      <div className="viewer-scroll">
        <article className="paper">
          {doc.clauses.map((c) => {
            const risk = riskByClause[c.id];
            return (
              <div
                key={c.id}
                id={`clause-${c.id}`}
                ref={(el) => {
                  refs.current[c.id] = el;
                }}
                className={`clause ${risk && risk !== 'none' ? `risk-${risk}` : ''} ${focus?.clauseId === c.id ? 'active' : ''}`}
              >
                <span className="clause-tag" aria-hidden>
                  {c.id}
                </span>
                {renderClause(c)}
              </div>
            );
          })}
        </article>
      </div>
    </section>
  );
}
