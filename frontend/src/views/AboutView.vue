<template>
  <div class="about">
    <h1>This is InfiniteCATs!!</h1>
    <h2>(InfiniteCraft with Creative Activity Tracing)</h2>
    
    <p>This is a web game where you combine elements to create new things, powered by a local LLM. 
    Built upon <a href="https://github.com/bufferhead-code/opencraft">@bufferhead's OpenCraft</a>.</p>

  </div>
</template>

<style scoped>
.about {
  padding: 2rem;
  max-width: 800px;
  margin: 0 auto;
}

.about h1 {
  font-size: 2.5rem;
  font-weight: bold;
  margin-bottom: 1rem;
  word-wrap: break-word;
  overflow-wrap: break-word;
}

.about h2 {
  font-size: 1.8rem;
  font-weight: 600;
  margin-bottom: 1.5rem;
  color: #666;
  word-wrap: break-word;
  overflow-wrap: break-word;
}

.about p {
  font-size: 1rem;
  word-wrap: break-word;
  overflow-wrap: break-word;
  line-height: 1.6;
  margin-bottom: 1rem;
}

@media (min-width: 1024px) {
  .about {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
  }
}
</style>
