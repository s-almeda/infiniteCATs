<!--
  Container.vue

  Main game container holding the canvas and resources panel.
  Manages the drag-and-drop zone and canvas state (boxes/items).
  Desktop: canvas left (75%), resources panel right (25%).
  Mobile: canvas on top, resources panel below with horizontal scroll.
  Dragging the canvas background pans the view; boxes keep canvas-space
  coordinates and the whole layer is translated by the pan offset.
-->

<script lang="ts" setup>
import {useDrop, type XYCoord} from 'vue3-dnd'
import {ItemTypes} from './ItemTypes'
import Box from './Box.vue'
import type {DragItem} from './interfaces'
import {ref} from 'vue'
import ItemCard from "@/components/ItemCard.vue";
import AvailableResources from "@/components/AvailableResources.vue";
import {useBoxesStore} from "@/stores/useBoxesStore";

const store = useBoxesStore()
const { boxes, pan } = store
const moveBox = (id: string | null, left: number, top: number, title?: string, emoji?: string) => {
  if (id) {
    Object.assign(boxes[id], {left, top})
  } else {
    const key = Math.random().toString(36).substring(7);
    boxes[key] = {top, left, title: title || '', emoji: emoji || ''}
  }
}

const canvasElement = ref<HTMLElement | null>(null)

const [, drop] = useDrop(() => ({
  accept: ItemTypes.BOX,
  drop(item: DragItem, monitor) {
    if (item.id && item.left !== null && item.top !== null) {
      const delta = monitor.getDifferenceFromInitialOffset() as XYCoord
      if(delta && delta.x && delta.y){
        const left = Math.round((item.left) + delta.x)
        const top = Math.round((item.top) + delta.y )
        moveBox(item.id, left, top)
      }
    } else {
      const delta = monitor.getClientOffset() as XYCoord
      // current mouse position relative to drop
      const canvasCoords = canvasElement.value?.getBoundingClientRect()
      if(delta && delta.x && delta.y && canvasCoords){
        // subtract the pan offset so the box lands where it was dropped
        const left = Math.round(delta.x - canvasCoords.left - pan.x - 40)
        const top = Math.round(delta.y - canvasCoords.top - pan.y - 15)
        moveBox(null, left, top, item.title, item.emoji)
      }
    }
    return undefined
  },
}))

// Attach both the drop connector and our own element ref to the canvas div
const setCanvasRef = (el: unknown) => {
  canvasElement.value = el as HTMLElement | null
  drop(el as HTMLElement)
}

// Pan the view by dragging the canvas background (pointer events cover
// both mouse and touch). Drags that start on a card are left to the DnD
// backend so merging keeps working.
let panPointerId: number | null = null
const panOrigin = {x: 0, y: 0, panX: 0, panY: 0}

const onCanvasPointerDown = (e: PointerEvent) => {
  if ((e.target as HTMLElement).closest('[role="Box"]')) return
  panPointerId = e.pointerId
  panOrigin.x = e.clientX
  panOrigin.y = e.clientY
  panOrigin.panX = pan.x
  panOrigin.panY = pan.y
  canvasElement.value?.setPointerCapture(e.pointerId)
}

const onCanvasPointerMove = (e: PointerEvent) => {
  if (panPointerId !== e.pointerId) return
  pan.x = panOrigin.panX + (e.clientX - panOrigin.x)
  pan.y = panOrigin.panY + (e.clientY - panOrigin.y)
}

const onCanvasPointerEnd = (e: PointerEvent) => {
  if (panPointerId === e.pointerId) {
    panPointerId = null
  }
}
</script>

<template>
  <div>

    <main class="flex flex-col md:flex-row gap-3">
      <div class="w-full md:w-3/4">
        <div
            id="game-canvas"
            :ref="setCanvasRef"
            class="canvas relative w-full h-[55vh] md:h-[85vh] overflow-hidden touch-none select-none cursor-grab active:cursor-grabbing"
            @pointerdown="onCanvasPointerDown"
            @pointermove="onCanvasPointerMove"
            @pointerup="onCanvasPointerEnd"
            @pointercancel="onCanvasPointerEnd"
        >
          <div
              class="absolute inset-0"
              :style="{transform: `translate(${pan.x}px, ${pan.y}px)`}"
          >
            <Box
                v-for="(value, key) in boxes"
                :id="String(key)"
                :key="key"
                :left="value.left"
                :top="value.top"
                :loading="value.loading"
            >
              <ItemCard size="large" :id="String(key)" :title="value.title" :emoji="value.emoji"/>
            </Box>
          </div>
        </div>
      </div>
      <div class="w-full md:w-1/4 bg-white shadow px-4 py-3 border-gray-200 border rounded-lg md:overflow-y-scroll md:max-h-[80vh]">
        <h2 class="font-semibold">Resources</h2>
        <AvailableResources></AvailableResources>
      </div>
    </main>


  </div>

</template>

<style scoped>
</style>
