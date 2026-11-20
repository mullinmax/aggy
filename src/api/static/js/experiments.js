// Prediction experiments: the panel at the foot of the model stats modal.
//
// An experiment replays your past votes against every prediction method the
// app knows and reports which would have put your upvotes first. It is queued
// on the server and worked one at a time in the background, so everything
// here is drawn from what the server has stored: closing the modal,
// refreshing the page or restarting the app loses nothing.
//
// A result is aggregate scores only, built to be copied out of the app.

const EXPERIMENT_POLL_MS = 3000;
const EXPERIMENT_LIST_LIMIT = 10;

const EXPERIMENT_METHOD_LABELS = {
  live_picker: 'What the app uses today',
  time_picker: 'Pick by recent ranking',
  blend_top3: 'Blend of the best 3',
  blend_core: 'Blend of 4 simple methods',
  newest_first: 'Newest first (baseline)',
  taste_profile: 'Taste profile',
  multi_interest: 'Multi-interest profile',
  knn_recent_30d: 'Similar posts, recent votes first',
  ridge_recent_7d: 'Linear, 7-day memory',
  ridge_recent_30d: 'Linear, 30-day memory',
  ridge_recent_90d: 'Linear, 90-day memory',
  logistic_neighbors: 'Logistic + neighbour votes',
  pca_logistic: 'Logistic on compressed text',
  three_way: 'Up / neutral / down classifier',
  pairwise_ranker: 'Pairwise ranker',
  source_prior_knn: 'Source and author prior',
  knn_tuned: 'Similar posts, tuned',
  ridge_tuned: 'Linear, tuned',
  account_knn: 'Similar posts, all feeds',
  account_ridge: 'Linear, all feeds',
  account_logistic: 'Logistic, all feeds',
  gradient_boost_upvote: 'Boosted trees on upvotes',
  opens_as_neutral_knn: 'Opens count as neutral',
  llm_judge: 'Language model judge',
};

const EXPERIMENT_BASELINE = 'live_picker';

let experimentTimer = null;
let experimentRows = [];
let experimentExpanded = null; // id of the result being shown
const experimentResults = new Map(); // id -> stored result

const experimentMethodLabel = (name) =>
  EXPERIMENT_METHOD_LABELS[name] || modelLabel(name);

const experimentIsOpen = (e) => e.status === 'queued' || e.status === 'running';

function stopExperimentWatch() {
  clearInterval(experimentTimer);
  experimentTimer = null;
}

// Poll only while something is waiting or running and the modal is open to
// show it. The run itself does not need watching: it is the server's.
function watchExperiments() {
  if (experimentTimer) return;
  experimentTimer = setInterval(async () => {
    if (!$('statsModal').open) { stopExperimentWatch(); return; }
    await loadExperiments({ quiet: true });
  }, EXPERIMENT_POLL_MS);
}

async function loadExperiments({ quiet = false } = {}) {
  const host = $('experimentsPanel');
  if (!host) return;
  try {
    const before = new Map(experimentRows.map((e) => [e.experiment_id, e.status]));
    const data = await sdk.experimentsList({ limit: EXPERIMENT_LIST_LIMIT });
    experimentRows = data.experiments;
    for (const e of experimentRows) {
      const was = before.get(e.experiment_id);
      if (was && was !== e.status && e.status === 'done') {
        toast(`Experiment #${e.experiment_id} finished`);
      }
    }
    renderExperiments();
    if (experimentRows.some(experimentIsOpen)) watchExperiments();
    else stopExperimentWatch();
  } catch (err) {
    if (!quiet) render(host, h('p', { class: 'text-sm text-error' }, err.message));
  }
}

async function startExperiment(scope) {
  try {
    await sdk.experimentsStart({
      feed_name_hash: scope === 'feed' && currentFeed ? currentFeed.feed_name_hash : undefined,
      mode: $('experimentMode').value,
      llm_judge: $('experimentLlm').checked,
    });
    toast('Experiment queued. It runs in the background, so you can close this.');
    await loadExperiments();
  } catch (err) {
    toast(err.message, 'alert-error');
  }
}

async function experimentResult(id) {
  if (!experimentResults.has(id)) {
    const full = await sdk.experimentsGet({ experiment_id: id });
    experimentResults.set(id, full.result);
  }
  return experimentResults.get(id);
}

async function toggleExperimentResult(id) {
  if (experimentExpanded === id) {
    experimentExpanded = null;
    renderExperiments();
    return;
  }
  try {
    await experimentResult(id);
    experimentExpanded = id;
    renderExperiments();
  } catch (err) {
    toast(err.message, 'alert-error');
  }
}

// Clipboard access needs a secure page, and a home server is often plain
// http. When it is refused the JSON is put in a box, already selected, so
// copying is still one keystroke.
async function copyExperimentResult(id) {
  let text;
  try {
    text = JSON.stringify(await experimentResult(id), null, 2);
  } catch (err) {
    toast(err.message, 'alert-error');
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    toast('Results copied. Only scores, no article details.');
  } catch {
    experimentExpanded = id;
    renderExperiments();
    const box = $('experimentCopyBox');
    box.value = text;
    box.classList.remove('hidden');
    box.focus();
    box.select();
    toast('Press Ctrl+C (or Cmd+C) to copy the selected results', 'alert-info');
  }
}

async function cancelExperiment(id) {
  try {
    await sdk.experimentsCancel({ experiment_id: id });
  } catch (err) {
    toast(err.message, 'alert-error');
  }
  await loadExperiments();
}

async function deleteExperiment(id) {
  try {
    await sdk.experimentsDelete({ experiment_id: id });
    experimentResults.delete(id);
    if (experimentExpanded === id) experimentExpanded = null;
  } catch (err) {
    toast(err.message, 'alert-error');
  }
  await loadExperiments();
}

function experimentScopeLabel(e) {
  if (!e.feed_name_hash) return 'all feeds';
  return currentFeed && currentFeed.feed_name_hash === e.feed_name_hash
    ? 'this feed' : 'one feed';
}

function experimentStatusLine(e) {
  if (e.status === 'queued') {
    return e.queued_ahead > 0
      ? `Waiting, ${e.queued_ahead} ahead of it`
      : 'Waiting to start';
  }
  if (e.status === 'running') {
    const p = e.progress;
    if (!p) return 'Starting';
    return `Feed ${p.feed} of ${p.feeds}, block ${p.block} of ${p.blocks}`
      + (p.method ? `, ${experimentMethodLabel(p.method)}` : '');
  }
  if (e.status === 'done') return `Finished ${timeAgo(e.finished_at)}`;
  if (e.status === 'cancelled') return 'Cancelled';
  return `Failed: ${e.error || 'unknown error'}`;
}

const experimentScore = (v, digits = 3) => (v == null ? '·' : v.toFixed(digits));
const experimentPct = (v) => (v == null ? '·' : `${Math.round(v * 100)}%`);

function experimentVerdict(row) {
  if (row.method === EXPERIMENT_BASELINE) {
    return h('span', { class: 'badge badge-ghost badge-xs' }, 'baseline');
  }
  const versus = row.vs_baseline;
  if (!versus) return h('span', { class: 'text-base-content/40' }, '·');
  const sign = versus.auc_diff > 0 ? '+' : '';
  const cls = versus.verdict === 'better' ? 'text-success'
    : versus.verdict === 'worse' ? 'text-error' : 'text-base-content/60';
  const range = versus.auc_diff_range
    ? `95% range ${versus.auc_diff_range[0]} to ${versus.auc_diff_range[1]}. ` : '';
  return h('span', {
    class: cls,
    title: `${range}Won ${experimentPct(versus.block_win_rate)} of ${versus.blocks} blocks. ${versus.verdict}.`,
  }, `${sign}${experimentScore(versus.auc_diff)}`);
}

function experimentResultView(result) {
  if (!result) return null;
  if (!result.methods.length) {
    return h('p', { class: 'text-xs text-base-content/60 mt-2' },
      'Not enough votes to replay yet. A feed needs at least 15 votes.');
  }
  const row = (m) =>
    h('tr', { class: m.method === EXPERIMENT_BASELINE ? 'bg-primary/10' : '' },
      h('td', { class: 'text-xs' }, experimentMethodLabel(m.method)),
      h('td', { class: 'text-xs text-right' }, experimentScore(m.auc)),
      h('td', { class: 'text-xs text-right' }, experimentPct(m.top5_hit_rate)),
      h('td', { class: 'text-xs text-right' }, experimentVerdict(m)),
      h('td', { class: 'text-xs text-right text-base-content/50' },
        m.seconds_per_fit == null ? '·' : `${m.seconds_per_fit.toFixed(2)}s`));
  const opens = result.engagement ? result.engagement.opens_recorded : 0;
  return h('div', { class: 'mt-2' },
    h('p', { class: 'text-xs text-base-content/60 mb-2' },
      `${result.predictions} votes predicted in ${result.blocks} blocks across `
      + `${result.feeds.length} feed${result.feeds.length === 1 ? '' : 's'}, `
      + `${result.mode} mode, ${Math.round(result.seconds)}s. `
      + `${opens} article open${opens === 1 ? '' : 's'} recorded so far.`),
    h('div', { class: 'overflow-x-auto max-h-80 overflow-y-auto' },
      h('table', { class: 'table table-xs table-pin-rows' },
        h('thead', {},
          h('tr', {},
            h('th', {}, 'Method'),
            h('th', {
              class: 'text-right',
              title: 'How often an upvoted article is ranked above one you did not upvote. 0.5 is a coin flip.',
            }, 'Ranking'),
            h('th', {
              class: 'text-right',
              title: 'Share of the 5 top-ranked articles in each block that you upvoted',
            }, 'Top 5'),
            h('th', {
              class: 'text-right',
              title: 'Ranking score compared with what the app uses today, on the same votes',
            }, 'vs today'),
            h('th', { class: 'text-right', title: 'Average time to train once' }, 'Fit'))),
        h('tbody', {}, result.methods.map(row)))),
    h('textarea', {
      id: 'experimentCopyBox', readonly: 'readonly', rows: '6',
      class: 'hidden textarea textarea-bordered w-full font-mono text-xs mt-2',
    }));
}

function experimentRow(e) {
  const open = experimentIsOpen(e);
  const actions = [];
  if (e.has_result) {
    actions.push(
      h('button', {
        class: 'btn btn-ghost btn-xs', onclick: () => toggleExperimentResult(e.experiment_id),
      }, experimentExpanded === e.experiment_id ? 'Hide' : 'View'),
      h('button', {
        class: 'btn btn-primary btn-xs', onclick: () => copyExperimentResult(e.experiment_id),
      }, 'Copy results'));
  }
  actions.push(open
    ? h('button', {
        class: 'btn btn-ghost btn-xs', onclick: () => cancelExperiment(e.experiment_id),
      }, 'Cancel')
    : h('button', {
        class: 'btn btn-ghost btn-xs text-base-content/50',
        title: 'Delete this experiment and its result',
        onclick: () => deleteExperiment(e.experiment_id),
      }, 'Delete'));

  const progress = e.status === 'running'
    ? h('progress', {
        class: 'progress progress-primary w-full h-1.5 mt-1',
        value: String(e.progress ? e.progress.fraction : 0), max: '1',
      })
    : null;

  return h('div', { class: 'rounded-lg border border-base-300 p-2' },
    h('div', { class: 'flex flex-wrap items-center gap-x-2 gap-y-1' },
      h('span', { class: 'text-xs font-medium' },
        `#${e.experiment_id} · ${experimentScopeLabel(e)} · ${e.mode}`
        + (e.llm_judge ? ' · LLM judge' : '')),
      h('span', {
        class: `text-xs ${e.status === 'error' ? 'text-error' : 'text-base-content/60'}`,
      }, experimentStatusLine(e)),
      h('span', { class: 'ml-auto flex gap-1' }, actions)),
    progress,
    experimentExpanded === e.experiment_id
      ? experimentResultView(experimentResults.get(e.experiment_id)) : null);
}

function renderExperiments() {
  const host = $('experimentsPanel');
  if (!host) return;
  // keep what the controls were set to across the re-render a poll causes
  const mode = $('experimentMode') ? $('experimentMode').value : 'quick';
  const llm = $('experimentLlm') ? $('experimentLlm').checked : false;
  const copyBox = $('experimentCopyBox');
  const copied = copyBox && !copyBox.classList.contains('hidden') ? copyBox.value : null;

  render(host,
    h('div', { class: 'divider my-3' }),
    h('h4', { class: 'font-semibold text-sm mb-1' }, 'Prediction experiments'),
    h('p', { class: 'text-xs text-base-content/60 mb-3' },
      'Replays your past votes in order and checks which method would have put your '
      + 'upvotes first. It never changes how the feed is ranked. Experiments run one at a '
      + 'time in the background at low priority, and results are kept until you delete them.'),
    h('div', { class: 'flex flex-wrap items-center gap-2 mb-3' },
      h('select', {
        id: 'experimentMode', class: 'select select-bordered select-xs',
        title: 'Quick skips the slow models and replays fewer blocks',
      },
        h('option', { value: 'quick' }, 'Quick'),
        h('option', { value: 'full' }, 'Full (slower)')),
      h('label', {
        class: 'label cursor-pointer gap-1 py-0',
        title: 'Also ask the local analysis model to judge a small sample of articles. Slow, and needs Ollama.',
      },
        h('input', { type: 'checkbox', id: 'experimentLlm', class: 'checkbox checkbox-xs' }),
        h('span', { class: 'text-xs' }, 'LLM judge')),
      h('button', {
        class: 'btn btn-outline btn-xs', onclick: () => startExperiment('feed'),
      }, 'Run on this feed'),
      h('button', {
        class: 'btn btn-outline btn-xs', onclick: () => startExperiment('all'),
      }, 'Run on all feeds')),
    experimentRows.length
      ? h('div', { class: 'flex flex-col gap-2' }, experimentRows.map(experimentRow))
      : h('p', { class: 'text-xs text-base-content/50' }, 'No experiments yet.'));

  $('experimentMode').value = mode;
  $('experimentLlm').checked = llm;
  if (copied != null && $('experimentCopyBox')) {
    $('experimentCopyBox').value = copied;
    $('experimentCopyBox').classList.remove('hidden');
  }
}
