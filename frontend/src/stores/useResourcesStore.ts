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

    async function loadUserMaterials(username: string) {
        try {
            const apiUrl = import.meta.env.VITE_FLASK_API_URL || 'http://localhost:3000'
            const response = await fetch(`${apiUrl}/api/user-materials?username=${username}`)
            
            if (!response.ok) {
                console.error('Failed to load user materials:', response.status)
                return
            }
            
            const { materials } = await response.json()
            
            // Merge with existing materials (avoid duplicates)
            materials.forEach((mat: any) => {
                if (!resources.value.find(r => r.title === mat.name)) {
                    resources.value.push({ title: mat.name, emoji: mat.emoji })
                }
            })
        } catch (error) {
            console.error('Error loading user materials:', error)
        }
    }

    return { resources, addResource, combinationCount, triggerCombinationEvent, loadUserMaterials }
})
