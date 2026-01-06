<script setup>
import { onMounted, onBeforeUnmount, ref, watch } from "vue";
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter
} from "d3-force";
import { useBoxesStore } from "@/stores/useBoxesStore";
import { useResourcesStore } from "@/stores/useResourcesStore";
import { useUserStore } from "@/stores/useUserStore";
import { storeToRefs } from "pinia";

const boxStore = useBoxesStore();
const resourceStore = useResourcesStore();
const userStore = useUserStore();
const { combinationCount } = storeToRefs(resourceStore);
const { username, isLoggedIn } = storeToRefs(userStore);
const canvas = ref(null);
let simulation;
let ctx;
let animationFrame;

const width = ref(window.innerWidth - 40);
const height = ref(600);
const storedNodes = ref([]);
const hoverNode = ref(null);
const hoverPos = ref({ x: 0, y: 0 });
const draggingNode = ref(null);
const dragStartPos = ref({ x: 0, y: 0 });
const zoomLevel = ref(1);
const panX = ref(0);
const panY = ref(0);
const timePercentage = ref(100);
let expandedNodes = [];
let expandedLinks = [];
let recipePathEdges = new Set();
let recipeToComboNodeId = {};  // Map from "comp1_comp2_result" to combNode id
let recipeMap = {};  // Map from result material to [comp1, comp2, rank]
let isPanning = false;
let panStartX = 0;
let panStartY = 0;

function draw(nodes, links) {
  ctx.clearRect(0, 0, width.value, height.value);
  
  // Apply zoom and pan translation
  ctx.save();
  ctx.translate(panX.value, panY.value);
  ctx.translate(width.value / 2, height.value / 2);
  ctx.scale(zoomLevel.value, zoomLevel.value);
  ctx.translate(-width.value / 2, -height.value / 2);

  // links - draw normal links in gray
  ctx.strokeStyle = "#888";
  ctx.beginPath();
  links.forEach(l => {
    if (!isRecipePathLink(l)) {
      ctx.moveTo(l.source.x, l.source.y);
      ctx.lineTo(l.target.x, l.target.y);
    }
  });
  ctx.stroke();

  // recipe path links in red
  ctx.strokeStyle = "#ff0000";
  ctx.lineWidth = 2;
  ctx.beginPath();
  links.forEach(l => {
    if (isRecipePathLink(l)) {
      ctx.moveTo(l.source.x, l.source.y);
      ctx.lineTo(l.target.x, l.target.y);
    }
  });
  ctx.stroke();
  ctx.lineWidth = 1;

  // arrowheads for direction
  links.forEach(l => {
    const fromX = l.source.x;
    const fromY = l.source.y;
    const toX = l.target.x;
    const toY = l.target.y;

    const dx = toX - fromX;
    const dy = toY - fromY;
    const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len;
    const uy = dy / len;

    const arrowLen = 14;
    const arrowWidth = 8;
    const pullBack = 30; // pull back more so arrowhead stays off the node

    const baseX = toX - ux * pullBack;
    const baseY = toY - uy * pullBack;

    const leftX = baseX - uy * arrowWidth + ux * arrowLen;
    const leftY = baseY + ux * arrowWidth + uy * arrowLen;
    const rightX = baseX + uy * arrowWidth + ux * arrowLen;
    const rightY = baseY - ux * arrowWidth + uy * arrowLen;

    ctx.fillStyle = "#444";
    ctx.beginPath();
    ctx.moveTo(toX, toY);
    ctx.lineTo(leftX, leftY);
    ctx.lineTo(rightX, rightY);
    ctx.closePath();
    ctx.fill();
  });

  // nodes
  nodes.forEach(n => {
    ctx.beginPath();
    ctx.fillStyle =
      n.type === "combination" ? "#ffb703" : "#219ebc";
    ctx.arc(n.x, n.y, 6, 0, Math.PI * 2);
    ctx.fill();

    // Draw emoji label (skip for combination nodes)
    if (n.type !== "combination") {
      ctx.font = "16px sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      const emoji = n.emoji || "❓";
      ctx.fillText(emoji, n.x, n.y - 14);
    }
  });
  
  ctx.restore();
}

function isRecipePathLink(link) {
  // Check if this link is part of the recipe path
  // We need to check if the link is one of the three edges in a recipe path triple
  for (const [comp1, comp2, result] of recipePathEdges) {
    const recipeKey = `${comp1}_${comp2}_${result}`;
    const combNodeId = recipeToComboNodeId[recipeKey];
    
    if (combNodeId) {
      // Check if link is one of: comp1->combNode, comp2->combNode, combNode->result
      if ((link.source.id === comp1 && link.target.id === combNodeId) ||
          (link.source.id === comp2 && link.target.id === combNodeId) ||
          (link.source.id === combNodeId && link.target.id === result)) {
        return true;
      }
    }
  }
  return false;
}

function screenToCanvasCoords(screenX, screenY) {
  // Convert screen coordinates to canvas coordinates accounting for zoom and pan
  // Reverse the transformations applied in draw()
  const centerX = width.value / 2;
  const centerY = height.value / 2;
  
  // Remove pan translation
  let x = screenX - panX.value;
  let y = screenY - panY.value;
  
  // Translate back from center
  x -= centerX;
  y -= centerY;
  
  // Unscale by zoom
  x /= zoomLevel.value;
  y /= zoomLevel.value;
  
  // Translate back
  x += centerX;
  y += centerY;
  
  return { x, y };
}

function onMouseMove(event) {
  if (!storedNodes.value.length) return;
  const rect = canvas.value.getBoundingClientRect();
  const screenX = event.clientX - rect.left;
  const screenY = event.clientY - rect.top;
  
  hoverPos.value = { x: screenX, y: screenY };
  
  // Handle panning
  if (isPanning) {
    const deltaX = screenX - panStartX;
    const deltaY = screenY - panStartY;
    panX.value += deltaX;
    panY.value += deltaY;
    panStartX = screenX;
    panStartY = screenY;
    return;
  }
  
  const { x, y } = screenToCanvasCoords(screenX, screenY);

  if (draggingNode.value) {
    draggingNode.value.fx = x;
    draggingNode.value.fy = y;
    simulation?.alpha(0.7).restart();
    return;
  }

  const hit = storedNodes.value.find(n => {
    const dx = n.x - x;
    const dy = n.y - y;
    return dx * dx + dy * dy <= 10 * 10; // radius 10px
  });

  hoverNode.value = hit ? hit.label || hit.id || hit.name : null;
}

function findPathToNode(targetMaterial) {
  // Trace back the recipe path to the target material
  const path = new Set();
  
  function trace(material) {
    if (recipeMap[material]) {
      const [comp1, comp2] = recipeMap[material];
      path.add([comp1, comp2, material]);
      trace(comp1);
      trace(comp2);
    }
  }
  
  trace(targetMaterial);
  return path;
}

function updateRecipePath(targetMaterial) {
  // Update the recipe path to highlight the path to the target material
  recipePathEdges = findPathToNode(targetMaterial);
  
  // Redraw the graph with the new recipe path
  if (expandedNodes.length > 0 && expandedLinks.length > 0) {
    draw(expandedNodes, expandedLinks);
  }
}

function handleNodeClick(node) {
  // Only handle non-combination nodes
  if (node.type === "combination") return;

  // Update the recipe path to this node
  updateRecipePath(node.id);

  // Get container dimensions for centering
  const containerWidth = window.innerWidth * 0.75;
  const containerHeight = window.innerHeight * 0.9;

  // Calculate center position
  const centerX = containerWidth / 2 - 40;
  const centerY = containerHeight / 2 - 15;

  // Add random offset (±100px)
  const randomOffsetX = (Math.random() - 0.5) * 200;
  const randomOffsetY = (Math.random() - 0.5) * 200;

  const finalX = Math.round(centerX + randomOffsetX);
  const finalY = Math.round(centerY + randomOffsetY);

  // Add to canvas
  const key = Math.random().toString(36).substring(7);
  boxStore.boxes[key] = { top: finalY, left: finalX, title: node.label || node.id, emoji: node.emoji };
}

function onMouseDown(event) {
  if (!storedNodes.value.length) return;
  const rect = canvas.value.getBoundingClientRect();
  const screenX = event.clientX - rect.left;
  const screenY = event.clientY - rect.top;

  const { x, y } = screenToCanvasCoords(screenX, screenY);
  dragStartPos.value = { x: screenX, y: screenY };

  const hit = storedNodes.value.find(n => {
    const dx = n.x - x;
    const dy = n.y - y;
    return dx * dx + dy * dy <= 10 * 10;
  });

  // Left-click on empty space pans; left-click on node drags/clicks node.
  if (!hit && event.button === 0) {
    isPanning = true;
    panStartX = screenX;
    panStartY = screenY;
    return;
  }

  if (hit && event.button === 0) {
    draggingNode.value = hit;
    hit.fx = x;
    hit.fy = y;
    simulation?.alpha(0.7).restart();
  }
}

function onMouseUp(event) {
  isPanning = false;
  
  if (draggingNode.value) {
    // Calculate distance moved (in screen coordinates)
    const rect = canvas.value.getBoundingClientRect();
    const screenX = event.clientX - rect.left;
    const screenY = event.clientY - rect.top;
    const dx = screenX - dragStartPos.value.x;
    const dy = screenY - dragStartPos.value.y;
    const distance = Math.hypot(dx, dy);

    // If movement is minimal, treat as click
    if (distance < 5) {
      handleNodeClick(draggingNode.value);
    }

    draggingNode.value.fx = null;
    draggingNode.value.fy = null;
    draggingNode.value = null;
    simulation?.alphaTarget(0);
  }
}

function onMouseLeave() {
  hoverNode.value = null;
}

function setZoomToViewCenter(newZoom) {
  const clampedZoom = Math.max(0.5, Math.min(3, newZoom));
  const oldZoom = zoomLevel.value || 1;
  if (clampedZoom === oldZoom) return;

  // Keep the *current view center* fixed by scaling pan with the zoom ratio.
  // With our transform order (pan -> center -> scale), maintaining the same
  // world point under screen-center requires: pan' = pan * (newZoom/oldZoom)
  const ratio = clampedZoom / oldZoom;
  panX.value *= ratio;
  panY.value *= ratio;
  zoomLevel.value = clampedZoom;
}

function onWheel(event) {
  event.preventDefault();
  const zoomSpeed = 0.1;
  const direction = event.deltaY > 0 ? -1 : 1;
  setZoomToViewCenter(zoomLevel.value + direction * zoomSpeed);
}

function zoomIn() {
  setZoomToViewCenter(zoomLevel.value + 0.2);
}

function zoomOut() {
  setZoomToViewCenter(zoomLevel.value - 0.2);
}

function resetZoom() {
  zoomLevel.value = 1;
  panX.value = 0;
  panY.value = 0;
}

async function loadGraphData() {
  console.log("Loading graph data...");
  try {
    const apiUrl = import.meta.env.VITE_FLASK_API_URL || 'http://localhost:3000'
    let query = isLoggedIn.value && username.value
      ? `?username=${encodeURIComponent(username.value)}`
      : '';
    
    // Add percentage parameter
    const percentageParam = `percentage=${timePercentage.value}`;
    query = query ? `${query}&${percentageParam}` : `?${percentageParam}`;
    
    const res = await fetch(`${apiUrl}/api/graph${query}`);
    if (!res.ok) {
      console.error("Failed to fetch graph data:", res.status);
      return;
    }
    const { nodes, links, recipePath } = await res.json();
    console.log("Loaded graph data:", { nodes, links, recipePath });

    // Build recipe map for finding paths to any node
    recipeMap = {};
    links.forEach(l => {
      if (!recipeMap[l.to]) {
        recipeMap[l.to] = [l.from1, l.from2];
      }
    });

    // Store recipe path for highlighting (initially the default path from API)
    recipePathEdges = new Set(recipePath.map(p => [p[0], p[1], p[2]]));
    recipeToComboNodeId = {};  // Reset the mapping

    // cache nodes for hover detection
    storedNodes.value = nodes;

    // Turn each combination link into linear links by adding a combination node
    expandedNodes = [...nodes];
    expandedLinks = [];
    let combinationNodeId = 0;

    links.forEach(l => {
      // Resolve source and target nodes
      const sourceNode1 = expandedNodes.find(n => n.id === l.from1);
      const sourceNode2 = expandedNodes.find(n => n.id === l.from2);
      const targetNode = expandedNodes.find(n => n.id === l.to);

      if (!sourceNode1 || !sourceNode2 || !targetNode) {
        console.warn("Could not resolve nodes for link:", l, { sourceNode1, sourceNode2, targetNode });
        console.warn("Available node IDs:", expandedNodes.map(n => n.id));
        // Skip this link instead of crashing
        return;
      }

      // Create intermediate combination node
      const combId = `_comb_${combinationNodeId++}`;
      const combNode = {
        id: combId,
        label: `${sourceNode1.label} + ${sourceNode2.label}`,
        emoji: "",
        type: "combination"
      };
      expandedNodes.push(combNode);
      
      // Store mapping for recipe path highlighting
      const recipeKey = `${l.from1}_${l.from2}_${l.to}`;
      recipeToComboNodeId[recipeKey] = combId;

      // Create links with distance data: source1 → combination, source2 → combination, combination → target
      console.log("Creating expanded links for combination:", l);
      expandedLinks.push({ source: sourceNode1, target: combNode, distance: l.distanceFrom1 });
      expandedLinks.push({ source: sourceNode2, target: combNode, distance: l.distanceFrom2 });
      expandedLinks.push({ source: combNode, target: targetNode, distance: l.distanceTo });
    });

    const normalizedLinks = expandedLinks;
    storedNodes.value = expandedNodes;

    // Stop existing simulation if it exists
    if (simulation) {
      simulation.stop();
    }

    ctx = canvas.value.getContext("2d");

    simulation = forceSimulation(expandedNodes)
      .force("link",
        forceLink(normalizedLinks)
          .distance(l => {
            // Use distance values from API if available, otherwise use defaults
            if (l.distance !== undefined && l.distance !== null && !isNaN(l.distance)) {
              const maxDistance = 300;
              const minDistance = 10;
              return minDistance + l.distance * (maxDistance - minDistance);
            }
            // Fallback to default distance if no valid distance data
            return 80;
          })
          .strength(0.8)
      )
      .force("charge", forceManyBody().strength(-200))
      .force("center", forceCenter(width.value / 2, height.value / 2));

    simulation.on("tick", () => {
      draw(expandedNodes, normalizedLinks);
    });
  } catch (error) {
    console.error("Error loading graph:", error);
  }
}

// Quick visibility to confirm the component is evaluated
console.log("Graph component module loaded");

onMounted(async () => {
  console.log("Mounting Graph component and loading data...");
  
  // Handle window resize
  const handleResize = () => {
    width.value = window.innerWidth - 40;
  };
  window.addEventListener('resize', handleResize);
  
  await loadGraphData();
  
  return () => {
    window.removeEventListener('resize', handleResize);
  };
});

// Watch for combination events and reload graph
watch(combinationCount, async () => {
  console.log("Combination detected, waiting for database to update...");
  // Wait 500ms for database to update
  await new Promise(resolve => setTimeout(resolve, 500));
  console.log("Reloading graph...");
  loadGraphData();
});

// Watch zoom level and redraw
watch(zoomLevel, () => {
  if (simulation && expandedNodes.length > 0) {
    draw(expandedNodes, expandedLinks);
  }
});

// Watch pan and redraw
watch([panX, panY], () => {
  if (simulation && expandedNodes.length > 0) {
    draw(expandedNodes, expandedLinks);
  }
});

// Watch time percentage slider and reload graph
watch(timePercentage, () => {
  console.log(`Time slider changed to ${timePercentage.value}%`);
  loadGraphData();
});

onBeforeUnmount(() => {
  simulation?.stop();
  cancelAnimationFrame(animationFrame);
});
</script>

<template>
  <div
    class="relative inline-block border border-gray-300 rounded-md shadow-sm"
    @mousemove="onMouseMove"
    @mouseleave="onMouseLeave"
    @mousedown="onMouseDown"
    @mouseup="onMouseUp"
    @wheel="onWheel"
    @contextmenu.prevent
  >
    <canvas
      ref="canvas"
      :width="width"
      :height="height"
    />
    <div
      v-if="hoverNode"
      class="absolute bg-white border border-gray-300 rounded px-2 py-1 text-sm shadow"
      :style="{ left: `${hoverPos.x + 10}px`, top: `${hoverPos.y + 10}px` }">
      {{ hoverNode }}
    </div>
    <div class="absolute top-2 right-2 flex gap-2">
      <button @click="zoomIn" class="bg-blue-500 text-white px-3 py-1 rounded text-sm hover:bg-blue-600">+</button>
      <button @click="resetZoom" class="bg-gray-500 text-white px-3 py-1 rounded text-sm hover:bg-gray-600">Reset</button>
      <button @click="zoomOut" class="bg-blue-500 text-white px-3 py-1 rounded text-sm hover:bg-blue-600">−</button>
    </div>
    <div class="absolute bottom-2 left-2 right-2 bg-white border border-gray-300 rounded px-4 py-3 shadow" @wheel.stop @mousedown.stop>
      <div class="flex items-center gap-3">
        <label class="text-sm font-medium whitespace-nowrap">Timeline: {{ timePercentage }}%</label>
        <input 
          type="range" 
          v-model="timePercentage" 
          min="1" 
          max="100" 
          step="1"
          class="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
        />
      </div>
    </div>
  </div>
</template>
