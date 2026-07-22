// Aggy app views: dashboard (feed grid) and feed (articles + sources).
// Built on core.js (h/render/router) and the generated sdk.js.

'use strict';

const sdk = new AggySDK();

// ---------- state ----------
const PAGE_SIZE = 20;
let currentFeed = null;
let currentList = null; // the list being browsed in the list-detail view
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
    .add('list/:hash', ({ hash }) => showList(hash))
    .start();
});

function bindControls() {
  $('logoutBtn').onclick = () => { auth.clear(); location.href = '/login'; };
  $('newFeedBtn').onclick = () => showModal('createFeedModal');
  $('createFeedForm').onsubmit = handleCreateFeed;

  $('importBtn').onclick = openImportModal;
  $('importParseBtn').onclick = handleImportParse;
  $('importCopyScriptBtn').onclick = copyImportScript;
  $('importBackBtn').onclick = () => setImportStep('input');
  $('importCreateBtn').onclick = handleImportCreate;
  $('importSelectAll').onchange = (e) => {
    importState.candidates.forEach((c) => { if (!c.error) c.selected = e.target.checked; });
    renderImportCandidates();
  };
  $('importAssignApplyBtn').onclick = applyImportFeedToSelected;
  $('importNewFeedBtn').onclick = createImportFeed;
  $('importGroupFeedsBtn').onclick = createImportFeedsFromGroups;

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
  $('srcTabAnalyze').onclick = () => switchSourceTab('analyze');
  $('srcTabFeed').onclick = () => switchSourceTab('feed');
  $('analyzeForm').onsubmit = handleAnalyzeWebsite;
  $('analyzeBackBtn').onclick = resetAnalyzeTab;
  $('analyzeAddBtn').onclick = handleCreateAnalyzedSource;
  $('templateSearch').oninput = debounce(searchTemplates, 300);
  $('templateBackBtn').onclick = clearTemplateSelection;
  $('templateAddBtn').onclick = handleCreateSourceFromTemplate;
  $('editSourceSaveBtn').onclick = handleUpdateSource;

  $('createListForm').onsubmit = handleCreateList;
  $('listSaveBtn').onclick = handleListSave;
  $('deleteListBtn').onclick = confirmDeleteList;

  // stop gifs/videos/embeds when the reader closes: destroy the youtube
  // player first (halts audio, clears its timers), then empty the media host
  // to unload any <video>/iframe
  $('readerModal').addEventListener('close', () => {
    destroyPlayersIn($('readerMedia'));
    render($('readerMedia'));
    updateGifPlayback();
  });

  // infinite scroll: when the load-more button scrolls near the viewport,
  // click it automatically
  new IntersectionObserver((entries) => {
    const btn = $('loadMoreBtn');
    if (entries.some((en) => en.isIntersecting) && !btn.classList.contains('hidden')) btn.click();
  }, { rootMargin: '600px' }).observe($('loadMoreBtn'));

  setupAutoHideNav();
}

// Hide-on-scroll navbar: tuck it away when scrolling down, bring it back when
// scrolling up (and always show it near the very top). A small threshold keeps
// tiny/jittery scrolls from flickering it.
function setupAutoHideNav() {
  const nav = $('appNavbar');
  if (!nav) return;
  let lastY = window.scrollY;
  let ticking = false;
  const THRESHOLD = 8;
  const update = () => {
    ticking = false;
    const y = Math.max(0, window.scrollY);
    if (Math.abs(y - lastY) < THRESHOLD) return;
    // near the top, or scrolling up -> show; scrolling down past the bar -> hide
    const hide = y > nav.offsetHeight && y > lastY;
    nav.classList.toggle('-translate-y-full', hide);
    lastY = y;
  };
  window.addEventListener('scroll', () => {
    if (!ticking) { ticking = true; requestAnimationFrame(update); }
  }, { passive: true });
}

function setView(name) {
  $('viewDashboard').classList.toggle('hidden', name !== 'dashboard');
  $('viewFeed').classList.toggle('hidden', name !== 'feed');
  $('viewList').classList.toggle('hidden', name !== 'list');
  // never leave the navbar tucked away when switching views
  $('appNavbar')?.classList.remove('-translate-y-full');
}

// ---------- dashboard ----------
function showDashboard() {
  setView('dashboard');
  currentFeed = null;
  currentList = null;
  loadFeeds();
  loadLists();
}

// The lists section only appears once the user has at least one list; lists
// are created by bookmarking articles from a feed.
async function loadLists() {
  const section = $('listsSection');
  const grid = $('listGrid');
  try {
    const lists = await sdk.listList({});
    if (!lists.length) { section.classList.add('hidden'); return; }
    section.classList.remove('hidden');
    render(grid, lists.map(listCard));
  } catch {
    section.classList.add('hidden');
  }
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
      h('div', { class: 'card-actions flex-col gap-2' },
        h('button', {
          class: 'btn btn-primary w-full',
          onclick: () => { onboardingContinue = true; showModal('createFeedModal'); $('newFeedName').focus(); },
        }, 'Create your first feed'),
        h('button', { class: 'btn btn-ghost btn-sm w-full', onclick: openImportModal },
          'or import your Reddit / YouTube / Bluesky subscriptions'))));
}

function feedCard(feed) {
  // summary line: unread count (or total when nothing's unread) + posts/day
  const stats = [];
  if (feed.feed_item_count != null) {
    if (feed.feed_unread_count) stats.push(`${feed.feed_unread_count} unread`);
    else stats.push(`${feed.feed_item_count} post${feed.feed_item_count === 1 ? '' : 's'}`);
    if (feed.feed_posts_per_day != null) stats.push(`~${feed.feed_posts_per_day}/day`);
  }
  return h('div', {
    class: 'card bg-base-200 border border-base-300 hover:border-primary transition-colors cursor-pointer',
    onclick: () => router.go(`feed/${feed.feed_name_hash}`),
  },
    h('div', { class: 'card-body p-3 gap-1' },
      h('h2', { class: 'font-semibold text-sm leading-snug line-clamp-2' }, feed.feed_name),
      stats.length ? h('div', { class: 'text-xs text-base-content/50 truncate' }, stats.join(' · ')) : null));
}

// Compact card for a saved list, mirroring the feed cards but visually
// distinct (a bookmark glyph + secondary hover accent).
function listCard(list) {
  const count = list.list_item_count ?? 0;
  return h('div', {
    class: 'card bg-base-200 border border-base-300 hover:border-secondary transition-colors cursor-pointer',
    onclick: () => router.go(`list/${list.list_name_hash}`),
  },
    h('div', { class: 'card-body p-3 gap-1' },
      h('h2', { class: 'font-semibold text-sm leading-snug line-clamp-2' }, list.list_name),
      h('div', { class: 'text-xs text-base-content/50 truncate' },
        `${count} item${count === 1 ? '' : 's'}`)));
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
  currentList = null; // leaving any list-detail context
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

// ---------- list detail view ----------
// A list browses like a feed's article list, but with no recommendation
// engine: no sort/filter, model stats, predictions, or vote buttons — just
// the saved articles, newest-added first.
async function showList(hash) {
  setView('list');
  currentFeed = null; // no feed context: the reader won't record vote state
  render($('listItemList'), spinner());

  if (!currentList || currentList.list_name_hash !== hash) {
    try {
      currentList = await sdk.listGet({ list_name_hash: hash });
    } catch (err) {
      toast(err.message, 'alert-error');
      router.go('');
      return;
    }
  }

  $('listTitle').textContent = currentList.list_name;
  $('listBreadcrumb').textContent = currentList.list_name;
  loadListItems();
}

async function loadListItems() {
  const list = $('listItemList');
  render(list, spinner());
  try {
    const items = await sdk.listItems({ list_name_hash: currentList.list_name_hash });
    if (!items.length) {
      render(list, emptyState('\u{1F516}', 'This list is empty',
        'Save articles to this list from any feed with the bookmark button.'));
      return;
    }
    render(list);
    items.forEach((item) => list.append(itemCard(item, { listMode: true })));
  } catch (err) {
    render(list, h('div', { class: 'text-center py-16 text-base-content/50' }, 'Failed to load list'));
    toast(err.message, 'alert-error');
  }
}

function confirmDeleteList() {
  if (!currentList) return;
  confirmDialog({
    title: 'Delete List',
    message: `Delete "${currentList.list_name}"? The articles stay in their feeds; only the list is removed.`,
    action: 'Delete List',
    onConfirm: async () => {
      await sdk.listDelete({ list_name_hash: currentList.list_name_hash });
      currentList = null;
      toast('List deleted');
      router.go('');
    },
  });
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
  logistic: 'Logistic regression',
  svr: 'Support vector regression',
  random_forest: 'Random forest',
  gradient_boost: 'Gradient boosting',
  neural_net: 'Neural net (shallow)',
  deep_neural_net: 'Deep neural net',
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

// ---------- youtube player (Plyr + SponsorBlock) ----------

// Local sprite: Plyr's default iconUrl points at its CDN, which the app
// can't rely on (and shouldn't, being self-hosted). Ships in /static/vendor.
const PLYR_SPRITE_URL = '/static/vendor/plyr.svg';

// SponsorBlock categories auto-skipped by default: paid sponsors, unpaid
// self-promotion, and subscribe/like reminders — the extension's default
// "skip" set. Intro/outro/music are deliberately left alone.
const SPONSORBLOCK_CATEGORIES = ['sponsor', 'selfpromo', 'interaction'];
const SPONSORBLOCK_API = 'https://sponsor.ajay.app/api/skipSegments';

// Human-readable segment names for the countdown chip.
const SPONSOR_LABELS = {
  sponsor: 'sponsor',
  selfpromo: 'self promotion',
  interaction: 'interaction reminder',
};

// videoId -> Promise<[{start, end, category}]>. Cached for the page so many
// feed cards (or a revisit) don't re-hit the API, which asks not to be abused.
const sponsorCache = new Map();

function fetchSponsorSegments(videoId) {
  if (sponsorCache.has(videoId)) return sponsorCache.get(videoId);
  const cats = encodeURIComponent(JSON.stringify(SPONSORBLOCK_CATEGORIES));
  const url = `${SPONSORBLOCK_API}?videoID=${encodeURIComponent(videoId)}&categories=${cats}`;
  // 404 = "no segments for this video"; network errors -> behave as none.
  const p = fetch(url)
    .then((r) => (r.ok ? r.json() : []))
    .then((rows) => (Array.isArray(rows) ? rows : [])
      .map((row) => ({ start: row.segment[0], end: row.segment[1], category: row.category }))
      .filter((s) => Number.isFinite(s.start) && Number.isFinite(s.end) && s.end > s.start)
      .sort((a, b) => a.start - b.start))
    .catch(() => []);
  sponsorCache.set(videoId, p);
  return p;
}

// Fullscreen orientation: force landscape on the way in (so it rotates even
// when the phone's auto-rotate is off), release it again on the way out.
// Best-effort — the Screen Orientation API isn't everywhere and lock() only
// works while fullscreen; on iOS the native video fullscreen handles rotation.
function lockLandscape() {
  try { screen.orientation?.lock?.('landscape')?.catch?.(() => {}); } catch { /* unsupported */ }
}
function unlockOrientation() {
  try { screen.orientation?.unlock?.(); } catch { /* unsupported */ }
}

// Only build the real player when a card nears the viewport, mirroring the
// old loading="lazy" iframes so a feed full of videos doesn't spin up dozens
// of players at once.
const ytPlayerObserver = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    ytPlayerObserver.unobserve(entry.target);
    initYouTubePlayer(entry.target);
  }
}, { rootMargin: '300px' });

// A YouTube video id -> placeholder element that upgrades itself into a full
// Plyr player (skip buttons, real fullscreen, SponsorBlock) once on screen.
function youtubeEmbed(id) {
  const wrap = h('div', {
    class: 'aggy-player relative w-full',
    // in the feed the card opens the reader on click; player clicks are its own
    onclick: (e) => e.stopPropagation(),
  });
  wrap.dataset.videoId = id;
  // 16:9 poster + play glyph so the box isn't blank (and doesn't shift)
  // before the player initialises. Plyr provides its own ratio afterwards.
  wrap.append(
    h('div', { class: 'aspect-video w-full bg-black relative overflow-hidden' },
      h('img', {
        class: 'absolute inset-0 w-full h-full object-cover',
        src: `https://i.ytimg.com/vi/${id}/hqdefault.jpg`, alt: '', loading: 'lazy',
        onerror: (e) => e.target.remove(),
      }),
      h('div', { class: 'absolute inset-0 grid place-items-center pointer-events-none' },
        h('div', { class: 'aggy-play-badge' }))));
  ytPlayerObserver.observe(wrap);
  return wrap;
}

function initYouTubePlayer(wrap) {
  if (wrap._plyr) return;
  const id = wrap.dataset.videoId;
  const embed = h('div', { 'data-plyr-provider': 'youtube', 'data-plyr-embed-id': id });
  render(wrap, embed); // drop the poster, hand the box to Plyr

  // library missing (offline shell without vendor JS): plain nocookie iframe
  if (typeof Plyr === 'undefined') {
    render(wrap, h('div', { class: 'aspect-video w-full' },
      h('iframe', {
        class: 'w-full h-full', src: `https://www.youtube-nocookie.com/embed/${id}`,
        title: 'YouTube video player', loading: 'lazy', allowfullscreen: true,
        allow: 'accelerometer; encrypted-media; gyroscope; picture-in-picture',
      })));
    return;
  }

  const player = new Plyr(embed, {
    iconUrl: PLYR_SPRITE_URL,
    controls: ['play-large', 'rewind', 'play', 'fast-forward', 'progress',
      'current-time', 'mute', 'volume', 'settings', 'fullscreen'],
    settings: ['quality', 'speed'],
    ratio: '16:9',
    youtube: { noCookie: true, rel: 0, modestbranding: 1, playsinline: 1 },
    fullscreen: { enabled: true, iosNative: true },
    storage: { enabled: false },
  });
  wrap._plyr = player;
  player.on('ready', () => setupPlayerOverlays(player, id));
}

// SponsorBlock auto-skip + fullscreen skip zones, both living inside Plyr's
// container so they show (and rotate) in fullscreen too.
function setupPlayerOverlays(player, id) {
  const container = player.elements.container;

  // Force landscape in fullscreen, release it on the way out, and flag the
  // container so the tap-to-skip zones only arm while fullscreen.
  player.on('enterfullscreen', () => { container.classList.add('aggy-fs'); lockLandscape(); });
  player.on('exitfullscreen', () => { container.classList.remove('aggy-fs'); unlockOrientation(); });

  // --- SponsorBlock ---------------------------------------------------------
  // Segments load on first play so idle feed cards don't hit the API. Each is
  // skipped only after a 5s countdown the viewer can cancel by tapping.
  let segments = null;
  const cancelled = new Set(); // segments the viewer chose to keep
  const loadSegments = () => {
    if (segments !== null) return;
    segments = []; // guard against a second fetch while the first is in flight
    fetchSponsorSegments(id).then((s) => { segments = s; });
  };
  player.on('playing', loadSegments);

  // Countdown chip: appears ~5s before a skip, tap to cancel that skip.
  let chipSeg = null;
  const chipText = h('span', {});
  const chip = h('button', {
    type: 'button', class: 'aggy-sb-chip hidden', title: 'Tap to cancel the skip',
    onclick: (e) => { e.stopPropagation(); if (chipSeg) cancelled.add(chipSeg); hideChip(); },
  }, chipText, h('span', { class: 'aggy-sb-chip-hint' }, 'tap to cancel'));
  const showChip = (seg, secs) => {
    chipSeg = seg;
    const label = SPONSOR_LABELS[seg.category] || seg.category;
    chipText.textContent = `Skipping ${label} in ${secs}s`;
    chip.classList.remove('hidden');
  };
  const hideChip = () => { chipSeg = null; chip.classList.add('hidden'); };

  player.on('timeupdate', () => {
    if (!segments || !segments.length) return hideChip();
    const t = player.currentTime;
    let upcoming = null;
    for (const seg of segments) {
      if (seg.end - 0.15 <= t) continue;   // already behind us
      if (cancelled.has(seg)) continue;    // viewer opted to keep it
      if (t >= seg.start) {                // inside the segment -> skip now
        player.currentTime = seg.end;
        return hideChip();
      }
      upcoming = seg;                       // first still-pending segment ahead
      break;
    }
    if (upcoming && upcoming.start - t <= 5) showChip(upcoming, Math.max(1, Math.ceil(upcoming.start - t)));
    else hideChip();
  });

  // --- Tap-to-skip zones (fullscreen only) ---------------------------------
  // Left/right edges rewind/forward; they clear the bottom control bar and
  // leave the centre free so play/pause and the controls still work.
  const seek = player.config?.seekTime || 10;
  const tapZone = (side, action) => h('button', {
    type: 'button', class: `aggy-tap aggy-tap-${side}`,
    'aria-label': side === 'left' ? `Rewind ${seek} seconds` : `Forward ${seek} seconds`,
    onclick: (e) => { e.stopPropagation(); action(); flashTap(e.currentTarget); },
  }, h('span', { class: 'aggy-tap-icon' }, side === 'left' ? `« ${seek}` : `${seek} »`));

  container.append(
    tapZone('left', () => player.rewind()),
    tapZone('right', () => player.forward()),
    chip);
}

// Briefly flash a tap zone's label so a skip tap gives visible feedback.
function flashTap(el) {
  el.classList.remove('aggy-tap-active');
  void el.offsetWidth; // restart the animation
  el.classList.add('aggy-tap-active');
}

// Destroy any players inside a host (stops audio, clears timers) before it's
// emptied — used when the reader modal closes.
function destroyPlayersIn(host) {
  host.querySelectorAll('.aggy-player').forEach((wrap) => {
    ytPlayerObserver.unobserve(wrap);
    if (wrap._plyr) { try { wrap._plyr.destroy(); } catch { /* already gone */ } wrap._plyr = null; }
  });
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
// below, then the action row. In `listMode` the recommendation-engine bits
// (the "why recommended" button, the predicted-match badge, and the vote
// buttons) are dropped — a list is a plain saved collection.
function itemCard(item, { listMode = false } = {}) {
  const published = item.item_date_published ? timeAgo(item.item_date_published) : '';
  const ytId = youtubeId(item.item_url);
  const media = !ytId && (item.item_media || []).length ? item.item_media : null;
  const imageUrl = ytId || media ? null : (item.item_image_url || parseItemContent(item).imageUrl);
  const excerpt = cleanExcerpt(item);

  const mediaBlock = ytId
    ? h('figure', { class: 'bg-base-300 aggy-card-media' }, youtubeEmbed(ytId))
    : media
    ? h('figure', { class: 'bg-base-300 aggy-card-media' }, mediaGallery(media))
    : imageUrl
      ? h('figure', { class: 'bg-base-300 aggy-card-media' },
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
        listMode ? null : explainButton(item),
        openLinkButton(item.item_url)),
      !mediaBlock && excerpt && h('p', { class: 'text-xs text-base-content/50 line-clamp-2 mt-1' }, excerpt)),
    mediaBlock,
    h('div', { class: 'flex items-center gap-1 px-2 py-1.5' },
      h('div', { class: 'flex flex-wrap items-center gap-2 text-xs text-base-content/50 min-w-0 pl-2' },
        sourceBadge(item.item_source_name, item.item_source_color),
        item.item_author && h('span', { class: 'truncate max-w-32' }, item.item_author),
        published && h('span', { class: 'whitespace-nowrap' }, published),
        listMode ? null : predictedBadge),
      h('div', { class: 'flex items-center gap-1 ml-auto' },
        listButton(item),
        listMode ? null : voteButton('▲', 1, 'Upvote'),
        listMode ? null : voteButton('●', 0, 'Neutral — seen it, no strong feelings'),
        listMode ? null : voteButton('▼', -1, 'Downvote'))));
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

// ---------- lists ----------
// The current item + its list button while the list modal is open, so a save
// can update the card in place.
let listModalItem = null;
let listModalBtn = null;

// Bookmark icon; filled when the article is saved to at least one list.
function listIconSvg(filled) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', filled ? 'currentColor' : 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.8');
  svg.setAttribute('class', 'w-5 h-5');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('stroke-linecap', 'round');
  path.setAttribute('stroke-linejoin', 'round');
  path.setAttribute('d', 'M6.32 2.577a49.255 49.255 0 0111.36 0c1.497.174 2.57 '
    + '1.46 2.57 2.93V21a.75.75 0 01-1.085.67L12 18.089l-7.165 3.583A.75.75 0 '
    + '013.75 21V5.507c0-1.47 1.073-2.756 2.57-2.93z');
  svg.appendChild(path);
  return svg;
}

// The "add to list" button shown in each card's action row.
function listButton(item) {
  return h('button', {
    class: `btn btn-ghost btn-sm btn-square ${item.item_in_list ? 'text-primary' : 'text-base-content/60'}`,
    title: 'Add to a list',
    onclick: (e) => { e.stopPropagation(); openListModal(item, e.currentTarget); },
  }, listIconSvg(!!item.item_in_list));
}

// One row of the list checklist: a checkbox + name + item count.
function listChecklistRow(l) {
  return h('label', {
    class: 'label cursor-pointer justify-start gap-3 py-1.5 px-2 rounded-lg hover:bg-base-200',
  },
    h('input', {
      type: 'checkbox', class: 'checkbox checkbox-sm checkbox-primary',
      checked: !!l.list_contains_item, 'data-list-hash': l.list_name_hash,
    }),
    h('span', { class: 'label-text flex-1 min-w-0 truncate' }, l.list_name),
    h('span', { class: 'text-xs text-base-content/40' }, String(l.list_item_count ?? 0)));
}

async function openListModal(item, btn) {
  listModalItem = item;
  listModalBtn = btn || null;
  $('newListName').value = '';
  showModal('listModal');
  render($('listChecklist'), spinner());
  try {
    const lists = await sdk.listList({ item_url_hash: item.item_hash });
    renderListChecklist(lists);
  } catch (err) {
    render($('listChecklist'), h('p', { class: 'text-sm text-error py-2' }, err.message));
  }
}

function renderListChecklist(lists) {
  if (!lists.length) {
    render($('listChecklist'),
      h('p', { class: 'text-sm text-base-content/50 py-2' }, 'No lists yet — create one below.'));
    return;
  }
  render($('listChecklist'), lists.map(listChecklistRow));
}

// Create a new list from the inline field and add its (pre-checked) row without
// reloading, so any boxes the user already ticked stay ticked.
async function handleCreateList(e) {
  e.preventDefault();
  const name = $('newListName').value.trim();
  if (!name) return;
  try {
    const created = await sdk.listCreate({ list_name: name });
    $('newListName').value = '';
    const box = $('listChecklist');
    if (!box.querySelector('input')) render(box); // clear the "no lists yet" note
    box.append(listChecklistRow({ ...created, list_contains_item: true }));
  } catch (err) {
    toast(err.message, 'alert-error');
  }
}

async function handleListSave() {
  if (!listModalItem) return;
  const hashes = Array.from($('listChecklist').querySelectorAll('input:checked'))
    .map((i) => i.getAttribute('data-list-hash'));
  try {
    await sdk.listSetItemLists({
      item_url_hash: listModalItem.item_hash,
      list_hashes: hashes.join(','),
    });
    const inList = hashes.length > 0;
    listModalItem.item_in_list = inList;
    if (listModalBtn) {
      listModalBtn.classList.toggle('text-primary', inList);
      listModalBtn.classList.toggle('text-base-content/60', !inList);
      render(listModalBtn, listIconSvg(inList));
    }
    closeModal('listModal');
    toast(inList ? 'Saved to lists' : 'Removed from all lists');
    // while browsing a list, membership changes can add/remove the card
    if (currentList) loadListItems();
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
  const isFeed = !!source.source_feed_hash;
  // Feed sources mirror another feed rather than fetching an RSS URL, so they
  // show the origin feed instead of a URL and skip the fetch-related actions.
  const subtitle = isFeed
    ? `\u{1F517} Feed: ${source.source_feed_name || source.source_name}`
    : source.source_url;
  const checked = source.source_last_ingested_at
    ? `checked ${timeAgo(source.source_last_ingested_at)}`
    : 'not checked yet';
  const interval = intervalLabel(source.source_ingest_interval_minutes);
  const meta = isFeed
    ? `${count} article${count === 1 ? '' : 's'} · shared from another feed`
    : `${count} article${count === 1 ? '' : 's'} · ${checked}${interval ? ` · checks ${interval}` : ''}`;
  const actions = [
    h('button', {
      class: 'btn btn-ghost btn-xs',
      title: 'Show only this source in the feed',
      onclick: () => viewSourceInFeed(source),
    }, 'View'),
  ];
  if (!isFeed) {
    actions.push(h('button', {
      class: 'btn btn-ghost btn-xs',
      title: 'Re-collect images, content and previews for this source',
      onclick: (e) => rescrapeSource(source, e.currentTarget),
    }, 'Re-scrape'));
    actions.push(h('button', {
      class: 'btn btn-ghost btn-xs',
      onclick: () => openEditSourceModal(source),
    }, 'Edit'));
  }
  actions.push(h('button', {
    class: 'btn btn-ghost btn-xs text-error',
    onclick: () => confirmDeleteSource(source),
  }, 'Remove'));
  return h('div', { class: 'flex items-center justify-between gap-3 p-3 bg-base-200 border border-base-300 rounded-lg mb-2' },
    h('div', { class: 'min-w-0' },
      h('div', { class: 'font-medium text-sm flex items-center gap-2' },
        h('span', {
          class: 'inline-block w-2.5 h-2.5 rounded-full flex-shrink-0',
          style: `background:${sourceColor(source.source_name, source.source_color)}`,
        }),
        source.source_name),
      h('div', { class: 'text-xs text-base-content/40 truncate' }, subtitle),
      h('div', { class: 'text-xs text-base-content/60 mt-1' }, meta),
      source.source_last_ingest_error && h('div', { class: 'text-xs text-error mt-1' },
        `Last check failed: ${source.source_last_ingest_error}`)),
    h('div', { class: 'flex gap-1 flex-shrink-0' }, ...actions));
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
  $('srcTabAnalyze').classList.toggle('tab-active', tab === 'analyze');
  $('srcTabFeed').classList.toggle('tab-active', tab === 'feed');
  $('sourceTabTemplate').classList.toggle('hidden', tab !== 'template');
  $('sourceTabAnalyze').classList.toggle('hidden', tab !== 'analyze');
  $('sourceTabFeed').classList.toggle('hidden', tab !== 'feed');
  if (tab === 'feed') loadFeedSourceOptions();
}

// List the user's other feeds as candidate feed-sources. The current feed and
// any feed already added as a source are excluded.
async function loadFeedSourceOptions() {
  const list = $('feedSourceList');
  render(list, spinner());
  try {
    const [feeds, existing] = await Promise.all([
      sdk.feedList(),
      sdk.feedSources({ feed_name_hash: currentFeed.feed_name_hash }),
    ]);
    const alreadySourced = new Set(
      existing.filter((s) => s.source_feed_hash).map((s) => s.source_feed_hash));
    const candidates = feeds.filter((f) =>
      f.feed_name_hash !== currentFeed.feed_name_hash
      && !alreadySourced.has(f.feed_name_hash));
    if (!candidates.length) {
      render(list, h('div', { class: 'p-4 text-center text-sm text-base-content/50' },
        'No other feeds available to add'));
      return;
    }
    render(list, candidates.map((f) =>
      h('div', { class: 'flex items-center justify-between gap-3 p-3 border-b border-base-300 last:border-0' },
        h('div', { class: 'min-w-0' },
          h('div', { class: 'font-medium text-sm truncate' }, f.feed_name),
          h('div', { class: 'text-xs text-base-content/50' },
            `${f.feed_item_count ?? 0} article${(f.feed_item_count ?? 0) === 1 ? '' : 's'}`)),
        h('button', {
          class: 'btn btn-primary btn-xs flex-shrink-0',
          onclick: (e) => handleAddFeedSource(f, e.currentTarget),
        }, 'Add'))));
  } catch (err) {
    render(list, h('div', { class: 'p-4 text-center text-sm text-base-content/50' },
      'Failed to load feeds'));
    toast(err.message, 'alert-error');
  }
}

async function handleAddFeedSource(feed, btn) {
  if (!currentFeed) return;
  if (btn) { btn.disabled = true; btn.textContent = 'Adding…'; }
  try {
    await sdk.sourceCreateFeed({
      feed_name_hash: currentFeed.feed_name_hash,
      source_feed_name_hash: feed.feed_name_hash,
    });
    closeModal('addSourceModal');
    toast(`Added feed "${feed.feed_name}" as a source`);
    loadSources();
  } catch (err) {
    if (btn) { btn.disabled = false; btn.textContent = 'Add'; }
    toast(err.message, 'alert-error');
  }
}

// ---------- analyze a website into selectors (✨ Website tab) ----------

// The backend asks Ollama for candidate CSS selectors per rss-bridge
// parameter; the user can switch between candidates and watch the preview
// (rendered by rss-bridge itself) update before saving the source.
const ANALYZE_FIELDS = [
  { key: 'entry_element_selector', label: 'Article entries', required: true },
  { key: 'title_selector', label: 'Title', none: 'Page default' },
  { key: 'url_selector', label: 'Article link', none: 'First link in entry' },
  { key: 'author_selector', label: 'Author', none: 'None' },
  { key: 'time_selector', label: 'Published date', none: 'None' },
];

let analyzeState = null; // { suggestion, params } while the result step is open
let analyzePreviewSeq = 0; // ignore out-of-order preview responses

function resetAnalyzeTab() {
  analyzeState = null;
  analyzePreviewSeq += 1;
  $('analyzeInputStep').classList.remove('hidden');
  $('analyzeResultStep').classList.add('hidden');
  $('analyzeProgress').classList.add('hidden');
  $('analyzeBtn').disabled = false;
}

// Analysis runs server-side as a background job (LLM passes can take minutes
// on CPU, longer than most reverse-proxy timeouts allow a request to live),
// so we start it and poll for the result every couple of seconds.
const ANALYZE_POLL_MS = 2000;
const ANALYZE_TIMEOUT_MS = 8 * 60 * 1000;

async function pollAnalyzeJob(jobId) {
  const started = Date.now();
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, ANALYZE_POLL_MS));
    const job = await sdk.sourceAnalyzeSuggestResult({ job_id: jobId });
    if (job.status === 'done') return job.result;
    if (Date.now() - started > ANALYZE_TIMEOUT_MS) {
      throw new Error('Analysis timed out — Ollama may be overloaded or the model is still loading');
    }
    const seconds = Math.round((Date.now() - started) / 1000);
    $('analyzeProgressText').textContent =
      `Asking Ollama for selectors — ${seconds}s. The first run after a restart is slowest (the model loads into memory).`;
  }
}

// Derive a readable source name from a URL when the feed gives no title.
function hostnameFromUrl(url) {
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return url; }
}

async function handleAnalyzeWebsite(e) {
  e.preventDefault();
  const url = $('analyzeUrl').value.trim();
  if (!url) return;

  $('analyzeBtn').disabled = true;
  $('analyzeProgress').classList.remove('hidden');
  $('analyzeProgressText').textContent = 'Checking whether the URL is already a feed…';
  try {
    const cookie = $('analyzeCookie').value.trim() || null;

    // If the URL is already a valid RSS/Atom feed, add it directly — no need
    // to scrape the page or run the model.
    const detected = await sdk.sourceAnalyzeDetectFeed({ body: { url, cookie } });
    if (detected.is_feed) {
      const name = detected.feed_title || hostnameFromUrl(url);
      await sdk.sourceCreate({
        feed_name_hash: currentFeed.feed_name_hash,
        source_name: name,
        source_url: url,
      });
      closeModal('addSourceModal');
      toast(`Source "${name}" added`);
      loadSources();
      // the first ingest runs in the background; refresh to pick up its result
      setTimeout(loadSources, 5000);
      return;
    }

    $('analyzeProgressText').textContent =
      'Scraping the page and asking Ollama for selectors — this can take a minute or two…';
    const job = await sdk.sourceAnalyzeSuggest({ body: { url, cookie } });
    const suggestion = await pollAnalyzeJob(job.job_id);
    // custom: fields where the user typed a selector instead of picking one
    analyzeState = { suggestion, params: { ...suggestion.defaults }, custom: {} };
    $('analyzeSourceName').value = suggestion.suggested_source_name || '';
    renderAnalyzeFields();
    $('analyzeInputStep').classList.add('hidden');
    $('analyzeResultStep').classList.remove('hidden');
    loadAnalyzePreview();
  } catch (err) {
    toast(err.message, 'alert-error');
  } finally {
    $('analyzeBtn').disabled = false;
    $('analyzeProgress').classList.add('hidden');
  }
}

// A candidate's extracted samples, one per line so it's obvious where each
// title/link ends and the next begins (a bad parse looks like one long run).
function analyzeFieldSamples(field) {
  if (analyzeState.custom[field.key]) return [];
  const candidates = analyzeState.suggestion.candidates[field.key] || [];
  const current = candidates.find((c) => c.selector === analyzeState.params[field.key]);
  return current ? current.samples : [];
}

const ANALYZE_CUSTOM = '__custom__';

function renderAnalyzeFields() {
  render($('analyzeFields'), ANALYZE_FIELDS.map((field) => {
    const candidates = analyzeState.suggestion.candidates[field.key] || [];
    const isCustom = !!analyzeState.custom[field.key];

    const select = h('select', {
      class: 'select select-bordered select-sm w-full font-mono',
      onchange: (e) => {
        if (e.target.value === ANALYZE_CUSTOM) {
          analyzeState.custom[field.key] = true;
        } else {
          analyzeState.custom[field.key] = false;
          analyzeState.params[field.key] = e.target.value;
          if (field.key === 'time_selector') {
            // the bridge needs the matching PHP format alongside the selector
            const chosen = candidates.find((c) => c.selector === e.target.value);
            analyzeState.params.time_format = (chosen && chosen.time_format) || '';
          }
          scheduleAnalyzePreview();
        }
        renderAnalyzeFields();
      },
    },
      field.none ? h('option', {
        value: '', selected: !isCustom && !analyzeState.params[field.key],
      }, `(${field.none})`) : null,
      candidates.map((c) => h('option', {
        value: c.selector,
        selected: !isCustom && analyzeState.params[field.key] === c.selector,
      }, `${c.selector}  (${c.match_count} match${c.match_count === 1 ? '' : 'es'})`)),
      h('option', { value: ANALYZE_CUSTOM, selected: isCustom }, 'Custom selector…'));

    // free-text override, so a wrong or missing suggestion is always fixable
    const customInput = isCustom && h('input', {
      type: 'text',
      class: 'input input-bordered input-sm w-full font-mono mt-1',
      value: analyzeState.params[field.key] || '',
      placeholder: field.required ? 'div.article' : '.byline a',
      oninput: (e) => { analyzeState.params[field.key] = e.target.value.trim(); scheduleAnalyzePreview(); },
    });

    // the date needs a parse format next to its selector; keep it editable so
    // an off-by-hours or misparsed date can be corrected by hand
    const showTimeFormat = field.key === 'time_selector'
      && (isCustom || analyzeState.params.time_selector);
    const timeFormatInput = showTimeFormat && h('div', { class: 'mt-1' },
      h('label', { class: 'label py-0' },
        h('span', { class: 'label-text-alt text-base-content/50' },
          'Date format (PHP date(), e.g. Y-m-d\\TH:i:sP or d/m/Y H:i)')),
      h('input', {
        type: 'text',
        class: 'input input-bordered input-sm w-full font-mono',
        value: analyzeState.params.time_format || '',
        oninput: (e) => { analyzeState.params.time_format = e.target.value.trim(); scheduleAnalyzePreview(); },
      }));

    const samples = analyzeFieldSamples(field);
    return h('div', { class: 'form-control mb-2' },
      h('label', { class: 'label py-1' },
        h('span', { class: 'label-text text-xs font-medium' },
          field.label + (field.required ? ' *' : ''))),
      select,
      customInput,
      timeFormatInput,
      samples.length ? h('div', { class: 'mt-0.5' },
        samples.map((s) => h('div', { class: 'text-xs text-base-content/40 truncate' }, `‣ ${s}`))) : null);
  }));
}

const scheduleAnalyzePreview = debounce(loadAnalyzePreview, 500);

async function loadAnalyzePreview() {
  if (!analyzeState) return;
  const seq = ++analyzePreviewSeq;
  $('analyzePreviewStatus').textContent = 'rendering via rss-bridge…';
  render($('analyzePreview'), h('div', { class: 'p-6' }, spinner()));
  try {
    const preview = await sdk.sourceAnalyzePreview({
      body: { parameters: analyzeState.params },
    });
    if (seq !== analyzePreviewSeq || !analyzeState) return;
    $('analyzePreviewStatus').textContent =
      `${preview.items.length} item${preview.items.length === 1 ? '' : 's'}`;
    if (!preview.items.length) {
      render($('analyzePreview'), h('div', { class: 'p-4 text-center text-sm text-base-content/50' },
        'No items — try a different "Article entries" selector'));
      return;
    }
    render($('analyzePreview'), preview.items.map((item) =>
      h('div', { class: 'flex gap-3 px-3 py-2 border-b border-base-300 last:border-b-0' },
        item.image && h('img', {
          src: item.image, class: 'w-14 h-14 object-cover rounded flex-shrink-0', loading: 'lazy',
        }),
        h('div', { class: 'min-w-0' },
          h('a', {
            class: 'text-sm font-medium link link-hover', href: item.url || '#',
            target: '_blank', rel: 'noopener',
          }, item.title || '(no title)'),
          (item.author || item.date_published) && h('div', { class: 'text-xs text-base-content/40' },
            [item.author, item.date_published].filter(Boolean).join(' · ')),
          item.excerpt && h('div', { class: 'text-xs text-base-content/60 line-clamp-2' },
            item.excerpt)))));
  } catch (err) {
    if (seq !== analyzePreviewSeq || !analyzeState) return;
    $('analyzePreviewStatus').textContent = '';
    render($('analyzePreview'), h('div', { class: 'p-4 text-sm text-error' }, err.message));
  }
}

async function handleCreateAnalyzedSource() {
  if (!analyzeState || !currentFeed) return;
  const name = $('analyzeSourceName').value.trim();
  if (!name) { toast('Please enter a source name', 'alert-error'); return; }

  const btn = $('analyzeAddBtn');
  btn.disabled = true;
  try {
    await sdk.sourceTemplateCreate({
      body: {
        source_template_name_hash: analyzeState.suggestion.template_name_hash,
        feed_hash: currentFeed.feed_name_hash,
        source_name: name,
        parameters: analyzeState.params,
      },
    });
    closeModal('addSourceModal');
    toast(`Source "${name}" added`);
    resetAnalyzeTab();
    $('analyzeUrl').value = '';
    loadSources();
    // the first ingest runs in the background; refresh to pick up its result
    setTimeout(loadSources, 5000);
  } catch (err) {
    toast(err.message, 'alert-error');
  } finally {
    btn.disabled = false;
  }
}

// ---------- bulk import ----------

// Wizard for onboarding many sources at once: pick a platform and provide
// subscription data (export file, pasted list, or username), review the
// detected sources and assign each to a feed, then import.

// Reddit's official data export can take up to 30 days, so we offer a
// browser-console script that pulls subscriptions instantly instead.
const REDDIT_EXPORT_SCRIPT = `(async () => {
  const subs = [];
  let after = null;

  do {
    const url = new URL('https://www.reddit.com/subreddits/mine/subscriber.json');
    url.searchParams.set('limit', '100');
    if (after) url.searchParams.set('after', after);

    const res = await fetch(url, { credentials: 'include' });
    if (!res.ok) throw new Error(\`Request failed: \${res.status} \${res.statusText}\`);

    const json = await res.json();
    for (const child of json.data.children) {
      subs.push(child.data.display_name_prefixed);
    }
    after = json.data.after;
  } while (after);

  subs.sort((a, b) => a.localeCompare(b));
  console.log(\`Found \${subs.length} subscriptions\`);
  console.table(subs);

  const blob = new Blob([subs.join('\\n')], { type: 'text/plain' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'my-subreddits.txt';
  a.click();

  window.mySubs = subs;
})();`;

const IMPORT_PLATFORMS = {
  reddit: {
    label: 'Reddit',
    help: 'While logged in to reddit.com, open your browser console '
      + '(F12 → Console), paste the copied script, and press Enter — it downloads '
      + 'my-subreddits.txt with all your subscriptions. Upload or paste that below.',
    script: REDDIT_EXPORT_SCRIPT,
    fileAccept: '.csv,.txt,text/csv,text/plain',
    textPlaceholder: 'r/selfhosted\nr/alligators\nhttps://www.reddit.com/r/aquariums',
  },
  youtube: {
    label: 'YouTube',
    help: 'Upload subscriptions.csv from Google Takeout (takeout.google.com → '
      + 'deselect all → YouTube → subscriptions only), or paste channel links or @handles below.',
    fileAccept: '.csv,text/csv',
    textPlaceholder: '@veritasium\nhttps://www.youtube.com/@kurzgesagt\nUCXuqSBlHAE6Xw-yeJA0Tunw',
  },
  bluesky: {
    label: 'Bluesky',
    help: 'Enter a Bluesky handle — every account it follows is fetched via '
      + "Bluesky's public API, no login needed.",
    username: true,
  },
  opml: {
    label: 'RSS / OPML',
    help: 'Upload the OPML file exported by your RSS reader or podcast app '
      + '(Feedly, Inoreader, NewsBlur, AntennaPod, ...). Folders can become feeds.',
    fileAccept: '.opml,.xml,text/xml,text/x-opml',
    textPlaceholder: 'or paste OPML here',
  },
};

let importState = { platform: 'reddit', candidates: [], feeds: [] };

function openImportModal() {
  importState = { platform: importState.platform, candidates: [], feeds: [] };
  selectImportPlatform(importState.platform);
  setImportStep('input');
  showModal('importModal');
  // feeds populate the per-row dropdowns on the review step
  sdk.feedList().then((feeds) => { importState.feeds = feeds; }).catch(() => {});
}

function setImportStep(step) {
  $('importStepInput').classList.toggle('hidden', step !== 'input');
  $('importStepReview').classList.toggle('hidden', step !== 'review');
  $('importStepResults').classList.toggle('hidden', step !== 'results');
}

function selectImportPlatform(platform) {
  importState.platform = platform;
  const cfg = IMPORT_PLATFORMS[platform];
  render($('importPlatformTabs'),
    Object.entries(IMPORT_PLATFORMS).map(([key, p]) =>
      h('a', {
        role: 'tab',
        class: `tab${key === platform ? ' tab-active' : ''}`,
        onclick: () => selectImportPlatform(key),
      }, p.label)));
  $('importHelp').textContent = cfg.help;
  $('importScriptControl').classList.toggle('hidden', !cfg.script);
  $('importFileControl').classList.toggle('hidden', !cfg.fileAccept);
  $('importTextControl').classList.toggle('hidden', !cfg.textPlaceholder);
  $('importUsernameControl').classList.toggle('hidden', !cfg.username);
  if (cfg.fileAccept) $('importFile').setAttribute('accept', cfg.fileAccept);
  $('importFile').value = '';
  $('importText').value = '';
  $('importText').placeholder = cfg.textPlaceholder || '';
}

async function copyImportScript() {
  const cfg = IMPORT_PLATFORMS[importState.platform];
  if (!cfg.script) return;
  try {
    await navigator.clipboard.writeText(cfg.script);
    toast('Script copied — paste it into the browser console on reddit.com');
  } catch {
    toast('Couldn\'t access the clipboard — copy the script manually', 'alert-error');
  }
}

const readFileText = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(reader.result);
  reader.onerror = () => reject(new Error(`Couldn't read ${file.name}`));
  reader.readAsText(file);
});

async function handleImportParse() {
  const cfg = IMPORT_PLATFORMS[importState.platform];
  const body = { platform: importState.platform };
  if (cfg.username) {
    body.username = $('importUsername').value.trim();
    if (!body.username) { toast('Enter a handle first', 'alert-error'); return; }
  } else {
    // file and pasted text are combined so users can top up an export
    const parts = [];
    const file = $('importFile').files[0];
    try {
      if (file) parts.push(await readFileText(file));
    } catch (err) {
      toast(err.message, 'alert-error');
      return;
    }
    if ($('importText').value.trim()) parts.push($('importText').value);
    body.data = parts.join('\n');
    if (!body.data.trim()) { toast('Upload a file or paste your subscriptions first', 'alert-error'); return; }
  }

  const btn = $('importParseBtn');
  btn.disabled = true;
  btn.textContent = 'Looking up…';
  try {
    const parsed = await sdk.importParse({ body });
    // rows keep UI state (selected + target feed) alongside the candidate
    const defaultFeed = importState.feeds.length === 1 ? importState.feeds[0].feed_name_hash : '';
    importState.candidates = parsed.candidates.map((c) => ({
      ...c,
      selected: !c.error,
      feedHash: defaultFeed,
    }));
    render($('importWarnings'), (parsed.warnings || []).map((w) =>
      h('div', { class: 'text-xs text-warning' }, w)));
    $('importGroupFeedsBtn').classList.toggle('hidden',
      !importState.candidates.some((c) => c.group));
    $('importSelectAll').checked = true;
    renderImportFeedOptions();
    renderImportCandidates();
    setImportStep('review');
  } catch (err) {
    toast(err.message, 'alert-error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Find sources';
  }
}

// The bulk-assign dropdown mirrors the per-row feed dropdowns.
function renderImportFeedOptions() {
  render($('importAssignFeed'),
    h('option', { value: '' }, 'Pick a feed…'),
    importState.feeds.map((f) => h('option', { value: f.feed_name_hash }, f.feed_name)));
}

function importFeedSelect(row) {
  return h('select', {
    class: `select select-bordered select-xs${row.feedHash ? '' : ' select-warning'}`,
    onchange: (e) => { row.feedHash = e.target.value; renderImportCandidates(); },
  },
    h('option', { value: '', selected: !row.feedHash }, 'Pick a feed…'),
    importState.feeds.map((f) =>
      h('option', { value: f.feed_name_hash, selected: row.feedHash === f.feed_name_hash }, f.feed_name)));
}

function renderImportCandidates() {
  const rows = importState.candidates;
  const selected = rows.filter((r) => r.selected);
  $('importSelectedCount').textContent =
    `${selected.length} of ${rows.length} selected`;
  $('importCreateBtn').disabled = !selected.length || selected.some((r) => !r.feedHash);
  $('importCreateBtn').textContent = selected.length
    ? `Import ${selected.length} source${selected.length === 1 ? '' : 's'}`
    : 'Import';

  render($('importCandidateList'), rows.map((row) =>
    h('div', { class: `flex items-center gap-2 px-3 py-2 border-b border-base-300 last:border-b-0${row.error ? ' opacity-50' : ''}` },
      h('input', {
        type: 'checkbox', class: 'checkbox checkbox-sm checkbox-primary flex-shrink-0',
        checked: row.selected, disabled: !!row.error,
        onchange: (e) => { row.selected = e.target.checked; renderImportCandidates(); },
      }),
      h('div', { class: 'flex-1 min-w-0' },
        h('input', {
          type: 'text', class: 'input input-ghost input-xs w-full font-medium px-0',
          value: row.name, title: 'Source name (editable)',
          onchange: (e) => { row.name = e.target.value.trim() || row.name; },
        }),
        h('div', { class: `text-xs truncate ${row.error ? 'text-error' : 'text-base-content/40'}` },
          row.error || [row.group, row.url].filter(Boolean).join(' · '))),
      row.error ? null : importFeedSelect(row))));
}

function applyImportFeedToSelected() {
  const feedHash = $('importAssignFeed').value;
  if (!feedHash) { toast('Pick a feed to assign first', 'alert-error'); return; }
  importState.candidates.forEach((row) => { if (row.selected) row.feedHash = feedHash; });
  renderImportCandidates();
}

// Inline feed creation so the wizard works before any feed exists. The new
// feed only fills in selected rows that don't have a feed picked yet —
// dropdowns the user already set are left alone.
async function createImportFeed() {
  const name = prompt('Name for the new feed:');
  if (!name || !name.trim()) return;
  try {
    const feed = await sdk.feedCreate({ feed_name: name.trim() });
    if (!importState.feeds.some((f) => f.feed_name_hash === feed.feed_name_hash)) {
      importState.feeds.push(feed);
    }
    renderImportFeedOptions();
    $('importAssignFeed').value = feed.feed_name_hash;
    importState.candidates.forEach((row) => {
      if (row.selected && !row.feedHash) row.feedHash = feed.feed_name_hash;
    });
    renderImportCandidates();
    toast(`Feed "${feed.feed_name}" created and assigned to unassigned selected sources`);
  } catch (err) {
    toast(err.message, 'alert-error');
  }
}

// OPML folders map naturally onto Aggy feeds: create a feed per folder and
// assign each source to its folder's feed.
async function createImportFeedsFromGroups() {
  const groups = [...new Set(importState.candidates.map((c) => c.group).filter(Boolean))];
  if (!groups.length) return;
  const btn = $('importGroupFeedsBtn');
  btn.disabled = true;
  try {
    for (const group of groups) {
      // feed/create returns the existing feed when the name is already taken
      const feed = await sdk.feedCreate({ feed_name: group });
      if (!importState.feeds.some((f) => f.feed_name_hash === feed.feed_name_hash)) {
        importState.feeds.push(feed);
      }
      importState.candidates.forEach((row) => {
        if (row.group === group) row.feedHash = feed.feed_name_hash;
      });
    }
    renderImportFeedOptions();
    renderImportCandidates();
    toast(`Assigned sources to ${groups.length} feed${groups.length === 1 ? '' : 's'} from folders`);
  } catch (err) {
    toast(err.message, 'alert-error');
  } finally {
    btn.disabled = false;
  }
}

async function handleImportCreate() {
  const rows = importState.candidates.filter((r) => r.selected);
  if (!rows.length) return;
  if (rows.some((r) => !r.feedHash)) {
    toast('Every selected source needs a feed', 'alert-error');
    return;
  }

  const btn = $('importCreateBtn');
  btn.disabled = true;
  btn.textContent = 'Importing…';
  try {
    const response = await sdk.importCreate({
      body: {
        sources: rows.map((r) => ({
          feed_name_hash: r.feedHash,
          source_name: r.name,
          source_url: r.url,
          template_name_hash: r.template_name_hash,
          template_parameters: r.template_parameters,
        })),
      },
    });
    renderImportResults(response);
    setImportStep('results');
    loadFeeds();
  } catch (err) {
    toast(err.message, 'alert-error');
  } finally {
    btn.disabled = false;
    renderImportCandidates();
  }
}

function renderImportResults(response) {
  const failed = response.results.filter((r) => r.status !== 'created');
  const feedName = (hash) =>
    (importState.feeds.find((f) => f.feed_name_hash === hash) || {}).feed_name || '';
  render($('importResultsBody'),
    h('div', { class: 'stats stats-horizontal shadow-none border border-base-300 w-full mb-3' },
      h('div', { class: 'stat py-2' },
        h('div', { class: 'stat-title text-xs' }, 'Imported'),
        h('div', { class: 'stat-value text-lg text-success' }, String(response.created))),
      h('div', { class: 'stat py-2' },
        h('div', { class: 'stat-title text-xs' }, 'Already existed'),
        h('div', { class: 'stat-value text-lg' }, String(response.duplicates))),
      h('div', { class: 'stat py-2' },
        h('div', { class: 'stat-title text-xs' }, 'Failed'),
        h('div', { class: 'stat-value text-lg text-error' }, String(response.errors)))),
    response.created
      ? h('p', { class: 'text-xs text-base-content/60 mb-3' },
          'Articles will roll in over the next hour or so as each new source is checked for the first time.')
      : null,
    failed.length
      ? h('div', { class: 'max-h-[40vh] overflow-y-auto border border-base-300 rounded-lg' },
          failed.map((r) =>
            h('div', { class: 'px-3 py-2 border-b border-base-300 last:border-b-0' },
              h('div', { class: 'text-sm font-medium' },
                r.source_name,
                h('span', { class: 'text-base-content/40 font-normal' }, ` → ${feedName(r.feed_name_hash)}`)),
              h('div', { class: `text-xs ${r.status === 'error' ? 'text-error' : 'text-base-content/50'}` },
                r.detail || r.status))))
      : null);
}

// ---------- source templates ----------
function openAddSourceModal() {
  showModal('addSourceModal');
  clearTemplateSelection();
  resetAnalyzeTab();
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
