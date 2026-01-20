<script setup>
import { onMounted, onBeforeUnmount, ref, watch, nextTick } from "vue";
import { useUserStore } from "@/stores/useUserStore";
import { storeToRefs } from "pinia";
import {
  COMMUNITY_PARAMS,
  computeCommunities,
  assignCommunityColors,
  buildCommunitySummaries,
  fetchGraphData,
  addCraftTimesToNodes
} from "@/utils/communities";


const userStore = useUserStore();
const { username, isLoggedIn } = storeToRefs(userStore);

const canvas = ref(null);
let ctx;

const width = ref(1000);
const height = ref(1000);
const centerX = ref(500);
const centerY = ref(500);

const zoomLevel = ref(1);
const panX = ref(0);
const panY = ref(0);
let isPanning = false;
let panStartX = 0;
let panStartY = 0;

const hoverNode = ref(null);
const hoverPos = ref({ x: 0, y: 0 });

const loading = ref(true);
const error = ref(null);

let allNodes = [];
let allLinks = [];
let positionedNodes = [];
let communityAssignments = {};
let communityColors = {};
const communitySummaries = ref([]);

// Expand nodes so each user-discovery is a separate node
function expandNodesByUser(nodes) {
  const expanded = [];

  nodes.forEach(node => {
    if (node.isBaseMaterial || node.craftTimes === null) {
      // Base materials appear once at center
      expanded.push({
        ...node,
        craftTime: -1,
        discoveredBy: null
      });
    } else if (Object.keys(node.craftTimes).length === 0) {
      // Node exists but hasn't been discovered by anyone - skip it
      // (This shouldn't happen normally)
      console.warn(`Node ${node.id} has no craft times, skipping`);
    } else {
      // Create a node for each user who discovered this material
      Object.entries(node.craftTimes).forEach(([username, craftTime]) => {
        expanded.push({
          ...node,
          craftTime,
          discoveredBy: username
        });
      });
    }
  });

  console.log(`Expanded ${nodes.length} nodes to ${expanded.length} user-discovery nodes`);
  return expanded;
}

// Build a distance matrix from links
function buildDistanceMatrix(links) {
  const distances = new Map(); // "nodeA|nodeB" -> distance

  const setDistance = (a, b, dist) => {
    if (dist === null || dist === undefined || isNaN(dist)) return;
    const key1 = `${a}|${b}`;
    const key2 = `${b}|${a}`;
    // Keep the smallest distance if we see the same pair multiple times
    if (!distances.has(key1) || distances.get(key1) > dist) {
      distances.set(key1, dist);
      distances.set(key2, dist);
    }
  };

  links.forEach(link => {
    const { from1, from2, to, distanceFrom1, distanceFrom2, distanceTo } = link;
    // distanceFrom1 is distance from from1 to the combination midpoint
    // distanceFrom2 is distance from from2 to the combination midpoint
    // distanceTo is distance from the midpoint to the result
    // We can use these to approximate pairwise distances
    if (distanceFrom1 !== null && distanceFrom2 !== null) {
      // Approximate distance between from1 and from2
      setDistance(from1, from2, distanceFrom1 + distanceFrom2);
    }
    if (distanceFrom1 !== null && distanceTo !== null) {
      setDistance(from1, to, distanceFrom1 + distanceTo);
    }
    if (distanceFrom2 !== null && distanceTo !== null) {
      setDistance(from2, to, distanceFrom2 + distanceTo);
    }
  });

  return distances;
}

// Order nodes on a ring by similarity using nearest-neighbor greedy algorithm
function orderNodesBySimilarity(ringNodes, distanceMatrix) {
  if (ringNodes.length <= 2) return ringNodes;

  const getDistance = (a, b) => {
    const key = `${a.id}|${b.id}`;
    return distanceMatrix.get(key) ?? Infinity;
  };

  const ordered = [];
  const remaining = new Set(ringNodes);

  // Start with the first node
  let current = ringNodes[0];
  ordered.push(current);
  remaining.delete(current);

  // Greedily pick the nearest unvisited node
  while (remaining.size > 0) {
    let nearest = null;
    let nearestDist = Infinity;

    for (const node of remaining) {
      const dist = getDistance(current, node);
      if (dist < nearestDist) {
        nearestDist = dist;
        nearest = node;
      }
    }

    if (nearest) {
      ordered.push(nearest);
      remaining.delete(nearest);
      current = nearest;
    } else {
      // No connected node found, just add remaining nodes
      for (const node of remaining) {
        ordered.push(node);
      }
      break;
    }
  }

  return ordered;
}

function layoutRadialGraph(nodes) {
  // First expand nodes by user
  const expandedNodes = expandNodesByUser(nodes);

  // Build distance matrix from links
  const distanceMatrix = buildDistanceMatrix(allLinks);

  // Find max craft time (excluding base materials at -1)
  const craftTimes = expandedNodes.map(n => n.craftTime).filter(t => t >= 0);
  const maxCraftTime = Math.max(...craftTimes, 1);

  // Calculate max radius
  const maxRadius = Math.min(width.value, height.value) / 2 - 50;

  // Order ALL nodes by similarity as if on one ring
  const orderedNodes = orderNodesBySimilarity(expandedNodes, distanceMatrix);

  console.log(`RadialGraph: ${expandedNodes.length} nodes, maxCraftTime=${maxCraftTime}`);

  // Position nodes: angle from ordering, radius from craftTime
  const angleStep = (2 * Math.PI) / Math.max(orderedNodes.length, 1);

  orderedNodes.forEach((node, i) => {
    const angle = i * angleStep - Math.PI / 2; // Start from top
    const radius = node.craftTime === -1 ? 0 : (node.craftTime / maxCraftTime) * maxRadius;

    node.x = centerX.value + radius * Math.cos(angle);
    node.y = centerY.value + radius * Math.sin(angle);
    node.radius = radius;
    node.angle = angle;
  });

  return expandedNodes;
}

function draw() {
  if (!ctx || positionedNodes.length === 0) return;

  ctx.clearRect(0, 0, width.value, height.value);

  // Apply zoom and pan
  ctx.save();
  ctx.translate(panX.value, panY.value);
  ctx.translate(width.value / 2, height.value / 2);
  ctx.scale(zoomLevel.value, zoomLevel.value);
  ctx.translate(-width.value / 2, -height.value / 2);

  // Draw ring guides
  const maxRadius = Math.min(width.value, height.value) / 2 - 50;
  const rings = new Set(positionedNodes.map(n => n.radius).filter(r => r > 0));

  ctx.strokeStyle = '#eee';
  ctx.lineWidth = 1;
  rings.forEach(radius => {
    ctx.beginPath();
    ctx.arc(centerX.value, centerY.value, radius, 0, Math.PI * 2);
    ctx.stroke();
  });

  // Draw nodes - size scales with zoom
  const baseRadius = 1;
  const scaledRadius = baseRadius// * zoomLevel.value;

  positionedNodes.forEach(node => {
    const color = communityColors[node.id] || '#219ebc';
    const nodeRadius = node.isBaseMaterial ? scaledRadius * 2 : scaledRadius;

    ctx.beginPath();
    ctx.fillStyle = color;
    ctx.arc(node.x, node.y, nodeRadius, 0, Math.PI * 2);
    ctx.fill();
  });

  ctx.restore();
}

function screenToCanvasCoords(screenX, screenY) {
  const cX = width.value / 2;
  const cY = height.value / 2;

  let x = screenX - panX.value;
  let y = screenY - panY.value;

  x -= cX;
  y -= cY;

  x /= zoomLevel.value;
  y /= zoomLevel.value;

  x += cX;
  y += cY;

  return { x, y };
}

function onMouseMove(event) {
  if (!canvas.value) return;
  const rect = canvas.value.getBoundingClientRect();
  const screenX = event.clientX - rect.left;
  const screenY = event.clientY - rect.top;

  hoverPos.value = { x: screenX, y: screenY };

  if (isPanning) {
    const deltaX = screenX - panStartX;
    const deltaY = screenY - panStartY;
    panX.value += deltaX;
    panY.value += deltaY;
    panStartX = screenX;
    panStartY = screenY;
    draw();
    return;
  }

  const { x, y } = screenToCanvasCoords(screenX, screenY);

  const hit = positionedNodes.find(n => {
    const dx = n.x - x;
    const dy = n.y - y;
    return dx * dx + dy * dy <= 100;
  });

  if (hit) {
    const timeStr = hit.craftTime === -1 ? 'Base' : `#${hit.craftTime}`;
    const userStr = hit.discoveredBy ? ` by ${hit.discoveredBy}` : '';
    hoverNode.value = `${hit.emoji} ${hit.label} (${timeStr}${userStr})`;
  } else {
    hoverNode.value = null;
  }
}

function onMouseDown(event) {
  if (event.button === 0) {
    const rect = canvas.value.getBoundingClientRect();
    isPanning = true;
    panStartX = event.clientX - rect.left;
    panStartY = event.clientY - rect.top;
  }
}

function onMouseUp() {
  isPanning = false;
}

function onMouseLeave() {
  hoverNode.value = null;
  isPanning = false;
}

function onWheel(event) {
  event.preventDefault();
  const zoomSpeed = 0.05;
  const direction = event.deltaY > 0 ? -1 : 1;
  const newZoom = Math.max(0.1, Math.min(5, zoomLevel.value + direction * zoomSpeed));

  const ratio = newZoom / zoomLevel.value;
  panX.value *= ratio;
  panY.value *= ratio;
  zoomLevel.value = newZoom;

  draw();
}

async function loadData() {
  loading.value = true;
  error.value = null;

  try {
    // Fetch everyone's graph data
    const { nodes, links } = await fetchGraphData(null, false);
    console.log("RadialGraph: Fetched data", { nodes: nodes.length, links: links.length });

    allLinks = links;

    // Add craft times to nodes
    const nodesWithCraftTimes = addCraftTimesToNodes(nodes, links);
    console.log("RadialGraph: Nodes with craft times", nodesWithCraftTimes);

    // Compute communities
    communityAssignments = computeCommunities(nodesWithCraftTimes, links, COMMUNITY_PARAMS);
    communityColors = assignCommunityColors(communityAssignments);
    communitySummaries.value = buildCommunitySummaries(communityAssignments, communityColors, nodesWithCraftTimes);

    allNodes = nodesWithCraftTimes;

    // Layout nodes
    positionedNodes = layoutRadialGraph([...allNodes]);

    // Set loading false so canvas renders, then draw on next tick
    loading.value = false;
    await nextTick();

    ctx = canvas.value.getContext("2d");
    draw();

  } catch (err) {
    console.error("RadialGraph: Error loading data", err);
    error.value = err.message;
    loading.value = false;
  }
}

watch([zoomLevel, panX, panY], () => {
  draw();
});

onMounted(() => {
  loadData();
});
</script>

<template>
  <div class="radial-graph">
    <h2 class="text-lg font-semibold mb-2">Radial Discovery Graph</h2>

    <div v-if="loading" class="text-gray-500">Loading...</div>
    <div v-else-if="error" class="text-red-500">Error: {{ error }}</div>

    <div
      v-else
      class="relative inline-block border border-gray-300 rounded-md shadow-sm"
      @mousemove="onMouseMove"
      @mouseleave="onMouseLeave"
      @mousedown="onMouseDown"
      @mouseup="onMouseUp"
      @wheel="onWheel"
    >
      <canvas
        ref="canvas"
        :width="width"
        :height="height"
      />
      <div
        v-if="hoverNode"
        class="absolute bg-white border border-gray-300 rounded px-2 py-1 text-sm shadow pointer-events-none"
        :style="{ left: `${hoverPos.x + 10}px`, top: `${hoverPos.y + 10}px` }"
      >
        {{ hoverNode }}
      </div>
    </div>

    <div class="mt-4">
      <h3 class="text-sm font-semibold mb-2">Communities</h3>
      <div class="flex flex-wrap gap-2">
        <div
          v-for="comm in communitySummaries.slice(0, 10)"
          :key="comm.id"
          class="flex items-center gap-1 text-xs"
        >
          <span class="w-3 h-3 rounded-sm" :style="{ backgroundColor: comm.color }"></span>
          <span>{{ comm.labels[0] }} ({{ comm.count }})</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.radial-graph {
  padding: 1rem;
}
</style>
