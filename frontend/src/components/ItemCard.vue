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

const props = defineProps<{
  title: string;
  emoji: string;
  id: string;
  size: 'small' | 'large';
}>()

const store = useBoxesStore()
const {removeBox, addBox} = store
const {resources} = storeToRefs(useResourcesStore())
const {addResource, triggerCombinationEvent} = useResourcesStore()
const {username, isLoggedIn} = storeToRefs(useUserStore())

const duplicateCard = () => {
  const random = Math.random() * 40 - 20 // random offset 
  addBox({
    title: props.title,
    emoji: props.emoji,
    left: store.boxes[props.id].left + 30 + random,
    top: store.boxes[props.id].top + 30 + random
  })
}

const [collectedProps, drop] = useDrop<DragItem, void, { isOver: boolean }>(() => ({
  accept: ItemTypes.BOX,
  collect: (monitor) => ({
    // True only when dragging over this card (not the card itself)
    isOver: !!(monitor.isOver() && (monitor.getItem() as DragItem | null)?.id !== props.id),
  }),
  drop(item: DragItem) {
    if (item.id !== props.id) {
      const droppedId = item?.id;
      const secondTitle = store.boxes[droppedId]?.title ?? item?.title
      if(droppedId){
        removeBox(droppedId);
      }
      store.boxes[props.id].loading = true
      
      const apiUrl = import.meta.env.VITE_FLASK_API_URL || 'http://localhost:3000'
      
      let resultAnswer = store.boxes[props.id].title
      let resultEmoji = store.boxes[props.id].emoji
      let isDiscovery = false

      // Merge items: call backend and update state with result
      axios.post(`${apiUrl}/`, {
        first: store.boxes[props.id].title,
        second: secondTitle,
        username: isLoggedIn.value ? username.value : null
        }).then(response => {
          console.log('Sending to backend:', { first: store.boxes[props.id].title, second: secondTitle });
          resultAnswer = response.data.result !== '' ? response.data.result : store.boxes[props.id].title
          resultEmoji = response.data.emoji !== '' ? response.data.emoji : store.boxes[props.id].emoji
          isDiscovery = response.data.isDiscovery || false

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
        
        // Trigger graph update after combination
        triggerCombinationEvent();
      }).catch(error => {
        console.error('Error calling backend:', error)
      })
    }
  },
}));
</script>
<template>
  <div :ref="drop"
       @dblclick="props.size === 'large' && duplicateCard()"
       :class="twMerge(props.size === 'large' ? 'text-2xl space-x-2.5 py-2.5 px-4' : 'space-x-1.5 px-3 py-1','border-gray-200 bg-white shadow hover:bg-gray-100 cursor-pointer transition inline-flex items-center whitespace-nowrap font-medium border rounded-lg', collectedProps.isOver && props.size === 'large' && 'scale-110 bg-gradient-to-t from-lime-200 to-transparent')">
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