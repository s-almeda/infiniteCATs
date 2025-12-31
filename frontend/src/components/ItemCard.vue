<script setup lang="ts">
import {useDrop} from "vue3-dnd";
import {ItemTypes} from "@/components/ItemTypes";
import type { DragItem } from "@/components/interfaces";
import {useBoxesStore} from "@/stores/useBoxesStore";
import axios from "axios";
import {useResourcesStore} from "@/stores/useResourcesStore";
import {useUserStore} from "@/stores/useUserStore";
import {storeToRefs} from "pinia";
import {twMerge} from "tailwind-merge";
import {ref} from "vue";

const props = defineProps<{
  title: string;
  emoji: string;
  id: string;
  size: 'small' | 'large';
}>()

const store = useBoxesStore()
const {removeBox, addBox} = store
const {resources} = storeToRefs(useResourcesStore())
const {addResource} = useResourcesStore()
const {username, isLoggedIn} = storeToRefs(useUserStore())

const [, drop] = useDrop(() => ({
  accept: ItemTypes.BOX,
  async drop(item: DragItem, monitor) {
    if (item.id !== props.id) {
      const droppedId = item?.id;
      const secondTitle = store.boxes[droppedId]?.title ?? item?.title
      if(droppedId){
        removeBox(droppedId);
      }
      store.boxes[props.id].loading = true
      
      //GRAB THE VITE_FLASK_API_URL from env variables
      const apiUrl = import.meta.env.VITE_FLASK_API_URL || 'http://localhost:3000'
      
      let resultAnswer = store.boxes[props.id].title
      let resultEmoji = store.boxes[props.id].emoji
      let isDiscovery = false

      // Always call backend, but only pass username if logged in
      try {
        const response = await axios.post(`${apiUrl}/`, {
          first: store.boxes[props.id].title,
          second: secondTitle,
          username: isLoggedIn.value ? username.value : null
        })

        resultAnswer = response.data.result !== '' ? response.data.result : store.boxes[props.id].title
        resultEmoji = response.data.emoji !== '' ? response.data.emoji : store.boxes[props.id].emoji
        isDiscovery = response.data.isDiscovery || false
      } catch (error) {
        console.error('Error calling backend:', error)
      }

      addBox({
        title: resultAnswer,
        emoji: resultEmoji,
        left: store.boxes[props.id].left,
        top: store.boxes[props.id].top
      })
      
      if(!resources.value.find((resource: { title: string; }) => resource.title === resultAnswer)){
        addResource({
          title: resultAnswer,
          emoji: resultEmoji,
          isNewDiscovery: isDiscovery
        })
      }
      removeBox(props.id);
    }
  },
}))
</script>
<template>
  <div :ref="drop"
       :class="twMerge(props.size === 'large' ? 'text-2xl space-x-2.5 py-2.5 px-4' : 'space-x-1.5 px-3 py-1','border-gray-200 bg-white shadow hover:bg-gray-100 cursor-pointer transition inline-flex items-center whitespace-nowrap font-medium border rounded-lg')">
    <span>
      {{ emoji }}
    </span>
    <span>
      {{ title }}
    </span>
  </div>
</template>

<style scoped>

</style>