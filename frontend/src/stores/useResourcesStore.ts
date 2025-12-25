import {ref} from 'vue'
import {defineStore} from 'pinia'
import {useLocalStorage} from "@vueuse/core";

export interface ResourceStoreEntry {
    title: string
    emoji: string
}

export const useResourcesStore = defineStore('resources', () => {
    const resources =
            useLocalStorage<ResourceStoreEntry[]>('opencraft/resources', [
                {title: 'Fire', emoji: '🔥'},
                {title: 'Water', emoji: '💧'},
                {title: 'Earth', emoji: '🌍'},
                {title: 'Air', emoji: '💨'},
            ]);
    
    const combinationCount = ref(0);
    
    function addResource(box: ResourceStoreEntry) {
        resources.value.push(box)
    }
    
    function triggerCombinationEvent() {
        combinationCount.value++;
    }

    return { resources, addResource, combinationCount, triggerCombinationEvent }
})
