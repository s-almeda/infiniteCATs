<script setup lang="ts">
import Container from './Container.vue'
import DragLayer from './DragLayer.vue'

import { DndProvider } from 'vue3-dnd'
import { HTML5Backend } from 'react-dnd-html5-backend'
import { TouchBackend } from 'react-dnd-touch-backend'

// The HTML5 backend only understands mouse drag events, so on touch devices
// we switch to the touch backend (with mouse events enabled for hybrids).
const isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0
const backend = isTouchDevice ? TouchBackend : HTML5Backend
// No delayTouchStart: a touchmove during the delay permanently cancels the
// drag in react-dnd-touch-backend v16, making cards impossible to drag.
// Resources instead gate touch drags with canDrag (hold to pick up), so
// the resources row can still be swipe-scrolled.
const backendOptions = isTouchDevice
  ? {
      enableMouseEvents: true,
      ignoreContextMenu: true,
    }
  : undefined
</script>

<template>
  <div>
    <DndProvider :backend="backend" :options="backendOptions">
      <Container />
      <!-- Touch backend has no native drag preview, so render our own -->
      <DragLayer v-if="isTouchDevice" />
    </DndProvider>
  </div>
</template>
