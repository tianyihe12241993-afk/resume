// Tailor Studio — unified service worker. Routes content-script & popup
// messages to the studio backend. Combines both former extensions:
//   Sourcing:  list_profiles, queue_url
//   Apply:     resume_for, fetch_answers, draft_answers, upload_observed,
//              download_resume
//   Shared:    rescue_check, rescue_send  (silent recovery of stuck JDs)

const DEFAULT_SERVER = 'http://127.0.0.1:8001';

async function getServer() {
  const { server } = await chrome.storage.local.get('server');
  return (server || DEFAULT_SERVER).replace(/\/+$/, '');
}

async function getMainProfileId() {
  const { mainProfileId } = await chrome.storage.local.get('mainProfileId');
  return mainProfileId || null;
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

async function getJson(path) {
  const server = await getServer();
  const r = await fetch(server + path, { credentials: 'include' });
  if (!r.ok) {
    const text = await r.text().catch(() => '');
    return { __error: `HTTP ${r.status}: ${text.slice(0, 200)}` };
  }
  return r.json();
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      if (!msg || !msg.type) { sendResponse({ error: 'no message type' }); return; }

      // ── Shared: rescue ──────────────────────────────────────────────
      if (msg.type === 'rescue_check') {
        const r = await postJson('/api/extension/check_url', { url: msg.url });
        if (r.__error) sendResponse({ stuck: false, error: r.__error });
        else sendResponse({ stuck: !!r.stuck, count: r.count || 0 });
        return;
      }
      if (msg.type === 'rescue_send') {
        sendResponse(await postJson('/api/extension/rescue', { url: msg.url, html: msg.html }));
        return;
      }

      // ── Sourcing: floating Add button ───────────────────────────────
      if (msg.type === 'list_profiles') {
        const r = await getJson('/api/admin/profiles');
        if (r.__error) sendResponse({ error: r.__error });
        else sendResponse({ profiles: (r.profiles || []).map((p) => ({ id: p.id, name: p.name })) });
        return;
      }
      if (msg.type === 'queue_url') {
        const r = await postJson('/api/extension/queue', {
          urls: [msg.url], profile_ids: [msg.profileId],
        });
        sendResponse(r && r.__error ? { error: r.__error } : r);
        return;
      }

      // ── Apply: resume widget / draft / upload audit ─────────────────
      if (msg.type === 'set_main_profile') {
        await chrome.storage.local.set({ mainProfileId: msg.profileId || null });
        sendResponse({ ok: true });
        return;
      }
      if (msg.type === 'resume_for') {
        // Explicit profile (from the in-page picker) wins over the saved main.
        const pid = msg.profileId || await getMainProfileId();
        const qs = new URLSearchParams({ url: msg.url });
        if (pid) qs.set('profile_id', String(pid));
        sendResponse(await getJson('/api/extension/resume_for?' + qs.toString()));
        return;
      }
      if (msg.type === 'fetch_answers') {
        const pid = await getMainProfileId();
        if (!pid) { sendResponse({ ok: false, error: 'No main profile set — pick one in the popup first.' }); return; }
        const r = await getJson(`/api/extension/answers?profile_id=${pid}`);
        if (r.__error) sendResponse({ ok: false, error: r.__error });
        else sendResponse({ ok: true, answers: r.answers, profile_id: r.profile_id });
        return;
      }
      if (msg.type === 'draft_answers') {
        const pid = await getMainProfileId();
        sendResponse(await postJson('/api/extension/draft_answers',
          { url: msg.url, profile_id: pid, questions: msg.questions }));
        return;
      }
      if (msg.type === 'upload_observed') {
        sendResponse(await postJson('/api/extension/upload_observed', {
          url: msg.url, filename: msg.filename, size: msg.size, sha256: msg.sha256,
        }));
        return;
      }
      if (msg.type === 'download_resume') {
        const server = await getServer();
        try {
          const downloadId = await chrome.downloads.download({
            url: server + msg.path, filename: msg.filename,
            conflictAction: 'overwrite', saveAs: false,
          });
          sendResponse({ ok: true, downloadId, filename: msg.filename });
        } catch (e) {
          sendResponse({ ok: false, error: (e && e.message) || String(e) });
        }
        return;
      }

      sendResponse({ error: 'unknown message' });
    } catch (e) {
      sendResponse({ error: (e && e.message) || String(e) });
    }
  })();
  return true;  // async response
});

chrome.runtime.onInstalled.addListener(() => { /* no-op */ });
