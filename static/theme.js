// Apply before styles load to avoid flashing the wrong theme on navigation.
(() => {
  const storageKey = 'compute-dashboard-theme';
  const media = window.matchMedia?.('(prefers-color-scheme: dark)');
  let preference = null;
  try {
    const saved = localStorage.getItem(storageKey);
    if (saved === 'light' || saved === 'dark') preference = saved;
  } catch { /* Storage may be disabled; the toggle still works. */ }

  function updateButton() {
    const button = document.getElementById('btn-theme');
    if (!button) return;
    const isLight = document.documentElement.dataset.theme === 'light';
    button.textContent = isLight ? 'Dark mode' : 'Light mode';
    button.setAttribute('aria-label', `Switch to ${isLight ? 'dark' : 'light'} mode`);
    button.setAttribute('aria-pressed', String(isLight));
    button.title = button.getAttribute('aria-label');
  }

  function apply(theme) {
    document.documentElement.dataset.theme = theme;
    updateButton();
  }

  function toggle() {
    preference = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
    try { localStorage.setItem(storageKey, preference); } catch { /* Keep session choice. */ }
    apply(preference);
  }

  function bind() {
    const button = document.getElementById('btn-theme');
    if (button && !button.dataset.themeBound) {
      button.addEventListener('click', toggle);
      button.dataset.themeBound = 'true';
    }
    updateButton();
  }

  apply(preference || (media?.matches ? 'dark' : 'light'));
  media?.addEventListener?.('change', (event) => {
    if (!preference) apply(event.matches ? 'dark' : 'light');
  });
  window.addEventListener('storage', (event) => {
    if (event.key !== storageKey && event.key !== null) return;
    preference = ['light', 'dark'].includes(event.newValue) ? event.newValue : null;
    apply(preference || (media?.matches ? 'dark' : 'light'));
  });
  window.dashboardTheme = {bind, toggle};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();
})();
