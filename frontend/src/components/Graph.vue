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
import { storeToRefs } from "pinia";

const boxStore = useBoxesStore();
const resourceStore = useResourcesStore();
const { combinationCount } = storeToRefs(resourceStore);
const canvas = ref(null);
let simulation;
let ctx;
let animationFrame;

const width = ref(800);
const height = ref(600);
const storedNodes = ref([]);
const hoverNode = ref(null);
const hoverPos = ref({ x: 0, y: 0 });
const draggingNode = ref(null);
const dragStartPos = ref({ x: 0, y: 0 });

function draw(nodes, links) {
  ctx.clearRect(0, 0, width.value, height.value);

  // links
  ctx.strokeStyle = "#888";
  ctx.beginPath();
  links.forEach(l => {
    ctx.moveTo(l.source.x, l.source.y);
    ctx.lineTo(l.target.x, l.target.y);
    
  });
  ctx.stroke();

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
}

function onMouseMove(event) {
  if (!storedNodes.value.length) return;
  const rect = canvas.value.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  hoverPos.value = { x, y };

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

function handleNodeClick(node) {
  // Only add non-combination nodes to canvas
  if (node.type === "combination") return;

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
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  dragStartPos.value = { x, y };

  const hit = storedNodes.value.find(n => {
    const dx = n.x - x;
    const dy = n.y - y;
    return dx * dx + dy * dy <= 10 * 10;
  });

  if (hit) {
    draggingNode.value = hit;
    hit.fx = x;
    hit.fy = y;
    simulation?.alpha(0.7).restart();
  }
}

function onMouseUp(event) {
  if (draggingNode.value) {
    // Calculate distance moved
    const rect = canvas.value.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const dx = x - dragStartPos.value.x;
    const dy = y - dragStartPos.value.y;
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

async function loadGraphData() {
  console.log("Loading graph data...");
  try {
    const res = await fetch("http://localhost:3000/api/graph");
    if (!res.ok) {
      console.error("Failed to fetch graph data:", res.status);
      return;
    }
    const { nodes, links } = await res.json();
    console.log("Loaded graph data:", { nodes, links });

    // cache nodes for hover detection
    storedNodes.value = nodes;

    // Turn each combination link into linear links by adding a combination node
    const expandedNodes = [...nodes];
    const expandedLinks = [];
    let combinationNodeId = 0;

    links.forEach(l => {
      // Resolve source and target nodes
      const sourceNode1 = expandedNodes.find(n => n.id === l.from1);
      const sourceNode2 = expandedNodes.find(n => n.id === l.from2);
      const targetNode = expandedNodes.find(n => n.id === l.to);

      if (!sourceNode1 || !sourceNode2 || !targetNode) {
        console.warn("Could not resolve nodes for link:", l, { sourceNode1, sourceNode2, targetNode });
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

      // Create links: source1 → combination, source2 → combination, combination → target
      expandedLinks.push({ source: sourceNode1, target: combNode });
      expandedLinks.push({ source: sourceNode2, target: combNode });
      expandedLinks.push({ source: combNode, target: targetNode });
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
          .distance(l =>
            l.source.type === "combination" ||
            l.target.type === "combination"
              ? 40
              : 80
          )
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
  await loadGraphData();
});

// Watch for combination events and reload graph
watch(combinationCount, () => {
  console.log("Combination detected, reloading graph...");
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
  </div>
</template>
