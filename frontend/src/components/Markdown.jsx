// Renders the small subset of markdown language models actually produce:
// headings, **bold**, *italic*, `code`, bullet and numbered lists, pipe tables,
// rules. It builds React elements only (no innerHTML), so model output cannot
// inject markup.

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;

function inline(text, keyPrefix) {
  return text.split(INLINE).map((part, i) => {
    const key = `${keyPrefix}-${i}`;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={key} className="text-term-text">{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) return <code key={key} className="px-1 rounded bg-term-bg text-term-amber">{part.slice(1, -1)}</code>;
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) return <em key={key}>{part.slice(1, -1)}</em>;
    return part;
  });
}

const isTableRow = (l) => /^\s*\|.*\|\s*$/.test(l);
const isTableRule = (l) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l);
const cells = (l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

export function parseBlocks(source) {
  const lines = String(source ?? "").replace(/\r/g, "").split("\n");
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }

    if (isTableRow(line) && i + 1 < lines.length && isTableRule(lines[i + 1])) {
      const head = cells(line);
      const rows = [];
      i += 2;
      while (i < lines.length && isTableRow(lines[i])) rows.push(cells(lines[i++]));
      blocks.push({ type: "table", head, rows });
      continue;
    }
    const heading = line.match(/^\s{0,3}(#{1,4})\s+(.*)$/);
    if (heading) { blocks.push({ type: "heading", text: heading[2].replace(/\*\*/g, "") }); i++; continue; }
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { blocks.push({ type: "rule" }); i++; continue; }

    const bullet = /^\s*[-*•]\s+/;
    const numbered = /^\s*\d+[.)]\s+/;
    if (bullet.test(line) || numbered.test(line)) {
      const ordered = numbered.test(line);
      const re = ordered ? numbered : bullet;
      const items = [];
      while (i < lines.length && re.test(lines[i])) {
        let text = lines[i].replace(re, "");
        i++;
        while (i < lines.length && lines[i].trim() && !bullet.test(lines[i]) && !numbered.test(lines[i]) && !isTableRow(lines[i]) && /^\s{2,}/.test(lines[i])) text += " " + lines[i++].trim();
        items.push(text);
      }
      blocks.push({ type: ordered ? "ol" : "ul", items });
      continue;
    }

    const para = [];
    while (i < lines.length && lines[i].trim() && !isTableRow(lines[i]) && !/^\s{0,3}#{1,4}\s/.test(lines[i]) && !bullet.test(lines[i]) && !numbered.test(lines[i])) para.push(lines[i++].trim());
    blocks.push({ type: "p", text: para.join(" ") });
  }
  return blocks;
}

export default function Markdown({ text }) {
  const blocks = parseBlocks(text);
  return (
    <div className="space-y-2 leading-relaxed">
      {blocks.map((b, i) => {
        const k = `b${i}`;
        switch (b.type) {
          case "heading": return <div key={k} className="font-bold text-term-green">{inline(b.text, k)}</div>;
          case "rule": return <hr key={k} className="border-term-border" />;
          case "ul": return <ul key={k} className="list-disc pl-5 space-y-1">{b.items.map((t, j) => <li key={j}>{inline(t, `${k}-${j}`)}</li>)}</ul>;
          case "ol": return <ol key={k} className="list-decimal pl-5 space-y-1">{b.items.map((t, j) => <li key={j}>{inline(t, `${k}-${j}`)}</li>)}</ol>;
          case "table": return (
            <div key={k} className="overflow-x-auto">
              <table className="border-collapse text-left">
                <thead><tr>{b.head.map((h, j) => <th key={j} className="border border-term-border px-2 py-1 text-term-green">{inline(h, `${k}h${j}`)}</th>)}</tr></thead>
                <tbody>{b.rows.map((r, j) => <tr key={j}>{r.map((c, m) => <td key={m} className="border border-term-border px-2 py-1 align-top">{inline(c, `${k}-${j}-${m}`)}</td>)}</tr>)}</tbody>
              </table>
            </div>
          );
          default: return <p key={k}>{inline(b.text, k)}</p>;
        }
      })}
    </div>
  );
}
