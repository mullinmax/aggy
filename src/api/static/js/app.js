// Aggy app views: dashboard (feed grid) and feed (articles + sources).
// Built on core.js (h/render/router) and the generated sdk.js.

'use strict';

const sdk = new AggySDK();

// ---------- state ----------
const PAGE_SIZE = 20;
let currentFeed = null;
let itemSkip = 0;
let lastItemBand = null; // sort-band of the last rendered item, for threshold dividers
// filter/sort state for the current feed; sources: null means "all sources"
const defaultFilters = () => ({ sort: 'predicted', includeRead: false, textOnly: '', sources: null });
let feedFilters = defaultFilters();
let feedSourceList = []; // sources of the current feed, for the filter panel
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
  $('renameFeedBtn').onclick = openRenameFeed;
  $('renameFeedForm').onsubmit = handleRenameFeed;
  $('manageSourcesBtn').onclick = () => switchFeedTab('sources');
  $('filterBtn').onclick = toggleFilterPanel;
  $('statsBtn').onclick = openStatsModal;
  $('rerankBtn').onclick = handleRerank;
  $('filterSort').onchange = (e) => { feedFilters.sort = e.target.value; reloadItems(); };
  $('filterMedia').onchange = (e) => { feedFilters.textOnly = e.target.value; reloadItems(); };
  $('filterIncludeRead').onchange = (e) => { feedFilters.includeRead = e.target.checked; reloadItems(); };
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

  // stop gifs/videos/embeds when the reader closes: emptying the media
  // host halts <video> playback and unloads youtube iframes
  $('readerModal').addEventListener('close', () => {
    render($('readerMedia'));
    updateGifPlayback();
  });

  // infinite scroll: when the load-more button scrolls near the viewport,
  // click it automatically
  new IntersectionObserver((entries) => {
    const btn = $('loadMoreBtn');
    if (entries.some((en) => en.isIntersecting) && !btn.classList.contains('hidden')) btn.click();
  }, { rootMargin: '600px' }).observe($('loadMoreBtn'));
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
  // summary line: total posts, unread, average posts/day (last 30 days)
  const stats = [];
  if (feed.feed_item_count != null) {
    stats.push(`${feed.feed_item_count} post${feed.feed_item_count === 1 ? '' : 's'}`);
    if (feed.feed_unread_count != null) stats.push(`${feed.feed_unread_count} unread`);
    if (feed.feed_posts_per_day != null) stats.push(`~${feed.feed_posts_per_day}/day`);
  }
  return h('div', {
    class: 'card bg-base-200 shadow-sm hover:shadow-md transition-shadow cursor-pointer border border-base-300 hover:border-primary',
    onclick: () => router.go(`feed/${feed.feed_name_hash}`),
  },
    h('div', { class: 'card-body p-5' },
      h('div', { class: 'badge badge-primary badge-outline font-bold text-lg p-3' },
        feed.feed_name.charAt(0).toUpperCase()),
      h('h2', { class: 'card-title text-base mt-2' }, feed.feed_name),
      stats.length ? h('div', { class: 'text-xs text-base-content/50' }, stats.join(' · ')) : null));
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

function openRenameFeed() {
  if (!currentFeed) return;
  $('renameFeedName').value = currentFeed.feed_name;
  showModal('renameFeedModal');
  $('renameFeedName').focus();
}

async function handleRenameFeed(e) {
  e.preventDefault();
  if (!currentFeed) return;
  const name = $('renameFeedName').value.trim();
  if (!name) return;
  if (name === currentFeed.feed_name) { closeModal('renameFeedModal'); return; }
  try {
    const feed = await sdk.feedRename({ feed_name_hash: currentFeed.feed_name_hash, new_name: name });
    closeModal('renameFeedModal');
    toast(`Feed renamed to "${name}"`);
    // the name_hash (and the feed's URL) changes on rename; drop the cached
    // feed and navigate to the new hash
    currentFeed = null;
    router.go(`feed/${feed.feed_name_hash}`);
  } catch (err) {
    toast(err.message, 'alert-error');
  }
}

// ---------- feed view ----------
async function showFeed(hash) {
  setView('feed');
  itemSkip = 0;
  render($('itemList'), spinner());

  if (!currentFeed || currentFeed.feed_name_hash !== hash) {
    feedFilters = defaultFilters();
    feedSourceList = [];
    $('filterPanel').classList.add('hidden');
    syncFilterControls();
  }

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
  // The filter only applies to the article list; hide the button (and any
  // open panel) on the sources/settings tab.
  $('filterBtn').classList.toggle('hidden', tab !== 'items');
  if (tab !== 'items') $('filterPanel').classList.add('hidden');
  if (tab === 'sources') loadSources();
}

// ---------- filters ----------
function syncFilterControls() {
  $('filterSort').value = feedFilters.sort;
  $('filterMedia').value = feedFilters.textOnly;
  $('filterIncludeRead').checked = feedFilters.includeRead;
}

function reloadItems() {
  itemSkip = 0;
  loadFeedItems();
}

async function toggleFilterPanel() {
  const panel = $('filterPanel');
  panel.classList.toggle('hidden');
  if (!panel.classList.contains('hidden') && !feedSourceList.length) {
    try {
      feedSourceList = await sdk.feedSources({ feed_name_hash: currentFeed.feed_name_hash });
    } catch { feedSourceList = []; }
    renderFilterSources();
  }
}

// Source checkboxes; all checked (sources: null) by default. Always read
// and re-render from feedFilters.sources so repeated toggles never work
// against a stale snapshot of the selection.
function renderFilterSources() {
  const selected = feedFilters.sources; // null = all
  // "Toggle all" checks/unchecks every source at once; only shown when the
  // feed has sources. Checked when all are selected (sources === null).
  const toggleAllLabel = $('filterSourcesToggleAllLabel');
  const toggleAll = $('filterSourcesToggleAll');
  if (toggleAllLabel && toggleAll) {
    toggleAllLabel.classList.toggle('hidden', !feedSourceList.length);
    toggleAll.checked = selected === null;
    toggleAll.onchange = (e) => {
      // Checking selects all (null); unchecking clears the selection.
      feedFilters.sources = e.target.checked ? null : [];
      renderFilterSources();
      reloadItems();
    };
  }
  render($('filterSources'),
    feedSourceList.length
      ? feedSourceList.map((s) =>
          h('label', { class: 'label cursor-pointer gap-1.5 py-0 px-2 border border-base-300 rounded-lg bg-base-100' },
            h('input', {
              type: 'checkbox', class: 'checkbox checkbox-xs checkbox-primary',
              checked: selected === null || selected.includes(s.source_name_hash),
              onchange: (e) => {
                const all = feedSourceList.map((x) => x.source_name_hash);
                let picked = feedFilters.sources === null ? all.slice() : feedFilters.sources.slice();
                if (e.target.checked) { if (!picked.includes(s.source_name_hash)) picked.push(s.source_name_hash); }
                else picked = picked.filter((hsh) => hsh !== s.source_name_hash);
                feedFilters.sources = picked.length === all.length ? null : picked;
                renderFilterSources();
                reloadItems();
              },
            }),
            h('span', {
              class: 'inline-block w-2 h-2 rounded-full',
              style: `background:${sourceColor(s.source_name, s.source_color)}`,
            }),
            h('span', { class: 'label-text text-xs' }, s.source_name)))
      : h('span', { class: 'text-xs text-base-content/40' }, 'No sources in this feed'));
}

// ---------- model stats ----------
function formatMetric(v, digits = 3) {
  return v == null ? '—' : Number(v).toFixed(digits);
}

// Human labels for the backend model names.
const MODEL_LABELS = {
  global_mean: 'Global mean (baseline)',
  source_mean: 'Source average',
  knn_embedding: 'Similar posts (kNN)',
  ridge: 'Linear model (ridge)',
  neural_net: 'Neural net',
};

function renderStats(stats) {
  const votes = stats.up_votes + stats.down_votes + stats.neutral_votes;
  const row = (m) =>
    h('tr', { class: m.chosen ? 'bg-primary/10' : '' },
      h('td', { class: 'text-sm' },
        MODEL_LABELS[m.model_name] || m.model_name,
        m.chosen ? h('span', { class: 'badge badge-primary badge-xs ml-2' }, 'in use') : null),
      h('td', { class: 'text-sm text-right' }, formatMetric(m.mae)),
      h('td', { class: 'text-sm text-right' }, formatMetric(m.rmse)),
      h('td', { class: 'text-sm text-right' },
        m.sign_accuracy == null ? '—' : `${Math.round(m.sign_accuracy * 100)}%`));

  render($('statsBody'),
    h('div', { class: 'stats stats-horizontal shadow-none border border-base-300 w-full mb-4' },
      h('div', { class: 'stat py-2' },
        h('div', { class: 'stat-title text-xs' }, 'Votes'),
        h('div', { class: 'stat-value text-lg' }, String(votes)),
        h('div', { class: 'stat-desc' }, `▲ ${stats.up_votes} · ● ${stats.neutral_votes} · ▼ ${stats.down_votes}`)),
      h('div', { class: 'stat py-2' },
        h('div', { class: 'stat-title text-xs' }, 'Articles ranked'),
        h('div', { class: 'stat-value text-lg' }, `${stats.predicted_items}/${stats.total_items}`))),
    stats.models.length
      ? h('div', { class: 'overflow-x-auto' },
          h('table', { class: 'table table-sm' },
            h('thead', {},
              h('tr', {},
                h('th', {}, 'Model'),
                h('th', { class: 'text-right', title: 'Mean absolute error (lower is better)' }, 'MAE'),
                h('th', { class: 'text-right', title: 'Root mean squared error (lower is better)' }, 'RMSE'),
                h('th', { class: 'text-right', title: 'How often the predicted vote direction matches yours' }, 'Direction'))),
            h('tbody', {}, stats.models.map(row))))
      : h('p', { class: 'text-sm text-base-content/50' },
          'No model stats yet — vote on a few articles, then hit "Recompute now".'));
}

async function openStatsModal() {
  showModal('statsModal');
  render($('statsBody'), spinner());
  try {
    renderStats(await sdk.feedRankingStats({ feed_name_hash: currentFeed.feed_name_hash }));
  } catch (err) {
    render($('statsBody'), h('p', { class: 'text-sm text-error' }, err.message));
  }
}

async function handleRerank() {
  const btn = $('rerankBtn');
  btn.disabled = true;
  btn.textContent = 'Computing…';
  try {
    renderStats(await sdk.feedRerank({ feed_name_hash: currentFeed.feed_name_hash }));
    reloadItems();
  } catch (err) {
    toast(err.message, 'alert-error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Recompute now';
  }
}

// ---------- items ----------
let itemsRequestSeq = 0; // discards out-of-order responses

// Threshold dividers: as you scroll a ranked feed, mark where the model's
// verdict crosses a meaningful line so a run of cards reads as labeled bands.
//
// For the predicted sorts, votes live on a -1..1 scale (down / neutral / up),
// so the midpoints +0.5 and -0.5 split "more likely an upvote" from "more
// likely neutral" from "more likely a downvote". For the confidence sorts we
// split the 0..1 confidence range into thirds. Each `band` maps an item to a
// zone; `labels` gives the divider text shown when entering that zone from the
// one above it (the very first zone in view never gets a divider).
function predictionBand(item) {
  const s = item.item_predicted_score;
  if (s == null) return null;
  if (s >= 0.5) return 'up';
  if (s >= -0.5) return 'neutral';
  return 'down';
}

function confidenceBand(item) {
  const c = item.item_predicted_confidence;
  if (c == null) return null;
  if (c >= 2 / 3) return 'high';
  if (c >= 1 / 3) return 'mid';
  return 'low';
}

const SORT_BANDS = {
  predicted: {
    band: predictionBand,
    labels: {
      neutral: 'More likely neutral than an upvote',
      down: 'More likely a downvote than neutral',
    },
  },
  predicted_asc: {
    band: predictionBand,
    labels: {
      neutral: 'More likely neutral than a downvote',
      up: 'More likely an upvote than neutral',
    },
  },
  controversial: {
    band: confidenceBand,
    labels: {
      mid: 'Middle third — model moderately unsure',
      high: 'Least controversial — model most confident',
    },
  },
  confident: {
    band: confidenceBand,
    labels: {
      mid: 'Model moderately confident',
      low: 'Model least confident',
    },
  },
};

// Horizontal rule with a centered note, marking a threshold in the sort order.
function sortDivider(text) {
  return h('div', { class: 'flex items-center gap-3 my-1 text-xs text-base-content/40 select-none' },
    h('div', { class: 'flex-1 border-t border-base-300' }),
    h('span', { class: 'whitespace-nowrap uppercase tracking-wide' }, text),
    h('div', { class: 'flex-1 border-t border-base-300' }));
}

// Append `item`'s card to `list`, first inserting a threshold divider when the
// item's sort-band differs from the previous card's. `lastItemBand` carries the
// band across paginated loads so dividers land correctly on infinite scroll.
function appendItemWithDivider(list, item) {
  const cfg = SORT_BANDS[feedFilters.sort];
  if (cfg) {
    const band = cfg.band(item);
    if (band) {
      if (lastItemBand && band !== lastItemBand && cfg.labels[band]) {
        list.append(sortDivider(cfg.labels[band]));
      }
      lastItemBand = band;
    }
  }
  list.append(itemCard(item));
}

async function loadFeedItems() {
  const seq = ++itemsRequestSeq;
  const list = $('itemList');
  if (itemSkip === 0) { render(list, spinner()); lastItemBand = null; }
  // hide while loading so the infinite-scroll observer can't double-fire
  $('loadMoreBtn').classList.add('hidden');

  try {
    const items = await sdk.feedItems({
      feed_name_hash: currentFeed.feed_name_hash,
      skip: itemSkip,
      limit: PAGE_SIZE,
      sort: feedFilters.sort,
      include_read: feedFilters.includeRead,
      sources: feedFilters.sources === null ? null : feedFilters.sources.join(','),
      text_only: feedFilters.textOnly === '' ? null : feedFilters.textOnly,
    });
    if (seq !== itemsRequestSeq) return; // a newer request superseded this one
    if (itemSkip === 0) render(list);

    if (!items.length && itemSkip === 0) {
      render(list, emptyState('\u{1F4F0}', 'No articles yet',
        'Add some sources and articles will appear here once ingested',
        h('button', { class: 'btn btn-primary btn-sm', onclick: openAddSourceModal }, '+ Add Source')));
      $('loadMoreBtn').classList.add('hidden');
      return;
    }

    items.forEach((item) => appendItemWithDivider(list, item));
    $('loadMoreBtn').classList.toggle('hidden', items.length < PAGE_SIZE);
  } catch (err) {
    if (seq !== itemsRequestSeq) return;
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

// ---------- source colors ----------

// Mirrors SOURCE_COLORS in db/source.py: sources created before colors
// existed get a deterministic fallback from the same palette.
const SOURCE_COLOR_PALETTE = [
  '#ef5350', '#ec407a', '#ab47bc', '#7e57c2', '#5c6bc0', '#42a5f5', '#26c6da',
  '#26a69a', '#66bb6a', '#9ccc65', '#d4b106', '#ffa726', '#ff7043', '#8d6e63',
];

function sourceColor(name, stored) {
  if (stored) return stored;
  let hash = 0;
  for (const ch of String(name || '')) hash = (hash * 31 + ch.codePointAt(0)) >>> 0;
  return SOURCE_COLOR_PALETTE[hash % SOURCE_COLOR_PALETTE.length];
}

function sourceBadge(name, storedColor) {
  if (!name) return null;
  const color = sourceColor(name, storedColor);
  return h('span', {
    class: 'badge badge-outline badge-xs',
    style: `border-color:${color};color:${color}`,
  }, name);
}

// "Open in new tab" icon (matches the modal close button's size/style),
// shown next to titles to open the source's original link.
function openInNewTabIcon() {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.8');
  svg.setAttribute('class', 'w-4 h-4');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('stroke-linecap', 'round');
  path.setAttribute('stroke-linejoin', 'round');
  path.setAttribute('d', 'M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 '
    + '005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25');
  svg.appendChild(path);
  return svg;
}

// "Open original" button, shown next to titles.
function openLinkButton(url, cls = 'btn btn-ghost btn-xs btn-square text-base-content/60') {
  if (!url) return null;
  return h('a', {
    class: cls, href: url, target: '_blank', rel: 'noopener', title: 'Open original',
    onclick: (e) => e.stopPropagation(),
  }, openInNewTabIcon());
}

// Bar-chart icon that opens the per-article "why recommended?" breakdown.
function explainButton(item) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.8');
  svg.setAttribute('class', 'w-4 h-4');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('stroke-linecap', 'round');
  path.setAttribute('stroke-linejoin', 'round');
  path.setAttribute('d', 'M4 20V10M10 20V4M16 20v-7M20 20H3');
  svg.appendChild(path);
  return h('button', {
    class: 'btn btn-ghost btn-xs btn-square text-base-content/60',
    title: 'Why is this recommended?',
    onclick: (e) => { e.stopPropagation(); openExplanationModal(item); },
  }, svg);
}

// ---------- media ----------

const isVideoFile = (url) => /\.(mp4|webm)(\?|$)/i.test(url || '');

// Video id for youtube watch/short/embed/youtu.be links, else null.
function youtubeId(url) {
  try {
    const u = new URL(url);
    const host = u.hostname.replace(/^www\.|^m\./, '');
    if (host === 'youtu.be') return u.pathname.slice(1).split('/')[0] || null;
    if (host === 'youtube.com' || host === 'youtube-nocookie.com') {
      if (u.pathname === '/watch') return u.searchParams.get('v');
      const m = u.pathname.match(/^\/(?:embed|shorts|live|v)\/([\w-]{6,})/);
      if (m) return m[1];
    }
  } catch { /* not a URL */ }
  return null;
}

function youtubeEmbed(id) {
  return h('div', { class: 'aspect-video w-full' },
    h('iframe', {
      class: 'w-full h-full', src: `https://www.youtube-nocookie.com/embed/${id}`,
      title: 'YouTube video player', loading: 'lazy', allowfullscreen: true,
      allow: 'accelerometer; encrypted-media; gyroscope; picture-in-picture',
    }));
}

// Gif playback policy: pause everything offscreen, and of the gifs on
// screen play only the topmost fully-visible one, so a feed full of gifs
// doesn't churn bandwidth and CPU or fight for attention.
const gifRatios = new Map(); // gif <video> -> latest intersection ratio

function updateGifPlayback() {
  // gifs in an open reader modal take priority over the feed behind it
  const readerOpen = Array.from(gifRatios.keys())
    .some((v) => v.isConnected && v.closest('dialog[open]'));
  let playing = null;
  for (const [video, ratio] of gifRatios) {
    if (!video.isConnected) { gifRatios.delete(video); continue; }
    if (readerOpen && !video.closest('dialog[open]')) continue;
    if (ratio < 0.98) continue; // fully visible only
    const top = video.getBoundingClientRect().top;
    if (!playing || top < playing.top) playing = { video, top };
  }
  // nothing fully visible (e.g. mid-scroll between gifs): fall back to the
  // most-visible one so playback doesn't stall
  if (!playing) {
    for (const [video, ratio] of gifRatios) {
      if (readerOpen && !video.closest('dialog[open]')) continue;
      if (ratio > 0.5 && (!playing || ratio > playing.ratio)) playing = { video, ratio };
    }
  }
  gifRatios.forEach((_, video) => {
    if (playing && video === playing.video) video.play().catch(() => {});
    else video.pause();
  });
}

const gifVisibility = new IntersectionObserver((entries) => {
  entries.forEach((en) => gifRatios.set(en.target, en.intersectionRatio));
  updateGifPlayback();
}, { threshold: [0, 0.25, 0.5, 0.75, 0.98, 1] });

// Which gif is "topmost" can change while scrolling without crossing an
// intersection threshold; re-evaluate on scroll (rAF-throttled).
let gifScrollTick = false;
document.addEventListener('scroll', () => {
  if (gifScrollTick || !gifRatios.size) return;
  gifScrollTick = true;
  requestAnimationFrame(() => { gifScrollTick = false; updateGifPlayback(); });
}, { passive: true, capture: true });

// Preview card for a "link" media entry: a reddit post that points off-site.
// Clicking opens the destination directly (stopPropagation) rather than the
// reader, and it surfaces a link that would otherwise stay buried in the post.
function linkCard(m) {
  let host = m.domain || '';
  if (!host) { try { host = new URL(m.url).hostname.replace(/^www\./, ''); } catch { /* leave blank */ } }
  return h('a', {
    class: 'flex items-stretch gap-3 bg-base-100 hover:bg-base-300 transition-colors',
    href: m.url, target: '_blank', rel: 'noopener',
    onclick: (e) => e.stopPropagation(),
  },
    m.poster
      ? h('img', {
          src: m.poster, alt: '', loading: 'lazy',
          class: 'w-24 sm:w-32 flex-none object-cover bg-base-300',
          onerror: (e) => e.target.remove(),
        })
      : null,
    h('div', { class: 'flex flex-col justify-center gap-1 min-w-0 py-3 px-3' },
      h('div', { class: 'flex items-center gap-1.5 text-xs font-medium text-base-content/60' },
        openInNewTabIcon(), h('span', { class: 'truncate' }, host || 'External link')),
      h('div', { class: 'text-sm text-primary break-all line-clamp-2' }, m.url)));
}

// One media entry ({type, url, poster?}) -> element. Gifs autoplay muted
// and loop like the reddit app; videos get controls, so their clicks must
// reach the player instead of opening the reader.
function mediaElement(m, cls = 'w-full max-h-[70vh] object-contain') {
  // reddit link posts point off-site: show a preview card, not a media frame
  if (m.type === 'link') return linkCard(m);
  // third-party players (e.g. redgifs) embed as an iframe; their clicks
  // never bubble, so they don't open the reader
  if (m.type === 'embed') {
    return h('div', { class: 'aspect-video w-full' },
      h('iframe', {
        class: 'w-full h-full', src: m.url, loading: 'lazy',
        allowfullscreen: true, allow: 'autoplay; fullscreen; picture-in-picture',
      }));
  }
  if (m.type === 'video' || (m.type === 'gif' && isVideoFile(m.url))) {
    const isGif = m.type === 'gif';
    const video = h('video', {
      class: cls, src: m.url, poster: m.poster || null,
      loop: isGif, autoplay: isGif, controls: !isGif,
      playsinline: true, preload: isGif ? 'auto' : 'metadata',
      onclick: isGif ? null : (e) => e.stopPropagation(),
    });
    // autoplay is only allowed when the muted IDL property is set; the
    // attribute alone isn't enough in Chrome
    video.muted = true;
    if (isGif) gifVisibility.observe(video);
    return video;
  }
  return h('img', { class: cls, src: m.url, alt: '', loading: 'lazy' });
}

// A media list -> single element or a swipeable snap-scrolling gallery
// strip with an index badge.
function mediaGallery(mediaList) {
  if (mediaList.length === 1) return mediaElement(mediaList[0]);
  const counter = h('div', {
    class: 'badge badge-neutral badge-sm absolute top-2 right-2 pointer-events-none',
  }, `1/${mediaList.length}`);
  const strip = h('div', { class: 'flex overflow-x-auto snap-x snap-mandatory' },
    mediaList.map((m) =>
      h('div', { class: 'w-full flex-none snap-center flex items-center justify-center bg-base-300' },
        mediaElement(m))));
  strip.addEventListener('scroll', () => {
    const index = Math.min(Math.round(strip.scrollLeft / strip.clientWidth) + 1, mediaList.length);
    counter.textContent = `${index}/${mediaList.length}`;
  }, { passive: true });
  return h('div', { class: 'relative' }, strip, counter);
}

// Reddit-app-style card: meta row and title up top, full-feed-width media
// below, then the vote row.
function itemCard(item) {
  const published = item.item_date_published ? timeAgo(item.item_date_published) : '';
  const ytId = youtubeId(item.item_url);
  const media = !ytId && (item.item_media || []).length ? item.item_media : null;
  const imageUrl = ytId || media ? null : (item.item_image_url || parseItemContent(item).imageUrl);
  const excerpt = cleanExcerpt(item);

  const mediaBlock = ytId
    ? h('figure', { class: 'bg-base-300' }, youtubeEmbed(ytId))
    : media
    ? h('figure', { class: 'bg-base-300' }, mediaGallery(media))
    : imageUrl
      ? h('figure', { class: 'bg-base-300' },
          h('img', {
            src: imageUrl, class: 'w-full max-h-[70vh] object-contain', alt: '', loading: 'lazy',
            onerror: (e) => { e.target.closest('figure').remove(); },
          }))
      : null;

  const voteClass = (score) => (score > 0 ? 'text-success' : score < 0 ? 'text-error' : 'text-warning');
  const voteButton = (label, score, title) =>
    h('button', {
      class: `btn btn-ghost btn-sm px-4${item.item_user_score === score ? ` ${voteClass(score)}` : ''}`,
      'data-score': String(score),
      title,
      onclick: (e) => { e.stopPropagation(); voteItem(item, score, e.currentTarget); },
    }, label);

  // model's take on this article, when a prediction exists
  const predicted = item.item_predicted_score;
  const predictedBadge = predicted != null
    ? h('span', {
        class: 'badge badge-ghost badge-xs text-base-content/50',
        title: `Predicted vote ${predicted.toFixed(2)} · confidence ${((item.item_predicted_confidence ?? 0) * 100).toFixed(0)}%`,
      }, `${predicted > 0 ? '+' : ''}${(predicted * 100).toFixed(0)}% match`)
    : null;

  return h('div', {
    class: 'card bg-base-200 border border-base-300 hover:border-primary/50 transition-colors cursor-pointer overflow-hidden',
    onclick: () => openReader(item),
  },
    h('div', { class: 'px-4 pt-3 pb-2' },
      h('div', { class: 'flex items-start gap-2' },
        h('h3', { class: 'font-semibold leading-snug flex-1 min-w-0 line-clamp-2' }, item.item_title || 'Untitled'),
        explainButton(item),
        openLinkButton(item.item_url)),
      !mediaBlock && excerpt && h('p', { class: 'text-xs text-base-content/50 line-clamp-2 mt-1' }, excerpt)),
    mediaBlock,
    h('div', { class: 'flex items-center gap-1 px-2 py-1.5' },
      h('div', { class: 'flex flex-wrap items-center gap-2 text-xs text-base-content/50 min-w-0 pl-2' },
        sourceBadge(item.item_source_name, item.item_source_color),
        item.item_author && h('span', { class: 'truncate max-w-32' }, item.item_author),
        published && h('span', { class: 'whitespace-nowrap' }, published),
        predictedBadge),
      h('div', { class: 'flex items-center gap-1 ml-auto' },
        voteButton('▲', 1, 'Upvote'),
        voteButton('●', 0, 'Neutral — seen it, no strong feelings'),
        voteButton('▼', -1, 'Downvote'))));
}

// ---------- why recommended ----------

// A field's contribution rendered as up to two green "+" or red "−" marks,
// or a muted dash when it had no measurable effect on the prediction.
function contributionMarks(sign, level) {
  if (!level || !sign) return h('span', { class: 'text-base-content/30' }, '·');
  const symbol = sign > 0 ? '+' : '−';
  const cls = sign > 0 ? 'text-success' : 'text-error';
  return h('span', { class: `font-bold ${cls}` }, symbol.repeat(level));
}

function renderExplanation(data) {
  const rows = data.fields.map((f) =>
    h('div', { class: 'flex items-center justify-between py-1.5 border-b border-base-300 last:border-b-0' },
      h('span', { class: 'text-sm' }, f.label),
      h('span', { class: 'text-lg leading-none tracking-widest' }, contributionMarks(f.sign, f.level))));

  const pct = Math.round(data.baseline_score * 100);
  render($('explainBody'),
    h('div', { class: 'flex flex-col' }, rows),
    h('p', { class: 'text-xs text-base-content/50 mt-4' },
      `Predicted match ${pct > 0 ? '+' : ''}${pct}% · model: ${MODEL_LABELS[data.model_name] || data.model_name}`));
}

async function openExplanationModal(item) {
  showModal('explainModal');
  render($('explainBody'), spinner());
  try {
    renderExplanation(await sdk.feedItemExplanation({
      feed_name_hash: currentFeed.feed_name_hash,
      item_url_hash: item.item_hash,
    }));
  } catch (err) {
    render($('explainBody'), h('p', { class: 'text-sm text-base-content/60' }, err.message));
  }
}

// Animate a voted card shrinking away, then drop it from the DOM.
function collapseCard(card) {
  card.style.height = `${card.offsetHeight}px`;
  card.style.overflow = 'hidden';
  requestAnimationFrame(() => {
    card.style.transition = 'height 0.3s ease, opacity 0.3s ease';
    card.style.height = '0px';
    card.style.opacity = '0';
    card.style.pointerEvents = 'none';
  });
  setTimeout(() => card.remove(), 320);
}

async function voteItem(item, score, btn) {
  try {
    await sdk.itemSetState({
      feed_hash: currentFeed.feed_name_hash,
      item_url_hash: item.item_hash,
      score,
      is_read: true,
    });
    item.item_user_score = score;
    btn.parentElement.querySelectorAll('button').forEach((b) =>
      b.classList.remove('text-success', 'text-error', 'text-warning'));
    btn.classList.add(score > 0 ? 'text-success' : score < 0 ? 'text-error' : 'text-warning');
    // voted items leave the feed unless the user opted to keep them visible
    if (!feedFilters.includeRead) {
      const card = btn.closest('.card');
      if (card) collapseCard(card);
    }
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

  $('readerOpenLink').href = item.item_url;

  render($('readerMeta'),
    sourceBadge(item.item_source_name, item.item_source_color),
    item.item_author && h('span', {}, `by ${item.item_author}`),
    item.item_date_published && h('span', {}, timeAgo(item.item_date_published)),
    item.item_domain && h('span', { class: 'ml-auto' }, item.item_domain));

  // YouTube links embed the actual player; ingested media (gifs, videos,
  // galleries) takes the hero slot. Otherwise non-reddit articles keep
  // their images inline in the content and only reddit-style posts promote
  // a content image to the hero.
  const ytId = youtubeId(item.item_url);
  const media = ytId ? [] : item.item_media || [];
  const heroUrl = ytId || media.length
    ? null
    : item.item_image_url || (parsed.isReddit ? parsed.imageUrl : null);
  const mediaHost = $('readerMedia');
  if (ytId) {
    render(mediaHost, youtubeEmbed(ytId));
    // the content's thumbnails would just duplicate the player
    parsed.root.querySelectorAll('img').forEach((img) => (img.closest('a') || img).remove());
  } else if (media.length) {
    render(mediaHost, mediaGallery(media));
  } else if (heroUrl) {
    render(mediaHost, h('img', {
      src: heroUrl, class: 'rounded-lg max-w-full max-h-[60vh] object-contain mx-auto',
      alt: '', onerror: (e) => e.target.remove(),
    }));
  } else {
    render(mediaHost);
  }

  // item_content is sanitized server-side (bleach) before storage; it is the
  // only place raw HTML is intentionally rendered.
  if (parsed.isReddit) {
    // the hero media above already shows the content image
    stripRedditBoilerplate(parsed.root, media.length > 0 || parsed.imageFromContent);
  }
  if (parsed.root.textContent.trim() || parsed.root.querySelector('img')) {
    $('readerContent').innerHTML = parsed.root.innerHTML;
  } else if (!heroUrl && !media.length) {
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

// "60" -> "every hour", "1440" -> "daily" — for the source list row.
function intervalLabel(mins) {
  if (!mins) return '';
  if (mins % 1440 === 0) { const days = mins / 1440; return days === 1 ? 'daily' : `every ${days} days`; }
  if (mins % 60 === 0) { const hours = mins / 60; return hours === 1 ? 'hourly' : `every ${hours} hours`; }
  return `every ${mins} min`;
}

function sourceRow(source) {
  const count = source.source_item_count ?? 0;
  const checked = source.source_last_ingested_at
    ? `checked ${timeAgo(source.source_last_ingested_at)}`
    : 'not checked yet';
  const interval = intervalLabel(source.source_ingest_interval_minutes);
  return h('div', { class: 'flex items-center justify-between gap-3 p-3 bg-base-200 border border-base-300 rounded-lg mb-2' },
    h('div', { class: 'min-w-0' },
      h('div', { class: 'font-medium text-sm flex items-center gap-2' },
        h('span', {
          class: 'inline-block w-2.5 h-2.5 rounded-full flex-shrink-0',
          style: `background:${sourceColor(source.source_name, source.source_color)}`,
        }),
        source.source_name),
      h('div', { class: 'text-xs text-base-content/40 truncate' }, source.source_url),
      h('div', { class: 'text-xs text-base-content/60 mt-1' },
        `${count} article${count === 1 ? '' : 's'} · ${checked}${interval ? ` · checks ${interval}` : ''}`),
      source.source_last_ingest_error && h('div', { class: 'text-xs text-error mt-1' },
        `Last check failed: ${source.source_last_ingest_error}`)),
    h('div', { class: 'flex gap-1 flex-shrink-0' },
      h('button', {
        class: 'btn btn-ghost btn-xs',
        title: 'Show only this source in the feed',
        onclick: () => viewSourceInFeed(source),
      }, 'View'),
      h('button', {
        class: 'btn btn-ghost btn-xs',
        title: 'Re-collect images, content and previews for this source',
        onclick: (e) => rescrapeSource(source, e.currentTarget),
      }, 'Re-scrape'),
      h('button', {
        class: 'btn btn-ghost btn-xs',
        onclick: () => openEditSourceModal(source),
      }, 'Edit'),
      h('button', {
        class: 'btn btn-ghost btn-xs text-error',
        onclick: () => confirmDeleteSource(source),
      }, 'Remove')));
}

// Jump to the article list showing only this source, by seeding the source
// filter with just this one and switching back to the items tab.
function viewSourceInFeed(source) {
  feedFilters.sources = [source.source_name_hash];
  syncFilterControls();
  renderFilterSources();
  itemSkip = 0;
  switchFeedTab('items');
  loadFeedItems();
}

// Ask the API to re-collect content/images/previews (and regenerate
// embeddings) for this source's existing items, without re-ingesting the feed.
async function rescrapeSource(source, btn) {
  btn.disabled = true;
  const original = btn.textContent;
  btn.textContent = 'Re-scraping…';
  try {
    await sdk.sourceRescrape({
      feed_name_hash: currentFeed.feed_name_hash,
      source_name_hash: source.source_name_hash,
    });
    toast(`Re-scraping "${source.source_name}" — this runs in the background`);
  } catch (err) {
    toast(err.message, 'alert-error');
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}

async function openEditSourceModal(source) {
  editingSource = source;
  editingTemplate = null;
  $('editSourceTitle').textContent = `Edit ${source.source_name}`;
  $('editSourceName').value = source.source_name;
  $('editSourceColor').value = sourceColor(source.source_name, source.source_color);

  // custom intervals (set via the API) get their own option so they survive
  // a save that doesn't touch the frequency
  const intervalSelect = $('editSourceInterval');
  const saved = source.source_ingest_interval_minutes;
  if (saved && !Array.from(intervalSelect.options).some((o) => o.value === String(saved))) {
    intervalSelect.append(h('option', { value: String(saved) }, `Every ${saved} minutes`));
  }
  intervalSelect.value = saved ? String(saved) : '';

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

  const intervalValue = $('editSourceInterval').value;
  const body = {
    feed_name_hash: currentFeed.feed_name_hash,
    source_name_hash: editingSource.source_name_hash,
    source_name: name,
    source_color: $('editSourceColor').value,
    // null resets the source to the server default frequency
    ingest_interval_minutes: intervalValue ? Number(intervalValue) : null,
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

    // Suggest a distinct name from the first required text parameter until
    // the user edits the name field, so adding several sources from the same
    // template doesn't collide. Reddit sources read best as "r/name" and
    // "u/name"; other templates get "Template - value".
    let nameEdited = false;
    nameInput.oninput = () => { nameEdited = true; };
    const firstParam = $('templateParamFields').querySelector('input[type="text"][required]');
    if (firstParam) {
      const suggestName = (value) => {
        if (!value) return baseName;
        if (firstParam.name === 'subreddit') return `r/${value.replace(/^\/?r\//i, '')}`;
        if (firstParam.name === 'username' && /reddit/i.test(baseName)) return `u/${value.replace(/^\/?u\//i, '')}`;
        return `${baseName} - ${value}`;
      };
      firstParam.addEventListener('input', () => {
        if (nameEdited) return;
        nameInput.value = suggestName(firstParam.value.trim());
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
