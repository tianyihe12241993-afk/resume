// Tailor Studio unified popup.
//   Apply side  — pick the "main profile" the content scripts use (which
//                 tailored resume to auto-download, which answer library to
//                 draft from). Stored as `mainProfileId`.
//   Source side — read open job tabs, pick which profile(s) to queue them
//                 into, POST to /api/extension/queue, optionally close tabs.
// One /api/admin/profiles fetch feeds both the Apply <select> and the Source
// checkbox list.

const DEFAULT_SERVER = 'http://127.0.0.1:8001';

// Hosts whose pages count as job postings worth queueing.
const ATS_HOSTS = [
  'greenhouse.io', 'lever.co', 'ashbyhq.com', 'myworkdayjobs.com', 'rippling.com',
  'smartrecruiters.com', 'workable.com', 'oraclecloud.com', 'icims.com', 'workday.com',
  'ripplehire.com', 'pinpointhq.com', 'personio.com', 'freshteam.com', 'applytojob.com',
  'linkedin.com', 'indeed.com', 'jobright.ai', 'ashby.com', 'recruiterflow.com',
  'gem.com', 'bamboohr.com', 'jazzhr.com', 'jobvite.com', 'taleo.net', 'adp.com',
  'brassring.com',
];

const state = {
  server: DEFAULT_SERVER,
  profiles: [],            // [{id, name}]
  selectedProfileIds: [],  // source-side: queue targets
  mainProfileId: null,     // apply-side
  tabs: [],
};

const getStored = () =>
  chrome.storage.local.get(['server', 'selectedProfileIds', 'mainProfileId']);
const setStored = (obj) => chrome.storage.local.set(obj);

function setStatus(text, cls = '') {
  const el = document.getElementById('status');
  el.textContent = text; el.className = cls;
}

function looksLikeJobUrl(url) {
  try {
    const u = new URL(url);
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return false;
    const host = u.hostname.toLowerCase();
    return ATS_HOSTS.some((h) => host === h || host.endsWith('.' + h));
  } catch { return false; }
}

async function loadTabs() {
  const all = await chrome.tabs.query({});
  const filtered = all
    .filter((t) => t.url && looksLikeJobUrl(t.url))
    .map((t) => ({
      id: t.id, url: t.url, title: t.title || t.url,
      host: new URL(t.url).hostname.replace(/^www\./, ''), selected: true,
    }));
  const seen = new Set();
  state.tabs = filtered.filter((t) => (seen.has(t.url) ? false : (seen.add(t.url), true)));
  renderTabs();
}

function renderTabs() {
  const ul = document.getElementById('urls');
  document.getElementById('urls-count').textContent = state.tabs.length;
  if (!state.tabs.length) {
    ul.innerHTML = '<li class="empty">No job tabs open in any window.</li>';
    updateButton();
    return;
  }
  ul.innerHTML = '';
  for (const t of state.tabs) {
    const li = document.createElement('li');
    const lbl = document.createElement('label');
    const cb = document.createElement('input');
    cb.type = 'checkbox'; cb.checked = t.selected;
    cb.addEventListener('change', () => { t.selected = cb.checked; updateButton(); });
    const wrap = document.createElement('div');
    wrap.style.flex = '1'; wrap.style.minWidth = '0';
    const title = document.createElement('div');
    title.className = 'title'; title.textContent = t.title; title.title = t.url;
    const host = document.createElement('div');
    host.className = 'host'; host.textContent = t.host;
    wrap.appendChild(title); wrap.appendChild(host);
    lbl.appendChild(cb); lbl.appendChild(wrap);
    li.appendChild(lbl); ul.appendChild(li);
  }
  updateButton();
}

async function loadProfiles() {
  const ul = document.getElementById('profiles');
  const sel = document.getElementById('main-profile');
  try {
    const r = await fetch(`${state.server}/api/admin/profiles`, { credentials: 'include' });
    if (r.status === 401) {
      ul.innerHTML = `<li class="empty">Not signed in. <a href="${state.server}/login" target="_blank">Log in</a> first.</li>`;
      return;
    }
    if (!r.ok) { ul.innerHTML = `<li class="empty err">Server error: ${r.status}</li>`; return; }
    const data = await r.json();
    state.profiles = (data.profiles || []).map((p) => ({ id: p.id, name: p.name }));

    // Apply <select>
    sel.innerHTML = '<option value="">— pick one —</option>' +
      state.profiles.map((p) => `<option value="${p.id}">${(p.name || '').replace(/</g, '&lt;')}</option>`).join('');
    if (state.mainProfileId && state.profiles.some((p) => p.id === state.mainProfileId)) {
      sel.value = String(state.mainProfileId);
    }

    // Source checkbox list
    if (!state.profiles.length) {
      ul.innerHTML = '<li class="empty">No profiles. Create one in the web app first.</li>';
      return;
    }
    const saved = new Set(state.selectedProfileIds || []);
    if (!saved.size) saved.add(state.profiles[0].id);
    state.selectedProfileIds = [];
    ul.innerHTML = '';
    for (const p of state.profiles) {
      const li = document.createElement('li');
      const lbl = document.createElement('label');
      const cb = document.createElement('input');
      cb.type = 'checkbox'; cb.checked = saved.has(p.id);
      if (cb.checked) state.selectedProfileIds.push(p.id);
      cb.addEventListener('change', () => {
        if (cb.checked) state.selectedProfileIds.push(p.id);
        else state.selectedProfileIds = state.selectedProfileIds.filter((x) => x !== p.id);
        setStored({ selectedProfileIds: state.selectedProfileIds });
        updateButton();
      });
      const span = document.createElement('span');
      span.className = 'title'; span.textContent = p.name;
      lbl.appendChild(cb); lbl.appendChild(span);
      li.appendChild(lbl); ul.appendChild(li);
    }
    updateButton();
  } catch (e) {
    ul.innerHTML = `<li class="empty err">${e.message || 'fetch failed'}</li>`;
  }
}

function updateButton() {
  const nUrls = state.tabs.filter((t) => t.selected).length;
  const nProf = state.selectedProfileIds.length;
  const btn = document.getElementById('queue');
  btn.disabled = !(nUrls && nProf);
  btn.textContent = nUrls && nProf
    ? `Queue ${nUrls} URL${nUrls === 1 ? '' : 's'} → ${nProf} profile${nProf === 1 ? '' : 's'}`
    : 'Queue';
}

async function doQueue() {
  const btn = document.getElementById('queue');
  const results = document.getElementById('results');
  results.style.display = 'none'; results.classList.remove('err');
  const selected = state.tabs.filter((t) => t.selected);
  const urls = selected.map((t) => t.url);
  if (!urls.length || !state.selectedProfileIds.length) return;

  btn.disabled = true; setStatus('Queueing…');
  try {
    const r = await fetch(`${state.server}/api/extension/queue`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ urls, profile_ids: state.selectedProfileIds }),
    });
    if (r.status === 401) throw new Error('Not signed in. Log in to Tailor Studio first.');
    if (!r.ok) throw new Error(`Server ${r.status}: ${(await r.text()).slice(0, 200)}`);
    const data = await r.json();
    const lines = []; let anyAdded = false;
    for (const res of data.results) {
      if (res.error) lines.push(`✗ ${res.profile_name || ('#' + res.profile_id)}: ${res.error}`);
      else {
        anyAdded = anyAdded || res.added > 0;
        const skip = res.skipped_existing || 0;
        lines.push(`✓ ${res.profile_name}: ${res.added} queued${skip ? `, ${skip} already added` : ''}`);
      }
    }
    results.innerHTML = lines.map((l) => `<div>${l}</div>`).join('');
    results.style.display = 'block'; setStatus('');
    if (anyAdded && document.getElementById('close-after').checked) {
      try { await chrome.tabs.remove(selected.map((t) => t.id)); } catch {}
      await loadTabs();
    }
  } catch (e) {
    setStatus(e.message || 'failed', 'err');
    results.classList.add('err');
  } finally {
    btn.disabled = false; updateButton();
  }
}

(async function init() {
  const stored = await getStored();
  state.server = stored.server || DEFAULT_SERVER;
  state.selectedProfileIds = stored.selectedProfileIds || [];
  state.mainProfileId = stored.mainProfileId || null;

  document.getElementById('queue').addEventListener('click', doQueue);
  document.getElementById('main-profile').addEventListener('change', async (e) => {
    const v = e.target.value ? parseInt(e.target.value, 10) : null;
    state.mainProfileId = v;
    await setStored({ mainProfileId: v });
    setStatus(v ? 'Main profile saved.' : 'Main profile cleared.', 'ok');
  });
  document.getElementById('settings').addEventListener('click', async () => {
    const v = prompt('Tailor Studio server URL', state.server);
    if (!v) return;
    state.server = v.replace(/\/+$/, '');
    await setStored({ server: state.server });
    await loadProfiles();
  });

  await Promise.all([loadTabs(), loadProfiles()]);
})();
