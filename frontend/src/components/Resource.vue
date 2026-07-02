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
import { ref, onBeforeUnmount } from 'vue'
import ItemCard from "@/components/ItemCard.vue";
const props = defineProps<{
  emoji: string
  title: string
  isNewDiscovery?: boolean
}>()

const emit = defineEmits<{
  click: [title: string, emoji: string]
}>()

// On touch devices a drag would start on the first touchmove, which is the
// same gesture as swipe-scrolling the resources row. Gate touch drags behind
// a short hold: swipe right away = scroll, hold then move = drag.
const isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0
const holdReady = ref(false)
let holdTimer: ReturnType<typeof setTimeout> | null = null

const onTouchStart = () => {
  holdTimer = setTimeout(() => {
    holdReady.value = true
  }, 250)
}

const cancelHold = () => {
  if (holdTimer) {
    clearTimeout(holdTimer)
    holdTimer = null
  }
}

const onTouchMove = () => {
  // moved before the hold completed: treat as a scroll, not a drag
  if (!holdReady.value) cancelHold()
}

const onTouchEnd = () => {
  cancelHold()
  holdReady.value = false
}

onBeforeUnmount(cancelHold)

const [collect, drag] = useDrag(() => ({
  type: ItemTypes.BOX,
  item: { title: props.title, emoji: props.emoji },
  canDrag: () => !isTouchDevice || holdReady.value,
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
      class="inline-block cursor-pointer rounded-lg select-none touch-manipulation"
      :class="{'ring-2 ring-orange-300': isNewDiscovery, 'scale-110 ring-2 ring-lime-400': holdReady}"
      :ref="drag"
      role="Box"
      data-testid="box"
      @click="handleClick"
      @touchstart="onTouchStart"
      @touchmove="onTouchMove"
      @touchend="onTouchEnd"
      @touchcancel="onTouchEnd"
  >
    <ItemCard id="resource-item" size="small" :title="title" :emoji="emoji"></ItemCard>
  </div>
</template>

<style scoped>

</style>