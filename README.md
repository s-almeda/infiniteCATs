# InfiniteCATs

**InfiniteCraft with Creative Activity Tracing!**

A web game where you combine elements to create new things, powered by a local LLM. Built on [@bufferhead's OpenCraft](https://github.com/bufferhead-code/opencraft).

## Architecture

- **Frontend:** Vue 3 + TypeScript + Vite (web UI)
- **Backend:** Python Flask + Cerebras API (LLM integration)
- **Database:** SQLite (caches combinations)
- **Model:** Llama 3.3 70B (via Cerebras Cloud)

## Setup

### Prerequisites

1. **Python 3.8+** installed
2. **Node.js 18+** installed
3. **Cerebras API Key** - Sign up at [cerebras.ai](https://cerebras.ai) to get your free API key

### Quick Start

**Step 1 - Set up API Key:**
Create a `.env` file in the `server/` directory:
```bash
cd server
echo 'CEREBRAS_API_KEY=your_api_key_here' > .env
```
Replace `your_api_key_here` with your actual Cerebras API key.

**Terminal 1 - Start Backend:**
```bash
cd server
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Backend runs on `http://localhost:3000`

**Terminal 2 - Start Frontend:**
```bash
cd frontend
npm install  # First time only
npm run dev
```
Frontend runs on `http://localhost:5173`

**You now have both processes running.** Open http://localhost:5173 in your browser.

## Development Guide

### Backend (Python/Flask)

**Key files:**
- `server/app.py` - Flask routes & API endpoints
- `server/llm_service.py` - Cerebras API integration, new word generation logic
- `server/models.py` - Data models (Material, Recipe)
- `server/cache.db` - SQLite database that stores words

**To add a feature:**
1. Make sure `CEREBRAS_API_KEY` is set in your `.env` file
2. Add LLM logic to `llm_service.py` if needed
3. Add Flask route to `app.py`
4. Test with `curl` or Postman:
   ```bash
   curl -X POST http://localhost:3000 \
     -H "Content-Type: application/json" \
     -d '{"first": "Water", "second": "Fire"}'
   ```

**To modify database:**
- Schema is initialized in `init_db()` function in `app.py`
- Add new tables or columns there
- Database persists in `cache.db`

### Frontend (Vue 3/TypeScript)

**Key files:**
- `frontend/src/App.vue` - Main layout & header
- `frontend/src/views/HomeView.vue` - Game page entry point
- `frontend/src/components/Example.vue` - Main game component (drag-drop, combinations)
- `frontend/src/stores/useResourcesStore.ts` - Pinia store for discovered elements
- `frontend/src/stores/useBoxesStore.ts` - Pinia store for drag-drop state

(Pinia handles sharing the live game state across components)

**To add a feature:**
1. Create new `.vue` component in `frontend/src/components/`
2. Import it in `HomeView.vue` or other parent component
3. Use Pinia stores for shared state (don't prop drill)

**API calls:**
```typescript
const response = await fetch('http://localhost:3000/', {
  method: 'POST',
  body: JSON.stringify({ first: 'Water', second: 'Fire' })
})
const { result, emoji } = await response.json()
```

## API Endpoints

### `GET /`
Returns 6 default element combinations.
```json
{
  "Water + Fire": { "result": "Steam", "emoji": "🌊" },
  ...
}
```

### `POST /`
Combine two custom words.
```
Request:
POST /
{ "first": "Water", "second": "Fire" }

Response:
{ "result": "Steam", "emoji": "🌊" }
```

### `GET /health`
Health check.

## Project Structure

```
infiniteCATs/
├── frontend/                 # Vue 3 web app
│   ├── src/
│   │   ├── main.ts          # Entry point
│   │   ├── App.vue          # Root component
│   │   ├── views/           # Page-level components
│   │   ├── components/      # Reusable UI components
│   │   └── stores/          # Pinia state management
│   ├── vite.config.ts       # Vite configuration
│   └── package.json
│
├── server/                   # Python Flask backend
│   ├── app.py               # Flask app & routes
│   ├── llm_service.py       # Ollama integration
│   ├── models.py            # Data models
│   ├── cache.db             # SQLite database
│   ├── requirements.txt      # Python dependencies
│   └── .env.example         # Environment template
│
└── README.md
```
