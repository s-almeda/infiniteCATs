<!--
  DragLayer.vue

  Custom drag preview for the touch backend (which renders no native
  preview). Follows the pointer and mimics ItemCard styling. Rendered as
  plain markup rather than ItemCard so it doesn't register a drop target.
-->

<script setup lang="ts">
import {useDragLayer} from 'vue3-dnd'
import {toRefs} from '@vueuse/core'
import {computed} from 'vue'
import {useBoxesStore} from '@/stores/useBoxesStore'
import type {DragItem} from './interfaces'

const store = useBoxesStore()

const collect = useDragLayer(monitor => ({
  item: monitor.getItem() as DragItem | null,
  isDragging: monitor.isDragging(),
  offset: monitor.getClientOffset(),
}))
const {item, isDragging, offset} = toRefs(collect)

const preview = computed(() => {
  const it = item.value
  if (!it) return null
  // Canvas boxes carry an id; resources carry title/emoji directly
  if (it.id && store.boxes[it.id]) {
    const box = store.boxes[it.id]
    return {title: box.title, emoji: box.emoji, large: true}
  }
  if (it.title) {
    return {title: it.title, emoji: it.emoji, large: false}
  }
  return null
})
</script>

<template>
  <div
      v-if="isDragging && offset && preview"
      class="fixed z-50 pointer-events-none"
      :style="{left: `${offset.x}px`, top: `${offset.y}px`, transform: 'translate(-50%, -50%)'}"
  >
    <div
        :class="[
          preview.large ? 'text-2xl space-x-2.5 py-2.5 px-4' : 'space-x-1.5 px-3 py-1',
          'border-gray-200 bg-white shadow-lg inline-flex items-center whitespace-nowrap font-medium border rounded-lg opacity-90'
        ]"
    >
      <span>{{ preview.emoji }}</span>
      <span>{{ preview.title }}</span>
    </div>
  </div>
</template>
