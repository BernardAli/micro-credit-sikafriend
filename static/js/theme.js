/* Run in the head so the saved/system theme is set before the first paint. */
(function () {
  'use strict';
  const root = document.documentElement;
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  const valid = value => value === 'light' || value === 'dark';
  let preference = null;
  try {
    const saved = localStorage.getItem('sf-theme');
    if (valid(saved)) preference = saved;
  } catch (_) { /* Browser privacy settings may disable storage. */ }

  const icons = {
    light: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M20.7 13.1A8.5 8.5 0 0 1 10.9 3.3 8.5 8.5 0 1 0 20.7 13.1Z"/></svg>',
    dark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>'
  };
  function updateControls(theme) {
    document.querySelectorAll('[data-theme-toggle]').forEach(button => {
      const label = theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme';
      button.innerHTML = icons[theme];
      button.setAttribute('aria-label', label);
      button.setAttribute('title', label);
      button.setAttribute('aria-pressed', String(theme === 'dark'));
    });
  }
  function apply(theme) {
    const changed = root.dataset.theme !== theme;
    root.dataset.theme = theme;
    updateControls(theme);
    if (changed) window.dispatchEvent(new CustomEvent('sf:themechange', { detail: { theme } }));
  }
  apply(preference || (system.matches ? 'dark' : 'light'));
  document.addEventListener('DOMContentLoaded', () => {
    updateControls(root.dataset.theme);
    document.querySelectorAll('[data-theme-toggle]').forEach(button => {
      button.addEventListener('click', () => {
        preference = root.dataset.theme === 'dark' ? 'light' : 'dark';
        try { localStorage.setItem('sf-theme', preference); } catch (_) { /* Keep the session choice. */ }
        apply(preference);
      });
    });
  });
  system.addEventListener('change', event => {
    if (!preference) apply(event.matches ? 'dark' : 'light');
  });
  window.addEventListener('storage', event => {
    if (event.key !== 'sf-theme' && event.key !== null) return;
    preference = valid(event.newValue) ? event.newValue : null;
    apply(preference || (system.matches ? 'dark' : 'light'));
  });
})();
