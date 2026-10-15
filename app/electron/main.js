// Drive Lens: the desktop search app. The main process owns the index
// (SQLite + sqlite-vec) and the query model (ONNX); the window only asks.
import { app, BrowserWindow, dialog, ipcMain, shell } from "electron";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadEmbedder } from "./embedder.js";
import { info, openIndex, search } from "./search.js";

const here = path.dirname(fileURLToPath(import.meta.url));
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

/** The index to open at start: the last one used, else one found next to the app (development). */
function initialIndex() {
  const last = readSettings().indexPath;
  if (last && fs.existsSync(last)) return last;
  const dataDir = path.resolve(here, "..", "..", "data");
  try {
    for (const d of fs.readdirSync(dataDir)) {
      const p = path.join(dataDir, d, "index.db");
      if (fs.existsSync(p)) return p;
    }
  } catch { /* no data folder */ }
  return "";
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
ipcMain.handle("open", (_e, url) => {
  // Only Drive links leave the app.
  if (/^https:\/\/drive\.google\.com\//.test(String(url))) shell.openExternal(url);
});

function createWindow() {
  win = new BrowserWindow({
    width: 1280, height: 860, minWidth: 720, minHeight: 520,
    title: "Drive Lens",
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
  const p = initialIndex();
  if (p) tryOpen(p);
  createWindow();
  startModel();
});
app.on("window-all-closed", () => app.quit());
