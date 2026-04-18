/**
 * main.js — Electron main process for OfficePilot AI
 *
 * Backend auto-start strategy
 * ────────────────────────────
 * Development mode  (npm start / electron .):
 *   • Python exe  : <project>/venv/Scripts/python.exe
 *   • Script      : <project>/run.py           (reload=True for hot-reload)
 *   • CWD         : <project root>
 *
 * Packaged mode  (portable .exe built by electron-builder):
 *   • Python exe  : discovered from LOCALAPPDATA/Programs/Python/ or PATH
 *   • Script      : <resourcesPath>/backend/run_prod.py  (reload=False)
 *   • CWD         : <resourcesPath>/backend
 *   • Env vars    : OFFICEPILOT_RESOURCE_DIR, OFFICEPILOT_DATA_DIR
 *
 * On startup:
 *   1. Pre-flight health check — if port 8000 already answers, skip spawn
 *   2. Otherwise spawn Python, poll health every second (up to 40 s)
 *   3. Send IPC 'backend-status' to renderer on every state change
 */

const { app, BrowserWindow, ipcMain, shell } = require('electron')
const { spawn }  = require('child_process')
const path       = require('path')
const fs         = require('fs')
const http       = require('http')

// ── Configuration ──────────────────────────────────────────────────────────────

const BACKEND_URL  = 'http://127.0.0.1:8000'
const HEALTH_PATH  = '/quotations/health'
const IS_PACKAGED  = app.isPackaged
const DEV_MODE     = process.argv.includes('--dev')

// Project root (parent of this desktop-app folder) — dev mode only
const PROJECT_ROOT = path.join(__dirname, '..')

// ── State ──────────────────────────────────────────────────────────────────────

let mainWindow   = null
let backendProc  = null
let backendReady = false

// ── Path helpers ───────────────────────────────────────────────────────────────

/**
 * Directory that contains run_prod.py / run.py and the app/ sub-folder.
 * In packaged mode this is extraResources/backend/.
 */
function getBackendDir () {
  return IS_PACKAGED
    ? path.join(process.resourcesPath, 'backend')
    : PROJECT_ROOT
}

/**
 * Entry-point script to pass to Python.
 * Use run_prod.py in packaged mode (no reload), run.py in dev mode.
 */
function getRunScript () {
  const dir = getBackendDir()
  return IS_PACKAGED
    ? path.join(dir, 'run_prod.py')
    : path.join(dir, 'run.py')
}

/**
 * Find the best Python executable available.
 *
 * Order of preference:
 *  1. Venv Python (dev mode only — packages are definitely installed here)
 *  2. LOCALAPPDATA/Programs/Python/PythonXXX/  (newest version first)
 *  3. Common global install paths
 *  4. 'python' / 'python3' from PATH
 */
function findPython () {
  const candidates = []

  if (!IS_PACKAGED) {
    // Dev: venv has the exact packages we need
    candidates.push(
      path.join(PROJECT_ROOT, 'venv', 'Scripts', 'python.exe'),
      path.join(PROJECT_ROOT, 'venv', 'bin', 'python3'),
    )
  }

  // LOCALAPPDATA\Programs\Python — standard Windows installer location
  const localAppData = process.env.LOCALAPPDATA || ''
  const pythonProgramsDir = path.join(localAppData, 'Programs', 'Python')
  if (fs.existsSync(pythonProgramsDir)) {
    try {
      fs.readdirSync(pythonProgramsDir)
        .filter(d => /^Python\d+$/.test(d))
        // Sort descending so Python314 comes before Python311
        .sort((a, b) => {
          const na = parseInt(a.replace('Python', ''), 10)
          const nb = parseInt(b.replace('Python', ''), 10)
          return nb - na
        })
        .forEach(ver => {
          candidates.push(path.join(pythonProgramsDir, ver, 'python.exe'))
        })
    } catch { /* ignore read errors */ }
  }

  // Common global install paths
  candidates.push(
    'C:\\Python314\\python.exe',
    'C:\\Python313\\python.exe',
    'C:\\Python312\\python.exe',
    'C:\\Python311\\python.exe',
    'C:\\Python310\\python.exe',
  )

  // PATH fallback
  candidates.push('python', 'python3')

  const found = candidates.find(p => {
    try {
      return path.isAbsolute(p) ? fs.existsSync(p) : true
    } catch { return false }
  })

  console.log('[backend] Python candidate selected:', found)
  return found || 'python'
}

/**
 * Environment variables to pass to the Python process.
 * In packaged mode, tell the backend where its resources and writable data live.
 */
function getBackendEnv () {
  const env = { ...process.env }

  if (IS_PACKAGED) {
    const backendDir = getBackendDir()
    // config.py uses this to locate the Excel template
    env.OFFICEPILOT_RESOURCE_DIR = backendDir
    // company_memory.py uses this to locate (and write) companies.json
    env.OFFICEPILOT_DATA_DIR = app.getPath('userData')
  }

  return env
}

// ── Window ─────────────────────────────────────────────────────────────────────

function createWindow () {
  mainWindow = new BrowserWindow({
    width:           960,
    height:          780,
    minWidth:        760,
    minHeight:       600,
    title:           'OfficePilot AI',
    backgroundColor: '#0d0f1a',
    show:            false,
    webPreferences: {
      preload:          path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration:  false,
      sandbox:          false,
    },
  })

  mainWindow.setMenuBarVisibility(false)
  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'))

  if (DEV_MODE) {
    mainWindow.webContents.openDevTools({ mode: 'detach' })
  }

  mainWindow.once('ready-to-show', () => {
    mainWindow.show()
    // Re-send current status once renderer is fully visible
    notifyRenderer('backend-status', backendReady
      ? { running: true,  message: 'Backend connected' }
      : { running: false, message: 'Starting backend…' })
  })

  mainWindow.on('closed', () => { mainWindow = null })
}

// ── IPC helpers ────────────────────────────────────────────────────────────────

function notifyRenderer (channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, payload)
  }
}

// ── Health check ───────────────────────────────────────────────────────────────

/** Single async health check — resolves true/false. */
function checkHealth () {
  return new Promise(resolve => {
    const req = http.get(`${BACKEND_URL}${HEALTH_PATH}`, res => {
      backendReady = res.statusCode === 200
      res.resume()
      resolve(backendReady)
    })
    req.on('error', () => resolve(false))
    req.setTimeout(2000, () => { req.destroy(); resolve(false) })
  })
}

// ── Backend spawn ──────────────────────────────────────────────────────────────

function startBackend () {
  const runScript = getRunScript()
  const backendDir = getBackendDir()

  if (!fs.existsSync(runScript)) {
    const msg = `Backend script not found: ${runScript}`
    console.error('[backend]', msg)
    notifyRenderer('backend-status', { running: false, message: msg })
    return
  }

  const pythonExe = findPython()
  const env = getBackendEnv()

  console.log('[backend] Spawning:', pythonExe, runScript)
  console.log('[backend] CWD:', backendDir)
  if (IS_PACKAGED) {
    console.log('[backend] OFFICEPILOT_RESOURCE_DIR:', env.OFFICEPILOT_RESOURCE_DIR)
    console.log('[backend] OFFICEPILOT_DATA_DIR:    ', env.OFFICEPILOT_DATA_DIR)
  }

  backendProc = spawn(pythonExe, [runScript], {
    cwd:         backendDir,
    env,
    stdio:       ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  })

  backendProc.stdout.on('data', d => process.stdout.write(`[py] ${d}`))
  backendProc.stderr.on('data', d => process.stderr.write(`[py] ${d}`))

  backendProc.on('error', err => {
    console.error('[backend] Spawn error:', err.message)
    notifyRenderer('backend-status', {
      running: false,
      message: `Cannot start backend: ${err.message}`,
    })
  })

  backendProc.on('exit', (code, signal) => {
    console.log(`[backend] Exited — code: ${code}, signal: ${signal}`)
    backendReady = false
    backendProc  = null
    notifyRenderer('backend-status', { running: false, message: 'Backend stopped.' })
  })

  notifyRenderer('backend-status', { running: false, message: 'Starting backend…' })
}

// ── Health polling ─────────────────────────────────────────────────────────────

function pollBackendHealth (attempt = 0, max = 40) {
  checkHealth().then(ok => {
    if (ok) {
      console.log('[backend] Ready after', attempt + 1, 'poll(s).')
      notifyRenderer('backend-status', { running: true, message: 'Backend connected' })
    } else if (attempt < max) {
      setTimeout(() => pollBackendHealth(attempt + 1, max), 1000)
    } else {
      console.warn('[backend] Health timeout after', max, 'seconds.')
      notifyRenderer('backend-status', {
        running: false,
        message: 'Backend did not start. Check that Python and required packages are installed.',
      })
    }
  })
}

// ── Startup orchestration ──────────────────────────────────────────────────────

/**
 * Main startup sequence:
 *  1. Pre-flight: if port 8000 already answers, announce ready and stop.
 *  2. Otherwise: spawn Python, then poll until healthy (or timeout).
 */
async function initBackend () {
  console.log('[backend] Pre-flight health check…')
  const alreadyRunning = await checkHealth()

  if (alreadyRunning) {
    console.log('[backend] Port 8000 already alive — skipping spawn.')
    notifyRenderer('backend-status', { running: true, message: 'Backend connected' })
    return
  }

  startBackend()
  // Give the process a moment to bind the port before polling
  setTimeout(() => pollBackendHealth(), 1500)
}

// ── IPC handlers ───────────────────────────────────────────────────────────────

ipcMain.handle('open-path', async (_, targetPath) => {
  try   { await shell.openPath(targetPath); return { ok: true } }
  catch (err) { return { ok: false, error: err.message } }
})

ipcMain.handle('show-in-folder', async (_, filePath) => {
  try   { shell.showItemInFolder(filePath); return { ok: true } }
  catch (err) { return { ok: false, error: err.message } }
})

ipcMain.handle('check-backend', async () => {
  const ok = await checkHealth()
  return { running: ok }
})

ipcMain.handle('get-app-info', () => ({
  version: app.getVersion(),
  name:    app.getName(),
}))

// ── App lifecycle ──────────────────────────────────────────────────────────────

app.whenReady().then(async () => {
  createWindow()
  await initBackend()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

function killBackend () {
  if (backendProc) {
    console.log('[backend] Killing backend process…')
    backendProc.kill()
    backendProc = null
  }
}

app.on('window-all-closed', () => {
  killBackend()
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', killBackend)
