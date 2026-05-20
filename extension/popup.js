// Tailor Studio extension popup. Quick Add: read all open tabs that look
// like job postings, let the user pick which profile(s) to queue them into,
// POST the URL list to /api/extension/queue, optionally close the tabs.

const DEFAULT_SERVER = 'http://127.0.0.1:8001';

// Hosts whose pages count as "job postings" worth queueing. Match by suffix
// so subdomains (boards.greenhouse.io, jobs.lever.co, etc.) are all caught.
const ATS_HOSTS = [
  'greenhouse.io',
  'lever.co',
  'ashbyhq.com',
  'myworkdayjobs.com',
  'rippling.com',
  'smartrecruiters.com',
  'workable.com',
  'oraclecloud.com',
  'icims.com',
  'workday.com',
  'ripplehire.com',
  'pinpointhq.com',
  'personio.com',
  'freshteam.com',
  'applytojob.com',
  'linkedin.com',         // /jobs/view/ etc.
  'indeed.com',
  'jobright.ai',
  'ashby.com',
  'recruiterflow.com',
  'gem.com',
  'bamboohr.com',
  'jazzhr.com',
  'jobvite.com',
  'taleo.net',
  'adp.com',
  'brassring.com',
];

const state = {
  server: DEFAULT_SERVER,
  profiles: [],            // [{id, name}]
  selectedProfileIds: [],  // [id]
  tabs: [],                // [{id, url, title, host, selected}]
};

async function getStored() {
  const r = await chrome.storage.local.get(['server', 'selectedProfileIds']);
  return r;
}
async function setStored(obj) {
  await chrome.storage.local.set(obj);
}

function looksLikeJobUrl(url) {
  try {
    const u = new URL(url);
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return false;
    const host = u.hostname.toLowerCase();
    return ATS_HOSTS.some((h) => host === h || host.endsWith('.' + h));
  } catch {
    return false;
  }
}

async function loadTabs() {
  const all = await chrome.tabs.query({});
  const filtered = all
    .filter((t) => t.url && looksLikeJobUrl(t.url))
    .map((t) => ({
      id: t.id, url: t.url, title: t.title || t.url,
      host: new URL(t.url).hostname.replace(/^www\./, ''),
      selected: true,
    }));
  // dedupe by URL
  const seen = new Set();
  state.tabs = filtered.filter((t) => {
    if (seen.has(t.url)) return false;
    seen.add(t.url); return true;
  });
  renderTabs();
}

function renderTabs() {
  const ul = document.getElementById('urls');
  document.getElementById('urls-count').textContent = state.tabs.length;
  if (!state.tabs.length) {
    ul.innerHTML = '<li class="empty">No job tabs open. Open some postings in this window first.</li>';
    return;
  }
  ul.innerHTML = '';
  for (const t of state.tabs) {
    const li = document.createElement('li');
    const lbl = document.createElement('label');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = t.selected;
    cb.addEventListener('change', () => { t.selected = cb.checked; updateButton(); });
    const wrap = document.createElement('div');
    wrap.style.flex = '1'; wrap.style.minWidth = '0';
    const title = document.createElement('div');
    title.className = 'title'; title.textContent = t.title;
    title.title = t.url;
    const host = document.createElement('div');
    host.className = 'host'; host.textContent = t.host;
    wrap.appendChild(title); wrap.appendChild(host);
    lbl.appendChild(cb); lbl.appendChild(wrap);
    li.appendChild(lbl);
    ul.appendChild(li);
  }
  updateButton();
}

async function loadProfiles() {
  const ul = document.getElementById('profiles');
  try {
    const r = await fetch(`${state.server}/api/admin/profiles`, { credentials: 'include' });
    if (r.status === 401) {
      ul.innerHTML = `<li class="empty">Not signed in. <a href="${state.server}/login" target="_blank">Log in</a> first.</li>`;
      return;
    }
    if (!r.ok) {
      ul.innerHTML = `<li class="empty err">Server error: ${r.status}</li>`;
      return;
    }
    const data = await r.json();
    state.profiles = (data.profiles || []).map((p) => ({ id: p.id, name: p.name }));
    if (!state.profiles.length) {
      ul.innerHTML = '<li class="empty">No profiles. Create one in the web UI first.</li>';
      return;
    }
    ul.innerHTML = '';

    const saved = new Set(state.selectedProfileIds || []);
    // Default to the first profile if nothing saved.
    if (!saved.size) saved.add(state.profiles[0].id);
    state.selectedProfileIds = [];
    for (const p of state.profiles) {
      const li = document.createElement('li');
      const lbl = document.createElement('label');
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = saved.has(p.id);
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
      li.appendChild(lbl);
      ul.appendChild(li);
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
  const status = document.getElementById('status');
  const results = document.getElementById('results');
  results.style.display = 'none'; results.classList.remove('err');
  const selected = state.tabs.filter((t) => t.selected);
  const urls = selected.map((t) => t.url);
  if (!urls.length || !state.selectedProfileIds.length) return;

  btn.disabled = true;
  status.textContent = 'Queueing…'; status.className = '';
  try {
    const r = await fetch(`${state.server}/api/extension/queue`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ urls, profile_ids: state.selectedProfileIds }),
    });
    if (r.status === 401) throw new Error('Not signed in. Log in to tailor studio first.');
    if (!r.ok) {
      const body = await r.text();
      throw new Error(`Server ${r.status}: ${body.slice(0, 200)}`);
    }
    const data = await r.json();
    const lines = [];
    let anyAdded = false;
    for (const res of data.results) {
      if (res.error) {
        lines.push(`✗ ${res.profile_name || ('#' + res.profile_id)}: ${res.error}`);
      } else {
        anyAdded = anyAdded || res.added > 0;
        const skip = (res.skipped_existing || 0);
        lines.push(`✓ ${res.profile_name}: ${res.added} queued${skip ? `, ${skip} skipped (already submitted)` : ''}`);
      }
    }
    results.innerHTML = lines.map((l) => `<div>${l}</div>`).join('');
    results.style.display = 'block';
    status.textContent = ''; status.className = '';

    if (anyAdded && document.getElementById('close-after').checked) {
      // Close only the tabs we actually queued.
      try { await chrome.tabs.remove(selected.map((t) => t.id)); } catch {}
      // Refresh the URL list (will likely be empty now).
      await loadTabs();
    }
  } catch (e) {
    status.textContent = e.message || 'failed';
    status.className = 'err';
    results.classList.add('err');
  } finally {
    btn.disabled = false;
    updateButton();
  }
}

function bindSettings() {
  document.getElementById('settings').addEventListener('click', async () => {
    const v = prompt('Tailor Studio server URL', state.server);
    if (!v) return;
    state.server = v.replace(/\/+$/, '');
    await setStored({ server: state.server });
    await loadProfiles();
  });
}

(async function init() {
  const stored = await getStored();
  state.server = stored.server || DEFAULT_SERVER;
  state.selectedProfileIds = stored.selectedProfileIds || [];
  document.getElementById('queue').addEventListener('click', doQueue);
  bindSettings();
  await Promise.all([loadTabs(), loadProfiles()]);
})();
