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
  // Get container dimensions for centering
  const containerWidth = window.innerWidth * 0.75 // 75% of viewport (from Container.vue layout)
  const containerHeight = window.innerHeight * 0.9 // 90% of viewport height
  
  // Calculate center position
  const centerX = containerWidth / 2 - 40 // -40 for half card width
  const centerY = containerHeight / 2 - 15 // -15 for half card height
  
  // Add random offset (±100px)
  const randomOffsetX = (Math.random() - 0.5) * 200
  const randomOffsetY = (Math.random() - 0.5) * 200
  
  const finalX = Math.round(centerX + randomOffsetX)
  const finalY = Math.round(centerY + randomOffsetY)
  
  // Add to canvas
  const key = Math.random().toString(36).substring(7)
  boxes.value[key] = {top: finalY, left: finalX, title, emoji}
}
</script>

<template>
  <div class="flex gap-3 flex-wrap pt-3">
    <input v-model="searchTerm" type="text" class="w-full border border-gray-300 rounded-lg px-3 py-2" placeholder="Search resources...">
    <Resource 
      v-for="resource in filteredResources" 
      :key="resource.title" 
      :title="resource.title"  
      :emoji="resource.emoji"
      @click="handleResourceClick(resource.title, resource.emoji)"
    ></Resource>
  </div>
</template>

<style scoped>

</style>