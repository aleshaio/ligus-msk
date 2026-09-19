// Inert without a configured counter. No remote tag before explicit consent.
(() => {
  const id = Number(document.querySelector('meta[name="metrica-id"]')?.content || 0);
  const key = 'ligus.analytics-consent.v1';
  const lifetime = 180 * 24 * 60 * 60 * 1000;
  const goals = new Set(['request_open', 'phone_click', 'email_click', 'form_start',
    'file_attached', 'form_submit_started', 'form_submit_success', 'form_submit_error']);
  let choice = null;
  let active = false;
  let tag;
  let loaded = false;
  let expiryTimer;
  const base = document.querySelector('meta[name="site-base"]')?.content || '';
  const banner = document.querySelector('.cookie-banner');
  const readChoice = () => {
    try {
      const value = JSON.parse(localStorage.getItem(key));
      return value?.version === 1 && ['granted', 'denied'].includes(value.state)
        && value.expires > Date.now() ? value : null;
    } catch { return null; }
  };
  const permitted = () => id > 0 && choice?.state === 'granted' && choice.expires > Date.now();
  const safeURL = () => {
    const clean = new URL(location.pathname, location.origin);
    const query = new URLSearchParams(location.search);
    // Only campaign tags, never form data or arbitrary query parameters.
    ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'yclid'].forEach(name => {
      const value = query.get(name);
      if (value && value.length <= 200 && /^[\p{L}\p{N} _.,{}|:+-]+$/u.test(value)) clean.searchParams.set(name, value);
    });
    return clean.href;
  };
  const stop = () => {
    clearTimeout(expiryTimer);
    if (active) window.ym?.(id, 'destruct');
    active = false;
  };
  const start = () => {
    if (!permitted() || active) return;
    window.ym = window.ym || function () { (window.ym.a = window.ym.a || []).push(arguments); };
    window.ym.l = window.ym.l || Date.now();
    if (!tag) {
      tag = document.createElement('script');
      tag.src = 'https://mc.yandex.ru/metrika/tag.js';
      tag.async = true;
      tag.referrerPolicy = 'origin';
      tag.onload = () => { loaded = true; start(); };
      tag.onerror = () => { tag.remove(); tag = null; };
      document.head.append(tag);
    }
    // If consent is withdrawn while the script loads, don't initialize it later.
    if (!loaded) return;
    active = true;
    window.ym(id, 'init', {defer: true, webvisor: false, clickmap: false,
      trackLinks: false, accurateTrackBounce: true, trackHash: false});
    let referer = '';
    try { const u = new URL(document.referrer); referer = u.origin + u.pathname; } catch {}
    window.ym(id, 'hit', safeURL(), {title: document.title, referer});
    // setTimeout is capped to avoid overflow for a 180-day choice.
    const checkExpiry = () => {
      if (!permitted()) { stop(); render(); return; }
      expiryTimer = setTimeout(checkExpiry, Math.min(60 * 60 * 1000, choice.expires - Date.now()));
    };
    checkExpiry();
  };
  const render = () => {
    if (banner) banner.hidden = !id || Boolean(choice && choice.expires > Date.now());
    const status = document.querySelector('.cookie-choice-status');
    if (status) status.textContent = permitted() ? 'Аналитика разрешена.' : 'Аналитика отключена.';
  };
  const select = state => {
    choice = {version: 1, state, expires: Date.now() + lifetime};
    try { localStorage.setItem(key, JSON.stringify(choice)); } catch {}
    if (permitted()) start(); else stop();
    render();
    document.querySelector('#cookie-dialog')?.close();
  };
  const track = (name, details = {}) => new Promise(resolve => {
    if (!permitted() || !active || !goals.has(name)) { resolve(); return; }
    // Deliberately exclude name, phone, email, comment, file names and request IDs.
    const data = {page: location.pathname};
    if (['selection', 'quote'].includes(details.intent)) data.intent = details.intent;
    if (['home', 'request'].includes(details.form)) data.form = details.form;
    let timer = setTimeout(resolve, 600);
    try { window.ym(id, 'reachGoal', name, data, () => { clearTimeout(timer); resolve(); }); }
    catch { clearTimeout(timer); resolve(); }
  });
  window.ligusAnalytics = Object.freeze({track});
  document.querySelectorAll('[data-analytics-consent]').forEach(button => {
    button.addEventListener('click', () => select(button.dataset.analyticsConsent));
  });
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link) return;
    const url = new URL(link.href, location.origin);
    if (url.protocol === 'tel:') track('phone_click');
    else if (url.protocol === 'mailto:') track('email_click');
    else if (url.origin === location.origin && url.pathname === `${base}/request/`)
      track('request_open', {intent: url.searchParams.get('intent')});
  });
  window.addEventListener('storage', event => {
    if (event.key !== key && event.key !== null) return;
    choice = readChoice();
    if (permitted()) start(); else stop();
    render();
  });
  window.addEventListener('pageshow', event => {
    if (!event.persisted) return;
    choice = readChoice();
    if (permitted()) start(); else stop();
    render();
  });
  choice = readChoice();
  render();
  start();
})();
