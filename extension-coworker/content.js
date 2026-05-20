// Tailor Studio content script.
//
// Two responsibilities on every ATS page load:
//   1. Rescue Mode — if the current URL is stuck in needs_manual_jd,
//      send the rendered DOM so the server can re-extract the JD.
//   2. Resume Ready — if a tailored resume exists for this URL under the
//      user's main profile, silently auto-download it AND inject a small
//      corner widget showing exactly which file is queued for upload.

(function () {
  // Avoid double-running across SPA route changes (Lever/Workday do
  // history.pushState). We re-arm on URL change instead.
  let lastUrl = null;

  function send(msg) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(msg, (resp) => {
          if (chrome.runtime.lastError) {
            // Service worker may have been torn down; treat as no-op.
            resolve(null);
            return;
          }
          resolve(resp);
        });
      } catch {
        resolve(null);
      }
    });
  }

  function showToast(text, ok = true) {
    // Tiny non-intrusive corner toast. Auto-dismisses.
    try {
      const el = document.createElement('div');
      el.textContent = text;
      el.style.cssText = [
        'position:fixed', 'right:14px', 'bottom:14px', 'z-index:2147483647',
        'padding:8px 12px', 'border-radius:6px', 'font:13px/1.4 -apple-system,system-ui,sans-serif',
        'box-shadow:0 4px 16px rgba(0,0,0,.18)',
        ok ? 'background:#15803d' : 'background:#b91c1c', 'color:#fff',
        'pointer-events:none',
      ].join(';');
      document.documentElement.appendChild(el);
      setTimeout(() => { try { el.remove(); } catch {} }, 4500);
    } catch {}
  }

  async function maybeRescue() {
    const url = location.href;
    if (url === lastUrl) return;
    lastUrl = url;

    const check = await send({ type: 'rescue_check', url });
    if (!check || !check.stuck) return;

    // SPA pages may not have rendered the JD yet. Wait up to 7s for the body
    // to settle. We bail earlier if the document already has a lot of text.
    // ADP / workforcenow / Workday often take 3-5s of JS to populate the JD.
    await waitForJdText(7000);

    const html = (document.documentElement && document.documentElement.outerHTML) || '';
    // Cap on the client side too to keep request bodies sane.
    const trimmed = html.length > 1_500_000 ? html.slice(0, 1_500_000) : html;

    const resp = await send({ type: 'rescue_send', url, html: trimmed });
    if (resp && resp.rescued > 0) {
      showToast(`Tailor Studio: rescued "${resp.title || 'job'}"`, true);
    } else if (resp && resp.error) {
      // Stay quiet on failure unless useful — most failures are just "DOM
      // doesn't contain a JD yet". Log to extension console for debugging.
      console.debug('[tailor-studio] rescue failed:', resp.error);
    }
  }

  function waitForJdText(maxMs) {
    return new Promise((resolve) => {
      const start = Date.now();
      const tick = () => {
        const txt = document.body ? document.body.innerText || '' : '';
        if (txt.length > 1500 || Date.now() - start > maxMs) return resolve();
        setTimeout(tick, 200);
      };
      tick();
    });
  }

  // ── Resume Ready widget ─────────────────────────────────────────────────
  let widgetEl = null;
  let lastResumeUrl = null;
  // What we last auto-downloaded for the current page; used by the upload
  // observer to verify the co-worker uploaded the matching file.
  let expectedResume = null;  // { filename, size, sha256 }
  let lastWidgetState = null;

  function ensureWidget() {
    if (widgetEl && document.body.contains(widgetEl)) return widgetEl;
    const w = document.createElement('div');
    w.id = 'tailor-studio-widget';
    w.style.cssText = [
      'position:fixed', 'right:14px', 'bottom:14px', 'z-index:2147483647',
      'min-width:280px', 'max-width:340px',
      'padding:10px 12px 11px', 'border-radius:8px',
      'font:13px/1.4 -apple-system,system-ui,sans-serif',
      'box-shadow:0 6px 20px rgba(0,0,0,.16)',
      'background:#fff', 'color:#1f2937', 'border:1px solid #e5e7eb',
    ].join(';');
    document.documentElement.appendChild(w);
    widgetEl = w;
    return w;
  }

  function dismissWidget() {
    if (widgetEl) { try { widgetEl.remove(); } catch {} widgetEl = null; }
  }

  function renderWidget({ tone, header, filename, body, actions }) {
    const w = ensureWidget();
    const colors = {
      green:  ['#ecfdf5', '#bbf7d0', '#166534'],
      amber:  ['#fffbeb', '#fde68a', '#92400e'],
      gray:   ['#f9fafb', '#e5e7eb', '#374151'],
      red:    ['#fef2f2', '#fecaca', '#991b1b'],
    }[tone] || ['#fff', '#e5e7eb', '#1f2937'];
    w.style.background = colors[0];
    w.style.borderColor = colors[1];
    w.style.color = colors[2];
    w.innerHTML = '';

    const head = document.createElement('div');
    head.style.cssText = 'display:flex;align-items:center;justify-content:space-between;font-weight:600;font-size:12px;';
    const headSpan = document.createElement('span');
    headSpan.textContent = header;
    const x = document.createElement('button');
    x.textContent = '×'; x.title = 'Dismiss';
    x.style.cssText = 'background:none;border:0;cursor:pointer;font-size:16px;line-height:1;padding:0 4px;color:inherit;opacity:.55;';
    x.addEventListener('click', dismissWidget);
    head.appendChild(headSpan); head.appendChild(x);
    w.appendChild(head);

    if (filename) {
      const f = document.createElement('div');
      f.style.cssText = 'margin-top:4px;font-size:11px;font-family:ui-monospace,monospace;color:inherit;opacity:.85;word-break:break-all;';
      f.textContent = filename;
      w.appendChild(f);
    }
    if (body) {
      const b = document.createElement('div');
      b.style.cssText = 'margin-top:4px;font-size:12px;color:inherit;opacity:.85;';
      b.textContent = body;
      w.appendChild(b);
    }
    if (actions && actions.length) {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;gap:6px;margin-top:8px;';
      for (const a of actions) {
        const btn = document.createElement('button');
        btn.textContent = a.label;
        btn.style.cssText = 'background:#fff;border:1px solid ' + colors[1] + ';color:' + colors[2] + ';padding:4px 10px;border-radius:5px;cursor:pointer;font-size:12px;font-weight:600;';
        btn.addEventListener('click', a.onClick);
        row.appendChild(btn);
      }
      w.appendChild(row);
    }
  }

  async function send(msg) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(msg, (resp) => {
          if (chrome.runtime.lastError) return resolve(null);
          resolve(resp);
        });
      } catch { resolve(null); }
    });
  }

  async function maybeResumeReady() {
    // The widget renders into document.documentElement, and the script
    // runs in every iframe (all_frames:true is needed for ADP rescue).
    // We only want one widget per page — only the top frame paints it.
    if (window.top !== window.self) return;
    const url = location.href;
    if (url === lastResumeUrl) return;
    lastResumeUrl = url;

    const info = await send({ type: 'resume_for', url });
    if (!info) return;
    if (info.__error) {
      // 401 / auth error or server down — stay quiet.
      return;
    }

    if (!info.matched) {
      // No tailored resume tracked for this URL. Offer base if available.
      if (info.base && info.base.has_base) {
        renderWidget({
          tone: 'gray',
          header: 'No tailored resume',
          filename: info.base.base_filename,
          body: `Profile: ${info.base.profile_name} · base resume only`,
          actions: [{
            label: '↓ Base resume',
            onClick: async () => {
              await send({ type: 'download_resume', path: info.base.base_url, filename: info.base.base_filename });
            },
          }],
        });
      }
      return;
    }

    // We have a JobUrl match. Render by pipeline status.
    if (info.status === 'done' && info.has_tailored) {
      const t = info.tailored;
      // Remember the expected file's fingerprint so the upload observer
      // can verify the co-worker uploads this one and not something else.
      expectedResume = { filename: t.filename, size: t.size, sha256: t.sha256 };
      // Silent auto-download.
      const dl = await send({ type: 'download_resume', path: t.docx_url, filename: t.filename });
      const ok = dl && dl.ok;
      lastWidgetState = 'ready';
      renderWidget({
        tone: 'green',
        header: `Tailored ✓  ${info.company || ''}`.trim(),
        filename: t.filename,
        body: ok ? 'Auto-downloaded — watching upload form…' : 'Click to download',
        actions: [
          { label: '↓ Re-download .docx',
            onClick: async () => { await send({ type: 'download_resume', path: t.docx_url, filename: t.filename }); } },
          { label: '↓ pdf',
            onClick: async () => { await send({ type: 'download_resume', path: t.pdf_url, filename: t.filename.replace(/\.docx$/i, '.pdf') }); } },
        ],
      });
      return;
    }

    if (info.status === 'error') {
      renderWidget({
        tone: 'red',
        header: 'Tailoring failed',
        filename: '',
        body: `Profile: ${info.profile_name} · open studio to retry`,
        actions: info.base && info.base.has_base ? [{
          label: '↓ Base resume',
          onClick: async () => {
            await send({ type: 'download_resume', path: info.base.base_url, filename: info.base.base_filename });
          },
        }] : [],
      });
      return;
    }

    if (info.status === 'needs_manual_jd') {
      renderWidget({
        tone: 'amber',
        header: 'JD needs rescue',
        filename: '',
        body: 'Stay on this page — Rescue Mode will fix it shortly.',
      });
      return;
    }

    // pending / fetching / analyzing / tailoring
    renderWidget({
      tone: 'amber',
      header: 'Tailoring in progress…',
      filename: '',
      body: `Profile: ${info.profile_name} · status: ${info.status}`,
      actions: info.base && info.base.has_base ? [{
        label: '↓ Base resume (fallback)',
        onClick: async () => {
          await send({ type: 'download_resume', path: info.base.base_url, filename: info.base.base_filename });
        },
      }] : [],
    });
  }

  // ── Upload observer ─────────────────────────────────────────────────────
  // Watches every <input type="file"> on the page. When one fires `change`,
  // hashes the picked file and posts an observation to the server so the
  // user can see in studio whether the right resume was uploaded.

  const watchedInputs = new WeakSet();

  async function sha256File(file) {
    try {
      const buf = await file.arrayBuffer();
      const digest = await crypto.subtle.digest('SHA-256', buf);
      return Array.from(new Uint8Array(digest))
        .map((b) => b.toString(16).padStart(2, '0')).join('');
    } catch (e) {
      console.debug('[tailor-studio] hash failed', e);
      return null;
    }
  }

  async function onFilePicked(input) {
    if (!input.files || !input.files[0]) return;
    const file = input.files[0];
    // Tiny safety guard — refuse to hash >50MB files (resumes shouldn't be).
    if (file.size > 50 * 1024 * 1024) return;
    const sha = await sha256File(file);
    if (!sha) return;

    // Local verdict (instant feedback) — server confirms with profile_base
    // comparison in its response.
    let verdict = 'other';
    if (expectedResume && expectedResume.sha256 === sha) verdict = 'tailored';

    // Update widget immediately based on local verdict; server response
    // refines to 'base' when applicable.
    showUploadStatus(verdict, file);

    const resp = await send({
      type: 'upload_observed',
      url: location.href,
      filename: file.name,
      size: file.size,
      sha256: sha,
    });
    if (resp && resp.match && resp.match !== verdict) {
      showUploadStatus(resp.match, file);
    }
  }

  function showUploadStatus(verdict, file) {
    if (verdict === 'tailored') {
      renderWidget({
        tone: 'green',
        header: '✓ Verified — tailored resume uploaded',
        filename: file.name,
        body: `${(file.size/1024).toFixed(1)} KB · hash match`,
      });
    } else if (verdict === 'base') {
      renderWidget({
        tone: 'amber',
        header: '⚠ Base resume uploaded (not tailored)',
        filename: file.name,
        body: `${(file.size/1024).toFixed(1)} KB · matches base resume`,
      });
    } else {
      renderWidget({
        tone: 'red',
        header: '⚠ Different file uploaded',
        filename: file.name,
        body: `${(file.size/1024).toFixed(1)} KB · not the tailored or base resume`,
      });
    }
  }

  function hookFileInputs(root) {
    const inputs = (root || document).querySelectorAll('input[type="file"]');
    inputs.forEach((input) => {
      if (watchedInputs.has(input)) return;
      watchedInputs.add(input);
      input.addEventListener('change', () => onFilePicked(input));
    });
  }

  function startUploadObserver() {
    // Only meaningful in the top frame (where the widget lives).
    if (window.top !== window.self) return;
    hookFileInputs(document);
    const mo = new MutationObserver((muts) => {
      for (const m of muts) {
        m.addedNodes.forEach((n) => {
          if (!(n instanceof Element)) return;
          if (n.matches && n.matches('input[type="file"]')) {
            hookFileInputs(n.parentNode || n);
          } else {
            hookFileInputs(n);
          }
        });
      }
    });
    mo.observe(document.documentElement, { childList: true, subtree: true });
  }

  // ── Essay-question detection (Tier 3 / "Draft answers") ───────────────
  // Walks the form for textareas + custom-card text inputs that the regex
  // form-filler can't handle, pulls the surrounding question text, and
  // returns a {element, id, text, kind, options} list the Draft flow sends
  // to the backend.

  function findQuestionText(el) {
    // (1) label[for=id]
    if (el.id) {
      const lab = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lab && lab.textContent && lab.textContent.trim()) return lab.textContent.trim();
    }
    // (2) wrapping <label>
    let p = el.parentElement;
    for (let i = 0; i < 4 && p; i++, p = p.parentElement) {
      if (p.tagName === 'LABEL' && p.textContent) return p.textContent.trim();
    }
    // (3) nearest ancestor with a class hinting "question" / "field"
    let anc = el.parentElement;
    for (let i = 0; i < 6 && anc; i++, anc = anc.parentElement) {
      const cls = (anc.className || '').toString().toLowerCase();
      if (cls.includes('question') || cls.includes('application-question') ||
          cls.includes('field') || cls.includes('form-group')) {
        // Pull the first .text / label / div / span / h{1-6} inside
        const labelish = anc.querySelector(
          ':scope > label, :scope > .question-text, :scope > .application-label, ' +
          ':scope > h1, :scope > h2, :scope > h3, :scope > h4, :scope > div'
        );
        if (labelish && labelish.textContent && labelish.textContent.trim()) {
          // Strip out the input's value if it leaked in
          let t = labelish.textContent.trim();
          if (el.value && t.includes(el.value)) t = t.split(el.value)[0].trim();
          if (t.length > 5) return t;
        }
        // Else: take the first text node of this ancestor (often the prompt)
        const txt = (anc.textContent || '').trim().split('\n')[0].slice(0, 400);
        if (txt && txt.length > 5) return txt;
      }
    }
    // (4) Previous sibling text
    let sib = el.previousElementSibling;
    for (let i = 0; i < 3 && sib; i++, sib = sib.previousElementSibling) {
      const t = (sib.textContent || '').trim();
      if (t && t.length > 5 && t.length < 500) return t;
    }
    return el.placeholder || el.getAttribute('aria-label') || '(no question text found)';
  }

  function isStandardField(el) {
    // Reuse the formfill library's pattern engine to decide whether this
    // element is a "standard" field. If yes, Tier 1+2 handles it — Draft
    // should skip.
    const fn = window.__tailorStudioMatchStandardField;
    if (typeof fn !== 'function') return false;
    return !!fn(el);
  }

  function isFieldRequired(el) {
    if (el.required) return true;
    if (el.getAttribute('aria-required') === 'true') return true;
    let p = el.parentElement;
    for (let i = 0; i < 5 && p; i++, p = p.parentElement) {
      const cls = (p.className || '').toString().toLowerCase();
      if (cls.includes('required')) return true;
    }
    return false;
  }


  function detectEssayQuestions() {
    const out = [];
    const seen = new WeakSet();

    // Textareas — essay-style, only required ones.
    document.querySelectorAll('textarea').forEach((el) => {
      if (el.disabled || el.readOnly) return;
      if (seen.has(el)) return;
      if (!isFieldRequired(el)) return;
      seen.add(el);
      const text = findQuestionText(el);
      out.push({ element: el, kind: 'textarea', text });
    });

    // Text inputs that are NOT standard fields → custom screener questions.
    document.querySelectorAll('input[type="text"], input:not([type])').forEach((el) => {
      if (el.disabled || el.readOnly) return;
      if (seen.has(el)) return;
      if (isStandardField(el)) return;
      if (!isFieldRequired(el)) return;
      seen.add(el);
      const text = findQuestionText(el);
      if (!text || text.length < 8) return;
      out.push({ element: el, kind: 'text', text });
    });

    // Radio groups — collect options once per group.
    const radios = Array.from(document.querySelectorAll('input[type="radio"]'));
    const groups = new Map();
    radios.forEach((r) => {
      const k = r.name || r.id;
      if (!k) return;
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(r);
    });
    groups.forEach((group, name) => {
      if (group.length < 2) return;
      if (!group.some((r) => isFieldRequired(r))) return;
      // If formfill already handled this group (yes/no), skip.
      const ytext = (() => {
        for (let p = group[0].parentElement, i = 0; i < 6 && p; i++, p = p.parentElement) {
          if (p.tagName === 'FIELDSET' || (p.className || '').toString().match(/question|field/i)) {
            return (p.textContent || '').slice(0, 400);
          }
        }
        return '';
      })();
      // Yes/no eligibility groups → covered by Tier 1+2.
      if (/yes[\s,]*\/?[\s,]*no|\bauthorized\b|\bsponsorship\b|\brelocate\b|\bremote\b/i.test(ytext)) return;

      const options = group.map((r) => {
        // label text
        if (r.id) {
          const lab = document.querySelector(`label[for="${CSS.escape(r.id)}"]`);
          if (lab && lab.textContent) return lab.textContent.trim();
        }
        let pp = r.parentElement;
        for (let i = 0; i < 3 && pp; i++, pp = pp.parentElement) {
          if (pp.tagName === 'LABEL') return (pp.textContent || '').trim();
        }
        return r.value || '';
      }).filter(Boolean);
      const text = findQuestionText(group[0]);
      if (text && options.length >= 2) {
        out.push({ element: group, kind: 'radio', text, options });
      }
    });

    return out;
  }

  function applyDraft(questions, drafts) {
    const byId = new Map(drafts.map((d) => [d.id, d]));
    let filled = 0;
    questions.forEach((q, i) => {
      const draft = byId.get(String(i));
      if (!draft || !draft.answer) return;
      if (q.kind === 'textarea' || q.kind === 'text') {
        const el = q.element;
        const proto = Object.getPrototypeOf(el);
        const desc = Object.getOwnPropertyDescriptor(proto, 'value');
        if (desc && desc.set) desc.set.call(el, draft.answer);
        else el.value = draft.answer;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.style.boxShadow = '0 0 0 3px #c4b5fd';
        setTimeout(() => { el.style.boxShadow = ''; }, 3000);
        filled++;
      } else if (q.kind === 'radio') {
        const target = draft.answer.trim().toLowerCase();
        for (const r of q.element) {
          const lab = (() => {
            if (r.id) {
              const l = document.querySelector(`label[for="${CSS.escape(r.id)}"]`);
              if (l) return (l.textContent || '').trim().toLowerCase();
            }
            return (r.value || '').toLowerCase();
          })();
          if (lab === target || lab.includes(target) || target.includes(lab)) {
            if (!r.checked) r.click();
            r.style.boxShadow = '0 0 0 3px #c4b5fd';
            setTimeout(() => { r.style.boxShadow = ''; }, 3000);
            filled++;
            break;
          }
        }
      }
    });
    return filled;
  }

  function injectDraftButton() {
    if (window.top !== window.self) return;
    if (document.getElementById('tailor-studio-draft-btn')) return;
    if (!document.body) return;

    const btn = document.createElement('button');
    btn.id = 'tailor-studio-draft-btn';
    btn.type = 'button';
    btn.textContent = '✨ Draft';
    btn.title = 'Tailor Studio (Co-worker): use the candidate profile + JD to draft answers for essay questions';
    btn.style.cssText = [
      'position:fixed', 'left:14px', 'bottom:14px', 'z-index:2147483647',
      'padding:9px 14px', 'border:0', 'border-radius:999px',
      'background:linear-gradient(135deg,#a78bfa,#7c3aed)',
      'color:#fff', 'font:600 13px/1 -apple-system,system-ui,sans-serif',
      'cursor:pointer', 'box-shadow:0 4px 14px rgba(124,58,237,.35)',
      'transition:transform .12s ease, box-shadow .12s ease',
    ].join(';');
    btn.addEventListener('mouseenter', () => {
      btn.style.transform = 'translateY(-1px)';
      btn.style.boxShadow  = '0 6px 18px rgba(124,58,237,.45)';
    });
    btn.addEventListener('mouseleave', () => {
      btn.style.transform = '';
      btn.style.boxShadow = '0 4px 14px rgba(124,58,237,.35)';
    });

    btn.addEventListener('click', async () => {
      btn.disabled = true;
      const orig = btn.textContent;
      try {
        const questions = detectEssayQuestions();
        console.log('[tailor-studio] draft: detected', questions.length, 'questions:',
          questions.map((q) => ({ kind: q.kind, text: q.text.slice(0, 80) })));
        if (!questions.length) {
          showToast('No essay questions detected on this page.', false);
          return;
        }
        btn.textContent = `Drafting ${questions.length}…`;
        const payload = questions.map((q, i) => ({
          id: String(i),
          text: q.text,
          kind: q.kind,
          options: q.options || null,
        }));
        console.log('[tailor-studio] draft: POSTing to background…');
        const resp = await send({ type: 'draft_answers', url: location.href, questions: payload });
        console.log('[tailor-studio] draft: response =', resp);
        if (!resp) throw new Error('Background returned no response (service worker may be sleeping — retry once).');
        if (resp.__error) throw new Error(resp.__error);
        if (resp.error) throw new Error(resp.error);
        if (!resp.drafts) throw new Error('Server returned no drafts');
        const filled = applyDraft(questions, resp.drafts);
        console.log('[tailor-studio] draft: filled', filled, 'of', questions.length);
        showToast(
          `Drafted ${filled} of ${questions.length} answer${questions.length === 1 ? '' : 's'} — review before submit.`,
          filled > 0,
        );
      } catch (e) {
        console.error('[tailor-studio] draft failed:', e);
        showToast((e && e.message) || 'draft failed', false);
      } finally {
        btn.disabled = false;
        btn.textContent = orig;
      }
    });
    document.body.appendChild(btn);
  }

  // Initial run + re-arm on SPA navigation.
  const watch = () => {
    maybeRescue();
    maybeResumeReady();
    startUploadObserver();
    injectDraftButton();
    // Patch history methods so we notice client-side navigation.
    const onNav = () => {
      setTimeout(() => {
        maybeRescue(); maybeResumeReady();
        injectDraftButton();
      }, 250);
    };
    const origPush = history.pushState;
    const origRep = history.replaceState;
    history.pushState = function () { origPush.apply(this, arguments); onNav(); };
    history.replaceState = function () { origRep.apply(this, arguments); onNav(); };
    window.addEventListener('popstate', onNav);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', watch, { once: true });
  } else {
    watch();
  }
})();
