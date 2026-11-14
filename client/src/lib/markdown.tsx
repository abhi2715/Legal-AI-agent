import { Fragment, type ReactNode } from 'react';

/** Minimal, safe Markdown renderer (no HTML injection): headings, lists, bold, italics, code, quotes. */
function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|_[^_]+_|\*[^*]+\*|`[^`]+`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const key = `${keyBase}-${i++}`;
    if (tok.startsWith('**')) out.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith('`')) out.push(<code key={key}>{tok.slice(1, -1)}</code>);
    else out.push(<em key={key}>{tok.slice(1, -1)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ text, className }: { text: string; className?: string }) {
  const lines = text.replace(/\r/g, '').split('\n');
  const blocks: ReactNode[] = [];
  let list: { ordered: boolean; items: { text: string; sub: string[] }[] } | null = null;
  let para: string[] = [];

  const flushPara = () => {
    if (para.length) {
      const k = `p${blocks.length}`;
      blocks.push(<p key={k}>{inline(para.join(' '), k)}</p>);
      para = [];
    }
  };
  const flushList = () => {
    if (list) {
      const k = `l${blocks.length}`;
      const items = list.items.map((it, i) => (
        <li key={i}>
          {inline(it.text, `${k}-${i}`)}
          {it.sub.length > 0 && (
            <ul>
              {it.sub.map((sub, j) => (
                <li key={j}>{inline(sub, `${k}-${i}-${j}`)}</li>
              ))}
            </ul>
          )}
        </li>
      ));
      blocks.push(list.ordered ? <ol key={k}>{items}</ol> : <ul key={k}>{items}</ul>);
      list = null;
    }
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    const ul = /^\s*[-*•]\s+(.*)$/.exec(line);
    const ol = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    const quote = /^>\s?(.*)$/.exec(line);
    if (!line.trim()) {
      flushPara();
      flushList();
    } else if (h) {
      flushPara();
      flushList();
      const level = Math.min(4, h[1].length + 1);
      const k = `h${blocks.length}`;
      const Tag = `h${level}` as 'h2' | 'h3' | 'h4' | 'h5';
      blocks.push(<Tag key={k}>{inline(h[2], k)}</Tag>);
    } else if (ul && list && /^\s{2,}/.test(raw)) {
      list.items[list.items.length - 1].sub.push(ul[1]);
    } else if (ul || ol) {
      flushPara();
      const ordered = Boolean(ol);
      if (!list || list.ordered !== ordered) {
        flushList();
        list = { ordered, items: [] };
      }
      list.items.push({ text: (ul ?? ol)![1], sub: [] });
    } else if (quote) {
      flushPara();
      flushList();
      const k = `q${blocks.length}`;
      blocks.push(<blockquote key={k}>{inline(quote[1], k)}</blockquote>);
    } else if (list && /^\s{2,}/.test(raw)) {
      list.items[list.items.length - 1].text += ` ${line.trim()}`;
    } else {
      flushList();
      para.push(line.trim());
    }
  }
  flushPara();
  flushList();
  return <div className={`md ${className ?? ''}`}>{blocks.map((b, i) => <Fragment key={i}>{b}</Fragment>)}</div>;
}
