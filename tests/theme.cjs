const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const source = fs.readFileSync('static/theme.js', 'utf8');
function boot({saved, dark = false, blocked = false} = {}) {
  const dom = new JSDOM('<button id="btn-theme">Theme</button>', {url:'http://localhost/', runScripts:'outside-only'});
  let onSystemChange;
  dom.window.matchMedia = () => ({matches:dark, addEventListener:(_, listener) => {onSystemChange = listener;}});
  if (saved) dom.window.localStorage.setItem('compute-dashboard-theme', saved);
  if (blocked) Object.defineProperty(dom.window, 'localStorage', {get() {throw new Error('Storage blocked');}});
  dom.window.eval(source);
  dom.window.dashboardTheme.bind();
  return {dom, root:dom.window.document.documentElement, button:dom.window.document.getElementById('btn-theme'), system:(dark) => onSystemChange({matches:dark})};
}
let test = boot();
assert.equal(test.root.dataset.theme, 'light');
assert.equal(test.button.textContent, 'Dark mode');
test.button.click();
assert.equal(test.root.dataset.theme, 'dark');
assert.equal(test.dom.window.localStorage.getItem('compute-dashboard-theme'), 'dark');
assert.equal(test.button.getAttribute('aria-label'), 'Switch to light mode');
test.dom.window.dashboardTheme.bind();
test.button.click();
assert.equal(test.root.dataset.theme, 'light'); // binding must not double-toggle
assert.equal(test.button.getAttribute('aria-pressed'), 'true');
test.dom.window.close();
test = boot({dark:true});
assert.equal(test.root.dataset.theme, 'dark');
test.system(false);
assert.equal(test.root.dataset.theme, 'light');
test.button.click();
test.system(false);
assert.equal(test.root.dataset.theme, 'dark'); // explicit choice overrides system changes
test.dom.window.close();
test = boot({saved:'light', dark:true});
assert.equal(test.root.dataset.theme, 'light');
test.dom.window.dispatchEvent(new test.dom.window.StorageEvent('storage', {key:'compute-dashboard-theme',newValue:'dark'}));
assert.equal(test.root.dataset.theme, 'dark');
test.dom.window.close();
test = boot({blocked:true});
test.button.click();
assert.equal(test.root.dataset.theme, 'dark');
test.dom.window.close();
console.log('Theme checks passed: system preference, persisted choice, accessible toggle, cross-tab updates and blocked storage.');
