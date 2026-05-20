// Form-fill logic shared between the extension popup and content scripts.
// Loaded as a content script (see manifest.json) so it can be invoked via
// chrome.scripting on demand, or run inline alongside the rescue content.
//
// Strategy:
//   1. Walk every <input>, <textarea>, and <select> on the page.
//   2. Score each field against a known pattern library by matching the
//      field's `name`, `id`, `placeholder`, `aria-label`, and nearest <label>.
//   3. Highest-scoring pattern that exceeds the threshold gets filled.
//   4. Yes/no radio + checkbox groups are detected by question text matching.
//   5. After filling, dispatch `input` and `change` events so React /
//      Greenhouse-style frontends notice.

(function () {
  if (window.__tailorStudioFormFillInstalled) return;
  window.__tailorStudioFormFillInstalled = true;

  // ── Field patterns ─────────────────────────────────────────────────────
  // Each entry: [answer_path, [/regex/i, …]]. Order matters — first match wins.
  const FIELD_PATTERNS = [
    ['personal.first_name',     [/\bfirst[\s_-]*name\b/i, /\bgiven[\s_-]*name\b/i, /\bfname\b/i, /^first$/i]],
    ['personal.last_name',      [/\blast[\s_-]*name\b/i, /\bfamily[\s_-]*name\b/i, /\bsurname\b/i, /\blname\b/i, /^last$/i]],
    // Full name / generic "name" — only matched after first/last failed.
    ['personal.full_name',      [/\bfull[\s_-]*name\b/i, /\byour[\s_-]*name\b/i, /\bname\b/i]],
    ['personal.email',          [/\bemail\b/i, /\be-mail\b/i]],
    ['personal.phone',          [/\bphone\b/i, /\btelephone\b/i, /\bmobile\b/i, /\bcell\b/i]],
    ['personal.linkedin_url',   [/\blinkedin\b/i]],
    ['personal.github_url',     [/\bgithub\b/i, /\bgit[\s_-]*hub\b/i]],
    ['personal.portfolio_url',  [/\bportfolio\b/i, /\bpersonal[\s_-]*(site|website|page)\b/i, /\bwebsite\b/i]],
    // Lever's `name="location"` is a free-form "City, ST" string — fall back
    // to the synthetic full_location (city + state) the popup builds below.
    ['personal.full_location',  [/\blocation\b/i, /\bbased[\s_-]*in\b/i, /\bwhere[\s_-]*are[\s_-]*you[\s_-]*located\b/i]],
    ['personal.address_city',   [/\bcity\b/i]],
    ['personal.address_state',  [/\bstate\b/i, /\bregion\b/i, /\bprovince\b/i]],
    ['personal.address_country',[/\bcountry\b/i]],
    ['personal.address_zip',    [/\bzip\b/i, /\bpostal[\s_-]*code\b/i, /\bpost[\s_-]*code\b/i]],
    ['professional.current_company', [
      /\bcurrent[\s_-]*(company|employer)\b/i, /\bemployer\b/i, /\bcompany\b/i,
      /\borganization\b/i, /\borg\b/i,
    ]],
    ['professional.current_title',   [/\bcurrent[\s_-]*(title|role|position)\b/i, /\b(job[\s_-]*)?title\b/i]],
    ['professional.years_of_experience', [/\byears[\s_-]*(of[\s_-]*)?experience\b/i, /\byoe\b/i]],
    ['eligibility.salary_expectation',   [/\bsalary\b/i, /\bcompensation\b/i, /\bdesired[\s_-]*pay\b/i]],
    ['eligibility.preferred_start',      [/\bstart[\s_-]*(date|when)\b/i, /\bavailab(le|ility)\b/i, /\bnotice[\s_-]*period\b/i]],
    // EEO / demographics — selects with predefined options (gender/race/veteran).
    ['demographics.gender',              [/\bgender\b/i, /eeo\[gender\]/i]],
    ['demographics.race',                [/\b(race|ethnicity)\b/i, /eeo\[race\]/i]],
    ['demographics.veteran',             [/\bveteran\b/i, /\bmilitary[\s_-]*service\b/i, /eeo\[veteran\]/i]],
    ['demographics.disability',          [/\bdisability\b/i, /\bdisabled\b/i]],
  ];

  // Yes/no questions — match against the surrounding label text.
  const YESNO_PATTERNS = [
    ['eligibility.us_authorized',
      [/\bauthorized[\s_-]*to[\s_-]*work\b/i, /\bwork[\s_-]*authorization\b/i,
       /\beligible[\s_-]*to[\s_-]*work\b/i, /\blegally[\s_-]*authoriz/i]],
    ['eligibility.need_sponsorship',
      [/\b(require|need)[\s_-]*sponsorship\b/i, /\bvisa[\s_-]*sponsorship\b/i,
       /\bh.?1.?b\b/i, /\bsponsorship\b/i]],
    ['eligibility.willing_to_relocate',
      [/\b(willing|able)[\s_-]*to[\s_-]*relocate\b/i, /\brelocation\b/i]],
    ['eligibility.willing_remote',
      [/\bopen[\s_-]*to[\s_-]*remote\b/i, /\bremote[\s_-]*work\b/i,
       /\bwork[\s_-]*remotely\b/i]],
  ];

  function isRequired(el) {
    if (el.required) return true;
    if (el.getAttribute('aria-required') === 'true') return true;
    // Lever / Greenhouse / Ashby mark required questions with classes like
    // .application-question.required or an asterisk in the label.
    let p = el.parentElement;
    for (let i = 0; i < 5 && p; i++, p = p.parentElement) {
      const cls = (p.className || '').toString().toLowerCase();
      if (cls.includes('required')) return true;
    }
    return false;
  }


  function get(answers, path) {
    return path.split('.').reduce((o, k) => (o == null ? o : o[k]), answers);
  }

  function fieldText(input) {
    // Combine every signal that tells us what this field is about.
    const parts = [
      input.name, input.id, input.getAttribute('aria-label'),
      input.getAttribute('placeholder'), input.getAttribute('autocomplete'),
    ];
    // Nearest <label>
    if (input.id) {
      const lab = document.querySelector(`label[for="${CSS.escape(input.id)}"]`);
      if (lab) parts.push(lab.textContent || '');
    }
    // Wrapping <label>
    let p = input.parentElement;
    for (let i = 0; i < 4 && p; i++, p = p.parentElement) {
      if (p.tagName === 'LABEL') { parts.push(p.textContent || ''); break; }
    }
    return parts.filter(Boolean).join(' ').slice(0, 500);
  }

  function questionText(input) {
    // For radio/checkbox groups, the question is usually in a wrapping
    // fieldset legend or a sibling heading/label above the option group.
    let p = input.parentElement;
    for (let i = 0; i < 6 && p; i++, p = p.parentElement) {
      const legend = p.querySelector(':scope > legend, :scope > .label, :scope > label');
      if (legend && legend.textContent) return legend.textContent.slice(0, 500);
      if (p.tagName === 'FIELDSET') return (p.textContent || '').slice(0, 500);
    }
    // Fall back to the standard field-text signals.
    return fieldText(input);
  }

  function matchField(input, patterns) {
    const text = fieldText(input);
    for (const [path, rxs] of patterns) {
      for (const rx of rxs) if (rx.test(text)) return path;
    }
    return null;
  }

  function setNativeValue(el, value) {
    // React tracks the value via an internal descriptor — bypass it so the
    // onChange handler fires with our new value.
    const proto = Object.getPrototypeOf(el);
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    if (desc && desc.set) desc.set.call(el, value);
    else el.value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function fillText(input, value) {
    if (value == null || value === '') return false;
    setNativeValue(input, String(value));
    flashHighlight(input, '#a7f3d0');
    return true;
  }

  function fillSelect(select, value) {
    if (value == null || value === '') return false;
    const v = String(value).toLowerCase();
    let chosen = null;
    for (const opt of select.options) {
      const txt = (opt.text || '').toLowerCase();
      if (txt === v || opt.value.toLowerCase() === v) { chosen = opt; break; }
    }
    if (!chosen) {
      for (const opt of select.options) {
        const txt = (opt.text || '').toLowerCase();
        if (txt.includes(v) || v.includes(txt)) { chosen = opt; break; }
      }
    }
    if (!chosen) return false;
    select.value = chosen.value;
    select.dispatchEvent(new Event('change', { bubbles: true }));
    flashHighlight(select, '#a7f3d0');
    return true;
  }

  function fillCheckbox(input, checked) {
    if (checked == null) return false;
    if (input.checked !== !!checked) {
      input.click();
    }
    flashHighlight(input, '#a7f3d0');
    return true;
  }

  function fillYesNoRadio(group, yes) {
    // Group is an array of radio inputs sharing the same `name`.
    const target = yes ? /\byes\b|^y$|true|✓/i : /\bno\b|^n$|false|✕/i;
    for (const r of group) {
      const label = (() => {
        if (r.id) {
          const lab = document.querySelector(`label[for="${CSS.escape(r.id)}"]`);
          if (lab) return lab.textContent || '';
        }
        let p = r.parentElement;
        for (let i = 0; i < 3 && p; i++, p = p.parentElement) {
          if (p.tagName === 'LABEL') return p.textContent || '';
        }
        return r.value || '';
      })();
      if (target.test(label)) {
        if (!r.checked) r.click();
        flashHighlight(r, '#a7f3d0');
        return true;
      }
    }
    return false;
  }

  function flashHighlight(el, color) {
    const old = el.style.boxShadow;
    el.style.boxShadow = `0 0 0 3px ${color}`;
    setTimeout(() => { el.style.boxShadow = old; }, 1800);
  }

  // ── Main entry ─────────────────────────────────────────────────────────
  function fillForm(answers) {
    if (!answers) return { filled: 0, skipped: 0 };

    // Synthesize a few combined fields the patterns can use directly.
    const personal = answers.personal || {};
    if (personal.first_name || personal.last_name) {
      personal.full_name = [personal.first_name, personal.last_name].filter(Boolean).join(' ');
    }
    if (personal.address_city || personal.address_state || personal.address_country) {
      personal.full_location = [personal.address_city, personal.address_state, personal.address_country]
        .filter(Boolean).join(', ');
    }

    let filled = 0;
    const filledFields = new Set();

    // 1) Text inputs / textareas / selects — match against FIELD_PATTERNS.
    //    Per-user preference: only fill REQUIRED fields. Optional fields
    //    (LinkedIn URL on most ATSes, "Other URL", etc.) get skipped.
    document.querySelectorAll('input, textarea, select').forEach((el) => {
      if (el.disabled || el.readOnly) return;
      if (el.tagName === 'INPUT') {
        const t = (el.type || '').toLowerCase();
        if (['checkbox', 'radio', 'submit', 'button', 'file', 'hidden', 'image', 'reset'].includes(t)) return;
      }
      if (!isRequired(el)) return;
      const path = matchField(el, FIELD_PATTERNS);
      if (!path) return;
      const v = get(answers, path);
      if (v == null || v === '') return;
      let ok = false;
      if (el.tagName === 'SELECT') ok = fillSelect(el, v);
      else ok = fillText(el, v);
      if (ok) { filled++; filledFields.add(path); }
    });

    // 2) Yes/no radio groups by question text.
    const radios = Array.from(document.querySelectorAll('input[type="radio"]'));
    const groups = new Map();
    radios.forEach((r) => {
      const k = r.name || r.id;
      if (!k) return;
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(r);
    });
    groups.forEach((group) => {
      if (group.length < 2) return;
      // Skip optional radio groups (e.g., demographics they didn't mark required).
      if (!group.some((r) => isRequired(r))) return;
      const qtext = questionText(group[0]);
      for (const [path, rxs] of YESNO_PATTERNS) {
        if (!rxs.some((rx) => rx.test(qtext))) continue;
        const v = get(answers, path);
        if (v == null) return;
        if (fillYesNoRadio(group, !!v)) { filled++; filledFields.add(path); }
        return;
      }
    });

    // 3) Standalone yes/no checkboxes (rare on ATS but seen on Lever).
    document.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
      if (!isRequired(cb)) return;
      const qtext = questionText(cb);
      for (const [path, rxs] of YESNO_PATTERNS) {
        if (!rxs.some((rx) => rx.test(qtext))) continue;
        const v = get(answers, path);
        if (v == null) return;
        if (fillCheckbox(cb, !!v)) { filled++; filledFields.add(path); }
        return;
      }
    });

    return { filled, fields: [...filledFields] };
  }

  // Expose for the content script messaging layer.
  window.__tailorStudioFillForm = fillForm;
  // Question detector uses this to skip elements that Tier 1+2 handles.
  window.__tailorStudioMatchStandardField = (el) => matchField(el, FIELD_PATTERNS);
})();
