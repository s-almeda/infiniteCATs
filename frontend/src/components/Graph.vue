<script setup>
import { onMounted, onBeforeUnmount, ref, watch, computed } from "vue";
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
const discoveryCanvas = ref(null);
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
const selectedCommunities = ref(new Set());
const colorMode = ref('communities'); // 'communities' or 'users'
const communityAlgorithm = ref('undirected'); // 'undirected' or 'directed'
const minCommunitySize = ref(1); // Minimum community size for Community Graph view
const selectedUsers = ref(new Set());
let userAssignments = {}; // nodeId -> username (first discoverer)
let userColors = {}; // nodeId -> color string
let edgeUserMap = {}; // recipeKey -> Set of usernames who traversed this edge
const userSummaries = ref([]);
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
let communityAssignments = {}; // nodeId -> communityId
let communityColors = {}; // nodeId -> color string
const communitySummaries = ref([]);
const globalCentralization = ref(0);
const globalInterCommunityDistance = ref(0);
const avgCommunitySpread = computed(() => {
  const spreads = communitySummaries.value
    .filter(c => c.count >= 2 && c.avgDistToCentroid !== undefined)
    .map(c => c.avgDistToCentroid);
  if (spreads.length === 0) return 0;
  return spreads.reduce((a, b) => a + b, 0) / spreads.length;
});
const COMMUNITY_PARAMS = {
  gamma: 0.5,      // < 1 => coarser communities; > 1 => finer communities
  maxPasses: 50,   // number of local-move sweeps
  minGain: -1e-6   // allow tiny negative to avoid getting stuck
};

function getEmojiFor(id) {
  if (!allNodes) return "";
  const n = allNodes.find(node => node.id === id);
  return n?.emoji || "";
}

function layoutLinkograph(nodes) {
  // Position nodes in a horizontal line based on chronological order
  const padding = 50;
  const nodeSpacing = 80;
  const baseY = height.value / 2;
  
  nodes.forEach((node) => {
    // Position actual material nodes (not connector nodes which are already positioned)
    if (!node.isConnector && node.chronoIndex !== undefined) {
      node.x = padding + node.chronoIndex * nodeSpacing;
      node.y = baseY;
    }
    // Connector nodes already have x, y set in buildLinkograph - don't override
  });
}

function drawLinkograph(nodes, links) {
  ctx.clearRect(0, 0, width.value, height.value);
  
  // Apply zoom and pan translation
  ctx.save();
  ctx.translate(panX.value, panY.value);
  ctx.translate(width.value / 2, height.value / 2);
  ctx.scale(zoomLevel.value, zoomLevel.value);
  ctx.translate(-width.value / 2, -height.value / 2);

  // Draw edges separately by type
  const baseY = height.value / 2;
  
  const linkColorFor = (link) => {
    const src = link.source?.id ?? link.source;
    const tgt = link.target?.id ?? link.target;
    if (!src || !tgt) return null;

    // Use user colors when in user mode and viewing global graph
    if (colorMode.value === 'users' && !isLoggedIn.value) {
      const srcUser = userAssignments[src];
      const tgtUser = userAssignments[tgt];
      if (srcUser !== undefined && tgtUser !== undefined && srcUser === tgtUser) {
        return userColors[src];
      }
      if (srcUser !== undefined && tgtUser === undefined) return userColors[src];
      if (tgtUser !== undefined && srcUser === undefined) return userColors[tgt];
      return null;
    }

    // allow combination/connector endpoints to inherit the material endpoint color
    const srcComm = communityAssignments[src];
    const tgtComm = communityAssignments[tgt];

    if (srcComm !== undefined && tgtComm !== undefined && srcComm === tgtComm) {
      return communityColors[src];
    }

    // If one side is a combo/connector (no community) but the other has one, use that color
    if (srcComm !== undefined && tgtComm === undefined) return communityColors[src];
    if (tgtComm !== undefined && srcComm === undefined) return communityColors[tgt];

    return null;
  };

  // First, draw duplicate links below the line
  links.forEach(link => {
    if (link.isDuplicate) {
      ctx.strokeStyle = "#666";
      ctx.lineWidth = 1;
      ctx.globalAlpha = 0.3;
      
      ctx.beginPath();
      ctx.moveTo(link.source.x, link.source.y);
      ctx.lineTo(link.target.x, link.target.y);
      ctx.stroke();
    }
  });
  
  // Helper to determine if a link is selected (for highlighting)
  const isLinkSelected = (link) => {
    const src = link.source?.id ?? link.source;
    const tgt = link.target?.id ?? link.target;
    
    if (colorMode.value === 'users' && !isLoggedIn.value) {
      if (selectedUsers.value.size === 0) return null; // no selection active
      
      const srcUser = userAssignments[src];
      const tgtUser = userAssignments[tgt];
      const srcSelected = srcUser !== undefined && selectedUsers.value.has(srcUser);
      const tgtSelected = tgtUser !== undefined && selectedUsers.value.has(tgtUser);
      
      // Also check edgeUserMap for this specific edge
      const edgeKey = link.recipeKey;
      let edgeHasSelectedUser = false;
      if (edgeKey && edgeUserMap[edgeKey]) {
        for (const u of selectedUsers.value) {
          if (edgeUserMap[edgeKey].has(u)) {
            edgeHasSelectedUser = true;
            break;
          }
        }
      }
      
      return srcSelected || tgtSelected || edgeHasSelectedUser;
    } else {
      if (selectedCommunities.value.size === 0) return null; // no selection active
      
      const srcComm = communityAssignments[src];
      const tgtComm = communityAssignments[tgt];
      const srcSelected = srcComm !== undefined && selectedCommunities.value.has(srcComm);
      const tgtSelected = tgtComm !== undefined && selectedCommunities.value.has(tgtComm);
      return srcSelected || tgtSelected;
    }
  };

  // Then, draw recipe edges above the line (use community color if both ends share one)
  links.forEach(link => {
    if (!link.isDuplicate) {
      const isRecipe = link.isRecipe;
      const linkColor = isRecipe ? null : linkColorFor(link);
      const selectionState = isLinkSelected(link);
      const selectionActive = selectionState !== null;
      const isSelected = selectionState === true;
      
      ctx.strokeStyle = linkColor || (isRecipe ? "#ff0000" : "#888");
      ctx.lineWidth = isRecipe ? 2 : (isSelected ? 2 : 1);
      ctx.globalAlpha = selectionActive 
        ? (isSelected ? 0.8 : 0.08)
        : (isRecipe ? 0.7 : (linkColor ? 0.5 : 0.4));
      
      ctx.beginPath();
      ctx.moveTo(link.source.x, link.source.y);
      ctx.lineTo(link.target.x, link.target.y);
      ctx.stroke();
    }
  });
  ctx.globalAlpha = 1;

  // Helper to get selection state based on colorMode
  const getSelectionState = (nodeId) => {
    if (colorMode.value === 'users' && !isLoggedIn.value) {
      const userId = userAssignments[nodeId];
      return {
        selectionActive: selectedUsers.value.size > 0,
        isSelected: userId !== undefined && selectedUsers.value.has(userId)
      };
    } else {
      const commId = communityAssignments[nodeId];
      return {
        selectionActive: selectedCommunities.value.size > 0,
        isSelected: commId !== undefined && selectedCommunities.value.has(commId)
      };
    }
  };

  // Draw nodes
  nodes.forEach(node => {
    const { selectionActive, isSelected } = getSelectionState(node.id);
    // Draw node circle
    ctx.beginPath();
    
    // Choose color based on colorMode
    let nodeColor;
    if (colorMode.value === 'users' && !isLoggedIn.value) {
      nodeColor = (!node.isConnector && userColors[node.id]) ? userColors[node.id] : (node.isConnector ? "#ff9500" : "#219ebc");
    } else {
      nodeColor = (!node.isConnector && communityColors[node.id]) ? communityColors[node.id] : (node.isConnector ? "#ff9500" : "#219ebc");
    }
    
    ctx.fillStyle = nodeColor;
    ctx.globalAlpha = selectionActive ? (isSelected ? 1 : 0.15) : 1;
    const radius = node.isConnector ? 4 : (isSelected ? 8 : 6);
    ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;

    // Draw emoji label (skip for connector nodes)
    if (!node.isConnector) {
      ctx.font = "16px sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      const emoji = node.emoji || "❓";
      ctx.fillText(emoji, node.x, node.y - 14);
    }
  });
  
  ctx.restore();
}

function draw(nodes, links) {
  // Use specialized drawing for linkograph and path linkography modes
  if (renderMode.value === 'Linkograph' || renderMode.value === 'Path Linkography') {
    drawLinkograph(nodes, links);
    return;
  }
  
  // Use specialized drawing for community graph mode
  if (renderMode.value === 'Community') {
    drawCommunityGraph(nodes, links);
    return;
  }
  
  ctx.clearRect(0, 0, width.value, height.value);
  
  // Apply zoom and pan translation
  ctx.save();
  ctx.translate(panX.value, panY.value);
  ctx.translate(width.value / 2, height.value / 2);
  ctx.scale(zoomLevel.value, zoomLevel.value);
  ctx.translate(-width.value / 2, -height.value / 2);

  // Helper to pick a color for a link based on colorMode
  const linkColorFor = (link) => {
    const src = link.source?.id ?? link.source;
    const tgt = link.target?.id ?? link.target;
    if (!src || !tgt) return null;

    // Use user colors when in user mode and viewing global graph
    if (colorMode.value === 'users' && !isLoggedIn.value) {
      const srcUser = userAssignments[src];
      const tgtUser = userAssignments[tgt];
      if (srcUser !== undefined && tgtUser !== undefined && srcUser === tgtUser) {
        return userColors[src];
      }
      if (srcUser !== undefined && tgtUser === undefined) return userColors[src];
      if (tgtUser !== undefined && srcUser === undefined) return userColors[tgt];
      return null;
    }

    const srcComm = communityAssignments[src];
    const tgtComm = communityAssignments[tgt];

    // both endpoints in same community
    if (srcComm !== undefined && tgtComm !== undefined && srcComm === tgtComm) {
      return communityColors[src];
    }

    // one endpoint is unclassified (combo/connector) — inherit from the classified side
    if (srcComm !== undefined && tgtComm === undefined) return communityColors[src];
    if (tgtComm !== undefined && srcComm === undefined) return communityColors[tgt];

    return null;
  };

  // Determine which selection system to use based on colorMode
  const getSelectionState = (nodeId) => {
    if (colorMode.value === 'users' && !isLoggedIn.value) {
      const userId = userAssignments[nodeId];
      return {
        selectionActive: selectedUsers.value.size > 0,
        isSelected: userId !== undefined && selectedUsers.value.has(userId)
      };
    } else {
      const commId = communityAssignments[nodeId];
      return {
        selectionActive: selectedCommunities.value.size > 0,
        isSelected: commId !== undefined && selectedCommunities.value.has(commId)
      };
    }
  };

  // Draw links individually for dynamic styling
  links.forEach(l => {
    const isRecipe = l.isRecipe;
    const isLabelHi = renderMode.value === 'Labeled Arrows' && l.isLabelHighlight;
    const linkColor = (!isRecipe && !isLabelHi) ? linkColorFor(l) : null;
    
    const srcId = l.source?.id ?? l.source;
    const tgtId = l.target?.id ?? l.target;
    const srcState = getSelectionState(srcId);
    const tgtState = getSelectionState(tgtId);
    const selectionActive = srcState.selectionActive;
    
    // For user mode, check if any selected user traversed this edge
    let isSelectedLink = srcState.isSelected || tgtState.isSelected;
    if (colorMode.value === 'users' && !isLoggedIn.value && l.recipeKey && selectedUsers.value.size > 0) {
      const edgeUsers = edgeUserMap[l.recipeKey];
      if (edgeUsers) {
        for (const user of selectedUsers.value) {
          if (edgeUsers.has(user)) {
            isSelectedLink = true;
            break;
          }
        }
      }
    }

    ctx.strokeStyle = isRecipe ? "#ff0000" : (isLabelHi ? "#1e90ff" : (linkColor || "#888"));
    ctx.lineWidth = (isRecipe || isLabelHi || isSelectedLink) ? 2.2 : 1;
    ctx.globalAlpha = isRecipe ? 0.7 : (isLabelHi ? 0.6 : (selectionActive ? (isSelectedLink ? 0.85 : 0.12) : (linkColor ? 0.5 : 0.3)));
    ctx.beginPath();
    ctx.moveTo(l.source.x, l.source.y);
    ctx.lineTo(l.target.x, l.target.y);
    ctx.stroke();
    ctx.globalAlpha = 1;
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
    const { selectionActive, isSelected } = getSelectionState(n.id);
    ctx.beginPath();
    
    // Choose color based on colorMode
    let color;
    if (colorMode.value === 'users' && !isLoggedIn.value) {
      color = (!n.isConnector && userColors[n.id]) ? userColors[n.id] : (n.type === "combination" ? "#ffb703" : "#219ebc");
    } else {
      color = (!n.isConnector && communityColors[n.id]) ? communityColors[n.id] : (n.type === "combination" ? "#ffb703" : "#219ebc");
    }
    
    ctx.fillStyle = color;
    ctx.globalAlpha = selectionActive ? (isSelected ? 1 : 0.18) : 1;
    const radius = isSelected ? 8 : 6;
    ctx.arc(n.x, n.y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;

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
  // Iteratively trace back the recipe path with cycle protection
  const path = new Set();
  const visited = new Set();
  const stack = [targetMaterial];
  let safetyCounter = 0;
  const maxSteps = 50000; // guard against malformed cyclic graphs
  const baseSet = new Set(['Fire', 'Water', 'Earth', 'Air']);

  while (stack.length) {
    const material = stack.pop();
    if (visited.has(material)) continue;
    visited.add(material);

    // Terminate traceback at base materials — do not expand or add edges
    if (baseSet.has(material)) {
      continue;
    }

    const comps = currentRecipeMap[material];
    if (Array.isArray(comps) && comps.length === 2) {
      const [comp1, comp2] = comps;
      path.add(`${comp1}_${comp2}_${material}`);
      if (!visited.has(comp1) && !baseSet.has(comp1)) stack.push(comp1);
      if (!visited.has(comp2) && !baseSet.has(comp2)) stack.push(comp2);
    }

    safetyCounter++;
    if (safetyCounter > maxSteps) {
      console.warn('Path tracing aborted: exceeded maxSteps');
      break;
    }
  }

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

function clearHighlights() {
  // Reset recipe and label highlights so the underlying structure is easier to see
  recipePathEdges = new Set();
  markRecipePathLinks();
  currentLabelHighlight.value = null;
  markLabelHighlightedEdges();
  selectedCommunities.value = new Set();
  selectedUsers.value = new Set();

  if (expandedNodes.length > 0 && expandedLinks.length > 0) {
    draw(expandedNodes, expandedLinks);
  }
}

function onCommunityToggle(commId, checked) {
  const next = new Set(selectedCommunities.value);
  if (checked) {
    next.add(commId);
  } else {
    next.delete(commId);
  }
  selectedCommunities.value = next;

  if (expandedNodes.length > 0 && expandedLinks.length > 0) {
    draw(expandedNodes, expandedLinks);
  }
}

async function recomputeCommunities() {
  // Recompute communities based on the selected algorithm
  if (communityAlgorithm.value === 'directed') {
    communityAssignments = computeCommunitiesDirected(allNodes, originalLinks, COMMUNITY_PARAMS);
  } else if (communityAlgorithm.value === 'in-degree') {
    communityAssignments = computeCommunitiesInDegreeOnly(allNodes, originalLinks, COMMUNITY_PARAMS);
  } else if (communityAlgorithm.value === 'out-degree') {
    communityAssignments = computeCommunitiesOutDegreeOnly(allNodes, originalLinks, COMMUNITY_PARAMS);
  } else if (communityAlgorithm.value === 'infomap') {
    communityAssignments = computeCommunitiesInfomap(allNodes, originalLinks, COMMUNITY_PARAMS);
  } else {
    communityAssignments = computeCommunities(allNodes, originalLinks, COMMUNITY_PARAMS);
  }
  communityColors = assignCommunityColors(communityAssignments);
  communitySummaries.value = buildCommunitySummaries(communityAssignments, communityColors, allNodes, originalLinks);
  
  // Compute global graph centralization
  const materialNodes = allNodes.filter(n => n && n.type !== "combination" && !n.isConnector);
  globalCentralization.value = computeFreemanCentralization(materialNodes, originalLinks, {}, null);
  
  // Fetch embedding statistics for communities
  await fetchCommunityEmbeddingStats(communityAssignments);
  
  // Clear community selection since community IDs may have changed
  selectedCommunities.value = new Set();
  
  // Redraw the graph with new colors
  if (expandedNodes.length > 0 && expandedLinks.length > 0) {
    draw(expandedNodes, expandedLinks);
  }
}

function computeCommunities(nodes, links, params = COMMUNITY_PARAMS) {
  // Louvain-style modularity heuristic on an undirected, unweighted graph derived from links
  const nodeIds = nodes.map(n => n.id);
  const idToIndex = new Map(nodeIds.map((id, idx) => [id, idx]));
  const adjacency = new Map(); // id -> Map(neighborId -> weight)

  const addEdge = (a, b) => {
    if (!a || !b) return;
    if (!adjacency.has(a)) adjacency.set(a, new Map());
    if (!adjacency.has(b)) adjacency.set(b, new Map());
    const wa = adjacency.get(a);
    const wb = adjacency.get(b);
    wa.set(b, (wa.get(b) || 0) + 1);
    wb.set(a, (wb.get(a) || 0) + 1);
  };

  // Build undirected edges from combination links: connect from1->to and from2->to
  links.forEach(l => {
    let added = false;
    if (l.from1 && l.to) {
      addEdge(l.from1, l.to);
      added = true;
    }
    if (l.from2 && l.to) {
      addEdge(l.from2, l.to);
      added = true;
    }
    if (!added) {
      const a = l.source?.id ?? l.source;
      const b = l.target?.id ?? l.target ?? l.to;
      addEdge(a, b);
    }
  });

  // Degrees and total edge weight
  const degrees = new Map();
  let m2 = 0; // 2 * total weight
  adjacency.forEach((neighbors, id) => {
    let d = 0;
    neighbors.forEach(w => { d += w; });
    degrees.set(id, d);
    m2 += d;
  });
  if (m2 === 0) {
    // No edges: each node its own community
    const assignment = {};
    nodeIds.forEach((id, idx) => { assignment[id] = idx; });
    return assignment;
  }

  // Initial communities
  let community = new Map(); // nodeId -> communityId
  let communityWeight = new Map(); // communityId -> sum of degrees
  nodeIds.forEach(id => {
    community.set(id, id);
    communityWeight.set(id, degrees.get(id) || 0);
  });

  let moved = true;
  const maxPasses = params.maxPasses ?? 10;
  let pass = 0;
  while (moved && pass < maxPasses) {
    moved = false;
    pass++;
    // iterate nodes (fixed order is fine for our scale)
    nodeIds.forEach(id => {
      const currentComm = community.get(id);
      const k_i = degrees.get(id) || 0;
      const neighbors = adjacency.get(id) || new Map();

      // Remove node from current community temporarily
      communityWeight.set(currentComm, (communityWeight.get(currentComm) || 0) - k_i);

      // Compute k_i_in for neighbor communities
      const communityConnections = new Map();
      neighbors.forEach((w, nb) => {
        const commNb = community.get(nb);
        communityConnections.set(commNb, (communityConnections.get(commNb) || 0) + w);
      });

      let bestComm = currentComm;
      let bestGain = 0;
      const m = m2 / 2;
      communityConnections.forEach((k_i_in, comm) => {
        const tot = communityWeight.get(comm) || 0;
        const gamma = params.gamma ?? 1.0;
        const gain = k_i_in - gamma * (k_i * tot) / m2;
        if (gain > bestGain) {
          bestGain = gain;
          bestComm = comm;
        }
      });

      // Restore weight to chosen community
      communityWeight.set(bestComm, (communityWeight.get(bestComm) || 0) + k_i);

      const minGain = params.minGain ?? 0;
      if (bestComm !== currentComm && bestGain > minGain) {
        community.set(id, bestComm);
        moved = true;
      }
    });
  }

  const assignment = {};
  nodeIds.forEach(id => { assignment[id] = community.get(id); });
  return assignment;
}

function computeCommunitiesDirected(nodes, links, params = COMMUNITY_PARAMS) {
  // Louvain-style modularity heuristic on a DIRECTED, unweighted graph derived from links
  // Uses directed modularity: Q = (1/m) * sum[ A_ij - (k_out_i * k_in_j) / m ] * delta(c_i, c_j)
  const nodeIds = nodes.map(n => n.id);
  const outAdj = new Map(); // id -> Map(neighborId -> weight) for outgoing edges
  const inAdj = new Map();  // id -> Map(neighborId -> weight) for incoming edges

  const addDirectedEdge = (from, to) => {
    if (!from || !to) return;
    if (!outAdj.has(from)) outAdj.set(from, new Map());
    if (!inAdj.has(to)) inAdj.set(to, new Map());
    const outMap = outAdj.get(from);
    outMap.set(to, (outMap.get(to) || 0) + 1);
    const inMap = inAdj.get(to);
    inMap.set(from, (inMap.get(from) || 0) + 1);
  };

  // Build directed edges from combination links: from1->to and from2->to
  links.forEach(l => {
    let added = false;
    if (l.from1 && l.to) {
      addDirectedEdge(l.from1, l.to);
      added = true;
    }
    if (l.from2 && l.to) {
      addDirectedEdge(l.from2, l.to);
      added = true;
    }
    if (!added) {
      const a = l.source?.id ?? l.source;
      const b = l.target?.id ?? l.target ?? l.to;
      addDirectedEdge(a, b);
    }
  });

  // Compute in-degrees and out-degrees
  const outDegrees = new Map();
  const inDegrees = new Map();
  let m = 0; // total number of edges
  
  nodeIds.forEach(id => {
    let outDeg = 0;
    let inDeg = 0;
    if (outAdj.has(id)) {
      outAdj.get(id).forEach(w => { outDeg += w; });
    }
    if (inAdj.has(id)) {
      inAdj.get(id).forEach(w => { inDeg += w; });
    }
    outDegrees.set(id, outDeg);
    inDegrees.set(id, inDeg);
    m += outDeg; // count total edges
  });

  if (m === 0) {
    // No edges: each node its own community
    const assignment = {};
    nodeIds.forEach((id, idx) => { assignment[id] = idx; });
    return assignment;
  }

  // Initial communities
  let community = new Map(); // nodeId -> communityId
  // Track sum of in-degrees and out-degrees per community
  let commInDeg = new Map(); // communityId -> sum of in-degrees
  let commOutDeg = new Map(); // communityId -> sum of out-degrees
  
  nodeIds.forEach(id => {
    community.set(id, id);
    commInDeg.set(id, inDegrees.get(id) || 0);
    commOutDeg.set(id, outDegrees.get(id) || 0);
  });

  let moved = true;
  const maxPasses = params.maxPasses ?? 10;
  let pass = 0;
  
  while (moved && pass < maxPasses) {
    moved = false;
    pass++;
    
    nodeIds.forEach(id => {
      const currentComm = community.get(id);
      const k_out_i = outDegrees.get(id) || 0;
      const k_in_i = inDegrees.get(id) || 0;

      // Remove node from current community
      commOutDeg.set(currentComm, (commOutDeg.get(currentComm) || 0) - k_out_i);
      commInDeg.set(currentComm, (commInDeg.get(currentComm) || 0) - k_in_i);

      // Compute connections to/from neighbor communities
      // For directed modularity, we need both incoming and outgoing edges
      const communityConnections = new Map(); // commId -> { inEdges, outEdges }
      
      // Outgoing edges from this node
      if (outAdj.has(id)) {
        outAdj.get(id).forEach((w, nb) => {
          const commNb = community.get(nb);
          if (!communityConnections.has(commNb)) {
            communityConnections.set(commNb, { inEdges: 0, outEdges: 0 });
          }
          communityConnections.get(commNb).outEdges += w;
        });
      }
      
      // Incoming edges to this node
      if (inAdj.has(id)) {
        inAdj.get(id).forEach((w, nb) => {
          const commNb = community.get(nb);
          if (!communityConnections.has(commNb)) {
            communityConnections.set(commNb, { inEdges: 0, outEdges: 0 });
          }
          communityConnections.get(commNb).inEdges += w;
        });
      }

      let bestComm = currentComm;
      let bestGain = 0;
      const gamma = params.gamma ?? 1.0;
      
      communityConnections.forEach((conn, comm) => {
        const totIn = commInDeg.get(comm) || 0;
        const totOut = commOutDeg.get(comm) || 0;
        
        // Directed modularity gain:
        // delta_Q = (1/m) * [ (edges from i to C) + (edges from C to i) - gamma * (k_out_i * tot_in_C + k_in_i * tot_out_C) / m ]
        const edgesToComm = conn.outEdges;
        const edgesFromComm = conn.inEdges;
        const nullModelTerm = gamma * (k_out_i * totIn + k_in_i * totOut) / m;
        const gain = (edgesToComm + edgesFromComm) - nullModelTerm;
        
        if (gain > bestGain) {
          bestGain = gain;
          bestComm = comm;
        }
      });

      // Add node to best community
      commOutDeg.set(bestComm, (commOutDeg.get(bestComm) || 0) + k_out_i);
      commInDeg.set(bestComm, (commInDeg.get(bestComm) || 0) + k_in_i);

      const minGain = params.minGain ?? 0;
      if (bestComm !== currentComm && bestGain > minGain) {
        community.set(id, bestComm);
        moved = true;
      }
    });
  }

  const assignment = {};
  nodeIds.forEach(id => { assignment[id] = community.get(id); });
  return assignment;
}

function computeCommunitiesInDegreeOnly(nodes, links, params = COMMUNITY_PARAMS) {
  // Louvain-style modularity using ONLY in-degree neighbors (nodes that point TO this node)
  // This groups nodes by what points to them (shared predecessors)
  const nodeIds = nodes.map(n => n.id);
  const inAdj = new Map(); // id -> Map(neighborId -> weight) for incoming edges

  const addDirectedEdge = (from, to) => {
    if (!from || !to) return;
    if (!inAdj.has(to)) inAdj.set(to, new Map());
    const inMap = inAdj.get(to);
    inMap.set(from, (inMap.get(from) || 0) + 1);
  };

  // Build directed edges from combination links: from1->to and from2->to
  links.forEach(l => {
    let added = false;
    if (l.from1 && l.to) {
      addDirectedEdge(l.from1, l.to);
      added = true;
    }
    if (l.from2 && l.to) {
      addDirectedEdge(l.from2, l.to);
      added = true;
    }
    if (!added) {
      const a = l.source?.id ?? l.source;
      const b = l.target?.id ?? l.target ?? l.to;
      addDirectedEdge(a, b);
    }
  });

  // Compute in-degrees only
  const inDegrees = new Map();
  let m2 = 0; // sum of all in-degrees (= total edges)
  
  nodeIds.forEach(id => {
    let inDeg = 0;
    if (inAdj.has(id)) {
      inAdj.get(id).forEach(w => { inDeg += w; });
    }
    inDegrees.set(id, inDeg);
    m2 += inDeg;
  });

  if (m2 === 0) {
    const assignment = {};
    nodeIds.forEach((id, idx) => { assignment[id] = idx; });
    return assignment;
  }

  // Initial communities
  let community = new Map();
  let communityWeight = new Map(); // sum of in-degrees per community
  
  nodeIds.forEach(id => {
    community.set(id, id);
    communityWeight.set(id, inDegrees.get(id) || 0);
  });

  let moved = true;
  const maxPasses = params.maxPasses ?? 10;
  let pass = 0;
  
  while (moved && pass < maxPasses) {
    moved = false;
    pass++;
    
    nodeIds.forEach(id => {
      const currentComm = community.get(id);
      const k_i = inDegrees.get(id) || 0;
      const neighbors = inAdj.get(id) || new Map(); // Only in-neighbors

      // Remove node from current community
      communityWeight.set(currentComm, (communityWeight.get(currentComm) || 0) - k_i);

      // Compute connections to neighbor communities (via in-edges)
      const communityConnections = new Map();
      neighbors.forEach((w, nb) => {
        const commNb = community.get(nb);
        communityConnections.set(commNb, (communityConnections.get(commNb) || 0) + w);
      });

      let bestComm = currentComm;
      let bestGain = 0;
      const gamma = params.gamma ?? 1.0;
      
      communityConnections.forEach((k_i_in, comm) => {
        const tot = communityWeight.get(comm) || 0;
        const gain = k_i_in - gamma * (k_i * tot) / m2;
        if (gain > bestGain) {
          bestGain = gain;
          bestComm = comm;
        }
      });

      // Restore weight to chosen community
      communityWeight.set(bestComm, (communityWeight.get(bestComm) || 0) + k_i);

      const minGain = params.minGain ?? 0;
      if (bestComm !== currentComm && bestGain > minGain) {
        community.set(id, bestComm);
        moved = true;
      }
    });
  }

  const assignment = {};
  nodeIds.forEach(id => { assignment[id] = community.get(id); });
  return assignment;
}

function computeCommunitiesOutDegreeOnly(nodes, links, params = COMMUNITY_PARAMS) {
  // Louvain-style modularity using ONLY out-degree neighbors (nodes this node points TO)
  // This groups nodes by what they produce (shared successors)
  const nodeIds = nodes.map(n => n.id);
  const outAdj = new Map(); // id -> Map(neighborId -> weight) for outgoing edges

  const addDirectedEdge = (from, to) => {
    if (!from || !to) return;
    if (!outAdj.has(from)) outAdj.set(from, new Map());
    const outMap = outAdj.get(from);
    outMap.set(to, (outMap.get(to) || 0) + 1);
  };

  // Build directed edges from combination links: from1->to and from2->to
  links.forEach(l => {
    let added = false;
    if (l.from1 && l.to) {
      addDirectedEdge(l.from1, l.to);
      added = true;
    }
    if (l.from2 && l.to) {
      addDirectedEdge(l.from2, l.to);
      added = true;
    }
    if (!added) {
      const a = l.source?.id ?? l.source;
      const b = l.target?.id ?? l.target ?? l.to;
      addDirectedEdge(a, b);
    }
  });

  // Compute out-degrees only
  const outDegrees = new Map();
  let m2 = 0; // sum of all out-degrees (= total edges)
  
  nodeIds.forEach(id => {
    let outDeg = 0;
    if (outAdj.has(id)) {
      outAdj.get(id).forEach(w => { outDeg += w; });
    }
    outDegrees.set(id, outDeg);
    m2 += outDeg;
  });

  if (m2 === 0) {
    const assignment = {};
    nodeIds.forEach((id, idx) => { assignment[id] = idx; });
    return assignment;
  }

  // Initial communities
  let community = new Map();
  let communityWeight = new Map(); // sum of out-degrees per community
  
  nodeIds.forEach(id => {
    community.set(id, id);
    communityWeight.set(id, outDegrees.get(id) || 0);
  });

  let moved = true;
  const maxPasses = params.maxPasses ?? 10;
  let pass = 0;
  
  while (moved && pass < maxPasses) {
    moved = false;
    pass++;
    
    nodeIds.forEach(id => {
      const currentComm = community.get(id);
      const k_i = outDegrees.get(id) || 0;
      const neighbors = outAdj.get(id) || new Map(); // Only out-neighbors

      // Remove node from current community
      communityWeight.set(currentComm, (communityWeight.get(currentComm) || 0) - k_i);

      // Compute connections to neighbor communities (via out-edges)
      const communityConnections = new Map();
      neighbors.forEach((w, nb) => {
        const commNb = community.get(nb);
        communityConnections.set(commNb, (communityConnections.get(commNb) || 0) + w);
      });

      let bestComm = currentComm;
      let bestGain = 0;
      const gamma = params.gamma ?? 1.0;
      
      communityConnections.forEach((k_i_in, comm) => {
        const tot = communityWeight.get(comm) || 0;
        const gain = k_i_in - gamma * (k_i * tot) / m2;
        if (gain > bestGain) {
          bestGain = gain;
          bestComm = comm;
        }
      });

      // Restore weight to chosen community
      communityWeight.set(bestComm, (communityWeight.get(bestComm) || 0) + k_i);

      const minGain = params.minGain ?? 0;
      if (bestComm !== currentComm && bestGain > minGain) {
        community.set(id, bestComm);
        moved = true;
      }
    });
  }

  const assignment = {};
  nodeIds.forEach(id => { assignment[id] = community.get(id); });
  return assignment;
}

function computeCommunitiesInfomap(nodes, links, params = COMMUNITY_PARAMS) {
  // Infomap-style community detection using random walk and information theory
  // Minimizes the expected description length of a random walk on the network
  // Based on the map equation: L = qH(Q) + sum_i(p_i * H(P_i))
  const nodeIds = nodes.map(n => n.id);
  const outAdj = new Map(); // id -> Map(neighborId -> weight) for outgoing edges
  const inAdj = new Map();  // id -> Map(neighborId -> weight) for incoming edges

  const addDirectedEdge = (from, to) => {
    if (!from || !to) return;
    if (!outAdj.has(from)) outAdj.set(from, new Map());
    if (!inAdj.has(to)) inAdj.set(to, new Map());
    const outMap = outAdj.get(from);
    outMap.set(to, (outMap.get(to) || 0) + 1);
    const inMap = inAdj.get(to);
    inMap.set(from, (inMap.get(from) || 0) + 1);
  };

  // Build directed edges from combination links
  links.forEach(l => {
    let added = false;
    if (l.from1 && l.to) {
      addDirectedEdge(l.from1, l.to);
      added = true;
    }
    if (l.from2 && l.to) {
      addDirectedEdge(l.from2, l.to);
      added = true;
    }
    if (!added) {
      const a = l.source?.id ?? l.source;
      const b = l.target?.id ?? l.target ?? l.to;
      addDirectedEdge(a, b);
    }
  });

  // Compute out-degrees and in-degrees
  const outDegrees = new Map();
  const inDegrees = new Map();
  let totalEdges = 0;

  nodeIds.forEach(id => {
    let outDeg = 0;
    let inDeg = 0;
    if (outAdj.has(id)) {
      outAdj.get(id).forEach(w => { outDeg += w; });
    }
    if (inAdj.has(id)) {
      inAdj.get(id).forEach(w => { inDeg += w; });
    }
    outDegrees.set(id, outDeg);
    inDegrees.set(id, inDeg);
    totalEdges += outDeg;
  });

  if (totalEdges === 0) {
    const assignment = {};
    nodeIds.forEach((id, idx) => { assignment[id] = idx; });
    return assignment;
  }

  // Compute PageRank-like stationary distribution (teleport probability tau = 0.15)
  const tau = 0.15;
  const numNodes = nodeIds.length;
  let pagerank = new Map();
  const danglingNodes = nodeIds.filter(id => (outDegrees.get(id) || 0) === 0);

  // Initialize uniform distribution
  nodeIds.forEach(id => pagerank.set(id, 1.0 / numNodes));

  // Power iteration for PageRank
  for (let iter = 0; iter < 100; iter++) {
    const newPagerank = new Map();
    let danglingSum = 0;
    danglingNodes.forEach(id => { danglingSum += pagerank.get(id) || 0; });

    nodeIds.forEach(id => {
      let rank = tau / numNodes; // teleportation
      rank += (1 - tau) * danglingSum / numNodes; // dangling node contribution
      
      // Contribution from incoming edges
      const incoming = inAdj.get(id) || new Map();
      incoming.forEach((w, srcId) => {
        const srcOutDeg = outDegrees.get(srcId) || 1;
        rank += (1 - tau) * (pagerank.get(srcId) || 0) * w / srcOutDeg;
      });
      newPagerank.set(id, rank);
    });

    // Normalize
    let sum = 0;
    newPagerank.forEach(v => { sum += v; });
    if (sum > 0) {
      newPagerank.forEach((v, k) => newPagerank.set(k, v / sum));
    }
    pagerank = newPagerank;
  }

  // Helper: entropy function H(p) = -sum(p_i * log2(p_i))
  const entropy = (probs) => {
    let h = 0;
    probs.forEach(p => {
      if (p > 0) h -= p * Math.log2(p);
    });
    return h;
  };

  // Helper: plogp(x) = x * log2(x) or 0 if x <= 0
  const plogp = (x) => (x > 0 ? x * Math.log2(x) : 0);

  // Compute map equation codelength for a given partition
  const computeCodelength = (community, nodeIds) => {
    const moduleNodes = new Map(); // moduleId -> Set of nodeIds
    const modulePagerank = new Map(); // moduleId -> sum of pagerank
    const moduleExitFlow = new Map(); // moduleId -> exit probability

    // Group nodes by module
    nodeIds.forEach(id => {
      const mod = community.get(id);
      if (!moduleNodes.has(mod)) moduleNodes.set(mod, new Set());
      moduleNodes.get(mod).add(id);
      modulePagerank.set(mod, (modulePagerank.get(mod) || 0) + (pagerank.get(id) || 0));
    });

    // Compute exit flow for each module
    moduleNodes.forEach((nodes, mod) => {
      let exitFlow = 0;
      nodes.forEach(id => {
        const pr = pagerank.get(id) || 0;
        const outDeg = outDegrees.get(id) || 0;
        if (outDeg > 0) {
          const outNeighbors = outAdj.get(id) || new Map();
          outNeighbors.forEach((w, tgtId) => {
            // If target is in different module, add to exit flow
            if (!nodes.has(tgtId)) {
              exitFlow += pr * w / outDeg;
            }
          });
        }
        // Add teleportation exit
        exitFlow += tau * pr * (numNodes - nodes.size) / numNodes;
      });
      moduleExitFlow.set(mod, exitFlow);
    });

    // Calculate codelength using map equation
    // L = q * H(Q) + sum_m(p_m + q_m) * H(P_m)
    // where q = sum of exit flows, H(Q) = entropy of exit distribution
    // p_m = module pagerank, q_m = module exit flow

    let totalExit = 0;
    moduleExitFlow.forEach(q => { totalExit += q; });

    // Index codelength: q * H(Q)
    let indexCodelength = 0;
    if (totalExit > 0) {
      const exitProbs = [];
      moduleExitFlow.forEach(q => { if (q > 0) exitProbs.push(q / totalExit); });
      indexCodelength = totalExit * entropy(exitProbs);
    }

    // Module codelength: sum_m (p_m + q_m) * H(P_m)
    let moduleCodelength = 0;
    moduleNodes.forEach((nodes, mod) => {
      const modPr = modulePagerank.get(mod) || 0;
      const modExit = moduleExitFlow.get(mod) || 0;
      const modTotal = modPr + modExit;
      
      if (modTotal > 0 && nodes.size > 0) {
        // Entropy of movements within module + exit
        const probs = [];
        nodes.forEach(id => {
          const pr = pagerank.get(id) || 0;
          probs.push(pr / modTotal);
        });
        if (modExit > 0) probs.push(modExit / modTotal);
        moduleCodelength += modTotal * entropy(probs);
      }
    });

    return indexCodelength + moduleCodelength;
  };

  // Initialize each node in its own community
  let community = new Map();
  nodeIds.forEach(id => community.set(id, id));

  let currentCodelength = computeCodelength(community, nodeIds);
  let improved = true;
  const maxPasses = params.maxPasses ?? 50;
  let pass = 0;

  while (improved && pass < maxPasses) {
    improved = false;
    pass++;

    // Try moving each node to neighbor's community
    nodeIds.forEach(id => {
      const currentMod = community.get(id);
      const neighbors = new Set();
      
      // Collect neighboring modules (via both in and out edges)
      const outNeighbors = outAdj.get(id) || new Map();
      const inNeighbors = inAdj.get(id) || new Map();
      outNeighbors.forEach((_, nb) => neighbors.add(community.get(nb)));
      inNeighbors.forEach((_, nb) => neighbors.add(community.get(nb)));
      neighbors.delete(currentMod); // Don't check current module

      let bestMod = currentMod;
      let bestCodelength = currentCodelength;

      neighbors.forEach(targetMod => {
        // Try moving node to targetMod
        community.set(id, targetMod);
        const newCodelength = computeCodelength(community, nodeIds);
        
        if (newCodelength < bestCodelength - 1e-10) {
          bestCodelength = newCodelength;
          bestMod = targetMod;
        }
        
        // Restore original
        community.set(id, currentMod);
      });

      if (bestMod !== currentMod) {
        community.set(id, bestMod);
        currentCodelength = bestCodelength;
        improved = true;
      }
    });
  }

  const assignment = {};
  nodeIds.forEach(id => { assignment[id] = community.get(id); });
  return assignment;
}

function computeUserAssignments(nodes, links) {
  // Assign each node to the user who first discovered it (based on link order)
  // Also build edgeUserMap: which users traversed each edge
  // Skip duplicate/flipped recipes
  const assignments = {};
  const edgeUsers = {}; // recipeKey -> Set of usernames
  const seenRecipes = new Set(); // Track normalized recipes to skip flips
  
  // Base materials have no user - assign to 'system'
  ['Fire', 'Water', 'Earth', 'Air'].forEach(base => {
    assignments[base] = 'system';
  });
  
  // Helper to normalize recipe (canonical form: alphabetically sorted ingredients)
  const normalizeRecipe = (from1, from2, to) => {
    const ingredients = [from1, from2].sort().join('_');
    return `${ingredients}_${to}`;
  };
  
  // Process links in chronological order
  links.forEach(link => {
    const resultId = link.to;
    const linkUser = link.username || 'unknown';
    
    // Get normalized recipe to detect flipped combinations
    const normalizedRecipe = normalizeRecipe(link.from1, link.from2, link.to);
    
    // Skip if we've already seen this recipe (or its flip)
    if (seenRecipes.has(normalizedRecipe)) {
      return;
    }
    seenRecipes.add(normalizedRecipe);
    
    // First link to create this result determines the discoverer
    if (resultId && !assignments[resultId]) {
      assignments[resultId] = linkUser;
    }
    
    // Track all users who traversed this edge (recipe)
    const recipeKey = `${link.from1}_${link.from2}_${link.to}`;
    if (!edgeUsers[recipeKey]) {
      edgeUsers[recipeKey] = new Set();
    }
    edgeUsers[recipeKey].add(linkUser);
  });
  
  // Store edgeUserMap globally
  edgeUserMap = edgeUsers;
  
  return assignments;
}

function assignUserColors(assignments) {
  // Palette avoids bright red/blue to keep recipe/label highlights readable
  const palette = [
    '#f4a261', // amber
    '#6dccb5', // mint
    '#a4c639', // olive-lime
    '#8f5fe8', // violet
    '#d17ba0', // rose
    '#5ca9a5', // teal
    '#c7b446', // ochre
    '#6ab04c', // green
    '#b86ee0', // purple
    '#e6b980'  // sand
  ];

  const colors = {};
  const userToColor = new Map();
  let idx = 0;
  Object.entries(assignments).forEach(([nodeId, userId]) => {
    if (!userToColor.has(userId)) {
      userToColor.set(userId, palette[idx % palette.length]);
      idx++;
    }
    colors[nodeId] = userToColor.get(userId);
  });
  return colors;
}

function buildUserSummaries(assignments, colors, nodes) {
  const group = new Map();
  nodes.forEach(n => {
    if (!n || n.type === "combination" || n.isConnector) return;
    const userId = assignments[n.id];
    if (userId === undefined) return;
    if (!group.has(userId)) group.set(userId, { color: null, nodes: [] });
    const entry = group.get(userId);
    entry.color = entry.color || colors[n.id] || '#219ebc';
    entry.nodes.push(n);
  });

  return [...group.entries()].map(([userId, { color, nodes }]) => {
    const labels = nodes.slice(0, 5).map(n => n.label || n.id);
    return {
      id: userId,
      color,
      count: nodes.length,
      labels
    };
  }).sort((a, b) => b.count - a.count);
}

function onUserToggle(userId, checked) {
  const next = new Set(selectedUsers.value);
  if (checked) {
    next.add(userId);
  } else {
    next.delete(userId);
  }
  selectedUsers.value = next;

  if (expandedNodes.length > 0 && expandedLinks.length > 0) {
    draw(expandedNodes, expandedLinks);
  }
}

function assignCommunityColors(assignments) {
  // Palette avoids bright red/blue to keep recipe/label highlights readable
  const palette = [
    '#f4a261', // amber
    '#6dccb5', // mint
    '#a4c639', // olive-lime
    '#8f5fe8', // violet
    '#d17ba0', // rose
    '#5ca9a5', // teal
    '#c7b446', // ochre
    '#6ab04c', // green
    '#b86ee0', // purple
    '#e6b980'  // sand
  ];

  const colors = {};
  const commToColor = new Map();
  let idx = 0;
  Object.entries(assignments).forEach(([nodeId, commId]) => {
    if (!commToColor.has(commId)) {
      commToColor.set(commId, palette[idx % palette.length]);
      idx++;
    }
    colors[nodeId] = commToColor.get(commId);
  });
  return colors;
}

function buildCommunitySummaries(assignments, colors, nodes, links) {
  const group = new Map();
  nodes.forEach(n => {
    if (!n || n.type === "combination" || n.isConnector) return;
    const comm = assignments[n.id];
    if (comm === undefined) return;
    if (!group.has(comm)) group.set(comm, { color: null, nodes: [] });
    const entry = group.get(comm);
    entry.color = entry.color || colors[n.id] || '#219ebc';
    entry.nodes.push(n);
  });

  // Build a map from result node to its first creation link (chronologically first)
  // Links are already in chronological order
  const firstCreationLink = new Map(); // resultId -> { from1, from2, to }
  links.forEach(link => {
    const { from1, from2, to } = link;
    if (!to) return;
    if (!firstCreationLink.has(to)) {
      firstCreationLink.set(to, { from1, from2, to });
    }
  });

  // Compute directed inter-community edge counts
  // inDegrees[commA][commB] = count of edges FROM commB TO commA
  // outDegrees[commA][commB] = count of edges FROM commA TO commB
  const inDegrees = new Map(); // commId -> Map(sourceCommId -> count)
  const outDegrees = new Map(); // commId -> Map(targetCommId -> count)
  
  // Initialize maps for all communities
  group.forEach((_, commId) => {
    inDegrees.set(commId, new Map());
    outDegrees.set(commId, new Map());
  });
  
  // Count directed edges between communities
  links.forEach(link => {
    const { from1, from2, to } = link;
    if (!from1 || !from2 || !to) return;
    
    const comm1 = assignments[from1];
    const comm2 = assignments[from2];
    const commTo = assignments[to];
    
    const countDirectedEdge = (fromComm, toComm) => {
      if (fromComm === undefined || toComm === undefined || fromComm === toComm) return;
      if (!group.has(fromComm) || !group.has(toComm)) return;
      
      // outDegrees: fromComm -> toComm
      const outMap = outDegrees.get(fromComm);
      if (outMap) outMap.set(toComm, (outMap.get(toComm) || 0) + 1);
      
      // inDegrees: toComm <- fromComm
      const inMap = inDegrees.get(toComm);
      if (inMap) inMap.set(fromComm, (inMap.get(fromComm) || 0) + 1);
    };
    
    countDirectedEdge(comm1, commTo);
    if (comm2 !== comm1) {
      countDirectedEdge(comm2, commTo);
    }
  });

  return [...group.entries()].map(([commId, { color, nodes: commNodes }]) => {
    const labels = commNodes.slice(0, 5).map(n => n.label || n.id);
    
    // Compute Freeman Degree Centralization for this community
    const centralization = computeFreemanCentralization(commNodes, links, assignments, commId);
    
    // Get top 2 source communities (communities that point TO this one - in-degrees)
    const inMap = inDegrees.get(commId) || new Map();
    const topSources = [...inMap.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 2)
      .map(([srcCommId, count]) => ({ id: srcCommId, count }));
    
    // Get top 2 sink communities (communities this one points TO - out-degrees)
    const outMap = outDegrees.get(commId) || new Map();
    const topSinks = [...outMap.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 2)
      .map(([tgtCommId, count]) => ({ id: tgtCommId, count }));
    
    // Find parent communities: the community of the ingredients that created the first resource
    // Sort nodes by chronological index (smaller = earlier) to find the first resource
    const sortedNodes = [...commNodes].sort((a, b) => {
      const idxA = a.chronoIndex ?? Infinity;
      const idxB = b.chronoIndex ?? Infinity;
      return idxA - idxB;
    });
    
    let parentCommunities = [];
    // Find the first node that was created (has a creation link)
    for (const node of sortedNodes) {
      const creationLink = firstCreationLink.get(node.id);
      if (creationLink) {
        const { from1, from2 } = creationLink;
        const parentComm1 = assignments[from1];
        const parentComm2 = assignments[from2];
        
        // Collect unique parent communities (excluding self)
        const parents = new Set();
        if (parentComm1 !== undefined && parentComm1 !== commId) parents.add(parentComm1);
        if (parentComm2 !== undefined && parentComm2 !== commId) parents.add(parentComm2);
        
        // Also include self if one of the parents is from the same community
        if (parentComm1 === commId || parentComm2 === commId) {
          // One parent is from same community - note this
          if (parentComm1 !== undefined) parents.add(parentComm1);
          if (parentComm2 !== undefined) parents.add(parentComm2);
        }
        
        parentCommunities = [...parents];
        break;
      }
    }
    
    return {
      id: commId,
      color,
      count: commNodes.length,
      labels,
      centralization,
      topSources,
      topSinks,
      parentCommunities
    };
  }).sort((a, b) => b.count - a.count);
}

function computeFreemanCentralization(communityNodes, links, assignments, commId) {
  // Freeman Degree Centralization: C_D = sum(d_max - d_i) / [(n-1)(n-2)]
  // For undirected graph within the community
  
  const n = communityNodes.length;
  if (n <= 2) return 0; // Centralization undefined for n <= 2
  
  // Build set of node IDs in this community
  const nodeSet = new Set(communityNodes.map(node => node.id));
  
  // First, collect unique edges within the community (deduplicate)
  // Use a Set with canonical edge keys (sorted node IDs)
  const edgeSet = new Set();
  
  const addEdge = (a, b) => {
    if (!nodeSet.has(a) || !nodeSet.has(b)) return;
    if (a === b) return; // skip self-loops
    // Canonical form: alphabetically sorted
    const key = a < b ? `${a}|${b}` : `${b}|${a}`;
    edgeSet.add(key);
  };
  
  links.forEach(link => {
    // Handle combination link format: from1 + from2 -> to
    if (link.from1 && link.from2 && link.to) {
      addEdge(link.from1, link.to);
      addEdge(link.from2, link.to);
    } else {
      // Standard source-target format
      const src = link.source?.id ?? link.source;
      const tgt = link.target?.id ?? link.target ?? link.to;
      if (src && tgt) {
        addEdge(src, tgt);
      }
    }
  });
  
  // Now compute degrees from the deduplicated edge set
  const degrees = new Map();
  nodeSet.forEach(id => degrees.set(id, 0));
  
  edgeSet.forEach(edgeKey => {
    const [a, b] = edgeKey.split('|');
    degrees.set(a, degrees.get(a) + 1);
    degrees.set(b, degrees.get(b) + 1);
  });
  
  // Find max degree and sum of differences
  let maxDegree = 0;
  degrees.forEach(d => {
    if (d > maxDegree) maxDegree = d;
  });
  
  let sumDiff = 0;
  degrees.forEach(d => {
    sumDiff += (maxDegree - d);
  });
  
  // Freeman centralization formula
  // Maximum possible sum for a star graph is (n-1)(n-2)
  const maxPossible = (n - 1) * (n - 2);
  if (maxPossible === 0) return 0;
  
  return sumDiff / maxPossible;
}

async function fetchCommunityEmbeddingStats(assignments) {
  // Fetch embedding statistics (avg distance, std) for each community from the backend
  try {
    const apiUrl = import.meta.env.VITE_FLASK_API_URL || 'http://localhost:3000';
    const res = await fetch(`${apiUrl}/api/community-embedding-stats`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ communities: assignments })
    });
    
    if (!res.ok) {
      console.error("Failed to fetch community embedding stats:", res.status);
      return;
    }
    
    const { stats, avgInterCommunityDistance } = await res.json();
    
    // Update communitySummaries with embedding stats
    communitySummaries.value = communitySummaries.value.map(comm => {
      const commStats = stats[String(comm.id)];
      return {
        ...comm,
        avgDistToCentroid: commStats?.avgDistToCentroid ?? 0,
        stdDistToCentroid: commStats?.stdDistToCentroid ?? 0,
        maxDistToCentroid: commStats?.maxDistToCentroid ?? 0
      };
    });
    
    // Store inter-community distance for context
    globalInterCommunityDistance.value = avgInterCommunityDistance ?? 0;
    
    console.log("Community embedding stats loaded:", stats, "Inter-community dist:", avgInterCommunityDistance);
  } catch (err) {
    console.error("Error fetching community embedding stats:", err);
  }
}

function drawCommunityDiscoveryChart() {
  if (!discoveryCanvas.value || !originalLinks.length || !allNodes.length) return;
  
  const chartCtx = discoveryCanvas.value.getContext('2d');
  const chartWidth = discoveryCanvas.value.width;
  const chartHeight = discoveryCanvas.value.height;
  const padding = { top: 20, right: 20, bottom: 40, left: 50 };
  const plotWidth = chartWidth - padding.left - padding.right;
  const plotHeight = chartHeight - padding.top - padding.bottom;
  
  chartCtx.clearRect(0, 0, chartWidth, chartHeight);
  
  // Get top 10 largest communities
  const largeCommunities = communitySummaries.value.slice(0, 10);
  if (largeCommunities.length === 0) {
    chartCtx.fillStyle = '#666';
    chartCtx.font = '14px sans-serif';
    chartCtx.textAlign = 'center';
    chartCtx.fillText('No communities to display', chartWidth / 2, chartHeight / 2);
    return;
  }
  
  // Build node -> community lookup
  const nodeToComm = communityAssignments;
  
  // Build community -> set of node ids
  const commNodes = new Map();
  largeCommunities.forEach(c => {
    commNodes.set(c.id, new Set());
  });
  allNodes.forEach(n => {
    if (!n || n.type === "combination" || n.isConnector) return;
    const comm = nodeToComm[n.id];
    if (comm !== undefined && commNodes.has(comm)) {
      commNodes.get(comm).add(n.id);
    }
  });
  
  // Build discovery timeline: at each link index, track discovered nodes per community
  const totalLinks = originalLinks.length;
  const discoveredSets = new Map(); // commId -> Set of discovered node ids
  largeCommunities.forEach(c => {
    discoveredSets.set(c.id, new Set(['Fire', 'Water', 'Earth', 'Air'].filter(b => commNodes.get(c.id).has(b))));
  });
  
  // Sample points (every N links to avoid too many points)
  const sampleInterval = Math.max(1, Math.floor(totalLinks / 100));
  const dataPoints = new Map(); // commId -> array of {x, y}
  largeCommunities.forEach(c => {
    dataPoints.set(c.id, []);
  });
  
  // Add initial point at 0
  largeCommunities.forEach(c => {
    const total = commNodes.get(c.id).size;
    const discovered = discoveredSets.get(c.id).size;
    dataPoints.get(c.id).push({ x: 0, y: total > 0 ? (discovered / total) * 100 : 0 });
  });
  
  // Process links chronologically
  for (let i = 0; i < totalLinks; i++) {
    const link = originalLinks[i];
    const resultId = link.to;
    
    // Check if result belongs to a large community
    const comm = nodeToComm[resultId];
    if (comm !== undefined && discoveredSets.has(comm)) {
      discoveredSets.get(comm).add(resultId);
    }
    
    // Sample at intervals
    if ((i + 1) % sampleInterval === 0 || i === totalLinks - 1) {
      const xPercent = ((i + 1) / totalLinks) * 100;
      largeCommunities.forEach(c => {
        const total = commNodes.get(c.id).size;
        const discovered = discoveredSets.get(c.id).size;
        dataPoints.get(c.id).push({ x: xPercent, y: total > 0 ? (discovered / total) * 100 : 0 });
      });
    }
  }
  
  // Draw axes
  chartCtx.strokeStyle = '#333';
  chartCtx.lineWidth = 1;
  chartCtx.beginPath();
  chartCtx.moveTo(padding.left, padding.top);
  chartCtx.lineTo(padding.left, padding.top + plotHeight);
  chartCtx.lineTo(padding.left + plotWidth, padding.top + plotHeight);
  chartCtx.stroke();
  
  // Y-axis labels (0%, 50%, 100%)
  chartCtx.fillStyle = '#333';
  chartCtx.font = '11px sans-serif';
  chartCtx.textAlign = 'right';
  chartCtx.textBaseline = 'middle';
  [0, 50, 100].forEach(pct => {
    const y = padding.top + plotHeight - (pct / 100) * plotHeight;
    chartCtx.fillText(`${pct}%`, padding.left - 5, y);
    // Grid line
    chartCtx.strokeStyle = '#ddd';
    chartCtx.beginPath();
    chartCtx.moveTo(padding.left, y);
    chartCtx.lineTo(padding.left + plotWidth, y);
    chartCtx.stroke();
  });
  
  // X-axis labels
  chartCtx.textAlign = 'center';
  chartCtx.textBaseline = 'top';
  chartCtx.fillStyle = '#333';
  [0, 25, 50, 75, 100].forEach(pct => {
    const x = padding.left + (pct / 100) * plotWidth;
    chartCtx.fillText(`${pct}%`, x, padding.top + plotHeight + 5);
  });
  chartCtx.fillText('Timeline Progress', padding.left + plotWidth / 2, padding.top + plotHeight + 22);
  
  // Y-axis label
  chartCtx.save();
  chartCtx.translate(12, padding.top + plotHeight / 2);
  chartCtx.rotate(-Math.PI / 2);
  chartCtx.textAlign = 'center';
  chartCtx.fillText('% Discovered', 0, 0);
  chartCtx.restore();
  
  // Draw lines for each community
  largeCommunities.forEach(c => {
    const points = dataPoints.get(c.id);
    if (points.length < 2) return;
    
    chartCtx.strokeStyle = c.color;
    chartCtx.lineWidth = 2;
    chartCtx.beginPath();
    points.forEach((pt, idx) => {
      const x = padding.left + (pt.x / 100) * plotWidth;
      const y = padding.top + plotHeight - (pt.y / 100) * plotHeight;
      if (idx === 0) {
        chartCtx.moveTo(x, y);
      } else {
        chartCtx.lineTo(x, y);
      }
    });
    chartCtx.stroke();
  });
  
  // Draw legend
  const legendX = padding.left + 10;
  let legendY = padding.top + 5;
  chartCtx.font = '10px sans-serif';
  chartCtx.textAlign = 'left';
  chartCtx.textBaseline = 'middle';
  largeCommunities.slice(0, 8).forEach(c => {
    chartCtx.fillStyle = c.color;
    chartCtx.fillRect(legendX, legendY - 4, 12, 8);
    chartCtx.fillStyle = '#333';
    chartCtx.fillText(`${c.id} (${c.count})`, legendX + 16, legendY);
    legendY += 14;
  });
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
  const clampedZoom = Math.max(0.02, Math.min(3, newZoom));
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
  const zoomSpeed = 0.03;
  const direction = event.deltaY > 0 ? -1 : 1;
  setZoomToViewCenter(zoomLevel.value + direction * zoomSpeed);
}

function zoomIn() {
  setZoomToViewCenter(zoomLevel.value + 0.08);
}

function zoomOut() {
  setZoomToViewCenter(zoomLevel.value - 0.08);
}

function resetZoom() {
  zoomLevel.value = 1;
  panX.value = 0;
  panY.value = 0;
}

function buildPathLinkography(activeLinks) {
  // Create nodes in chronological order (duplicates allowed)
  expandedNodes = [];
  expandedLinks = [];
  
  // Track which material IDs we've seen and their chronological indices
  const nodeIndexMap = new Map(); // materialId -> array of node indices
  let chrono = 0; // Chronological counter for positioning
  
  // Start with base materials
  const baseMaterials = ['Fire', 'Water', 'Earth', 'Air'];
  baseMaterials.forEach(matId => {
    const nodeData = allNodes.find(n => n.id === matId);
    if (nodeData) {
      const node = {
        id: nodeData.id,
        label: nodeData.label,
        emoji: nodeData.emoji,
        type: nodeData.type,
        chronoIndex: chrono++,
        isConnector: false
      };
      expandedNodes.push(node);
      if (!nodeIndexMap.has(matId)) nodeIndexMap.set(matId, []);
      nodeIndexMap.get(matId).push(expandedNodes.length - 1);
    }
  });
  
  const baseY = height.value / 2;
  const nodeSpacing = 80;
  const padding = 50;
  
  // Build recipe map incrementally as we process links
  const incrementalRecipeMap = {};
  
  // Process each combination in chronological order
  activeLinks.forEach((link, linkIndex) => {
    const { from1, from2, to } = link;
    const recipeKey = `${from1}_${from2}_${to}`;
    
    // Add this recipe to the incremental map
    if (!incrementalRecipeMap[to]) {
      incrementalRecipeMap[to] = [from1, from2];
    }
    
    // Find most recent instances of from1 and from2
    const from1Indices = nodeIndexMap.get(from1) || [];
    const from2Indices = nodeIndexMap.get(from2) || [];
    
    if (from1Indices.length === 0 || from2Indices.length === 0) {
      console.warn(`Missing prerequisite nodes for ${recipeKey}`);
      return;
    }
    
    // Use the FIRST occurrence of each (original), not the most recent
    const sourceNode1 = expandedNodes[from1Indices[0]];
    const sourceNode2 = expandedNodes[from2Indices[0]];
    
    // Create result node (even if it's a duplicate)
    const resultNodeData = allNodes.find(n => n.id === to);
    if (resultNodeData) {
      const resultNode = {
        id: resultNodeData.id,
        label: resultNodeData.label,
        emoji: resultNodeData.emoji,
        type: resultNodeData.type,
        chronoIndex: chrono++,
        isConnector: false
      };
      expandedNodes.push(resultNode);
      
      if (!nodeIndexMap.has(to)) nodeIndexMap.set(to, []);
      nodeIndexMap.get(to).push(expandedNodes.length - 1);
      
      // PATH LINKOGRAPHY: Create edges to ALL nodes in the recipe dependency path
      // Find all nodes that are needed to create this result, up to this point in time
      const dependencySet = new Set(); // Set of node indices this result depends on
      
      // Trace recipe paths for both from1 and from2, but only use nodes created before this result
      const visited = new Set();
      const stack = [from1, from2];
      const baseSet = new Set(['Fire', 'Water', 'Earth', 'Air']);
      
      while (stack.length) {
        const material = stack.pop();
        if (visited.has(material)) continue;
        visited.add(material);
        
        // Find the FIRST occurrence of this material (it must exist before current)
        const materialIndices = nodeIndexMap.get(material);
        if (materialIndices && materialIndices.length > 0) {
          const firstOccurrenceIdx = materialIndices[0];
          // Only add if it's not the result itself
          if (expandedNodes[firstOccurrenceIdx].id !== to) {
            dependencySet.add(firstOccurrenceIdx);
          }
        }
        
        // Trace back further if this material is made from other materials
        if (!baseSet.has(material)) {
          const comps = incrementalRecipeMap[material];
          if (Array.isArray(comps) && comps.length === 2) {
            const [comp1, comp2] = comps;
            if (!visited.has(comp1)) stack.push(comp1);
            if (!visited.has(comp2)) stack.push(comp2);
          }
        }
      }
      
      // Create connector and edges to each dependency
      dependencySet.forEach((depIdx) => {
        const depNode = expandedNodes[depIdx];
        
        // Create a connector node for this dependency path
        const connectorNode = {
          id: `_path_connector_${resultNode.id}_${depNode.id}_${linkIndex}`,
          label: `${depNode.label} to ${resultNode.label}`,
          emoji: "",
          type: "connector",
          isConnector: true,
          isLabelHighlight: false,
          isRecipe: false
        };
        
        expandedNodes.push(connectorNode);
        
        // Position connector between dep and result
        const xDep = padding + depNode.chronoIndex * nodeSpacing;
        const xRes = padding + resultNode.chronoIndex * nodeSpacing;
        
        connectorNode.x = (xDep + xRes) / 2;
        connectorNode.y = baseY - Math.abs(xRes - xDep) / 2; // Above the line
        
        // Create edges: dep -> connector -> result
        expandedLinks.push({
          source: depNode,
          target: connectorNode,
          recipeKey: `${depNode.id}_${resultNode.id}`,
          isRecipe: false,
          isLabelHighlight: false
        });
        expandedLinks.push({
          source: connectorNode,
          target: resultNode,
          recipeKey: `${depNode.id}_${resultNode.id}`,
          isRecipe: false,
          isLabelHighlight: false
        });
      });
    }
  });
  
  // Update recipe path
  currentRecipeMap = incrementalRecipeMap;
  
  const goalMaterial = activeLinks[activeLinks.length - 1]?.to;
  recipePathEdges = goalMaterial ? findPathToNode(goalMaterial) : new Set();
  
  // Mark recipe links
  expandedLinks.forEach(link => {
    link.isRecipe = recipePathEdges.has(link.recipeKey);
  });
  
  // Add duplicate links: each duplicate node connects to its first occurrence
  const firstOccurrence = new Map(); // materialId -> first node index
  expandedNodes.forEach((node, idx) => {
    if (!node.isConnector && node.id) {
      if (!firstOccurrence.has(node.id)) {
        firstOccurrence.set(node.id, idx);
      }
    }
  });
  
  // For each duplicate (not first occurrence), add a link to the original
  expandedNodes.forEach((node, idx) => {
    if (!node.isConnector && node.id) {
      const firstIdx = firstOccurrence.get(node.id);
      if (firstIdx !== idx) {
        // This is a duplicate - link it to the original
        const originalNode = expandedNodes[firstIdx];
        
        // Create a connector-like node below the line for the duplicate link
        const duplicateConnectorNode = {
          id: `_dup_connector_${node.id}_${idx}`,
          label: `duplicate ${node.label}`,
          emoji: "",
          type: "duplicateConnector",
          isConnector: true,
          isLabelHighlight: false,
          isRecipe: false,
          isDuplicate: true
        };
        
        expandedNodes.push(duplicateConnectorNode);
        
        // Position the connector below the line
        const xNode = padding + node.chronoIndex * nodeSpacing;
        const xOriginal = padding + originalNode.chronoIndex * nodeSpacing;
        
        duplicateConnectorNode.x = (xNode + xOriginal) / 2;
        duplicateConnectorNode.y = baseY + Math.abs(xOriginal - xNode) / 2; // Below the line (positive offset)
        
        // Create two edges: node -> connector -> original
        expandedLinks.push({
          source: node,
          target: duplicateConnectorNode,
          isDuplicate: true,
          isRecipe: false,
          isLabelHighlight: false
        });
        expandedLinks.push({
          source: duplicateConnectorNode,
          target: originalNode,
          isDuplicate: true,
          isRecipe: false,
          isLabelHighlight: false
        });
      }
    }
  });
  
  // Apply linkograph layout (positions all nodes including connectors)
  layoutLinkograph(expandedNodes);
  
  storedNodes.value = expandedNodes;
  
  // Draw immediately (no force simulation for path linkography)
  draw(expandedNodes, expandedLinks);
}

function buildLinkograph(activeLinks) {
  // Create nodes in chronological order (duplicates allowed)
  expandedNodes = [];
  expandedLinks = [];
  
  // Track which material IDs we've seen and their chronological indices
  const nodeIndexMap = new Map(); // materialId -> array of node indices
  let chrono = 0; // Chronological counter for positioning
  
  // Start with base materials
  const baseMaterials = ['Fire', 'Water', 'Earth', 'Air'];
  baseMaterials.forEach(matId => {
    const nodeData = allNodes.find(n => n.id === matId);
    if (nodeData) {
      const node = {
        id: nodeData.id,
        label: nodeData.label,
        emoji: nodeData.emoji,
        type: nodeData.type,
        chronoIndex: chrono++,
        isConnector: false
      };
      expandedNodes.push(node);
      if (!nodeIndexMap.has(matId)) nodeIndexMap.set(matId, []);
      nodeIndexMap.get(matId).push(expandedNodes.length - 1);
    }
  });
  
  const baseY = height.value / 2;
  const nodeSpacing = 80;
  const padding = 50;
  
  // Process each combination in chronological order
  activeLinks.forEach((link, linkIndex) => {
    const { from1, from2, to } = link;
    const recipeKey = `${from1}_${from2}_${to}`;
    
    // Find most recent instances of from1 and from2
    const from1Indices = nodeIndexMap.get(from1) || [];
    const from2Indices = nodeIndexMap.get(from2) || [];
    
    if (from1Indices.length === 0 || from2Indices.length === 0) {
      console.warn(`Missing prerequisite nodes for ${recipeKey}`);
      return;
    }
    
    // Use the FIRST occurrence of each (original), not the most recent
    const sourceNode1 = expandedNodes[from1Indices[0]];
    const sourceNode2 = expandedNodes[from2Indices[0]];
    
    // Create result node (even if it's a duplicate)
    const resultNodeData = allNodes.find(n => n.id === to);
    if (resultNodeData) {
      const resultNode = {
        id: resultNodeData.id,
        label: resultNodeData.label,
        emoji: resultNodeData.emoji,
        type: resultNodeData.type,
        chronoIndex: chrono++,
        isConnector: false
      };
      expandedNodes.push(resultNode);
      
      if (!nodeIndexMap.has(to)) nodeIndexMap.set(to, []);
      nodeIndexMap.get(to).push(expandedNodes.length - 1);
      
      // Create two connector nodes for this combination
      const connector1Node = {
        id: `_connector_${linkIndex}_1`,
        label: `${sourceNode1.label} to ${resultNode.label}`,
        emoji: "",
        type: "connector",
        isConnector: true,
        isLabelHighlight: false,
        isRecipe: false
      };
      
      const connector2Node = {
        id: `_connector_${linkIndex}_2`,
        label: `${sourceNode2.label} to ${resultNode.label}`,
        emoji: "",
        type: "connector",
        isConnector: true,
        isLabelHighlight: false,
        isRecipe: false
      };
      
      expandedNodes.push(connector1Node);
      expandedNodes.push(connector2Node);
      
      // Position connector nodes based on the formula: [(a.x + b.x)/2, line.y - (b.x - a.x)/2]
      const x1 = padding + sourceNode1.chronoIndex * nodeSpacing;
      const x3 = padding + resultNode.chronoIndex * nodeSpacing;
      const x2 = padding + sourceNode2.chronoIndex * nodeSpacing;
      
      connector1Node.x = (x1 + x3) / 2;
      connector1Node.y = baseY - Math.abs(x3 - x1) / 2;
      
      connector2Node.x = (x2 + x3) / 2;
      connector2Node.y = baseY - Math.abs(x3 - x2) / 2;
      
      // Create edges: source1 -> connector1 -> result
      const edge1_1 = {
        source: sourceNode1,
        target: connector1Node,
        recipeKey,
        isRecipe: false,
        isLabelHighlight: false
      };
      const edge1_2 = {
        source: connector1Node,
        target: resultNode,
        recipeKey,
        isRecipe: false,
        isLabelHighlight: false
      };
      
      // Create edges: source2 -> connector2 -> result
      const edge2_1 = {
        source: sourceNode2,
        target: connector2Node,
        recipeKey,
        isRecipe: false,
        isLabelHighlight: false
      };
      const edge2_2 = {
        source: connector2Node,
        target: resultNode,
        recipeKey,
        isRecipe: false,
        isLabelHighlight: false
      };
      
      expandedLinks.push(edge1_1, edge1_2, edge2_1, edge2_2);
    }
  });
  
  // Update recipe path
  currentRecipeMap = {};
  activeLinks.forEach(l => {
    if (!currentRecipeMap[l.to]) {
      currentRecipeMap[l.to] = [l.from1, l.from2];
    }
  });
  
  const goalMaterial = activeLinks[activeLinks.length - 1]?.to;
  recipePathEdges = goalMaterial ? findPathToNode(goalMaterial) : new Set();
  
  // Mark recipe links
  expandedLinks.forEach(link => {
    link.isRecipe = recipePathEdges.has(link.recipeKey);
  });
  
  // Add duplicate links: each duplicate node connects to its first occurrence
  const firstOccurrence = new Map(); // materialId -> first node index
  expandedNodes.forEach((node, idx) => {
    if (!node.isConnector && node.id) {
      if (!firstOccurrence.has(node.id)) {
        firstOccurrence.set(node.id, idx);
      }
    }
  });
  
  // For each duplicate (not first occurrence), add a link to the original
  expandedNodes.forEach((node, idx) => {
    if (!node.isConnector && node.id) {
      const firstIdx = firstOccurrence.get(node.id);
      if (firstIdx !== idx) {
        // This is a duplicate - link it to the original
        const originalNode = expandedNodes[firstIdx];
        
        // Create a connector-like node below the line for the duplicate link
        const duplicateConnectorNode = {
          id: `_dup_connector_${node.id}_${idx}`,
          label: `duplicate ${node.label}`,
          emoji: "",
          type: "duplicateConnector",
          isConnector: true,
          isLabelHighlight: false,
          isRecipe: false,
          isDuplicate: true
        };
        
        expandedNodes.push(duplicateConnectorNode);
        
        // Position the connector below the line
        const baseY = height.value / 2;
        const nodeSpacing = 80;
        const padding = 50;
        const xNode = padding + node.chronoIndex * nodeSpacing;
        const xOriginal = padding + originalNode.chronoIndex * nodeSpacing;
        
        duplicateConnectorNode.x = (xNode + xOriginal) / 2;
        duplicateConnectorNode.y = baseY + Math.abs(xOriginal - xNode) / 2; // Below the line (positive offset)
        
        // Create two edges: node -> connector -> original
        expandedLinks.push({
          source: node,
          target: duplicateConnectorNode,
          isDuplicate: true,
          isRecipe: false,
          isLabelHighlight: false
        });
        expandedLinks.push({
          source: duplicateConnectorNode,
          target: originalNode,
          isDuplicate: true,
          isRecipe: false,
          isLabelHighlight: false
        });
      }
    }
  });
  
  // Apply linkograph layout (positions all nodes including connectors)
  layoutLinkograph(expandedNodes);
  
  storedNodes.value = expandedNodes;
  
  // Draw immediately (no force simulation for linkograph)
  draw(expandedNodes, expandedLinks);
}

function buildCommunityGraph(activeLinks) {
  // Build a graph where nodes are communities and edges are weighted by inter-community links
  expandedNodes = [];
  expandedLinks = [];
  
  // Get unique communities from communityAssignments
  const communitySet = new Set();
  Object.values(communityAssignments).forEach(commId => communitySet.add(commId));
  
  // Get community summaries for colors and sizes
  const commSummaryMap = new Map();
  communitySummaries.value.forEach(cs => commSummaryMap.set(cs.id, cs));
  
  // Create a node for each community that meets the minimum size threshold
  const commNodeMap = new Map(); // commId -> node
  const minSize = minCommunitySize.value || 1;
  communitySet.forEach(commId => {
    const summary = commSummaryMap.get(commId);
    const count = summary?.count ?? 1;
    // Skip communities smaller than the minimum size
    if (count < minSize) return;
    const node = {
      id: `comm_${commId}`,
      commId: commId,
      label: `Community ${commId}`,
      count: count,
      color: summary?.color ?? '#219ebc',
      examples: summary?.labels?.slice(0, 3).join(', ') ?? '',
      x: Math.random() * width.value,
      y: Math.random() * height.value
    };
    expandedNodes.push(node);
    commNodeMap.set(commId, node);
  });
  
  // Count DIRECTED inter-community links
  // Track from->to and to->from separately
  const edgeWeights = new Map(); // \"fromComm_toComm\" -> count (directed: source_target)
  
  activeLinks.forEach(link => {
    const { from1, from2, to } = link;
    
    // Get communities for each material
    const comm1 = communityAssignments[from1];
    const comm2 = communityAssignments[from2];
    const commTo = communityAssignments[to];
    
    // Count DIRECTED edges: from ingredient communities TO result community
    const countDirectedEdge = (fromComm, toComm) => {
      if (fromComm === undefined || toComm === undefined || fromComm === toComm) return;
      // Only count if both communities are in our filtered set
      if (!commNodeMap.has(fromComm) || !commNodeMap.has(toComm)) return;
      const key = `${fromComm}_${toComm}`;
      edgeWeights.set(key, (edgeWeights.get(key) || 0) + 1);
    };
    
    // from1 -> to and from2 -> to (ingredients point to result)
    // But only count each unique source community once per link
    countDirectedEdge(comm1, commTo);
    if (comm2 !== comm1) {
      countDirectedEdge(comm2, commTo);
    }
  });
  
  // Create directed edges between communities
  edgeWeights.forEach((weight, key) => {
    const [fromComm, toComm] = key.split('_');
    const nodeFrom = commNodeMap.get(fromComm);
    const nodeTo = commNodeMap.get(toComm);
    if (nodeFrom && nodeTo) {
      expandedLinks.push({
        source: nodeFrom,
        target: nodeTo,
        weight: weight,
        isDirected: true
      });
    }
  });
  
  storedNodes.value = expandedNodes;
  
  // Set up force simulation for community graph
  if (simulation) {
    simulation.stop();
  }
  
  simulation = forceSimulation(expandedNodes)
    .force("link",
      forceLink(expandedLinks)
        .id(d => d.id)
        .distance(150) // Constant distance
        .strength(0.5) // Constant strength
    )
    .force("charge", forceManyBody().strength(-500))
    .force("center", forceCenter(width.value / 2, height.value / 2));
  
  simulation.on("tick", () => {
    draw(expandedNodes, expandedLinks);
  });
}

function drawCommunityGraph(nodes, links) {
  ctx.clearRect(0, 0, width.value, height.value);
  
  // Apply zoom and pan translation
  ctx.save();
  ctx.translate(panX.value, panY.value);
  ctx.translate(width.value / 2, height.value / 2);
  ctx.scale(zoomLevel.value, zoomLevel.value);
  ctx.translate(-width.value / 2, -height.value / 2);
  
  // Find max count for scaling node sizes, max weight for scaling edge widths
  const maxCount = Math.max(1, ...nodes.map(n => n.count));
  const maxWeight = Math.max(1, ...links.map(l => l.weight));
  
  // Helper to compute node radius
  const getNodeRadius = (node) => (node.count / maxCount) * 55;
  
  // Build a set of reverse edges to detect bidirectional pairs
  // Key: "srcId_tgtId" -> true if reverse edge exists
  const reverseEdgeExists = new Set();
  links.forEach(link => {
    const srcId = link.source.id || link.source;
    const tgtId = link.target.id || link.target;
    // Check if the reverse direction exists
    const reverseKey = `${tgtId}_${srcId}`;
    reverseEdgeExists.add(`${srcId}_${tgtId}`);
  });
  
  // Draw curved directed edges with arrowheads
  links.forEach(link => {
    const normalizedWeight = link.weight / maxWeight;
    const lineWidth = 1 + normalizedWeight * 8; // Range: 1-9px
    
    const srcX = link.source.x;
    const srcY = link.source.y;
    const tgtX = link.target.x;
    const tgtY = link.target.y;
    
    // Check if there's a reverse edge (bidirectional connection)
    const srcId = link.source.id || link.source;
    const tgtId = link.target.id || link.target;
    const reverseKey = `${tgtId}_${srcId}`;
    const hasBidirectional = reverseEdgeExists.has(reverseKey);
    
    // Curve direction: always curve "to the right" relative to the edge direction
    // This means A->B curves one way, B->A curves the opposite way naturally
    let curveDirection = 0;
    if (hasBidirectional) {
      // Always curve to the right of the direction of travel (clockwise)
      curveDirection = 1;
    }
    
    // Calculate curve control point
    const midX = (srcX + tgtX) / 2;
    const midY = (srcY + tgtY) / 2;
    
    // Perpendicular offset for the curve
    const dx = tgtX - srcX;
    const dy = tgtY - srcY;
    const dist = Math.sqrt(dx * dx + dy * dy);
    const curveMagnitude = hasBidirectional ? Math.min(50, dist * 0.3) : 0;
    
    // Perpendicular vector (normalized)
    const perpX = -dy / (dist || 1);
    const perpY = dx / (dist || 1);
    
    // Control point
    const ctrlX = midX + perpX * curveMagnitude * curveDirection;
    const ctrlY = midY + perpY * curveMagnitude * curveDirection;
    
    // Get target node radius to stop arrow before the node
    const targetRadius = getNodeRadius(link.target);
    const sourceRadius = getNodeRadius(link.source);
    
    // Calculate where the curve meets the target node edge
    // For a quadratic bezier, we need to find the point at parameter t where it hits the node
    // Approximate by finding the angle from control point to target
    const angleToTarget = Math.atan2(tgtY - ctrlY, tgtX - ctrlX);
    const arrowEndX = tgtX - Math.cos(angleToTarget) * (targetRadius + 5);
    const arrowEndY = tgtY - Math.sin(angleToTarget) * (targetRadius + 5);
    
    // Start point offset from source node
    const angleFromSource = Math.atan2(ctrlY - srcY, ctrlX - srcX);
    const arrowStartX = srcX + Math.cos(angleFromSource) * (sourceRadius + 2);
    const arrowStartY = srcY + Math.sin(angleFromSource) * (sourceRadius + 2);
    
    // Draw curved line
    ctx.beginPath();
    ctx.strokeStyle = `rgba(100, 100, 100, ${0.4 + normalizedWeight * 0.4})`;
    ctx.lineWidth = lineWidth;
    ctx.moveTo(arrowStartX, arrowStartY);
    ctx.quadraticCurveTo(ctrlX, ctrlY, arrowEndX, arrowEndY);
    ctx.stroke();
    
    // Draw arrowhead
    const arrowSize = 6 + lineWidth;
    const arrowAngle = Math.atan2(arrowEndY - ctrlY, arrowEndX - ctrlX);
    
    ctx.beginPath();
    ctx.fillStyle = `rgba(100, 100, 100, ${0.5 + normalizedWeight * 0.4})`;
    ctx.moveTo(arrowEndX, arrowEndY);
    ctx.lineTo(
      arrowEndX - arrowSize * Math.cos(arrowAngle - Math.PI / 6),
      arrowEndY - arrowSize * Math.sin(arrowAngle - Math.PI / 6)
    );
    ctx.lineTo(
      arrowEndX - arrowSize * Math.cos(arrowAngle + Math.PI / 6),
      arrowEndY - arrowSize * Math.sin(arrowAngle + Math.PI / 6)
    );
    ctx.closePath();
    ctx.fill();
    
    // Draw weight label near the curve midpoint (offset slightly)
    const labelX = ctrlX;
    const labelY = ctrlY;
    ctx.fillStyle = '#333';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(link.weight.toString(), labelX, labelY);
  });
  
  // Draw nodes with size proportional to community size
  nodes.forEach(node => {
    const radius = getNodeRadius(node);
    
    // Draw node circle
    ctx.beginPath();
    ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
    ctx.fillStyle = node.color;
    ctx.fill();
    ctx.strokeStyle = '#333';
    ctx.lineWidth = 2;
    ctx.stroke();
    
    // Draw label
    ctx.fillStyle = '#fff';
    ctx.font = 'bold 12px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(`${node.count}`, node.x, node.y - 6);
    
    // Draw examples below count
    ctx.font = '9px sans-serif';
    ctx.fillStyle = '#fff';
    const exampleText = node.examples.length > 15 ? node.examples.substring(0, 15) + '...' : node.examples;
    ctx.fillText(exampleText, node.x, node.y + 8);
  });
  
  ctx.restore();
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
  
  // Handle Linkograph mode separately
  if (renderMode.value === 'Linkograph') {
    buildLinkograph(activeLinks);
    return;
  }
  
  // Handle Community graph mode separately
  if (renderMode.value === 'Community') {
    buildCommunityGraph(activeLinks);
    return;
  }
  
  // Handle Path Linkography mode separately
  if (renderMode.value === 'Path Linkography') {
    buildPathLinkography(activeLinks);
    return;
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
        expandedLinks.push({ source: sourceNode1, target: targetNode, distance: linkData.distanceTo + linkData.distanceFrom1, isRecipe: false, isLabelHighlight: false, recipeKey, label: from2 });
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
    const { nodes, links } = await res.json();
    console.log("Loaded full graph data:", { nodes: nodes.length, links: links.length });

    // Store full data for timeline filtering
    originalLinks = links;
    allNodes = nodes;
    
    // Compute communities and assign colors based on selected algorithm
    await recomputeCommunities();
    
    // Compute user assignments (for global graph coloring by user)
    if (!isLoggedIn.value) {
      userAssignments = computeUserAssignments(allNodes, originalLinks);
      userColors = assignUserColors(userAssignments);
      userSummaries.value = buildUserSummaries(userAssignments, userColors, allNodes);
    }
    
    // Draw community discovery chart
    drawCommunityDiscoveryChart();
    
    // Initial recipe path will be computed locally via findPathToNode during rebuild
    recipePathEdges = new Set();
    
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
  if (expandedNodes.length > 0) {
    draw(expandedNodes, expandedLinks);
  }
});

// Watch pan and redraw
watch([panX, panY], () => {
  if (expandedNodes.length > 0) {
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

// Redraw when colorMode changes
watch(colorMode, () => {
  console.log(`Color mode changed to ${colorMode.value}`);
  // Clear selections when switching modes
  selectedCommunities.value = new Set();
  selectedUsers.value = new Set();
  if (expandedNodes.length > 0 && expandedLinks.length > 0) {
    draw(expandedNodes, expandedLinks);
  }
});

// Recompute communities when algorithm changes
watch(communityAlgorithm, async () => {
  console.log(`Community algorithm changed to ${communityAlgorithm.value}`);
  if (allNodes.length > 0 && originalLinks.length > 0) {
    await recomputeCommunities();
  }
});

// Rebuild community graph when minimum size filter changes
watch(minCommunitySize, () => {
  if (renderMode.value === 'Community' && originalLinks.length > 0) {
    console.log(`Min community size changed to ${minCommunitySize.value}`);
    rebuildGraphForTimeline(true);
  }
});

// Redraw discovery chart when communities change
watch(communitySummaries, () => {
  drawCommunityDiscoveryChart();
}, { deep: true });

onBeforeUnmount(() => {
  simulation?.stop();
  cancelAnimationFrame(animationFrame);
});
</script>

<template>
  <div class="flex flex-col gap-4 items-start">
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
            <option value="Linkograph">Linkograph</option>
            <option value="Path Linkography">Path Linkography</option>
            <option value="Community">Community Graph</option>
          </select>
        </div>
        <div v-if="renderMode === 'Community'" class="flex items-center gap-3 mb-3">
          <label class="text-sm font-medium whitespace-nowrap">Min Community Size:</label>
          <input 
            type="number" 
            v-model.number="minCommunitySize" 
            min="1" 
            step="1"
            class="w-20 text-sm border border-gray-300 rounded px-2 py-1"
          />
          <span class="text-xs text-gray-500">Only show communities with at least this many nodes</span>
        </div>
        <div class="flex items-center gap-3 mb-3">
          <button
            @click="clearHighlights"
            class="bg-gray-700 text-white px-3 py-1 rounded text-xs hover:bg-gray-800"
          >
            Clear Highlights
          </button>
          <span class="text-xs text-gray-500">Reset recipe path and label highlights</span>
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

    <!-- Color Mode Toggle (only shown for global graph) -->
    <div v-if="!isLoggedIn" class="w-full max-w-4xl border border-gray-200 rounded-md p-3 bg-white shadow-sm">
      <h3 class="text-sm font-semibold mb-2">Color By</h3>
      <div class="flex items-center gap-4">
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="radio" v-model="colorMode" value="communities" class="w-4 h-4" />
          <span class="text-sm">Communities</span>
        </label>
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="radio" v-model="colorMode" value="users" class="w-4 h-4" />
          <span class="text-sm">Users</span>
        </label>
      </div>
    </div>

    <!-- Community Algorithm Selection -->
    <div class="w-full max-w-4xl border border-gray-200 rounded-md p-3 bg-white shadow-sm">
      <div class="flex items-center gap-3">
        <label class="text-sm font-medium whitespace-nowrap">Community Algorithm:</label>
        <select v-model="communityAlgorithm" class="text-sm border border-gray-300 rounded px-2 py-1">
          <option value="undirected">Louvain (Undirected)</option>
          <option value="directed">Louvain (Directed)</option>
          <option value="in-degree">Louvain (In-Degree Only)</option>
          <option value="out-degree">Louvain (Out-Degree Only)</option>
          <option value="infomap">Infomap (Random Walk)</option>
        </select>
        <span class="text-xs text-gray-500">
          {{ communityAlgorithm === 'directed' ? 'Considers edge direction (A→B ≠ B→A)' : 
             communityAlgorithm === 'in-degree' ? 'Groups by shared predecessors (what points to them)' :
             communityAlgorithm === 'out-degree' ? 'Groups by shared successors (what they produce)' :
             communityAlgorithm === 'infomap' ? 'Minimizes random walk description length' :
             'Treats edges as bidirectional' }}
        </span>
      </div>
    </div>

    <!-- Communities List (shown when colorMode is communities or user is logged in) -->
    <div v-if="colorMode === 'communities' || isLoggedIn" class="w-full max-w-4xl border border-gray-200 rounded-md p-3 bg-white shadow-sm">
      <div class="flex items-center justify-between mb-2 flex-wrap gap-2">
        <h3 class="text-sm font-semibold">Communities</h3>
        <span class="text-xs text-blue-600" title="Freeman Degree Centralization for the entire graph">Global Centr: {{ globalCentralization.toFixed(3) }}</span>
        <span class="text-xs text-purple-600" title="Average semantic spread across all communities (avg cosine distance to centroid)">Avg Spread: {{ avgCommunitySpread.toFixed(3) }}</span>
        <span class="text-xs text-teal-600" title="Average cosine distance between community centroids (how separated communities are in semantic space)">Inter-Comm Dist: {{ globalInterCommunityDistance.toFixed(3) }}</span>
      </div>
      <div class="flex flex-col gap-2">
        <div v-if="communitySummaries.length === 0" class="text-xs text-gray-500">Communities will appear after data loads.</div>
        <div
          v-for="comm in communitySummaries"
          :key="comm.id"
          class="flex items-center gap-3 text-sm flex-wrap"
        >
          <input
            type="checkbox"
            class="w-4 h-4"
            :checked="selectedCommunities.has(comm.id)"
            @change="onCommunityToggle(comm.id, $event.target.checked)"
          />
          <span class="inline-block w-4 h-4 rounded-sm border" :style="{ backgroundColor: comm.color }"></span>
          <span class="font-medium">Community {{ comm.id }}</span>
          <span class="text-gray-500 text-xs">({{ comm.count }} nodes)</span>
          <span class="text-blue-600 text-xs" :title="'Freeman Degree Centralization: measures how centralized the community structure is (0=decentralized, 1=star-shaped)'">Centr: {{ comm.centralization.toFixed(3) }}</span>
          <span class="text-purple-600 text-xs" :title="'Average Euclidean distance from each node to the community centroid (semantic spread)'">Spread: {{ (comm.avgDistToCentroid ?? 0).toFixed(3) }}</span>
          <span class="text-orange-600 text-xs" :title="'Standard deviation of distances to centroid (uniformity of spread)'">±{{ (comm.stdDistToCentroid ?? 0).toFixed(3) }}</span>
          <span class="text-green-600 text-xs" :title="'Maximum distance to centroid (community radius)'">Radius: {{ (comm.maxDistToCentroid ?? 0).toFixed(3) }}</span>
          <span v-if="comm.parentCommunities && comm.parentCommunities.length > 0" class="text-amber-600 text-xs" :title="'Parent community: the community of the ingredients that created the first resource in this community'">
            Parent: {{ comm.parentCommunities.join(', ') }}
          </span>
          <span v-if="comm.topSources && comm.topSources.length > 0" class="text-cyan-600 text-xs" :title="'Top communities that feed into this one (in-degree sources)'">
            ← From: {{ comm.topSources.map(s => `${s.id}(${s.count})`).join(', ') }}
          </span>
          <span v-if="comm.topSinks && comm.topSinks.length > 0" class="text-pink-600 text-xs" :title="'Top communities this one feeds into (out-degree sinks)'">
            → To: {{ comm.topSinks.map(s => `${s.id}(${s.count})`).join(', ') }}
          </span>
          <span class="text-gray-700 text-xs">Examples: {{ comm.labels.join(', ') }}</span>
        </div>
      </div>
    </div>

    <!-- Users List (shown when colorMode is users and no user logged in) -->
    <div v-if="colorMode === 'users' && !isLoggedIn" class="w-full max-w-4xl border border-gray-200 rounded-md p-3 bg-white shadow-sm">
      <h3 class="text-sm font-semibold mb-2">Users</h3>
      <div class="flex flex-col gap-2">
        <div v-if="userSummaries.length === 0" class="text-xs text-gray-500">Users will appear after data loads.</div>
        <div
          v-for="user in userSummaries"
          :key="user.id"
          class="flex items-center gap-3 text-sm"
        >
          <input
            type="checkbox"
            class="w-4 h-4"
            :checked="selectedUsers.has(user.id)"
            @change="onUserToggle(user.id, $event.target.checked)"
          />
          <span class="inline-block w-4 h-4 rounded-sm border" :style="{ backgroundColor: user.color }"></span>
          <span class="font-medium">{{ user.id }}</span>
          <span class="text-gray-500 text-xs">({{ user.count }} nodes)</span>
          <span class="text-gray-700 text-xs">Examples: {{ user.labels.join(', ') }}</span>
        </div>
      </div>
    </div>

    <div class="w-full max-w-4xl border border-gray-200 rounded-md p-3 bg-white shadow-sm">
      <h3 class="text-sm font-semibold mb-2">Community Discovery Over Time</h3>
      <canvas
        ref="discoveryCanvas"
        :width="600"
        :height="300"
        class="w-full"
      />
    </div>
  </div>
</template>
