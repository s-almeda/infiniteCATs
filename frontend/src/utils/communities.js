// Community detection and color assignment utilities

export const COMMUNITY_PARAMS = {
  gamma: 0.5,      // < 1 => coarser communities; > 1 => finer communities
  maxPasses: 50,   // number of local-move sweeps
  minGain: -1e-6   // allow tiny negative to avoid getting stuck
};

export function computeCommunities(nodes, links, params = COMMUNITY_PARAMS) {
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

export function assignCommunityColors(assignments) {
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

export function buildCommunitySummaries(assignments, colors, nodes) {
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

  return [...group.entries()].map(([commId, { color, nodes }]) => {
    const labels = nodes.slice(0, 5).map(n => n.label || n.id);
    return {
      id: commId,
      color,
      count: nodes.length,
      labels
    };
  }).sort((a, b) => b.count - a.count);
}

// Fetch graph data from the API
export async function fetchGraphData(username = null, isLoggedIn = false) {
  const apiUrl = import.meta.env.VITE_FLASK_API_URL || 'http://localhost:3000';
  let query = isLoggedIn && username
    ? `?username=${encodeURIComponent(username)}`
    : '';

  const res = await fetch(`${apiUrl}/api/graph${query}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch graph data: ${res.status}`);
  }
  return res.json();
}

// Fetch user-specific graph data with craft times pre-computed by the backend
export async function fetchUserGraphData(username) {
  const apiUrl = import.meta.env.VITE_FLASK_API_URL || 'http://localhost:3000';
  
  if (!username) {
    throw new Error('Username is required for user graph data');
  }

  const res = await fetch(`${apiUrl}/api/user-graph?username=${encodeURIComponent(username)}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch user graph data: ${res.status}`);
  }
  return res.json();
}

// Fetch full pairwise distance matrix for a user's materials
export async function fetchUserDistanceMatrix(username) {
  const apiUrl = import.meta.env.VITE_FLASK_API_URL || 'http://localhost:3000';
  
  if (!username) {
    throw new Error('Username is required for distance matrix');
  }

  console.log(`[DistanceMatrix] Fetching distance matrix for user: ${username}`);
  const res = await fetch(`${apiUrl}/api/user-distance-matrix?username=${encodeURIComponent(username)}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch distance matrix: ${res.status}`);
  }
  const data = await res.json();
  console.log(`[DistanceMatrix] Received ${Object.keys(data.distances).length} distances for ${data.materials.length} materials`);
  return data;
}

// Fetch global graph data (all combinations from all users)
export async function fetchGlobalGraphData() {
  const apiUrl = import.meta.env.VITE_FLASK_API_URL || 'http://localhost:3000';

  console.log(`[GlobalGraph] Fetching global graph data...`);
  const res = await fetch(`${apiUrl}/api/graph`);
  if (!res.ok) {
    throw new Error(`Failed to fetch global graph data: ${res.status}`);
  }
  const data = await res.json();
  console.log(`[GlobalGraph] Received ${data.nodes.length} nodes, ${data.links.length} links`);
  return data;
}

// Fetch radial layout with pre-computed positions from backend
export async function fetchRadialLayout(username = null, width = 1000, height = 1000) {
  const apiUrl = import.meta.env.VITE_FLASK_API_URL || 'http://localhost:3000';
  
  let url = `${apiUrl}/api/radial-layout?width=${width}&height=${height}`;
  if (username) {
    url += `&username=${encodeURIComponent(username)}`;
  }
  
  console.log(`[RadialLayout] Fetching layout${username ? ` for user: ${username}` : ' (global)'}...`);
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to fetch radial layout: ${res.status}`);
  }
  const data = await res.json();
  console.log(`[RadialLayout] Received ${data.nodes.length} nodes with positions`);
  return data;
}

// Fetch full pairwise distance matrix for ALL materials
export async function fetchGlobalDistanceMatrix() {
  const apiUrl = import.meta.env.VITE_FLASK_API_URL || 'http://localhost:3000';

  console.log(`[GlobalDistanceMatrix] Fetching global distance matrix...`);
  try {
    const res = await fetch(`${apiUrl}/api/global-distance-matrix`);
    if (!res.ok) {
      throw new Error(`Failed to fetch global distance matrix: ${res.status}`);
    }
    const text = await res.text();
    if (!text) {
      throw new Error('Empty response from global distance matrix endpoint');
    }
    const data = JSON.parse(text);
    console.log(`[GlobalDistanceMatrix] Received ${Object.keys(data.distances).length} distances for ${data.materials.length} materials`);
    return data;
  } catch (err) {
    console.error('[GlobalDistanceMatrix] Error:', err);
    throw err;
  }
}

// Compute when each material was first crafted per user
// Returns a map of nodeId -> { username -> craftIndex }
export function computeCraftTimes(nodes, links) {
  const baseMaterials = new Set(['Fire', 'Water', 'Earth', 'Air']);
  const craftTimes = {}; // nodeId -> { username -> index }

  // Base materials have no craft time (they exist from the start)
  nodes.forEach(node => {
    craftTimes[node.id] = {};
    if (baseMaterials.has(node.id)) {
      craftTimes[node.id] = null; // null means base material
    }
  });

  // Track per-user indices
  const userIndices = {}; // username -> current index

  // Process links in chronological order
  links.forEach((link) => {
    const resultId = link.to;
    const username = link.username;

    if (!username) return;

    // Initialize user index if needed
    if (userIndices[username] === undefined) {
      userIndices[username] = 0;
    }

    // Record craft time for this user if not already recorded
    if (craftTimes[resultId] !== null && craftTimes[resultId] !== undefined) {
      if (craftTimes[resultId][username] === undefined) {
        craftTimes[resultId][username] = userIndices[username];
      }
    }

    userIndices[username]++;
  });

  return craftTimes;
}

// Add craft time to each node object
export function addCraftTimesToNodes(nodes, links) {
  const craftTimes = computeCraftTimes(nodes, links);

  return nodes.map(node => ({
    ...node,
    craftTimes: craftTimes[node.id] ?? null, // null for base materials, object of { username: index } otherwise
    isBaseMaterial: ['Fire', 'Water', 'Earth', 'Air'].includes(node.id)
  }));
}
