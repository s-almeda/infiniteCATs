<script setup>
import { onMounted, ref } from "vue";
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

const loading = ref(true);
const error = ref(null);
const communities = ref([]);

async function loadUserCategories() {
  console.log("Loading user categories...");
  loading.value = true;
  error.value = null;

  try {
    // Fetch graph data
    const { nodes, links } = await fetchGraphData(username.value, isLoggedIn.value);
    console.log("Fetched graph data:", { nodes: nodes.length, links: links.length });
    console.log("All links:", links);

    // Add craft times to nodes
    const nodesWithCraftTimes = addCraftTimesToNodes(nodes, links);
    console.log("Nodes with craft times:", nodesWithCraftTimes);

    // Compute communities
    const assignments = computeCommunities(nodesWithCraftTimes, links, COMMUNITY_PARAMS);
    console.log("Community assignments:", assignments);

    // Assign colors to communities
    const colors = assignCommunityColors(assignments);
    console.log("Community colors:", colors);

    // Build summaries
    const summaries = buildCommunitySummaries(assignments, colors, nodesWithCraftTimes);
    console.log("Community summaries:", summaries);

    communities.value = summaries;
  } catch (err) {
    console.error("Error loading categories:", err);
    error.value = err.message;
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  loadUserCategories();
});
</script>

<template>
  <div class="user-categories">
    <h2>User Categories</h2>
    <div v-if="loading">Loading categories...</div>
    <div v-else-if="error" class="error">Error: {{ error }}</div>
    <div v-else>
      <p>Found {{ communities.length }} communities. Check console for details.</p>
    </div>
  </div>
</template>

<style scoped>
.user-categories {
  padding: 1rem;
  border: 1px solid #ccc;
  border-radius: 4px;
  margin: 1rem 0;
}

.error {
  color: red;
}
</style>
