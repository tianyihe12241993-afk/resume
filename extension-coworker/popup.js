// Co-worker popup. Two responsibilities:
//   1. Let the co-worker pick a "main profile" once. The content scripts read
//      this from chrome.storage.local to decide which tailored resume to
//      auto-download and which answer library to fill.
//   2. Trigger Fill Form on the active tab.

const DEFAULT_SERVER = 'http://127.0.0.1:8001';

async function getServer() {
  const { server } = await chrome.storage.local.get('server');
  return (server || DEFAULT_SERVER).replace(/\/+$/, '');
}

async function loadProfiles() {
  const sel = document.getElementById('main-profile');
  const server = await getServer();
  try {
    const r = await fetch(server + '/api/admin/profiles', { credentials: 'include' });
    if (r.status === 401) {
      setStatus(`Not signed in. Open ${server}/login in a tab, then reopen this popup.`, 'err');
      return;
    }
    if (!r.ok) {
      setStatus(`Server error: ${r.status}`, 'err');
      return;
    }
    const data = await r.json();
    const profiles = data.profiles || [];
    const stored = await chrome.storage.local.get('mainProfileId');
    sel.innerHTML = '<option value="">— pick one —</option>' +
      profiles.map((p) => `<option value="${p.id}">${(p.name || '').replace(/</g, '&lt;')}</option>`).join('');
    if (stored.mainProfileId) sel.value = String(stored.mainProfileId);
    sel.addEventListener('change', async () => {
      const v = sel.value ? parseInt(sel.value, 10) : null;
      await chrome.storage.local.set({ mainProfileId: v });
      setStatus(v ? 'Main profile saved.' : 'Cleared.', 'ok');
    });
  } catch (e) {
    setStatus((e && e.message) || 'fetch failed', 'err');
  }
}

function setStatus(text, cls = '') {
  const el = document.getElementById('status');
  el.textContent = text;
  el.className = cls;
}

function bindSettings() {
  document.getElementById('settings').addEventListener('click', async () => {
    const cur = await getServer();
    const v = prompt('Tailor Studio server URL', cur);
    if (!v) return;
    await chrome.storage.local.set({ server: v.replace(/\/+$/, '') });
    await loadProfiles();
  });
}

bindSettings();
loadProfiles();
