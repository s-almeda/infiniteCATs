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
const renderMode = ref('Combination Nodes');
const currentLabelHighlight = ref(null);
let expandedNodes = [];
let expandedLinks = [];
let originalLinks = []; // Raw chronological links from API
let allNodes = []; // All nodes from API
let recipePathEdges = new Set();
let recipeToComboNodeId = {};  // Map from "comp1_comp2_result" to combNode id
let currentRecipeMap = {};  // Active timeline's recipe map: result -> [comp1, comp2]
let lastActiveCount = 0; // Track last active count to compute diff
let isPanning = false;
let panStartX = 0;
let panStartY = 0;

function getEmojiFor(id) {
  if (!allNodes) return "";
  const n = allNodes.find(node => node.id === id);
  return n?.emoji || "";
}

function draw(nodes, links) {
  ctx.clearRect(0, 0, width.value, height.value);
  
  // Apply zoom and pan translation
  ctx.save();
  ctx.translate(panX.value, panY.value);
  ctx.translate(width.value / 2, height.value / 2);
  ctx.scale(zoomLevel.value, zoomLevel.value);
  ctx.translate(-width.value / 2, -height.value / 2);

  // Draw links individually for dynamic styling
  links.forEach(l => {
    const isRecipe = l.isRecipe;
    const isLabelHi = renderMode.value === 'Labeled Arrows' && l.isLabelHighlight;
    ctx.strokeStyle = isRecipe ? "#ff0000" : (isLabelHi ? "#1e90ff" : "#888");
    ctx.lineWidth = (isRecipe || isLabelHi) ? 2 : 1;
    ctx.beginPath();
    ctx.moveTo(l.source.x, l.source.y);
    ctx.lineTo(l.target.x, l.target.y);
    ctx.stroke();
    ctx.lineWidth = 1;

    // Arrowhead per link
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
    const pullBack = 30;

    const baseX = toX - ux * pullBack;
    const baseY = toY - uy * pullBack;

    const leftX = baseX - uy * arrowWidth + ux * arrowLen;
    const leftY = baseY + ux * arrowWidth + uy * arrowLen;
    const rightX = baseX + uy * arrowWidth + ux * arrowLen;
    const rightY = baseY - ux * arrowWidth + uy * arrowLen;

    ctx.fillStyle = isRecipe ? "#ff0000" : (isLabelHi ? "#0a4fa3" : "#444");
    ctx.beginPath();
    ctx.moveTo(toX, toY);
    ctx.lineTo(leftX, leftY);
    ctx.lineTo(rightX, rightY);
    ctx.closePath();
    ctx.fill();

    // Edge label for 'Labeled Arrows' render mode
    if (renderMode.value === 'Labeled Arrows' && l.label) {
      const midX = (fromX + toX) / 2;
      const midY = (fromY + toY) / 2;
      // Offset label slightly perpendicular to the edge
      const offset = 12;
      const labelX = midX - uy * offset;
      const labelY = midY + ux * offset;
      ctx.fillStyle = isRecipe ? '#b00000' : (isLabelHi ? '#003366' : '#222');
      ctx.font = '12px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      const emoji = getEmojiFor(l.label);
      const labelText = emoji ? `${l.label} ${emoji}` : l.label;
      ctx.fillText(labelText, labelX, labelY);
    }
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
  // Use cached membership flag for performance
  return !!link.isRecipe;
}

function markRecipePathLinks() {
  // Reset all links
  expandedLinks.forEach(l => { l.isRecipe = false; });

  // Mark links that belong to the current recipe path using recipeKey
  expandedLinks.forEach(l => {
    if (l.recipeKey && recipePathEdges.has(l.recipeKey)) {
      l.isRecipe = true;
    }
  });
}

function markLabelHighlightedEdges() {
  // Only applies in Labeled Arrows mode
  const active = renderMode.value === 'Labeled Arrows' ? currentLabelHighlight.value : null;
  expandedLinks.forEach(l => {
    l.isLabelHighlight = !!(active && l.label === active);
  });
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
  // Trace back the recipe path to the target material using current recipe map
  const path = new Set();
  
  function trace(material) {
    if (currentRecipeMap[material]) {
      const [comp1, comp2] = currentRecipeMap[material];
      path.add(`${comp1}_${comp2}_${material}`);
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
  markRecipePathLinks();
  
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

  // Right-click behavior: highlight edges by label in Labeled Arrows mode
  if (event.button === 2) {
    if (renderMode.value === 'Labeled Arrows') {
      if (hit) {
        currentLabelHighlight.value = hit.id || hit.label || hit.name;
      } else {
        currentLabelHighlight.value = null;
      }
      markLabelHighlightedEdges();
      // Update link force to strengthen highlighted edges
      if (simulation) {
        simulation.force("link",
          forceLink(expandedLinks)
            .distance(l => {
              if (l.distance !== undefined && l.distance !== null && !isNaN(l.distance)) {
                const maxDistance = 300;
                const minDistance = 10;
                return minDistance + l.distance * (maxDistance - minDistance);
              }
              return 80;
            })
            .strength(l => (l.isRecipe || (renderMode.value === 'Labeled Arrows' && l.isLabelHighlight)) ? 1.5 : 0.8)
        );
        simulation.alpha(0.25).restart();
      }
      // Redraw immediately for visual feedback
      if (expandedNodes.length) draw(expandedNodes, expandedLinks);
    }
    return; // prevent panning/dragging on right-click
  }

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

function rebuildGraphForTimeline(fullReset = false) {
  if (!originalLinks || originalLinks.length === 0 || !allNodes) return;
  
  const total = originalLinks.length;
  const activeCount = Math.max(1, Math.floor((timePercentage.value / 100) * total));
  const activeLinks = originalLinks.slice(0, activeCount);
  
  console.log(`Updating graph to ${activeCount}/${total} links (${timePercentage.value}%)`);

  // When switching render modes, fully reset state to avoid leftover mutated objects
  if (fullReset) {
    recipeToComboNodeId = {};
    expandedNodes = [];
    expandedLinks = [];
    storedNodes.value = [];
    if (simulation) {
      simulation.stop();
      simulation = null;
    }
  }
  
  // Step 1: Build what SHOULD exist depending on render mode
  const shouldExistMaterials = new Set(['Fire', 'Water', 'Earth', 'Air']);
  const shouldExistCombos = new Set(); // recipe keys (used as edge identity)
  
  activeLinks.forEach(l => {
    const recipeKey = `${l.from1}_${l.from2}_${l.to}`;
    shouldExistCombos.add(recipeKey);
    if (renderMode.value === 'Combination Nodes') {
      shouldExistMaterials.add(l.from1);
      shouldExistMaterials.add(l.from2);
      shouldExistMaterials.add(l.to);
    } else {
      // Labeled Arrows (reversed): connect from1 -> to and label with from2
      shouldExistMaterials.add(l.from1);
      shouldExistMaterials.add(l.to);
    }
  });
  
  // Step 2: Determine what to add and what to remove
  const currentMaterialIds = new Set(expandedNodes.filter(n => n.type !== "combination").map(n => n.id));
  const currentComboKeys = new Set(Object.keys(recipeToComboNodeId));
  
  const materialsToAdd = [...shouldExistMaterials].filter(id => !currentMaterialIds.has(id));
  const materialsToRemove = [...currentMaterialIds].filter(id => !shouldExistMaterials.has(id));
  const combosToAdd = [...shouldExistCombos].filter(key => !currentComboKeys.has(key));
  const combosToRemove = [...currentComboKeys].filter(key => !shouldExistCombos.has(key));
  
  console.log(`Add: ${materialsToAdd.length} materials, ${combosToAdd.length} combos | Remove: ${materialsToRemove.length} materials, ${combosToRemove.length} combos`);
  
  // Step 3: Remove nodes and links
  if (combosToRemove.length > 0 || materialsToRemove.length > 0) {
    const materialIdsToRemove = new Set(materialsToRemove);
    if (renderMode.value === 'Combination Nodes') {
      const comboIdsToRemove = new Set(combosToRemove.map(key => recipeToComboNodeId[key]));
      // Remove combo mappings
      combosToRemove.forEach(key => delete recipeToComboNodeId[key]);
      // Filter out removed nodes
      expandedNodes = expandedNodes.filter(n => {
        return !comboIdsToRemove.has(n.id) && !materialIdsToRemove.has(n.id);
      });
      // Filter out links connected to removed nodes
      expandedLinks = expandedLinks.filter(link => {
        const sourceId = link.source.id || link.source;
        const targetId = link.target.id || link.target;
        return !comboIdsToRemove.has(sourceId) && !comboIdsToRemove.has(targetId) &&
               !materialIdsToRemove.has(sourceId) && !materialIdsToRemove.has(targetId);
      });
    } else {
      // Labeled Arrows: remove edges by recipeKey
      const combosToRemoveSet = new Set(combosToRemove);
      expandedLinks = expandedLinks.filter(link => !combosToRemoveSet.has(link.recipeKey));
      // Remove materials not in shouldExist
      expandedNodes = expandedNodes.filter(n => !materialIdsToRemove.has(n.id));
      // Also filter any links connected to removed materials
      const removedMaterials = materialIdsToRemove;
      expandedLinks = expandedLinks.filter(link => {
        const sourceId = link.source.id || link.source;
        const targetId = link.target.id || link.target;
        return !removedMaterials.has(sourceId) && !removedMaterials.has(targetId);
      });
    }
  }
  
  // Step 4: Add new materials
  if (materialsToAdd.length > 0) {
    materialsToAdd.forEach(matId => {
      const nodeData = allNodes.find(n => n.id === matId);
      if (nodeData) {
        expandedNodes.push({
          id: nodeData.id,
          label: nodeData.label,
          emoji: nodeData.emoji,
          type: nodeData.type
        });
      }
    });
  }
  
  // Step 5: Add new combos/edges
  if (combosToAdd.length > 0) {
    if (renderMode.value === 'Combination Nodes') {
      let combinationNodeId = Object.keys(recipeToComboNodeId).length;
      combosToAdd.forEach(recipeKey => {
        const [from1, from2, to] = recipeKey.split('_');
        const linkData = activeLinks.find(l => l.from1 === from1 && l.from2 === from2 && l.to === to);
        if (!linkData) {
          console.warn("Could not find link data for recipe:", recipeKey);
          return;
        }
        const sourceNode1 = expandedNodes.find(n => n.id === from1);
        const sourceNode2 = expandedNodes.find(n => n.id === from2);
        const targetNode = expandedNodes.find(n => n.id === to);
        if (!sourceNode1 || !sourceNode2 || !targetNode) {
          console.warn("Could not resolve nodes for recipe:", recipeKey);
          return;
        }
        // Create combo node
        const combId = `_comb_${combinationNodeId++}`;
        const combNode = { id: combId, label: `${sourceNode1.label} + ${sourceNode2.label}`, emoji: "", type: "combination" };
        expandedNodes.push(combNode);
        recipeToComboNodeId[recipeKey] = combId;
        // Add links with recipeKey
        expandedLinks.push({ source: sourceNode1, target: combNode, distance: linkData.distanceFrom1, isRecipe: false, isLabelHighlight: false, recipeKey });
        expandedLinks.push({ source: sourceNode2, target: combNode, distance: linkData.distanceFrom2, isRecipe: false, isLabelHighlight: false, recipeKey });
        expandedLinks.push({ source: combNode, target: targetNode, distance: linkData.distanceTo, isRecipe: false, isLabelHighlight: false, recipeKey });
      });
    } else {
      // Labeled Arrows (reversed): create single edge from from1 -> to labeled with from2
      combosToAdd.forEach(recipeKey => {
        const [from1, from2, to] = recipeKey.split('_');
        const linkData = activeLinks.find(l => l.from1 === from1 && l.from2 === from2 && l.to === to);
        if (!linkData) {
          console.warn("Could not find link data for recipe:", recipeKey);
          return;
        }
        const sourceNode1 = expandedNodes.find(n => n.id === from1);
        const targetNode = expandedNodes.find(n => n.id === to);
        if (!sourceNode1 || !targetNode) {
          console.warn("Could not resolve nodes for labeled arrow:", recipeKey);
          return;
        }
        expandedLinks.push({ source: sourceNode1, target: targetNode, distance: linkData.distanceTo, isRecipe: false, isLabelHighlight: false, recipeKey, label: from2 });
      });
    }
  }
  
  // Step 6: Update recipe map and path
  currentRecipeMap = {};
  activeLinks.forEach(l => {
    if (!currentRecipeMap[l.to]) {
      currentRecipeMap[l.to] = [l.from1, l.from2];
    }
  });
  
  const goalMaterial = activeLinks[activeCount - 1]?.to;
  recipePathEdges = goalMaterial ? findPathToNode(goalMaterial) : new Set();
  markRecipePathLinks();
  
  // Step 7: Update simulation
  storedNodes.value = expandedNodes;
  
  const isInitialBuild = !simulation;
  if (isInitialBuild) {
    simulation = forceSimulation(expandedNodes)
      .force("link",
        forceLink(expandedLinks)
          .distance(l => {
            if (l.distance !== undefined && l.distance !== null && !isNaN(l.distance)) {
              const maxDistance = 300;
              const minDistance = 10;
              return minDistance + l.distance * (maxDistance - minDistance);
            }
            return 80;
          })
          .strength(l => (l.isRecipe || (renderMode.value === 'Labeled Arrows' && l.isLabelHighlight)) ? 1.5 : 0.8)
      )
      .force("charge", forceManyBody().strength(-200))
      .force("center", forceCenter(width.value / 2, height.value / 2));
    
    simulation.on("tick", () => {
      draw(expandedNodes, expandedLinks);
    });
  } else {
    simulation.nodes(expandedNodes);
    simulation.force("link",
      forceLink(expandedLinks)
        .distance(l => {
          if (l.distance !== undefined && l.distance !== null && !isNaN(l.distance)) {
            const maxDistance = 300;
            const minDistance = 10;
            return minDistance + l.distance * (maxDistance - minDistance);
          }
          return 80;
        })
        .strength(l => (l.isRecipe || (renderMode.value === 'Labeled Arrows' && l.isLabelHighlight)) ? 1.5 : 0.8)
    );
    simulation.alpha(0.3).restart();
  }
}

async function loadGraphData() {
  console.log("Loading graph data...");
  try {
    const apiUrl = import.meta.env.VITE_FLASK_API_URL || 'http://localhost:3000'
    let query = isLoggedIn.value && username.value
      ? `?username=${encodeURIComponent(username.value)}`
      : '';
    
    // Always fetch full graph - no percentage parameter
    const res = await fetch(`${apiUrl}/api/graph${query}`);
    if (!res.ok) {
      console.error("Failed to fetch graph data:", res.status);
      return;
    }
    const { nodes, links, recipePath } = await res.json();
    console.log("Loaded full graph data:", { nodes: nodes.length, links: links.length });

    // Store full data for timeline filtering
    originalLinks = links;
    allNodes = nodes;
    
    // Store initial recipe path (for full history) as string keys
    recipePathEdges = new Set(recipePath.map(p => `${p[0]}_${p[1]}_${p[2]}`));
    
    ctx = canvas.value.getContext("2d");
    
    // Build graph based on current timeline percentage
    rebuildGraphForTimeline();
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

// Watch time percentage slider and rebuild graph
watch(timePercentage, () => {
  console.log(`Time slider changed to ${timePercentage.value}%`);
  rebuildGraphForTimeline();
});

// Rebuild when render mode changes
watch(renderMode, () => {
  console.log(`Render mode changed to ${renderMode.value}`);
  rebuildGraphForTimeline(true);
  // clear any label highlight when switching modes
  currentLabelHighlight.value = null;
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
      <div class="flex items-center gap-3 mb-3">
        <label class="text-sm font-medium whitespace-nowrap">Render Mode:</label>
        <select v-model="renderMode" class="text-sm border border-gray-300 rounded px-2 py-1">
          <option value="Combination Nodes">Combination Nodes</option>
          <option value="Labeled Arrows">Labeled Arrows</option>
        </select>
      </div>
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
