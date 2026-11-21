import { useEffect, useState } from "react";
import { badge, describe } from "./MapView.jsx";
import { displayName } from "./model.js";
import { treeAncestors } from "./tree.js";

const KIND_LABEL = {
  root: "project",
  folder: "folder",
  database: "database",
  file: "file",
  class: "class",
  function: "function",
  script: "top-level code",
  endpoint: "API endpoint",
  table: "table",
};
const EDGE_OUT = { calls: "Calls", instantiates: "Creates", imports: "Imports", inherits: "Inherits from", routes: "Handled by", reads: "Reads table", writes: "Writes table" };
const EDGE_IN = { calls: "Called by", instantiates: "Created by", imports: "Imported by", inherits: "Subclassed by", routes: "Endpoint", reads: "Read by", writes: "Written by" };
const MAX_SOURCE_LINES = 160;
const fmt = (n) => n.toLocaleString("en");

function Certainty({ c }) {
  return <span className={`cert cert-${c}`} title={`certainty: ${c}`} />;
}

function EdgeList({ ix, items, labels, side, onGo }) {
  const groups = new Map();
  for (const e of items) {
    const key = labels[e.kind] || e.kind;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(e);
  }
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
              <button type="button" className="linkish" onClick={() => onGo(other.id)}>
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

function Deps({ title, items, tree, onGo }) {
  if (!items.length) return null;
  return (
    <section>
      <h4>{title}</h4>
      <ul className="links">
        {items.map(([id, count]) => (
          <li key={id}>
            {id === "elsewhere" ? (
              <span className="muted">outside the project map</span>
            ) : (
              <button type="button" className="linkish" onClick={() => onGo(id.replace(/^@/, ""))}>
                {tree.T.get(id.replace(/^@/, ""))?.name}
              </button>
            )}
            {id.startsWith("@") && <small className="muted"> · elsewhere</small>}
            <small> · {count} link{count > 1 ? "s" : ""}</small>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Source({ n, version }) {
  const [lines, setLines] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    if (!n?.file) return undefined;
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
  }, [n?.file, version]);
  if (!n?.file) return null;
  if (error) return <p className="muted">Source not available ({error}).</p>;
  if (!lines) return <p className="muted">Loading source…</p>;
  const whole = n.kind === "file";
  const start = whole || !n.line ? 1 : n.line;
  const last = whole ? lines.length : n.end_line || start;
  const end = Math.min(last, start + MAX_SOURCE_LINES - 1);
  return (
    <>
      <h4>Source</h4>
      <pre className="source">
        {lines.slice(start - 1, end).map((text, i) => (
          <div key={start + i}>
            <span className="ln">{start + i}</span>
            {text || " "}
          </div>
        ))}
        {end < last && <div className="muted">… {last - end} more lines</div>}
      </pre>
    </>
  );
}

export default function Panel({ ix, tree, t, isFocus, repo, version, lens, deps, onGo, onOpen, onUp, onFocus }) {
  if (!t) return <aside className="panel" />;
  const n = t.n;
  const s = t.stats;
  const path = treeAncestors(tree, t.id).map((id) => tree.T.get(id));
  const vscode = n?.file && repo ? `vscode://file${repo}/${n.file}${n.line && n.kind !== "file" ? `:${n.line}` : ""}` : null;
  const isCode = n && (n.kind === "function" || n.kind === "script" || n.kind === "endpoint" || n.kind === "table" || n.kind === "class");
  const kids = [...t.children].sort((a, b) => b.stats.loc - a.stats.loc);

  return (
    <aside className="panel">
      <nav className="crumbs">
        {path.map((p) => (
          <button type="button" key={p.id} className="linkish" onClick={() => onFocus(p.id)}>
            {p.name}
          </button>
        ))}
      </nav>
      <h2>
        {n?.kind === "function" ? displayName(ix, n) : t.name} <span className="kind">{KIND_LABEL[t.kind] || t.kind}</span>
      </h2>
      <div className="actions">
        {!isFocus && t.children.length > 0 && (
          <button type="button" className="primary" onClick={() => onOpen(t.id)}>
            Open ↵
          </button>
        )}
        {t.parent && (
          <button type="button" onClick={onUp}>
            ↑ Up
          </button>
        )}
        {vscode && (
          <a className="button" href={vscode}>
            Open in VS Code
          </a>
        )}
      </div>
      {t.path && <p className="muted">{n?.line && n.kind !== "file" ? `${t.path}:${n.line}${n.end_line && n.end_line !== n.line ? `–${n.end_line}` : ""}` : t.path}</p>}
      {n?.attrs?.error && <p className="warn">{n.attrs.error}</p>}

      {n?.kind === "function" && (
        <code className="sig">
          {n.attrs.is_async ? "async " : ""}
          {n.name}({(n.attrs.params || []).map((p) => (p.ann ? `${p.name}: ${p.ann}` : p.name)).join(", ")}){n.attrs.returns ? ` -> ${n.attrs.returns}` : ""}
        </code>
      )}
      {n?.attrs?.decorators?.length > 0 && <p className="muted">@{n.attrs.decorators.join("  @")}</p>}
      {n?.attrs?.doc && <p className="doc">{n.attrs.doc}</p>}

      {!isCode && (
        <table className="stats">
          <tbody>
            <tr>
              <td>Lines of code</td>
              <td>{fmt(s.loc)}</td>
            </tr>
            {s.folders > (t.kind === "folder" ? 1 : 0) && (
              <tr>
                <td>Folders</td>
                <td>{s.folders - (t.kind === "folder" ? 1 : 0)}</td>
              </tr>
            )}
            {s.files > 1 && (
              <tr>
                <td>Files</td>
                <td>{s.files}</td>
              </tr>
            )}
            <tr>
              <td>Classes / functions</td>
              <td>
                {s.classes} / {s.functions}
              </td>
            </tr>
            {s.tests > 0 && (
              <tr>
                <td>Tests</td>
                <td>{s.tests}</td>
              </tr>
            )}
            {(s.endpoints > 0 || s.tables > 0) && (
              <tr>
                <td>API endpoints / tables</td>
                <td>
                  {s.endpoints} / {s.tables}
                </td>
              </tr>
            )}
            {s.functions > 0 && (
              <tr>
                <td>Reached by tests</td>
                <td>
                  {s.tested} of {s.functions} ({Math.round((100 * s.tested) / s.functions)}%)
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
      {n?.kind === "function" && !t.isTest && <p className={`tested ${lens === "tests" ? "strong" : ""}`}>Tests: {badge(t, "tests", ix)}</p>}

      {deps && (
        <>
          <Deps title="Depends on" items={deps.out} tree={tree} onGo={onGo} />
          <Deps title="Used by" items={deps.in} tree={tree} onGo={onGo} />
        </>
      )}
      {isCode && (
        <>
          <EdgeList ix={ix} items={ix.out.get(n.id) || []} labels={EDGE_OUT} side="out" onGo={onGo} />
          <EdgeList ix={ix} items={ix.inn.get(n.id) || []} labels={EDGE_IN} side="in" onGo={onGo} />
        </>
      )}

      {kids.length > 0 && (
        <section>
          <h4>
            Contains <small>{kids.length}</small>
          </h4>
          <ul className="links">
            {kids.slice(0, 80).map((k) => (
              <li key={k.id}>
                <button type="button" className="linkish" onClick={() => onGo(k.id)}>
                  {k.kind === "function" ? `${k.name}()` : k.name}
                </button>
                <small className="muted"> {lens === "map" ? describe(k) : badge(k, lens, ix)}</small>
              </li>
            ))}
          </ul>
        </section>
      )}
      {n && n.kind !== "table" && n.kind !== "endpoint" && <Source n={n} version={version} />}
    </aside>
  );
}
