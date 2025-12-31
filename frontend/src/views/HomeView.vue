<script setup lang="ts">
import Example from "@/components/Example.vue";
import ItemCard from "@/components/ItemCard.vue";
import Resource from "@/components/Resource.vue";
import AvaliableResources from "@/components/AvailableResources.vue";
import Container from "@/components/Container.vue";
import Graph from "@/components/Graph.vue";
import { computed, onMounted } from "vue";
import { useUserStore } from "@/stores/useUserStore";
import { useResourcesStore } from "@/stores/useResourcesStore";

const urlParams = new URLSearchParams(window.location.search);
const showGraph = computed(() => urlParams.get('graph') === 'true');

const userStore = useUserStore();
const resourcesStore = useResourcesStore();

onMounted(async () => {
    if (userStore.isLoggedIn && userStore.username) {
        await resourcesStore.loadUserMaterials(userStore.username);
    }
});
</script>

<template>
  <Example></Example>
  <Graph v-if="showGraph"></Graph>
</template>
