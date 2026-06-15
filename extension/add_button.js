// Tailor Studio Sourcing extension — floating "Add" button.
//
// Injected on every page. Lets you review a job description in the page, then
// click "Add this job" to send the current URL into the tailoring system for a
// chosen profile. All server calls go through the background service worker
// (the content script's own origin is the page, so it can't call the API
// directly — CORS). Manual, one-at-a-time, so no duplicates and no EasyApply
// spam: you only add what you've actually looked at.

(function () {
  if (window.__tsAddButton) return;            // guard against double-inject
  window.__tsAddButton = true;

  const send = (msg) =>
    new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(msg, (resp) => {
          if (chrome.runtime.lastError) return resolve({ error: chrome.runtime.lastError.message });
          resolve(resp || {});
        });
      } catch (e) { resolve({ error: String(e) }); }
    });

  const host = document.createElement('div');
  host.id = 'ts-add-host';
  // Top-right: clears the apply-side UI (Resume widget bottom-right, Draft
  // button bottom-left) that also appears on job pages in this combined build.
  host.style.cssText = 'position:fixed;right:16px;top:84px;z-index:2147483646;';
  const root = host.attachShadow({ mode: 'open' });
  root.innerHTML = `
    <style>
      :host, * { box-sizing: border-box; }
      .bubble {
        width:44px;height:44px;border-radius:50%;border:none;cursor:pointer;
        background:#4f46e5;color:#fff;font-size:20px;line-height:44px;
        box-shadow:0 4px 14px rgba(0,0,0,.25);
      }
      .card {
        width:268px;background:#fff;border:1px solid #e5e7eb;border-radius:12px;
        box-shadow:0 8px 28px rgba(0,0,0,.18);overflow:hidden;
        font:13px/1.4 -apple-system,system-ui,Segoe UI,sans-serif;color:#111827;
      }
      .hd { display:flex;align-items:center;gap:6px;padding:10px 12px;
            background:#eef2ff;border-bottom:1px solid #e0e7ff;font-weight:600;color:#3730a3; }
      .hd .x { margin-left:auto;cursor:pointer;color:#6b7280;font-weight:400;font-size:15px; }
      .bd { padding:12px; }
      label { display:block;font-size:11px;font-weight:600;color:#6b7280;margin-bottom:4px; }
      select { width:100%;padding:6px 8px;border:1px solid #d1d5db;border-radius:7px;
               font:inherit;background:#fff;margin-bottom:10px; }
      .add { width:100%;padding:8px;border:none;border-radius:8px;cursor:pointer;
             background:#4f46e5;color:#fff;font-weight:600; }
      .add:disabled { opacity:.5;cursor:default; }
      .status { margin-top:8px;font-size:12px;min-height:16px; }
      .ok { color:#15803d; } .err { color:#b91c1c; } .muted { color:#6b7280; }
      .url { margin-top:6px;font-size:11px;color:#9ca3af;word-break:break-all; }
      .hidden { display:none; }
    </style>
    <button class="bubble" title="Add this job to Tailor Studio">✦</button>
    <div class="card hidden">
      <div class="hd">✦ Tailor Studio <span class="x" title="Collapse">×</span></div>
      <div class="bd">
        <label>Profile</label>
        <select class="prof"><option>Loading…</option></select>
        <button class="add" disabled>Add this job</button>
        <div class="status muted">Reviewing this page…</div>
        <div class="url"></div>
      </div>
    </div>`;
  (document.body || document.documentElement).appendChild(host);

  const $ = (s) => root.querySelector(s);
  const bubble = $('.bubble'), card = $('.card'), sel = $('.prof');
  const addBtn = $('.add'), status = $('.status'), urlEl = $('.url');

  const setStatus = (text, cls) => { status.textContent = text; status.className = 'status ' + (cls || 'muted'); };
  const show = (expanded) => { card.classList.toggle('hidden', !expanded); bubble.classList.toggle('hidden', expanded); };

  bubble.addEventListener('click', () => { show(true); urlEl.textContent = location.href; });
  $('.x').addEventListener('click', () => show(false));

  async function loadProfiles() {
    const r = await send({ type: 'list_profiles' });
    if (r.error || !r.profiles) {
      sel.innerHTML = '<option>—</option>';
      setStatus('Log in to Tailor Studio first, then reopen.', 'err');
      return;
    }
    if (!r.profiles.length) {
      sel.innerHTML = '<option>—</option>';
      setStatus('No profiles yet. Create one in the web app.', 'err');
      return;
    }
    const { addProfileId } = await chrome.storage.local.get('addProfileId');
    sel.innerHTML = r.profiles
      .map((p) => `<option value="${p.id}">${p.name}</option>`).join('');
    if (addProfileId && r.profiles.some((p) => p.id === addProfileId)) sel.value = String(addProfileId);
    addBtn.disabled = false;
    setStatus('Review the JD, then add.', 'muted');
  }

  sel.addEventListener('change', () => {
    const id = Number(sel.value);
    if (id) chrome.storage.local.set({ addProfileId: id });
  });

  addBtn.addEventListener('click', async () => {
    const pid = Number(sel.value);
    if (!pid) return;
    addBtn.disabled = true;
    setStatus('Adding…', 'muted');
    const r = await send({ type: 'queue_url', url: location.href, profileId: pid });
    addBtn.disabled = false;
    if (r.error) { setStatus(r.error.slice(0, 120), 'err'); return; }
    const res = (r.results && r.results[0]) || {};
    if (res.error) setStatus(res.error.slice(0, 120), 'err');
    else if (res.added > 0) setStatus('Added ✓ — tailoring started.', 'ok');
    else if (res.skipped_done > 0) setStatus('Already tailored for this profile.', 'muted');
    else if (res.skipped_existing > 0) setStatus('Already in the queue.', 'muted');
    else if (res.skipped_dupe > 0) setStatus('Already added.', 'muted');
    else if (res.skipped_linkedin > 0) setStatus("Can't add a LinkedIn list page — open the job itself.", 'err');
    else setStatus('Nothing added.', 'muted');
  });

  loadProfiles();
})();
