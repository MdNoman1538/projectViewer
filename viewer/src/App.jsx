import { LinearInterpolator } from "@deck.gl/core";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { layout } from "./layout.js";
import MapView from "./MapView.jsx";
import { displayName, groupLinks, indexWorld, linksFor, search } from "./model.js";
import Panel from "./Panel.jsx";
import { fitView } from "./view.js";

const POLL_MS = 1500;
const LENSES = [
  ["map", "Architecture", "How packages depend on each other"],
  ["tests", "Tests", "Green: called by a test · dark green: reached indirectly · red: no test reaches it"],
  ["data", "Data", "Which code reads and writes which tables"],
  ["api", "API", "Endpoints and the code behind them"],
];
const FLY = { transitionDuration: 500, transitionInterpolator: new LinearInterpolator(["target", "zoom"]) };

const whole = (L) => ({ x0: 0, y0: 0, x1: L.width, y1: L.height, zTop: L.zTop });

function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  const lens = p.get("lens");
  return { sel: p.get("sel"), lens: LENSES.some(([id]) => id === lens) ? lens : "map", mode: p.get("view") === "2d" ? "2d" : "3d" };
}

function useSize(ref) {
  const [size, setSize] = useState(null); // unknown until measured: never frame the map on a guess
  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setSize({ width: e.contentRect.width, height: e.contentRect.height }));
    if (ref.current) ro.observe(ref.current);
    return () => ro.disconnect();
  }, [ref]);
  return size;
}

// Poll the server; fetch the world only when its version changes (live updates while you code).
function useLiveWorld() {
  const [world, setWorld] = useState(null);
  const [error, setError] = useState(null);
  const [updatedAt, setUpdatedAt] = useState(null);
  const version = useRef(null);
  useEffect(() => {
    let stopped = false;
    let timer;
    const tick = async () => {
      try {
        const v = await (await fetch("api/version")).json();
        if (v.version !== version.current) {
          const w = await (await fetch("api/world")).json();
          version.current = w.version;
          setWorld(w);
          setUpdatedAt(new Date());
        }
        setError(null);
      } catch {
        setError("Server not reachable. Is `projectviewer serve` running?");
      }
      if (!stopped) timer = setTimeout(tick, POLL_MS);
    };
    tick();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, []);
  return { world, error, updatedAt };
}

function lensData(ix, lens) {
  const set = new Set();
  const links = [];
  if (lens === "data") {
    for (const e of ix.edges)
      if (e.kind === "reads" || e.kind === "writes") {
        set.add(e.source);
        links.push({ source: e.source, target: e.target, count: e.count });
      }
  } else if (lens === "api") {
    let frontier = [];
    for (const e of ix.edges)
      if (e.kind === "routes") {
        links.push({ source: e.source, target: e.target, count: 1 });
        set.add(e.target);
        frontier.push(e.target);
      }
    for (let hop = 0; hop < 3 && frontier.length; hop++) {
      const next = [];
      for (const id of frontier)
        for (const e of ix.out.get(id) || [])
          if ((e.kind === "calls" || e.kind === "instantiates") && !set.has(e.target)) {
            set.add(e.target);
            next.push(e.target);
          }
      frontier = next;
    }
  } else if (lens === "map") {
    links.push(...groupLinks(ix));
  }
  return { set, links };
}

export default function App() {
  const { world, error, updatedAt } = useLiveWorld();
  const mapRef = useRef(null);
  const searchRef = useRef(null);
  const size = useSize(mapRef);
  const initial = useRef(readHash());
  const [sel, setSel] = useState(initial.current.sel);
  const [lens, setLens] = useState(initial.current.lens);
  const [mode, setMode] = useState(initial.current.mode); // "3d" = 2.5D city (default), "2d" = flat map
  const [query, setQuery] = useState("");
  const [viewState, setViewState] = useState(null);

  const ix = useMemo(() => (world ? indexWorld(world) : null), [world]);
  const L = useMemo(() => (ix ? layout(ix) : null), [ix]);
  const selId = sel && ix?.byId.has(sel) ? sel : null;
  const selLinks = useMemo(() => (ix && selId ? linksFor(ix, selId) : null), [ix, selId]);
  const lensInfo = useMemo(() => (ix ? lensData(ix, lens) : { set: new Set(), links: [] }), [ix, lens]);
  const results = useMemo(() => (ix ? search(ix, query) : []), [ix, query]);

  const fitAll = useCallback(() => {
    if (L && size) setViewState((v) => ({ ...fitView(whole(L), size, mode === "3d", v, 1.04), ...FLY }));
  }, [L, size, mode]);

  // first world: frame the whole map; later updates keep the camera where you are
  useEffect(() => {
    if (L && !viewState && size) setViewState(fitView(whole(L), size, mode === "3d", null, 1.04));
  }, [L, viewState, size, mode]);

  const zoomTo = useCallback(
    (id) => {
      const r = L?.rects.get(id);
      if (r && size) setViewState((v) => ({ ...fitView(r, size, mode === "3d", v, 1.5), ...FLY }));
    },
    [L, size, mode],
  );

  const onSelect = useCallback(
    (id, opts = {}) => {
      if (opts.fromMap && id && id === selId) zoomTo(id); // click again to fly in
      setSel(id);
      if (opts.zoom && id) zoomTo(id);
    },
    [selId, zoomTo],
  );

  // keep #lens=…&sel=… in the address bar: links open the map at the same place
  useEffect(() => {
    const p = new URLSearchParams();
    if (lens !== "map") p.set("lens", lens);
    if (mode === "2d") p.set("view", "2d");
    if (selId) p.set("sel", selId);
    const h = p.toString();
    if (h !== location.hash.slice(1)) history.replaceState(null, "", h ? `#${h}` : location.pathname);
  }, [lens, selId, mode]);

  // a selection that came from the URL: fly to it once the map exists
  const flewToInitial = useRef(false);
  useEffect(() => {
    if (!flewToInitial.current && viewState && initial.current.sel && L?.rects.has(initial.current.sel)) {
      flewToInitial.current = true;
      zoomTo(initial.current.sel);
    }
  }, [viewState, L, zoomTo]);

  useEffect(() => {
    const onKey = (e) => {
      const typing = e.target.tagName === "INPUT";
      if (e.key === "Escape") {
        setSel(null);
        setQuery("");
        searchRef.current?.blur();
      } else if (!typing && e.key === "/") {
        e.preventDefault();
        searchRef.current?.focus();
      } else if (!typing && (e.key === "f" || e.key === "0")) fitAll();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fitAll]);

  const stats = world?.stats;
  const repoName = world?.repo?.split("/").filter(Boolean).at(-1) || "";
  const summary = stats && (
    <div className="summary">
      <h2>{repoName}</h2>
      <p className="muted">
        {world.commit ? `commit ${world.commit.slice(0, 7)}${world.dirty ? " + uncommitted changes" : ""}` : "not a git repository"}
      </p>
      <table>
        <tbody>
          <tr><td>Files</td><td>{stats.files.total}{stats.files.errors ? ` (${stats.files.errors} with errors)` : ""}</td></tr>
          <tr><td>Classes / functions</td><td>{stats.nodes.class || 0} / {stats.nodes.function || 0}</td></tr>
          <tr><td>API endpoints / tables</td><td>{stats.nodes.endpoint || 0} / {stats.nodes.table || 0}</td></tr>
          <tr><td>Links</td><td>{Object.values(stats.edges).reduce((a, b) => a + b, 0)}</td></tr>
          <tr><td>Calls linked</td><td>{stats.calls.resolved} (unresolved {stats.calls.unresolved}, libraries {stats.calls.external}, builtin {stats.calls.builtin})</td></tr>
        </tbody>
      </table>
      <h4>How to use</h4>
      <ul className="help">
        <li><b>Drag</b> to move, <b>scroll</b> to zoom. Labels appear as you zoom in.</li>
        <li>2.5D: <b>right-drag</b> (or Ctrl-drag) to rotate. Taller = more code.</li>
        <li><b>Click</b> something to see its links; <b>click again</b> to fly in.</li>
        <li><b>/</b> search · <b>Esc</b> clear · <b>F</b> show everything</li>
        <li>Lenses (top) colour the map by one question.</li>
      </ul>
      <h4>Lines</h4>
      <ul className="legend">
        <li><span className="swatch" style={{ background: "rgb(104,168,255)" }} /> what the selection uses</li>
        <li><span className="swatch" style={{ background: "rgb(240,168,80)" }} /> what uses the selection</li>
        <li><span className="cert cert-proven" /> proven · <span className="cert cert-inferred" /> inferred · <span className="cert cert-pattern" /> pattern (text match)</li>
      </ul>
    </div>
  );

  return (
    <div className="app">
      <header className="top">
        <span className="brand">projectViewer</span>
        <span className="repo">{repoName}</span>
        <div className="lenses" role="tablist">
          {LENSES.map(([id, label, title]) => (
            <button key={id} type="button" title={title} className={lens === id ? "on" : ""} onClick={() => setLens(id)}>
              {label}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="mode"
          title="Switch between the 2.5D city and the flat map"
          onClick={() => {
            const next = mode === "3d" ? "2d" : "3d";
            setMode(next);
            if (L && size) setViewState((v) => ({ ...fitView(selId && L.rects.get(selId) ? L.rects.get(selId) : whole(L), size, next === "3d", v, selId ? 1.5 : 1.04), ...FLY }));
          }}
        >
          {mode === "3d" ? "2.5D" : "2D"}
        </button>
        <div className="search">
          <input
            ref={searchRef}
            value={query}
            placeholder="Search  ( / )"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && results[0]) {
                onSelect(results[0].id, { zoom: true });
                setQuery("");
              }
            }}
          />
          {results.length > 0 && (
            <ul className="results">
              {results.map((n) => (
                <li key={n.id}>
                  <button
                    type="button"
                    onClick={() => {
                      onSelect(n.id, { zoom: true });
                      setQuery("");
                    }}
                  >
                    {displayName(ix, n)} <small>{n.kind === "file" ? n.file : `${n.kind} · ${n.file || ""}`}</small>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <span className={`live ${error ? "down" : ""}`} title={error || "Updates automatically when files change"}>
          {error ? "offline" : updatedAt ? `live · ${updatedAt.toLocaleTimeString()}` : "loading…"}
        </span>
      </header>
      <main className="body">
        <div className="map" ref={mapRef}>
          {L && viewState && size ? (
            <MapView
              L={L}
              ix={ix}
              sel={selId}
              lens={lens}
              lensSet={lensInfo.set}
              selLinks={selLinks}
              overview={lensInfo.links}
              viewState={viewState}
              onViewState={setViewState}
              size={size}
              onSelect={onSelect}
              mode={mode}
            />
          ) : (
            <div className="empty">{error || "Mapping the project…"}</div>
          )}
          <div className="lens-note">{LENSES.find(([id]) => id === lens)[2]}</div>
        </div>
        {ix && <Panel ix={ix} sel={selId} repo={world.repo} version={world.version} lens={lens} onSelect={onSelect} onZoom={zoomTo} summary={summary} />}
      </main>
    </div>
  );
}
