import { LinearInterpolator } from "@deck.gl/core";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChangesDrawer, changedCode, TourBar, tourSteps } from "./Changes.jsx";
import { layoutLevel } from "./layout.js";
import MapView from "./MapView.jsx";
import { indexWorld } from "./model.js";
import Panel from "./Panel.jsx";
import { blockDeps, buildTree, changeMarks, levelLinks, treeAncestors } from "./tree.js";
import { fitView } from "./view.js";

const POLL_MS = 1500;
const TOUR_MS = 5000;
const LENSES = [
  ["map", "Architecture", "Blocks = folders and files · size and height = number of functions · roof = what is inside · lines = dependencies"],
  ["tests", "Tests", "Share of functions reached by tests · green ≥ 60% · amber ≥ 30% · red below"],
  ["data", "Data", "Which code reads and writes the database tables"],
  ["api", "API", "Where the API endpoints are, and the code behind them"],
];
const FLY = { transitionDuration: 450, transitionInterpolator: new LinearInterpolator(["target", "zoom"]) };
const RANK = { folder: 0, file: 1, class: 2, function: 3, endpoint: 4, table: 5, database: 6, script: 7 };

function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  const lens = p.get("lens");
  return {
    project: p.get("p"),
    focus: p.get("focus") || "root",
    sel: p.get("sel"),
    lens: LENSES.some(([id]) => id === lens) ? lens : "map",
    mode: p.get("view") === "2d" ? "2d" : "3d",
    change: p.get("ch"),
    follow: p.get("follow") !== "0",
  };
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

const getJSON = async (url) => {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
};

// Poll the list of projects (with each one's version and last change): drives live updates and "follow".
function useProjects() {
  const [projects, setProjects] = useState([]);
  const [error, setError] = useState(null);
  useEffect(() => {
    let stopped = false;
    let timer;
    const tick = async () => {
      try {
        setProjects(await getJSON("api/projects"));
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
  return { projects, error };
}

// Fetch `url` again whenever `key` changes; keep the last good value while loading.
function useFetched(url, key) {
  const [data, setData] = useState(null);
  useEffect(() => {
    if (!url) {
      setData(null);
      return undefined;
    }
    let live = true;
    getJSON(url)
      .then((d) => live && setData(d))
      .catch(() => live && setData(null));
    return () => {
      live = false;
    };
  }, [url, key]);
  return data;
}

// API lens: the endpoints' handlers and what they call (3 steps).
function apiReach(ix) {
  const set = new Set();
  let frontier = [];
  for (const e of ix.edges)
    if (e.kind === "routes") {
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
  return set;
}

export default function App() {
  const { projects, error } = useProjects();
  const mapRef = useRef(null);
  const searchRef = useRef(null);
  const size = useSize(mapRef);
  const initial = useRef(readHash());
  const [pid, setPid] = useState(initial.current.project);
  const [follow, setFollow] = useState(initial.current.follow);
  const [focus, setFocus] = useState(initial.current.focus);
  const [sel, setSel] = useState(initial.current.sel);
  const [lens, setLens] = useState(initial.current.lens);
  const [mode, setMode] = useState(initial.current.mode); // "3d" = 2.5D city (default), "2d" = flat map
  const [changeRef, setChangeRef] = useState(initial.current.change); // null | "working" | commit sha
  const [drawer, setDrawer] = useState(false);
  const [tour, setTour] = useState(null); // index into the tour steps, or null
  const [playing, setPlaying] = useState(false);
  const [query, setQuery] = useState("");
  const [viewState, setViewState] = useState(null);

  // ---------------------------------------------------------------- which project
  const project = projects.find((p) => p.id === pid) || projects[0] || null;
  const switchTo = useCallback((id) => {
    setPid(id);
    setFocus("root");
    setSel(null);
    setTour(null);
  }, []);
  // Follow activity: when another project's files change, show that project.
  const lastSeen = useRef({});
  useEffect(() => {
    const prev = lastSeen.current;
    if (follow && project) {
      const moved = projects.filter((p) => prev[p.id] !== undefined && p.last_change > prev[p.id] && p.id !== project.id);
      if (moved.length) {
        const newest = moved.reduce((a, b) => (a.last_change > b.last_change ? a : b));
        if (newest.last_change > project.last_change) switchTo(newest.id);
      }
    }
    lastSeen.current = Object.fromEntries(projects.map((p) => [p.id, p.last_change]));
  }, [projects, follow, project, switchTo]);

  const api = project ? `api/p/${encodeURIComponent(project.id)}` : null;
  const version = project?.version;
  const world = useFetched(api && `${api}/world`, version);
  const live = useFetched(api && `${api}/changes?ref=working`, version);
  const commits = useFetched(api && drawer ? `${api}/commits` : null, version);
  const picked = useFetched(api && changeRef && changeRef !== "working" ? `${api}/changes?ref=${changeRef}` : null, changeRef);
  const cs = changeRef === "working" ? live : changeRef ? picked : null;

  // ---------------------------------------------------------------- the map of the current level
  const repoName = world?.repo?.split("/").filter(Boolean).at(-1) || project?.name || "project";
  const ix = useMemo(() => (world ? indexWorld(world) : null), [world]);
  const tree = useMemo(() => (ix ? buildTree(ix, repoName) : null), [ix, repoName]);
  const focusId = tree ? (tree.T.has(focus) && tree.T.get(focus).children.length ? focus : "root") : null;
  const focusT = tree?.T.get(focusId);
  const selId = sel && focusT?.children.some((c) => c.id === sel) ? sel : null;
  const L = useMemo(() => (focusT ? layoutLevel(focusT) : null), [focusT]);
  const links = useMemo(() => (tree ? levelLinks(ix, tree, focusId) : []), [ix, tree, focusId]);
  const reachSet = useMemo(() => (ix ? apiReach(ix) : new Set()), [ix]);
  const deps = useMemo(() => (tree && selId ? blockDeps(ix, tree, focusId, selId) : null), [ix, tree, focusId, selId]);
  const marks = useMemo(() => (tree && cs ? changeMarks(tree, cs) : null), [tree, cs]);
  const steps = useMemo(() => (cs && ix ? tourSteps(cs, ix) : []), [cs, ix]);
  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!tree || !q) return [];
    return [...tree.T.values()]
      .filter((t) => t.parent && t.name.toLowerCase().includes(q))
      .sort((a, b) => (a.name.toLowerCase() === q ? -1 : 0) - (b.name.toLowerCase() === q ? -1 : 0) || (RANK[a.kind] ?? 9) - (RANK[b.kind] ?? 9) || a.name.length - b.name.length)
      .slice(0, 12);
  }, [tree, query]);

  const whole = useCallback((Lv) => ({ x0: 0, y0: 0, x1: Lv.width, y1: Lv.height, zTop: Lv.zTop }), []);

  // Frame the whole level whenever the project, level or view mode changes.
  const framed = useRef(null);
  useEffect(() => {
    if (!L || !size) return;
    const key = `${project?.id}|${focusId}|${mode}|${size.width}x${size.height}`;
    if (framed.current === key) return;
    const first = framed.current === null;
    framed.current = key;
    setViewState((v) => ({ ...fitView(whole(L), size, mode === "3d", v, 1.06), ...(first ? {} : FLY) }));
  }, [L, size, focusId, mode, whole, project?.id]);

  // Keep the place in the address bar: links reopen the same view.
  useEffect(() => {
    if (!tree || !project) return;
    const p = new URLSearchParams();
    if (projects.length > 1) p.set("p", project.id);
    if (focusId !== "root") p.set("focus", focusId);
    if (selId) p.set("sel", selId);
    if (lens !== "map") p.set("lens", lens);
    if (mode === "2d") p.set("view", "2d");
    if (changeRef) p.set("ch", changeRef);
    if (!follow) p.set("follow", "0");
    const h = p.toString();
    if (h !== location.hash.slice(1)) history.replaceState(null, "", h ? `#${h}` : location.pathname);
  }, [tree, project, projects.length, focusId, selId, lens, mode, changeRef, follow]);

  // ---------------------------------------------------------------- navigation
  const open = useCallback(
    (id) => {
      const t = tree?.T.get(id);
      if (t?.children.length) {
        setFocus(id);
        setSel(null);
      }
    },
    [tree],
  );
  const up = useCallback(() => {
    if (!focusT?.parent) return;
    setFocus(focusT.parent);
    setSel(focusT.id); // show where you came from
  }, [focusT]);
  const go = useCallback(
    (id) => {
      const t = tree?.T.get(id);
      if (!t || !t.parent) return;
      setFocus(t.parent);
      setSel(id);
      setQuery("");
    },
    [tree],
  );
  const onSelect = useCallback(
    (id, opts = {}) => {
      if (opts.fromMap && id && id === selId) return open(id); // click a selected block again to open it
      setSel(id);
    },
    [selId, open],
  );

  // ---------------------------------------------------------------- the Show tour
  const showStep = useCallback(
    (i) => {
      if (!steps.length) return;
      const k = Math.max(0, Math.min(steps.length - 1, i));
      setTour(k);
      go(steps[k]);
    },
    [steps, go],
  );
  useEffect(() => {
    if (!playing || tour === null) return undefined;
    if (tour >= steps.length - 1) {
      setPlaying(false);
      return undefined;
    }
    const t = setTimeout(() => showStep(tour + 1), TOUR_MS);
    return () => clearTimeout(t);
  }, [playing, tour, steps.length, showStep]);
  const pickChange = (ref) => {
    setChangeRef(ref === changeRef ? null : ref);
    setTour(null);
    setPlaying(false);
    setSel(null);
  };

  useEffect(() => {
    const onKey = (e) => {
      const typing = e.target.tagName === "INPUT" || e.target.tagName === "SELECT";
      if (e.key === "Escape") {
        if (query) setQuery("");
        else if (tour !== null) setTour(null);
        else if (selId) setSel(null);
        else up();
        searchRef.current?.blur();
      } else if (typing) return;
      else if (e.key === "/") {
        e.preventDefault();
        searchRef.current?.focus();
      } else if (tour !== null && e.key === "ArrowRight") showStep(tour + 1);
      else if (tour !== null && e.key === "ArrowLeft") showStep(tour - 1);
      else if (e.key === "Enter" && selId) open(selId);
      else if (e.key === "Backspace") up();
      else if (e.key === "f") setViewState((v) => ({ ...fitView(whole(L), size, mode === "3d", v, 1.06), ...FLY }));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [query, tour, selId, up, open, L, size, mode, whole, showStep]);

  const crumbs = tree && focusT ? [...treeAncestors(tree, focusId), focusId].map((id) => tree.T.get(id)) : [];
  const shown = selId ? tree.T.get(selId) : focusT;
  const liveCount = changedCode(live).length;

  return (
    <div className="app">
      <header className="top">
        <span className="brand">projectViewer</span>
        {projects.length > 1 ? (
          <select className="project" value={project?.id || ""} onChange={(e) => switchTo(e.target.value)} title="Project">
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        ) : (
          <span className="repo">{project?.name}</span>
        )}
        {projects.length > 1 && (
          <label className="follow" title="Show whichever project is changing right now">
            <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> follow activity
          </label>
        )}
        <div className="lenses" role="tablist">
          {LENSES.map(([id, label, title]) => (
            <button key={id} type="button" title={title} className={lens === id ? "on" : ""} onClick={() => setLens(id)}>
              {label}
            </button>
          ))}
        </div>
        <button type="button" className={`changes-btn ${drawer || changeRef ? "on" : ""}`} onClick={() => setDrawer((d) => !d)} title="What changed, where, why and what it affects">
          Changes{liveCount > 0 && <span className="pill">{liveCount} live</span>}
        </button>
        <button type="button" className="mode" title="Switch between the 2.5D city and the flat map" onClick={() => setMode((m) => (m === "3d" ? "2d" : "3d"))}>
          {mode === "3d" ? "2.5D" : "2D"}
        </button>
        <div className="search">
          <input
            ref={searchRef}
            value={query}
            placeholder="Search  ( / )"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && results[0]) go(results[0].id);
            }}
          />
          {results.length > 0 && (
            <ul className="results">
              {results.map((t) => (
                <li key={t.id}>
                  <button type="button" onClick={() => go(t.id)}>
                    {t.kind === "function" ? `${t.name}()` : t.name} <small>{t.kind} · {t.path || ""}</small>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <span className={`live ${error ? "down" : ""}`} title={error || "Updates automatically when files change"}>
          {error ? "offline" : world ? "live" : "loading…"}
        </span>
      </header>
      <main className="body">
        <div className="map" ref={mapRef}>
          {L && viewState && size ? (
            L.blocks.length ? (
              <MapView
                L={L}
                ix={ix}
                sel={selId}
                lens={lens}
                lensSet={reachSet}
                links={links}
                viewState={viewState}
                onViewState={setViewState}
                size={size}
                onSelect={onSelect}
                onTile={(tile) => {
                  // a roof tile: go straight into it (or show it in its block when there is nothing inside)
                  const t = tree.T.get(tile.id);
                  if (t?.children.length) {
                    setFocus(t.id);
                    setSel(null);
                  } else {
                    setFocus(tile.parent);
                    setSel(tile.id);
                  }
                }}
                mode={mode}
                marks={marks}
              />
            ) : (
              <div className="empty">Nothing inside.</div>
            )
          ) : (
            <div className="empty">{error || (projects.length ? "Mapping the project…" : "No projects yet: run `projectviewer add <repo>`")}</div>
          )}
          <nav className="levelbar">
            {crumbs.map((t, i) => (
              <span key={t.id}>
                {i > 0 && <span className="sep">›</span>}
                <button type="button" className={i === crumbs.length - 1 ? "here" : ""} onClick={() => (i < crumbs.length - 1 ? (setFocus(t.id), setSel(null)) : setSel(null))}>
                  {t.name}
                </button>
              </span>
            ))}
            {focusT?.parent && (
              <button type="button" className="upbtn" title="Up one level (Backspace)" onClick={up}>
                ↑
              </button>
            )}
          </nav>
          {drawer && <ChangesDrawer live={live} commits={commits} active={changeRef} onPick={pickChange} onClose={() => setDrawer(false)} />}
          {cs && tour !== null && steps.length > 0 && (
            <TourBar
              steps={steps}
              index={tour}
              ix={ix}
              cs={cs}
              playing={playing}
              onStep={showStep}
              onPlay={() => setPlaying((p) => !p)}
              onClose={() => {
                setTour(null);
                setPlaying(false);
              }}
            />
          )}
          <div className="lens-note">
            {cs ? (
              <>
                <span className="swatch red" /> changed · <span className="swatch purple" /> moved · <span className="swatch amber" /> affected · {cs.ref === "working" ? "live: uncommitted changes" : cs.subject}
              </>
            ) : (
              <>
                {LENSES.find(([id]) => id === lens)[2]}
                {L?.measure === "lines" ? " (here: lines of code, since every block is one function)" : ""}
              </>
            )}
            <br />
            <span className="keys">click = select · click again / Enter = open · Backspace / Esc = up · right-drag = rotate</span>
          </div>
        </div>
        {tree && (
          <Panel
            ix={ix}
            tree={tree}
            t={shown}
            isFocus={!selId}
            repo={world.repo}
            version={world.version}
            lens={lens}
            deps={selId && shown?.children.length ? deps : null}
            onGo={go}
            onOpen={open}
            onUp={up}
            onFocus={(id) => {
              setFocus(id);
              setSel(null);
            }}
            api={api}
            cs={cs}
            onShow={() => {
              showStep(0);
              setPlaying(true);
            }}
          />
        )}
      </main>
    </div>
  );
}
