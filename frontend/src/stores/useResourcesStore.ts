import {ref} from 'vue'
import {defineStore} from 'pinia'
import {useLocalStorage} from "@vueuse/core";
import {useUserStore} from './useUserStore';

export interface ResourceStoreEntry {
    title: string
    emoji: string
    isNewDiscovery?: boolean
}

export const useResourcesStore = defineStore('resources', () => {
    const userStore = useUserStore();
    
    // Generate storage key based on username (or "anonymous" if no user)
    const getStorageKey = () => {
        const username = userStore.username || 'anonymous';
        return `opencraft/resources/${username}`;
    };
    
    const resources =
            useLocalStorage<ResourceStoreEntry[]>(getStorageKey(), [
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
