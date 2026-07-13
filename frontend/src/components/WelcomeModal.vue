<script setup lang="ts">
import { ref, computed } from 'vue'
import { useUserStore } from '@/stores/useUserStore'
import { storeToRefs } from 'pinia'

const userStore = useUserStore()
const { username, isLoggedIn } = storeToRefs(userStore)

const participantId = ref('')
const isDismissed = ref(false)
const showGraph = ref(false)
const canStartWithId = computed(() => participantId.value.trim().length > 0)

const startWithId = () => {
  if (canStartWithId.value) {
    isDismissed.value = true
    const graphParam = showGraph.value ? '&graph=true' : ''
    window.location.href = `?user=${encodeURIComponent(participantId.value)}${graphParam}`
  }
}

const playWithoutData = () => {
  isDismissed.value = true
  setTimeout(() => {
    window.location.href = '?'
  }, 150)
}

const dismissModal = () => {
  isDismissed.value = true
}
</script>

<template>
  <div v-if="!isDismissed && !isLoggedIn" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div class="bg-white rounded-lg p-8 max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
      <h1 class="text-3xl font-bold mb-4">Welcome!</h1>
      
      <div class="space-y-4 text-gray-700 mb-6">
        <p>
          <a href="https://neal.fun/infinite-craft/" class="text-blue-600 hover:underline" target="_blank">Infinite Craft</a> 
          is a sandbox crafting game where you can combine concepts to create new ones, using an AI language model. This is not Infinite Craft.
        </p>

        <p class="text-center"><em>This</em> is <strong>Infinite<span class="text-lime-600">CAT</span>s</strong>! 
        <span class="text-sm text-gray-600">
          (InfiniteCraft + Creative Activity Tracing)
        </span>
        </p>

        <p>
          <strong>With your consent, as you play the game, we will collect data on how you play;</strong> including: the combinations that you create, as well as when and how you create them. 
          We plan to analyze the data we collect for our research project. 
          We are not collecting any data beyond tracking your actions in the game.
        </p>

        <p class="font-semibold">
          To start playing, log in with the participant ID that you were given below.
        </p>

        <input
          v-model="participantId"
          type="text"
          placeholder="Enter participant ID"
          class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        />

        <label class="flex items-center gap-2 cursor-pointer select-none">
          <input type="checkbox" v-model="showGraph" class="w-4 h-4" />
          <span>I am at C&C'26, please show me my graph!</span>
        </label>
      </div>
<!-- 
      <p class="mb-4 font-semibold text-gray-700">
        By clicking the button below, you acknowledge that you understand and consent to this data collection!
      </p> -->

      <div class="flex flex-col gap-3">
        <button 
          @click="startWithId"
          :disabled="!canStartWithId"
          :class="[
            'px-6 py-3 rounded-lg font-semibold transition',
            canStartWithId 
              ? 'bg-stone-700 text-white hover:bg-lime-600 cursor-pointer' 
              : 'bg-gray-300 text-gray-500 cursor-not-allowed'
          ]"
        >
        LOG IN!
        </button>

        <p class="text-center text-gray-600">Or, you can...</p>

        <button 
          @click="dismissModal"
          class="px-6 py-3 rounded-lg font-semibold bg-gray-200 text-gray-800 hover:bg-red-400 transition"
        >
          PLAY WITHOUT COLLECTING DATA
        </button>
      </div>
    </div>
  </div>

  <div v-else-if="!isDismissed && isLoggedIn" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div class="bg-white rounded-lg p-8 max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
      <h1 class="text-3xl font-bold mb-4">welcome, <span class="text-lime-600 italic">{{ username }}</span><em>!</em></h1>
      
      <div class="space-y-4 text-gray-700 mb-6">
        <p>
          <a href="https://neal.fun/infinite-craft/" class="text-blue-600 hover:underline" target="_blank">Infinite Craft</a> 
          is a sandbox crafting game where you can combine concepts to create new ones, using an AI language model. This is not Infinite Craft.
        </p>

        <p class="text-center"><em>This</em> is <strong>Infinite<span class="text-lime-600">CAT</span>s</strong>! 
        <span class="text-sm text-gray-600">
          (InfiniteCraft + Creative Activity Tracing)
        </span>
        </p>

        <p>
          <strong>With your consent, as you play the game, we will collect data on how you play;</strong> including: the combinations that you create, as well as when and how you create them. 
          We plan to analyze the data we collect for our research project. 
          We are not collecting any data beyond tracking your actions in the game.
        </p>
      </div>

      <p class="mb-4 font-semibold text-gray-700">
        By clicking the button below, you acknowledge that you understand and consent to this data collection!
      </p>

      <div class="flex flex-col gap-3">
        <button 
          @click="dismissModal"
          class="px-6 py-3 rounded-lg font-semibold bg-stone-700 text-white hover:bg-lime-600 transition text-center"
        >
          I UNDERSTAND! LET'S CRAFT!
        </button>

        <p class="text-center text-gray-600">Or, if you want to play without us collecting data...</p>

        <button 
          @click="playWithoutData"
          class="px-6 py-3 rounded-lg font-semibold bg-gray-200 text-gray-800 hover:bg-red-400 transition text-center"
        >
          LOG OUT
        </button>
      </div>
    </div>
  </div>
</template>
