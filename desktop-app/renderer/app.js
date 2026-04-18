'use strict'

// ── Constants ──────────────────────────────────────────────────────────────────
const BACKEND_BASE    = 'http://127.0.0.1:8000'
const CREATE_URL      = `${BACKEND_BASE}/quotations/create`
const HEALTH_URL      = `${BACKEND_BASE}/quotations/health`
const PARSE_URL       = `${BACKEND_BASE}/quotations/parse-command`
const COMPANIES_URL   = `${BACKEND_BASE}/companies`
const LOOKUP_URL      = `${BACKEND_BASE}/companies/lookup`
const LEDGER_URL      = `${BACKEND_BASE}/ledger`

// ── DOM references ─────────────────────────────────────────────────────────────
const statusDot    = document.getElementById('statusDot')
const statusText   = document.getElementById('statusText')
const retryBtn     = document.getElementById('retryBtn')
const appVersion   = document.getElementById('appVersion')
const footerMsg    = document.getElementById('footerMsg')
const quotForm     = document.getElementById('quotForm')
const submitBtn    = document.getElementById('submitBtn')
const resultCard   = document.getElementById('resultCard')
const resultHeader = document.getElementById('resultHeader')
const resultBody   = document.getElementById('resultBody')

// Quick Command DOM refs
const nlCommand       = document.getElementById('nlCommand')
const parseBtn        = document.getElementById('parseBtn')
const qcPreview       = document.getElementById('qcPreview')
const previewGrid     = document.getElementById('previewGrid')
const previewWarnings = document.getElementById('previewWarnings')
const confirmBtn      = document.getElementById('confirmBtn')
const editFormBtn     = document.getElementById('editFormBtn')
const qcResultCard    = document.getElementById('qcResultCard')
const qcResultHeader  = document.getElementById('qcResultHeader')
const qcResultBody    = document.getElementById('qcResultBody')

// Holds the last successful parse response so Confirm can re-use it
let _parsedData = null

// ── App initialisation ─────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  initTabs()
  fillDefaultDate()
  wireForm()
  wireRetryBtn()
  wireQuickCommand()
  initItemsForm()
  initCompanyAutofill()
  initLedgerModule()
  await loadAppInfo()

  if (window.electronAPI?.onBackendStatus) {
    window.electronAPI.onBackendStatus(updateBackendStatus)
  }
  checkAndUpdateStatus()
})

// ── App info ───────────────────────────────────────────────────────────────────
async function loadAppInfo () {
  try {
    const info = await window.electronAPI?.getAppInfo()
    if (info?.version) appVersion.textContent = `v${info.version}`
  } catch { /* non-critical */ }
}

// ── Backend status ─────────────────────────────────────────────────────────────
function updateBackendStatus ({ running, message }) {
  statusDot.className = `status-dot ${running ? 'online' : 'offline'}`
  statusText.textContent = running
    ? 'Backend connected'
    : (message || 'Backend not running')
  setFooter(running ? 'Ready' : 'Start the backend: python run.py')
}

async function checkAndUpdateStatus () {
  updateBackendStatus({ running: false, message: 'Connecting…' })
  statusDot.className = 'status-dot'

  try {
    if (window.electronAPI?.checkBackend) {
      const result = await window.electronAPI.checkBackend()
      updateBackendStatus(result)
    } else {
      const res = await fetch(HEALTH_URL, { signal: AbortSignal.timeout(3000) })
      updateBackendStatus({ running: res.ok })
    }
  } catch {
    updateBackendStatus({ running: false, message: 'Backend not running' })
  }
}

function wireRetryBtn () {
  retryBtn.addEventListener('click', () => {
    retryBtn.style.transform = 'rotate(360deg)'
    setTimeout(() => { retryBtn.style.transform = '' }, 400)
    checkAndUpdateStatus()
  })
}

// ── Tab switching ──────────────────────────────────────────────────────────────
function initTabs () {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.tab
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'))
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'))
      btn.classList.add('active')
      document.getElementById(`tab-${target}`)?.classList.add('active')
    })
  })
}

function switchToTab (tabName) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'))
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'))
  document.querySelector(`.tab-btn[data-tab="${tabName}"]`)?.classList.add('active')
  document.getElementById(`tab-${tabName}`)?.classList.add('active')
}

// ── Date helpers ───────────────────────────────────────────────────────────────
function fillDefaultDate () {
  const now  = new Date()
  const dd   = String(now.getDate()).padStart(2, '0')
  const mm   = String(now.getMonth() + 1).padStart(2, '0')
  const yyyy = String(now.getFullYear())

  document.getElementById('date').value  = `${dd}-${mm}-${yyyy}`
  document.getElementById('year').value  = yyyy
  document.getElementById('month').value = mm
}

// ── Company autofill ───────────────────────────────────────────────────────────

let _companyDebounceTimer = null
let _activeDropdownIndex  = -1
let _currentCompanyRecord = null   // last applied record; null = none / new

function initCompanyAutofill () {
  const input    = document.getElementById('client_name')
  const dropdown = document.getElementById('companyDropdown')
  const clearBtn = document.getElementById('companyPanelClear')

  input.addEventListener('input', () => {
    clearTimeout(_companyDebounceTimer)
    _companyDebounceTimer = setTimeout(() => _triggerLookup(input.value.trim()), 280)
  })

  input.addEventListener('keydown', e => {
    if (dropdown.style.display === 'none') return
    const items = dropdown.querySelectorAll('.company-suggestion')
    if (!items.length) return

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      _activeDropdownIndex = Math.min(_activeDropdownIndex + 1, items.length - 1)
      _highlightDropdown(items)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      _activeDropdownIndex = Math.max(_activeDropdownIndex - 1, 0)
      _highlightDropdown(items)
    } else if (e.key === 'Enter') {
      if (_activeDropdownIndex >= 0 && items[_activeDropdownIndex]) {
        e.preventDefault()
        items[_activeDropdownIndex].click()
      }
    } else if (e.key === 'Escape') {
      _closeDropdown()
    }
  })

  // Close dropdown on outside click
  document.addEventListener('click', e => {
    if (!input.contains(e.target) && !dropdown.contains(e.target)) {
      _closeDropdown()
    }
  })

  clearBtn.addEventListener('click', _clearCompanyPanel)
}

async function _triggerLookup (query) {
  const dropdown = document.getElementById('companyDropdown')
  if (!query || query.length < 2) {
    _closeDropdown()
    return
  }

  try {
    const res = await fetch(`${LOOKUP_URL}?q=${encodeURIComponent(query)}`, {
      signal: AbortSignal.timeout(5000),
    })
    if (!res.ok) return
    const matches = await res.json()
    _renderDropdown(matches)
  } catch { /* backend offline — silently skip */ }
}

function _renderDropdown (matches) {
  const dropdown = document.getElementById('companyDropdown')
  if (!matches || matches.length === 0) {
    _closeDropdown()
    return
  }

  _activeDropdownIndex = -1
  dropdown.innerHTML = matches.map((m, i) => {
    const meta = [m.attn, m.trn].filter(Boolean).join(' · ')
    return `
      <div class="company-suggestion" data-idx="${i}"
           data-name="${escAttr(m.company_name)}"
           data-attn="${escAttr(m.attn)}"
           data-trn="${escAttr(m.trn)}"
           data-phone="${escAttr(m.phone)}"
           data-fax="${escAttr(m.fax)}">
        <div class="cs-name">${escHtml(m.company_name)}</div>
        ${meta ? `<div class="cs-meta">${escHtml(meta)}</div>` : ''}
      </div>`
  }).join('')

  dropdown.querySelectorAll('.company-suggestion').forEach(el => {
    el.addEventListener('mousedown', e => {
      e.preventDefault()   // prevent input blur before click fires
      const d = el.dataset
      document.getElementById('client_name').value = d.name
      applyCompanyRecord({
        company_name: d.name,
        attn:  d.attn,
        trn:   d.trn,
        phone: d.phone,
        fax:   d.fax,
      })
      _closeDropdown()
    })
  })

  dropdown.style.display = 'block'
}

function _highlightDropdown (items) {
  items.forEach((el, i) => el.classList.toggle('active', i === _activeDropdownIndex))
}

function _closeDropdown () {
  const dropdown = document.getElementById('companyDropdown')
  dropdown.style.display = 'none'
  dropdown.innerHTML = ''
  _activeDropdownIndex = -1
}

/**
 * Fill the company panel from a record object.
 * Pass null / empty string values to open a blank "New company" panel.
 */
function applyCompanyRecord (rec, isNew = false) {
  _currentCompanyRecord = rec

  document.getElementById('c_attn').value  = rec.attn  || ''
  document.getElementById('c_trn').value   = rec.trn   || ''
  document.getElementById('c_phone').value = rec.phone || ''
  document.getElementById('c_fax').value   = rec.fax   || ''

  const badge = document.getElementById('companyPanelBadge')
  if (isNew) {
    badge.textContent = 'New Company'
    badge.className   = 'company-panel-badge new'
  } else {
    badge.textContent = 'Matched'
    badge.className   = 'company-panel-badge'
  }

  document.getElementById('companyPanel').style.display = 'block'
}

function _clearCompanyPanel () {
  _currentCompanyRecord = null
  document.getElementById('c_attn').value  = ''
  document.getElementById('c_trn').value   = ''
  document.getElementById('c_phone').value = ''
  document.getElementById('c_fax').value   = ''
  document.getElementById('companyPanel').style.display = 'none'
}

/** Return the current company panel values. */
function getCompanyPayload () {
  return {
    attn:  document.getElementById('c_attn').value.trim(),
    trn:   document.getElementById('c_trn').value.trim(),
    phone: document.getElementById('c_phone').value.trim(),
    fax:   document.getElementById('c_fax').value.trim(),
  }
}

/** Save the current company panel as a new/updated record. */
async function saveCurrentCompany (clientName) {
  const cp = getCompanyPayload()
  if (!clientName) return

  const record = {
    company_name: clientName,
    attn:  cp.attn,
    trn:   cp.trn,
    phone: cp.phone,
    fax:   cp.fax,
  }

  try {
    await fetch(COMPANIES_URL, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(record),
      signal:  AbortSignal.timeout(5000),
    })
    setFooter(`Company "${clientName}" saved.`)
  } catch { /* non-critical */ }
}

/**
 * Check if the entered client name already has a saved record.
 * Returns the best match or null.
 */
async function lookupCompanyByName (name) {
  if (!name || name.length < 2) return null
  try {
    const res = await fetch(`${LOOKUP_URL}?q=${encodeURIComponent(name)}`, {
      signal: AbortSignal.timeout(5000),
    })
    if (!res.ok) return null
    const matches = await res.json()
    return matches.length > 0 ? matches[0] : null
  } catch {
    return null
  }
}

// ── Multi-item form ────────────────────────────────────────────────────────────

let _itemSeq = 0   // ever-incrementing so each block has a unique key

function initItemsForm () {
  addItemBlock()   // start with one empty item

  document.getElementById('addItemBtn').addEventListener('click', () => {
    addItemBlock()
    setFooter('Item added.')
  })

  // Recalc when tax changes
  document.getElementById('tax').addEventListener('input', recalcTotals)
}

/**
 * Add a new item block to #itemsList.
 * @param {{ description?, size?, quantity?, rate? }} data  Optional pre-filled values.
 * @returns {HTMLElement} The new block element.
 */
function addItemBlock (data = {}) {
  _itemSeq++
  const list  = document.getElementById('itemsList')
  const index = list.children.length + 1   // visual label (1-based)

  const block = document.createElement('div')
  block.className = 'item-block'
  block.dataset.seq = _itemSeq

  const qty  = data.quantity ?? 1
  const rate = data.rate     ?? 0

  block.innerHTML = `
    <div class="item-block-header">
      <span class="item-block-num">Item ${index}</span>
      <button type="button" class="btn-remove-item" title="Remove item">
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
          <path d="M1.5 1.5l7 7M8.5 1.5l-7 7" stroke="currentColor"
                stroke-width="1.8" stroke-linecap="round"/>
        </svg>
      </button>
    </div>
    <div class="form-row cols-1" style="margin-bottom:10px">
      <div class="field">
        <label>Description</label>
        <input class="item-desc" type="text"
               placeholder="Fabrication of S.S Roller"
               value="${escAttr(data.description || '')}" />
      </div>
    </div>
    <div class="form-row cols-3">
      <div class="field">
        <label>Size / Spec</label>
        <input class="item-size" type="text"
               placeholder="40 × 120 mm"
               value="${escAttr(data.size || '')}" />
      </div>
      <div class="field">
        <label>Qty</label>
        <input class="item-qty" type="number" min="0.001" step="any"
               value="${qty}" />
      </div>
      <div class="field">
        <label>Rate (AED)</label>
        <input class="item-rate" type="number" min="0" step="any"
               value="${rate}" />
      </div>
    </div>
    <div class="item-amount-row">
      <span class="item-amount-label">Amount</span>
      <span class="item-amount-value">${(qty * rate).toFixed(2)}</span>
    </div>
  `

  // Remove button — keep at least one item
  block.querySelector('.btn-remove-item').addEventListener('click', () => {
    if (document.getElementById('itemsList').children.length > 1) {
      block.remove()
      _renumberItems()
      recalcTotals()
    } else {
      setFooter('At least one item is required.')
    }
  })

  // Auto-recalc on qty / rate change
  block.querySelector('.item-qty').addEventListener('input',  () => { _updateBlockAmount(block); recalcTotals() })
  block.querySelector('.item-rate').addEventListener('input', () => { _updateBlockAmount(block); recalcTotals() })

  list.appendChild(block)
  recalcTotals()
  return block
}

/** Rewrite "Item 1", "Item 2" … labels after a removal. */
function _renumberItems () {
  document.querySelectorAll('#itemsList .item-block').forEach((b, i) => {
    b.querySelector('.item-block-num').textContent = `Item ${i + 1}`
  })
}

/** Update the Amount display inside a single block. */
function _updateBlockAmount (block) {
  const qty  = parseFloat(block.querySelector('.item-qty').value)  || 0
  const rate = parseFloat(block.querySelector('.item-rate').value) || 0
  block.querySelector('.item-amount-value').textContent = (qty * rate).toFixed(2)
}

/** Recompute Subtotal and Total from all item blocks. */
function recalcTotals () {
  let subtotal = 0
  document.querySelectorAll('#itemsList .item-block').forEach(b => {
    subtotal += (parseFloat(b.querySelector('.item-qty').value)  || 0)
              * (parseFloat(b.querySelector('.item-rate').value) || 0)
  })
  subtotal = Math.round(subtotal * 100) / 100

  document.getElementById('subtotal').value = subtotal.toFixed(2)

  const tax   = parseFloat(document.getElementById('tax').value) || 0
  const total = Math.round((subtotal + tax) * 100) / 100
  document.getElementById('total').value = total.toFixed(2)
}

/** Return the items array from the current form state. */
function getItemsPayload () {
  return Array.from(document.querySelectorAll('#itemsList .item-block')).map(b => ({
    description: b.querySelector('.item-desc').value.trim(),
    size:        b.querySelector('.item-size').value.trim(),
    quantity:    parseFloat(b.querySelector('.item-qty').value)  || 1,
    rate:        parseFloat(b.querySelector('.item-rate').value) || 0,
  }))
}

/** Clear all item blocks (used before repopulating from parsed data). */
function clearItemBlocks () {
  document.getElementById('itemsList').innerHTML = ''
}

// ── Form submission ────────────────────────────────────────────────────────────
function wireForm () {
  quotForm.addEventListener('submit', handleSubmit)
}

async function handleSubmit (e) {
  e.preventDefault()

  const items = getItemsPayload()

  // ── Validation ─────────────────────────────────────────────────────────────
  const clientName = document.getElementById('client_name').value.trim()
  const date       = document.getElementById('date').value.trim()

  if (!clientName) {
    showError('Please enter a client name.')
    return
  }
  if (!date) {
    showError('Please enter a date.')
    return
  }
  if (!items[0]?.description) {
    showError('Item 1 must have a description.')
    return
  }

  // ── Build payload ──────────────────────────────────────────────────────────
  const tax      = parseFloat(document.getElementById('tax').value)      || 0
  const total    = parseFloat(document.getElementById('total').value)    || 0
  const isMulti  = items.length > 1
  const company  = getCompanyPayload()

  const payload = {
    year:        document.getElementById('year').value.trim(),
    month:       document.getElementById('month').value.trim(),
    date,
    client_name: clientName,
    // Company memory fields
    attn:  company.attn,
    trn:   company.trn,
    phone: company.phone,
    fax:   company.fax,
    // Legacy single-item fields (always filled from first item for compat)
    description: items[0].description,
    size:        items[0].size || '',
    quantity:    items[0].quantity,
    rate:        items[0].rate,
    tax,
    total,
    // Multi-item array: sent only when 2+ items so single-item uses legacy path
    items: isMulti ? items : [],
  }

  // ── Submit ─────────────────────────────────────────────────────────────────
  setSubmitLoading(true)
  setFooter('Creating quotation…')
  hideResult()

  try {
    const response = await fetch(CREATE_URL, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
      signal:  AbortSignal.timeout(30_000),
    })

    const data = await response.json()

    if (response.ok && data.success) {
      showSuccess(data)
      setFooter(`Quotation #${data.new_ref_number} created successfully`)
      // If the panel has data and it was a new company (not matched), offer to save
      _offerSaveCompanyIfNew(clientName)
    } else {
      const msg = data.detail || data.message || JSON.stringify(data)
      showError(msg)
      setFooter('Error creating quotation')
    }

  } catch (err) {
    if (err.name === 'TimeoutError') {
      showError('Request timed out. The backend may be busy or unreachable.')
    } else if (err.message?.includes('fetch')) {
      showError(
        'Cannot connect to backend.\n\n' +
        'Make sure the Python backend is running:\n' +
        '  cd quotation-agent\n  python run.py'
      )
      updateBackendStatus({ running: false, message: 'Backend not running' })
    } else {
      showError(`Unexpected error: ${err.message}`)
    }
    setFooter('Error — see result panel for details')
  }

  setSubmitLoading(false)
}

// ── Result rendering ───────────────────────────────────────────────────────────

function showSuccess (data) {
  resultCard.className = 'result-card success'

  resultHeader.innerHTML = `
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
      <circle cx="7.5" cy="7.5" r="6.5" stroke="currentColor" stroke-width="1.5"/>
      <path d="M4.5 7.5l2 2 4-4" stroke="currentColor" stroke-width="1.5"
            stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    Quotation Created
  `

  const pdfBadge = `<span class="pdf-badge ${data.pdf_status}">${data.pdf_status}</span>`

  resultBody.innerHTML = `
    <table class="result-table">
      <tr>
        <td>Ref Number</td>
        <td><span class="ref-badge">#${data.new_ref_number}</span></td>
      </tr>
      <tr>
        <td>Filename</td>
        <td style="color:var(--text-secondary)">${escHtml(data.filename)}</td>
      </tr>
      <tr>
        <td>Excel</td>
        <td>
          <div class="path-text">${escHtml(data.excel_path)}</div>
          <div class="path-actions">
            ${makePathBtn('Open Excel',        'openPath',     data.excel_path)}
            ${makePathBtn('Show in Explorer',  'showInFolder', data.excel_path)}
          </div>
        </td>
      </tr>
      ${data.pdf_path ? `
      <tr>
        <td>PDF</td>
        <td>
          <div class="path-text">${escHtml(data.pdf_path)}</div>
          <div class="path-actions">
            ${makePathBtn('Open PDF',           'openPath',     data.pdf_path)}
            ${makePathBtn('Show in Explorer',   'showInFolder', data.pdf_path)}
          </div>
        </td>
      </tr>` : ''}
      <tr>
        <td>PDF Status</td>
        <td>${pdfBadge} <span style="font-size:11.5px;color:var(--text-muted);margin-left:6px">${escHtml(data.pdf_message)}</span></td>
      </tr>
      <tr>
        <td>Folder</td>
        <td>
          <div class="path-text">${escHtml(data.source_folder)}</div>
          <div class="path-actions">
            ${makePathBtn('Open Folder', 'openPath', data.source_folder)}
          </div>
        </td>
      </tr>
    </table>
  `

  resultBody.querySelectorAll('[data-action]').forEach(btn => {
    btn.addEventListener('click', () => {
      const action = btn.dataset.action
      const target = btn.dataset.target
      if (action === 'openPath')     window.electronAPI?.openPath(target)
      if (action === 'showInFolder') window.electronAPI?.showInFolder(target)
    })
  })

  resultCard.style.display = 'block'
  resultCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
}

function showError (msg) {
  resultCard.className = 'result-card error'

  resultHeader.innerHTML = `
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
      <circle cx="7.5" cy="7.5" r="6.5" stroke="currentColor" stroke-width="1.5"/>
      <path d="M5 5l5 5M10 5l-5 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
    </svg>
    Error
  `

  resultBody.innerHTML = `
    <pre style="font-family:var(--font-mono);font-size:12px;color:var(--text-secondary);
                white-space:pre-wrap;word-break:break-word">${escHtml(msg)}</pre>
  `

  resultCard.style.display = 'block'
  resultCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
}

function hideResult () {
  resultCard.style.display = 'none'
}

function _offerSaveCompanyIfNew (clientName) {
  const cp = getCompanyPayload()
  const hasDetails = cp.attn || cp.trn || cp.phone || cp.fax
  // If the record was already matched from DB, _currentCompanyRecord is set
  if (!hasDetails || _currentCompanyRecord) return

  const prompt = document.createElement('div')
  prompt.className = 'save-company-prompt'
  prompt.innerHTML = `
    <span>Save <strong>${escHtml(clientName)}</strong> to company memory?</span>
    <button class="btn-save-company" id="btnSaveCompanyNow">Save Company</button>
  `
  resultBody.appendChild(prompt)

  document.getElementById('btnSaveCompanyNow').addEventListener('click', async () => {
    await saveCurrentCompany(clientName)
    _currentCompanyRecord = { company_name: clientName, ...cp }
    prompt.innerHTML = `<span style="color:var(--green)">Company saved successfully.</span>`
  })
}

// ── UI helpers ─────────────────────────────────────────────────────────────────

function setSubmitLoading (loading) {
  submitBtn.disabled = loading
  submitBtn.innerHTML = loading
    ? `<span class="spinner"></span> Generating…`
    : `<svg width="18" height="18" viewBox="0 0 18 18" fill="none">
         <path d="M9 2v14M2 9h14" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>
       </svg>
       Generate Quotation`
}

function setFooter (msg) {
  footerMsg.textContent = msg
}

function makePathBtn (label, action, target) {
  const safePath = escAttr(target)
  return `<button class="btn-action" data-action="${action}" data-target="${safePath}">${label}</button>`
}

function escHtml (str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function escAttr (str) {
  return String(str ?? '').replace(/"/g, '&quot;').replace(/'/g, '&#39;')
}

// ── Quick Command ──────────────────────────────────────────────────────────────

function wireQuickCommand () {
  document.querySelectorAll('.example-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      nlCommand.value = chip.dataset.cmd
      nlCommand.focus()
    })
  })

  parseBtn.addEventListener('click', parseCommand)

  nlCommand.addEventListener('keydown', e => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      parseCommand()
    }
  })

  confirmBtn.addEventListener('click', confirmAndCreate)
  editFormBtn.addEventListener('click', editInForm)
}

async function parseCommand () {
  const cmd = nlCommand.value.trim()
  if (!cmd) {
    nlCommand.focus()
    setFooter('Enter a command first.')
    return
  }

  setParseBtnLoading(true)
  setFooter('Parsing command…')
  qcPreview.style.display = 'none'
  qcResultCard.style.display = 'none'
  _parsedData = null

  try {
    const res = await fetch(PARSE_URL, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ command: cmd }),
      signal:  AbortSignal.timeout(15_000),
    })

    const data = await res.json()

    if (!res.ok) {
      const msg = data.detail || data.message || JSON.stringify(data)
      setFooter(`Parse error: ${msg}`)
      setParseBtnLoading(false)
      return
    }

    _parsedData = data
    // Silently enrich with company memory
    const match = await lookupCompanyByName(data.parsed.client_name)
    if (match) {
      _parsedData.parsed.attn  = match.attn  || ''
      _parsedData.parsed.trn   = match.trn   || ''
      _parsedData.parsed.phone = match.phone || ''
      _parsedData.parsed.fax   = match.fax   || ''
      _parsedData._companyMatched = true
    }
    renderPreview(_parsedData)
    qcPreview.style.display = 'block'
    qcPreview.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    setFooter('Review the parsed fields, then confirm to create.')

  } catch (err) {
    if (err.name === 'TimeoutError') {
      setFooter('Parse request timed out.')
    } else {
      setFooter(`Cannot reach backend: ${err.message}`)
    }
  }

  setParseBtnLoading(false)
}

function renderPreview (data) {
  const { parsed, confidence, warnings } = data
  const isMulti = parsed.items && parsed.items.length > 1

  if (isMulti) {
    _renderMultiItemPreview(parsed, confidence)
  } else {
    _renderSingleItemPreview(parsed, confidence)
  }

  if (warnings && warnings.length) {
    previewWarnings.innerHTML =
      `<ul>${warnings.map(w => `<li>${escHtml(w)}</li>`).join('')}</ul>`
    previewWarnings.style.display = 'block'
  } else {
    previewWarnings.style.display = 'none'
  }

  qcResultCard.style.display = 'none'
  confirmBtn.disabled = false
}

function _renderSingleItemPreview (parsed, confidence) {
  const confKeys = new Set(['client_name', 'description', 'size', 'quantity', 'rate', 'tax'])
  const fields = [
    ['Client',      'client_name', null],
    ['Description', 'description', null],
    ['Size / Spec', 'size',        null],
    ['Date',        'date',        null],
    ['Quantity',    'quantity',    v => String(v)],
    ['Rate (AED)',  'rate',        v => Number(v).toFixed(2)],
    ['Tax (AED)',   'tax',         v => Number(v).toFixed(2)],
    ['Total (AED)', 'total',       v => Number(v).toFixed(2)],
  ]

  previewGrid.className = 'preview-grid'
  let html = fields.map(([label, key, fmt]) => {
    const raw     = parsed[key]
    const val     = fmt ? fmt(raw) : (raw || '—')
    const isFound = confKeys.has(key) ? confidence[key] : true
    const badge   = confKeys.has(key)
      ? `<span class="conf-badge ${isFound ? 'found' : 'default'}">${isFound ? 'found' : 'default'}</span>`
      : ''
    return `
      <div class="preview-field">
        <div class="preview-field-label">${escHtml(label)}${badge}</div>
        <div class="preview-field-value">${escHtml(String(val))}</div>
      </div>`
  }).join('')

  html += _renderCompanyPreviewBlock(parsed)
  previewGrid.innerHTML = html
}

function _renderCompanyPreviewBlock (parsed) {
  const hasCompany = parsed.attn || parsed.trn || parsed.phone || parsed.fax
  if (!hasCompany) return ''
  const parts = []
  if (parsed.attn)  parts.push(`Attn: ${parsed.attn}`)
  if (parsed.trn)   parts.push(`TRN: ${parsed.trn}`)
  if (parsed.phone) parts.push(`Tel: ${parsed.phone}`)
  if (parsed.fax)   parts.push(`Fax: ${parsed.fax}`)
  return `
    <div class="preview-field preview-field--company">
      <div class="preview-field-label">Company Details <span class="conf-badge found">memory</span></div>
      <div class="preview-field-value">${parts.map(escHtml).join(' &nbsp;·&nbsp; ')}</div>
    </div>`
}

function _renderMultiItemPreview (parsed, confidence) {
  const clientBadge = confidence.client_name
    ? '<span class="conf-badge found">found</span>'
    : '<span class="conf-badge default">default</span>'

  const rateBadge = confidence.rate
    ? '<span class="conf-badge found">found</span>'
    : '<span class="conf-badge default">default</span>'

  const itemRows = parsed.items.map((item, i) => `
    <tr>
      <td class="pit-no">${i + 1}</td>
      <td class="pit-desc">
        ${escHtml(item.description)}
        ${item.size ? `<span class="pit-size">(${escHtml(item.size)})</span>` : ''}
      </td>
      <td class="pit-num">${item.quantity}</td>
      <td class="pit-num">${Number(item.rate).toFixed(2)}</td>
      <td class="pit-num">${Number(item.amount).toFixed(2)}</td>
    </tr>`).join('')

  const subtotal = parsed.items.reduce((s, i) => s + i.amount, 0)

  previewGrid.className = 'preview-grid preview-grid--multi'
  previewGrid.innerHTML = `
    <div class="preview-field">
      <div class="preview-field-label">Client ${clientBadge}</div>
      <div class="preview-field-value">${escHtml(parsed.client_name)}</div>
    </div>
    <div class="preview-field">
      <div class="preview-field-label">Date</div>
      <div class="preview-field-value">${escHtml(parsed.date)}</div>
    </div>

    <div class="preview-items-wrap">
      <div class="preview-field-label" style="margin-bottom:8px">
        Items (${parsed.items.length}) ${rateBadge}
      </div>
      <table class="preview-items-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Description</th>
            <th>Qty</th>
            <th>Rate</th>
            <th>Amount</th>
          </tr>
        </thead>
        <tbody>${itemRows}</tbody>
        <tfoot>
          <tr class="pit-subtotal">
            <td colspan="4" style="text-align:right">Subtotal</td>
            <td class="pit-num">${subtotal.toFixed(2)}</td>
          </tr>
          <tr>
            <td colspan="4" style="text-align:right">VAT (5%)</td>
            <td class="pit-num">${Number(parsed.tax).toFixed(2)}</td>
          </tr>
          <tr class="pit-total">
            <td colspan="4" style="text-align:right">Total</td>
            <td class="pit-num">${Number(parsed.total).toFixed(2)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
    ${_renderCompanyPreviewBlock(parsed)}`
}

async function confirmAndCreate () {
  if (!_parsedData) return

  setConfirmBtnLoading(true)
  setFooter('Creating quotation…')
  qcResultCard.style.display = 'none'

  try {
    const res = await fetch(CREATE_URL, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(_parsedData.parsed),   // already enriched with attn/trn/phone/fax
      signal:  AbortSignal.timeout(30_000),
    })

    const data = await res.json()

    if (res.ok && data.success) {
      qcShowSuccess(data)
      setFooter(`Quotation #${data.new_ref_number} created successfully`)
    } else {
      const msg = data.detail || data.message || JSON.stringify(data)
      qcShowError(msg)
      setFooter('Error creating quotation')
    }

  } catch (err) {
    qcShowError(err.name === 'TimeoutError'
      ? 'Request timed out.'
      : `Cannot reach backend: ${err.message}`)
    setFooter('Error — see result panel')
  }

  setConfirmBtnLoading(false)
}

/**
 * Populate the Create Quotation form from parsed Quick Command data
 * and switch to that tab.
 */
function editInForm () {
  if (!_parsedData) return
  const p = _parsedData.parsed

  // Header fields
  document.getElementById('year').value        = p.year        || ''
  document.getElementById('month').value       = p.month       || ''
  document.getElementById('date').value        = p.date        || ''
  document.getElementById('client_name').value = p.client_name || ''
  document.getElementById('tax').value         = p.tax         ?? 0

  // Company panel
  if (p.attn || p.trn || p.phone || p.fax) {
    applyCompanyRecord({
      company_name: p.client_name,
      attn:  p.attn  || '',
      trn:   p.trn   || '',
      phone: p.phone || '',
      fax:   p.fax   || '',
    }, !_parsedData._companyMatched)
  } else {
    _clearCompanyPanel()
  }

  // Clear existing items and repopulate
  clearItemBlocks()

  if (p.items && p.items.length > 0) {
    p.items.forEach(item => addItemBlock({
      description: item.description,
      size:        item.size,
      quantity:    item.quantity,
      rate:        item.rate,
    }))
  } else {
    addItemBlock({
      description: p.description || '',
      size:        p.size        || '',
      quantity:    p.quantity    ?? 1,
      rate:        p.rate        ?? 0,
    })
  }

  recalcTotals()
  switchToTab('quotation')
  setFooter('Form populated from parsed command — review and generate.')
  hideResult()
}

// ── Quick Command result cards ─────────────────────────────────────────────────

function qcShowSuccess (data) {
  qcResultCard.className = 'result-card success'
  qcResultHeader.innerHTML = `
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
      <circle cx="7.5" cy="7.5" r="6.5" stroke="currentColor" stroke-width="1.5"/>
      <path d="M4.5 7.5l2 2 4-4" stroke="currentColor" stroke-width="1.5"
            stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    Quotation Created`

  const pdfBadge = `<span class="pdf-badge ${data.pdf_status}">${data.pdf_status}</span>`

  qcResultBody.innerHTML = `
    <table class="result-table">
      <tr>
        <td>Ref Number</td>
        <td><span class="ref-badge">#${data.new_ref_number}</span></td>
      </tr>
      <tr>
        <td>Filename</td>
        <td style="color:var(--text-secondary)">${escHtml(data.filename)}</td>
      </tr>
      <tr>
        <td>Excel</td>
        <td>
          <div class="path-text">${escHtml(data.excel_path)}</div>
          <div class="path-actions">
            ${makePathBtn('Open Excel',       'openPath',     data.excel_path)}
            ${makePathBtn('Show in Explorer', 'showInFolder', data.excel_path)}
          </div>
        </td>
      </tr>
      ${data.pdf_path ? `
      <tr>
        <td>PDF</td>
        <td>
          <div class="path-text">${escHtml(data.pdf_path)}</div>
          <div class="path-actions">
            ${makePathBtn('Open PDF',         'openPath',     data.pdf_path)}
            ${makePathBtn('Show in Explorer', 'showInFolder', data.pdf_path)}
          </div>
        </td>
      </tr>` : ''}
      <tr>
        <td>PDF Status</td>
        <td>${pdfBadge} <span style="font-size:11.5px;color:var(--text-muted);margin-left:6px">${escHtml(data.pdf_message)}</span></td>
      </tr>
    </table>`

  qcResultBody.querySelectorAll('[data-action]').forEach(btn => {
    btn.addEventListener('click', () => {
      const action = btn.dataset.action
      const target = btn.dataset.target
      if (action === 'openPath')     window.electronAPI?.openPath(target)
      if (action === 'showInFolder') window.electronAPI?.showInFolder(target)
    })
  })

  qcResultCard.style.display = 'block'
  qcResultCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
}

function qcShowError (msg) {
  qcResultCard.className = 'result-card error'
  qcResultHeader.innerHTML = `
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
      <circle cx="7.5" cy="7.5" r="6.5" stroke="currentColor" stroke-width="1.5"/>
      <path d="M5 5l5 5M10 5l-5 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
    </svg>
    Error`
  qcResultBody.innerHTML = `
    <pre style="font-family:var(--font-mono);font-size:12px;color:var(--text-secondary);
                white-space:pre-wrap;word-break:break-word">${escHtml(msg)}</pre>`
  qcResultCard.style.display = 'block'
  qcResultCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
}

// ── Loading states ─────────────────────────────────────────────────────────────

function setParseBtnLoading (loading) {
  parseBtn.disabled = loading
  parseBtn.innerHTML = loading
    ? `<span class="spinner"></span> Parsing…`
    : `<svg width="15" height="15" viewBox="0 0 15 15" fill="none">
         <circle cx="7.5" cy="7.5" r="6.5" stroke="currentColor" stroke-width="1.5"/>
         <path d="M5 7.5h5M8 5.5l2 2-2 2" stroke="currentColor" stroke-width="1.5"
               stroke-linecap="round" stroke-linejoin="round"/>
       </svg>
       Parse &amp; Preview`
}

function setConfirmBtnLoading (loading) {
  confirmBtn.disabled = loading
  confirmBtn.innerHTML = loading
    ? `<span class="spinner"></span> Creating…`
    : `<svg width="14" height="14" viewBox="0 0 14 14" fill="none">
         <path d="M2.5 7.5l3 3 6-6" stroke="currentColor" stroke-width="1.8"
               stroke-linecap="round" stroke-linejoin="round"/>
       </svg>
       Confirm &amp; Create`

// ════════════════════════════════════════════ LEDGER MODULE ════════════════════

// ── Generic company autocomplete (used by ledger forms) ────────────────────────

/**
 * Attach a company-name autocomplete dropdown to any input element.
 * onSelect(record) is called when the user clicks a suggestion.
 */
function attachLdgAutocomplete (inputId, dropdownId, onSelect) {
  const input    = document.getElementById(inputId)
  const dropdown = document.getElementById(dropdownId)
  if (!input || !dropdown) return

  let debounceT = null
  let activeIdx = -1

  function close () {
    dropdown.style.display = 'none'
    dropdown.innerHTML = ''
    activeIdx = -1
  }

  function highlight (items) {
    items.forEach((el, i) => el.classList.toggle('active', i === activeIdx))
  }

  input.addEventListener('input', () => {
    clearTimeout(debounceT)
    debounceT = setTimeout(async () => {
      const q = input.value.trim()
      if (q.length < 2) { close(); return }
      try {
        const res = await fetch(`${LOOKUP_URL}?q=${encodeURIComponent(q)}`,
          { signal: AbortSignal.timeout(4000) })
        if (!res.ok) return
        const matches = await res.json()
        if (!matches.length) { close(); return }

        activeIdx = -1
        dropdown.innerHTML = matches.map((m, i) => {
          const meta = [m.attn, m.trn].filter(Boolean).join(' · ')
          return `<div class="company-suggestion" data-idx="${i}"
                       data-name="${escAttr(m.company_name)}">
            <div class="cs-name">${escHtml(m.company_name)}</div>
            ${meta ? `<div class="cs-meta">${escHtml(meta)}</div>` : ''}
          </div>`
        }).join('')

        dropdown.querySelectorAll('.company-suggestion').forEach((el, i) => {
          el.addEventListener('mousedown', e => {
            e.preventDefault()
            input.value = matches[i].company_name
            close()
            onSelect(matches[i])
          })
        })
        dropdown.style.display = 'block'
      } catch { /* backend offline */ }
    }, 260)
  })

  input.addEventListener('keydown', e => {
    const items = dropdown.querySelectorAll('.company-suggestion')
    if (dropdown.style.display === 'none' || !items.length) return
    if (e.key === 'ArrowDown')  { e.preventDefault(); activeIdx = Math.min(activeIdx + 1, items.length - 1); highlight(items) }
    else if (e.key === 'ArrowUp')    { e.preventDefault(); activeIdx = Math.max(activeIdx - 1, 0); highlight(items) }
    else if (e.key === 'Enter' && activeIdx >= 0) { e.preventDefault(); items[activeIdx].dispatchEvent(new MouseEvent('mousedown')) }
    else if (e.key === 'Escape') close()
  })

  document.addEventListener('click', e => {
    if (!input.contains(e.target) && !dropdown.contains(e.target)) close()
  })
}

// ── Date helpers (client-side) ─────────────────────────────────────────────────

function _addDays (ddmmyyyy, n) {
  if (!ddmmyyyy || ddmmyyyy.length < 10) return ''
  const [d, m, y] = ddmmyyyy.split('-').map(Number)
  if (!d || !m || !y) return ''
  const dt = new Date(y, m - 1, d)
  dt.setDate(dt.getDate() + n)
  const dd = String(dt.getDate()).padStart(2, '0')
  const mm = String(dt.getMonth() + 1).padStart(2, '0')
  return `${dd}-${mm}-${dt.getFullYear()}`
}

function _todayDMY () {
  const now = new Date()
  const dd  = String(now.getDate()).padStart(2, '0')
  const mm  = String(now.getMonth() + 1).padStart(2, '0')
  return `${dd}-${mm}-${now.getFullYear()}`
}

// ── Sub-tab switching ──────────────────────────────────────────────────────────

function initLedgerModule () {
  // Sub-tab buttons
  document.querySelectorAll('.ldg-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => _switchLdgTab(btn.dataset.ltab))
  })

  _initInvoiceForm()
  _initPaymentForm()
  _initLedgerView()
}

function _switchLdgTab (name) {
  document.querySelectorAll('.ldg-tab-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.ltab === name))
  document.querySelectorAll('.ldg-panel').forEach(p => p.classList.remove('active'))
  document.getElementById(`ltab-${name}`)?.classList.add('active')
  if (name === 'view') _loadLedgerView()
}

// ── Invoice form ───────────────────────────────────────────────────────────────

function _initInvoiceForm () {
  // Pre-fill today
  document.getElementById('inv_date').value = _todayDMY()
  _recalcDueDate()

  // Autocomplete: on select, fill payment terms from company record
  attachLdgAutocomplete('inv_company', 'invCompanyDropdown', rec => {
    if (rec.payment_terms_days != null) {
      document.getElementById('inv_terms').value = rec.payment_terms_days
      _recalcDueDate()
    }
  })

  // Auto-recalc due date when date or terms change
  document.getElementById('inv_date').addEventListener('input',  _recalcDueDate)
  document.getElementById('inv_terms').addEventListener('input', _recalcDueDate)

  document.getElementById('invoiceForm').addEventListener('submit', _submitInvoice)
}

function _recalcDueDate () {
  const dateVal  = document.getElementById('inv_date').value.trim()
  const termsVal = parseInt(document.getElementById('inv_terms').value, 10) || 0
  document.getElementById('inv_due').value = _addDays(dateVal, termsVal)
}

async function _submitInvoice (e) {
  e.preventDefault()
  const btn = document.getElementById('saveInvoiceBtn')
  btn.disabled = true
  btn.innerHTML = `<span class="spinner"></span> Saving…`

  const payload = {
    company_name:       document.getElementById('inv_company').value.trim(),
    invoice_number:     document.getElementById('inv_number').value.trim(),
    invoice_date:       document.getElementById('inv_date').value.trim(),
    lpo_number:         document.getElementById('inv_lpo').value.trim(),
    amount:             parseFloat(document.getElementById('inv_amount').value) || 0,
    payment_terms_days: parseInt(document.getElementById('inv_terms').value, 10) || 30,
    due_date:           document.getElementById('inv_due').value.trim(),
    remarks:            document.getElementById('inv_remarks').value.trim(),
  }

  const rc  = document.getElementById('invoiceResultCard')
  const rh  = document.getElementById('invoiceResultHeader')
  const rb  = document.getElementById('invoiceResultBody')

  try {
    const res  = await fetch(`${LEDGER_URL}/invoices`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(15_000),
    })
    const data = await res.json()

    if (res.ok) {
      rc.className = 'result-card success'
      rh.innerHTML = `<svg width="14" height="14" viewBox="0 0 14 14" fill="none">
        <circle cx="7" cy="7" r="6" stroke="currentColor" stroke-width="1.5"/>
        <path d="M4 7l2 2 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg> Invoice Saved`
      rb.innerHTML = `<table class="result-table">
        <tr><td>ID</td><td>${escHtml(data.id)}</td></tr>
        <tr><td>Invoice #</td><td>${escHtml(data.invoice_number)}</td></tr>
        <tr><td>Company</td><td>${escHtml(data.company_name)}</td></tr>
        <tr><td>Amount</td><td>AED ${Number(data.amount).toFixed(2)}</td></tr>
        <tr><td>Due Date</td><td>${escHtml(data.due_date)}</td></tr>
      </table>`
      // Reset form (keep company, date, terms)
      document.getElementById('inv_number').value  = ''
      document.getElementById('inv_lpo').value     = ''
      document.getElementById('inv_amount').value  = ''
      document.getElementById('inv_remarks').value = ''
      setFooter(`Invoice ${data.invoice_number} saved for ${data.company_name}`)
    } else {
      rc.className = 'result-card error'
      rh.innerHTML = `Error`
      rb.innerHTML = `<pre style="font-size:12px;white-space:pre-wrap">${escHtml(data.detail || JSON.stringify(data))}</pre>`
    }
    rc.style.display = 'block'
    rc.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  } catch (err) {
    rc.className  = 'result-card error'
    rh.innerHTML  = `Error`
    rb.innerHTML  = `<pre style="font-size:12px">${escHtml(err.message)}</pre>`
    rc.style.display = 'block'
  }

  btn.disabled  = false
  btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 16 16" fill="none">
    <path d="M8 2v12M2 8h12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
  </svg> Save Invoice`
}

// ── Payment form ───────────────────────────────────────────────────────────────

function _initPaymentForm () {
  document.getElementById('pay_date').value = _todayDMY()

  attachLdgAutocomplete('pay_company', 'payCompanyDropdown', rec => {
    _loadInvoicesForCompany(rec.company_name)
  })

  // Also load on manual blur
  document.getElementById('pay_company').addEventListener('blur', () => {
    const v = document.getElementById('pay_company').value.trim()
    if (v) _loadInvoicesForCompany(v)
  })

  document.getElementById('paymentForm').addEventListener('submit', _submitPayment)
}

async function _loadInvoicesForCompany (companyName) {
  const sel = document.getElementById('pay_invoice')
  sel.innerHTML = '<option value="">— loading… —</option>'

  try {
    // Get overview to have balance data
    const res  = await fetch(`${LEDGER_URL}/overview`, { signal: AbortSignal.timeout(8000) })
    if (!res.ok) { sel.innerHTML = '<option value="">— error loading —</option>'; return }
    const data = await res.json()

    const company = data.companies.find(c =>
      c.company_name.toUpperCase() === companyName.toUpperCase())

    if (!company || !company.invoices.length) {
      sel.innerHTML = '<option value="">— no invoices found —</option>'
      return
    }

    // Show all invoices; highlight outstanding
    const outstanding = company.invoices.filter(i => i.status !== 'PAID')
    const paid        = company.invoices.filter(i => i.status === 'PAID')

    sel.innerHTML = '<option value="">— select invoice —</option>'

    if (outstanding.length) {
      const og = document.createElement('optgroup')
      og.label = 'Outstanding'
      outstanding.forEach(inv => {
        const o = document.createElement('option')
        o.value       = inv.invoice_number
        o.textContent = `${inv.invoice_number}${inv.lpo_number ? ' · ' + inv.lpo_number : ''} — Balance: AED ${Number(inv.balance).toFixed(2)}`
        og.appendChild(o)
      })
      sel.appendChild(og)
    }

    if (paid.length) {
      const pg = document.createElement('optgroup')
      pg.label = 'Paid'
      paid.forEach(inv => {
        const o = document.createElement('option')
        o.value       = inv.invoice_number
        o.textContent = `${inv.invoice_number} — PAID`
        pg.appendChild(o)
      })
      sel.appendChild(pg)
    }
  } catch {
    sel.innerHTML = '<option value="">— error —</option>'
  }
}

async function _submitPayment (e) {
  e.preventDefault()
  const btn = document.getElementById('savePaymentBtn')
  btn.disabled = true
  btn.innerHTML = `<span class="spinner"></span> Saving…`

  const payload = {
    company_name:    document.getElementById('pay_company').value.trim(),
    invoice_number:  document.getElementById('pay_invoice').value.trim(),
    payment_date:    document.getElementById('pay_date').value.trim(),
    amount_received: parseFloat(document.getElementById('pay_amount').value) || 0,
    payment_mode:    document.getElementById('pay_mode').value,
    remarks:         document.getElementById('pay_remarks').value.trim(),
  }

  const rc = document.getElementById('paymentResultCard')
  const rh = document.getElementById('paymentResultHeader')
  const rb = document.getElementById('paymentResultBody')

  try {
    const res  = await fetch(`${LEDGER_URL}/payments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(15_000),
    })
    const data = await res.json()

    if (res.ok) {
      rc.className = 'result-card success'
      rh.innerHTML = `<svg width="14" height="14" viewBox="0 0 14 14" fill="none">
        <circle cx="7" cy="7" r="6" stroke="currentColor" stroke-width="1.5"/>
        <path d="M4 7l2 2 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg> Payment Recorded`
      rb.innerHTML = `<table class="result-table">
        <tr><td>ID</td><td>${escHtml(data.id)}</td></tr>
        <tr><td>Invoice #</td><td>${escHtml(data.invoice_number)}</td></tr>
        <tr><td>Amount</td><td>AED ${Number(data.amount_received).toFixed(2)}</td></tr>
        <tr><td>Mode</td><td>${escHtml(data.payment_mode)}</td></tr>
        <tr><td>Date</td><td>${escHtml(data.payment_date)}</td></tr>
      </table>`
      document.getElementById('pay_amount').value  = ''
      document.getElementById('pay_remarks').value = ''
      setFooter(`Payment recorded for invoice ${data.invoice_number}`)
      // Refresh invoice list
      _loadInvoicesForCompany(payload.company_name)
    } else {
      rc.className = 'result-card error'
      rh.innerHTML = `Error`
      rb.innerHTML = `<pre style="font-size:12px;white-space:pre-wrap">${escHtml(data.detail || JSON.stringify(data))}</pre>`
    }
    rc.style.display = 'block'
    rc.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  } catch (err) {
    rc.className  = 'result-card error'
    rh.innerHTML  = `Error`
    rb.innerHTML  = `<pre style="font-size:12px">${escHtml(err.message)}</pre>`
    rc.style.display = 'block'
  }

  btn.disabled  = false
  btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 16 16" fill="none">
    <path d="M2.5 8.5l3.5 3.5 8-8" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  </svg> Record Payment`
}

// ── Ledger view ────────────────────────────────────────────────────────────────

let _ldgData = null  // cached overview

function _initLedgerView () {
  document.getElementById('ldgRefreshBtn').addEventListener('click', () => _loadLedgerView(true))
  document.getElementById('ldgFilterCompany').addEventListener('change', _renderLedgerTable)
  document.getElementById('ldgFilterStatus').addEventListener('change', _renderLedgerTable)
}

async function _loadLedgerView (force = false) {
  const btn = document.getElementById('ldgRefreshBtn')
  btn.textContent = '⟳ Loading…'

  try {
    const res  = await fetch(`${LEDGER_URL}/overview`, { signal: AbortSignal.timeout(10_000) })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    _ldgData = await res.json()
    _populateCompanyFilter(_ldgData)
    _updateKpis(_ldgData)
    _renderLedgerTable()
  } catch (err) {
    document.getElementById('ldgEmpty').innerHTML =
      `<strong>Could not load ledger:</strong> ${escHtml(err.message)}`
    document.getElementById('ldgEmpty').style.display = 'block'
    document.getElementById('ldgTableWrap').innerHTML = ''
    document.getElementById('ldgTableWrap').appendChild(document.getElementById('ldgEmpty'))
  }

  btn.textContent = '↺ Refresh'
}

function _populateCompanyFilter (data) {
  const sel = document.getElementById('ldgFilterCompany')
  const cur = sel.value
  sel.innerHTML = '<option value="">All Companies</option>'
  data.companies.forEach(c => {
    const o = document.createElement('option')
    o.value = c.company_name
    o.textContent = c.company_name
    if (c.company_name === cur) o.selected = true
    sel.appendChild(o)
  })
}

function _updateKpis (data) {
  document.getElementById('ldgKpiInvoiced').textContent   = `AED ${_fmt(data.total_invoiced)}`
  document.getElementById('ldgKpiReceived').textContent   = `AED ${_fmt(data.total_received)}`
  document.getElementById('ldgKpiOutstanding').textContent= `AED ${_fmt(data.outstanding)}`
}

function _fmt (n) {
  return Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function _renderLedgerTable () {
  if (!_ldgData) return

  const filterCo  = document.getElementById('ldgFilterCompany').value
  const filterSt  = document.getElementById('ldgFilterStatus').value
  const wrap      = document.getElementById('ldgTableWrap')

  let companies = _ldgData.companies
  if (filterCo) companies = companies.filter(c => c.company_name === filterCo)

  // KPI update for filtered view
  if (filterCo) {
    const co = companies[0]
    if (co) {
      document.getElementById('ldgKpiInvoiced').textContent    = `AED ${_fmt(co.total_invoiced)}`
      document.getElementById('ldgKpiReceived').textContent    = `AED ${_fmt(co.total_received)}`
      document.getElementById('ldgKpiOutstanding').textContent = `AED ${_fmt(co.outstanding)}`
    }
  } else {
    _updateKpis(_ldgData)
  }

  // Filter invoices by status
  const hasInvoices = companies.some(c => {
    const lines = filterSt ? c.invoices.filter(i => _matchStatus(i, filterSt)) : c.invoices
    return lines.length > 0
  })

  if (!hasInvoices) {
    wrap.innerHTML = `<div class="ldg-empty">No records match the current filters.</div>`
    return
  }

  wrap.innerHTML = ''
  companies.forEach(cs => {
    const lines = filterSt
      ? cs.invoices.filter(i => _matchStatus(i, filterSt))
      : cs.invoices
    if (!lines.length) return
    wrap.appendChild(_buildCompanySection(cs, lines))
  })
}

function _matchStatus (inv, filter) {
  if (filter === 'OVERDUE')        return inv.overdue && inv.status !== 'PAID'
  if (filter === 'UNPAID')         return inv.status === 'UNPAID'
  if (filter === 'PARTIALLY PAID') return inv.status === 'PARTIALLY PAID'
  if (filter === 'PAID')           return inv.status === 'PAID'
  return true
}

function _buildCompanySection (cs, lines) {
  const section = document.createElement('div')
  section.className = 'ldg-company-section'

  const hasOutstanding = cs.outstanding > 0

  // Header
  const header = document.createElement('div')
  header.className = 'ldg-company-header'
  header.innerHTML = `
    <span class="ldg-company-name">${escHtml(cs.company_name)}</span>
    <div class="ldg-company-totals">
      <span>Invoiced: AED ${_fmt(cs.total_invoiced)}</span>
      <span>Received: AED ${_fmt(cs.total_received)}</span>
      <span class="${hasOutstanding ? 'ldg-ot-amount' : ''}">Outstanding: AED ${_fmt(cs.outstanding)}</span>
      ${cs.overdue_count > 0 ? `<span style="color:var(--red)">${cs.overdue_count} overdue</span>` : ''}
    </div>
    <span class="ldg-company-toggle">▾</span>`

  header.addEventListener('click', () => {
    section.classList.toggle('collapsed')
  })

  // Table
  const tableWrap = document.createElement('div')
  tableWrap.className = 'ldg-table-body'

  const table = document.createElement('table')
  table.className = 'ldg-table'
  table.innerHTML = `
    <thead>
      <tr>
        <th>#</th>
        <th>Invoice No</th>
        <th>LPO No</th>
        <th>Invoice Date</th>
        <th>Due Date</th>
        <th class="ldg-num">Amount</th>
        <th class="ldg-num">Received</th>
        <th class="ldg-num">Balance</th>
        <th>Status</th>
        <th></th>
      </tr>
    </thead>
    <tbody></tbody>`

  const tbody = table.querySelector('tbody')

  lines.forEach((inv, idx) => {
    const statusClass = inv.status === 'PAID'
      ? 'paid'
      : inv.status === 'PARTIALLY PAID'
        ? 'partial'
        : inv.overdue ? 'overdue' : 'unpaid'

    const statusLabel = inv.overdue && inv.status !== 'PAID'
      ? `<span class="ldg-status overdue">OVERDUE</span>`
      : `<span class="ldg-status ${statusClass}">${escHtml(inv.status)}</span>`

    const row = document.createElement('tr')
    row.className = `ldg-inv-row${inv.overdue && inv.status !== 'PAID' ? ' is-overdue' : ''}`
    row.dataset.invId = inv.invoice_id
    row.innerHTML = `
      <td>${idx + 1}</td>
      <td>${escHtml(inv.invoice_number)}</td>
      <td>${escHtml(inv.lpo_number || '—')}</td>
      <td>${escHtml(inv.invoice_date)}</td>
      <td>${escHtml(inv.due_date || '—')}</td>
      <td class="ldg-num">${_fmt(inv.amount)}</td>
      <td class="ldg-num">${_fmt(inv.received)}</td>
      <td class="ldg-num">${_fmt(inv.balance)}</td>
      <td>${statusLabel}</td>
      <td><button class="btn-ldg-del" title="Delete invoice" data-inv-id="${escAttr(inv.invoice_id)}">&#x2715;</button></td>`

    // Expand to show payments on row click (not on delete button)
    const detailRow = document.createElement('tr')
    detailRow.className = 'ldg-detail-row'
    detailRow.style.display = 'none'
    detailRow.innerHTML = `<td colspan="10">${_buildPayHistory(inv)}</td>`

    row.addEventListener('click', e => {
      if (e.target.closest('.btn-ldg-del')) return
      const isOpen = detailRow.style.display !== 'none'
      detailRow.style.display = isOpen ? 'none' : 'table-row'
    })

    // Delete handler
    row.querySelector('.btn-ldg-del').addEventListener('click', async e => {
      e.stopPropagation()
      if (!confirm(`Delete invoice ${inv.invoice_number} and all its payments?`)) return
      try {
        const res = await fetch(`${LEDGER_URL}/invoices/${encodeURIComponent(inv.invoice_id)}`,
          { method: 'DELETE', signal: AbortSignal.timeout(8000) })
        if (res.ok || res.status === 204) {
          setFooter(`Invoice ${inv.invoice_number} deleted.`)
          _loadLedgerView(true)
        } else {
          const d = await res.json().catch(() => ({}))
          alert(`Could not delete: ${d.detail || res.statusText}`)
        }
      } catch (err) { alert(`Error: ${err.message}`) }
    })

    tbody.appendChild(row)
    tbody.appendChild(detailRow)
  })

  tableWrap.appendChild(table)
  section.appendChild(header)
  section.appendChild(tableWrap)
  return section
}

function _buildPayHistory (inv) {
  if (!inv.payments || inv.payments.length === 0) {
    return `<div class="ldg-pay-history"><div class="ldg-pay-history-title">Payments</div>
      <div style="color:var(--text-muted);font-size:12px;padding:4px 0">No payments recorded.</div></div>`
  }
  const rows = inv.payments.map(p => `
    <div class="ldg-pay-item">
      <span>${escHtml(p.payment_date)}</span>
      <span class="ldg-pay-amt">+AED ${_fmt(p.amount_received)}</span>
      <span class="ldg-pay-mode">${escHtml(p.payment_mode)}</span>
      ${p.remarks ? `<span style="color:var(--text-muted)">${escHtml(p.remarks)}</span>` : ''}
    </div>`).join('')
  return `<div class="ldg-pay-history">
    <div class="ldg-pay-history-title">Payment History (${inv.payments.length})</div>${rows}</div>`
}
}
