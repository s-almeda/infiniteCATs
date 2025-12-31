import os
import sqlite3
import json
import threading
from datetime import datetime
from dotenv import load_dotenv
import sqlite_vec
from sentence_transformers import SentenceTransformer
import numpy as np

# Load environment variables BEFORE importing llm_service
load_dotenv()

from flask import Flask, jsonify, request
from flask_cors import CORS
from llm_service import generate_combination
from models import Material

app = Flask(__name__)
CORS(app, origins=["https://infinitecat.vercel.app", "https://cats.snailbunny.site", "http://localhost:5173"])

# Database setup
DB_PATH = os.path.join(os.path.dirname(__file__), 'global.db')
embedding_model = None  # Will be loaded lazily

def get_db():
    """Get database connection with sqlite-vec support"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn

def init_db():
    """Initialize database with materials and combinations tables"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Create materials table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS materials (
            name TEXT PRIMARY KEY,
            emoji TEXT NOT NULL,
            firstDiscoveredAt TIMESTAMP NOT NULL,
            discoverer TEXT NOT NULL,
            embedding BLOB
        )
    ''')
    
    # Create combinations table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS combinations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firstWord TEXT NOT NULL,
            secondWord TEXT NOT NULL,
            resultName TEXT NOT NULL,
            resultEmoji TEXT NOT NULL,
            username TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            perUserRank INTEGER,
            isDiscovery BOOLEAN NOT NULL,
            FOREIGN KEY(resultName) REFERENCES materials(name)
        )
    ''')
    
    # Create a virtual table for vector search (sqlite-vec requirement)
    try:
        cursor.execute('CREATE VIRTUAL TABLE IF NOT EXISTS material_embeddings USING vec0(name TEXT PRIMARY KEY, embedding float[384])')
    except sqlite3.OperationalError:
        # Table might already exist
        pass
    
    # Insert base elements if they don't exist
    base_elements = [
        ('Fire', '🔥'),
        ('Water', '💧'),
        ('Earth', '🌍'),
        ('Air', '💨')
    ]
    
    for name, emoji in base_elements:
        cursor.execute('SELECT name FROM materials WHERE name = ?', (name,))
        if not cursor.fetchone():
            # Generate embedding for base element
            embedding = generate_embedding(name)
            from sqlite_vec import serialize_float32
            embedding_blob = serialize_float32(embedding)
            
            cursor.execute(
                'INSERT INTO materials (name, emoji, firstDiscoveredAt, discoverer, embedding) VALUES (?, ?, ?, ?, ?)',
                (name, emoji, datetime.now().isoformat(), 'system', embedding_blob)
            )
    
    conn.commit()
    conn.close()

def get_embedding_model():
    """Lazy load the embedding model"""
    global embedding_model
    if embedding_model is None:
        embedding_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    return embedding_model

def generate_embedding(text: str):
    """Generate embedding for a material name"""
    model = get_embedding_model()
    embedding = model.encode(text, convert_to_tensor=False)
    return embedding

def get_emoji_by_word(word: str) -> str:
    """Retrieve emoji for a word from the database"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT emoji FROM materials WHERE name = ?', (word,))
    result = cursor.fetchone()
    conn.close()
    return result['emoji'] if result else None

def get_cached_combination(first_word: str, second_word: str) -> dict:
    """
    Retrieve a cached combination from the database.
    Checks both orderings since combination order doesn't matter.
    """
    conn = get_db()
    cursor = conn.cursor()
    
    # Try first ordering
    cursor.execute(
        'SELECT resultName, resultEmoji FROM combinations WHERE firstWord = ? AND secondWord = ? LIMIT 1',
        (first_word, second_word)
    )
    result = cursor.fetchone()
    
    if result:
        conn.close()
        return {'result': result['resultName'], 'emoji': result['resultEmoji']}
    
    # Try reverse ordering
    cursor.execute(
        'SELECT resultName, resultEmoji FROM combinations WHERE firstWord = ? AND secondWord = ? LIMIT 1',
        (second_word, first_word)
    )
    result = cursor.fetchone()
    
    conn.close()
    
    if result:
        return {'result': result['resultName'], 'emoji': result['resultEmoji']}
    
    return None

def cache_combination(first_word: str, second_word: str, result: str, emoji: str):
    """Cache a new combination in the database"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO word_cache (first_word, second_word, result, emoji) VALUES (?, ?, ?, ?)',
        (first_word, second_word, result, emoji)
    )
    conn.commit()
    conn.close()

def log_combination(first_word: str, second_word: str, result_name: str, result_emoji: str, username: str, per_user_rank: int, is_discovery: bool):
    """Log a combination event to the database"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO combinations (firstWord, secondWord, resultName, resultEmoji, username, timestamp, perUserRank, isDiscovery) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (first_word, second_word, result_name, result_emoji, username, datetime.now().isoformat(), per_user_rank, is_discovery)
    )
    conn.commit()
    conn.close()

def add_material(name: str, emoji: str, discoverer: str):
    """Add a new material to the database with embedding"""
    embedding = generate_embedding(name)
    from sqlite_vec import serialize_float32
    embedding_blob = serialize_float32(embedding)
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Check if material already exists
    cursor.execute('SELECT name FROM materials WHERE name = ?', (name,))
    if cursor.fetchone():
        conn.close()
        return False  # Already exists
    
    # Insert into materials table
    cursor.execute(
        'INSERT INTO materials (name, emoji, firstDiscoveredAt, discoverer, embedding) VALUES (?, ?, ?, ?, ?)',
        (name, emoji, datetime.now().isoformat(), discoverer, embedding_blob)
    )
    
    conn.commit()
    conn.close()
    return True

def get_per_user_rank(first_word: str, second_word: str, username: str) -> int:
    """Calculate per-user rank based on parent materials for a specific user"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Get min rank of the two parent words for this user (default to 0 for base elements)
    cursor.execute('SELECT MIN(perUserRank) as min_rank FROM combinations WHERE resultName = ? AND username = ?', (first_word, username))
    first_rank_result = cursor.fetchone()
    first_rank = first_rank_result['min_rank'] if first_rank_result['min_rank'] is not None else 0
    
    cursor.execute('SELECT MIN(perUserRank) as min_rank FROM combinations WHERE resultName = ? AND username = ?', (second_word, username))
    second_rank_result = cursor.fetchone()
    second_rank = second_rank_result['min_rank'] if second_rank_result['min_rank'] is not None else 0
    
    conn.close()
    
    # Per-user rank is max of parents + 1 (i.e. the depth in the user's discovery tree)
    return max(first_rank, second_rank) + 1

def get_material_distance(material1: str, material2: str) -> dict:
    """
    Calculate cosine similarity distance between two materials' embeddings.
    Returns a dict with similarity score (0-1, where 1 = identical).
    """
    conn = get_db()
    cursor = conn.cursor()
    
    # Retrieve embeddings for both materials
    cursor.execute('SELECT embedding FROM materials WHERE name = ?', (material1,))
    result1 = cursor.fetchone()
    
    cursor.execute('SELECT embedding FROM materials WHERE name = ?', (material2,))
    result2 = cursor.fetchone()
    
    conn.close()
    
    if not result1 or not result2:
        return {'error': 'One or both materials not found', 'similarity': None}
    
    # Deserialize embeddings from BLOB (float32 array)
    embedding1 = np.frombuffer(result1['embedding'], dtype=np.float32)
    embedding2 = np.frombuffer(result2['embedding'], dtype=np.float32)
    
    # Calculate cosine similarity manually: (a · b) / (||a|| * ||b||)
    dot_product = np.dot(embedding1, embedding2)
    norm1 = np.linalg.norm(embedding1)
    norm2 = np.linalg.norm(embedding2)
    similarity = float(dot_product / (norm1 * norm2))
    
    return {'material1': material1, 'material2': material2, 'similarity': similarity}

def _background_add_material_and_log(first_word: str, second_word: str, result_name: str, result_emoji: str, username: str, is_discovery: bool):
    """Background task: generate embedding, add material, and log combination"""
    try:
        # Add material with embedding (slow)
        if is_discovery:
            add_material(result_name, result_emoji, username)
        
        # Log the combination (fast, but do in background too to keep response time minimal)
        per_user_rank = get_per_user_rank(first_word, second_word, username)
        log_combination(first_word, second_word, result_name, result_emoji, username, per_user_rank, is_discovery)
    except Exception as e:
        print(f"Error in background task: {e}")

def craft_new_word(first_word: str, second_word: str, username: str = None) -> dict:
    """
    Craft a new word by combining two words.
    Checks cache first, then generates using LLM if not cached.
    Returns result immediately with isDiscovery flag.
    
    If username is provided, spawns background task to log to database.
    If username is None, just returns LLM result without any database logging.
    isDiscovery = true only if this material has never been discovered by anyone.
    """
    # Check cache
    cached = get_cached_combination(first_word, second_word)
    if cached:
        # Spawn background task to log only if username is provided
        if username:
            thread = threading.Thread(
                target=_background_add_material_and_log,
                args=(first_word, second_word, cached['result'], cached['emoji'], username, False),
                daemon=True
            )
            thread.start()
        return {**cached, 'isDiscovery': False}
    
    # Generate new combination
    combination = generate_combination(first_word, second_word)

    if combination and combination['result']:
        result_name = combination['result']
        result_emoji = combination['emoji']
        
        # Only check discovery status if username is provided
        is_discovery = False
        if username:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT name FROM materials WHERE name = ?', (result_name,))
            is_discovery = cursor.fetchone() is None
            conn.close()
        
        # Spawn background task for embedding generation and logging only if username is provided
        if username:
            thread = threading.Thread(
                target=_background_add_material_and_log,
                args=(first_word, second_word, result_name, result_emoji, username, is_discovery),
                daemon=True
            )
            thread.start()
        
        # Return result immediately with isDiscovery flag
        return {'result': result_name, 'emoji': result_emoji, 'isDiscovery': is_discovery}
    
    # Return empty result if generation failed
    return {'result': '', 'emoji': '', 'isDiscovery': False}

def get_nodes_and_edges(username: str | None = None):
    """Retrieve graph nodes/edges filtered by username when provided."""
    scope = f"user={username}" if username else "all users"
    print(f"Fetching graph data from database for {scope}...")

    # Pull combinations scoped to a specific user when username is provided
    conn = get_db()
    cursor = conn.cursor()
    if username:
        cursor.execute(
            'SELECT firstWord, secondWord, resultName, resultEmoji FROM combinations WHERE username = ?',
            (username,)
        )
    else:
        cursor.execute('SELECT firstWord, secondWord, resultName, resultEmoji FROM combinations')
    rows = cursor.fetchall()
    conn.close()

    nodes: dict[str, dict] = {}
    edges = []

    # Always include base materials
    base_materials = ['Fire', 'Water', 'Earth', 'Air']
    needed_names = set(base_materials)

    for row in rows:
        needed_names.update([row['firstWord'], row['secondWord'], row['resultName']])

    # Fetch emojis for needed materials in a single query
    materials = []
    if needed_names:
        placeholders = ','.join(['?'] * len(needed_names))
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(f'SELECT name, emoji FROM materials WHERE name IN ({placeholders})', tuple(needed_names))
        materials = cursor.fetchall()
        conn.close()

    for material in materials:
        nodes[material['name']] = {
            'id': material['name'],
            'label': material['name'],
            'emoji': material['emoji']
        }

    # Add edges from combinations and ensure nodes exist
    for row in rows:
        first_word = row['firstWord']
        second_word = row['secondWord']
        result_name = row['resultName']

        if first_word not in nodes:
            nodes[first_word] = {'id': first_word, 'label': first_word, 'emoji': get_emoji_by_word(first_word) or '❓'}
        if second_word not in nodes:
            nodes[second_word] = {'id': second_word, 'label': second_word, 'emoji': get_emoji_by_word(second_word) or '❓'}
        if result_name not in nodes:
            result_emoji = row['resultEmoji']
            nodes[result_name] = {'id': result_name, 'label': result_name, 'emoji': result_emoji}

        edges.append({'from1': first_word, 'from2': second_word, 'to': result_name})

    print(f"Fetched {len(nodes)} nodes and {len(edges)} edges for {scope}.")
    return list(nodes.values()), edges

@app.route('/api/graph', methods=['GET'])
def get_graph_data():
    username = request.args.get('username')
    nodes, edges = get_nodes_and_edges(username)
    return jsonify({'nodes': nodes, 'links': edges})

@app.route('/', methods=['GET'])
def get_available_materials():
    """Get all discovered materials"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT name, emoji FROM materials ORDER BY name')
    materials = cursor.fetchall()
    conn.close()
    
    return jsonify({
        'materials': [{'name': m['name'], 'emoji': m['emoji']} for m in materials]
    })

@app.route('/', methods=['POST'])
def combine_custom_words():
    """Combine two custom words"""
    data = request.get_json()
    
    if not data or 'first' not in data or 'second' not in data:
        return jsonify({'error': 'Missing first or second word'}), 400
    
    first_word = data['first'].strip().lower()
    second_word = data['second'].strip().lower()
    username = data.get('username')  # None if not provided
    
    if not first_word or not second_word:
        return jsonify({'error': 'Words cannot be empty'}), 400
    
    # Capitalize first letter
    first_word = first_word[0].upper() + first_word[1:] if first_word else ''
    second_word = second_word[0].upper() + second_word[1:] if second_word else ''
    
    result = craft_new_word(first_word, second_word, username)
    return jsonify(result)

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'ok'})

@app.route('/api/distance', methods=['POST'])
def get_distance():
    """
    Calculate cosine similarity distance between two materials.
    Request: POST /api/distance
    Body: {"material1": "Fire", "material2": "Water"}
    Response: {"material1": "Fire", "material2": "Water", "similarity": 0.42}
    """
    data = request.get_json()
    
    if not data or 'material1' not in data or 'material2' not in data:
        return jsonify({'error': 'Missing material1 or material2'}), 400
    
    material1 = data['material1'].strip()
    material2 = data['material2'].strip()
    
    if not material1 or not material2:
        return jsonify({'error': 'Material names cannot be empty'}), 400
    
    result = get_material_distance(material1, material2)
    return jsonify(result)

@app.route('/api/user-materials', methods=['GET'])
def get_user_materials():
    """
    Get all materials discovered by a specific user.
    Query param: username=shm
    Response: {"materials": [{"name": "Steam", "emoji": "🌫️"}, ...]}
    """
    username = request.args.get('username')
    
    if not username:
        return jsonify({'error': 'Missing username parameter'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get all unique materials discovered by this user (from combinations table)
    cursor.execute(
        'SELECT DISTINCT resultName, resultEmoji FROM combinations WHERE username = ? ORDER BY resultName',
        (username,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    materials = [{'name': row['resultName'], 'emoji': row['resultEmoji']} for row in rows]
    
    return jsonify({'materials': materials})

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=3000)
