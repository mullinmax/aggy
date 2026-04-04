// ========== State ==========
let currentFeed = null;      // { feed_name, feed_name_hash }
let currentItems = [];
let itemSkip = 0;
const ITEMS_PER_PAGE = 20;
let selectedTemplate = null;
let searchTimeout = null;

// ========== Init ==========
document.addEventListener('DOMContentLoaded', async () => {
  if (!api.getToken()) {
    window.location.href = '/login';
    return;
  }
  try {
    const info = await api.userInfo();
    document.getElementById('usernameDisplay').textContent = info.username;
  } catch {
    window.location.href = '/login';
    return;
  }
  loadFeeds();
});

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeReader();
    closeModal('createFeedModal');
    closeModal('addSourceModal');
    closeModal('confirmModal');
  }
});

// ========== Navigation ==========
function showDashboard() {
  document.getElementById('viewDashboard').style.display = 'block';
  document.getElementById('viewFeed').style.display = 'none';
  currentFeed = null;
  loadFeeds();
}

function showFeedView(feed) {
  currentFeed = feed;
  document.getElementById('viewDashboard').style.display = 'none';
  document.getElementById('viewFeed').style.display = 'block';
  document.getElementById('feedTitle').textContent = feed.feed_name;
  document.getElementById('feedBreadcrumb').textContent = feed.feed_name;
  switchFeedTab('items', document.querySelector('[data-tab="items"]'));
  itemSkip = 0;
  currentItems = [];
  loadFeedItems();
}

function switchFeedTab(tab, el) {
  document.querySelectorAll('.tab-bar .tab').forEach(t => t.classList.remove('active'));
  if (el) el.classList.add('active');
  document.getElementById('tabItems').style.display = tab === 'items' ? 'block' : 'none';
  document.getElementById('tabSources').style.display = tab === 'sources' ? 'block' : 'none';
  if (tab === 'sources') loadSources();
}

// ========== Feeds ==========
async function loadFeeds() {
  const grid = document.getElementById('feedGrid');
  grid.innerHTML = '<div class="loading-center"><div class="spinner"></div></div>';
  try {
    const feeds = await api.listFeeds();
    if (!feeds.length) {
      grid.innerHTML = `
        <div class="empty-state" style="grid-column:1/-1;">
          <div class="empty-state-icon">&#x1f4e1;</div>
          <h3>No feeds yet</h3>
          <p>Create your first feed to start aggregating content</p>
          <button class="btn btn-primary" onclick="showCreateFeedModal()">+ Create Feed</button>
        </div>`;
      return;
    }
    grid.innerHTML = feeds.map(f => {
      const initial = f.feed_name.charAt(0).toUpperCase();
      return `
        <div class="feed-card" onclick="showFeedView(${esc(f)})">
          <div class="feed-card-header">
            <div class="feed-card-icon">${escHtml(initial)}</div>
            <button class="btn btn-icon btn-ghost btn-sm feed-card-delete"
              onclick="event.stopPropagation(); confirmDeleteFeedCard('${escAttr(f.feed_name_hash)}', '${escAttr(f.feed_name)}')"
              title="Delete feed">&times;</button>
          </div>
          <div>
            <div class="feed-card-name">${escHtml(f.feed_name)}</div>
          </div>
        </div>`;
    }).join('');
  } catch (err) {
    grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1;"><p>Failed to load feeds</p></div>`;
    toast(err.message, 'error');
  }
}

function showCreateFeedModal() {
  document.getElementById('newFeedName').value = '';
  openModal('createFeedModal');
  document.getElementById('newFeedName').focus();
}

async function handleCreateFeed(e) {
  e.preventDefault();
  const name = document.getElementById('newFeedName').value.trim();
  if (!name) return;
  try {
    await api.createFeed(name);
    closeModal('createFeedModal');
    toast(`Feed "${name}" created`);
    loadFeeds();
  } catch (err) {
    toast(err.message, 'error');
  }
}

function confirmDeleteFeedCard(hash, name) {
  document.getElementById('confirmTitle').textContent = 'Delete Feed';
  document.getElementById('confirmMessage').textContent = `Are you sure you want to delete "${name}"? All sources and items within it will be removed.`;
  const btn = document.getElementById('confirmAction');
  btn.textContent = 'Delete Feed';
  btn.onclick = async () => {
    try {
      await api.deleteFeed(hash);
      closeModal('confirmModal');
      toast(`Feed "${name}" deleted`);
      loadFeeds();
    } catch (err) { toast(err.message, 'error'); }
  };
  openModal('confirmModal');
}

function confirmDeleteFeed() {
  if (!currentFeed) return;
  document.getElementById('confirmTitle').textContent = 'Delete Feed';
  document.getElementById('confirmMessage').textContent = `Are you sure you want to delete "${currentFeed.feed_name}"? This cannot be undone.`;
  const btn = document.getElementById('confirmAction');
  btn.textContent = 'Delete Feed';
  btn.onclick = async () => {
    try {
      await api.deleteFeed(currentFeed.feed_name_hash);
      closeModal('confirmModal');
      toast(`Feed deleted`);
      showDashboard();
    } catch (err) { toast(err.message, 'error'); }
  };
  openModal('confirmModal');
}

// ========== Items ==========
async function loadFeedItems() {
  const list = document.getElementById('itemList');
  if (itemSkip === 0) list.innerHTML = '<div class="loading-center"><div class="spinner"></div></div>';

  try {
    const items = await api.getFeedItems(currentFeed.feed_name_hash, itemSkip, ITEMS_PER_PAGE);
    if (itemSkip === 0) list.innerHTML = '';

    if (!items.length && itemSkip === 0) {
      list.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">&#x1f4f0;</div>
          <h3>No articles yet</h3>
          <p>Add some sources to this feed and articles will appear here once ingested</p>
          <button class="btn btn-primary btn-sm" onclick="showAddSourceModal()">+ Add Source</button>
        </div>`;
      document.getElementById('loadMoreBtn').style.display = 'none';
      return;
    }

    currentItems = currentItems.concat(items);
    items.forEach(item => {
      list.insertAdjacentHTML('beforeend', renderItemCard(item));
    });

    document.getElementById('loadMoreBtn').style.display = items.length >= ITEMS_PER_PAGE ? 'inline-flex' : 'none';
  } catch (err) {
    if (itemSkip === 0) list.innerHTML = `<div class="empty-state"><p>Failed to load articles</p></div>`;
    toast(err.message, 'error');
  }
}

function loadMoreItems() {
  itemSkip += ITEMS_PER_PAGE;
  loadFeedItems();
}

function renderItemCard(item) {
  const date = item.item_date_published ? formatDate(item.item_date_published) : '';
  const img = item.item_image_url
    ? `<img class="item-thumbnail" src="${escAttr(item.item_image_url)}" alt="" onerror="this.style.display='none'">`
    : '';
  return `
    <div class="item-card" onclick="openReader(${esc(item)})">
      ${img}
      <div class="item-body">
        <div class="item-title">${escHtml(item.item_title || 'Untitled')}</div>
        <div class="item-excerpt">${escHtml(item.item_excerpt || '')}</div>
        <div class="item-meta">
          ${item.item_domain ? `<span class="domain">${escHtml(item.item_domain)}</span>` : ''}
          ${item.item_author ? `<span>${escHtml(item.item_author)}</span>` : ''}
          ${date ? `<span>${date}</span>` : ''}
        </div>
      </div>
      <div class="item-score-controls" onclick="event.stopPropagation()">
        <button class="vote-btn" onclick="voteItem('${escAttr(item.item_hash)}', 1, this)" title="Upvote">&#9650;</button>
        <button class="vote-btn" onclick="voteItem('${escAttr(item.item_hash)}', -1, this)" title="Downvote">&#9660;</button>
      </div>
    </div>`;
}

async function voteItem(hash, score, btn) {
  try {
    await api.setItemState(currentFeed.feed_name_hash, hash, score, true);
    // Highlight the button
    const parent = btn.parentElement;
    parent.querySelectorAll('.vote-btn').forEach(b => {
      b.classList.remove('upvoted', 'downvoted');
    });
    btn.classList.add(score > 0 ? 'upvoted' : 'downvoted');
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ========== Reader ==========
function openReader(item) {
  document.getElementById('readerTitle').textContent = item.item_title || 'Untitled';

  let meta = '';
  if (item.item_domain) meta += `<a href="${escAttr(item.item_url)}" target="_blank" rel="noopener">${escHtml(item.item_domain)}</a>`;
  if (item.item_author) meta += `<span>by ${escHtml(item.item_author)}</span>`;
  if (item.item_date_published) meta += `<span>${formatDate(item.item_date_published)}</span>`;
  meta += `<a href="${escAttr(item.item_url)}" target="_blank" rel="noopener" style="margin-left:auto;">Open original &#8599;</a>`;
  document.getElementById('readerMeta').innerHTML = meta;

  const img = document.getElementById('readerImage');
  if (item.item_image_url) {
    img.src = item.item_image_url;
    img.style.display = 'block';
    img.onerror = () => { img.style.display = 'none'; };
  } else {
    img.style.display = 'none';
  }

  document.getElementById('readerContent').innerHTML = item.item_content || `<p>${escHtml(item.item_excerpt || 'No content available.')}</p>`;
  document.getElementById('readerOverlay').classList.add('active');
  document.body.style.overflow = 'hidden';

  // Mark as read
  if (currentFeed) {
    api.setItemState(currentFeed.feed_name_hash, item.item_hash, null, true).catch(() => {});
  }
}

function closeReader() {
  document.getElementById('readerOverlay').classList.remove('active');
  document.body.style.overflow = '';
}

// ========== Sources ==========
async function loadSources() {
  const list = document.getElementById('sourceList');
  list.innerHTML = '<div class="loading-center"><div class="spinner"></div></div>';
  try {
    const sources = await api.getFeedSources(currentFeed.feed_name_hash);
    if (!sources.length) {
      list.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">&#x1f517;</div>
          <h3>No sources</h3>
          <p>Add sources to pull content into this feed</p>
          <button class="btn btn-primary btn-sm" onclick="showAddSourceModal()">+ Add Source</button>
        </div>`;
      return;
    }
    list.innerHTML = sources.map(s => `
      <div class="source-item">
        <div class="source-info">
          <div class="source-name">${escHtml(s.source_name)}</div>
          <div class="source-url">${escHtml(s.source_url)}</div>
        </div>
        <button class="btn btn-sm btn-danger" onclick="confirmDeleteSource('${escAttr(s.source_name_hash)}', '${escAttr(s.source_name)}')">Remove</button>
      </div>`).join('');
  } catch (err) {
    list.innerHTML = '<div class="empty-state"><p>Failed to load sources</p></div>';
    toast(err.message, 'error');
  }
}

function showManageSources() {
  switchFeedTab('sources', document.querySelector('[data-tab="sources"]'));
}

function showAddSourceModal() {
  selectedTemplate = null;
  document.getElementById('templateSearch').value = '';
  document.getElementById('templateList').innerHTML = '';
  document.getElementById('templateParams').style.display = 'none';
  switchSourceTab('template');
  openModal('addSourceModal');
  document.getElementById('templateSearch').focus();
}

function switchSourceTab(tab) {
  document.querySelectorAll('#addSourceModal .auth-tab').forEach((t, i) => {
    t.classList.toggle('active', (tab === 'template' && i === 0) || (tab === 'manual' && i === 1));
  });
  document.getElementById('sourceTabTemplate').style.display = tab === 'template' ? 'block' : 'none';
  document.getElementById('sourceTabManual').style.display = tab === 'manual' ? 'block' : 'none';
}

async function searchTemplates() {
  const q = document.getElementById('templateSearch').value.trim();
  if (!q) {
    document.getElementById('templateList').innerHTML = '';
    return;
  }
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(async () => {
    try {
      const templates = await api.searchTemplates(q, 0, 20);
      const list = document.getElementById('templateList');
      if (!templates.length) {
        list.innerHTML = '<div style="padding:20px; text-align:center; color:var(--text-muted); font-size:0.85rem;">No templates found</div>';
        return;
      }
      list.innerHTML = templates.map(t => `
        <div class="template-item" onclick="selectTemplate('${escAttr(t.name_hash)}')">
          <div class="template-name">${escHtml(t.user_friendly_name || t.name)}</div>
          ${t.description ? `<div class="template-desc">${escHtml(t.description)}</div>` : ''}
        </div>`).join('');
    } catch (err) {
      toast(err.message, 'error');
    }
  }, 300);
}

async function selectTemplate(hash) {
  try {
    const tmpl = await api.getTemplate(hash);
    selectedTemplate = tmpl;
    document.getElementById('templateList').style.display = 'none';
    document.getElementById('templateParams').style.display = 'block';
    document.getElementById('templateSourceName').value = tmpl.user_friendly_name || tmpl.name || '';

    const fields = document.getElementById('templateParamFields');
    fields.innerHTML = '';
    if (tmpl.parameters) {
      for (const [key, param] of Object.entries(tmpl.parameters)) {
        const required = param.required ? 'required' : '';
        const label = param.title || param.name || key;
        let input;
        if (param.type === 'select' && param.options) {
          const opts = Object.entries(param.options).map(([v, l]) =>
            `<option value="${escAttr(v)}" ${v === param.default ? 'selected' : ''}>${escHtml(l || v)}</option>`
          ).join('');
          input = `<select class="form-input" name="${escAttr(key)}" ${required}>${opts}</select>`;
        } else if (param.type === 'checkbox') {
          input = `<input type="checkbox" name="${escAttr(key)}" ${param.default === 'checked' ? 'checked' : ''} style="width:auto;">`;
        } else if (param.type === 'number') {
          input = `<input type="number" class="form-input" name="${escAttr(key)}" value="${escAttr(param.default || '')}" placeholder="${escAttr(param.example || '')}" ${required}>`;
        } else {
          input = `<input type="text" class="form-input" name="${escAttr(key)}" value="${escAttr(param.default || '')}" placeholder="${escAttr(param.example || '')}" ${required}>`;
        }
        fields.innerHTML += `<div class="form-group"><label>${escHtml(label)}${param.required ? ' *' : ''}</label>${input}</div>`;
      }
    }
  } catch (err) {
    toast(err.message, 'error');
  }
}

function clearTemplateSelection() {
  selectedTemplate = null;
  document.getElementById('templateList').style.display = 'block';
  document.getElementById('templateParams').style.display = 'none';
}

async function handleCreateSourceFromTemplate() {
  if (!selectedTemplate || !currentFeed) return;
  const name = document.getElementById('templateSourceName').value.trim();
  if (!name) { toast('Please enter a source name', 'error'); return; }

  const params = {};
  const fields = document.getElementById('templateParamFields');
  fields.querySelectorAll('input, select').forEach(el => {
    if (el.type === 'checkbox') {
      params[el.name] = el.checked ? 'on' : '';
    } else {
      params[el.name] = el.value;
    }
  });

  try {
    await api.createSourceFromTemplate(
      selectedTemplate.name_hash,
      currentFeed.feed_name_hash,
      name,
      params
    );
    closeModal('addSourceModal');
    toast(`Source "${name}" added`);
    loadSources();
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function handleCreateManualSource(e) {
  e.preventDefault();
  if (!currentFeed) return;
  const name = document.getElementById('manualSourceName').value.trim();
  const url = document.getElementById('manualSourceUrl').value.trim();
  try {
    await api.createSource(currentFeed.feed_name_hash, name, url);
    closeModal('addSourceModal');
    toast(`Source "${name}" added`);
    document.getElementById('manualSourceName').value = '';
    document.getElementById('manualSourceUrl').value = '';
    loadSources();
  } catch (err) {
    toast(err.message, 'error');
  }
}

function confirmDeleteSource(hash, name) {
  document.getElementById('confirmTitle').textContent = 'Remove Source';
  document.getElementById('confirmMessage').textContent = `Remove "${name}" from this feed?`;
  const btn = document.getElementById('confirmAction');
  btn.textContent = 'Remove';
  btn.onclick = async () => {
    try {
      await api.deleteSource(currentFeed.feed_name_hash, hash);
      closeModal('confirmModal');
      toast(`Source removed`);
      loadSources();
    } catch (err) { toast(err.message, 'error'); }
  };
  openModal('confirmModal');
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
    const diffMs = now - d;
    const diffMins = Math.floor(diffMs / 60000);
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

function esc(obj) {
  return escAttr(JSON.stringify(obj));
}
