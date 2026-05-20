// Sourcing extension — service worker. Routes content-script & popup
// messages to the studio backend. Three responsibilities:
//   • rescue_check / rescue_send  → silent recovery of stuck JDs
//   • queue (from popup)          → batch-add open tabs to selected profiles

const DEFAULT_SERVER = 'http://127.0.0.1:8001';

async function getServer() {
  const { server } = await chrome.storage.local.get('server');
  return (server || DEFAULT_SERVER).replace(/\/+$/, '');
}

async function postJson(path, body) {
  const server = await getServer();
  const r = await fetch(server + path, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const text = await r.text().catch(() => '');
    return { __error: `HTTP ${r.status}: ${text.slice(0, 200)}` };
  }
  return r.json();
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      if (msg && msg.type === 'rescue_check') {
        const r = await postJson('/api/extension/check_url', { url: msg.url });
        if (r.__error) sendResponse({ stuck: false, error: r.__error });
        else sendResponse({ stuck: !!r.stuck, count: r.count || 0 });
        return;
      }
      if (msg && msg.type === 'rescue_send') {
        const r = await postJson('/api/extension/rescue', { url: msg.url, html: msg.html });
        sendResponse(r);
        return;
      }
      sendResponse({ error: 'unknown message' });
    } catch (e) {
      sendResponse({ error: (e && e.message) || String(e) });
    }
  })();
  return true;
});

chrome.runtime.onInstalled.addListener(() => { /* no-op */ });
