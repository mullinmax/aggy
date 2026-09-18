// The feed's similarity graph, drawn.
//
// Every article Aggy has placed carries a short list of the articles most like
// it (see src/api/neighbors). Those links are a real structure — the duplicate
// check walks them, the recommender reads votes across them, the reader shows
// them beside an article — but until now the only way to see one was an article
// at a time. This draws the whole thing: what clusters your feed has, which
// sources cover the same ground, and where the copies of one story sit.
//
// Positions come from a force simulation over the links themselves and nothing
// else. Two articles end up near each other because Aggy linked them, not
// because a projection put them there — so what you are looking at is the graph
// the rest of the system actually uses.
//
// Drawn on a canvas rather than as SVG: a thousand nodes and five thousand
// edges is five thousand DOM nodes to update sixty times a second during the
// layout, and that is where an SVG version falls over. The cost is hit-testing
// by hand, which is the `nodeAt` function below and not much else.

// ---------- force layout ----------

// How far apart the springs try to hold a pair, in world units. A more similar
// pair is pulled tighter, so the distance on screen carries the same meaning as
// the number: near means alike.
const GRAPH_LINK_MIN = 26;
const GRAPH_LINK_SPREAD = 220;

// Barnes-Hut opening angle. Below this ratio of cell size to distance, a whole
// cell of articles is treated as one lump rather than visited node by node —
// which is what turns the repulsion from "every pair, every tick" into
// something that can carry a thousand nodes. 0.9 is loose enough to be quick
// and tight enough that clusters still separate properly.
const GRAPH_THETA = 0.9;
const GRAPH_MAX_DEPTH = 22;

// One cell of the quadtree. A cell either holds points directly (a leaf) or
// four children, never both.
function graphCell(x, y, size) {
  return { x, y, size, kids: null, points: [], mass: 0, cx: 0, cy: 0 };
}

function graphQuadrant(cell, node) {
  const half = cell.size / 2;
  return (node.x >= cell.x + half ? 1 : 0) + (node.y >= cell.y + half ? 2 : 0);
}

function graphSubdivide(cell) {
  const half = cell.size / 2;
  cell.kids = [
    graphCell(cell.x, cell.y, half),
    graphCell(cell.x + half, cell.y, half),
    graphCell(cell.x, cell.y + half, half),
    graphCell(cell.x + half, cell.y + half, half),
  ];
  cell.points = null;
}

function graphInsert(cell, node, depth) {
  if (cell.kids) {
    graphInsert(cell.kids[graphQuadrant(cell, node)], node, depth + 1);
    return;
  }
  cell.points.push(node);
  // Split once a leaf holds more than one point — unless we are as deep as we
  // go, which happens when articles land on exactly the same spot. There the
  // leaf simply keeps the pile, and the repulsion treats it as one lump.
  if (cell.points.length > 1 && depth < GRAPH_MAX_DEPTH) {
    const held = cell.points;
    graphSubdivide(cell);
    for (const point of held) {
      graphInsert(cell.kids[graphQuadrant(cell, point)], point, depth + 1);
    }
  }
}

// Mass and centre of mass, bottom up. Done as its own pass rather than during
// insertion because a split moves points between cells, and totals maintained
// on the way down would have to be unwound.
function graphSummarize(cell) {
  if (!cell.kids) {
    cell.mass = cell.points.length;
    if (!cell.mass) return;
    let sx = 0;
    let sy = 0;
    for (const point of cell.points) { sx += point.x; sy += point.y; }
    cell.cx = sx / cell.mass;
    cell.cy = sy / cell.mass;
    return;
  }
  let mass = 0;
  let sx = 0;
  let sy = 0;
  for (const kid of cell.kids) {
    graphSummarize(kid);
    if (!kid.mass) continue;
    mass += kid.mass;
    sx += kid.cx * kid.mass;
    sy += kid.cy * kid.mass;
  }
  cell.mass = mass;
  if (mass) { cell.cx = sx / mass; cell.cy = sy / mass; }
}

function graphBuildTree(nodes) {
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const node of nodes) {
    if (node.x < x0) x0 = node.x;
    if (node.y < y0) y0 = node.y;
    if (node.x > x1) x1 = node.x;
    if (node.y > y1) y1 = node.y;
  }
  // a square root cell, padded so a point never sits exactly on the far edge
  const size = Math.max(x1 - x0, y1 - y0, 1) * 1.05;
  const root = graphCell(x0 - 1, y0 - 1, size + 2);
  for (const node of nodes) graphInsert(root, node, 0);
  graphSummarize(root);
  return root;
}

// Push one node away from everything else, approximating distant crowds.
function graphRepel(cell, node, strength) {
  if (!cell.mass) return;
  let dx = cell.cx - node.x;
  let dy = cell.cy - node.y;
  let d2 = dx * dx + dy * dy;

  // Two articles on exactly the same spot have no direction to separate along,
  // which is the normal case for a pair of near-identical duplicates. Nudge
  // them apart randomly rather than dividing by zero.
  if (d2 < 1e-6) {
    dx = Math.random() - 0.5;
    dy = Math.random() - 0.5;
    d2 = dx * dx + dy * dy || 1e-6;
  }

  const faraway = cell.size * cell.size < GRAPH_THETA * GRAPH_THETA * d2;
  if (cell.kids && !faraway) {
    for (const kid of cell.kids) graphRepel(kid, node, strength);
    return;
  }
  if (!cell.kids && cell.points.length === 1 && cell.points[0] === node) return;

  const d = Math.sqrt(d2);
  // inverse-square, then a further division by d to normalise the direction
  const force = (strength * cell.mass) / (d2 * d);
  node.vx -= dx * force;
  node.vy -= dy * force;
}

// One step of the simulation. Returns the alpha it leaves behind, so the caller
// can tell a settled layout from a moving one.
function graphTick(nodes, edges, alpha) {
  // Repulsion beats gravity by enough that clusters push apart rather than
  // settling into one disc. Gravity is only here to stop parts of the graph
  // that share no links drifting off screen forever.
  const strength = 420;
  const spring = 0.08;
  const damping = 0.82;
  const gravity = 0.006;

  const tree = graphBuildTree(nodes);
  for (const node of nodes) {
    if (node.pinned) continue;
    graphRepel(tree, node, strength * alpha);
  }

  for (const edge of edges) {
    const a = edge.a;
    const b = edge.b;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const d = Math.hypot(dx, dy) || 0.01;
    // Stiffness follows the similarity, not just the rest length. With every
    // link pulling equally hard, a loose association drags two articles as
    // firmly together as a near-identical pair does, and the whole feed balls
    // up — which is exactly what it did before this line.
    const pull = ((d - edge.length) / d) * spring * (edge.strength ?? 1) * alpha;
    if (!a.pinned) { a.vx += dx * pull; a.vy += dy * pull; }
    if (!b.pinned) { b.vx -= dx * pull; b.vy -= dy * pull; }
  }

  // A weak pull to the middle. Without it the parts of the graph that share no
  // links drift apart forever, and a feed covering two unrelated subjects ends
  // up as two dots at opposite corners of an empty screen.
  for (const node of nodes) {
    if (node.pinned) { node.vx = 0; node.vy = 0; continue; }
    node.vx -= node.x * gravity * alpha;
    node.vy -= node.y * gravity * alpha;
    node.vx *= damping;
    node.vy *= damping;
    node.x += node.vx;
    node.y += node.vy;
  }

  return alpha * 0.985;
}

// ---------- view state ----------

const graphState = {
  feed: null,
  nodes: [],
  edges: [],
  byHash: new Map(),
  // every stored link, and the subset actually drawn once "links each" has
  // thinned them. The card lists what the graph really holds; the picture
  // shows what was asked for.
  allEdges: [],
  adjacency: new Map(),
  // who is joined to whom by a *drawn* edge, for the hover highlight
  linked: new Map(),
  // the source whose legend row is under the cursor
  highlightSource: null,
  alpha: 0,
  frame: null,
  // world -> screen: multiply by k, then add tx/ty
  view: { k: 1, tx: 0, ty: 0 },
  selected: null,
  hovered: null,
  dragging: null,
  panning: null,
  pointers: new Map(),
  pinchDistance: 0,
  bound: false,
  total: 0,
};

const GRAPH_MIN_RADIUS = 3;
const GRAPH_RADIUS_RANGE = 13;

// Rank, not raw value.
//
// A model's predictions cluster: a whole feed can land between -0.1 and +0.25,
// and mapping that onto the [-1, 1] the score *could* take spends a twentieth
// of the range, so every dot comes out the same size. Ranking each value
// against the others in the window instead guarantees the picture uses the
// whole scale, and what you read off it — "this one is among the best here" —
// is what you actually wanted to know.
//
// The cost is that the sizes are relative to what is on screen, which the
// legend says out loud rather than leaving you to infer.
function rankScale(values) {
  const sorted = [...values].sort((a, b) => a - b);
  if (sorted.length < 2 || sorted[0] === sorted[sorted.length - 1]) {
    return () => 0.5;
  }
  return (value) => {
    // how many values this one is at least as big as
    let low = 0;
    let high = sorted.length;
    while (low < high) {
      const mid = (low + high) >> 1;
      if (sorted[mid] < value) low = mid + 1; else high = mid;
    }
    return low / (sorted.length - 1);
  };
}

// Size is the predicted score, so the articles the model likes are the ones
// that catch your eye. An article it has not scored yet draws at its smallest
// rather than at the middle: "no opinion" should not look like "mediocre".
function graphRadius(node) {
  return GRAPH_MIN_RADIUS + GRAPH_RADIUS_RANGE * (node.sizeRank ?? 0);
}

async function showFeedGraph(feedHash) {
  setView('graph');
  currentList = null;

  // Reuse the feed the list view already fetched when it is the same one, so
  // stepping between the list and the graph costs nothing.
  if (!currentFeed || currentFeed.feed_name_hash !== feedHash) {
    try {
      currentFeed = await sdk.feedGet({ feed_name_hash: feedHash });
    } catch (err) {
      toast(err.message, 'alert-error');
      router.go('');
      return;
    }
  }

  render($('graphBreadcrumb'),
    h('a', { href: `#/feed/${feedHash}` }, currentFeed.feed_name));

  if (!graphState.bound) bindGraphControls();
  // The same panel the article list uses, moved here: one set of controls over
  // one piece of state, so the picture and the list never disagree about what
  // is being hidden.
  adoptFilterPanel('graphFilterHost');
  syncFilterControls();
  graphState.feed = feedHash;
  await loadFeedGraph();
}

function bindGraphControls() {
  graphState.bound = true;
  const canvas = $('graphCanvas');

  $('graphRefreshBtn').onclick = () => loadFeedGraph();
  $('graphLimit').onchange = () => loadFeedGraph();
  $('graphFilterBtn').onclick = toggleFilterPanel;
  // Thinning the drawn links needs no new data, only a different subset of
  // what is already here -- so it re-layouts rather than re-fetching.
  $('graphLinks').onchange = () => {
    applyLinkDensity();
    renderGraphFooter();
    startGraphLayout();
  };
  $('graphZoomIn').onclick = () => zoomGraphBy(1.3);
  $('graphZoomOut').onclick = () => zoomGraphBy(1 / 1.3);
  $('graphReset').onclick = () => { fitGraph(); drawGraph(); };

  canvas.style.cursor = 'grab';
  canvas.addEventListener('pointerdown', onGraphPointerDown);
  canvas.addEventListener('pointermove', onGraphPointerMove);
  canvas.addEventListener('pointerup', onGraphPointerUp);
  canvas.addEventListener('pointercancel', onGraphPointerUp);
  canvas.addEventListener('pointerleave', () => {
    if (graphState.hovered) { graphState.hovered = null; drawGraph(); }
  });
  canvas.addEventListener('wheel', onGraphWheel, { passive: false });

  // The canvas is sized in CSS and drawn in device pixels, so it has to be
  // re-measured whenever the box changes — a window resize, or the sidebar
  // opening on a tablet.
  new ResizeObserver(() => {
    if ($('viewGraph').classList.contains('hidden')) return;
    sizeGraphCanvas();
    drawGraph();
  }).observe($('graphStage'));
}

async function loadFeedGraph() {
  stopGraphLayout();
  graphState.selected = null;
  graphState.hovered = null;
  $('graphDetail').classList.add('hidden');
  render($('graphOverlay'), spinner());
  render($('graphLegend'));
  $('graphFooter').textContent = '';

  try {
    const chosen = $('graphLimit').value;
    const data = await sdk.feedGraph({
      feed_name_hash: graphState.feed,
      // "All" sends no limit at all, which the endpoint reads as the whole
      // filtered feed
      limit: chosen === 'all' ? null : Number(chosen),
      sort: feedFilters.sort,
      include_read: feedFilters.includeRead,
      sources: feedFilters.sources === null ? null : feedFilters.sources.join(','),
      post_types: feedFilters.postTypes === null ? null : feedFilters.postTypes.join(','),
      max_age: feedFilters.maxAge,
      only_duplicates: feedFilters.onlyDuplicates,
    });
    buildGraphModel(data);
  } catch (err) {
    render($('graphOverlay'),
      h('p', { class: 'text-sm text-error px-4 text-center' }, err.message));
    return;
  }

  sizeGraphCanvas();
  if (!graphState.nodes.length) {
    render($('graphOverlay'),
      h('p', { class: 'text-sm text-base-content/60 px-6 text-center' },
        'No articles in this feed yet. Once its sources have been read, they '
        + 'will show up here.'));
    drawGraph();
    return;
  }

  render($('graphOverlay'));
  renderGraphLegend();
  renderGraphFooter();
  fitGraph();
  startGraphLayout();
}

// Where an article starts, before the forces move it.
//
// Derived from its own hash rather than from its position in the response, so
// that the sort decides *which* articles are drawn and nothing else. A force
// layout is path-dependent: seeded in the order the rows arrived, the same
// thousand articles would settle into a different picture under "newest" than
// under "best predicted", and the arrangement would look like it meant
// something about the sort. It does not. Position comes from the links.
function graphSeedAngle(hash) {
  let value = 0;
  for (const ch of String(hash)) value = (value * 31 + ch.codePointAt(0)) >>> 0;
  return (value % 100000) / 100000;
}

function buildGraphModel(data) {
  // A ring to start from rather than pure noise: the simulation untangles a
  // ring far faster than it untangles a random cloud, because no two nodes
  // begin on top of each other.
  const count = data.nodes.length;
  const radius = Math.max(60, count * 3.2);
  graphState.nodes = data.nodes.map((item) => {
    const angle = graphSeedAngle(item.item_hash) * Math.PI * 2;
    return {
      item,
      x: Math.cos(angle) * radius,
      y: Math.sin(angle) * radius,
      vx: 0,
      vy: 0,
      pinned: false,
      sizeRank: 0,
      color: sourceColor(item.item_source_name, item.item_source_color),
    };
  });

  // Rank the predictions against each other, so the sizes use the whole scale
  // whatever narrow band this feed's model happens to output. Unscored
  // articles are left out of the ranking and stay at the minimum.
  const scored = graphState.nodes.filter((n) => n.item.item_predicted_score != null);
  const sizeOf = rankScale(scored.map((n) => n.item.item_predicted_score));
  for (const node of scored) {
    node.sizeRank = sizeOf(node.item.item_predicted_score);
  }

  graphState.byHash = new Map(
    graphState.nodes.map((node) => [node.item.item_hash, node]));
  graphState.adjacency = new Map();

  // The same ranking problem again, on the links. Cosine similarities between
  // articles from one feed sit in a narrow band near the top of the range, so
  // the raw number spreads almost nothing — ranked against each other, the
  // strong links in *this* feed pull tight and the weak ones let go.
  const pairs = data.edges
    .map((edge) => ({
      a: graphState.byHash.get(edge.source),
      b: graphState.byHash.get(edge.target),
      similarity: edge.similarity,
    }))
    .filter((edge) => edge.a && edge.b && edge.a !== edge.b);
  const closeness = rankScale(pairs.map((edge) => edge.similarity));

  graphState.allEdges = pairs.map((edge) => {
    const rank = closeness(edge.similarity);
    return {
      ...edge,
      rank,
      // near means alike: the closest links hold their pair tightest and
      // shortest, the loosest barely hold them at all
      length: GRAPH_LINK_MIN + GRAPH_LINK_SPREAD * (1 - rank),
      strength: 0.2 + 0.8 * rank,
    };
  });

  for (const edge of graphState.allEdges) {
    for (const [from, to] of [[edge.a, edge.b], [edge.b, edge.a]]) {
      if (!graphState.adjacency.has(from)) graphState.adjacency.set(from, []);
      graphState.adjacency.get(from).push({ node: to, similarity: edge.similarity });
    }
  }
  for (const list of graphState.adjacency.values()) {
    list.sort((x, y) => y.similarity - x.similarity);
  }

  graphState.total = data.total_items;
  applyLinkDensity();
}

// Thin the drawn links to each article's strongest few.
//
// Every article keeps NEIGHBOR_LINKS of them, which is what makes the walk
// work, but drawing all of them draws a feed as a ball: with five links out of
// each node and their mirrors coming back, the average article is joined to
// about ten others and there is no structure left to see. Keeping an edge when
// it is among *either* end's strongest few is the usual way out — it thins the
// picture without cutting the graph into pieces, because every article keeps at
// least its own best link.
function strongestLinks(edges, perNode) {
  const best = new Map();
  for (const edge of edges) {
    for (const node of [edge.a, edge.b]) {
      if (!best.has(node)) best.set(node, []);
      best.get(node).push(edge);
    }
  }
  const keep = new Set();
  for (const [, list] of best) {
    list.sort((x, y) => y.similarity - x.similarity);
    for (const edge of list.slice(0, perNode)) keep.add(edge);
  }
  return keep;
}

function applyLinkDensity() {
  const keep = strongestLinks(graphState.allEdges, Number($('graphLinks').value));

  graphState.edges = graphState.allEdges.filter((edge) => keep.has(edge));
  graphState.linked = new Map();
  for (const edge of graphState.edges) {
    for (const [from, to] of [[edge.a, edge.b], [edge.b, edge.a]]) {
      if (!graphState.linked.has(from)) graphState.linked.set(from, new Set());
      graphState.linked.get(from).add(to);
    }
  }
}

// Expose the pure pieces for the node-based unit test; harmless in a browser,
// which has no `module`.
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    graphBuildTree, graphSummarize, graphTick, graphCell, rankScale, strongestLinks,
    graphSeedAngle,
  };
}

// ---------- layout loop ----------

function startGraphLayout(alpha = 1) {
  // never two loops at once: a second would step the simulation twice per
  // frame and outlive whichever of them is cancelled
  stopGraphLayout();
  graphState.alpha = alpha;
  const step = () => {
    graphState.frame = null;
    // leaving the view mid-layout should not keep a simulation running
    if ($('viewGraph').classList.contains('hidden')) return;
    for (let i = 0; i < 2; i += 1) {
      graphState.alpha = graphTick(
        graphState.nodes, graphState.edges, graphState.alpha);
    }
    drawGraph();
    if (graphState.alpha > 0.02) graphState.frame = requestAnimationFrame(step);
  };
  graphState.frame = requestAnimationFrame(step);
}

function stopGraphLayout() {
  if (graphState.frame) cancelAnimationFrame(graphState.frame);
  graphState.frame = null;
  graphState.alpha = 0;
}

// Nudge the simulation back to life after a drag, so the neighbours of the
// article you moved follow it rather than staying where they were.
function reheatGraph() {
  // Enough to let the neighbours follow, nowhere near enough to throw the
  // whole layout back in the air -- a drag is a nudge, not a re-run.
  if (graphState.frame) { graphState.alpha = Math.max(graphState.alpha, 0.35); return; }
  startGraphLayout(0.35);
}

// ---------- drawing ----------

function sizeGraphCanvas() {
  const canvas = $('graphCanvas');
  const ratio = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(rect.width * ratio));
  canvas.height = Math.max(1, Math.round(rect.height * ratio));
}

function graphSize() {
  const canvas = $('graphCanvas');
  const ratio = window.devicePixelRatio || 1;
  return { w: canvas.width / ratio, h: canvas.height / ratio, ratio };
}

function fitGraph() {
  const { w, h: height } = graphSize();
  if (!graphState.nodes.length) return;
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const node of graphState.nodes) {
    x0 = Math.min(x0, node.x);
    y0 = Math.min(y0, node.y);
    x1 = Math.max(x1, node.x);
    y1 = Math.max(y1, node.y);
  }
  const pad = 40;
  const k = Math.min(
    (w - pad * 2) / Math.max(1, x1 - x0),
    (height - pad * 2) / Math.max(1, y1 - y0));
  graphState.view.k = Math.max(0.05, Math.min(4, k));
  graphState.view.tx = w / 2 - ((x0 + x1) / 2) * graphState.view.k;
  graphState.view.ty = height / 2 - ((y0 + y1) / 2) * graphState.view.k;
}

function zoomGraphBy(factor) {
  const { w, h } = graphSize();
  zoomGraphAt(w / 2, h / 2, factor);
  drawGraph();
}

function zoomGraphAt(sx, sy, factor) {
  const view = graphState.view;
  const k = Math.max(0.05, Math.min(6, view.k * factor));
  // keep the point under the cursor where it is
  view.tx = sx - ((sx - view.tx) / view.k) * k;
  view.ty = sy - ((sy - view.ty) / view.k) * k;
  view.k = k;
}

// Theme colours live in CSS variables on <html>, and the canvas cannot read a
// daisyUI class. Sampled from a probe element so the drawing follows the theme
// rather than hard-coding two palettes.
function graphThemeColors() {
  const probe = getComputedStyle($('graphStage'));
  const text = getComputedStyle(document.body).color;
  return { surface: probe.backgroundColor, ink: text };
}

function drawGraph() {
  const canvas = $('graphCanvas');
  const ctx = canvas.getContext('2d');
  const { w, h, ratio } = graphSize();
  const view = graphState.view;
  const theme = graphThemeColors();

  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const focus = graphState.selected || graphState.hovered;
  // What stays bright. Following the *drawn* links rather than every stored
  // one keeps the highlight honest: it lights up what you can actually see a
  // line to.
  let near = null;
  // Only a focused *article* narrows the lines too -- following one article's
  // neighbourhood is a question about its links. Picking out a source is a
  // question about where its articles sit, and blanking the graph around them
  // takes away the very thing you are trying to see them in.
  let edgeFocus = false;
  if (focus) {
    near = new Set(graphState.linked.get(focus) || []);
    near.add(focus);
    edgeFocus = true;
  } else if (graphState.highlightSource) {
    near = new Set(graphState.nodes.filter(
      (node) => (node.item.item_source_name || 'Unknown source')
        === graphState.highlightSource));
  }

  // Edges first, in three bands by similarity: a near-identical pair should
  // read as a heavier line than a loose association, and stroking each one
  // individually to get a per-edge alpha is what makes a big graph crawl.
  const bands = [
    { min: 0.0, alpha: 0.10, width: 0.6 },
    { min: 0.8, alpha: 0.18, width: 0.9 },
    { min: 0.93, alpha: 0.32, width: 1.4 },
  ];
  ctx.lineCap = 'round';
  for (let band = 0; band < bands.length; band += 1) {
    const next = bands[band + 1];
    ctx.beginPath();
    let drew = false;
    for (const edge of graphState.edges) {
      if (edge.similarity < bands[band].min) continue;
      if (next && edge.similarity >= next.min) continue;
      if (edgeFocus && !(near.has(edge.a) && near.has(edge.b))) continue;
      ctx.moveTo(edge.a.x * view.k + view.tx, edge.a.y * view.k + view.ty);
      ctx.lineTo(edge.b.x * view.k + view.tx, edge.b.y * view.k + view.ty);
      drew = true;
    }
    if (!drew) continue;
    ctx.globalAlpha = edgeFocus
      ? Math.min(1, bands[band].alpha * 2.6)
      : bands[band].alpha;
    ctx.lineWidth = bands[band].width;
    ctx.strokeStyle = theme.ink;
    ctx.stroke();
  }

  // Nodes, grouped by colour so the fill style is set once per source rather
  // than once per article.
  const bySource = new Map();
  for (const node of graphState.nodes) {
    if (!bySource.has(node.color)) bySource.set(node.color, []);
    bySource.get(node.color).push(node);
  }
  for (const [color, group] of bySource) {
    for (const dimmed of [true, false]) {
      ctx.beginPath();
      let drew = false;
      for (const node of group) {
        const isDim = near ? !near.has(node) : false;
        if (isDim !== dimmed) continue;
        const r = graphRadius(node) * Math.max(0.55, Math.min(1.6, view.k));
        ctx.moveTo(node.x * view.k + view.tx + r, node.y * view.k + view.ty);
        ctx.arc(node.x * view.k + view.tx, node.y * view.k + view.ty, r, 0, Math.PI * 2);
        drew = true;
      }
      if (!drew) continue;
      // Read articles are drawn faint: what is left bright is what is left to
      // look at, which is the same thing the feed list means by unread.
      ctx.globalAlpha = dimmed ? 0.12 : 0.85;
      ctx.fillStyle = color;
      ctx.fill();
    }
  }

  // Read state and votes ride on top as outlines, so they never fight the
  // source colour underneath for the same pixels.
  ctx.globalAlpha = 1;
  for (const node of graphState.nodes) {
    if (near && !near.has(node)) continue;
    const voted = node.item.item_user_score;
    const r = graphRadius(node) * Math.max(0.55, Math.min(1.6, view.k));
    const cx = node.x * view.k + view.tx;
    const cy = node.y * view.k + view.ty;
    if (voted != null) {
      ctx.beginPath();
      ctx.arc(cx, cy, r + 2.2, 0, Math.PI * 2);
      ctx.lineWidth = 1.6;
      ctx.strokeStyle = voted > 0 ? '#22c55e' : voted < 0 ? '#ef4444' : '#eab308';
      ctx.stroke();
    }
    if (node === graphState.selected || node === graphState.hovered) {
      ctx.beginPath();
      ctx.arc(cx, cy, r + 5, 0, Math.PI * 2);
      ctx.lineWidth = 1.8;
      ctx.strokeStyle = theme.ink;
      ctx.globalAlpha = 0.7;
      ctx.stroke();
      ctx.globalAlpha = 1;
    }
  }

  // A label for whatever is under the cursor. Only one, and only on hover:
  // three hundred titles at once is not a picture of anything.
  const labelled = graphState.hovered || graphState.selected;
  if (labelled) {
    const text = labelled.item.item_title || labelled.item.item_url;
    const cx = labelled.x * view.k + view.tx;
    const cy = labelled.y * view.k + view.ty;
    ctx.font = '12px ui-sans-serif, system-ui, sans-serif';
    const clipped = text.length > 64 ? `${text.slice(0, 63)}…` : text;
    const width = ctx.measureText(clipped).width;
    const bx = Math.min(Math.max(4, cx - width / 2 - 6), w - width - 16);
    const by = cy - graphRadius(labelled) - 24;
    ctx.globalAlpha = 0.92;
    ctx.fillStyle = theme.surface;
    ctx.fillRect(bx, by, width + 12, 20);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = theme.ink;
    ctx.globalAlpha = 0.2;
    ctx.strokeRect(bx, by, width + 12, 20);
    ctx.globalAlpha = 1;
    ctx.fillStyle = theme.ink;
    ctx.fillText(clipped, bx + 6, by + 14);
  }
}

// ---------- interaction ----------

function graphPointerPosition(event) {
  const rect = $('graphCanvas').getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}

// The article under a screen point, or null. Nearest wins, so overlapping
// duplicates pick the one you actually aimed at rather than the last drawn.
function nodeAt(sx, sy) {
  const view = graphState.view;
  let best = null;
  let bestDistance = Infinity;
  for (const node of graphState.nodes) {
    const dx = sx - (node.x * view.k + view.tx);
    const dy = sy - (node.y * view.k + view.ty);
    const distance = Math.hypot(dx, dy);
    const reach = graphRadius(node) * Math.max(0.55, Math.min(1.6, view.k)) + 4;
    if (distance <= reach && distance < bestDistance) {
      best = node;
      bestDistance = distance;
    }
  }
  return best;
}

function onGraphPointerDown(event) {
  const canvas = $('graphCanvas');
  canvas.setPointerCapture(event.pointerId);
  const point = graphPointerPosition(event);
  graphState.pointers.set(event.pointerId, point);

  if (graphState.pointers.size === 2) {
    // a second finger turns the gesture into a pinch; drop any drag or pan
    const [a, b] = [...graphState.pointers.values()];
    graphState.pinchDistance = Math.hypot(a.x - b.x, a.y - b.y);
    graphState.dragging = null;
    graphState.panning = null;
    return;
  }

  const node = nodeAt(point.x, point.y);
  if (node) {
    graphState.dragging = { node, moved: false, wasPinned: node.pinned };
    node.pinned = true;
  } else {
    graphState.panning = { x: point.x, y: point.y, moved: false };
  }
}

function onGraphPointerMove(event) {
  const point = graphPointerPosition(event);
  if (graphState.pointers.has(event.pointerId)) {
    graphState.pointers.set(event.pointerId, point);
  }

  if (graphState.pointers.size === 2) {
    const [a, b] = [...graphState.pointers.values()];
    const distance = Math.hypot(a.x - b.x, a.y - b.y);
    if (graphState.pinchDistance > 0) {
      zoomGraphAt((a.x + b.x) / 2, (a.y + b.y) / 2, distance / graphState.pinchDistance);
      drawGraph();
    }
    graphState.pinchDistance = distance;
    return;
  }

  if (graphState.dragging) {
    const view = graphState.view;
    const node = graphState.dragging.node;
    node.x = (point.x - view.tx) / view.k;
    node.y = (point.y - view.ty) / view.k;
    node.vx = 0;
    node.vy = 0;
    graphState.dragging.moved = true;
    reheatGraph();
    drawGraph();
    return;
  }

  if (graphState.panning) {
    const view = graphState.view;
    view.tx += point.x - graphState.panning.x;
    view.ty += point.y - graphState.panning.y;
    if (Math.hypot(point.x - graphState.panning.x, point.y - graphState.panning.y) > 3) {
      graphState.panning.moved = true;
    }
    graphState.panning.x = point.x;
    graphState.panning.y = point.y;
    drawGraph();
    return;
  }

  const hovered = nodeAt(point.x, point.y);
  if (hovered !== graphState.hovered) {
    graphState.hovered = hovered;
    $('graphCanvas').style.cursor = hovered ? 'pointer' : 'grab';
    drawGraph();
  }
}

function onGraphPointerUp(event) {
  graphState.pointers.delete(event.pointerId);
  if (graphState.pointers.size < 2) graphState.pinchDistance = 0;

  if (graphState.dragging) {
    const { node, moved, wasPinned } = graphState.dragging;
    graphState.dragging = null;
    // A drag leaves the article where you put it; a tap does not pin it.
    if (!moved) {
      node.pinned = wasPinned;
      selectGraphNode(node);
    }
    drawGraph();
    return;
  }

  if (graphState.panning) {
    const { moved } = graphState.panning;
    graphState.panning = null;
    // a click on empty space clears the selection
    if (!moved) selectGraphNode(null);
  }
}

function onGraphWheel(event) {
  event.preventDefault();
  const point = graphPointerPosition(event);
  zoomGraphAt(point.x, point.y, event.deltaY < 0 ? 1.12 : 1 / 1.12);
  drawGraph();
}

// ---------- the detail card and legend ----------

// The picture a node's article carries, if it has one.
//
// A still with a play badge rather than a working player: a video in a 288px
// card beside the graph is not where anyone wants to watch one, and the badge
// says plainly that opening it will give you something that plays. Opening is
// what `openGraphItem` does, and the reader it hands off to does pictures,
// galleries and players properly already.
function graphPreview(node) {
  const item = node.item;
  const media = item.item_media || [];
  // the same set db/feed.py calls a video post
  const playable = youtubeId(item.item_url)
    || media.some((entry) => ['video', 'gif', 'stream', 'embed'].includes(entry.type));
  // Stills to try, best first, in the same order the reader's own player uses
  // (see streamPlayer): the article's picture, then a media entry's poster,
  // then an entry that *is* a picture. A YouTube link carries none of those
  // and has a thumbnail at a known address, which is where the reader gets
  // its own from too.
  const ytId = youtubeId(item.item_url);
  const still = item.item_image_url
    || media.map((entry) => entry.poster).find(Boolean)
    || media.filter((entry) => ['image', 'gif'].includes(entry.type))
      .map((entry) => entry.url).find(Boolean)
    || (ytId ? `https://i.ytimg.com/vi/${ytId}/hqdefault.jpg` : null);

  if (!still && !playable) return null;

  const frame = h('div', {
    class: 'relative rounded overflow-hidden bg-base-300 cursor-pointer',
    title: 'Open this article',
    onclick: () => openGraphItem(node),
  });
  if (still) {
    frame.append(h('img', {
      src: still,
      alt: '',
      loading: 'lazy',
      class: 'w-full h-28 object-cover',
      // a picture whose host has since dropped it should leave the card tidy
      onerror: (e) => e.target.replaceWith(
        h('div', { class: 'w-full h-28 bg-base-300' })),
    }));
  } else {
    frame.append(h('div', { class: 'w-full h-28 bg-base-300' }));
  }
  if (playable) {
    frame.append(h('div', {
      class: 'absolute inset-0 flex items-center justify-center pointer-events-none',
    },
      h('span', {
        class: 'w-9 h-9 rounded-full bg-base-100/85 flex items-center justify-center '
          + 'text-base-content text-sm leading-none pl-0.5',
      }, '\u25B6')));
  }
  return frame;
}

// Open the article properly. The node payload has no body -- the graph draws
// dots and does not ship a thousand articles' text to do it -- so the reader
// is given the real article, fetched for this one.
async function openGraphItem(node) {
  try {
    const full = await sdk.feedItem({
      feed_name_hash: graphState.feed,
      item_url_hash: node.item.item_hash,
    });
    openReader(full);
  } catch (err) {
    toast(err.message, 'alert-error');
  }
}

function selectGraphNode(node) {
  graphState.selected = node;
  const host = $('graphDetail');
  if (!node) {
    host.classList.add('hidden');
    render(host);
    drawGraph();
    return;
  }

  const item = node.item;
  const neighbours = (graphState.adjacency.get(node) || []).slice(0, 5);
  const predicted = item.item_predicted_score;

  host.classList.remove('hidden');
  render(host,
    h('div', { class: 'card bg-base-100 shadow-lg border border-base-300' },
      h('div', { class: 'card-body p-3 gap-2' },
        h('div', { class: 'flex items-start gap-2' },
          h('button', {
            type: 'button',
            class: 'text-sm font-semibold leading-snug line-clamp-3 flex-1 text-left '
              + 'link link-hover',
            title: 'Open this article',
            onclick: () => openGraphItem(node),
          }, item.item_title || item.item_url),
          h('button', {
            type: 'button',
            class: 'btn btn-ghost btn-xs btn-circle',
            title: 'Close',
            onclick: () => selectGraphNode(null),
          }, '✕')),
        graphPreview(node),
        h('div', { class: 'flex flex-wrap items-center gap-2 text-[11px] text-base-content/60' },
          sourceBadge(item.item_source_name, item.item_source_color),
          item.item_date_published ? h('span', {}, timeAgo(item.item_date_published)) : null,
          predicted != null
            ? h('span', {}, `${predicted > 0 ? '+' : ''}${Math.round(predicted * 100)}% predicted`)
            : h('span', { class: 'text-base-content/40' }, 'not scored yet')),
        item.item_duplicate_group
          ? h('p', { class: 'text-[11px] text-base-content/50' },
              'Also reached this feed from another source')
          : null,
        neighbours.length
          ? h('div', {},
              h('p', { class: 'text-[11px] font-semibold text-base-content/50 mb-1' },
                'Most similar'),
              h('ul', { class: 'space-y-0.5' },
                neighbours.map(({ node: other, similarity }) =>
                  h('li', {},
                    h('button', {
                      type: 'button',
                      class: 'text-left text-[11px] link link-hover line-clamp-1 w-full',
                      title: other.item.item_title || other.item.item_url,
                      onclick: () => { centreGraphOn(other); selectGraphNode(other); },
                    }, `${Math.round(similarity * 100)}% · ${other.item.item_title || other.item.item_url}`)))))
          : h('p', { class: 'text-[11px] text-base-content/50' },
              'No links yet — Aggy has not placed this one in the graph.'),
        h('div', { class: 'flex items-center justify-between gap-2 pt-1' },
          // Built here rather than with voteRow() so the vote lands on the
          // node the canvas is drawing: the ring around a voted article has to
          // appear the moment you press the button, and repainting the card is
          // what redraws it.
          h('div', { class: 'flex items-center gap-1' },
            VOTE_OPTIONS.map((option) =>
              h('button', {
                type: 'button',
                class: `btn btn-ghost btn-xs px-2 ${
                  item.item_user_score === option.score ? option.cls : ''}`,
                title: option.title,
                onclick: async () => {
                  await voteItem(item, option.score);
                  selectGraphNode(node);
                },
              }, option.label))),
          h('div', { class: 'flex items-center gap-1' },
            h('button', {
              type: 'button',
              class: 'btn btn-ghost btn-xs',
              onclick: () => openGraphItem(node),
            }, 'Read'),
            h('a', {
              href: item.item_url,
              target: '_blank',
              rel: 'noopener noreferrer',
              class: 'btn btn-ghost btn-xs',
              title: 'Open the original on its own site',
            }, '\u2197'))))));
  drawGraph();
}

function centreGraphOn(node) {
  const { w, h: height } = graphSize();
  graphState.view.tx = w / 2 - node.x * graphState.view.k;
  graphState.view.ty = height / 2 - node.y * graphState.view.k;
}

function renderGraphLegend() {
  const counts = new Map();
  for (const node of graphState.nodes) {
    const name = node.item.item_source_name || 'Unknown source';
    if (!counts.has(name)) counts.set(name, { count: 0, color: node.color });
    counts.get(name).count += 1;
  }
  const top = [...counts.entries()].sort((a, b) => b[1].count - a[1].count).slice(0, 8);
  const hidden = counts.size - top.length;

  // A row you can point at. Hovering a source lights up its articles and dims
  // the rest, which is the only practical way to pick one source out of a
  // dozen colours that necessarily look alike at this size.
  const sourceRow = ([name, { count, color }]) =>
    h('button', {
      type: 'button',
      class: 'flex items-center gap-1.5 min-w-0 w-full text-left rounded px-1 '
        + '-mx-1 hover:bg-base-200',
      onmouseenter: () => { graphState.highlightSource = name; drawGraph(); },
      onmouseleave: () => { graphState.highlightSource = null; drawGraph(); },
      onfocus: () => { graphState.highlightSource = name; drawGraph(); },
      onblur: () => { graphState.highlightSource = null; drawGraph(); },
    },
      h('span', {
        class: 'inline-block w-2 h-2 rounded-full shrink-0',
        style: `background:${color}`,
      }),
      h('span', { class: 'text-[11px] truncate' }, name),
      h('span', { class: 'text-[10px] text-base-content/40 ml-auto shrink-0' },
        String(count)));

  // A swatch showing what a ring means, drawn the same way the canvas draws it.
  const ring = (color, label) =>
    h('div', { class: 'flex items-center gap-1.5' },
      h('span', {
        class: 'inline-block w-2.5 h-2.5 rounded-full shrink-0 bg-base-content/30',
        style: `box-shadow: 0 0 0 1.5px ${color}`,
      }),
      h('span', { class: 'text-[10px] text-base-content/60' }, label));

  // ...and three dots at the sizes the canvas actually uses, so "bigger is
  // better predicted" is something you can check rather than take on trust.
  const sizeSwatch = (fraction) =>
    h('span', {
      class: 'inline-block rounded-full bg-base-content/40 shrink-0',
      style: `width:${(GRAPH_MIN_RADIUS + GRAPH_RADIUS_RANGE * fraction) * 1.1}px;`
        + `height:${(GRAPH_MIN_RADIUS + GRAPH_RADIUS_RANGE * fraction) * 1.1}px`,
    });

  render($('graphLegend'),
    h('div', {
      class: 'rounded-box bg-base-100/90 border border-base-300 px-2.5 py-2 '
        + 'pointer-events-auto max-h-[70%] overflow-y-auto',
    },
      h('p', { class: 'text-[10px] font-semibold uppercase tracking-wide text-base-content/50 mb-1' },
        'Sources'),
      h('div', { class: 'flex flex-col gap-0.5' },
        top.map(sourceRow),
        hidden > 0
          ? h('p', { class: 'text-[10px] text-base-content/40 mt-0.5 px-1' },
              `+${hidden} more`)
          : null),

      h('div', { class: 'border-t border-base-300 mt-2 pt-1.5 flex flex-col gap-1' },
        h('p', { class: 'text-[10px] font-semibold uppercase tracking-wide text-base-content/50' },
          'Size'),
        h('div', { class: 'flex items-end gap-1.5' },
          h('div', { class: 'flex items-end gap-1' },
            sizeSwatch(0), sizeSwatch(0.5), sizeSwatch(1)),
          h('span', { class: 'text-[10px] text-base-content/60 leading-tight' },
            'worst → best predicted')),
        // Said plainly, because it is the one thing about this scale that
        // could mislead: the sizes are ranks within what is on screen, not
        // absolute scores.
        h('p', { class: 'text-[10px] text-base-content/40 leading-tight' },
          'ranked against the articles shown'),

        h('p', { class: 'text-[10px] font-semibold uppercase tracking-wide text-base-content/50 mt-1' },
          'Ring'),
        ring('#22c55e', 'you upvoted'),
        ring('#eab308', 'you marked neutral'),
        ring('#ef4444', 'you downvoted'),
        h('p', { class: 'text-[10px] text-base-content/40 leading-tight' },
          'no ring: you have not voted'))));
}

function renderGraphFooter() {
  const shown = graphState.nodes.length;
  const drawn = graphState.edges.length;
  const stored = graphState.allEdges.length;
  const unplaced = graphState.nodes.filter((n) => !graphState.adjacency.has(n)).length;

  const parts = [
    `${shown} article${shown === 1 ? '' : 's'}`,
    // Both numbers, when they differ: a thinned picture should never look like
    // a feed with fewer links than it has.
    drawn === stored
      ? `${drawn} link${drawn === 1 ? '' : 's'}`
      : `${drawn} of ${stored} links drawn`,
  ];
  if (graphState.total > shown) parts.push(`of ${graphState.total} in this feed`);
  // Said plainly rather than left looking like missing data: a feed still
  // being linked has articles with no edges yet, and that is a queue working
  // rather than a graph with holes in it.
  if (unplaced) parts.push(`${unplaced} not linked yet`);

  $('graphFooter').textContent = `${parts.join(' · ')}. Drag to pin an article, scroll to zoom.`;
}
