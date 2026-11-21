import { useEffect, useState } from "react";
import { ancestors, children, displayName } from "./model.js";

const KIND_LABEL = { group: "package", file: "file", class: "class", function: "function", script: "top-level code", endpoint: "API endpoint", table: "table" };
const EDGE_OUT = { calls: "Calls", instantiates: "Creates", imports: "Imports", inherits: "Inherits from", routes: "Handled by", reads: "Reads table", writes: "Writes table" };
const EDGE_IN = { calls: "Called by", instantiates: "Created by", imports: "Imported by", inherits: "Subclassed by", routes: "Endpoint", reads: "Read by", writes: "Written by" };
const MAX_SOURCE_LINES = 160;

function Certainty({ c }) {
  return <span className={`cert cert-${c}`} title={`certainty: ${c}`} />;
}

function EdgeList({ ix, items, labels, side, onSelect }) {
  const groups = new Map();
  for (const e of items) {
    const key = labels[e.kind] || e.kind;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(e);
  }
  if (!groups.size) return null;
  return [...groups.entries()].map(([label, es]) => (
    <section key={label}>
      <h4>
        {label} <small>{es.length}</small>
      </h4>
      <ul className="links">
        {es.slice(0, 60).map((e) => {
          const other = ix.byId.get(side === "out" ? e.target : e.source);
          return (
            <li key={`${e.source}>${e.target}>${e.kind}`}>
              <Certainty c={e.certainty} />
              <button type="button" className="linkish" onClick={() => onSelect(other.id, { zoom: true })}>
                {displayName(ix, other)}
              </button>
              {e.count > 1 && <small> ×{e.count}</small>}
            </li>
          );
        })}
      </ul>
    </section>
  ));
}

function Source({ n, version }) {
  const [lines, setLines] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    if (!n.file) return undefined;
    let live = true;
    setLines(null);
    setError(null);
    fetch(`api/source?file=${encodeURIComponent(n.file)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then((d) => live && setLines(d.lines))
      .catch((e) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [n.file, version]);
  if (!n.file) return null;
  if (error) return <p className="muted">Source not available ({error}).</p>;
  if (!lines) return <p className="muted">Loading source…</p>;
  const start = n.kind === "file" || !n.line ? 1 : n.line;
  const end = n.kind === "file" ? Math.min(lines.length, MAX_SOURCE_LINES) : Math.min(n.end_line || start, start + MAX_SOURCE_LINES - 1);
  const shown = lines.slice(start - 1, end);
  return (
    <pre className="source">
      {shown.map((text, i) => (
        <div key={start + i}>
          <span className="ln">{start + i}</span>
          {text || " "}
        </div>
      ))}
      {end < (n.kind === "file" ? lines.length : n.end_line || 0) && <div className="muted">… {(n.kind === "file" ? lines.length : n.end_line) - end} more lines</div>}
    </pre>
  );
}

export default function Panel({ ix, sel, repo, version, lens, onSelect, onZoom, summary }) {
  const n = sel ? ix.byId.get(sel) : null;
  if (!n) return <aside className="panel">{summary}</aside>;

  const path = ancestors(ix, n.id).map((id) => ix.byId.get(id));
  const out = ix.out.get(n.id) || [];
  const inn = ix.inn.get(n.id) || [];
  const kids = children(ix, n.id);
  const kidCounts = kids.reduce((m, k) => ((m[k.kind] = (m[k.kind] || 0) + 1), m), {});
  const vscode = n.file && repo ? `vscode://file${repo}/${n.file}${n.line ? `:${n.line}` : ""}` : null;
  const tested = n.kind === "function" && !n.attrs?.is_test ? (ix.testedDirect.has(n.id) ? "called by a test" : ix.testedReach.has(n.id) ? "reached by tests indirectly" : "not reached by any test") : null;

  return (
    <aside className="panel">
      <nav className="crumbs">
        {path.map((p) => (
          <button type="button" key={p.id} className="linkish" onClick={() => onSelect(p.id, { zoom: true })}>
            {p.name}
          </button>
        ))}
      </nav>
      <h2>
        {n.kind === "function" ? displayName(ix, n) : n.name} <span className="kind">{KIND_LABEL[n.kind] || n.kind}</span>
      </h2>
      <div className="actions">
        <button type="button" onClick={() => onZoom(n.id)}>
          Zoom to
        </button>
        {vscode && (
          <a className="button" href={vscode}>
            Open in VS Code
          </a>
        )}
        <button type="button" onClick={() => onSelect(null)}>
          Clear
        </button>
      </div>
      {n.file && (
        <p className="muted">
          {n.file}
          {n.line ? `:${n.line}${n.end_line && n.end_line !== n.line ? `–${n.end_line}` : ""}` : ""}
        </p>
      )}
      {n.attrs?.error && <p className="warn">{n.attrs.error}</p>}
      {n.kind === "function" && (
        <code className="sig">
          {n.attrs.is_async ? "async " : ""}
          {n.name}({(n.attrs.params || []).map((p) => (p.ann ? `${p.name}: ${p.ann}` : p.name)).join(", ")}){n.attrs.returns ? ` -> ${n.attrs.returns}` : ""}
        </code>
      )}
      {n.attrs?.decorators?.length > 0 && <p className="muted">@{n.attrs.decorators.join("  @")}</p>}
      {n.attrs?.doc && <p className="doc">{n.attrs.doc}</p>}
      {tested && <p className={`tested ${lens === "tests" ? "strong" : ""}`}>Tests: {tested}</p>}
      {kids.length > 0 && (
        <p className="muted">
          Contains{" "}
          {Object.entries(kidCounts)
            .map(([k, c]) => `${c} ${KIND_LABEL[k] || k}${c > 1 ? "s" : ""}`)
            .join(", ")}
        </p>
      )}
      <EdgeList ix={ix} items={out} labels={EDGE_OUT} side="out" onSelect={onSelect} />
      <EdgeList ix={ix} items={inn} labels={EDGE_IN} side="in" onSelect={onSelect} />
      {n.kind !== "group" && n.kind !== "table" && n.kind !== "endpoint" && <Source n={n} version={version} />}
    </aside>
  );
}
