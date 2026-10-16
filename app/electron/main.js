// Drive Lens: the desktop search app. The main process owns the index
// (SQLite + sqlite-vec) and the query model (ONNX); the window only asks.
import { app, BrowserWindow, dialog, ipcMain, shell } from "electron";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadEmbedder } from "./embedder.js";
import { browse, info, openIndex, search } from "./search.js";

const here = path.dirname(fileURLToPath(import.meta.url));

// Settings shared with the indexer: the repo's .env (when the app runs from
// a checkout), overridden by real environment variables. Only DRIVE_LENS_*
// keys are read; the LLM key is never needed here.
const envFile = process.env.DRIVE_LENS_ENV || path.resolve(here, "..", "..", ".env");
function readEnv(file) {
  const out = {};
  try {
    for (let line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
      line = line.trim();
      if (!line || line.startsWith("#") || !line.includes("=")) continue;
      const i = line.indexOf("=");
      const k = line.slice(0, i).trim();
      if (k.startsWith("DRIVE_LENS_")) out[k] = line.slice(i + 1).split(/\s+#/)[0].trim().replace(/^(["'])(.*)\1$/, "$2");
    }
  } catch { /* no .env: defaults */ }
  return out;
}
const conf = { ...readEnv(envFile), ...Object.fromEntries(Object.entries(process.env).filter(([k]) => k.startsWith("DRIVE_LENS_"))) };
const fromEnvDir = (p) => (path.isAbsolute(p) ? p : path.resolve(path.dirname(envFile), p));
const settingsFile = () => path.join(app.getPath("userData"), "settings.json");
const readSettings = () => { try { return JSON.parse(fs.readFileSync(settingsFile(), "utf8")); } catch { return {}; } };
const writeSettings = (s) => { fs.mkdirSync(path.dirname(settingsFile()), { recursive: true }); fs.writeFileSync(settingsFile(), JSON.stringify(s, null, 1)); };

let win = null;
let model = { state: "idle", progress: 0, error: "" };
const send = (ch, data) => win?.webContents.send(ch, data);

function setModel(patch) {
  model = { ...model, ...patch };
  send("model", model);
}

function startModel() {
  if (model.state === "loading" || model.state === "ready") return;
  setModel({ state: "loading", progress: 0, error: "" });
  const files = {};
  loadEmbedder({
    model: conf.DRIVE_LENS_QUERY_MODEL || undefined,
    bundledDir: app.isPackaged ? path.join(process.resourcesPath, "models") : path.resolve(here, "..", "models"),
    queryPrefix: conf.DRIVE_LENS_QUERY_PREFIX || undefined,
    cacheDir: path.join(app.getPath("userData"), "models"),
    onProgress: (p) => {
      if (p.status === "progress" && p.total) {
        files[p.file] = [p.loaded, p.total];
        const [l, t] = Object.values(files).reduce(([a, b], [x, y]) => [a + x, b + y], [0, 0]);
        setModel({ progress: t ? l / t : 0 });
      }
    },
  }).then(() => setModel({ state: "ready", progress: 1 }), (e) => setModel({ state: "error", error: String(e?.message || e) }));
}

/** The folders an installed app sits in. Packaged apps run from inside a
 *  bundle or a temporary mount, so the folder the user sees is found per
 *  format: Windows portable exe, Linux AppImage, macOS .app, else the exe's. */
function besideApp() {
  if (!app.isPackaged) return [];
  const dirs = [process.env.PORTABLE_EXECUTABLE_DIR, process.env.APPIMAGE && path.dirname(process.env.APPIMAGE)];
  const exe = app.getPath("exe");
  const bundle = exe.match(/^(.*)[\\/][^\\/]+\.app[\\/]Contents[\\/]MacOS[\\/]/);
  dirs.push(bundle ? bundle[1] : path.dirname(exe));
  return [...new Set(dirs.filter(Boolean))];
}

/** .db files in a folder, newest first. */
function dbFiles(dir) {
  try {
    return fs.readdirSync(dir).filter((f) => f.toLowerCase().endsWith(".db"))
      .map((f) => path.join(dir, f)).sort((x, y) => fs.statSync(y).mtimeMs - fs.statSync(x).mtimeMs);
  } catch { return []; }
}

/** Indexes to try at start, in order: DRIVE_LENS_DB; the one last opened
 *  (with Open index…); a .db next to the app (so an index handed out in the
 *  same folder as the app just opens); the data folder of a checkout
 *  (DRIVE_LENS_DATA, default ../data). The first that opens wins. */
function initialIndexes() {
  const out = [];
  if (conf.DRIVE_LENS_DB) out.push(fromEnvDir(conf.DRIVE_LENS_DB));
  const last = readSettings().indexPath;
  if (last) out.push(last);
  for (const d of besideApp()) out.push(...dbFiles(d));
  const dataDir = conf.DRIVE_LENS_DATA ? fromEnvDir(conf.DRIVE_LENS_DATA) : path.resolve(here, "..", "..", "data");
  try {
    for (const d of fs.readdirSync(dataDir)) out.push(path.join(dataDir, d, "index.db"));
  } catch { /* no data folder */ }
  out.push(...dbFiles(dataDir));
  return [...new Set(out)].filter((p) => fs.existsSync(p));
}

function tryOpen(p) {
  try {
    const i = openIndex(p);
    writeSettings({ ...readSettings(), indexPath: p });
    return { ok: true, info: i };
  } catch (e) {
    return { ok: false, error: String(e?.message || e) };
  }
}

ipcMain.handle("index:info", () => info());
ipcMain.handle("index:choose", async () => {
  const r = await dialog.showOpenDialog(win, { title: "Open a drive-lens index", properties: ["openFile"], filters: [{ name: "drive-lens index", extensions: ["db"] }] });
  if (r.canceled || !r.filePaths[0]) return { ok: false, canceled: true };
  return tryOpen(r.filePaths[0]);
});
ipcMain.handle("model:status", () => model);
ipcMain.handle("search", async (_e, q, opts) => {
  try {
    return { ok: true, results: await search(String(q || ""), opts || {}) };
  } catch (e) {
    return { ok: false, error: String(e?.message || e) };
  }
});
ipcMain.handle("browse", (_e, opts) => {
  try {
    return { ok: true, ...browse(opts || {}) };
  } catch (e) {
    return { ok: false, error: String(e?.message || e) };
  }
});
ipcMain.handle("open", (_e, url) => {
  // Only Drive links leave the app.
  if (/^https:\/\/drive\.google\.com\//.test(String(url))) shell.openExternal(url);
});

function createWindow() {
  win = new BrowserWindow({
    width: 1280, height: 860, minWidth: 720, minHeight: 520,
    title: "Drive Lens",
    icon: path.join(here, "..", "build", "icon.png"),
    backgroundColor: "#0b0d10",
    webPreferences: { preload: path.join(here, "preload.cjs"), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  win.removeMenu();
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https:\/\/drive\.google\.com\//.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  win.loadFile(path.join(here, "..", "dist", "index.html"));
}

app.whenReady().then(() => {
  for (const p of initialIndexes()) if (tryOpen(p).ok) break;
  createWindow();
  startModel();
});
app.on("window-all-closed", () => app.quit());
