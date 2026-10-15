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
          : <FileTile name={r.name} kind={r.kind} />}
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

// Placeholder art for files with no Drive preview: a tile per file type.
type TileType = { label: string; color: string; icon: React.ReactNode };
const ICON = {
  sheet: <><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M4 9h16M4 15h16M10 3v18" /></>,
  doc: <><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4M9 12h6M9 15h6M9 18h4" /></>,
  slides: <><rect x="3" y="4" width="18" height="12" rx="1.5" /><path d="M12 16v4M8 20h8M7 12l3-3 2 2 4-4" /></>,
  pdf: <><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4" /><path d="M8.5 16.5c2-4 3.5-7 3.5-8.5s-1.5-1-1.5 0 2 5 5 6.5-6 .5-7 2z" /></>,
  video: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M10 9v6l5-3z" /></>,
  audio: <><path d="M4 12h2M8 8v8M12 5v14M16 9v6M20 11v2" /></>,
  archive: <><path d="M4 7h16v13H4zM3 4h18v3H3zM10 11h4" /></>,
  map: <><path d="M12 21s-6-5.5-6-11a6 6 0 0 1 12 0c0 5.5-6 11-6 11z" /><circle cx="12" cy="10" r="2.2" /></>,
  design: <><path d="M4 20l4-1 11-11-3-3L5 16z" /><path d="M14 7l3 3" /></>,
  image: <><rect x="3" y="4" width="18" height="16" rx="2" /><circle cx="9" cy="10" r="2" /><path d="M21 16l-5-5-9 9" /></>,
  file: <><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4" /></>,
};
const TYPES: Array<[RegExp, TileType]> = [
  [/^(xlsx?|csv|ods|numbers|tsv)$/, { label: "Spreadsheet", color: "#1e8e4e", icon: ICON.sheet }],
  [/^(docx?|odt|rtf|txt|pages|md)$/, { label: "Document", color: "#2b6cd4", icon: ICON.doc }],
  [/^(pptx?|key|odp)$/, { label: "Slides", color: "#d9662b", icon: ICON.slides }],
  [/^pdf$/, { label: "PDF", color: "#c93a3a", icon: ICON.pdf }],
  [/^(mp4|mov|m4v|avi|wmv|mpe?g|mkv|webm|mts|3gp|flv|vob|m2ts)$/, { label: "Video", color: "#7b4fd6", icon: ICON.video }],
  [/^(mp3|wav|m4a|aac|ogg|flac|opus)$/, { label: "Audio", color: "#138a8a", icon: ICON.audio }],
  [/^(zip|rar|7z|tar|gz|tgz|bz2)$/, { label: "Archive", color: "#b7791f", icon: ICON.archive }],
  [/^(gpx|kml|kmz|geojson|shp)$/, { label: "Map / GPS", color: "#2f855a", icon: ICON.map }],
  [/^(ai|psd|indd|eps|svg|sketch|fig|xd|cdr)$/, { label: "Design file", color: "#c2417a", icon: ICON.design }],
  [/^(jpe?g|png|heic|heif|webp|gif|tiff?|nef|cr2|arw|dng|bmp)$/, { label: "Image", color: "#5a6b7d", icon: ICON.image }],
];
const KIND_TILE: Record<string, TileType> = {
  document: { label: "Google file", color: "#2b6cd4", icon: ICON.doc },
  video: TYPES[4][1], image: TYPES[9][1], pdf: TYPES[3][1],
};

function FileTile({ name, kind }: { name: string; kind: string }) {
  const ext = name.includes(".") ? name.split(".").pop()!.toLowerCase() : "";
  const t = TYPES.find(([re]) => re.test(ext))?.[1] ?? KIND_TILE[kind] ?? { label: "File", color: "#6b7268", icon: ICON.file };
  return (
    <div className="flex size-full flex-col items-center justify-center gap-2" style={{ background: `linear-gradient(135deg, ${t.color}26, ${t.color}0d)` }}>
      <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke={t.color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden>{t.icon}</svg>
      <span className="rounded px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-white" style={{ background: t.color }}>{ext && ext.length <= 5 ? ext : t.label}</span>
      <span className="text-[11px] text-mute">{t.label} · no preview</span>
    </div>
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
