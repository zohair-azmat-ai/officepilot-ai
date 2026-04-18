# OfficePilot AI — Desktop App

Windows desktop wrapper for the OfficePilot AI quotation automation backend.
Built with Electron. The FastAPI backend runs as a local process; the Electron
window is the UI shell that communicates with it.

---

## Architecture

```
OfficePilot AI (Electron window)
        │
        │  fetch()   POST /quotations/create
        ▼
FastAPI backend (Python, port 8000)
        │
        ├── ref_parser    — scans G:\...\Quotation\2026\04
        ├── excel_writer  — fills openpyxl template
        └── pdf_export    — LibreOffice headless
```

The Electron **main process** (`main.js`) auto-starts the Python backend
as a child process when the app opens, and kills it when the app closes.
You do not need to start the backend manually in normal use.

---

## Quick Start (Development)

### Step 1 — Install Node.js

Download and install Node.js (LTS) from https://nodejs.org  
Check it works: `node --version` and `npm --version`

### Step 2 — Install Python dependencies (first time only)

```cmd
cd "c:\Users\Zohair\Desktop\Zohair\OfficePilot AI\quotation-agent"
venv\Scripts\activate
pip install -r requirements.txt
```

### Step 3 — Generate the Excel template (first time only)

```cmd
cd "c:\Users\Zohair\Desktop\Zohair\OfficePilot AI\quotation-agent"
venv\Scripts\activate
python create_template.py
```

### Step 4 — Install Electron dependencies

```cmd
cd "c:\Users\Zohair\Desktop\Zohair\OfficePilot AI\quotation-agent\desktop-app"
npm install
```

### Step 5 — Run in development mode

```cmd
npm run dev
```

The app window opens. The backend auto-starts in the background.
You will see `[py]` prefixed log output in the terminal.

---

## Starting the Backend Manually (if auto-start fails)

```cmd
cd "c:\Users\Zohair\Desktop\Zohair\OfficePilot AI\quotation-agent"
venv\Scripts\activate
python run.py
```

Then launch the desktop app separately:
```cmd
cd desktop-app
npm start
```

---

## NPM Scripts

| Command               | What it does                                      |
|-----------------------|---------------------------------------------------|
| `npm start`           | Start Electron app (expects backend already up)   |
| `npm run dev`         | Start with DevTools panel open                    |
| `npm run build`       | Build both portable .exe and NSIS installer       |
| `npm run build:portable`  | Build portable single-file .exe only          |
| `npm run build:installer` | Build NSIS Windows installer only             |

---

## Building the Windows .exe

```cmd
cd "c:\Users\Zohair\Desktop\Zohair\OfficePilot AI\quotation-agent\desktop-app"
npm run build:portable
```

Output will be in `desktop-app\dist\`.

> **Important:** The packaged `.exe` does NOT bundle Python.
> Your machine must have Python (with venv and dependencies installed) for the
> backend to work when the app starts. The `.exe` packages only the Electron
> UI shell + backend source files (in `resources/backend/`).

---

## How Electron Connects to FastAPI

1. `main.js` spawns `python run.py` from the `quotation-agent/` directory.
2. It polls `GET /quotations/health` every second until the backend responds.
3. The **titlebar status indicator** shows `Backend connected` (green) when ready.
4. The renderer calls `POST /quotations/create` via `fetch()` in `app.js`.
5. Results are displayed in the result card below the form.
6. File path buttons use Electron IPC → `shell.showItemInFolder()` to open Explorer.

---

## Troubleshooting

### Backend not running / "Cannot connect to backend"

**Symptom:** Status indicator shows red, form submission fails.

**Fixes:**
1. Check the terminal where you ran `npm run dev` for Python error output.
2. Manually run `python run.py` in the `quotation-agent/` folder to see the error.
3. Make sure the venv was activated and `pip install -r requirements.txt` completed.
4. Check that port 8000 is not blocked by another app:
   ```cmd
   netstat -ano | findstr :8000
   ```
5. Click the **⟳** refresh button in the titlebar to retry the health check.

---

### Template file missing

**Symptom:** API returns 404 "Excel template not found at …"

**Fix:**
```cmd
cd quotation-agent
venv\Scripts\activate
python create_template.py
```

Or update `TEMPLATE_PATH` in `quotation-agent/.env` to point to your own template.

---

### Folder not found (G:\ drive not available)

**Symptom:** API returns 404 "Folder not found: G:\..."

**Fixes:**
1. Make sure your G: drive is connected and accessible.
2. Update `QUOTATION_BASE_PATH` in `quotation-agent/.env`:
   ```
   QUOTATION_BASE_PATH=D:\My Quotations
   ```
3. The year/month sub-folder is auto-created if it doesn't exist.

---

### LibreOffice not installed — PDF export skipped

**Symptom:** Result shows `pdf_status: skipped`, no PDF file created.

**Behavior:** This is expected — the Excel file is still created successfully.

**Fix:** Install LibreOffice from https://www.libreoffice.org/download/  
Default expected path: `C:\Program Files\LibreOffice\program\soffice.exe`

If installed elsewhere, add the path to `LIBREOFFICE_PATHS` in `quotation-agent/app/config.py`.

---

### Windows Defender / Antivirus blocks the .exe

Electron apps built with electron-builder are sometimes flagged by AV software
because they're unsigned. Options:
- Add an exclusion for the `dist/` folder in Windows Security
- Sign the executable with a code-signing certificate (beyond MVP scope)

---

## File Structure

```
desktop-app/
  main.js          ← Electron main process (window, backend lifecycle, IPC)
  preload.js       ← Secure bridge: exposes electronAPI to renderer
  renderer/
    index.html     ← App window HTML (two tabs: Create Quotation, Quick Command)
    style.css      ← Dark navy theme stylesheet
    app.js         ← Frontend logic (form handling, fetch, result display)
  package.json     ← npm config + electron-builder packaging config
  README.md        ← This file
```

---

## Customising the App

| What                         | Where to change                                |
|------------------------------|------------------------------------------------|
| Quotation base folder        | `quotation-agent/.env` → `QUOTATION_BASE_PATH` |
| Excel template path          | `quotation-agent/.env` → `TEMPLATE_PATH`       |
| Cell mapping in template     | `quotation-agent/app/config.py` → `CELL_MAP`   |
| App window size              | `main.js` → `width`, `height` in `new BrowserWindow(…)` |
| Backend port                 | `quotation-agent/.env` → `APP_PORT` and `renderer/app.js` → `BACKEND_BASE` |
| App icon (.ico)              | Place `icon.ico` in `desktop-app/build/` and update `package.json` build config |

---

## Next Phase Ideas

- **Auto-update:** `electron-updater` to push updates to installed copies
- **Tray icon:** Minimize to system tray, backend stays running
- **Salary module:** Add "Create Salary Slip" tab (backend already designed for this)
- **Invoice module:** Add "Create Invoice" tab
- **Quick Command (Tab 2):** Connect to an LLM to parse natural-language instructions
  into structured form data before calling the API
- **History panel:** List recently created quotations by scanning the output folder
