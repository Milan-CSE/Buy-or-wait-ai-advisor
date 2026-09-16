// Buy or Wait? AI Advisor Frontend Application

const API_BASE = '/api/v1';
let currentStagedBatchId = null;

// Helper: Token Management
function getToken() {
  return localStorage.getItem('buyorwait_token');
}

function setToken(token) {
  if (token) {
    localStorage.setItem('buyorwait_token', token);
  } else {
    localStorage.removeItem('buyorwait_token');
  }
}

function getUserEmail() {
  return localStorage.getItem('buyorwait_email') || '';
}

function setUserEmail(email) {
  if (email) {
    localStorage.setItem('buyorwait_email', email);
  } else {
    localStorage.removeItem('buyorwait_email');
  }
}

// Helper: Global Alerts
function showAlert(message, type = 'info', timeout = 5000) {
  const alertEl = document.getElementById('globalAlert');
  if (!alertEl) return;
  alertEl.className = `alert alert-${type}`;
  alertEl.textContent = message;
  alertEl.style.display = 'block';

  if (timeout > 0) {
    setTimeout(() => {
      alertEl.style.display = 'none';
    }, timeout);
  }
}

// Helper: Currency Formatting
function formatCurrency(amount, currency = 'USD') {
  if (amount === null || amount === undefined || isNaN(Number(amount))) {
    return '0.00';
  }
  const num = Number(amount);
  const curr = (currency || 'USD').toUpperCase().trim();

  // Explicit mappings for common currencies
  if (curr === 'INR') {
    try {
      return new Intl.NumberFormat('en-IN', {
        style: 'currency',
        currency: 'INR',
        maximumFractionDigits: 2,
        minimumFractionDigits: 2,
      }).format(num);
    } catch (_) {
      return `₹${num.toFixed(2)}`;
    }
  }

  if (curr === 'USD') {
    try {
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: 2,
        minimumFractionDigits: 2,
      }).format(num);
    } catch (_) {
      return `$${num.toFixed(2)}`;
    }
  }

  // Dynamic formatting for all other ISO currencies with graceful fallback
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: curr,
      maximumFractionDigits: 2,
      minimumFractionDigits: 2,
    }).format(num);
  } catch (_) {
    return `${curr} ${num.toFixed(2)}`;
  }
}

function hideAlert() {
  const alertEl = document.getElementById('globalAlert');
  if (alertEl) alertEl.style.display = 'none';
}

// Navigation & Auth View Switching
function switchAuthTab(tab) {
  hideAlert();
  const loginBtn = document.getElementById('tabLoginBtn');
  const regBtn = document.getElementById('tabRegisterBtn');
  const loginForm = document.getElementById('loginForm');
  const regForm = document.getElementById('registerForm');

  if (tab === 'login') {
    loginBtn.classList.add('active');
    regBtn.classList.remove('active');
    loginForm.style.display = 'block';
    regForm.style.display = 'none';
  } else {
    regBtn.classList.add('active');
    loginBtn.classList.remove('active');
    regForm.style.display = 'block';
    loginForm.style.display = 'none';
  }
}

function switchAppTab(tabName) {
  hideAlert();
  const tabs = ['evaluate', 'profile', 'statements', 'history'];
  tabs.forEach(t => {
    const btn = document.getElementById(`tab-${t}`);
    const content = document.getElementById(`tabContent${t.charAt(0).toUpperCase() + t.slice(1)}`);
    if (btn) btn.classList.toggle('active', t === tabName);
    if (content) content.style.display = (t === tabName) ? 'block' : 'none';
  });

  if (tabName === 'profile') loadProfile();
  if (tabName === 'history') loadDecisionHistory();
}

function updateAuthUI() {
  const token = getToken();
  const authSec = document.getElementById('authSection');
  const appSec = document.getElementById('appSection');
  const emailTag = document.getElementById('userEmailTag');
  const logoutBtn = document.getElementById('logoutBtn');

  if (token) {
    if (authSec) authSec.style.display = 'none';
    if (appSec) appSec.style.display = 'block';
    if (emailTag) {
      emailTag.textContent = getUserEmail();
      emailTag.style.display = 'inline-block';
    }
    if (logoutBtn) logoutBtn.style.display = 'inline-block';
    // Initialize defaults
    const today = new Date().toISOString().split('T')[0];
    const reqDateEl = document.getElementById('evalReqDate');
    if (reqDateEl && !reqDateEl.value) reqDateEl.value = today;
  } else {
    if (authSec) authSec.style.display = 'block';
    if (appSec) appSec.style.display = 'none';
    if (emailTag) emailTag.style.display = 'none';
    if (logoutBtn) logoutBtn.style.display = 'none';
  }
}

// API Request Wrapper
async function apiRequest(endpoint, options = {}) {
  const token = getToken();
  const headers = options.headers || {};

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  if (!(options.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  try {
    const res = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers
    });

    const isJson = (res.headers.get('content-type') || '').includes('application/json');
    const data = isJson ? await res.json() : null;

    if (res.status === 401) {
      // Token expired or revoked
      setToken(null);
      setUserEmail(null);
      updateAuthUI();
      showAlert('Session expired. Please sign in again.', 'warning');
      throw new Error('Unauthorized');
    }

    if (!res.ok) {
      const errMsg = (data && (data.detail || (data.error && data.error.message) || data.title)) || `Request failed with status ${res.status}`;
      const err = new Error(errMsg);
      err.status = res.status;
      err.data = data;
      throw err;
    }

    return data;
  } catch (err) {
    throw err;
  }
}

// Auth Handlers
async function handleLogin(e) {
  e.preventDefault();
  hideAlert();
  const email = document.getElementById('loginEmail').value.trim();
  const password = document.getElementById('loginPassword').value;
  const btn = document.getElementById('loginSubmitBtn');

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Signing in...';

  try {
    const res = await apiRequest('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password })
    });

    setToken(res.access_token);
    setUserEmail(email);
    updateAuthUI();
    showAlert('Welcome back! Successfully authenticated.', 'success');
    loadProfile();
  } catch (err) {
    showAlert(err.message || 'Login failed', 'danger');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span>Sign In</span>';
  }
}

async function handleRegister(e) {
  e.preventDefault();
  hideAlert();
  const fullName = document.getElementById('regFullName').value.trim();
  const email = document.getElementById('regEmail').value.trim();
  const password = document.getElementById('regPassword').value;
  const btn = document.getElementById('regSubmitBtn');

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Creating account...';

  try {
    await apiRequest('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, full_name: fullName })
    });

    // Auto login
    const loginRes = await apiRequest('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password })
    });

    setToken(loginRes.access_token);
    setUserEmail(email);
    updateAuthUI();
    showAlert('Account created! Now please configure your financial profile.', 'success');
    switchAppTab('profile');
  } catch (err) {
    showAlert(err.message || 'Registration failed', 'danger');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span>Register & Setup Profile</span>';
  }
}

async function handleLogout() {
  const token = getToken();
  if (token) {
    try {
      await apiRequest('/auth/logout', { method: 'POST' });
    } catch (_) {}
  }
  setToken(null);
  setUserEmail(null);
  updateAuthUI();
  showAlert('Signed out successfully.', 'info');
}

// Profile Handlers
async function loadProfile() {
  try {
    const prof = await apiRequest('/profile');
    const homeCurr = prof.home_currency || 'USD';
    document.getElementById('profHomeCurrency').value = homeCurr;
    const evalCurrEl = document.getElementById('evalCurrency');
    if (evalCurrEl && (!evalCurrEl.value || evalCurrEl.value === 'USD')) {
      evalCurrEl.value = homeCurr;
    }
    document.getElementById('profBalance').value = prof.current_available_balance ?? '';
    document.getElementById('profMinKeep').value = prof.minimum_balance_to_keep ?? '';
    document.getElementById('profProtected').value = (prof.protected_categories || []).join(', ');
    document.getElementById('profReducible').value = (prof.reducible_categories || []).join(', ');
    document.getElementById('profStoppable').value = (prof.stoppable_categories || []).join(', ');
    document.getElementById('profMaxInstallments').value = prof.max_installment_months ?? '';
  } catch (err) {
    if (err.status === 404) {
      // Profile not set up yet
      showAlert('Please initialize your financial profile below.', 'info');
    }
  }
}

async function handleSaveProfile(e) {
  e.preventDefault();
  hideAlert();
  const btn = document.getElementById('saveProfileBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Saving...';

  const body = {
    home_currency: document.getElementById('profHomeCurrency').value.trim().toUpperCase(),
    current_available_balance: parseFloat(document.getElementById('profBalance').value) || 0,
    minimum_balance_to_keep: parseFloat(document.getElementById('profMinKeep').value) || 0,
    protected_categories: document.getElementById('profProtected').value.split(',').map(s => s.trim()).filter(Boolean),
    reducible_categories: document.getElementById('profReducible').value.split(',').map(s => s.trim()).filter(Boolean),
    stoppable_categories: document.getElementById('profStoppable').value.split(',').map(s => s.trim()).filter(Boolean),
  };

  const maxInst = document.getElementById('profMaxInstallments').value;
  if (maxInst) {
    body.max_installment_months = parseInt(maxInst, 10);
  }

  try {
    await apiRequest('/profile', {
      method: 'PUT',
      body: JSON.stringify(body)
    });
    showAlert('Financial profile saved successfully!', 'success');
  } catch (err) {
    showAlert(err.message || 'Failed to save profile', 'danger');
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Save Financial Profile';
  }
}

// Statement Upload Handlers
async function handleUploadStatement(e) {
  e.preventDefault();
  hideAlert();
  const fileInput = document.getElementById('statementFile');
  if (!fileInput.files.length) {
    showAlert('Please select a CSV statement file to upload.', 'warning');
    return;
  }

  const btn = document.getElementById('uploadBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Uploading & Sanitizing...';

  const formData = new FormData();
  formData.append('file', fileInput.files[0]);
  formData.append('sign_convention', document.getElementById('signConvention').value);

  try {
    const res = await apiRequest('/imports', {
      method: 'POST',
      body: formData
    });

    currentStagedBatchId = res.batch_id;
    renderImportPreview(res);
    showAlert(`Statement parsed! Found ${res.total_rows} total rows (${res.accepted_rows} accepted).`, 'success');
  } catch (err) {
    showAlert(err.message || 'Failed to upload statement', 'danger');
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Upload & Preview Statement';
  }
}

function renderImportPreview(preview) {
  const card = document.getElementById('importPreviewCard');
  const body = document.getElementById('importPreviewBody');
  card.style.display = 'block';

  body.innerHTML = `
    <div class="grid-3" style="margin-bottom: 1rem;">
      <div class="stat-box">
        <div class="stat-label">Total Rows</div>
        <div class="stat-value">${preview.total_rows}</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Accepted</div>
        <div class="stat-value" style="color: var(--success);">${preview.accepted_rows}</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Duplicates / Skipped</div>
        <div class="stat-value" style="color: var(--warning);">${preview.duplicate_rows || 0}</div>
      </div>
    </div>
    <p style="font-size: 0.85rem; color: var(--text-muted);">
      Batch ID: <code>${preview.batch_id}</code><br/>
      File: <strong>${preview.filename}</strong> &bull; Status: <span class="badge">${preview.status}</span>
    </p>
  `;
}

async function handleCommitImport() {
  if (!currentStagedBatchId) return;
  hideAlert();
  const btn = document.getElementById('commitImportBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Committing to ledger...';

  try {
    const res = await apiRequest(`/imports/${currentStagedBatchId}/verify`, {
      method: 'POST',
      body: JSON.stringify({ override_ambiguous: false })
    });

    showAlert(`Success! ${res.committed_rows} transactions verified and committed to your permanent ledger.`, 'success');
    document.getElementById('importPreviewCard').style.display = 'none';
    currentStagedBatchId = null;
    document.getElementById('uploadForm').reset();
  } catch (err) {
    showAlert(err.message || 'Failed to commit import', 'danger');
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Verify & Commit Transactions';
  }
}

// Purchase Evaluation Handlers
async function handleEvaluate(e) {
  e.preventDefault();
  hideAlert();

  const btn = document.getElementById('evaluateBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Running Solvency Engine...';

  const reqDate = document.getElementById('evalReqDate').value;
  const compDate = document.getElementById('evalCompDate').value || null;

  const payload = {
    item_description: document.getElementById('evalDesc').value.trim(),
    requested_amount: parseFloat(document.getElementById('evalAmount').value),
    currency: document.getElementById('evalCurrency').value.trim().toUpperCase(),
    request_date: reqDate,
    desired_completion_date: compDate,
    allows_partial_payment: document.getElementById('evalPartial').checked,
    merchant_name: document.getElementById('evalMerchant').value.trim(),
    category: document.getElementById('evalCategory').value.trim()
  };

  try {
    const res = await apiRequest('/purchases/evaluate', {
      method: 'POST',
      body: JSON.stringify(payload)
    });

    renderEvaluationResult(res, payload.currency, payload.requested_amount);
    showAlert('Evaluation completed successfully!', 'success');
  } catch (err) {
    if (err.data && err.data.code === 'DATA_INSUFFICIENT') {
      renderDataInsufficient(err.data);
    } else {
      showAlert(err.message || 'Evaluation failed', 'danger');
    }
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Run Financial Decision Engine';
  }
}

function renderEvaluationResult(res, requestedCurrency = null, requestedAmount = null) {
  const container = document.getElementById('evaluateResultContainer');
  const verdictClass = `verdict-${res.verdict}`;
  const riskClass = `risk-${res.risk_tier || 'LOW_RISK'}`;

  // Dynamically resolve currency from supporting_facts, response, input payload, or profile
  const currency = (
    (res.grounded_explanation && res.grounded_explanation.supporting_facts && res.grounded_explanation.supporting_facts.currency) ||
    res.currency ||
    requestedCurrency ||
    (document.getElementById('evalCurrency') ? document.getElementById('evalCurrency').value : null) ||
    'USD'
  ).toUpperCase().trim();

  const formattedSafeAmount = formatCurrency(res.amount_safe_to_pay, currency);

  let expHeadline = '';
  let expText = res.decision_explanation || '';
  let expFacts = '';
  let expAction = '';

  if (res.grounded_explanation) {
    expHeadline = res.grounded_explanation.headline || '';
    expText = res.grounded_explanation.concise_explanation || res.decision_explanation;
    expAction = res.grounded_explanation.suggested_action || '';
    if (res.grounded_explanation.supporting_facts) {
      const facts = res.grounded_explanation.supporting_facts;
      expFacts = Object.entries(facts).map(([k, v]) => {
        let displayVal = v;
        // Format monetary amounts if key implies monetary value
        if (['requested_amount', 'safe_amount', 'headroom_p50', 'headroom_p90', 'safe_amount_p50', 'safe_amount_p90', 'reserve_required'].includes(k) && v !== null && v !== undefined) {
          displayVal = formatCurrency(v, currency);
        }
        return `<li><strong>${k.replace(/_/g, ' ')}:</strong> ${displayVal}</li>`;
      }).join('');
    }
  }

  // Risk metrics formatted with dynamic currency
  let riskDetailsHtml = '';
  if (res.risk_assessment) {
    const p90Buffer = formatCurrency(res.risk_assessment.headroom_p90 || 0, currency);
    const p50Headroom = res.risk_assessment.headroom_p50 !== undefined ? formatCurrency(res.risk_assessment.headroom_p50, currency) : null;
    riskDetailsHtml = `
      <div style="margin-top: 1rem; padding: 0.85rem; background: var(--bg-main); border-radius: var(--radius); font-size: 0.8rem; line-height: 1.6;">
        <div><strong>Risk Engine Stress Summary:</strong> ${res.risk_assessment.stress_summary || 'Standard'}</div>
        <div><strong>P90 Headroom Buffer:</strong> ${p90Buffer}</div>
        ${p50Headroom ? `<div><strong>Headroom P50:</strong> ${p50Headroom}</div>` : ''}
        ${res.risk_assessment.safe_amount_p90 !== undefined ? `<div><strong>Safe Amount (P90):</strong> ${formatCurrency(res.risk_assessment.safe_amount_p90, currency)}</div>` : ''}
      </div>
    `;
  }

  const requestedAmountFormatted = requestedAmount !== null && requestedAmount !== undefined
    ? formatCurrency(requestedAmount, currency)
    : (res.grounded_explanation && res.grounded_explanation.supporting_facts && res.grounded_explanation.supporting_facts.requested_amount
      ? formatCurrency(res.grounded_explanation.supporting_facts.requested_amount, currency)
      : null);

  container.innerHTML = `
    <div class="decision-card">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; gap: 0.5rem;">
        <div>
          <span class="verdict-badge ${verdictClass}">${res.verdict.replace(/_/g, ' ')}</span>
          <span class="risk-tag ${riskClass}" style="margin-left: 0.5rem;">${(res.risk_tier || 'LOW RISK').replace(/_/g, ' ')}</span>
        </div>
        <span style="font-size: 0.8rem; color: var(--text-muted);">Status: <strong>${(res.affordability_status || '').replace(/_/g, ' ')}</strong></span>
      </div>

      <div class="grid-2" style="margin-bottom: 1.25rem;">
        <div class="stat-box">
          <div class="stat-label">Amount Safe to Pay Now</div>
          <div class="stat-value" style="color: var(--primary);">${formattedSafeAmount}</div>
          ${requestedAmountFormatted ? `<div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.25rem;">Requested: <strong>${requestedAmountFormatted}</strong></div>` : ''}
        </div>
        <div class="stat-box">
          <div class="stat-label">Recommended Method</div>
          <div class="stat-value" style="font-size: 1.15rem;">${(res.recommended_payment_method || 'none').replace(/_/g, ' ')}</div>
          <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.25rem;">Currency: <strong>${currency}</strong></div>
        </div>
      </div>

      ${res.earliest_date_for_full_payment ? `
        <div class="alert alert-info" style="margin-bottom: 1rem;">
          <strong>Earliest Date for Full Payment:</strong> ${res.earliest_date_for_full_payment}
        </div>
      ` : ''}

      ${res.payment_plan && res.payment_plan !== 'none' ? `
        <div class="alert alert-warning" style="margin-bottom: 1rem;">
          <strong>Recommended Payment Plan:</strong> <code>${res.payment_plan}</code>
        </div>
      ` : ''}

      <div style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border);">
        <h4 style="font-size: 1rem; font-weight: 700; margin-bottom: 0.4rem;">${expHeadline || 'Financial Assessment'}</h4>
        <p style="font-size: 0.9rem; color: var(--text-main); margin-bottom: 0.75rem;">${expText}</p>
        ${expAction ? `<p style="font-size: 0.85rem; color: var(--primary); font-weight: 600;">Action: ${expAction}</p>` : ''}
        ${expFacts ? `<ul style="font-size: 0.8rem; color: var(--text-muted); margin-left: 1.2rem; margin-top: 0.5rem;">${expFacts}</ul>` : ''}
      </div>

      ${riskDetailsHtml}
    </div>
  `;
}

function renderDataInsufficient(err) {
  const container = document.getElementById('evaluateResultContainer');
  const errorObj = err.error || {};
  container.innerHTML = `
    <div class="card" style="border-left: 6px solid var(--warning);">
      <h3 class="card-title" style="color: var(--warning); margin-bottom: 0.5rem;">Data Insufficient for Evaluation</h3>
      <p style="font-size: 0.9rem; color: var(--text-main); margin-bottom: 0.75rem;">
        ${errorObj.message || err.detail || 'Insufficient verified historical transaction data.'}
      </p>
      ${errorObj.user_action_required ? `
        <div class="alert alert-warning">
          <strong>Action Required:</strong> ${errorObj.user_action_required}
        </div>
      ` : ''}
      <button class="btn btn-outline btn-sm" onclick="switchAppTab('statements')">
        Upload Bank Statement Now
      </button>
    </div>
  `;
}

// Decision History Handlers
async function loadDecisionHistory() {
  const tbody = document.getElementById('historyTableBody');
  tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;"><span class="spinner spinner-dark"></span> Loading history...</td></tr>';

  try {
    const res = await apiRequest('/decisions?page=1&page_size=20');
    if (!res.items || !res.items.length) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No decisions evaluated yet.</td></tr>';
      return;
    }

    tbody.innerHTML = res.items.map(d => {
      const historyCurr = (
        (d.grounded_explanation && d.grounded_explanation.supporting_facts && d.grounded_explanation.supporting_facts.currency) ||
        (document.getElementById('profHomeCurrency') ? document.getElementById('profHomeCurrency').value : null) ||
        'USD'
      );
      const safeAmountFormatted = formatCurrency(d.amount_safe_to_pay, historyCurr);
      return `
        <tr>
          <td>${(d.created_at || '').substring(0, 10)}</td>
          <td><span class="verdict-badge verdict-${d.verdict}" style="font-size: 0.75rem; padding: 0.2rem 0.5rem;">${d.verdict}</span></td>
          <td>${(d.affordability_status || '').replace(/_/g, ' ')}</td>
          <td><strong>${safeAmountFormatted}</strong></td>
          <td>${(d.recommended_payment_method || 'none').replace(/_/g, ' ')}</td>
          <td><span class="risk-tag risk-${d.risk_tier || 'LOW_RISK'}">${d.risk_tier || 'LOW'}</span></td>
          <td style="max-width: 250px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${d.decision_explanation}">${d.decision_explanation}</td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--danger);">Failed to load history: ${err.message}</td></tr>`;
  }
}

// Initial bootstrap
document.addEventListener('DOMContentLoaded', () => {
  const logoutBtn = document.getElementById('logoutBtn');
  if (logoutBtn) logoutBtn.addEventListener('click', handleLogout);

  const brand = document.getElementById('navBrand');
  if (brand) {
    brand.addEventListener('click', (e) => {
      e.preventDefault();
      if (getToken()) switchAppTab('evaluate');
    });
  }

  updateAuthUI();
});