<!--
  AvailableResources.vue
  
  Resources panel that displays all discovered elements.
  Includes search filter and click-to-place functionality.
  Each resource is a draggable item that can be dropped on canvas.
-->

<script setup lang="ts">
import Resource from "@/components/Resource.vue";
import {useResourcesStore} from "@/stores/useResourcesStore";
import {useBoxesStore} from "@/stores/useBoxesStore";
import {storeToRefs} from "pinia";
import {computed, ref} from "vue";

const resourceStore = useResourcesStore()
const boxStore = useBoxesStore()
const {resources} = storeToRefs(resourceStore)
const {boxes} = storeToRefs(boxStore)

const searchTerm = ref('')

const filteredResources = computed(() => {
  return resources.value.filter((resource) => {
    return resource.title.toLowerCase().includes(searchTerm.value.toLowerCase())
  })
})

const handleResourceClick = (title: string, emoji: string) => {
  // Center of the visible canvas, converted to canvas-space (undo the pan)
  const canvas = document.getElementById('game-canvas')
  const containerWidth = canvas?.clientWidth ?? window.innerWidth * 0.75
  const containerHeight = canvas?.clientHeight ?? window.innerHeight * 0.9
  const pan = boxStore.pan

  const centerX = containerWidth / 2 - 40 - pan.x // -40 for half card width
  const centerY = containerHeight / 2 - 15 - pan.y // -15 for half card height

  // Add random offset (±100px), kept inside the visible canvas
  const maxOffsetX = Math.min(100, containerWidth / 2 - 60)
  const maxOffsetY = Math.min(100, containerHeight / 2 - 40)
  const randomOffsetX = (Math.random() - 0.5) * 2 * maxOffsetX
  const randomOffsetY = (Math.random() - 0.5) * 2 * maxOffsetY

  const finalX = Math.round(centerX + randomOffsetX)
  const finalY = Math.round(centerY + randomOffsetY)

  // Add to canvas
  const key = Math.random().toString(36).substring(7)
  boxes.value[key] = {top: finalY, left: finalX, title, emoji}
}
</script>

<template>
  <div class="pt-3">
    <input v-model="searchTerm" type="text" class="w-full border border-gray-300 rounded-lg px-3 py-2" placeholder="Search resources...">
    <!-- Mobile: single row with horizontal scroll. Desktop: wrapping grid. -->
    <div class="flex gap-3 pt-3 flex-nowrap overflow-x-auto pb-2 md:flex-wrap md:overflow-x-visible md:pb-0">
      <Resource
        v-for="resource in filteredResources"
        :key="resource.title"
        class="shrink-0"
        :title="resource.title"
        :emoji="resource.emoji"
        :isNewDiscovery="resource.isNewDiscovery"
        @click="handleResourceClick(resource.title, resource.emoji)"
      ></Resource>
    </div>
  </div>
</template>

<style scoped>

</style>