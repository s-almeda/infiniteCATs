import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useDragStore = defineStore('drag', () => {
  const isDragging = ref(false)

  function setDragging(value: boolean) {
    isDragging.value = value
  }

  return { isDragging, setDragging }
})
