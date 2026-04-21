---
title: OfficePilot AI Backend
emoji: 🏢
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

<div align="center">

# 🏢 OfficePilot AI

**Self-hosted Windows business automation — quotations, ledger, statements, OCR, and document delivery via Telegram.**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![OCR Ready](https://img.shields.io/badge/OCR-Ready-FF6B35?style=for-the-badge&logo=googlelens&logoColor=white)](#-ocr-invoice-extraction)
[![PDF Statements](https://img.shields.io/badge/PDF-Statements-E74C3C?style=for-the-badge&logo=adobeacrobatreader&logoColor=white)](#-account-statement-generation)
[![Ledger](https://img.shields.io/badge/AR-Ledger-27AE60?style=for-the-badge&logo=microsoftexcel&logoColor=white)](#-customer-ledger--ar-module)
[![Desktop App](https://img.shields.io/badge/Desktop-Electron-47848F?style=for-the-badge&logo=electron&logoColor=white)](#-desktop-app)
[![Windows First](https://img.shields.io/badge/Windows-First-0078D6?style=for-the-badge&logo=windows&logoColor=white)](#-windows-auto-start)
[![Local First](https://img.shields.io/badge/Storage-Local--First-8E44AD?style=for-the-badge&logo=files&logoColor=white)](#-local-first-storage)
[![License](https://img.shields.io/badge/License-MIT-2ECC71?style=for-the-badge)](LICENSE)

</div>

---

## 🎯 What Is This?

OfficePilot AI is a **self-hosted, Windows-first office automation platform** built for small businesses that need professional-grade tools without cloud subscriptions or IT overhead.

- Send a quotation command from your **phone via Telegram** — get Excel + PDF back in seconds
- Photograph an **invoice** and OCR extracts company, amount, and date automatically
- Say **`send trade license`** and the bot fetches and delivers the document instantly
- **Account statements** are generated as professional A4 PDFs with letterhead
- Every file stays **100% local** on your Windows machine — no cloud, no SaaS

---

## 🗺️ Architecture

```
User (Mobile / Desktop)
        │
        ▼
┌──────────────────────────────────────────────────────┐
│            Telegram Bot  /  Desktop App (Electron)   │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│           FastAPI Backend  ·  127.0.0.1:8000         │
│                                                      │
│  Parser → Company Memory → Quotation Engine          │
│         → Ledger Module  → Statement Generator       │
│         → OCR Parser     → Document Fetcher          │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
         Excel / PDF / Local Files on Windows Drive
    (Quotation  ·  Ledger  ·  Statement  ·  Documents)
```

---

## ✨ Features

### 📋 Quotation Generation

- Natural-language commands: `make quotation for COMPANY item 1: ...`
- Sequential reference number auto-detection by scanning existing files
- Multi-item quotations with auto-calculated subtotal + 5% VAT
- Fills Excel template — company header, items, totals, ref number, date
- Auto-exports PDF via LibreOffice headless
- Windows-safe filenames: `18-04-2026 ref# 2705 GULF EXTRUSION.xlsx`
- Bot delivers both Excel and PDF via `sendDocument`

**Example:**
```
make quotation for Gulf Extrusion
item 1: SS roller fabrication, qty 2, price 500 each
item 2: teflon round bar, qty 1, price 350 each
```

---

### 🧠 Company Memory & Aliases

- Stores company name, ATTN, TRN, phone, fax per client
- Fuzzy / alias matching — `gulf` resolves to `GULF EXTRUSION COMPANY LLC`
- Auto-fills all form fields when a known company is detected
- Pre-loaded aliases: `gulf`, `islami`, `quant`, `globol`, `tayseer arar`, `tayseer containers`
- Persisted in `data/companies.json`

---

### 📒 Customer Ledger / AR Module

- Excel-based ledger file per company (`G:\...\Ledger\2026\COMPANY.xlsx`)
- Tracks debit (invoiced), credit (paid), and running balance
- Date-stamped entries with optional LPO number
- Company alias resolution on every command

```
create ledger for gulf
add ledger gulf invoice 2705 debit 5000
add ledger gulf invoice 2705 debit 5000 lpo 45892
ledger gulf
balance gulf
outstanding gulf
```

---

### 💳 Payment Tracking

- `payment received for COMPANY invoice NUMBER amount AMOUNT`
- Logs credit entries to the company ledger
- Instantly replies with updated outstanding balance
- Optional `date DD-MM-YYYY` override

---

### 📊 Account Statement Generation

- Professional A4 portrait PDF with full company letterhead
- Columns: Date · Invoice No · LPO · Debit (AED) · Credit (AED) · Balance (AED)
- Opening balance computed from all prior-period entries
- Closing balance, amount-in-words footer (AED Fourteen Thousand Dirhams Only)
- Signature block: *for DAR AL SALAM ENG. TURNING WORKS W/SHOP*
- `fitToWidth=1`, explicit print area — single page, no split
- Save path: `G:\...\Account Statement\YEAR\MM\COMPANY_YYYY-MM.xlsx / .pdf`

```
statement gulf april 2026
statement gulf 04 2026 unpaid
statement gulf april 2026 pdf
```

---

### 🔍 OCR Invoice Extraction

- Send a **photo or PDF** of any invoice to the Telegram bot
- Extracts: company name, invoice number, date, total amount, LPO number
- Preprocessing: EXIF rotation fix → grayscale → autocontrast → 2400px upscale → sharpen
- Zone-based OCR: top-left for invoice number, top-right for date, bottom-right for amount
- Template detection for Dar Al Salam / DTW invoices with seller/customer disambiguation
- After extraction, bot prompts: **YES** to add to ledger · **NO** to cancel · `correct FIELD VALUE` to fix any field
- PDF fallback via pdfplumber (works without Tesseract); photo OCR requires Tesseract

---

### 📎 Document Fetch

Deliver any document stored in the official documents folder directly via Telegram:

```
send trade license
send shed contract
send municipality
send doc2
```

- Case-insensitive partial filename matching
- One match → sends file immediately: *"Sending: Trade License.pdf"*
- Multiple matches → lists options and asks to be more specific
- No match → friendly error message
- Access locked to one fixed folder — no path traversal possible

---

### 🖥️ Desktop App

- Electron-based portable `.exe` — no install required
- Auto-starts the Python backend on launch
- Dark-themed modern UI
- Tabs: Quotation Form · Quick Command · Company Manager · Ledger View

---

### 🪟 Windows Auto-Start

- `install_task.ps1` registers a Windows Task Scheduler task
- Backend (and Telegram bot) starts silently at every Windows login
- `startup.log` captures backend output for debugging
- No terminal window required

---

### 💾 Local-First Storage

| Data | Location |
|------|----------|
| Quotation Excel + PDF | `G:\...\Quotation\YEAR\MM\` |
| Company Ledgers | `G:\...\Ledger\2026\COMPANY.xlsx` |
| Account Statements | `G:\...\Account Statement\YEAR\MM\` |
| Official Documents | `G:\...\Offical Documents 2026\` |
| Company Memory | `data/companies.json` |
| Excel Template | `templates/quotation_template.xlsx` |

Everything stays on your local drive. No cloud upload, no external API calls except Telegram bot messaging.

---

## 🆕 What's New — Latest Updates

| Feature | Details |
|---------|---------|
| **Document Fetch** | `send FILENAME` delivers any file from the official docs folder via Telegram |
| **Account Statements** | A4 portrait PDF with letterhead, LPO column, opening balance, amount-in-words, signature |
| **OCR Invoice Parsing** | Photo/PDF → auto-extracted fields → one-tap ledger entry with correction support |
| **Excel Ledger** | Per-company `.xlsx` ledger with LPO tracking and running balance |
| **NL Quotation Input** | `make quotation for COMPANY\nitem 1: ...` multi-item natural-language format |
| **Payment Tracking** | `payment received` command with immediate outstanding balance reply |
| **Windows Auto-Start** | Task Scheduler integration via `install_task.ps1` |

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+** — [python.org/downloads](https://www.python.org/downloads/)
- **LibreOffice** (optional, for PDF export) — [libreoffice.org](https://www.libreoffice.org/download/)
- **Tesseract OCR** (optional, for invoice photo parsing) — [tesseract-ocr releases](https://github.com/tesseract-ocr/tesseract/releases)
- **Node.js 18+** (only if rebuilding the desktop app)

### 1. Clone & install

```bash
git clone https://github.com/zohair-azmat-ai/officepilot-ai.git
cd officepilot-ai
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

```bash
copy .env.example .env
```

Edit `.env`:
```env
QUOTATION_BASE_PATH=G:\YOUR\QUOTATION\FOLDER
LEDGER_BASE_PATH=G:\YOUR\LEDGER\FOLDER\2026
STATEMENT_BASE_PATH=G:\YOUR\STATEMENT\FOLDER
TEMPLATE_PATH=templates\quotation_template.xlsx
APP_HOST=127.0.0.1
APP_PORT=8000
```

### 3. Run the backend

```bash
python run.py
```

Open **http://127.0.0.1:8000** in your browser.
API docs: **http://127.0.0.1:8000/docs**

---

## 📱 Telegram Bot Setup

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token
2. Message [@userinfobot](https://t.me/userinfobot) → copy your chat ID
3. Add to `.env`:
   ```env
   TELEGRAM_ENABLED=true
   TELEGRAM_BOT_TOKEN=your_token_here
   TELEGRAM_ALLOWED_CHAT_IDS=your_chat_id_here
   ```
4. Restart the backend — the bot starts automatically.

### Full command reference

```
help                                              → show all commands

make quotation for COMPANY                        → natural-language quotation
item 1: description, qty N, price N each
item 2: description, qty N, price N each

quote for COMPANY description qty 1 rate N       → single-item quotation

create ledger for COMPANY                         → create Excel ledger
ledger COMPANY                                    → view ledger summary
balance COMPANY                                   → check outstanding balance
outstanding COMPANY                               → check outstanding balance
add ledger COMPANY invoice N debit N              → record invoice
add ledger COMPANY invoice N debit N lpo N        → record invoice + LPO number
payment received for COMPANY invoice N amount N   → record payment received

statement COMPANY MONTH YEAR                      → generate account statement
statement COMPANY MONTH YEAR unpaid               → unpaid entries only
statement COMPANY MONTH YEAR pdf                  → send as PDF

send DOCUMENT NAME                                → fetch & deliver file from docs folder

[send photo or PDF]                               → OCR extract → ledger entry
```

---

## 🏗️ Project Structure

```
officepilot-ai/
├── app/
│   ├── main.py                     # FastAPI app + bot lifespan
│   ├── config.py                   # Settings, cell map, paths, Telegram config
│   ├── api/
│   │   ├── quotation.py            # POST /quotations/create
│   │   ├── companies.py            # GET/POST /companies
│   │   └── ledger.py               # Ledger endpoints
│   ├── schemas/
│   │   ├── quotation.py            # QuotationCreateRequest / Response
│   │   ├── company.py              # CompanyRecord
│   │   └── ledger.py               # Ledger schemas
│   └── services/
│       ├── command_parser.py       # NLP regex quotation parser
│       ├── company_memory.py       # Fuzzy lookup + alias resolution
│       ├── quotation_service.py    # Quotation orchestrator
│       ├── excel_writer.py         # openpyxl template filler
│       ├── file_naming.py          # Windows-safe filename builder
│       ├── ref_parser.py           # Folder scanner for next ref number
│       ├── pdf_export.py           # LibreOffice headless PDF conversion
│       ├── ledger_excel.py         # Excel ledger CRUD + balance computation
│       ├── statement_excel.py      # A4 account statement generator
│       ├── ocr_parser.py           # Invoice OCR (pytesseract + pdfplumber)
│       ├── file_fetcher.py         # Document folder search + send
│       ├── telegram_bot.py         # Bot lifecycle (start/stop)
│       ├── telegram_handlers.py    # Message routing + all command handlers
│       └── telegram_sender.py      # send_text / send_document helpers
├── desktop-app/
│   ├── main.js                     # Electron main (backend auto-start)
│   ├── preload.js
│   └── renderer/
│       ├── index.html
│       ├── app.js
│       └── style.css
├── data/
│   └── companies.json              # Company memory (aliases, TRN, ATTN, phone, fax)
├── templates/
│   └── quotation_template.xlsx     # Excel quotation template
├── static/
│   └── index.html                  # Web frontend (served by FastAPI)
├── install_task.ps1                # Register Windows auto-start task
├── start_backend_safe.cmd          # Safe backend launcher script
├── Dockerfile                      # Docker / Hugging Face Spaces deploy
├── run.py                          # Dev launcher (with reload)
├── requirements.txt
└── .env.example                    # Config template (copy → .env)
```

---

## 📊 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/quotations/create` | Create quotation from structured data |
| `POST` | `/quotations/parse-command` | Parse natural-language command |
| `GET`  | `/quotations/health` | Liveness check |
| `GET`  | `/companies` | List all saved companies |
| `GET`  | `/companies/lookup?q=` | Fuzzy company search |
| `POST` | `/companies` | Upsert company record |

Full interactive docs: **http://127.0.0.1:8000/docs**

---

## 📦 Requirements

```
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
openpyxl>=3.1.2
pydantic>=2.11.0
pydantic-settings>=2.5.0
python-dotenv>=1.0.1
python-multipart>=0.0.9
python-telegram-bot>=20.0
pdfplumber>=0.11.0
pytesseract>=0.3.10
Pillow>=10.0.0
```

---

## 📄 License

MIT — free to use, modify, and distribute.

---

<div align="center">
Built with ❤️ for real office automation — no cloud required.
</div>
