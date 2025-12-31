<script setup lang="ts">
import Example from "@/components/Example.vue";
import ItemCard from "@/components/ItemCard.vue";
import Resource from "@/components/Resource.vue";
import AvaliableResources from "@/components/AvailableResources.vue";
import Container from "@/components/Container.vue";
import Graph from "@/components/Graph.vue";
import { computed } from "vue";

const urlParams = new URLSearchParams(window.location.search);
const showGraph = computed(() => urlParams.get('graph') === 'true');
</script>

<template>
  <Example></Example>
  <Graph v-if="showGraph"></Graph>
</template>
