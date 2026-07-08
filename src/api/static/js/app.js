// Aggy app views: dashboard (feed grid) and feed (articles + sources).
// Built on core.js (h/render/router) and the generated sdk.js.

'use strict';

const sdk = new AggySDK();

// ---------- state ----------
const PAGE_SIZE = 20;
let currentFeed = null;
let itemSkip = 0;
let selectedTemplate = null;
let editingSource = null;
let editingTemplate = null;
let onboardingContinue = false; // set when the user creates their very first feed

// ---------- boot ----------
document.addEventListener('DOMContentLoaded', async () => {
  const token = auth.token();
  if (!token) { location.href = '/login'; return; }
  sdk.setToken(token);

  try {
    const info = await sdk.authUserInfo();
    $('usernameDisplay').textContent = info.username;
  } catch {
    auth.clear();
    location.href = '/login';
    return;
  }

  bindControls();

  router
    .add('', showDashboard)
    .add('feed/:hash', ({ hash }) => showFeed(hash))
    .start();
});

function bindControls() {
  $('logoutBtn').onclick = () => { auth.clear(); location.href = '/login'; };
  $('newFeedBtn').onclick = () => showModal('createFeedModal');
  $('createFeedForm').onsubmit = handleCreateFeed;

  $('deleteFeedBtn').onclick = confirmDeleteFeed;
  $('manageSourcesBtn').onclick = () => switchFeedTab('sources');
  $('sourcesBackBtn').onclick = () => { itemSkip = 0; switchFeedTab('items'); loadFeedItems(); };
  $('loadMoreBtn').onclick = () => { itemSkip += PAGE_SIZE; loadFeedItems(); };

  $('addSourceBtn').onclick = openAddSourceModal;
  $('srcTabTemplate').onclick = () => switchSourceTab('template');
  $('srcTabManual').onclick = () => switchSourceTab('manual');
  $('templateSearch').oninput = debounce(searchTemplates, 300);
  $('templateBackBtn').onclick = clearTemplateSelection;
  $('templateAddBtn').onclick = handleCreateSourceFromTemplate;
  $('manualSourceForm').onsubmit = handleCreateManualSource;
  $('editSourceSaveBtn').onclick = handleUpdateSource;
}

function setView(name) {
  $('viewDashboard').classList.toggle('hidden', name !== 'dashboard');
  $('viewFeed').classList.toggle('hidden', name !== 'feed');
}

// ---------- dashboard ----------
function showDashboard() {
  setView('dashboard');
  currentFeed = null;
  loadFeeds();
}

async function loadFeeds() {
  const grid = $('feedGrid');
  render(grid, h('div', { class: 'col-span-full' }, spinner()));
  try {
    const feeds = await sdk.feedList();
    if (!feeds.length) {
      render(grid, h('div', { class: 'col-span-full' }, onboardingWelcome()));
      return;
    }
    render(grid, feeds.map(feedCard));
  } catch (err) {
    render(grid, h('div', { class: 'col-span-full text-center py-16 text-base-content/50' }, 'Failed to load feeds'));
    toast(err.message, 'alert-error');
  }
}

// First-run onboarding shown in place of the feed grid when the user has no feeds.
function onboardingWelcome() {
  const step = (num, title, message, active) =>
    h('li', { class: 'flex gap-4 items-start' },
      h('div', {
        class: `badge ${active ? 'badge-primary' : 'badge-ghost'} badge-lg font-bold flex-shrink-0`,
      }, String(num)),
      h('div', {},
        h('div', { class: `font-semibold text-sm ${active ? '' : 'text-base-content/50'}` }, title),
        h('div', { class: 'text-xs text-base-content/60 mt-0.5' }, message)));

  return h('div', { class: 'card bg-base-200 border border-base-300 max-w-lg mx-auto mt-8' },
    h('div', { class: 'card-body' },
      h('p', { class: 'text-4xl mb-1' }, '\u{1F44B}'),
      h('h2', { class: 'card-title' }, 'Welcome to Aggy!'),
      h('p', { class: 'text-sm text-base-content/60 mb-4' },
        'Aggy pulls articles from sources you choose into feeds, then learns what you like as you vote. Getting set up takes three quick steps:'),
      h('ul', { class: 'flex flex-col gap-4 mb-5' },
        step(1, 'Create a feed', 'A feed is a topic bucket, like "Technology" or "Sports".', true),
        step(2, 'Add sources', 'Point the feed at websites via templates or RSS URLs.', false),
        step(3, 'Read & vote', 'Articles roll in; upvote and downvote to tune your ranking.', false)),
      h('div', { class: 'card-actions' },
        h('button', {
          class: 'btn btn-primary w-full',
          onclick: () => { onboardingContinue = true; showModal('createFeedModal'); $('newFeedName').focus(); },
        }, 'Create your first feed'))));
}

function feedCard(feed) {
  return h('div', {
    class: 'card bg-base-200 shadow-sm hover:shadow-md transition-shadow cursor-pointer border border-base-300 hover:border-primary',
    onclick: () => router.go(`feed/${feed.feed_name_hash}`),
  },
    h('div', { class: 'card-body p-5' },
      h('div', { class: 'flex items-start justify-between' },
        h('div', { class: 'badge badge-primary badge-outline font-bold text-lg p-3' },
          feed.feed_name.charAt(0).toUpperCase()),
        h('button', {
          class: 'btn btn-ghost btn-xs hover:text-error',
          title: 'Delete feed',
          onclick: (e) => { e.stopPropagation(); confirmDeleteFeedCard(feed); },
        }, '✕')),
      h('h2', { class: 'card-title text-base mt-2' }, feed.feed_name)));
}

async function handleCreateFeed(e) {
  e.preventDefault();
  const name = $('newFeedName').value.trim();
  if (!name) return;
  try {
    const feed = await sdk.feedCreate({ feed_name: name });
    closeModal('createFeedModal');
    $('newFeedName').value = '';
    toast(`Feed "${name}" created`);
    router.go(`feed/${feed.feed_name_hash}`);
  } catch (err) {
    toast(err.message, 'alert-error');
  }
}

function confirmDeleteFeedCard(feed) {
  confirmDialog({
    title: 'Delete Feed',
    message: `Are you sure you want to delete "${feed.feed_name}"? All sources and items within it will be removed.`,
    action: 'Delete Feed',
    onConfirm: async () => {
      await sdk.feedDelete({ feed_name_hash: feed.feed_name_hash });
      toast(`Feed "${feed.feed_name}" deleted`);
      loadFeeds();
    },
  });
}

function confirmDeleteFeed() {
  if (!currentFeed) return;
  confirmDialog({
    title: 'Delete Feed',
    message: `Are you sure you want to delete "${currentFeed.feed_name}"? This cannot be undone.`,
    action: 'Delete Feed',
    onConfirm: async () => {
      await sdk.feedDelete({ feed_name_hash: currentFeed.feed_name_hash });
      toast('Feed deleted');
      router.go('');
    },
  });
}

// ---------- feed view ----------
async function showFeed(hash) {
  setView('feed');
  itemSkip = 0;
  render($('itemList'), spinner());

  if (!currentFeed || currentFeed.feed_name_hash !== hash) {
    try {
      currentFeed = await sdk.feedGet({ feed_name_hash: hash });
    } catch (err) {
      toast(err.message, 'alert-error');
      router.go('');
      return;
    }
  }

  $('feedTitle').textContent = currentFeed.feed_name;
  $('feedBreadcrumb').textContent = currentFeed.feed_name;

  // Continue first-run onboarding: land the user on the next step (adding
  // a source) instead of an empty articles list.
  if (onboardingContinue) {
    onboardingContinue = false;
    switchFeedTab('sources');
    openAddSourceModal();
    toast('Feed created! Now add a source — search a template or paste an RSS URL.', 'alert-info');
    return;
  }

  switchFeedTab('items');
  loadFeedItems();
}

function switchFeedTab(tab) {
  $('tabItems').classList.toggle('hidden', tab !== 'items');
  $('tabSources').classList.toggle('hidden', tab !== 'sources');
  if (tab === 'sources') loadSources();
}

// ---------- items ----------
async function loadFeedItems() {
  const list = $('itemList');
  if (itemSkip === 0) render(list, spinner());

  try {
    const items = await sdk.feedItems({
      feed_name_hash: currentFeed.feed_name_hash,
      skip: itemSkip,
      limit: PAGE_SIZE,
    });
    if (itemSkip === 0) render(list);

    if (!items.length && itemSkip === 0) {
      render(list, emptyState('\u{1F4F0}', 'No articles yet',
        'Add some sources and articles will appear here once ingested',
        h('button', { class: 'btn btn-primary btn-sm', onclick: openAddSourceModal }, '+ Add Source')));
      $('loadMoreBtn').classList.add('hidden');
      return;
    }

    items.forEach((item) => list.append(itemCard(item)));
    $('loadMoreBtn').classList.toggle('hidden', items.length < PAGE_SIZE);
  } catch (err) {
    if (itemSkip === 0) render(list, h('div', { class: 'text-center py-16 text-base-content/50' }, 'Failed to load articles'));
    toast(err.message, 'alert-error');
  }
}

// Parse an item's (server-sanitized) content once to pull out the pieces the
// UI cares about: a usable image and whether it's reddit-style boilerplate.
function parseItemContent(item) {
  const root = document.createElement('div');
  root.innerHTML = item.item_content || '';
  const img = root.querySelector('img');
  const isReddit = Array.from(root.querySelectorAll('a'))
    .some((a) => a.textContent.trim() === '[comments]');
  return {
    root,
    isReddit,
    imageUrl: item.item_image_url || (img ? img.src : null),
    imageFromContent: !item.item_image_url && !!img,
  };
}

// Excerpts for reddit posts are mostly "submitted by /u/x [link] [comments]"
// noise — strip that so cards show real text or nothing.
function cleanExcerpt(item) {
  let text = (item.item_excerpt || '').replace(/\s+/g, ' ').trim();
  text = text.replace(/submitted by\s+\/u\/\S+.*$/i, '').trim();
  if (/^submitted by\b/i.test(text)) return '';
  return text;
}

function itemCard(item) {
  const published = item.item_date_published ? timeAgo(item.item_date_published) : '';
  const imageUrl = item.item_image_url || parseItemContent(item).imageUrl;

  const image = imageUrl
    ? h('figure', { class: 'w-24 h-24 flex-shrink-0 rounded-lg overflow-hidden bg-base-300 hidden sm:block' },
        h('img', {
          src: imageUrl, class: 'w-full h-full object-cover', alt: '',
          onerror: (e) => { e.target.parentElement.style.display = 'none'; },
        }))
    : null;

  const voteButton = (label, score, title) =>
    h('button', {
      class: 'btn btn-ghost btn-xs',
      title,
      onclick: (e) => { e.stopPropagation(); voteItem(item, score, e.currentTarget); },
    }, label);

  return h('div', {
    class: 'card card-side bg-base-200 border border-base-300 hover:border-primary/50 transition-colors cursor-pointer',
    onclick: () => openReader(item),
  },
    h('div', { class: 'card-body p-4 flex-row gap-4' },
      image,
      h('div', { class: 'flex-1 min-w-0' },
        h('h3', { class: 'font-semibold text-sm leading-snug line-clamp-2' }, item.item_title || 'Untitled'),
        h('p', { class: 'text-xs text-base-content/50 line-clamp-2 mt-1' }, cleanExcerpt(item)),
        h('div', { class: 'flex flex-wrap items-center gap-2 mt-2' },
          item.item_source_name && h('span', { class: 'badge badge-secondary badge-outline badge-xs' }, item.item_source_name),
          item.item_author && h('span', { class: 'text-xs text-base-content/40' }, item.item_author),
          published && h('span', { class: 'text-xs text-base-content/40' }, published))),
      h('div', { class: 'flex flex-col items-center gap-0 flex-shrink-0' },
        voteButton('▲', 1, 'Upvote'),
        voteButton('▼', -1, 'Downvote'))));
}

async function voteItem(item, score, btn) {
  try {
    await sdk.itemSetState({
      feed_hash: currentFeed.feed_name_hash,
      item_url_hash: item.item_hash,
      score,
      is_read: true,
    });
    btn.parentElement.querySelectorAll('button').forEach((b) =>
      b.classList.remove('text-success', 'text-error'));
    btn.classList.add(score > 0 ? 'text-success' : 'text-error');
  } catch (err) {
    toast(err.message, 'alert-error');
  }
}

// ---------- reader ----------

// Reddit RSS content wraps everything in a "submitted by /u/x [link]
// [comments]" table that duplicates the title link, the author, and the
// original link already shown in the reader header — strip it.
function stripRedditBoilerplate(root, removeImage) {
  root.querySelectorAll('a').forEach((a) => {
    const t = a.textContent.trim();
    if (t === '[link]' || t === '[comments]') a.remove();
  });
  if (removeImage) {
    const img = root.querySelector('img');
    if (img) (img.closest('a') || img).remove();
  }
  root.querySelectorAll('td, p').forEach((el) => {
    const text = el.textContent.replace(/\s+/g, ' ').trim();
    if (/^submitted by\b/i.test(text) && text.length < 120) el.remove();
  });
  root.querySelectorAll('table').forEach((t) => {
    if (!t.textContent.trim() && !t.querySelector('img')) t.remove();
  });
}

function openReader(item) {
  $('readerTitle').textContent = item.item_title || 'Untitled';
  const parsed = parseItemContent(item);

  let host = item.item_domain || '';
  try { host = new URL(item.item_url).hostname.replace(/^www\./, ''); } catch { /* keep fallback */ }

  render($('readerMeta'),
    item.item_source_name && h('span', { class: 'badge badge-secondary badge-outline badge-xs' }, item.item_source_name),
    item.item_author && h('span', {}, `by ${item.item_author}`),
    item.item_date_published && h('span', {}, timeAgo(item.item_date_published)),
    h('a', { href: item.item_url, target: '_blank', rel: 'noopener', class: 'link link-primary ml-auto' },
      host ? `Open on ${host} ↗` : 'Open original ↗'));

  // Non-reddit articles keep their images inline in the content; only
  // promote a content image to the hero slot for reddit-style posts.
  const heroUrl = item.item_image_url || (parsed.isReddit ? parsed.imageUrl : null);
  const img = $('readerImage');
  if (heroUrl) {
    img.src = heroUrl;
    img.classList.remove('hidden');
    img.onerror = () => img.classList.add('hidden');
  } else {
    img.classList.add('hidden');
  }

  // item_content is sanitized server-side (bleach) before storage; it is the
  // only place raw HTML is intentionally rendered.
  if (parsed.isReddit) {
    // the hero image above already shows the content image
    stripRedditBoilerplate(parsed.root, parsed.imageFromContent);
  }
  if (parsed.root.textContent.trim() || parsed.root.querySelector('img')) {
    $('readerContent').innerHTML = parsed.root.innerHTML;
  } else if (!heroUrl) {
    render($('readerContent'), h('p', {}, cleanExcerpt(item) || 'No content available.'));
  } else {
    render($('readerContent'));
  }
  showModal('readerModal');

  if (currentFeed) {
    sdk.itemSetState({
      feed_hash: currentFeed.feed_name_hash,
      item_url_hash: item.item_hash,
      is_read: true,
    }).catch(() => {});
  }
}

// ---------- sources ----------
async function loadSources() {
  const list = $('sourceList');
  render(list, spinner());
  try {
    const sources = await sdk.feedSources({ feed_name_hash: currentFeed.feed_name_hash });
    if (!sources.length) {
      render(list, emptyState('\u{1F517}', 'No sources',
        'Add sources to pull content into this feed',
        h('button', { class: 'btn btn-primary btn-sm', onclick: openAddSourceModal }, '+ Add Source')));
      return;
    }
    render(list, sources.map(sourceRow));
  } catch (err) {
    render(list, h('div', { class: 'text-center py-16 text-base-content/50' }, 'Failed to load sources'));
    toast(err.message, 'alert-error');
  }
}

function sourceRow(source) {
  const count = source.source_item_count ?? 0;
  const checked = source.source_last_ingested_at
    ? `checked ${timeAgo(source.source_last_ingested_at)}`
    : 'not checked yet';
  return h('div', { class: 'flex items-center justify-between gap-3 p-3 bg-base-200 border border-base-300 rounded-lg mb-2' },
    h('div', { class: 'min-w-0' },
      h('div', { class: 'font-medium text-sm' }, source.source_name),
      h('div', { class: 'text-xs text-base-content/40 truncate' }, source.source_url),
      h('div', { class: 'text-xs text-base-content/60 mt-1' },
        `${count} article${count === 1 ? '' : 's'} · ${checked}`),
      source.source_last_ingest_error && h('div', { class: 'text-xs text-error mt-1' },
        `Last check failed: ${source.source_last_ingest_error}`)),
    h('div', { class: 'flex gap-1 flex-shrink-0' },
      h('button', {
        class: 'btn btn-ghost btn-xs',
        onclick: () => openEditSourceModal(source),
      }, 'Edit'),
      h('button', {
        class: 'btn btn-ghost btn-xs text-error',
        onclick: () => confirmDeleteSource(source),
      }, 'Remove')));
}

async function openEditSourceModal(source) {
  editingSource = source;
  editingTemplate = null;
  $('editSourceTitle').textContent = `Edit ${source.source_name}`;
  $('editSourceName').value = source.source_name;

  const fields = $('editSourceFields');
  if (source.source_template_name_hash) {
    render(fields, spinner());
    showModal('editSourceModal');
    try {
      editingTemplate = await sdk.sourceTemplateGet({ name_hash: source.source_template_name_hash });
      const saved = source.source_template_parameters || {};
      render(fields,
        Object.entries(editingTemplate.parameters || {}).map(([key, param]) =>
          templateParamField(key, param, saved[key])));
    } catch (err) {
      // template no longer exists — fall back to editing the raw URL
      render(fields, editSourceUrlField(source));
    }
  } else {
    render(fields, editSourceUrlField(source));
    showModal('editSourceModal');
  }
}

function editSourceUrlField(source) {
  return h('div', { class: 'form-control mb-3' },
    h('label', { class: 'label' }, h('span', { class: 'label-text' }, 'RSS Feed URL')),
    h('input', {
      type: 'url', class: 'input input-bordered w-full', name: 'source_url',
      value: source.source_url, required: true,
    }));
}

async function handleUpdateSource() {
  if (!editingSource || !currentFeed) return;
  const name = $('editSourceName').value.trim();
  if (!name) { toast('Please enter a source name', 'alert-error'); return; }

  const body = {
    feed_name_hash: currentFeed.feed_name_hash,
    source_name_hash: editingSource.source_name_hash,
    source_name: name,
  };

  const urlInput = $('editSourceFields').querySelector('input[name="source_url"]');
  if (urlInput) {
    const url = urlInput.value.trim();
    if (!url) { toast('Please enter a URL', 'alert-error'); return; }
    body.source_url = url;
  } else if (editingTemplate) {
    const parameters = {};
    let missing = null;
    $('editSourceFields').querySelectorAll('.input-error').forEach((el) => el.classList.remove('input-error'));
    $('editSourceFields').querySelectorAll('input, select').forEach((el) => {
      const value = el.type === 'checkbox' ? (el.checked ? 'on' : '') : el.value.trim();
      if (el.required && !value && !missing) missing = el;
      parameters[el.name] = value;
    });
    if (missing) {
      missing.classList.add('input-error');
      missing.focus();
      const label = (editingTemplate.parameters[missing.name] || {}).title || missing.name;
      toast(`"${label}" is required`, 'alert-error');
      return;
    }
    body.parameters = parameters;
  }

  try {
    await sdk.sourceUpdate({ body });
    closeModal('editSourceModal');
    toast(`Source "${name}" updated`);
    editingSource = null;
    editingTemplate = null;
    loadSources();
    // an ingest may run in the background after a URL change; refresh
    setTimeout(loadSources, 5000);
  } catch (err) {
    toast(err.message, 'alert-error');
  }
}

function confirmDeleteSource(source) {
  confirmDialog({
    title: 'Remove Source',
    message: `Remove "${source.source_name}" from this feed?`,
    action: 'Remove',
    onConfirm: async () => {
      await sdk.sourceDelete({
        feed_name_hash: currentFeed.feed_name_hash,
        source_name_hash: source.source_name_hash,
      });
      toast('Source removed');
      loadSources();
    },
  });
}

function switchSourceTab(tab) {
  $('srcTabTemplate').classList.toggle('tab-active', tab === 'template');
  $('srcTabManual').classList.toggle('tab-active', tab === 'manual');
  $('sourceTabTemplate').classList.toggle('hidden', tab !== 'template');
  $('sourceTabManual').classList.toggle('hidden', tab !== 'manual');
}

async function handleCreateManualSource(e) {
  e.preventDefault();
  if (!currentFeed) return;
  const name = $('manualSourceName').value.trim();
  const url = $('manualSourceUrl').value.trim();
  try {
    await sdk.sourceCreate({ feed_name_hash: currentFeed.feed_name_hash, source_name: name, source_url: url });
    closeModal('addSourceModal');
    toast(`Source "${name}" added`);
    $('manualSourceName').value = '';
    $('manualSourceUrl').value = '';
    loadSources();
    // the first ingest runs in the background; refresh to pick up its result
    setTimeout(loadSources, 5000);
  } catch (err) {
    toast(err.message, 'alert-error');
  }
}

// ---------- source templates ----------
function openAddSourceModal() {
  showModal('addSourceModal');
  clearTemplateSelection();
  searchTemplates();
}

async function searchTemplates() {
  // An empty query returns the full template list (alphabetized); a query
  // filters and sorts it by fuzzy-match relevance.
  const query = $('templateSearch').value.trim();
  const list = $('templateList');
  try {
    const templates = await sdk.sourceTemplateSearch({ query });
    if (!templates.length) {
      render(list, h('div', { class: 'p-4 text-center text-sm text-base-content/50' }, 'No templates found'));
      return;
    }
    render(list, templates.map((t) =>
      h('div', {
        class: 'p-3 border-b border-base-300 last:border-b-0 cursor-pointer hover:bg-base-300 transition-colors',
        onclick: () => selectTemplate(t.name_hash),
      },
        h('div', { class: 'font-medium text-sm' }, t.user_friendly_name || t.name),
        t.description && h('div', { class: 'text-xs text-base-content/50 line-clamp-2 mt-0.5' }, t.description))));
  } catch (err) {
    toast(err.message, 'alert-error');
  }
}

async function selectTemplate(hash) {
  try {
    const tmpl = await sdk.sourceTemplateGet({ name_hash: hash });
    selectedTemplate = tmpl;
    // swap the modal from browse mode to a clean configure view
    $('addSourceTitle').textContent = `Configure ${tmpl.user_friendly_name || tmpl.name}`;
    $('sourceTabs').classList.add('hidden');
    $('templateSearch').classList.add('hidden');
    $('templateList').classList.add('hidden');
    $('templateParams').classList.remove('hidden');
    const nameInput = $('templateSourceName');
    const baseName = tmpl.user_friendly_name || tmpl.name || '';
    nameInput.value = baseName;
    render($('templateParamFields'),
      Object.entries(tmpl.parameters || {}).map(([key, param]) => templateParamField(key, param)));

    // Suggest a distinct name from the first required text parameter (e.g.
    // "Reddit Subreddit - selfhosted") until the user edits the name field,
    // so adding several sources from the same template doesn't collide.
    let nameEdited = false;
    nameInput.oninput = () => { nameEdited = true; };
    const firstParam = $('templateParamFields').querySelector('input[type="text"][required]');
    if (firstParam) {
      firstParam.addEventListener('input', () => {
        if (nameEdited) return;
        const v = firstParam.value.trim();
        nameInput.value = v ? `${baseName} - ${v}` : baseName;
      });
    }
  } catch (err) {
    toast(err.message, 'alert-error');
  }
}

// Renders one template parameter input. `current` (optional) prefills the
// field with a previously saved value when editing an existing source.
function templateParamField(key, param, current) {
  const label = param.title || param.name || key;
  let input;
  if (param.type === 'select' && param.options) {
    const selected = current != null && current !== '' ? current : param.default;
    input = h('select', { class: 'select select-bordered w-full', name: key, required: !!param.required },
      Object.entries(param.options).map(([value, text]) =>
        h('option', { value, selected: value === selected }, text || value)));
  } else if (param.type === 'checkbox') {
    const checked = current != null ? current === 'on' : param.default === 'checked';
    input = h('input', { type: 'checkbox', class: 'checkbox', name: key, checked });
  } else {
    input = h('input', {
      type: param.type === 'number' ? 'number' : 'text',
      class: 'input input-bordered w-full',
      name: key,
      value: current != null && current !== '' ? current : (param.default || ''),
      placeholder: param.example || '',
      required: !!param.required,
    });
  }
  return h('div', { class: 'form-control mb-3' },
    h('label', { class: 'label' },
      h('span', { class: 'label-text' }, label + (param.required ? ' *' : ''))),
    input);
}

function clearTemplateSelection() {
  selectedTemplate = null;
  $('addSourceTitle').textContent = 'Add Source';
  $('sourceTabs').classList.remove('hidden');
  $('templateSearch').classList.remove('hidden');
  $('templateList').classList.remove('hidden');
  $('templateParams').classList.add('hidden');
}

async function handleCreateSourceFromTemplate() {
  if (!selectedTemplate || !currentFeed) return;
  const name = $('templateSourceName').value.trim();
  if (!name) { toast('Please enter a source name', 'alert-error'); return; }

  const parameters = {};
  let missing = null;
  $('templateParamFields').querySelectorAll('.input-error').forEach((el) => el.classList.remove('input-error'));
  $('templateParamFields').querySelectorAll('input, select').forEach((el) => {
    const value = el.type === 'checkbox' ? (el.checked ? 'on' : '') : el.value.trim();
    if (el.required && !value && !missing) missing = el;
    parameters[el.name] = value;
  });
  if (missing) {
    missing.classList.add('input-error');
    missing.focus();
    const label = (selectedTemplate.parameters[missing.name] || {}).title || missing.name;
    toast(`"${label}" is required`, 'alert-error');
    return;
  }

  try {
    await sdk.sourceTemplateCreate({
      body: {
        source_template_name_hash: selectedTemplate.name_hash,
        feed_hash: currentFeed.feed_name_hash,
        source_name: name,
        parameters,
      },
    });
    closeModal('addSourceModal');
    toast(`Source "${name}" added`);
    loadSources();
    // the first ingest runs in the background; refresh to pick up its result
    setTimeout(loadSources, 5000);
  } catch (err) {
    toast(err.message, 'alert-error');
  }
}
