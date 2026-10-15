import { useEffect, useRef, useState } from "react";
import type { IndexInfo, ModelState, Result } from "./lens";

const KINDS: Array<[string, string]> = [["", "All"], ["image", "Photos"], ["video", "Videos"], ["pdf", "PDFs"], ["document", "Documents"], ["other", "Other"]];
const EXAMPLES = ["elephant ivory seizure", "rangers training in the forest", "bear cubs in a cage", "film festival poster", "annual report"];
const WHY_LABEL: Record<string, string> = { all: "all words", near: "words together", any: "some words" };
const KIND_LABEL: Record<string, string> = { image: "Photo", video: "Video", pdf: "PDF", document: "Document", other: "File" };

export default function App() {
  const [info, setInfo] = useState<IndexInfo | null>(null);
  const [model, setModel] = useState<ModelState>({ state: "idle", progress: 0, error: "" });
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [results, setResults] = useState<Result[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [openErr, setOpenErr] = useState("");
  const seq = useRef(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    window.lens.info().then(setInfo);
    window.lens.modelStatus().then(setModel);
    const off = window.lens.onModel(setModel);
    input.current?.focus();
    return off;
  }, []);

  // Search as you type (debounced); the latest query wins.
  useEffect(() => {
    if (!q.trim() || !info) { setResults(null); setError(""); return; }
    const mine = ++seq.current;
    const t = setTimeout(async () => {
      setBusy(true);
      const r = await window.lens.search(q, { kind, k: 60 });
      if (mine !== seq.current) return;
      setBusy(false);
      if (r.ok) { setResults(r.results || []); setError(""); } else setError(r.error || "Search failed");
    }, 250);
    return () => clearTimeout(t);
  }, [q, kind, info, model.state]);

  async function choose() {
    const r = await window.lens.chooseIndex();
    if (r.ok && r.info) { setInfo(r.info); setOpenErr(""); setResults(null); }
    else if (!r.canceled) setOpenErr(r.error || "Could not open that file");
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-4 border-b border-line bg-panel px-5 py-3">
        <div className="flex items-center gap-2">
          <Lens />
          <span className="text-[15px] font-semibold tracking-tight">Drive Lens</span>
        </div>
        <div className="min-w-0 flex-1 truncate text-xs text-mute">
          {info ? <>{info.files.toLocaleString()} files · {info.described.toLocaleString()} looked at · listed {info.listedAt.slice(0, 10)}</> : "No index open"}
        </div>
        <ModelBadge m={model} />
        <button onClick={choose} className="rounded-md border border-line px-3 py-1.5 text-xs hover:bg-bg">Open index…</button>
      </header>

      <div className="border-b border-line bg-panel px-5 pb-3 pt-4">
        <div className="relative mx-auto max-w-3xl">
          <input
            ref={input}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && setQ("")}
            placeholder={'Describe what you\'re looking for — a scene, a subject, a file name. "exact phrase", -exclude'}
            className="w-full rounded-xl border border-line bg-bg px-4 py-3 pr-10 text-[15px] outline-none placeholder:text-mute focus:border-accent"
            disabled={!info}
          />
          {busy && <span className="absolute right-4 top-1/2 size-4 -translate-y-1/2 animate-spin rounded-full border-2 border-mute border-t-transparent" />}
        </div>
        <div className="mx-auto mt-3 flex max-w-3xl flex-wrap gap-1.5">
          {KINDS.map(([k, label]) => (
            <button key={k} onClick={() => setKind(k)}
              className={`rounded-full border px-3 py-1 text-xs ${kind === k ? "border-accent bg-accent text-accent-ink" : "border-line text-mute hover:text-ink"}`}>
              {label}{info && k ? <span className="ml-1 opacity-70">{(info.kinds[k] || 0).toLocaleString()}</span> : null}
            </button>
          ))}
        </div>
      </div>

      <main className="flex-1 overflow-y-auto px-5 py-5">
        {!info && (
          <Empty title="Open an index to start">
            Drive Lens searches an index built by <code>drive-lens</code> (a <code>.db</code> file). {openErr && <span className="text-red-500">{openErr}</span>}
            <div className="mt-4"><button onClick={choose} className="rounded-md bg-accent px-4 py-2 text-sm text-accent-ink">Open index…</button></div>
          </Empty>
        )}
        {info && !q.trim() && (
          <Empty title="Find anything in the Drive by what it shows">
            Try
            <div className="mt-3 flex flex-wrap justify-center gap-2">
              {EXAMPLES.map((x) => <button key={x} onClick={() => setQ(x)} className="rounded-full border border-line px-3 py-1 text-xs hover:border-accent">{x}</button>)}
            </div>
            {info.lockedFolders.length > 0 && (
              <p className="mt-6 text-xs">{info.lockedFolders.length} folders are not shared with the link and are not searched.</p>
            )}
          </Empty>
        )}
        {error && <p className="mx-auto max-w-3xl text-sm text-red-500">{error}</p>}
        {results && results.length === 0 && !busy && <Empty title="Nothing found">Try other words, or fewer of them.</Empty>}
        {results && results.length > 0 && (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-4">
            {results.map((r) => <Card key={r.id} r={r} />)}
          </div>
        )}
      </main>
    </div>
  );
}

function Card({ r }: { r: Result }) {
  const folderName = r.folder.split("/").pop() || "My Drive";
  return (
    <article className="group flex flex-col overflow-hidden rounded-xl border border-line bg-panel">
      <button onClick={() => window.lens.open(r.url)} className="relative aspect-[4/3] w-full overflow-hidden bg-bg" title="Open in Google Drive">
        {r.thumb
          ? <img src={r.thumb} alt={r.title || r.name} className="size-full object-cover transition group-hover:scale-[1.02]" />
          : <div className="flex size-full items-center justify-center text-xs uppercase tracking-wider text-mute">{KIND_LABEL[r.kind] || "File"}</div>}
        <span className="absolute left-2 top-2 rounded bg-black/55 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-white">{KIND_LABEL[r.kind] || r.kind}</span>
        {r.sensitive && <span className="absolute right-2 top-2 rounded bg-amber-500/90 px-1.5 py-0.5 text-[10px] font-medium text-black">sensitive</span>}
      </button>
      <div className="flex flex-1 flex-col gap-1.5 p-3">
        <h3 className="line-clamp-2 text-sm font-medium leading-snug">{r.title || r.name}</h3>
        {r.description && <p className="line-clamp-3 text-xs leading-relaxed text-mute">{r.description}</p>}
        {!r.title && <p className="text-xs text-mute">{r.status === "done" ? "No preview in Drive" : "Not looked at yet"} — found by its name or folder.</p>}
        <p className="mt-auto truncate pt-1 text-[11px] text-mute" title={r.folder}>{r.folder || "My Drive"}</p>
        <div className="flex items-center gap-1.5 pt-1">
          <button onClick={() => window.lens.open(r.url)} className="rounded-md bg-accent px-2.5 py-1 text-xs text-accent-ink">Open in Drive</button>
          {r.folderUrl && <button onClick={() => window.lens.open(r.folderUrl)} className="truncate rounded-md border border-line px-2.5 py-1 text-xs hover:bg-bg" title={`Open folder: ${r.folder}`}>{folderName}</button>}
          <span className="ml-auto text-[10px] text-mute" title={r.why.map((w) => w.by === "meaning" ? `meaning #${w.rank} (similarity ${w.sim})` : `${WHY_LABEL[w.by]} #${w.rank}`).join(", ")}>
            {[...new Set(r.why.map((w) => (w.by === "meaning" ? "meaning" : w.by === "any" ? "some words" : "words")))].join(" + ")}
          </span>
        </div>
      </div>
    </article>
  );
}

function ModelBadge({ m }: { m: ModelState }) {
  if (m.state === "ready") return <span className="text-xs text-mute">● search model ready</span>;
  if (m.state === "error") return <span className="max-w-xs truncate text-xs text-red-500" title={m.error}>Search model failed: words only</span>;
  return <span className="text-xs text-mute">Loading search model… {m.progress > 0 && m.progress < 1 ? `${Math.round(m.progress * 100)}%` : ""}</span>;
}

function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="mx-auto mt-16 max-w-md text-center">
      <h2 className="text-base font-medium">{title}</h2>
      <div className="mt-2 text-sm text-mute">{children}</div>
    </div>
  );
}

function Lens() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" className="text-accent" aria-hidden>
      <circle cx="10.5" cy="10.5" r="6.5" stroke="currentColor" strokeWidth="2" />
      <path d="M15.5 15.5 21 21" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
