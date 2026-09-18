// The graph view's force layout, out of the browser.
//
// `static/js/graph.js` is mostly canvas and pointer handling, which needs a
// browser to mean anything. The layout underneath it does not: the quadtree's
// bookkeeping, whether linked articles actually end up near each other, and
// what a tick costs at the largest window the view offers are all plain
// arithmetic, and all three are the kind of thing that breaks quietly.
//
// Run with: node src/api/tests/js/graph_layout_test.js

const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(
  path.join(__dirname, '..', '..', 'static', 'js', 'graph.js'), 'utf8');

// graph.js is a plain script rather than a module -- it is loaded with a
// <script> tag alongside the rest of the app. Evaluating it with a `module`
// in scope picks up the export block at the bottom of its layout section;
// nothing else in the file runs at load time.
const loaded = { exports: {} };
new Function('module', source)(loaded);
const {
  graphBuildTree, graphTick, rankScale, strongestLinks, graphSeedAngle,
} = loaded.exports;

let failures = 0;

function check(ok, what) {
  if (ok) {
    console.log(`ok   ${what}`);
  } else {
    failures += 1;
    console.error(`FAIL ${what}`);
  }
}

// ---------- the quadtree ----------

const scattered = [];
for (let i = 0; i < 500; i += 1) {
  scattered.push({ x: Math.random() * 1000 - 500, y: Math.random() * 1000 - 500, vx: 0, vy: 0 });
}
let tree = graphBuildTree(scattered);
check(tree.mass === 500, 'every article is counted exactly once');

const trueMeanX = scattered.reduce((sum, p) => sum + p.x, 0) / scattered.length;
const trueMeanY = scattered.reduce((sum, p) => sum + p.y, 0) / scattered.length;
check(
  Math.abs(tree.cx - trueMeanX) < 1e-6 && Math.abs(tree.cy - trueMeanY) < 1e-6,
  'the root centre of mass is the real mean, so distant crowds push correctly');

// Near-identical duplicates land on the same spot, which is exactly what makes
// a quadtree recurse forever if nothing stops it.
const piled = Array.from({ length: 40 }, () => ({ x: 7, y: 7, vx: 0, vy: 0 }));
tree = graphBuildTree(piled);
check(tree.mass === 40, 'a pile of articles on one point is held, not split forever');

// ---------- the layout ----------

function clustered(count, groups, seed = 1) {
  // a fixed-seed LCG, so a failure here is reproducible rather than a coin toss
  let state = seed;
  const random = () => {
    state = (state * 1664525 + 1013904223) % 4294967296;
    return state / 4294967296;
  };
  const nodes = [];
  for (let i = 0; i < count; i += 1) {
    const angle = (i / count) * Math.PI * 2;
    nodes.push({
      x: Math.cos(angle) * count * 3.2,
      y: Math.sin(angle) * count * 3.2,
      vx: 0,
      vy: 0,
      pinned: false,
      group: i % groups,
    });
  }
  const edges = [];
  for (let i = 0; i < count; i += 1) {
    for (let j = i + 1; j < count; j += 1) {
      if (nodes[i].group === nodes[j].group && random() < 0.25) {
        edges.push({ a: nodes[i], b: nodes[j], similarity: 0.95, length: 22 });
      }
    }
  }
  return { nodes, edges, random };
}

const { nodes, edges } = clustered(90, 3);
let alpha = 1;
while (alpha > 0.02) alpha = graphTick(nodes, edges, alpha);

const centres = [0, 1, 2].map((group) => {
  const members = nodes.filter((node) => node.group === group);
  return [
    members.reduce((sum, node) => sum + node.x, 0) / members.length,
    members.reduce((sum, node) => sum + node.y, 0) / members.length,
  ];
});
const radiusOf = (group) => {
  const members = nodes.filter((node) => node.group === group);
  return Math.max(...members.map(
    (node) => Math.hypot(node.x - centres[group][0], node.y - centres[group][1])));
};
const nearestPair = Math.min(
  Math.hypot(centres[0][0] - centres[1][0], centres[0][1] - centres[1][1]),
  Math.hypot(centres[1][0] - centres[2][0], centres[1][1] - centres[2][1]),
  Math.hypot(centres[0][0] - centres[2][0], centres[0][1] - centres[2][1]));
const widest = Math.max(radiusOf(0), radiusOf(1), radiusOf(2));

// The whole point of the picture: three groups of articles that link within
// themselves and not to each other have to come out as three groups.
check(
  nearestPair > widest,
  `linked clusters separate (${nearestPair.toFixed(0)} apart vs ${widest.toFixed(0)} wide)`);
check(
  nodes.every((node) => Number.isFinite(node.x) && Number.isFinite(node.y)),
  'no article escapes to NaN or Infinity');

// A pinned article is one the reader dragged somewhere on purpose. The
// simulation must leave it there.
const { nodes: pinnedNodes, edges: pinnedEdges } = clustered(40, 2, 9);
pinnedNodes[0].pinned = true;
pinnedNodes[0].x = 1234;
pinnedNodes[0].y = -567;
let pinnedAlpha = 1;
while (pinnedAlpha > 0.05) {
  pinnedAlpha = graphTick(pinnedNodes, pinnedEdges, pinnedAlpha);
}
check(
  pinnedNodes[0].x === 1234 && pinnedNodes[0].y === -567,
  'an article dragged into place stays where it was put');

// ---------- spreading a graph out ----------

// The complaint that produced this section: with every link pulling equally
// hard, a feed came out as one ball. Ranking the similarities against each
// other and scaling both the rest length and the stiffness by that rank is
// what separates a strong pair from a loose association.

function ranked(edges) {
  const scale = rankScale(edges.map((edge) => edge.similarity));
  for (const edge of edges) {
    const rank = scale(edge.similarity);
    edge.length = 26 + 220 * (1 - rank);
    edge.strength = 0.2 + 0.8 * rank;
  }
  return edges;
}

// The over-connected case: everything linked to everything, which is roughly
// what five links each plus their mirrors looks like in a small feed.
const dense = { nodes: [], edges: [] };
for (let i = 0; i < 24; i += 1) {
  const angle = (i / 24) * Math.PI * 2;
  dense.nodes.push({ x: Math.cos(angle) * 80, y: Math.sin(angle) * 80, vx: 0, vy: 0, pinned: false });
}
for (let i = 0; i < dense.nodes.length; i += 1) {
  for (let j = i + 1; j < dense.nodes.length; j += 1) {
    // two tight groups, everything else a loose association
    const together = (i < 12) === (j < 12);
    dense.edges.push({
      a: dense.nodes[i],
      b: dense.nodes[j],
      similarity: together ? 0.97 : 0.72,
    });
  }
}
ranked(dense.edges);

let denseAlpha = 1;
while (denseAlpha > 0.02) denseAlpha = graphTick(dense.nodes, dense.edges, denseAlpha);

const distanceOf = (edge) => Math.hypot(edge.a.x - edge.b.x, edge.a.y - edge.b.y);
const meanOf = (list) => list.reduce((sum, edge) => sum + distanceOf(edge), 0) / list.length;
const tight = meanOf(dense.edges.filter((edge) => edge.similarity > 0.9));
const loose = meanOf(dense.edges.filter((edge) => edge.similarity <= 0.9));
check(
  loose > tight * 1.5,
  `strong links end up much shorter than weak ones (${tight.toFixed(0)} vs ${loose.toFixed(0)})`);

// ---------- ranking a narrow band ----------

// A feed's predictions can all sit between -0.1 and +0.25, and its similarities
// between 0.80 and 0.95. Mapped onto the range the numbers *could* take, every
// dot is the same size and every link the same length -- which is what made
// the first version of this view unreadable.
const narrow = [0.80, 0.83, 0.86, 0.90, 0.95];
const scale = rankScale(narrow);
check(scale(0.80) === 0 && scale(0.95) === 1, 'a narrow band still uses the whole scale');
check(
  scale(0.86) > 0 && scale(0.86) < 1,
  'and the values in between land in between');

const flat = rankScale([0.5, 0.5, 0.5]);
check(flat(0.5) === 0.5, 'values that are all the same sit in the middle, not at an end');
check(rankScale([])(1) === 0.5, 'an empty window does not divide by zero');

// ---------- thinning the drawn links ----------

const nodeA = { id: 'a' };
const nodeB = { id: 'b' };
const nodeC = { id: 'c' };
const strong = { a: nodeA, b: nodeB, similarity: 0.99 };
const middling = { a: nodeB, b: nodeC, similarity: 0.85 };
const weak = { a: nodeA, b: nodeC, similarity: 0.40 };
const kept = strongestLinks([strong, middling, weak], 1);

// Each article keeps its own best link, so nothing is cut adrift -- b's best
// is the same edge as a's, and c's best is the middling one.
check(kept.has(strong), "each article's strongest link is always drawn");
check(kept.has(middling), 'an article whose best link is nobody else\'s best still keeps it');
check(!kept.has(weak), 'a link that is nobody\'s best is dropped');
check(
  strongestLinks([strong, middling, weak], 5).size === 3,
  'asking for every link draws every link');

// ---------- the sort chooses which, never where ----------

// The sort is a filter: it decides which articles are drawn, and nothing else.
// A force layout is path-dependent, so seeding from each row's position in the
// response would make the same thousand articles settle differently under
// "newest" than under "best predicted" -- an arrangement that looked like it
// meant something about the sort, when position only ever comes from the links.
const hashes = ['aaa', 'bbb', 'ccc', 'ddd', 'eee'];
const seeded = hashes.map(graphSeedAngle);
check(
  seeded.every((angle) => angle >= 0 && angle < 1),
  'a seed angle is a fraction of a turn');
check(
  hashes.map(graphSeedAngle).every((angle, i) => angle === seeded[i]),
  'the same article always starts in the same place');
check(
  new Set(seeded).size === hashes.length,
  'different articles start in different places');
check(
  JSON.stringify([...hashes].reverse().map(graphSeedAngle))
    === JSON.stringify([...seeded].reverse()),
  'and where one starts does not depend on the order the rows arrived in');

// ---------- what it costs ----------

const big = clustered(1000, 12, 3);
ranked(big.edges);
const started = Date.now();
let bigAlpha = 1;
let ticks = 0;
while (bigAlpha > 0.02) {
  bigAlpha = graphTick(big.nodes, big.edges, bigAlpha);
  ticks += 1;
}
const perTick = (Date.now() - started) / ticks;
// The view offers 1000 articles as its largest window. Without the Barnes-Hut
// approximation this is half a million pairs a tick and the layout visibly
// crawls, so the ceiling here is really a test that the approximation is on.
check(
  perTick < 60,
  `a tick at the largest window stays cheap (${perTick.toFixed(1)}ms for 1000 articles, `
  + `${big.edges.length} links)`);

if (failures) {
  console.error(`\n${failures} check(s) failed`);
  process.exit(1);
}
console.log('\nall checks passed');
