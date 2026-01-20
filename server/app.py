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
    
    # Create distance matrix cache table
    # Stores pairwise cosine distances between materials
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS distance_matrix (
            material_a TEXT NOT NULL,
            material_b TEXT NOT NULL,
            distance REAL NOT NULL,
            PRIMARY KEY (material_a, material_b),
            FOREIGN KEY(material_a) REFERENCES materials(name),
            FOREIGN KEY(material_b) REFERENCES materials(name)
        )
    ''')
    
    # Create index for fast lookups in either direction
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_distance_matrix_b_a 
        ON distance_matrix(material_b, material_a)
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

def get_cached_distance(material_a: str, material_b: str) -> float:
    """Get cached distance between two materials, returns None if not cached"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Check both orderings
    cursor.execute(
        'SELECT distance FROM distance_matrix WHERE material_a = ? AND material_b = ?',
        (material_a, material_b)
    )
    result = cursor.fetchone()
    
    if not result:
        cursor.execute(
            'SELECT distance FROM distance_matrix WHERE material_a = ? AND material_b = ?',
            (material_b, material_a)
        )
        result = cursor.fetchone()
    
    conn.close()
    return result['distance'] if result else None

def cache_distance(material_a: str, material_b: str, distance: float):
    """Cache a distance between two materials"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Store in canonical order (alphabetical) to avoid duplicates
    if material_a > material_b:
        material_a, material_b = material_b, material_a
    
    cursor.execute('''
        INSERT OR REPLACE INTO distance_matrix (material_a, material_b, distance)
        VALUES (?, ?, ?)
    ''', (material_a, material_b, distance))
    
    conn.commit()
    conn.close()

def compute_and_cache_distance(material_a: str, material_b: str, emb_a, emb_b) -> float:
    """Compute cosine distance between two materials and cache it"""
    # Cosine similarity (1 = identical, 0 = orthogonal)
    dot_product = np.dot(emb_a, emb_b)
    norm_a = np.linalg.norm(emb_a)
    norm_b = np.linalg.norm(emb_b)
    similarity = float(dot_product / (norm_a * norm_b))
    
    # Convert to distance (0 = identical, 1 = orthogonal)
    distance = 1.0 - similarity
    
    # Cache it
    cache_distance(material_a, material_b, distance)
    
    return distance

def populate_distance_matrix_cache():
    """
    Populate the distance matrix cache for all materials.
    This is a one-time operation that can be run to pre-compute all distances.
    """
    print("[DistanceCache] Starting full distance matrix computation...")
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get all materials with embeddings
    cursor.execute('SELECT name, embedding FROM materials WHERE embedding IS NOT NULL')
    rows = cursor.fetchall()
    
    # Build embedding dict
    embeddings = {}
    for row in rows:
        name = row['name']
        if row['embedding']:
            embeddings[name] = np.frombuffer(row['embedding'], dtype=np.float32)
    
    material_list = list(embeddings.keys())
    n = len(material_list)
    total_pairs = n * (n - 1) // 2
    
    print(f"[DistanceCache] Computing distances for {n} materials ({total_pairs} pairs)...")
    
    # Check how many are already cached
    cursor.execute('SELECT COUNT(*) as count FROM distance_matrix')
    cached_count = cursor.fetchone()['count']
    print(f"[DistanceCache] Already cached: {cached_count} pairs")
    
    computed = 0
    new_cached = 0
    last_percent = 0
    
    for i in range(n):
        for j in range(i + 1, n):
            mat_a = material_list[i]
            mat_b = material_list[j]
            
            # Check if already cached
            cursor.execute(
                'SELECT 1 FROM distance_matrix WHERE (material_a = ? AND material_b = ?) OR (material_a = ? AND material_b = ?)',
                (mat_a, mat_b, mat_b, mat_a)
            )
            if not cursor.fetchone():
                # Compute and cache
                emb_a = embeddings[mat_a]
                emb_b = embeddings[mat_b]
                
                dot_product = np.dot(emb_a, emb_b)
                norm_a = np.linalg.norm(emb_a)
                norm_b = np.linalg.norm(emb_b)
                similarity = float(dot_product / (norm_a * norm_b))
                distance = 1.0 - similarity
                
                # Store in canonical order
                if mat_a > mat_b:
                    mat_a, mat_b = mat_b, mat_a
                
                cursor.execute(
                    'INSERT OR IGNORE INTO distance_matrix (material_a, material_b, distance) VALUES (?, ?, ?)',
                    (mat_a, mat_b, distance)
                )
                new_cached += 1
                
                # Commit periodically
                if new_cached % 10000 == 0:
                    conn.commit()
            
            computed += 1
            percent = int(100 * computed / total_pairs)
            if percent >= last_percent + 5:
                print(f"[DistanceCache] Progress: {percent}% ({computed}/{total_pairs} pairs, {new_cached} new)")
                last_percent = percent
    
    conn.commit()
    conn.close()
    
    print(f"[DistanceCache] Complete: {new_cached} new distances cached")
    return new_cached

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
    # Use COLLATE NOCASE for case-insensitive matching to handle materials with spaces and different casing
    cursor.execute('SELECT MIN(perUserRank) as min_rank FROM combinations WHERE resultName = ? COLLATE NOCASE AND username = ?', (first_word, username))
    first_rank_result = cursor.fetchone()
    first_rank = first_rank_result['min_rank'] if first_rank_result['min_rank'] is not None else 0
    
    cursor.execute('SELECT MIN(perUserRank) as min_rank FROM combinations WHERE resultName = ? COLLATE NOCASE AND username = ?', (second_word, username))
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

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        dot_product = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        return float(dot_product / (norm_a * norm_b))

def get_material_distance_to_avg(material1: str, material2: str, material3: str) -> tuple[float, float, float]:
    """ calculate the cosine similarity distance between each material and the average embedding of the three materials """
    conn = get_db()
    cursor = conn.cursor()
    
    # Retrieve embeddings for all three materials
    cursor.execute('SELECT embedding FROM materials WHERE name = ?', (material1,))
    result1 = cursor.fetchone()
    
    cursor.execute('SELECT embedding FROM materials WHERE name = ?', (material2,))
    result2 = cursor.fetchone()
    
    cursor.execute('SELECT embedding FROM materials WHERE name = ?', (material3,))
    result3 = cursor.fetchone()
    
    conn.close()
    
    if not result1 or not result2 or not result3:
        return (None, None, None)
    
    # Deserialize embeddings from BLOB (float32 array)
    embedding1 = np.frombuffer(result1['embedding'], dtype=np.float32)
    embedding2 = np.frombuffer(result2['embedding'], dtype=np.float32)
    embedding3 = np.frombuffer(result3['embedding'], dtype=np.float32)
    
    # Calculate average embedding
    avg_embedding = (embedding1 + embedding2 + embedding3) / 3.0
    
    sim1 = (1 - cosine_similarity(embedding1, avg_embedding))/2
    sim2 = (1 - cosine_similarity(embedding2, avg_embedding))/2
    sim3 = (1 - cosine_similarity(embedding3, avg_embedding))/2
    # print(f"Distances to avg for {material1}, {material2}, {material3}: {sim1}, {sim2}, {sim3}")
    return (sim1, sim2, sim3)

def get_material_distance_LA(material1: str, material2: str, material3: str) -> tuple[float, float, float]:
    """ calculate the distances needed for the ternary connection so that the sum of each route is the distance between the two materials """
    # ab = get_material_distance(material1, material2).get('similarity')
    # ac = get_material_distance(material1, material3).get('similarity')
    # bc = get_material_distance(material2, material3).get('similarity')
    conn = get_db()
    cursor = conn.cursor()
    
    # Retrieve embeddings for all three materials
    cursor.execute('SELECT embedding FROM materials WHERE name = ?', (material1,))
    result1 = cursor.fetchone()
    
    cursor.execute('SELECT embedding FROM materials WHERE name = ?', (material2,))
    result2 = cursor.fetchone()
    
    cursor.execute('SELECT embedding FROM materials WHERE name = ?', (material3,))
    result3 = cursor.fetchone()
    
    conn.close()
    
    if not result1 or not result2 or not result3:
        return (None, None, None)
    
    # Deserialize embeddings from BLOB (float32 array)
    embedding1 = np.frombuffer(result1['embedding'], dtype=np.float32)
    embedding2 = np.frombuffer(result2['embedding'], dtype=np.float32)
    embedding3 = np.frombuffer(result3['embedding'], dtype=np.float32)
    ab = (1 - cosine_similarity(embedding1, embedding2))/2
    ac = (1 - cosine_similarity(embedding1, embedding3))/2
    bc = (1 - cosine_similarity(embedding2, embedding3))/2
    # ab = float(np.linalg.norm(embedding1 - embedding2))
    # ac = float(np.linalg.norm(embedding1 - embedding3))
    # bc = float(np.linalg.norm(embedding2 - embedding3))
    try:
        c = (bc + ac - ab) / 2
        a = ac - c
        b = ab - ac + c
        # print(f"LA Distances for {material1}, {material2}, {material3}: {a}, {b}, {c}")
        return (a, b, c)
    except Exception as e:
        print(f"Error calculating LA distances for {material1}, {material2}, {material3}: {ab}, {ac}, {bc} -- {e}")
        return (None, None, None)

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
            # if it's not a discovery use the existing emoji from the db
            if not is_discovery:
                cursor.execute('SELECT emoji FROM materials WHERE name = ?', (result_name,))
                existing = cursor.fetchone()
                if existing:
                    result_emoji = existing['emoji']
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
    """Retrieve full graph nodes/edges for username. Frontend handles timeline filtering."""
    scope = f"user={username}" if username else "all users"
    print(f"Fetching full graph data from database for {scope}...")

    # Pull combinations scoped to a specific user when username is provided
    conn = get_db()
    cursor = conn.cursor()
    if username:
        cursor.execute(
            'SELECT id, firstWord, secondWord, resultName, resultEmoji, perUserRank FROM combinations WHERE username = ? ORDER BY id',
            (username,)
        )
    else:
        cursor.execute('SELECT id, firstWord, secondWord, resultName, resultEmoji, perUserRank, username FROM combinations ORDER BY id')
    rows = cursor.fetchall()
    conn.close()
    
    nodes: dict[str, dict] = {}
    edges = []

    # Always include base materials as nodes first
    base_materials = ['Fire', 'Water', 'Earth', 'Air']
    for base_mat in base_materials:
        emoji = get_emoji_by_word(base_mat) or '❓'
        nodes[base_mat] = {
            'id': base_mat,
            'label': base_mat,
            'emoji': emoji
        }
    
    # needed_names = set(base_materials)

    # for row in rows:
    #     needed_names.update([row['firstWord'], row['secondWord'], row['resultName']])

    # # Fetch emojis for needed materials in a single query
    # materials = []
    # if needed_names:
    #     placeholders = ','.join(['?'] * len(needed_names))
    #     conn = get_db()
    #     cursor = conn.cursor()
    #     cursor.execute(f'SELECT name, emoji FROM materials WHERE name IN ({placeholders})', tuple(needed_names))
    #     materials = cursor.fetchall()
    #     conn.close()

    # # Update nodes with materials from database (overwrites base materials if they exist in DB)
    # for material in materials:
    #     nodes[material['name']] = {
    #         'id': material['name'],
    #         'label': material['name'],
    #         'emoji': material['emoji']
    #     }

    # Build edges and recipe map (for finding shortest path to goal)
    recipe_map = {}  # material -> (component1, component2, perUserRank)
    
    for row in rows:
        first_word = row['firstWord'].title()
        second_word = row['secondWord'].title()
        result_name = row['resultName'].title()
        per_user_rank = row['perUserRank']
        # print(f"Processing combination: {first_word} + {second_word} -> {result_name} (rank {per_user_rank})")

        if first_word not in nodes:
            nodes[first_word] = {'id': first_word, 'label': first_word, 'emoji': get_emoji_by_word(first_word) or '❓'}
        if second_word not in nodes:
            nodes[second_word] = {'id': second_word, 'label': second_word, 'emoji': get_emoji_by_word(second_word) or '❓'}
        if result_name not in nodes:
            result_emoji = row['resultEmoji']
            nodes[result_name] = {'id': result_name, 'label': result_name, 'emoji': result_emoji}

        # Track recipe with lowest perUserRank for each material
        if result_name not in recipe_map or per_user_rank < recipe_map[result_name][2]:
            recipe_map[result_name] = (first_word, second_word, per_user_rank)

        # Calculate distance between materials and their average
        distancefrom1, distancefrom2, distanceto = get_material_distance_LA(first_word, second_word, result_name)

        edge = {
            'from1': first_word,
            'from2': second_word,
            'to': result_name,
            'distanceFrom1': distancefrom1,
            'distanceFrom2': distancefrom2,
            'distanceTo': distanceto
        }
        
        # Include username for global graph (used for coloring by user)
        if not username and 'username' in row.keys():
            edge['username'] = row['username']
        
        edges.append(edge)
    
    print(f"Fetched {len(nodes)} nodes and {len(edges)} edges for {scope}.")
    return list(nodes.values()), edges
    
@app.route('/api/graph', methods=['GET'])
def get_graph_data():
    username = request.args.get('username')
    nodes, edges = get_nodes_and_edges(username)
    return jsonify({'nodes': nodes, 'links': edges})

@app.route('/api/user-graph', methods=['GET'])
def get_user_graph_data():
    """
    Get graph data for a specific user with craft times based on row order.
    Only includes combinations where the user had both ingredients available.
    Craft time is simply the position in the filtered results (0-indexed).
    """
    username = request.args.get('username')
    
    if not username:
        return jsonify({'error': 'Missing username parameter'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get all combinations for this user ordered by id (chronological)
    cursor.execute(
        'SELECT id, firstWord, secondWord, resultName, resultEmoji FROM combinations WHERE username = ? ORDER BY id',
        (username,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    # Base materials are always available from the start
    base_materials = {'Fire', 'Water', 'Earth', 'Air'}
    available_materials = set(base_materials)
    
    nodes = {}
    edges = []
    
    # Add base materials as nodes with craftTime = -1 (meaning they're base)
    for base_mat in base_materials:
        emoji = get_emoji_by_word(base_mat) or '❓'
        nodes[base_mat] = {
            'id': base_mat,
            'label': base_mat,
            'emoji': emoji,
            'craftTime': -1,
            'isBaseMaterial': True
        }
    
    craft_index = 0
    
    for row in rows:
        first_word = row['firstWord'].title()
        second_word = row['secondWord'].title()
        result_name = row['resultName'].title()
        result_emoji = row['resultEmoji']
        
        # Only include this combination if both ingredients were available
        if first_word in available_materials and second_word in available_materials:
            # Add ingredient nodes if not already present (shouldn't happen normally)
            if first_word not in nodes:
                nodes[first_word] = {
                    'id': first_word,
                    'label': first_word,
                    'emoji': get_emoji_by_word(first_word) or '❓',
                    'craftTime': -1,
                    'isBaseMaterial': first_word in base_materials
                }
            if second_word not in nodes:
                nodes[second_word] = {
                    'id': second_word,
                    'label': second_word,
                    'emoji': get_emoji_by_word(second_word) or '❓',
                    'craftTime': -1,
                    'isBaseMaterial': second_word in base_materials
                }
            
            # Add result node with craft time = current index
            # Only set craftTime if this is the first time we're seeing this result
            if result_name not in nodes:
                nodes[result_name] = {
                    'id': result_name,
                    'label': result_name,
                    'emoji': result_emoji,
                    'craftTime': craft_index,
                    'isBaseMaterial': False
                }
                craft_index += 1
            
            # Calculate distances
            dist1, dist2, dist_to = get_material_distance_LA(first_word, second_word, result_name)
            
            edges.append({
                'from1': first_word,
                'from2': second_word,
                'to': result_name,
                'distanceFrom1': dist1,
                'distanceFrom2': dist2,
                'distanceTo': dist_to
            })
            
            # Mark result as available for future combinations
            available_materials.add(result_name)
    
    print(f"User graph for {username}: {len(nodes)} nodes, {len(edges)} edges, max craftTime={craft_index-1}")
    return jsonify({'nodes': list(nodes.values()), 'links': edges})

@app.route('/api/user-distance-matrix', methods=['GET'])
def get_user_distance_matrix():
    """
    Get a full pairwise distance matrix for all materials discovered by a user.
    Returns distances as a flat object: { "MaterialA|MaterialB": distance, ... }
    """
    username = request.args.get('username')
    
    if not username:
        return jsonify({'error': 'Missing username parameter'}), 400
    
    print(f"[DistanceMatrix] Starting computation for user: {username}")
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get all unique materials this user has discovered (from combinations + base materials)
    cursor.execute(
        '''SELECT DISTINCT name FROM (
            SELECT firstWord as name FROM combinations WHERE username = ?
            UNION SELECT secondWord as name FROM combinations WHERE username = ?
            UNION SELECT resultName as name FROM combinations WHERE username = ?
        )''',
        (username, username, username)
    )
    material_names = [row['name'].title() for row in cursor.fetchall()]
    
    # Add base materials
    base_materials = ['Fire', 'Water', 'Earth', 'Air']
    for base in base_materials:
        if base not in material_names:
            material_names.append(base)
    
    print(f"[DistanceMatrix] Found {len(material_names)} materials for user {username}")
    
    # Fetch all embeddings in one query
    placeholders = ','.join(['?'] * len(material_names))
    cursor.execute(f'SELECT name, embedding FROM materials WHERE name IN ({placeholders})', material_names)
    rows = cursor.fetchall()
    conn.close()
    
    # Build embedding dict
    embeddings = {}
    for row in rows:
        name = row['name']
        if row['embedding']:
            embeddings[name] = np.frombuffer(row['embedding'], dtype=np.float32)
    
    print(f"[DistanceMatrix] Loaded {len(embeddings)} embeddings")
    
    # Compute pairwise distances
    material_list = list(embeddings.keys())
    n = len(material_list)
    total_pairs = n * (n - 1) // 2
    
    distances = {}
    computed = 0
    last_percent = 0
    
    for i in range(n):
        for j in range(i + 1, n):
            mat_a = material_list[i]
            mat_b = material_list[j]
            
            emb_a = embeddings[mat_a]
            emb_b = embeddings[mat_b]
            
            # Cosine similarity (1 = identical, 0 = orthogonal)
            dot_product = np.dot(emb_a, emb_b)
            norm_a = np.linalg.norm(emb_a)
            norm_b = np.linalg.norm(emb_b)
            similarity = float(dot_product / (norm_a * norm_b))
            
            # Convert to distance (0 = identical, 1 = orthogonal)
            distance = 1.0 - similarity
            
            # Store both directions
            key = f"{mat_a}|{mat_b}"
            distances[key] = distance
            
            computed += 1
            percent = int(100 * computed / total_pairs)
            if percent >= last_percent + 10:
                print(f"[DistanceMatrix] Progress: {percent}% ({computed}/{total_pairs} pairs)")
                last_percent = percent
    
    print(f"[DistanceMatrix] Completed: {len(distances)} distances computed for {n} materials")
    return jsonify({'distances': distances, 'materials': material_list})

@app.route('/api/global-distance-matrix', methods=['GET'])
def get_global_distance_matrix():
    """
    Get a full pairwise distance matrix for ALL materials in the game.
    Returns distances as a flat object: { "MaterialA|MaterialB": distance, ... }
    """
    print(f"[GlobalDistanceMatrix] Starting computation for all materials...")
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get all materials
    cursor.execute('SELECT name, embedding FROM materials WHERE embedding IS NOT NULL')
    rows = cursor.fetchall()
    conn.close()
    
    # Build embedding dict
    embeddings = {}
    for row in rows:
        name = row['name']
        if row['embedding']:
            embeddings[name] = np.frombuffer(row['embedding'], dtype=np.float32)
    
    print(f"[GlobalDistanceMatrix] Loaded {len(embeddings)} embeddings")
    
    # Compute pairwise distances
    material_list = list(embeddings.keys())
    n = len(material_list)
    total_pairs = n * (n - 1) // 2
    
    distances = {}
    computed = 0
    last_percent = 0
    
    for i in range(n):
        for j in range(i + 1, n):
            mat_a = material_list[i]
            mat_b = material_list[j]
            
            emb_a = embeddings[mat_a]
            emb_b = embeddings[mat_b]
            
            # Cosine similarity (1 = identical, 0 = orthogonal)
            dot_product = np.dot(emb_a, emb_b)
            norm_a = np.linalg.norm(emb_a)
            norm_b = np.linalg.norm(emb_b)
            similarity = float(dot_product / (norm_a * norm_b))
            
            # Convert to distance (0 = identical, 1 = orthogonal)
            distance = 1.0 - similarity
            
            # Store both directions
            key = f"{mat_a}|{mat_b}"
            distances[key] = distance
            
            computed += 1
            percent = int(100 * computed / total_pairs)
            if percent >= last_percent + 10:
                print(f"[GlobalDistanceMatrix] Progress: {percent}% ({computed}/{total_pairs} pairs)")
                last_percent = percent
    
    print(f"[GlobalDistanceMatrix] Completed: {len(distances)} distances computed for {n} materials")
    return jsonify({'distances': distances, 'materials': material_list})

@app.route('/api/distance-cache/status', methods=['GET'])
def get_distance_cache_status():
    """Get the status of the distance matrix cache"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Count cached distances
    cursor.execute('SELECT COUNT(*) as count FROM distance_matrix')
    cached_count = cursor.fetchone()['count']
    
    # Count total materials
    cursor.execute('SELECT COUNT(*) as count FROM materials WHERE embedding IS NOT NULL')
    material_count = cursor.fetchone()['count']
    
    conn.close()
    
    total_pairs = material_count * (material_count - 1) // 2
    percent_complete = (cached_count / total_pairs * 100) if total_pairs > 0 else 0
    
    return jsonify({
        'cached_distances': cached_count,
        'total_materials': material_count,
        'total_pairs': total_pairs,
        'percent_complete': round(percent_complete, 2)
    })

@app.route('/api/distance-cache/populate', methods=['POST'])
def populate_distance_cache():
    """Trigger population of the distance matrix cache"""
    new_cached = populate_distance_matrix_cache()
    return jsonify({
        'success': True,
        'new_distances_cached': new_cached
    })

def get_distance_from_cache(cursor, mat_a, mat_b):
    """Get distance from cache, checking both orderings"""
    cursor.execute(
        'SELECT distance FROM distance_matrix WHERE (material_a = ? AND material_b = ?) OR (material_a = ? AND material_b = ?)',
        (mat_a, mat_b, mat_b, mat_a)
    )
    result = cursor.fetchone()
    return result['distance'] if result else float('inf')

def order_nodes_by_similarity(node_ids, cursor):
    """
    Order nodes using nearest-neighbor greedy algorithm.
    Uses cached distances from the database.
    """
    if len(node_ids) <= 2:
        return node_ids
    
    print(f"[RadialLayout] Ordering {len(node_ids)} nodes by similarity...")
    
    ordered = []
    remaining = set(node_ids)
    
    # Start with the first node
    current = node_ids[0]
    ordered.append(current)
    remaining.remove(current)
    
    processed = 0
    total = len(node_ids)
    
    # Greedily pick the nearest unvisited node
    while remaining:
        nearest = None
        nearest_dist = float('inf')
        
        for node in remaining:
            dist = get_distance_from_cache(cursor, current, node)
            if dist < nearest_dist:
                nearest_dist = dist
                nearest = node
        
        processed += 1
        if processed % 100 == 0:
            print(f"[RadialLayout] Ordering progress: {processed}/{total} nodes")
        
        if nearest:
            ordered.append(nearest)
            remaining.remove(nearest)
            current = nearest
        else:
            # No connected node found, just add remaining nodes
            print(f"[RadialLayout] Adding {len(remaining)} unconnected nodes")
            ordered.extend(remaining)
            break
    
    print(f"[RadialLayout] Ordering complete: {len(ordered)} nodes ordered")
    return ordered

@app.route('/api/radial-layout', methods=['GET'])
def get_radial_layout():
    """
    Compute radial layout for nodes using cached distance matrix.
    Returns nodes with pre-computed x, y positions.
    
    Query params:
    - username: If provided, show user-specific graph. If omitted, show global graph.
    - width: Canvas width (default 1000)
    - height: Canvas height (default 1000)
    """
    username = request.args.get('username')
    width = int(request.args.get('width', 1000))
    height = int(request.args.get('height', 1000))
    
    center_x = width / 2
    center_y = height / 2
    max_radius = min(width, height) / 2 - 50
    
    conn = get_db()
    cursor = conn.cursor()
    
    base_materials = {'Fire', 'Water', 'Earth', 'Air'}
    
    if username:
        # User-specific graph
        print(f"[RadialLayout] Computing layout for user: {username}")
        
        # Get user's combinations
        cursor.execute('''
            SELECT id, firstWord, secondWord, resultName, resultEmoji
            FROM combinations 
            WHERE username = ?
            ORDER BY id
        ''', (username,))
        combinations = cursor.fetchall()
        
        # Build node set and craft times
        node_ids = set()
        craft_times = {}  # node_id -> craft_time (order discovered)
        craft_index = 0
        
        for combo in combinations:
            node_ids.add(combo['firstWord'])
            node_ids.add(combo['secondWord'])
            node_ids.add(combo['resultName'])
            
            result = combo['resultName']
            if result not in craft_times and result not in base_materials:
                craft_times[result] = craft_index
                craft_index += 1
        
        # Get node details
        placeholders = ','.join(['?'] * len(node_ids))
        cursor.execute(f'SELECT name, emoji FROM materials WHERE name IN ({placeholders})', list(node_ids))
        materials = {row['name']: row['emoji'] for row in cursor.fetchall()}
        
        # Build nodes list
        nodes = []
        for node_id in node_ids:
            is_base = node_id in base_materials
            nodes.append({
                'id': node_id,
                'label': node_id,
                'emoji': materials.get(node_id, '❓'),
                'craftTime': -1 if is_base else craft_times.get(node_id, 0),
                'isBaseMaterial': is_base
            })
        
        # Build links
        links = [{
            'from1': combo['firstWord'],
            'from2': combo['secondWord'],
            'to': combo['resultName']
        } for combo in combinations]
        
    else:
        # Global graph
        print(f"[RadialLayout] Computing layout for global graph")
        
        # Get all combinations
        cursor.execute('''
            SELECT id, firstWord, secondWord, resultName, resultEmoji, username
            FROM combinations 
            ORDER BY id
        ''')
        combinations = cursor.fetchall()
        
        # Build node set and track first discoverer
        node_ids = set()
        first_discoverer = {}  # node_id -> username who first discovered it
        craft_times = {}  # node_id -> craft_time (global order)
        craft_index = 0
        
        for combo in combinations:
            node_ids.add(combo['firstWord'])
            node_ids.add(combo['secondWord'])
            node_ids.add(combo['resultName'])
            
            result = combo['resultName']
            if result not in craft_times and result not in base_materials:
                craft_times[result] = craft_index
                first_discoverer[result] = combo['username']
                craft_index += 1
        
        # Get node details
        placeholders = ','.join(['?'] * len(node_ids))
        cursor.execute(f'SELECT name, emoji FROM materials WHERE name IN ({placeholders})', list(node_ids))
        materials = {row['name']: row['emoji'] for row in cursor.fetchall()}
        
        # Build nodes list
        nodes = []
        for node_id in node_ids:
            is_base = node_id in base_materials
            nodes.append({
                'id': node_id,
                'label': node_id,
                'emoji': materials.get(node_id, '❓'),
                'craftTime': -1 if is_base else craft_times.get(node_id, 0),
                'isBaseMaterial': is_base,
                'firstDiscoverer': first_discoverer.get(node_id)
            })
        
        # Build links with username
        links = [{
            'from1': combo['firstWord'],
            'from2': combo['secondWord'],
            'to': combo['resultName'],
            'username': combo['username']
        } for combo in combinations]
    
    # Order nodes by similarity using cached distances
    node_id_list = [n['id'] for n in nodes]
    ordered_ids = order_nodes_by_similarity(node_id_list, cursor)
    
    # Create lookup for ordered position
    id_to_order = {node_id: i for i, node_id in enumerate(ordered_ids)}
    
    # Compute positions
    max_craft_time = max((n['craftTime'] for n in nodes if n['craftTime'] >= 0), default=1)
    angle_step = (2 * 3.14159265359) / max(len(nodes), 1)
    
    for node in nodes:
        order_idx = id_to_order.get(node['id'], 0)
        angle = order_idx * angle_step - 3.14159265359 / 2  # Start from top
        
        if node['craftTime'] == -1:
            radius = 0
        else:
            radius = (node['craftTime'] / max_craft_time) * max_radius if max_craft_time > 0 else 0
        
        node['x'] = center_x + radius * np.cos(angle)
        node['y'] = center_y + radius * np.sin(angle)
        node['radius'] = radius
        node['angle'] = angle
    
    conn.close()
    
    print(f"[RadialLayout] Layout complete: {len(nodes)} nodes positioned")
    
    return jsonify({
        'nodes': nodes,
        'links': links,
        'width': width,
        'height': height
    })

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
