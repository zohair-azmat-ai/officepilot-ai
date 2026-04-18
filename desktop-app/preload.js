/**
 * preload.js — Secure bridge between the Electron main process and the renderer.
 *
 * contextBridge exposes a typed API surface to the renderer page.
 * The renderer can only call functions defined here — it cannot access Node.js
 * modules directly (contextIsolation: true keeps them separated).
 *
 * All ipcRenderer calls are wrapped so the renderer never touches IPC directly.
 */

const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {

  // ── Backend lifecycle ──────────────────────────────────────────────────────

  /**
   * Manually trigger a backend health check.
   * Returns: { running: boolean }
   */
  checkBackend: () => ipcRenderer.invoke('check-backend'),

  /**
   * Listen for backend status updates pushed from the main process.
   * callback: ({ running: boolean, message: string }) => void
   */
  onBackendStatus: (callback) => {
    ipcRenderer.on('backend-status', (_event, status) => callback(status))
  },

  // ── File system helpers ────────────────────────────────────────────────────

  /**
   * Open a path with the default Windows app (e.g., open .xlsx with Excel).
   * Returns: { ok: boolean, error?: string }
   */
  openPath: (targetPath) => ipcRenderer.invoke('open-path', targetPath),

  /**
   * Open Explorer with the file highlighted / selected.
   * Returns: { ok: boolean, error?: string }
   */
  showInFolder: (filePath) => ipcRenderer.invoke('show-in-folder', filePath),

  // ── App metadata ───────────────────────────────────────────────────────────

  /**
   * Returns: { version: string, name: string }
   */
  getAppInfo: () => ipcRenderer.invoke('get-app-info'),

})
