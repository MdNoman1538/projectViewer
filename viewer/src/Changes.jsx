// Changes: what changed, where, why (notes) and how (diff), for the live working copy or a commit.
import { useEffect, useState } from "react";

const CODE = (id) => id.startsWith("py:") || id.startsWith("endpoint:");
const label = (n) => (n.kind === "script" ? "top-level code" : n.kind === "function" ? `${n.name}()` : n.name);
const HOW = { new: "new", modified: "changed", contains: "changed inside", moved: "moved" };

export const changedCode = (cs) => Object.keys(cs?.changed || {}).filter((id) => CODE(id) && cs.changed[id] !== "moved");
const movedCode = (cs) => Object.keys(cs?.moved || {}).filter(CODE);

export function notesFor(cs, id) {
  return (cs?.notes || []).filter((n) => n.node === id).map((n) => n.text);
}

// Steps of the Show tour: changed code first (by file and line), else changed files.
export function tourSteps(cs, ix) {
  const nodes = changedCode(cs)
    .map((id) => ix.byId.get(id))
    .filter((n) => n && !(n.kind === "class" && cs.changed[n.id] === "contains"));
  const files = Object.entries(cs?.changed || {})
    .filter(([, how]) => how !== "moved")
    .map(([id]) => ix.byId.get(id))
    .filter((n) => n?.kind === "file");
  const steps = nodes.length ? nodes : files;
  return steps.sort((a, b) => (a.file || "").localeCompare(b.file || "") || (a.line || 0) - (b.line || 0)).map((n) => n.id);
}

export function ChangesDrawer({ live, commits, active, onPick, onClose }) {
  const liveCount = changedCode(live).length;
  return (
    <div className="drawer">
      <div className="drawer-head">
        <b>Changes</b>
        <button type="button" className="linkish" onClick={onClose}>
          close
        </button>
      </div>
      <button type="button" className={`change-row live ${active === "working" ? "on" : ""}`} onClick={() => onPick("working")}>
        <span className="dot" /> Live: uncommitted changes
        <small>{live ? `${liveCount} changed · updates as files are saved` : "not a git repository"}</small>
      </button>
      <div className="drawer-sub">Commits</div>
      <div className="commit-list">
        {(commits || []).map((c) => (
          <button key={c.sha} type="button" className={`change-row ${active === c.sha ? "on" : ""}`} onClick={() => onPick(c.sha)}>
            {c.subject}
            <small>
              {c.short} · {new Date(c.date).toLocaleString()}
              {c.notes ? ` · ${c.notes} notes` : ""}
              {c.refs.length ? ` · #${c.refs.join(" #")}` : ""}
            </small>
          </button>
        ))}
        {commits && !commits.length && <p className="muted">No commits yet.</p>}
      </div>
    </div>
  );
}

// Hunks of a unified diff that touch [from, to] on the new side (all hunks when no range).
function hunks(patch, from, to) {
  const out = [];
  let cur = null;
  for (const line of patch.split("\n")) {
    const m = line.match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/);
    if (m) {
      const start = Number(m[1]);
      const end = start + Math.max(1, Number(m[2] ?? 1)) - 1;
      cur = { start, end, lines: [line] };
      out.push(cur);
    } else if (cur && !line.startsWith("diff ") && !line.startsWith("index ")) cur.lines.push(line);
    else if (!cur && line.startsWith("+") && !line.startsWith("+++")) {
      cur = { start: 1, end: 1e9, lines: [] }; // a new file shown whole
      out.push(cur);
      cur.lines.push(line);
    }
  }
  return from ? out.filter((h) => h.start <= to && from <= h.end) : out;
}

export function DiffView({ api, refName, file, from, to }) {
  const [patch, setPatch] = useState(null);
  useEffect(() => {
    let live = true;
    setPatch(null);
    fetch(`${api}/diff?ref=${encodeURIComponent(refName)}&file=${encodeURIComponent(file)}`)
      .then((r) => (r.ok ? r.json() : { diff: "" }))
      .then((d) => live && setPatch(d.diff || ""));
    return () => {
      live = false;
    };
  }, [api, refName, file]);
  if (patch === null) return <p className="muted">Loading the diff…</p>;
  const hs = hunks(patch, from, to);
  if (!hs.length) return <p className="muted">No line changes here.</p>;
  return (
    <pre className="source diff">
      {hs.flatMap((h, i) =>
        h.lines.map((l, j) => (
          // biome-ignore lint: diff lines have no identity beyond position
          <div key={`${i}-${j}`} className={l.startsWith("@@") ? "hunk" : l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : ""}>
            {l || " "}
          </div>
        )),
      )}
    </pre>
  );
}

export function ChangeSummary({ cs, ix, onGo, onShow }) {
  const items = changedCode(cs).map((id) => ix.byId.get(id)).filter(Boolean);
  const affected = Object.keys(cs.upstream || {}).length;
  const reached = Object.keys(cs.downstream || {}).length;
  const body = (cs.message || "")
    .split("\n")
    .slice(1)
    .filter((l) => !/^(Co-Authored-By|Signed-off-by):/i.test(l)) // git bookkeeping, not explanation
    .join("\n")
    .split(/\nChanges:\s*\n/)[0]
    .trim()
    .split(/\n\s*\n/) // commit bodies are wrapped at ~72 columns: re-join lines within a paragraph
    .map((para) => para.replace(/\s*\n\s*/g, " "))
    .join("\n\n");
  const moved = movedCode(cs).map((id) => ix.byId.get(id)).filter(Boolean);
  const unattached = (cs.notes || []).filter((n) => !n.node);
  return (
    <div className="change-summary">
      <h2>{cs.ref === "working" ? "Live: uncommitted changes" : cs.subject}</h2>
      {cs.sha && <p className="muted">commit {cs.sha.slice(0, 7)}{cs.refs?.length ? ` · issue #${cs.refs.join(", #")}` : ""}</p>}
      <div className="actions">
        <button type="button" className="primary" onClick={onShow} disabled={!items.length && !cs.files?.length}>
          ▶ Show
        </button>
      </div>
      <table className="stats">
        <tbody>
          <tr>
            <td>
              <span className="swatch red" /> Changed
            </td>
            <td>
              {items.length} in {cs.files?.length || 0} file{cs.files?.length === 1 ? "" : "s"}
            </td>
          </tr>
          <tr>
            <td>
              <span className="swatch amber" /> Depend on it
            </td>
            <td>{affected}</td>
          </tr>
          <tr>
            <td>
              <span className="swatch amber" /> It reaches
            </td>
            <td>{reached}</td>
          </tr>
          {moved.length > 0 && (
            <tr>
              <td>
                <span className="swatch purple" /> Moved
              </td>
              <td>{moved.length}</td>
            </tr>
          )}
          {cs.removed?.length > 0 && (
            <tr>
              <td>Removed</td>
              <td>{cs.removed.length}</td>
            </tr>
          )}
        </tbody>
      </table>
      {body && <p className="doc">{body}</p>}
      <h4>
        What changed <small>{items.length}</small>
      </h4>
      <ul className="links changes">
        {items.map((n) => (
          <li key={n.id}>
            <button type="button" className="linkish" onClick={() => onGo(n.id)}>
              {label(n)}
            </button>
            {n.kind === "script" && <small className="muted"> {n.file}</small>}
            <small className={`how how-${cs.changed[n.id]}`}> {HOW[cs.changed[n.id]] || cs.changed[n.id]}</small>
            {notesFor(cs, n.id).map((t) => (
              <div key={t} className="note">
                {t}
              </div>
            ))}
          </li>
        ))}
      </ul>
      {moved.length > 0 && (
        <>
          <h4>
            Moved <small>{moved.length}</small>
          </h4>
          <ul className="links">
            {moved.map((n) => (
              <li key={n.id}>
                <button type="button" className="linkish" onClick={() => onGo(n.id)}>
                  {label(n)}
                </button>
                <small className="muted"> to {n.file}</small>
                {notesFor(cs, n.id).map((t) => (
                  <div key={t} className="note">
                    {t}
                  </div>
                ))}
              </li>
            ))}
          </ul>
        </>
      )}
      {unattached.length > 0 && (
        <>
          <h4>Other notes</h4>
          <ul className="links">
            {unattached.map((n) => (
              <li key={`${n.path}${n.symbol}`}>
                <code>{n.symbol ? `${n.path}::${n.symbol}` : n.path}</code>
                <div className="note">{n.text}</div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

export function NodeChange({ cs, n, api }) {
  if (!cs || !n?.file) return null;
  const how = cs.changed?.[n.id];
  const up = cs.upstream?.[n.id];
  const down = cs.downstream?.[n.id];
  const notes = notesFor(cs, n.id);
  if (!how && !up && !down && !cs.files?.includes(n.file)) return null;
  const whole = n.kind === "file";
  return (
    <section className="node-change">
      <h4>{how ? `Change: ${HOW[how] || how}` : up ? `Affected: depends on the change (${up} step${up > 1 ? "s" : ""} away)` : down ? `Affected: reached by the change (${down} step${down > 1 ? "s" : ""})` : "In a changed file"}</h4>
      {notes.map((t) => (
        <p key={t} className="note">
          {t}
        </p>
      ))}
      {(how || cs.files?.includes(n.file)) && <DiffView api={api} refName={cs.ref === "working" ? "working" : cs.sha} file={n.file} from={whole ? null : n.line} to={whole ? null : n.end_line || n.line} />}
    </section>
  );
}

export function TourBar({ steps, index, ix, cs, playing, onStep, onPlay, onClose }) {
  const n = ix.byId.get(steps[index]);
  const note = n ? notesFor(cs, n.id)[0] : null;
  return (
    <div className="tourbar">
      <button type="button" onClick={() => onStep(index - 1)} disabled={index <= 0}>
        ◀
      </button>
      <div className="tour-text">
        <b>
          {index + 1} / {steps.length} · {n ? label(n) : ""}
        </b>
        <span>{note || (n ? `${HOW[cs.changed[n.id]] || "changed"} · ${n.file}` : "")}</span>
      </div>
      <button type="button" onClick={() => onStep(index + 1)} disabled={index >= steps.length - 1}>
        ▶
      </button>
      <button type="button" onClick={onPlay}>
        {playing ? "❚❚" : "auto"}
      </button>
      <button type="button" onClick={onClose}>
        ✕
      </button>
    </div>
  );
}

const ago = (ms) => {
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`;
};

// What the AI is doing, newest first (from the Claude Code hook).
export function ActivityFeed({ events, onFile }) {
  if (!events.length) return null;
  return (
    <div className="activity">
      <div className="activity-head">AI activity</div>
      {events.slice(0, 6).map((e, i) => (
        <div key={`${e.at}-${i}`} className={`activity-row ${i === 0 && Date.now() - e.at < 4000 ? "fresh" : ""}`}>
          {e.event === "UserPromptSubmit" ? (
            <span>💬 {e.prompt ? `“${e.prompt.slice(0, 90)}${e.prompt.length > 90 ? "…" : ""}”` : "new prompt"}</span>
          ) : e.event === "Stop" ? (
            <span>✓ finished a turn</span>
          ) : (
            <span>
              ✎ {e.tool || "edit"}{" "}
              {e.file ? (
                <button type="button" className="linkish" onClick={() => onFile(e.file)}>
                  {e.file}
                </button>
              ) : null}
            </span>
          )}
          <small>{ago(e.at)}</small>
        </div>
      ))}
    </div>
  );
}
