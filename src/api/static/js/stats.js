// Aggy article-stats page: cross-feed coverage numbers for every site the
// user's articles link to. Built on core.js (h/render) and the generated sdk.
// Reached from the link at the bottom of the dashboard (#/stats).

'use strict';

const STATS_TIMELINE_DAYS = 30;
const STATS_ROW_LIMIT = 25; // rows shown before "show all"

let articleStats = null;
let statsSort = { key: 'article_count', dir: 'desc' };
let statsFilter = '';
let statsShowAll = false;
let statsTimelineMetric = 'with_text_embedding';

// ---------- small helpers ----------

const SVG_NS = 'http://www.w3.org/2000/svg';

// SVG twin of core.js's h(): elements in the SVG namespace, same prop rules.
function svg(tag, props, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? '' : value);
  }
  el.append(...children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false));
  return el;
}

const fmtInt = (n) => Number(n || 0).toLocaleString();

// 940 -> "940", 1240 -> "1.2k", 25400 -> "25k"
function fmtCompact(n) {
  if (n == null) return '—';
  if (n < 1000) return String(Math.round(n));
  if (n < 10000) return `${(n / 1000).toFixed(1)}k`;
  return `${Math.round(n / 1000)}k`;
}

const pct = (part, total) => (total ? (part / total) * 100 : 0);
const fmtPct = (part, total) => (total ? `${Math.round(pct(part, total))}%` : '—');

// Smallest 1/2/5 x 10^k at or above v — keeps y-axis ticks on round numbers.
function niceCeil(v) {
  if (v <= 1) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(v));
  for (const step of [1, 2, 5, 10]) {
    if (v <= step * magnitude) return step * magnitude;
  }
  return 10 * magnitude;
}

// "2026-08-11" -> Date at local midnight (never parse as UTC: that shifts the
// day backwards for anyone west of Greenwich and mislabels the whole axis).
function parseDay(day) {
  const [y, m, d] = String(day).split('-').map(Number);
  return new Date(y, m - 1, d);
}

const dayLabel = (day) =>
  parseDay(day).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

// ---------- metric definitions ----------

// The coverage metrics, in the order they appear in the overview chart and as
// the columns of the per-site table. `meter` marks the three headline ones,
// which also get a bar in the table.
const COVERAGE_METRICS = [
  {
    key: 'with_preview_image',
    label: 'Preview image',
    short: 'Preview img',
    meter: true,
    help: 'Article has a preview picture — its own image, or the first image in the body',
  },
  {
    key: 'with_image_embedding',
    label: 'Image embedding',
    short: 'Image emb',
    meter: true,
    help: 'The preview picture has been embedded by the CLIP image model',
  },
  {
    key: 'with_text_embedding',
    label: 'Text embedding',
    short: 'Text emb',
    meter: true,
    help: 'The article text has been embedded by the Ollama embedding model',
  },
  {
    key: 'with_media',
    label: 'Rich media',
    short: 'Media',
    help: 'Article carries a gif, video, or gallery pulled in at ingest',
  },
  {
    key: 'with_content',
    label: 'Article body',
    short: 'Body',
    help: 'Article has body content, not just a title and a link',
  },
  {
    key: 'with_excerpt',
    label: 'Excerpt',
    short: 'Excerpt',
    help: 'Article has a short summary line',
  },
  {
    key: 'with_author',
    label: 'Author',
    short: 'Author',
    help: 'Article names an author',
  },
  {
    key: 'with_date_published',
    label: 'Publish date',
    short: 'Date',
    help: 'Article carries a publication date',
  },
];

// Which coverage the daily chart shades in; the rest of the column is the
// uncovered remainder.
const TIMELINE_METRICS = [
  { key: 'with_text_embedding', label: 'Text embedded' },
  { key: 'with_image_embedding', label: 'Image embedded' },
  { key: 'with_preview_image', label: 'Has preview image' },
];

// ---------- page ----------

async function showArticleStats() {
  setView('stats');
  currentFeed = null;
  currentList = null;
  render($('statsPageBody'), spinner());
  await loadArticleStats();
}

async function loadArticleStats() {
  try {
    articleStats = await sdk.statsArticles({ timeline_days: STATS_TIMELINE_DAYS });
    renderArticleStats();
  } catch (err) {
    render($('statsPageBody'),
      h('div', { class: 'text-center py-16 text-base-content/50' }, 'Failed to load article stats'));
    toast(err.message, 'alert-error');
  }
}

async function refreshArticleStats() {
  const btn = $('statsRefreshBtn');
  btn.disabled = true;
  try {
    await loadArticleStats();
  } finally {
    btn.disabled = false;
  }
}

function renderArticleStats() {
  const { summary, domains, timeline } = articleStats;

  if (!summary.total_articles) {
    render($('statsPageBody'),
      emptyState('\u{1F4CA}', 'No articles yet',
        'Once your feeds pull in articles, this page breaks them down by the site they link to.',
        h('a', { class: 'btn btn-primary btn-sm', href: '#/' }, 'Back to your feeds')));
    return;
  }

  render($('statsPageBody'),
    summaryTiles(summary),
    statsCard('Coverage across all articles',
      'Share of your articles that carry each field — the gaps are what the recommender is missing.',
      coverageChart(summary)),
    statsCard(`Articles collected per day (last ${STATS_TIMELINE_DAYS} days)`,
      'How many articles arrived each day, and how many of them the pipeline has processed.',
      timelineChart(timeline)),
    statsCard('By site',
      `${fmtInt(domains.length)} ${domains.length === 1 ? 'site' : 'sites'}, grouped by the base domain of each article's link.`,
      domainTable(summary, domains)));
}

// A titled section wrapper, so every block on the page reads the same.
function statsCard(title, subtitle, ...body) {
  return h('div', { class: 'card bg-base-200 border border-base-300 mb-4' },
    h('div', { class: 'card-body p-4 gap-3' },
      h('div', {},
        h('h2', { class: 'font-semibold' }, title),
        subtitle ? h('p', { class: 'text-xs text-base-content/60 mt-0.5' }, subtitle) : null),
      ...body));
}

// ---------- summary tiles ----------

function summaryTiles(summary) {
  const total = summary.total_articles;
  const tile = (label, value, desc, hero) =>
    h('div', { class: 'stat py-3 px-4' },
      h('div', { class: 'stat-title text-xs' }, label),
      h('div', { class: `stat-value ${hero ? 'text-3xl' : 'text-xl'}` }, value),
      desc ? h('div', { class: 'stat-desc text-xs' }, desc) : null);

  const coverageTile = (metric) =>
    tile(metric.label, fmtPct(summary[metric.key], total),
      `${fmtInt(summary[metric.key])} of ${fmtInt(total)}`);

  return h('div', { class: 'stats stats-vertical sm:stats-horizontal shadow-none border border-base-300 w-full mb-4 overflow-x-auto' },
    tile('Articles', fmtInt(total),
      summary.last_added_at ? `newest ${timeAgo(summary.last_added_at)}` : null, true),
    tile('Sites', fmtInt(summary.domain_count),
      summary.avg_content_chars ? `${fmtCompact(summary.avg_content_chars)} chars avg body` : null),
    ...COVERAGE_METRICS.filter((m) => m.meter).map(coverageTile));
}

// ---------- coverage chart ----------

// Horizontal meters, one per field: a single measure (share of articles), so
// one colour throughout — the labels carry identity, not hue.
function coverageChart(summary) {
  const total = summary.total_articles;
  const row = (metric) => {
    const value = summary[metric.key];
    return h('div', { class: 'flex items-center gap-3', title: metric.help },
      h('span', { class: 'text-xs text-base-content/70 w-28 flex-none' }, metric.label),
      h('span', { class: 'h-2 flex-1 rounded bg-base-300 overflow-hidden' },
        h('span', {
          class: 'block h-full rounded-r bg-primary',
          style: `width:${pct(value, total).toFixed(1)}%`,
        })),
      h('span', { class: 'text-xs tabular-nums w-24 text-right text-base-content/70' },
        `${fmtPct(value, total)} · ${fmtInt(value)}`));
  };

  // The image-embedding gap has two very different halves: pictures still
  // queued for the embedder, and pictures it has given up on after repeated
  // failed downloads. Only the first one closes by waiting, so say which.
  const failed = summary.image_embed_failed || 0;
  const note = failed
    ? h('p', { class: 'text-xs text-base-content/50 mt-1' },
      `${fmtInt(failed)} preview ${failed === 1 ? 'image' : 'images'} could not be ` +
      'downloaded after repeated tries and are no longer queued for embedding ' +
      '— usually expired or deleted images at the source.')
    : null;

  return h('div', { class: 'flex flex-col gap-2' }, COVERAGE_METRICS.map(row), note);
}

// ---------- daily timeline chart ----------

function timelineChart(timeline) {
  const metric = TIMELINE_METRICS.find((m) => m.key === statsTimelineMetric) || TIMELINE_METRICS[0];

  // plain wrapping buttons rather than a daisyUI join: a join keeps its
  // buttons on one line, which runs off the card on a phone
  const picker = h('div', { class: 'flex flex-wrap gap-1' },
    TIMELINE_METRICS.map((m) =>
      h('button', {
        class: `btn btn-xs ${m.key === metric.key ? 'btn-active' : ''}`,
        onclick: () => { statsTimelineMetric = m.key; renderArticleStats(); },
      }, m.label)));

  const legend = h('div', { class: 'flex items-center gap-4 text-xs text-base-content/60' },
    h('span', { class: 'flex items-center gap-1.5' },
      h('span', { class: 'w-2.5 h-2.5 rounded-sm bg-primary' }), metric.label),
    h('span', { class: 'flex items-center gap-1.5' },
      h('span', { class: 'w-2.5 h-2.5 rounded-sm bg-base-content/25' }), 'Not yet'));

  return h('div', { class: 'flex flex-col gap-3' },
    h('div', { class: 'flex flex-wrap items-center justify-between gap-2' }, picker, legend),
    timelinePlot(timeline, metric));
}

// Column chart: one column per day, split into the covered part (bottom) and
// the remainder (top), with a hover tooltip per day.
function timelinePlot(timeline, metric) {
  const W = 640;
  const H = 180;
  const pad = { top: 10, right: 6, bottom: 22, left: 36 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;

  const max = niceCeil(Math.max(...timeline.map((p) => p.article_count), 0));
  const band = plotW / timeline.length;
  const barW = Math.max(2, Math.min(24, band - 4));
  const y = (value) => pad.top + plotH - (value / max) * plotH;

  // rounded cap on the data-end only; the baseline end stays square
  const cappedColumn = (x, top, bottom, w) => {
    const height = Math.max(0, bottom - top);
    const r = Math.min(4, w / 2, height);
    return `M${x},${bottom} L${x},${top + r} Q${x},${top} ${x + r},${top} ` +
      `L${x + w - r},${top} Q${x + w},${top} ${x + w},${top + r} L${x + w},${bottom} Z`;
  };

  const gridlines = [0, 0.5, 1].map((f) =>
    svg('line', {
      x1: pad.left, x2: W - pad.right, y1: y(max * f), y2: y(max * f),
      class: 'stroke-base-300', 'stroke-width': 1,
    }));

  const yTicks = [0, 0.5, 1].map((f) =>
    svg('text', {
      x: pad.left - 6, y: y(max * f) + 3, 'text-anchor': 'end',
      class: 'fill-base-content/50 text-[11px] tabular-nums',
    }, fmtInt(Math.round(max * f))));

  // label roughly weekly, and always the last day
  const xTicks = timeline.map((point, i) => {
    const last = i === timeline.length - 1;
    if (!last && (i % 7 !== 0 || i > timeline.length - 4)) return null;
    return svg('text', {
      x: pad.left + i * band + band / 2, y: H - 6,
      'text-anchor': last ? 'end' : 'middle',
      class: 'fill-base-content/50 text-[11px]',
    }, dayLabel(point.day));
  });

  const columns = timeline.map((point, i) => {
    const x = pad.left + i * band + (band - barW) / 2;
    if (!point.article_count) return null;

    const covered = Math.min(point[metric.key], point.article_count);
    const baseline = y(0);
    const topOfAll = y(point.article_count);
    const topOfCovered = y(covered);
    const parts = [];

    if (covered > 0) {
      // covered segment sits on the baseline; it only gets the rounded cap
      // when nothing is stacked above it
      const capped = covered === point.article_count;
      parts.push(svg('path', {
        d: capped
          ? cappedColumn(x, topOfCovered, baseline, barW)
          : `M${x},${topOfCovered} h${barW} v${baseline - topOfCovered} h${-barW} Z`,
        class: 'fill-primary',
      }));
    }
    if (covered < point.article_count) {
      // 2px of surface separates the two segments instead of a stroke
      const gap = covered > 0 ? 2 : 0;
      parts.push(svg('path', {
        d: cappedColumn(x, topOfAll, Math.max(topOfAll, topOfCovered - gap), barW),
        class: 'fill-base-content/25',
      }));
    }
    return parts;
  });

  const tooltip = h('div', {
    class: 'pointer-events-none absolute hidden z-10 rounded-lg border border-base-300 ' +
      'bg-base-100 px-2 py-1.5 text-xs shadow-lg whitespace-nowrap',
  });

  const showTip = (point, i) => {
    render(tooltip,
      h('div', { class: 'font-semibold' }, dayLabel(point.day)),
      h('div', { class: 'text-base-content/70' },
        `${fmtInt(point.article_count)} ${point.article_count === 1 ? 'article' : 'articles'}`),
      h('div', { class: 'text-base-content/70' },
        `${metric.label}: ${fmtInt(point[metric.key])} (${fmtPct(point[metric.key], point.article_count)})`));
    tooltip.classList.remove('hidden');
    // keep the box inside the chart at either end instead of letting it hang
    // off the card
    const x = ((i + 0.5) / timeline.length) * 100;
    tooltip.style.left = `${Math.min(Math.max(x, 18), 82)}%`;
    tooltip.style.top = '0';
    tooltip.style.transform = 'translate(-50%, 0)';
  };

  // full-height hit bands: a 2px column is far too small to aim at
  const hitBands = timeline.map((point, i) =>
    svg('rect', {
      x: pad.left + i * band, y: pad.top, width: band, height: plotH,
      class: 'fill-base-content/0 hover:fill-base-content/5',
      'pointer-events': 'all',
      onmouseenter: () => showTip(point, i),
      onfocus: () => showTip(point, i),
      tabindex: '0',
    },
    svg('title', {},
      `${dayLabel(point.day)}: ${fmtInt(point.article_count)} articles, ` +
      `${fmtInt(point[metric.key])} ${metric.label.toLowerCase()}`)));

  const plot = svg('svg', {
    viewBox: `0 0 ${W} ${H}`, class: 'w-full h-44', role: 'img',
    'aria-label': `Articles collected per day over the last ${STATS_TIMELINE_DAYS} days`,
  }, gridlines, yTicks, xTicks, columns, hitBands);

  // The plot keeps a minimum width and the wrapper scrolls, so the day labels
  // stay readable on a phone instead of being squeezed to a few pixels.
  return h('div', { class: 'overflow-x-auto' },
    h('div', {
      class: 'relative min-w-[480px]',
      onmouseleave: () => tooltip.classList.add('hidden'),
    }, tooltip, plot));
}

// ---------- per-site table ----------

// Sort keys that are shares rather than raw counts, so "80% of 5" doesn't
// outrank "78% of 4,000" by accident — ties fall back to article count.
function domainSortValue(row, key) {
  if (key === 'domain') return row.domain;
  if (key === 'article_count' || key === 'avg_content_chars') return row[key] ?? -1;
  if (key === 'last_added_at') return row.last_added_at ? Date.parse(row.last_added_at) : -1;
  if (key === 'votes') return row.up_votes + row.down_votes + row.neutral_votes;
  return pct(row[key], row.article_count);
}

function sortedDomains(domains) {
  const { key, dir } = statsSort;
  const factor = dir === 'asc' ? 1 : -1;
  const term = statsFilter.trim().toLowerCase();
  const rows = term ? domains.filter((row) => row.domain.includes(term)) : domains.slice();

  return rows.sort((a, b) => {
    const av = domainSortValue(a, key);
    const bv = domainSortValue(b, key);
    if (av < bv) return -1 * factor;
    if (av > bv) return 1 * factor;
    return b.article_count - a.article_count;
  });
}

function sortHeader(label, key, { help, align = 'right' } = {}) {
  const active = statsSort.key === key;
  return h('th', { class: align === 'right' ? 'text-right' : '', title: help },
    h('button', {
      class: `inline-flex items-center gap-1 hover:text-base-content ${active ? 'text-base-content' : ''}`,
      onclick: () => {
        statsSort = active
          ? { key, dir: statsSort.dir === 'asc' ? 'desc' : 'asc' }
          : { key, dir: key === 'domain' ? 'asc' : 'desc' };
        rerenderDomainTable();
      },
    }, label, active ? h('span', {}, statsSort.dir === 'asc' ? '↑' : '↓') : null));
}

// A percentage cell; the headline metrics also carry a small meter.
function pctCell(part, total, withMeter) {
  const label = h('span', { class: 'tabular-nums' }, fmtPct(part, total));
  if (!withMeter) return h('td', { class: 'text-right text-xs' }, label);
  return h('td', { class: 'text-right text-xs' },
    h('div', { class: 'flex items-center justify-end gap-2' },
      label,
      h('span', { class: 'h-1.5 w-10 rounded bg-base-300 overflow-hidden flex-none' },
        h('span', {
          class: 'block h-full rounded-r bg-primary',
          style: `width:${pct(part, total).toFixed(1)}%`,
        }))));
}

// Sorting, filtering and "show all" only touch the table, so they re-render
// this host element rather than the whole page — the filter box keeps focus
// and the charts don't flicker on every keystroke.
let statsTableHost = null;

function rerenderDomainTable() {
  if (!statsTableHost || !articleStats) return;
  render(statsTableHost, domainTableBody(articleStats.summary, articleStats.domains));
}

function domainTable(summary, domains) {
  statsTableHost = h('div', {});
  render(statsTableHost, domainTableBody(summary, domains));

  const filterInput = h('input', {
    type: 'search', class: 'input input-bordered input-sm w-full sm:w-64',
    placeholder: 'Filter sites…', value: statsFilter,
    oninput: debounce((e) => {
      statsFilter = e.target.value;
      statsShowAll = false;
      rerenderDomainTable();
    }, 200),
  });

  return h('div', { class: 'flex flex-col gap-3' }, filterInput, statsTableHost);
}

function domainTableBody(summary, domains) {
  const rows = sortedDomains(domains);
  const shown = statsShowAll ? rows : rows.slice(0, STATS_ROW_LIMIT);
  const total = summary.total_articles;

  const domainRow = (row) =>
    h('tr', {},
      h('td', { class: 'font-medium text-xs' }, row.domain),
      h('td', { class: 'text-right text-xs' },
        h('div', { class: 'flex items-center justify-end gap-2' },
          h('span', { class: 'tabular-nums' }, fmtInt(row.article_count)),
          h('span', { class: 'h-1.5 w-12 rounded bg-base-300 overflow-hidden flex-none' },
            h('span', {
              class: 'block h-full rounded-r bg-primary',
              style: `width:${pct(row.article_count, total).toFixed(1)}%`,
            })))),
      COVERAGE_METRICS.map((m) => pctCell(row[m.key], row.article_count, m.meter)),
      h('td', { class: 'text-right text-xs tabular-nums' }, fmtCompact(row.avg_content_chars)),
      h('td', { class: 'text-right text-xs tabular-nums whitespace-nowrap' },
        row.up_votes || row.down_votes
          ? h('span', {},
              h('span', { class: 'text-success' }, `▲${row.up_votes}`),
              ' ',
              h('span', { class: 'text-error' }, `▼${row.down_votes}`))
          : h('span', { class: 'text-base-content/40' }, '—')),
      h('td', { class: 'text-right text-xs whitespace-nowrap text-base-content/60' },
        row.last_added_at ? timeAgo(row.last_added_at) : '—'));

  const totalsRow = h('tr', { class: 'border-t-2 border-base-300 font-semibold' },
    h('td', { class: 'text-xs' }, 'All sites'),
    h('td', { class: 'text-right text-xs tabular-nums' }, fmtInt(total)),
    COVERAGE_METRICS.map((m) =>
      h('td', { class: 'text-right text-xs tabular-nums' }, fmtPct(summary[m.key], total))),
    h('td', { class: 'text-right text-xs tabular-nums' }, fmtCompact(summary.avg_content_chars)),
    h('td', { class: 'text-right text-xs tabular-nums whitespace-nowrap' },
      h('span', { class: 'text-success' }, `▲${summary.up_votes}`),
      ' ',
      h('span', { class: 'text-error' }, `▼${summary.down_votes}`)),
    h('td', { class: 'text-right text-xs text-base-content/60' },
      summary.last_added_at ? timeAgo(summary.last_added_at) : '—'));

  return h('div', { class: 'flex flex-col gap-3' },
    rows.length
      ? h('div', { class: 'overflow-x-auto' },
          h('table', { class: 'table table-xs' },
            h('thead', {},
              h('tr', {},
                sortHeader('Site', 'domain', { align: 'left' }),
                sortHeader('Articles', 'article_count', { help: 'Articles linking to this site' }),
                COVERAGE_METRICS.map((m) => sortHeader(m.short, m.key, { help: m.help })),
                sortHeader('Body', 'avg_content_chars', { help: 'Average body length in characters' }),
                sortHeader('Votes', 'votes', { help: 'Your up and down votes on articles from this site' }),
                sortHeader('Newest', 'last_added_at', { help: 'When the most recent article arrived' }))),
            h('tbody', {}, shown.map(domainRow), statsShowAll || rows.length <= STATS_ROW_LIMIT ? totalsRow : null)))
      : h('p', { class: 'text-sm text-base-content/50 py-4' }, 'No sites match that filter.'),
    rows.length > STATS_ROW_LIMIT
      ? h('button', {
          class: 'btn btn-ghost btn-sm self-center',
          onclick: () => { statsShowAll = !statsShowAll; rerenderDomainTable(); },
        }, statsShowAll ? 'Show top sites only' : `Show all ${fmtInt(rows.length)} sites`)
      : null);
}
