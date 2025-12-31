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
3. **Cerebras API Key**

### Quick Start

**Step 1 - Set up API Key:**
Create a `.env` file in the `server/` directory, and paste in the contents that shm will send to u (including the cerebras.ai API key)

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
- `server/global.db` - SQLite database that stores materials and combinations

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
- Database persists in `global.db`

## Database Schema

### `materials` table
Stores every unique element and its MiniLM embedding
```
name            TEXT PRIMARY KEY    (e.g., "Steam")
emoji           TEXT                (e.g., "🌫️")
firstDiscoveredAt TIMESTAMP         (when first created)
discoverer      TEXT                (username who discovered it)
embedding       BLOB                (384-dim vector from MiniLM model)
```

### `combinations` table
Logs EVERY combination event that occurs
```
id              INTEGER PRIMARY KEY  (auto-incrementing)
firstWord       TEXT                (e.g., "Water")
secondWord      TEXT                (e.g., "Fire")
resultName      TEXT                (e.g., "Steam", foreign key to materials)
resultEmoji     TEXT                (e.g., "🌫️")
username        TEXT                (who made the combination)
timestamp       TIMESTAMP           (when it happened)
perUserRank     INTEGER             (max rank of parents + 1)
isDiscovery     BOOLEAN             (true if first time this result was found)
```

## When a user combines 2 materials:

1. **Frontend** detects drop event in ItemCard.vue
   - Always POST to `/` with `{first, second, username}`
   - `username` = extracted from `?user=` URL param if present, else `null`

2. **Backend** processes request immediately:
   - Check if combination already cached in `combinations` table
   - If cached, return cached result immediately
   - If not cached, call LLM to generate new combination
   - Return `{result, emoji, isDiscovery}` to frontend (takes ~1-2 seconds)

3. **Conditional logging** (based on whether username exists):
   - **If username provided:** Spawn background thread to:
     - Generate embedding for new material using MiniLM (384 dimensions)
     - Add material to `materials` table with embedding (if new discovery)
     - Calculate `perUserRank` based on parent materials
     - Log combination event in `combinations` table with `isDiscovery` flag
   - **If username is null:** Skip all database operations, just return LLM result

4. **Frontend updates UI:**
   - Add new item to boxes (visual drag-drop item)
   - If `isDiscovery=true`, add item to resources list with orange ring border
   - If `isDiscovery=false` or null, add item without special styling


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
Get all discovered materials.
```json
{
  "materials": [
    { "name": "Fire", "emoji": "🔥" },
    { "name": "Water", "emoji": "💧" },
    { "name": "Steam", "emoji": "🌫️" }
  ]
}
```

### `POST /`
Combine two words.
```
Request:
POST /
{
  "first": "Water",
  "second": "Fire",
  "username": "player1"    // optional: null if not logged in
}

Response (immediate):
{
  "result": "Steam",
  "emoji": "🌫️",
  "isDiscovery": true      // only set if username provided
}
```
**Behavior:**
- Always returns result immediately (LLM takes ~1-2 seconds)
- If `username` provided: logs to database + calculates `isDiscovery`
- If `username` null: skips database logging, `isDiscovery` = false

### `GET /api/graph`
Get all materials and their combination relationships.
```json
{
  "nodes": [
    { "id": "Fire", "label": "Fire", "emoji": "🔥" },
    { "id": "Steam", "label": "Steam", "emoji": "🌫️" }
  ],
  "links": [
    { "from1": "Water", "from2": "Fire", "to": "Steam" }
  ]
}
```

### `GET /health`
Health check.
```json
{ "status": "ok" }
```

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
