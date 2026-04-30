// ========== SDK Setup ==========
const sdk = new AggySDK();

function loadToken() {
  const t = localStorage.getItem('aggy_token');
  if (t) sdk.setToken(t);
  return t;
}

// ========== State ==========
let currentFeed = null;
let currentItems = [];
let itemSkip = 0;
const ITEMS_PER_PAGE = 20;
let selectedTemplate = null;
let searchTimeout = null;

// ========== Init ==========
document.addEventListener('DOMContentLoaded', async () => {
  if (!loadToken()) { window.location.href = '/login'; return; }
  try {
    const info = await sdk.authUserInfo();
    document.getElementById('usernameDisplay').textContent = info.username;
  } catch {
    window.location.href = '/login';
    return;
  }
  loadFeeds();
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    document.querySelectorAll('dialog[open]').forEach(d => d.close());
  }
});

// ========== Toast ==========
function toast(message, type = 'alert-success') {
  const c = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = `alert ${type} text-sm shadow-lg`;
  el.innerHTML = `<span>${escHtml(message)}</span>`;
  c.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ========== Modal Helpers ==========
function showModal(id) { document.getElementById(id).showModal(); }
function closeModal(id) { document.getElementById(id).close(); }

// ========== Navigation ==========
function showDashboard() {
  document.getElementById('viewDashboard').classList.remove('hidden');
  document.getElementById('viewFeed').classList.add('hidden');
  currentFeed = null;
  loadFeeds();
}

function showFeedView(feed) {
  currentFeed = feed;
  document.getElementById('viewDashboard').classList.add('hidden');
  document.getElementById('viewFeed').classList.remove('hidden');
  document.getElementById('feedTitle').textContent = feed.feed_name;
  document.getElementById('feedBreadcrumb').textContent = feed.feed_name;
  switchFeedTab('items');
  itemSkip = 0;
  currentItems = [];
  loadFeedItems();
}

function switchFeedTab(tab, el) {
  document.querySelectorAll('[role="tablist"] .tab[data-tab]').forEach(t =>
    t.classList.toggle('tab-active', t.dataset.tab === tab)
  );
  document.getElementById('tabItems').classList.toggle('hidden', tab !== 'items');
  document.getElementById('tabSources').classList.toggle('hidden', tab !== 'sources');
  if (tab === 'sources') loadSources();
}

// ========== Feeds ==========
async function loadFeeds() {
  const grid = document.getElementById('feedGrid');
  grid.innerHTML = '<div class="flex justify-center col-span-full py-16"><span class="loading loading-spinner loading-lg"></span></div>';
  try {
    const feeds = await sdk.feedList();
    if (!feeds.length) {
      grid.innerHTML = `
        <div class="col-span-full text-center py-16">
          <p class="text-4xl mb-3 opacity-40">&#x1f4e1;</p>
          <h3 class="font-semibold mb-1">No feeds yet</h3>
          <p class="text-sm text-base-content/60 mb-4">Create your first feed to start aggregating content</p>
          <button class="btn btn-primary btn-sm" onclick="showModal('createFeedModal')">+ Create Feed</button>
        </div>`;
      return;
    }
    grid.innerHTML = feeds.map(f => `
      <div class="card bg-base-200 shadow-sm hover:shadow-md transition-shadow cursor-pointer border border-base-300 hover:border-primary"
           onclick="showFeedView(${escAttr(JSON.stringify(f))})">
        <div class="card-body p-5">
          <div class="flex items-start justify-between">
            <div class="badge badge-primary badge-outline font-bold text-lg p-3">${escHtml(f.feed_name.charAt(0).toUpperCase())}</div>
            <button class="btn btn-ghost btn-xs opacity-0 group-hover:opacity-100 hover:text-error"
              onclick="event.stopPropagation(); confirmDeleteFeedCard('${escAttr(f.feed_name_hash)}', '${escAttr(f.feed_name)}')"
              title="Delete feed">✕</button>
          </div>
          <h2 class="card-title text-base mt-2">${escHtml(f.feed_name)}</h2>
        </div>
      </div>`).join('');
  } catch (err) {
    grid.innerHTML = '<div class="col-span-full text-center py-16 text-base-content/50">Failed to load feeds</div>';
    toast(err.message, 'alert-error');
  }
}

async function handleCreateFeed(e) {
  e.preventDefault();
  const name = document.getElementById('newFeedName').value.trim();
  if (!name) return;
  try {
    await sdk.feedCreate({ feed_name: name });
    closeModal('createFeedModal');
    document.getElementById('newFeedName').value = '';
    toast(`Feed "${name}" created`);
    loadFeeds();
  } catch (err) { toast(err.message, 'alert-error'); }
}

function confirmDeleteFeedCard(hash, name) {
  document.getElementById('confirmTitle').textContent = 'Delete Feed';
  document.getElementById('confirmMessage').textContent = `Are you sure you want to delete "${name}"? All sources and items within it will be removed.`;
  const btn = document.getElementById('confirmAction');
  btn.textContent = 'Delete Feed';
  btn.onclick = async () => {
    try { await sdk.feedDelete({ feed_name_hash: hash }); closeModal('confirmModal'); toast(`Feed "${name}" deleted`); loadFeeds(); }
    catch (err) { toast(err.message, 'alert-error'); }
  };
  showModal('confirmModal');
}

function confirmDeleteFeed() {
  if (!currentFeed) return;
  document.getElementById('confirmTitle').textContent = 'Delete Feed';
  document.getElementById('confirmMessage').textContent = `Are you sure you want to delete "${currentFeed.feed_name}"? This cannot be undone.`;
  const btn = document.getElementById('confirmAction');
  btn.textContent = 'Delete Feed';
  btn.onclick = async () => {
    try { await sdk.feedDelete({ feed_name_hash: currentFeed.feed_name_hash }); closeModal('confirmModal'); toast('Feed deleted'); showDashboard(); }
    catch (err) { toast(err.message, 'alert-error'); }
  };
  showModal('confirmModal');
}

// ========== Items ==========
async function loadFeedItems() {
  const list = document.getElementById('itemList');
  if (itemSkip === 0) list.innerHTML = '<div class="flex justify-center py-16"><span class="loading loading-spinner loading-lg"></span></div>';

  try {
    const items = await sdk.feedItems({ feed_name_hash: currentFeed.feed_name_hash, skip: itemSkip, limit: ITEMS_PER_PAGE });
    if (itemSkip === 0) list.innerHTML = '';

    if (!items.length && itemSkip === 0) {
      list.innerHTML = `
        <div class="text-center py-16">
          <p class="text-4xl mb-3 opacity-40">&#x1f4f0;</p>
          <h3 class="font-semibold mb-1">No articles yet</h3>
          <p class="text-sm text-base-content/60 mb-4">Add some sources and articles will appear here once ingested</p>
          <button class="btn btn-primary btn-sm" onclick="showModal('addSourceModal')">+ Add Source</button>
        </div>`;
      document.getElementById('loadMoreBtn').classList.add('hidden');
      return;
    }

    currentItems = currentItems.concat(items);
    items.forEach(item => list.insertAdjacentHTML('beforeend', renderItemCard(item)));
    document.getElementById('loadMoreBtn').classList.toggle('hidden', items.length < ITEMS_PER_PAGE);
  } catch (err) {
    if (itemSkip === 0) list.innerHTML = '<div class="text-center py-16 text-base-content/50">Failed to load articles</div>';
    toast(err.message, 'alert-error');
  }
}

function loadMoreItems() {
  itemSkip += ITEMS_PER_PAGE;
  loadFeedItems();
}

function renderItemCard(item) {
  const date = item.item_date_published ? formatDate(item.item_date_published) : '';
  const img = item.item_image_url
    ? `<figure class="w-24 h-24 flex-shrink-0 rounded-lg overflow-hidden bg-base-300 hidden sm:block"><img src="${escAttr(item.item_image_url)}" class="w-full h-full object-cover" alt="" onerror="this.parentElement.style.display='none'"></figure>`
    : '';
  return `
    <div class="card card-side bg-base-200 border border-base-300 hover:border-primary/50 transition-colors cursor-pointer"
         onclick="openReader(${escAttr(JSON.stringify(item))})">
      <div class="card-body p-4 flex-row gap-4">
        ${img}
        <div class="flex-1 min-w-0">
          <h3 class="font-semibold text-sm leading-snug line-clamp-2">${escHtml(item.item_title || 'Untitled')}</h3>
          <p class="text-xs text-base-content/50 line-clamp-2 mt-1">${escHtml(item.item_excerpt || '')}</p>
          <div class="flex flex-wrap items-center gap-2 mt-2">
            ${item.item_domain ? `<span class="badge badge-primary badge-outline badge-xs">${escHtml(item.item_domain)}</span>` : ''}
            ${item.item_author ? `<span class="text-xs text-base-content/40">${escHtml(item.item_author)}</span>` : ''}
            ${date ? `<span class="text-xs text-base-content/40">${date}</span>` : ''}
          </div>
        </div>
        <div class="flex flex-col items-center gap-0 flex-shrink-0" onclick="event.stopPropagation()">
          <button class="btn btn-ghost btn-xs" onclick="voteItem('${escAttr(item.item_hash)}', 1, this)" title="Upvote">&#9650;</button>
          <button class="btn btn-ghost btn-xs" onclick="voteItem('${escAttr(item.item_hash)}', -1, this)" title="Downvote">&#9660;</button>
        </div>
      </div>
    </div>`;
}

async function voteItem(hash, score, btn) {
  try {
    await sdk.itemSetState({ feed_hash: currentFeed.feed_name_hash, item_url_hash: hash, score, is_read: true });
    const parent = btn.parentElement;
    parent.querySelectorAll('button').forEach(b => { b.classList.remove('text-success', 'text-error'); });
    btn.classList.add(score > 0 ? 'text-success' : 'text-error');
  } catch (err) { toast(err.message, 'alert-error'); }
}

// ========== Reader ==========
function openReader(item) {
  document.getElementById('readerTitle').textContent = item.item_title || 'Untitled';

  const meta = document.getElementById('readerMeta');
  let metaHtml = '';
  if (item.item_domain) metaHtml += `<a href="${escAttr(item.item_url)}" target="_blank" rel="noopener" class="link link-primary">${escHtml(item.item_domain)}</a>`;
  if (item.item_author) metaHtml += `<span>by ${escHtml(item.item_author)}</span>`;
  if (item.item_date_published) metaHtml += `<span>${formatDate(item.item_date_published)}</span>`;
  metaHtml += `<a href="${escAttr(item.item_url)}" target="_blank" rel="noopener" class="link link-primary ml-auto">Open original &#8599;</a>`;
  meta.innerHTML = metaHtml;

  const img = document.getElementById('readerImage');
  if (item.item_image_url) { img.src = item.item_image_url; img.classList.remove('hidden'); img.onerror = () => img.classList.add('hidden'); }
  else { img.classList.add('hidden'); }

  document.getElementById('readerContent').innerHTML = item.item_content || `<p>${escHtml(item.item_excerpt || 'No content available.')}</p>`;
  showModal('readerModal');

  if (currentFeed) {
    sdk.itemSetState({ feed_hash: currentFeed.feed_name_hash, item_url_hash: item.item_hash, is_read: true }).catch(() => {});
  }
}

// ========== Sources ==========
async function loadSources() {
  const list = document.getElementById('sourceList');
  list.innerHTML = '<div class="flex justify-center py-16"><span class="loading loading-spinner loading-lg"></span></div>';
  try {
    const sources = await sdk.feedSources({ feed_name_hash: currentFeed.feed_name_hash });
    if (!sources.length) {
      list.innerHTML = `
        <div class="text-center py-16">
          <p class="text-4xl mb-3 opacity-40">&#x1f517;</p>
          <h3 class="font-semibold mb-1">No sources</h3>
          <p class="text-sm text-base-content/60 mb-4">Add sources to pull content into this feed</p>
          <button class="btn btn-primary btn-sm" onclick="showModal('addSourceModal')">+ Add Source</button>
        </div>`;
      return;
    }
    list.innerHTML = sources.map(s => `
      <div class="flex items-center justify-between p-3 bg-base-200 border border-base-300 rounded-lg mb-2">
        <div class="min-w-0">
          <div class="font-medium text-sm">${escHtml(s.source_name)}</div>
          <div class="text-xs text-base-content/40 truncate">${escHtml(s.source_url)}</div>
        </div>
        <button class="btn btn-ghost btn-xs text-error" onclick="confirmDeleteSource('${escAttr(s.source_name_hash)}', '${escAttr(s.source_name)}')">Remove</button>
      </div>`).join('');
  } catch (err) {
    list.innerHTML = '<div class="text-center py-16 text-base-content/50">Failed to load sources</div>';
    toast(err.message, 'alert-error');
  }
}

function switchSourceTab(tab) {
  document.getElementById('srcTabTemplate').classList.toggle('tab-active', tab === 'template');
  document.getElementById('srcTabManual').classList.toggle('tab-active', tab === 'manual');
  document.getElementById('sourceTabTemplate').classList.toggle('hidden', tab !== 'template');
  document.getElementById('sourceTabManual').classList.toggle('hidden', tab !== 'manual');
}

async function searchTemplates() {
  const q = document.getElementById('templateSearch').value.trim();
  const list = document.getElementById('templateList');
  if (!q) { list.innerHTML = ''; return; }
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(async () => {
    try {
      const templates = await sdk.sourceTemplateSearch({ query: q, limit: 20 });
      if (!templates.length) {
        list.innerHTML = '<div class="p-4 text-center text-sm text-base-content/50">No templates found</div>';
        return;
      }
      list.innerHTML = templates.map(t => `
        <div class="p-3 border-b border-base-300 last:border-b-0 cursor-pointer hover:bg-base-300 transition-colors"
             onclick="selectTemplate('${escAttr(t.name_hash)}')">
          <div class="font-medium text-sm">${escHtml(t.user_friendly_name || t.name)}</div>
          ${t.description ? `<div class="text-xs text-base-content/50 line-clamp-2 mt-0.5">${escHtml(t.description)}</div>` : ''}
        </div>`).join('');
    } catch (err) { toast(err.message, 'alert-error'); }
  }, 300);
}

async function selectTemplate(hash) {
  try {
    const tmpl = await sdk.sourceTemplateGet({ name_hash: hash });
    selectedTemplate = tmpl;
    document.getElementById('templateList').classList.add('hidden');
    document.getElementById('templateParams').classList.remove('hidden');
    document.getElementById('templateSourceName').value = tmpl.user_friendly_name || tmpl.name || '';

    const fields = document.getElementById('templateParamFields');
    fields.innerHTML = '';
    if (tmpl.parameters) {
      for (const [key, param] of Object.entries(tmpl.parameters)) {
        const req = param.required ? 'required' : '';
        const label = param.title || param.name || key;
        let input;
        if (param.type === 'select' && param.options) {
          const opts = Object.entries(param.options).map(([v, l]) =>
            `<option value="${escAttr(v)}" ${v === param.default ? 'selected' : ''}>${escHtml(l || v)}</option>`
          ).join('');
          input = `<select class="select select-bordered w-full" name="${escAttr(key)}" ${req}>${opts}</select>`;
        } else if (param.type === 'checkbox') {
          input = `<input type="checkbox" class="checkbox" name="${escAttr(key)}" ${param.default === 'checked' ? 'checked' : ''}>`;
        } else if (param.type === 'number') {
          input = `<input type="number" class="input input-bordered w-full" name="${escAttr(key)}" value="${escAttr(param.default || '')}" placeholder="${escAttr(param.example || '')}" ${req}>`;
        } else {
          input = `<input type="text" class="input input-bordered w-full" name="${escAttr(key)}" value="${escAttr(param.default || '')}" placeholder="${escAttr(param.example || '')}" ${req}>`;
        }
        fields.innerHTML += `<div class="form-control mb-3"><label class="label"><span class="label-text">${escHtml(label)}${param.required ? ' *' : ''}</span></label>${input}</div>`;
      }
    }
  } catch (err) { toast(err.message, 'alert-error'); }
}

function clearTemplateSelection() {
  selectedTemplate = null;
  document.getElementById('templateList').classList.remove('hidden');
  document.getElementById('templateParams').classList.add('hidden');
}

async function handleCreateSourceFromTemplate() {
  if (!selectedTemplate || !currentFeed) return;
  const name = document.getElementById('templateSourceName').value.trim();
  if (!name) { toast('Please enter a source name', 'alert-error'); return; }

  const params = {};
  document.getElementById('templateParamFields').querySelectorAll('input, select').forEach(el => {
    params[el.name] = el.type === 'checkbox' ? (el.checked ? 'on' : '') : el.value;
  });

  try {
    await sdk.sourceTemplateCreate({
      body: {
        source_template_name_hash: selectedTemplate.name_hash,
        feed_hash: currentFeed.feed_name_hash,
        source_name: name,
        parameters: params
      }
    });
    closeModal('addSourceModal');
    toast(`Source "${name}" added`);
    loadSources();
  } catch (err) { toast(err.message, 'alert-error'); }
}

async function handleCreateManualSource(e) {
  e.preventDefault();
  if (!currentFeed) return;
  const name = document.getElementById('manualSourceName').value.trim();
  const url = document.getElementById('manualSourceUrl').value.trim();
  try {
    await sdk.sourceCreate({ feed_name_hash: currentFeed.feed_name_hash, source_name: name, source_url: url });
    closeModal('addSourceModal');
    toast(`Source "${name}" added`);
    document.getElementById('manualSourceName').value = '';
    document.getElementById('manualSourceUrl').value = '';
    loadSources();
  } catch (err) { toast(err.message, 'alert-error'); }
}

function confirmDeleteSource(hash, name) {
  document.getElementById('confirmTitle').textContent = 'Remove Source';
  document.getElementById('confirmMessage').textContent = `Remove "${name}" from this feed?`;
  const btn = document.getElementById('confirmAction');
  btn.textContent = 'Remove';
  btn.onclick = async () => {
    try { await sdk.sourceDelete({ feed_name_hash: currentFeed.feed_name_hash, source_name_hash: hash }); closeModal('confirmModal'); toast('Source removed'); loadSources(); }
    catch (err) { toast(err.message, 'alert-error'); }
  };
  showModal('confirmModal');
}

// ========== Auth ==========
function logout() {
  localStorage.removeItem('aggy_token');
  window.location.href = '/login';
}

// ========== Helpers ==========
function formatDate(dateStr) {
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
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: d.getFullYear() !== now.getFullYear() ? 'numeric' : undefined });
  } catch { return ''; }
}

function escHtml(s) {
  if (!s) return '';
  const div = document.createElement('div');
  div.textContent = String(s);
  return div.innerHTML;
}

function escAttr(s) {
  if (!s) return '';
  return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
