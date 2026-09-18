// Aggy background-tasks page: what the scheduler has been doing, as a timeline
// of runs and as a table.
//
// The timeline is the point of the page. A log line says a pass happened; a bar
// across a time axis says how often it happens and how long it takes, which is
// what you actually want to know about a background job. One lane per task
// *kind*, so the rhythm of a lane reads at a glance: evenly spaced short bars is
// a healthy ingest, one long bar is a retrain, a wall of bars is something
// thrashing. Which source or feed a given pass was working on is on its hover
// tooltip and in the table, because a lane per source grew a row for every
// source added and left most rows near-empty.
//
// Colour encodes *status*, not task kind. Which task a bar belongs to is
// already carried by its lane, so spending hue on identity would re-encode the
// row label; what you scan a timeline for is the failures. Status is daisyUI's
// reserved success/error/info, always paired with a label in the legend and a
// word in the table -- never colour alone.

'use strict';

const TASKS_WINDOWS = [
  { hours: 1, label: '1h' },
  { hours: 6, label: '6h' },
  { hours: 24, label: '24h' },
  { hours: 72, label: '3d' },
  { hours: 24 * 7, label: '7d' },
];

// Labels and one-liners for the task kinds the API reports. Keyed by the
// backend's own constants so an unknown kind still renders (as itself) rather
// than vanishing from a page whose whole job is showing what ran.
const TASK_KIND_META = {
  feed_training: {
    label: 'Model training',
    help: 'Cross-validating every model on a feed’s votes and picking a winner',
  },
  feed_scoring: {
    label: 'Article scoring',
    help: 'Applying the chosen model to articles it has not scored yet',
  },
  source_ingest: {
    label: 'Source ingest',
    help: 'Fetching a source and storing what it returned',
  },
  source_rescrape: {
    label: 'Source re-scrape',
    help: 'Re-collecting content, pictures and media for articles already stored',
  },
  // retired: duplicate checks are now part of the similarity pass, but runs
  // from before the change are still in the timeline and deserve their label
  duplicate_detection: {
    label: 'Duplicate checks',
    help: 'Grouping articles that are the same content under different URLs',
  },
  image_embed_backfill: {
    label: 'Image embedding',
    help: 'Embedding preview pictures the recommender has not seen yet',
  },
  neighbor_graph: {
    label: 'Similar articles',
    help: 'Linking each article to the ones most like it in the same feed, and '
      + 'grouping the ones that turn out to be the same story',
  },
};

// The canonical display order, and the one kind the lane subtitle needs to name
// by hand (a source ingest covers sources; everything else covers feeds).
const TASK_KINDS = Object.keys(TASK_KIND_META);
const KIND_SOURCE_INGEST = 'source_ingest';

// Status is the reserved palette: never a task-kind hue, always with a word
// beside it. `bar` paints the mark, `text` the label, so a status never relies
// on colour alone to be read.
const TASK_STATUS_META = {
  ok: { label: 'Finished', bar: 'bg-success', text: 'text-success', mark: '●' },
  error: { label: 'Failed', bar: 'bg-error', text: 'text-error', mark: '▲' },
  running: { label: 'Running', bar: 'bg-info', text: 'text-info', mark: '◐' },
};

// The tasks a person can ask for by hand, in the order they are offered.
// Everything here is work the scheduler already does on its own interval -- the
// button only says "now", because waiting an hour to find out whether a fix
// worked is how a fix goes unverified.
//
// `confirm` marks the ones worth a second thought: a re-scrape re-fetches every
// article of every source from its original site, which is minutes of work and
// a lot of requests to other people's servers.
const TASK_TRIGGERS = [
  {
    task: 'image_embed_retry',
    label: 'Retry failed images',
    help: 'Clear the failures on every picture the embedder could not handle, '
      + 'including the ones that ran out of attempts and left the queue, then '
      + 'embed them again. Pictures whose host says they are gone are left '
      + 'alone; a re-scrape is what revives those.',
  },
  {
    task: 'ingest_sources',
    label: 'Fetch all sources',
    help: 'Check every one of your sources for new articles now, instead of at '
      + 'its next scheduled turn.',
  },
  {
    task: 'neighbor_graph',
    label: 'Link similar articles',
    help: 'Work through the articles waiting to be linked to the ones most '
      + 'like them, and re-group the ones that reach you as the same story. '
      + 'These links are also what the recommender reads your neighbouring '
      + 'votes from, and what the reader shows beside an article.',
  },
  {
    task: 'rescrape_sources',
    label: 'Re-scrape all sources',
    help: 'Re-collect content, pictures and media for every article you have '
      + 'stored, and rebuild their embeddings. Slow, and heavy on the sites it '
      + 'fetches from.',
    confirm: {
      title: 'Re-scrape every source?',
      message: 'This re-fetches every article of every source from its original '
        + 'site and rebuilds its embeddings. It can run for a long time and '
        + 'makes a lot of requests to other people’s servers.',
      action: 'Re-scrape',
    },
  },
];

const TASKS_REFRESH_SECONDS = 15;

let taskData = null;
// Which trigger is mid-request, so its button can say so and cannot be pressed
// twice; the work itself is not tracked here -- that is what the timeline is.
let taskTriggerPending = null;
let taskFilters = { hours: 24, kinds: null, statuses: null, view: 'timeline' };
let tasksTimer = null;

function kindMeta(kind) {
  return TASK_KIND_META[kind] || { label: kind, help: '' };
}

function statusMeta(status) {
  return TASK_STATUS_META[status] || TASK_STATUS_META.ok;
}

// ---------- page ----------

async function showTasks() {
  setView('tasks');
  currentFeed = null;
  currentList = null;

  $('tasksRefreshBtn').onclick = () => loadTasks();
  $('tasksAutoRefresh').onchange = (e) => {
    if (e.target.checked) startTasksRefresh();
    else stopTasksRefresh();
  };

  render($('tasksPageBody'), spinner());
  await loadTasks();
  if ($('tasksAutoRefresh').checked) startTasksRefresh();
}

// A page showing what is running now is worth refreshing on its own; stopped
// whenever the view is left so it does not poll in the background forever.
function startTasksRefresh() {
  stopTasksRefresh();
  tasksTimer = setInterval(() => {
    if (!$('viewTasks').classList.contains('hidden')) loadTasks();
    else stopTasksRefresh();
  }, TASKS_REFRESH_SECONDS * 1000);
}

function stopTasksRefresh() {
  if (tasksTimer) clearInterval(tasksTimer);
  tasksTimer = null;
}

async function loadTasks() {
  try {
    taskData = await sdk.tasksRuns({
      hours: taskFilters.hours,
      kinds: taskFilters.kinds === null ? null : taskFilters.kinds.join(','),
      statuses: taskFilters.statuses === null ? null : taskFilters.statuses.join(','),
    });
    renderTasks();
  } catch (err) {
    render($('tasksPageBody'),
      h('p', { class: 'text-sm text-error' }, err.message));
  }
}

function renderTasks() {
  const data = taskData;

  render($('tasksPageBody'),
    taskSummaryTiles(data),
    taskTriggerBar(),
    taskFilterBar(),
    data.truncated
      ? h('div', { class: 'alert alert-warning text-xs mb-3' },
          `Showing the most recent ${fmtInt(data.runs.length)} runs only, so the ` +
          'timeline does not cover the whole window. Narrow the window or the filters.')
      : null,
    taskFilters.view === 'timeline' ? taskTimeline(data) : taskTable(data),
    taskKindTable(data));
}

// ---------- summary ----------

function taskSummaryTiles(data) {
  const tile = (label, value, desc, cls) =>
    h('div', { class: 'stat py-3 px-4' },
      h('div', { class: 'stat-title text-xs' }, label),
      h('div', { class: `stat-value text-xl ${cls || ''}` }, value),
      desc ? h('div', { class: 'stat-desc text-xs' }, desc) : null);

  return h('div', { class: 'stats stats-vertical sm:stats-horizontal shadow-none border border-base-300 w-full mb-4 overflow-x-auto' },
    tile('Runs', fmtInt(data.total_runs), `in the last ${windowLabel(data.hours)}`),
    tile('Running now', fmtInt(data.total_running), 'passes in flight',
      data.total_running ? 'text-info' : null),
    tile('Failed', fmtInt(data.total_errors),
      data.total_errors ? 'needs a look' : 'none',
      data.total_errors ? 'text-error' : null));
}

function windowLabel(hours) {
  if (hours <= 24) return `${hours} hour${hours === 1 ? '' : 's'}`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? '' : 's'}`;
}

// ---------- run now ----------

// Asking for a pass now. Rendered as plain buttons rather than a menu: there
// are four, and the whole point is that the one you want is one press away
// while you are watching the timeline it feeds.
function taskTriggerBar() {
  const buttons = TASK_TRIGGERS.map((trigger) =>
    h('button', {
      class: `btn btn-sm ${taskTriggerPending === trigger.task ? 'btn-disabled' : ''}`,
      title: trigger.help,
      onclick: () => {
        if (!trigger.confirm) return runTaskNow(trigger);
        confirmDialog({
          ...trigger.confirm,
          onConfirm: () => runTaskNow(trigger),
        });
        showModal('confirmModal');
      },
    },
      taskTriggerPending === trigger.task
        ? h('span', { class: 'loading loading-spinner loading-xs' })
        : null,
      trigger.label));

  return sectionCard('Run a task now',
    'These all run on a schedule already; this just asks for one immediately',
    h('div', { class: 'flex flex-wrap gap-2' }, buttons));
}

// The answer says whether the pass actually started: a queue already being
// worked is not started a second time, and a button that claimed otherwise
// would have you pressing it again.
async function runTaskNow(trigger) {
  if (taskTriggerPending) return;
  taskTriggerPending = trigger.task;
  renderTasks();
  try {
    const result = await sdk.tasksRun({ task: trigger.task });
    toast(result.detail, result.started ? 'alert-success' : 'alert-warning');
    // A pass that just started is a bar the timeline does not have yet, and
    // the auto-refresh may be off.
    if (result.started && !taskFilterIncludes(result.kind)) {
      taskFilters.kinds = null;
    }
  } catch (err) {
    toast(err.message, 'alert-error');
  } finally {
    taskTriggerPending = null;
    await loadTasks();
  }
}

// Whether the timeline currently shows a kind at all -- a run you just asked
// for landing in a filtered-out lane looks like nothing happened.
function taskFilterIncludes(kind) {
  return taskFilters.kinds === null || taskFilters.kinds.includes(kind);
}

// ---------- filters ----------

// One row above the charts: the time window, what to include, and which view.
// Every control re-requests rather than filtering in the page, so the counts
// and the axis always describe the same set of rows.
function taskFilterBar() {
  const windowButtons = h('div', { class: 'flex flex-wrap gap-1' },
    TASKS_WINDOWS.map((w) =>
      h('button', {
        class: `btn btn-xs ${w.hours === taskFilters.hours ? 'btn-active' : ''}`,
        onclick: () => { taskFilters.hours = w.hours; loadTasks(); },
      }, w.label)));

  // A null filter means "everything", and every box ticked is the same view as
  // none ticked -- kept as null so the request stays clean.
  const toggle = (current, value, all) => {
    const picked = current === null ? all.slice() : current.slice();
    const at = picked.indexOf(value);
    if (at === -1) picked.push(value);
    else picked.splice(at, 1);
    return picked.length === all.length ? null : picked;
  };

  const allKinds = Object.keys(TASK_KIND_META);
  const kindBoxes = h('div', { class: 'flex flex-wrap gap-2' },
    allKinds.map((kind) => {
      const on = taskFilters.kinds === null || taskFilters.kinds.includes(kind);
      return h('label', {
        class: 'label cursor-pointer gap-1.5 py-0 px-2 border border-base-300 rounded-lg bg-base-100',
        title: kindMeta(kind).help,
      },
        h('input', {
          type: 'checkbox', class: 'checkbox checkbox-xs checkbox-primary',
          checked: on,
          onchange: () => {
            taskFilters.kinds = toggle(taskFilters.kinds, kind, allKinds);
            loadTasks();
          },
        }),
        h('span', { class: 'label-text text-xs' }, kindMeta(kind).label));
    }));

  const allStatuses = Object.keys(TASK_STATUS_META);
  const statusBoxes = h('div', { class: 'flex flex-wrap gap-2' },
    allStatuses.map((status) => {
      const on = taskFilters.statuses === null || taskFilters.statuses.includes(status);
      const meta = statusMeta(status);
      return h('label', {
        class: 'label cursor-pointer gap-1.5 py-0 px-2 border border-base-300 rounded-lg bg-base-100',
      },
        h('input', {
          type: 'checkbox', class: 'checkbox checkbox-xs checkbox-primary',
          checked: on,
          onchange: () => {
            taskFilters.statuses = toggle(taskFilters.statuses, status, allStatuses);
            loadTasks();
          },
        }),
        h('span', { class: `label-text text-xs ${meta.text}` }, meta.mark),
        h('span', { class: 'label-text text-xs' }, meta.label));
    }));

  const viewButtons = h('div', { class: 'flex gap-1' },
    [['timeline', 'Timeline'], ['table', 'Table']].map(([key, label]) =>
      h('button', {
        class: `btn btn-xs ${taskFilters.view === key ? 'btn-active' : ''}`,
        onclick: () => { taskFilters.view = key; renderTasks(); },
      }, label)));

  const group = (label, control) =>
    h('div', { class: 'flex flex-col gap-1' },
      h('span', { class: 'text-xs text-base-content/60' }, label),
      control);

  return h('div', { class: 'card bg-base-200 border border-base-300 mb-4' },
    h('div', { class: 'card-body p-3 flex-row flex-wrap gap-4 items-start' },
      group('Window', windowButtons),
      group('Task', kindBoxes),
      group('Status', statusBoxes),
      group('View', viewButtons)));
}

// ---------- timeline ----------

// One lane per task, a lane being a kind plus what it worked on -- so each
// source gets its own row and its cadence is visible, rather than every ingest
// piling into one "source ingest" line.
// One lane per task kind, not per target. A lane per source meant the timeline
// grew a row for every source added and most rows were near-empty; five lanes
// answer "what kind of work is happening, and how often" at a glance, and the
// bar's tooltip says which source or feed each pass was working on.
function taskLanes(runs) {
  const lanes = new Map();
  for (const run of runs) {
    if (!lanes.has(run.kind)) {
      lanes.set(run.kind, {
        kind: run.kind,
        systemWide: run.system_wide,
        targets: new Set(),
        runs: [],
      });
    }
    const lane = lanes.get(run.kind);
    lane.runs.push(run);
    if (run.target) lane.targets.add(run.target);
  }

  // Fixed order, never by how busy a lane is. The page refreshes itself every
  // few seconds, and a lane that changes row because its count moved makes the
  // reader re-find it -- the whole value of a lane is that the same task is
  // always in the same place.
  //
  // A kind this page has no label for still gets a lane, after the known ones:
  // a task the backend added and the UI has not caught up with is exactly the
  // thing a page about what ran must not hide.
  const known = TASK_KINDS.filter((kind) => lanes.has(kind));
  const unknown = [...lanes.keys()].filter((kind) => !TASK_KIND_META[kind]).sort();
  return [...known, ...unknown].map((kind) => lanes.get(kind));
}

function taskTimeline(data) {
  const lanes = taskLanes(data.runs);
  if (!lanes.length) {
    return sectionCard('Timeline', null,
      h('p', { class: 'text-sm text-base-content/50 py-4' },
        'No runs in this window match these filters.'));
  }

  const start = Date.parse(data.window_start);
  const end = Date.parse(data.window_end);
  const span = Math.max(end - start, 1);
  const pct = (t) => ((t - start) / span) * 100;

  // One tooltip for the whole chart rather than one per bar: there are hundreds
  // of bars and only ever one under the pointer.
  const tip = h('div', {
    class: 'pointer-events-none absolute z-20 hidden max-w-xs rounded-lg '
      + 'border border-base-300 bg-base-100 px-2.5 py-1.5 shadow-lg',
  });

  const lane = (l) =>
    h('div', { class: 'flex items-center gap-2 py-0.5' },
      h('div', { class: 'w-40 sm:w-56 flex-none min-w-0' },
        h('div', { class: 'text-xs truncate', title: kindMeta(l.kind).help },
          kindMeta(l.kind).label),
        h('div', { class: 'text-[10px] text-base-content/50 truncate' },
          laneSubtitle(l))),
      // The track is the lane's time axis; a bar is positioned and sized on it
      // as a percentage, so the whole thing reflows with the window.
      h('div', { class: 'relative flex-1 h-5 rounded bg-base-300/40 overflow-hidden' },
        l.runs.map((run) => taskBar(run, pct, tip))));

  return sectionCard(
    `Timeline (last ${windowLabel(data.hours)})`,
    'One row per task kind. Bar position is when the pass ran, bar width is how '
      + 'long it took. Hover a bar for what that pass was working on.',
    timelineAxis(start, end),
    h('div', { class: 'relative' },
      h('div', { class: 'flex flex-col' }, lanes.map(lane)),
      tip),
    timelineLegend());
}

// What a collapsed lane is covering: how many sources or feeds, and how many
// passes over them. Naming the count is what tells the reader the lane holds
// more than one thing and is worth hovering.
function laneSubtitle(l) {
  const runs = `${fmtInt(l.runs.length)} run${l.runs.length === 1 ? '' : 's'}`;
  if (l.systemWide) return `system-wide · ${runs}`;
  const noun = l.kind === KIND_SOURCE_INGEST ? 'source' : 'feed';
  const n = l.targets.size;
  if (!n) return runs;
  return `${fmtInt(n)} ${noun}${n === 1 ? '' : 's'} · ${runs}`;
}

// The hover layer. Positioned against the lane stack, and clamped so a bar at
// either edge does not push the tooltip off the card.
function showBarTip(tip, bar, run) {
  const meta = statusMeta(run.status);
  render(tip,
    h('div', { class: 'text-xs font-medium' },
      run.target || kindMeta(run.kind).label),
    h('div', { class: 'text-[11px] text-base-content/70' },
      h('span', { class: meta.text }, meta.mark),
      ' ', meta.label, ' · ', fmtDuration(run.duration_seconds),
      run.target ? ` · ${kindMeta(run.kind).label}` : null),
    h('div', { class: 'text-[10px] text-base-content/50' },
      new Date(run.started_at).toLocaleString()),
    run.detail
      ? h('div', { class: 'text-[10px] text-base-content/60 mt-1' }, run.detail)
      : null);

  tip.classList.remove('hidden');

  const box = tip.offsetParent.getBoundingClientRect();
  const at = bar.getBoundingClientRect();
  const left = Math.max(0, Math.min(
    box.width - tip.offsetWidth,
    at.left - box.left + at.width / 2 - tip.offsetWidth / 2));
  // Above the bar by default, below it for the top lane where there is no room.
  const above = at.top - box.top - tip.offsetHeight - 6;
  tip.style.left = `${left}px`;
  tip.style.top = `${above < 0 ? at.bottom - box.top + 6 : above}px`;
}

function taskBar(run, pct, tip) {
  const startedAt = Date.parse(run.started_at);
  const finishedAt = run.finished_at ? Date.parse(run.finished_at) : Date.now();
  const left = Math.max(0, Math.min(100, pct(startedAt)));
  // A pass that took under a second would otherwise be a zero-width bar and so
  // invisible -- and "it ran, very briefly" is exactly what this page is for.
  // The floor is in pixels rather than percent so it holds at every window.
  const width = Math.max(0, Math.min(100 - left, pct(finishedAt) - left));
  const meta = statusMeta(run.status);

  // Now that lanes are per kind, the target is only readable on hover, so this
  // is the custom layer rather than a native title: a browser tooltip waits
  // about a second and cannot be styled, which is too slow for running along a
  // lane to see which source ran when. The table view carries the same columns
  // for anyone not using a pointer.
  const bar = h('span', {
    // 2px ring in the surface colour so bars that abut stay countable, and
    // rounded ends per the mark spec.
    class: `absolute top-0.5 bottom-0.5 rounded ${meta.bar} ring-1 ring-base-100`,
    style: `left:${left}%;width:${width}%;min-width:3px`,
    onmouseenter: () => showBarTip(tip, bar, run),
    onmouseleave: () => tip.classList.add('hidden'),
  });
  return bar;
}

// A hairline axis with a handful of ticks -- recessive, never dashed, and
// labelled in the reader's own locale rather than UTC.
//
// Each label is positioned on the track rather than laid out in an equal-width
// cell: six labels in six cells put the last one at five sixths of the width,
// so every tick sat to the left of the time it named. The end labels are pulled
// back inside the track so neither overhangs it.
function timelineAxis(start, end) {
  const ticks = 5;
  const labels = [];
  for (let i = 0; i <= ticks; i += 1) {
    const at = new Date(start + ((end - start) * i) / ticks);
    const left = (i / ticks) * 100;
    const shift = i === 0 ? '0' : i === ticks ? '-100%' : '-50%';
    labels.push(h('span', {
      class: 'absolute bottom-0 text-[10px] text-base-content/40 whitespace-nowrap',
      style: `left:${left}%;transform:translateX(${shift})`,
    }, at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })));
  }
  return h('div', { class: 'flex items-end gap-2 mb-1' },
    h('div', { class: 'w-40 sm:w-56 flex-none' }),
    h('div', { class: 'relative flex-1 h-4 border-b border-base-300' }, labels));
}

function timelineLegend() {
  return h('div', { class: 'flex flex-wrap items-center gap-4 mt-2' },
    Object.entries(TASK_STATUS_META).map(([, meta]) =>
      h('span', { class: 'flex items-center gap-1.5 text-xs text-base-content/60' },
        h('span', { class: `w-3 h-2 rounded ${meta.bar}` }),
        meta.label)));
}

// ---------- table ----------

function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  if (seconds < 1) return '<1s';
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

// The table view the timeline owes the reader: every bar as a row, with the
// detail line that does not fit on a bar.
function taskTable(data) {
  if (!data.runs.length) {
    return sectionCard('Runs', null,
      h('p', { class: 'text-sm text-base-content/50 py-4' },
        'No runs in this window match these filters.'));
  }

  const row = (run) => {
    const meta = statusMeta(run.status);
    return h('tr', {},
      h('td', { class: 'text-xs whitespace-nowrap' },
        h('span', { class: `${meta.text} mr-1` }, meta.mark),
        meta.label),
      h('td', { class: 'text-xs' }, kindMeta(run.kind).label),
      h('td', { class: 'text-xs' },
        run.target
          ? h('span', { class: 'truncate' }, run.target)
          : h('span', { class: 'text-base-content/40' }, 'system-wide')),
      h('td', { class: 'text-xs whitespace-nowrap text-right tabular-nums' },
        fmtDuration(run.duration_seconds)),
      h('td', { class: 'text-xs whitespace-nowrap text-base-content/60' },
        timeAgo(run.started_at)),
      h('td', { class: 'text-xs text-base-content/60' }, run.detail || '—'));
  };

  // A busy install puts hundreds of passes in a day and the row limit allows
  // thousands, so the rows scroll inside the card rather than pushing the
  // per-task rollup off the bottom of the page. The header sticks so the
  // columns are still named at row four hundred.
  const th = (label, extra = '') =>
    h('th', { class: `sticky top-0 z-10 bg-base-200 ${extra}` }, label);

  return sectionCard(`Runs (last ${windowLabel(data.hours)})`,
    `${fmtInt(data.runs.length)} pass${data.runs.length === 1 ? '' : 'es'}, newest first.`,
    h('div', {
      class: 'max-h-[70vh] overflow-auto border border-base-300 rounded-lg',
    },
      h('table', { class: 'table table-xs' },
        h('thead', {},
          h('tr', {},
            th('Status'),
            th('Task'),
            th('Target'),
            th('Took', 'text-right'),
            th('Started'),
            th('Detail'))),
        h('tbody', {}, data.runs.map(row)))));
}

// Per-kind rollup, which answers "how expensive is this task" in a way a
// timeline of individual bars cannot. Always shown: it is the summary the
// timeline is a detail of, and it stays correct when the rows are truncated.
function taskKindTable(data) {
  if (!data.kinds.length) return null;

  const row = (k) =>
    h('tr', {},
      h('td', { class: 'text-xs' },
        h('div', { title: kindMeta(k.kind).help }, kindMeta(k.kind).label),
        k.system_wide
          ? h('div', { class: 'text-[10px] text-base-content/50' }, 'system-wide')
          : null),
      h('td', { class: 'text-right text-xs tabular-nums' }, fmtInt(k.runs)),
      h('td', { class: 'text-right text-xs tabular-nums' },
        k.errors
          ? h('span', { class: 'text-error' }, fmtInt(k.errors))
          : h('span', { class: 'text-base-content/40' }, '0')),
      h('td', { class: 'text-right text-xs tabular-nums' },
        fmtDuration(k.median_seconds)),
      h('td', { class: 'text-right text-xs tabular-nums' },
        fmtDuration(k.max_seconds)),
      h('td', { class: 'text-right text-xs whitespace-nowrap text-base-content/60' },
        k.last_started_at ? timeAgo(k.last_started_at) : '—'));

  return sectionCard('By task',
    'Counted over the whole window, so these stay right even when the timeline is cut short.',
    h('div', { class: 'overflow-x-auto' },
      h('table', { class: 'table table-xs' },
        h('thead', {},
          h('tr', {},
            h('th', {}, 'Task'),
            h('th', { class: 'text-right' }, 'Runs'),
            h('th', { class: 'text-right' }, 'Failed'),
            h('th', { class: 'text-right', title: 'Half of the passes finished faster than this' }, 'Median'),
            h('th', { class: 'text-right' }, 'Slowest'),
            h('th', { class: 'text-right' }, 'Last run'))),
        h('tbody', {}, data.kinds.map(row)))));
}
