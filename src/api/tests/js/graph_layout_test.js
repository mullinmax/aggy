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
const { graphBuildTree, graphTick } = loaded.exports;

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

// ---------- what it costs ----------

const big = clustered(1000, 12, 3);
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
