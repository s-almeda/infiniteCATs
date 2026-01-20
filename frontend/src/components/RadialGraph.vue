<script setup>
import { onMounted, onBeforeUnmount, ref, watch, nextTick } from "vue";
import { useUserStore } from "@/stores/useUserStore";
import { storeToRefs } from "pinia";
import {
  COMMUNITY_PARAMS,
  computeCommunities,
  assignCommunityColors,
  buildCommunitySummaries,
  fetchRadialLayout
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

// Track if we're in global mode
const isGlobalMode = ref(false);

let allNodes = [];
let allLinks = [];
let positionedNodes = [];
let communityAssignments = {};
let communityColors = {};
const communitySummaries = ref([]);
const userSummaries = ref([]); // For global mode: summaries by username

// Assign colors to nodes based on the username who first discovered them (for global mode)
function assignUserColors(nodes) {
  // Palette for users (distinct colors)
  const palette = [
    '#e63946', // red
    '#2a9d8f', // teal
    '#e9c46a', // gold
    '#264653', // dark blue
    '#f4a261', // orange
    '#8338ec', // purple
    '#06d6a0', // mint
    '#ef476f', // pink
    '#118ab2', // blue
    '#073b4c', // navy
    '#d62828', // crimson
    '#6dccb5', // seafoam
    '#a4c639', // lime
    '#b86ee0', // violet
    '#5ca9a5'  // teal-gray
  ];

  const baseMaterials = new Set(['Fire', 'Water', 'Earth', 'Air']);
  
  // Collect all unique usernames and assign colors
  const usernames = [...new Set(nodes.map(n => n.firstDiscoverer).filter(Boolean))];
  const userToColor = new Map();
  usernames.forEach((user, idx) => {
    userToColor.set(user, palette[idx % palette.length]);
  });
  
  // Build node colors
  const nodeColors = {};
  nodes.forEach(node => {
    if (baseMaterials.has(node.id)) {
      nodeColors[node.id] = '#999999';
    } else {
      const user = node.firstDiscoverer;
      nodeColors[node.id] = user ? userToColor.get(user) : '#cccccc';
    }
  });
  
  // Build user summaries for legend
  const userCounts = new Map();
  nodes.forEach(node => {
    if (!baseMaterials.has(node.id) && node.firstDiscoverer) {
      userCounts.set(node.firstDiscoverer, (userCounts.get(node.firstDiscoverer) || 0) + 1);
    }
  });
  
  const summaries = [...userCounts.entries()]
    .map(([user, count]) => ({
      id: user,
      color: userToColor.get(user),
      count,
      label: user
    }))
    .sort((a, b) => b.count - a.count);
  
  console.log(`[RadialGraph] Assigned colors for ${usernames.length} users`);
  
  return { nodeColors, summaries };
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
    hoverNode.value = `${hit.emoji} ${hit.label} (${timeStr})`;
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
    // Fetch radial layout with pre-computed positions from backend
    const layoutData = await fetchRadialLayout(
      username.value || null,
      width.value,
      height.value
    );
    
    const { nodes, links } = layoutData;
    isGlobalMode.value = !username.value;
    
    console.log(`[RadialGraph] Fetched layout: ${nodes.length} nodes, ${links.length} links (global=${isGlobalMode.value})`);

    allLinks = links;
    allNodes = nodes;
    
    // Nodes already have x, y positions from backend
    positionedNodes = nodes;

    // Assign colors based on mode
    if (isGlobalMode.value) {
      // Global mode: color by first discoverer (included in node data from backend)
      const userColors = assignUserColors(nodes);
      communityColors = userColors.nodeColors;
      userSummaries.value = userColors.summaries;
      communitySummaries.value = [];
    } else {
      // User mode: compute communities for coloring
      console.log("[RadialGraph] Computing communities...");
      communityAssignments = computeCommunities(nodes, links, COMMUNITY_PARAMS);
      communityColors = assignCommunityColors(communityAssignments);
      communitySummaries.value = buildCommunitySummaries(communityAssignments, communityColors, nodes);
      userSummaries.value = [];
    }

    // Set loading false so canvas renders, then draw on next tick
    loading.value = false;
    await nextTick();

    ctx = canvas.value.getContext("2d");
    draw();
    console.log("[RadialGraph] Render complete!");

  } catch (err) {
    console.error("RadialGraph: Error loading data", err);
    error.value = err.message;
    loading.value = false;
  }
}

watch([zoomLevel, panX, panY], () => {
  draw();
});

// Reload when username changes
watch(username, () => {
  loadData();
});

onMounted(() => {
  loadData();
});
</script>

<template>
  <div class="radial-graph">
    <h2 class="text-lg font-semibold mb-2">
      {{ isGlobalMode ? 'Global Radial Discovery Graph' : 'Radial Discovery Graph' }}
    </h2>
    <p v-if="isGlobalMode" class="text-xs text-gray-500 mb-2">
      Showing all discoveries, colored by first discoverer
    </p>

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

    <!-- User legend (global mode) -->
    <div v-if="isGlobalMode && userSummaries.length > 0" class="mt-4">
      <h3 class="text-sm font-semibold mb-2">First Discoverers</h3>
      <div class="flex flex-wrap gap-2">
        <div
          v-for="user in userSummaries.slice(0, 15)"
          :key="user.id"
          class="flex items-center gap-1 text-xs"
        >
          <span class="w-3 h-3 rounded-sm" :style="{ backgroundColor: user.color }"></span>
          <span>{{ user.label }} ({{ user.count }})</span>
        </div>
      </div>
    </div>

    <!-- Community legend (user mode) -->
    <div v-else-if="!isGlobalMode && communitySummaries.length > 0" class="mt-4">
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
