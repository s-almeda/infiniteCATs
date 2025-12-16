<!--
  Resource.vue
  
  Individual resource item in the Resources panel.
  Handles both drag-and-drop to canvas and click-to-place functionality.
  Clicking places the resource at canvas center with random offset.
-->

<script setup lang="ts">
import { useDrag } from 'vue3-dnd'
import { ItemTypes } from './ItemTypes'
import { toRefs } from '@vueuse/core'
import ItemCard from "@/components/ItemCard.vue";
const props = defineProps<{
  emoji: string
  title: string
}>()

const emit = defineEmits<{
  click: [title: string, emoji: string]
}>()

const [collect, drag] = useDrag(() => ({
  type: ItemTypes.BOX,
  item: { title: props.title, emoji: props.emoji },
  collect: monitor => ({
    isDragging: monitor.isDragging(),
  }),
}))
const { isDragging } = toRefs(collect)

const handleClick = () => {
  emit('click', props.title, props.emoji)
}
</script>

<template>
  <div
      class="inline-block cursor-pointer"
      :ref="drag"
      role="Box"
      data-testid="box"
      @click="handleClick"
  >
    <ItemCard id="resource-item" size="small" :title="title" :emoji="emoji"></ItemCard>
  </div>
</template>

<style scoped>

</style>