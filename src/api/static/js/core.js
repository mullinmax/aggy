// Aggy UI core — tiny helpers for static pages with vanilla JS.
// No build step, no dependencies. Everything renders through h()/render(),
// which only ever insert text nodes for strings, so user/content data can
// never be interpreted as HTML.

'use strict';

const $ = (id) => document.getElementById(id);

// h('div', { class: 'card', onclick: fn }, child, ...) -> HTMLElement
// Props starting with "on" are event listeners; strings become text nodes.
function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? '' : value);
  }
  el.append(...flatChildren(children));
  return el;
}

// render(el, ...children) — replace an element's children
function render(el, ...children) {
  el.replaceChildren(...flatChildren(children));
}

function flatChildren(children) {
  return children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false);
}

const spinner = () =>
  h('div', { class: 'flex justify-center py-16' },
    h('span', { class: 'loading loading-spinner loading-lg' }));

// emptyState('📰', 'No articles yet', 'Add sources...', button?)
function emptyState(icon, title, message, actionButton) {
  return h('div', { class: 'text-center py-16' },
    h('p', { class: 'text-4xl mb-3 opacity-40' }, icon),
    h('h3', { class: 'font-semibold mb-1' }, title),
    h('p', { class: 'text-sm text-base-content/60 mb-4' }, message),
    actionButton || null);
}

// ---------- toasts & modals ----------

function toast(message, type = 'alert-success') {
  const el = h('div', { class: `alert ${type} text-sm shadow-lg` }, h('span', {}, message));
  $('toasts').append(el);
  setTimeout(() => el.remove(), 3500);
}

const showModal = (id) => $(id).showModal();
const closeModal = (id) => $(id).close();

// Shared confirm dialog (markup lives in the page template).
function confirmDialog({ title = 'Confirm', message = '', action = 'Delete', onConfirm }) {
  $('confirmTitle').textContent = title;
  $('confirmMessage').textContent = message;
  const btn = $('confirmAction');
  btn.textContent = action;
  btn.onclick = async () => {
    try {
      await onConfirm();
      closeModal('confirmModal');
    } catch (err) {
      toast(err.message, 'alert-error');
    }
  };
  showModal('confirmModal');
}

// Close any open dialog on Escape.
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') document.querySelectorAll('dialog[open]').forEach((d) => d.close());
});

// Any element with data-close-modal closes its enclosing <dialog>.
document.addEventListener('click', (e) => {
  const closer = e.target.closest('[data-close-modal]');
  if (closer) closer.closest('dialog')?.close();
});

// ---------- hash router ----------

// router.add('', showHome).add('feed/:hash', ({hash}) => ...).start()
const router = {
  _routes: [],

  add(pattern, handler) {
    const names = [];
    const regex = new RegExp(
      '^' + pattern.replace(/:[^/]+/g, (m) => { names.push(m.slice(1)); return '([^/]+)'; }) + '$'
    );
    this._routes.push({ regex, names, handler });
    return this;
  },

  go(path) {
    const target = '#/' + String(path).replace(/^[#/]+/, '');
    if (location.hash === target) this._dispatch();
    else location.hash = target;
  },

  start() {
    window.addEventListener('hashchange', () => this._dispatch());
    this._dispatch();
  },

  _dispatch() {
    const path = location.hash.replace(/^[#/]+/, '').replace(/\/+$/, '');
    for (const route of this._routes) {
      const match = path.match(route.regex);
      if (match) {
        const params = {};
        route.names.forEach((name, i) => { params[name] = decodeURIComponent(match[i + 1]); });
        route.handler(params);
        return;
      }
    }
    if (path) this.go(''); // unknown route -> home
  },
};

// ---------- auth token ----------

const auth = {
  token: () => localStorage.getItem('aggy_token'),
  save: (t) => localStorage.setItem('aggy_token', t),
  clear: () => localStorage.removeItem('aggy_token'),
};

// ---------- misc ----------

function timeAgo(dateStr) {
  try {
    const d = new Date(dateStr);
    const now = new Date();
    const diffMins = Math.floor((now - d) / 60000);
    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    if (diffDays < 7) return `${diffDays}d ago`;
    return d.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: d.getFullYear() !== now.getFullYear() ? 'numeric' : undefined,
    });
  } catch {
    return '';
  }
}

// debounce(fn, ms) — trailing-edge debounce for inputs
function debounce(fn, ms = 300) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}
