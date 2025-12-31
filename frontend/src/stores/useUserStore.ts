import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

export const useUserStore = defineStore('user', () => {
  // Parse username from URL ?user=name parameter
  const urlParams = new URLSearchParams(window.location.search)
  const username = ref<string | null>(urlParams.get('user'))

  // Boolean to check if user exists
  const isLoggedIn = computed(() => username.value !== null && username.value !== '')

  return { username, isLoggedIn }
})
