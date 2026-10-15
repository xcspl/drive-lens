// The window's only door to the main process.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("lens", {
  info: () => ipcRenderer.invoke("index:info"),
  chooseIndex: () => ipcRenderer.invoke("index:choose"),
  modelStatus: () => ipcRenderer.invoke("model:status"),
  onModel: (fn) => {
    const h = (_e, m) => fn(m);
    ipcRenderer.on("model", h);
    return () => ipcRenderer.removeListener("model", h);
  },
  search: (q, opts) => ipcRenderer.invoke("search", q, opts),
  open: (url) => ipcRenderer.invoke("open", url),
});
