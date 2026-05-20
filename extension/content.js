// Tailor Studio Sourcing extension — content script.
//
// Single responsibility: Rescue Mode. If the current URL is stuck in
// needs_manual_jd, send the rendered DOM so the server can re-extract the JD.
//
// (The Resume Ready widget, file-upload audit, and form-fill have moved to
// the separate "Tailor Studio — Co-worker" extension since this side never
// applies to jobs.)

(function () {
  let lastUrl = null;

  function send(msg) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(msg, (resp) => {
          if (chrome.runtime.lastError) return resolve(null);
          resolve(resp);
        });
      } catch { resolve(null); }
    });
  }

  function showToast(text, ok = true) {
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

  async function maybeRescue() {
    const url = location.href;
    if (url === lastUrl) return;
    lastUrl = url;

    const check = await send({ type: 'rescue_check', url });
    if (!check || !check.stuck) return;

    await waitForJdText(7000);

    const html = (document.documentElement && document.documentElement.outerHTML) || '';
    const trimmed = html.length > 1_500_000 ? html.slice(0, 1_500_000) : html;

    const resp = await send({ type: 'rescue_send', url, html: trimmed });
    if (resp && resp.rescued > 0) {
      showToast(`Tailor Studio: rescued "${resp.title || 'job'}"`, true);
    } else if (resp && resp.error) {
      console.debug('[tailor-studio] rescue failed:', resp.error);
    }
  }

  const watch = () => {
    maybeRescue();
    const onNav = () => setTimeout(maybeRescue, 250);
    const origPush = history.pushState;
    const origRep  = history.replaceState;
    history.pushState    = function () { origPush.apply(this, arguments); onNav(); };
    history.replaceState = function () { origRep.apply(this, arguments);  onNav(); };
    window.addEventListener('popstate', onNav);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', watch, { once: true });
  } else {
    watch();
  }
})();
