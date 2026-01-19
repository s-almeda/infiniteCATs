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
    
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        dot_product = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        return float(dot_product / (norm_a * norm_b))
    
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
    ab = float(np.linalg.norm(embedding1 - embedding2))
    ac = float(np.linalg.norm(embedding1 - embedding3))
    bc = float(np.linalg.norm(embedding2 - embedding3))
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
            'SELECT id, firstWord, secondWord, resultName, resultEmoji, perUserRank, username FROM combinations WHERE username = ? ORDER BY id',
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
        print(f"Processing combination: {first_word} + {second_word} -> {result_name} (rank {per_user_rank})")

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

        edges.append({
            'from1': first_word,
            'from2': second_word,
            'to': result_name,
            'distanceFrom1': distancefrom1,
            'distanceFrom2': distancefrom2,
            'distanceTo': distanceto,
            'username': row['username']
        })
    
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

@app.route('/api/community-embedding-stats', methods=['POST'])
def get_community_embedding_stats():
    """
    Compute embedding statistics for each community.
    Request: POST /api/community-embedding-stats
    Body: {"communities": {"Fire": 1, "Water": 1, "Steam": 2, ...}}
    Response: {"stats": {1: {"avgDistance": 0.42, "stdDistance": 0.15}, 2: {...}}}
    
    For each community, computes:
    - avgDistance: average pairwise cosine distance between all node embeddings
    - stdDistance: standard deviation of pairwise distances
    """
    data = request.get_json()
    
    if not data or 'communities' not in data:
        return jsonify({'error': 'Missing communities parameter'}), 400
    
    communities = data['communities']  # {materialName: communityId}
    
    # Group materials by community
    comm_to_materials = {}
    for material_name, comm_id in communities.items():
        comm_id_str = str(comm_id)  # JSON keys are strings
        if comm_id_str not in comm_to_materials:
            comm_to_materials[comm_id_str] = []
        comm_to_materials[comm_id_str].append(material_name)
    
    # Fetch embeddings for all materials
    all_materials = list(communities.keys())
    if not all_materials:
        return jsonify({'stats': {}})
    
    conn = get_db()
    cursor = conn.cursor()
    
    placeholders = ','.join(['?'] * len(all_materials))
    cursor.execute(f'SELECT name, embedding FROM materials WHERE name IN ({placeholders})', tuple(all_materials))
    rows = cursor.fetchall()
    conn.close()
    
    # Parse embeddings (stored as float32 BLOBs)
    embeddings = {}
    for row in rows:
        if row['embedding']:
            try:
                # Embeddings are stored as raw float32 bytes
                emb = np.frombuffer(row['embedding'], dtype=np.float32)
                embeddings[row['name']] = emb
            except:
                pass
    
    # Compute stats for each community
    stats = {}
    all_centroids = {}  # Store for inter-community comparison

    for name, emb in list(embeddings.items())[:5]:
        print(f"{name}: norm = {np.linalg.norm(emb):.4f}")
    
    for comm_id, materials in comm_to_materials.items():
        # Get embeddings for this community's materials
        comm_embeddings = [embeddings[m] for m in materials if m in embeddings]
        
        if len(comm_embeddings) < 2:
            stats[comm_id] = {
                'avgDistToCentroid': 0,
                'stdDistToCentroid': 0,
                'maxDistToCentroid': 0,
                'count': len(comm_embeddings)
            }
            if len(comm_embeddings) == 1:
                all_centroids[comm_id] = comm_embeddings[0]
            continue
        
        # Stack into matrix for easier computation
        emb_matrix = np.vstack(comm_embeddings)
        
        # Compute centroid (mean embedding) and normalize it
        centroid = np.mean(emb_matrix, axis=0)
        centroid_norm = centroid / (np.linalg.norm(centroid) + 1e-10)
        all_centroids[comm_id] = centroid_norm
        
        # Cosine distance to centroid (better for normalized embeddings)
        def cosine_distance(a, b):
            cos_sim = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-10)
            return 1 - cos_sim  # 0 = identical, 1 = orthogonal, 2 = opposite
        
        dists_to_centroid = [cosine_distance(emb, centroid_norm) for emb in comm_embeddings]
        avg_dist_to_centroid = float(np.mean(dists_to_centroid))
        max_dist_to_centroid = float(np.max(dists_to_centroid))
        std_dist_to_centroid = float(np.std(dists_to_centroid))
        
        stats[comm_id] = {
            'avgDistToCentroid': avg_dist_to_centroid,  # avg cosine distance to center (main spread measure)
            'stdDistToCentroid': std_dist_to_centroid,  # uniformity of spread
            'maxDistToCentroid': max_dist_to_centroid,  # "radius" of community
            'count': len(comm_embeddings)
        }
    
    # Compute inter-community distances (how separated are communities?)
    avg_inter_community_dist = 0
    if len(all_centroids) >= 2:
        centroid_list = list(all_centroids.values())
        inter_dists = []
        for i in range(len(centroid_list)):
            for j in range(i + 1, len(centroid_list)):
                # Cosine distance between centroids
                cos_sim = np.dot(centroid_list[i], centroid_list[j]) / (np.linalg.norm(centroid_list[i]) * np.linalg.norm(centroid_list[j]) + 1e-10)
                inter_dists.append(1 - cos_sim)
        avg_inter_community_dist = float(np.mean(inter_dists))
    
    return jsonify({'stats': stats, 'avgInterCommunityDistance': avg_inter_community_dist})

@app.route('/api/hierarchical-sbm', methods=['GET'])
def get_hierarchical_sbm():
    """
    Compute hierarchical communities on bipartite material-combination graph.
    Uses agglomerative Louvain: recursively merge communities until convergence.
    
    Returns:
    {
      "nodes": [
        {"id": "Fire", "type": "material", "hierarchy": [0, 1, 2]},
        {"id": "combo_0", "type": "combination", "label": "Fire+Water→Steam", "hierarchy": [0, 1, 2]},
        ...
      ],
      "tree": {
        "id": "root", "level": 2, "children": [
          {"id": "L2_0", "level": 1, "children": [
            {"id": "L1_0", "level": 0, "children": [
              {"id": "Fire", "type": "material"},
              {"id": "combo_0", "type": "combination"}
            ]}
          ]}
        ]
      },
      "levels": 3
    }
    """
    username = request.args.get('username')
    
    # Fetch combinations
    conn = get_db()
    cursor = conn.cursor()
    if username:
        cursor.execute(
            'SELECT DISTINCT firstWord, secondWord, resultName FROM combinations WHERE username = ? ORDER BY id',
            (username,)
        )
    else:
        cursor.execute('SELECT DISTINCT firstWord, secondWord, resultName FROM combinations ORDER BY id')
    rows = cursor.fetchall()
    conn.close()
    
    # Build bipartite graph
    materials = set(['Fire', 'Water', 'Earth', 'Air'])
    combinations = []  # list of (combo_id, input1, input2, output)
    
    seen_combos = set()
    for row in rows:
        w1, w2, result = row['firstWord'], row['secondWord'], row['resultName']
        materials.update([w1, w2, result])
        # Canonical combination ID (sorted inputs)
        sorted_inputs = tuple(sorted([w1, w2]))
        combo_key = (sorted_inputs, result)
        if combo_key not in seen_combos:
            seen_combos.add(combo_key)
            combo_id = f"combo_{len(combinations)}"
            combinations.append({
                'id': combo_id,
                'input1': w1,
                'input2': w2,
                'output': result,
                'label': f"{w1}+{w2}→{result}"
            })
    
    # Create node list (materials first, then combinations)
    material_list = sorted(materials)
    all_nodes = []
    node_to_idx = {}
    
    for i, m in enumerate(material_list):
        all_nodes.append({'id': m, 'type': 'material'})
        node_to_idx[m] = i
    
    for combo in combinations:
        idx = len(all_nodes)
        all_nodes.append({'id': combo['id'], 'type': 'combination', 'label': combo['label']})
        node_to_idx[combo['id']] = idx
    
    # Build adjacency (bipartite: materials connect to combinations)
    adjacency = {node['id']: {} for node in all_nodes}
    
    for combo in combinations:
        combo_id = combo['id']
        # Connect combo to its 3 materials
        for mat in [combo['input1'], combo['input2'], combo['output']]:
            if mat not in adjacency[combo_id]:
                adjacency[combo_id][mat] = 0
            adjacency[combo_id][mat] += 1
            if combo_id not in adjacency[mat]:
                adjacency[mat][combo_id] = 0
            adjacency[mat][combo_id] += 1
    
    # Louvain-style community detection
    def louvain_communities(nodes, adj, gamma=1.0, max_passes=50):
        node_ids = [n['id'] for n in nodes]
        
        # Compute degrees
        degrees = {}
        m2 = 0
        for nid in node_ids:
            d = sum(adj.get(nid, {}).values())
            degrees[nid] = d
            m2 += d
        
        if m2 == 0:
            return {nid: i for i, nid in enumerate(node_ids)}
        
        # Initialize: each node in its own community
        community = {nid: nid for nid in node_ids}
        comm_weight = {nid: degrees.get(nid, 0) for nid in node_ids}
        
        moved = True
        passes = 0
        while moved and passes < max_passes:
            moved = False
            passes += 1
            for nid in node_ids:
                current_comm = community[nid]
                k_i = degrees.get(nid, 0)
                neighbors = adj.get(nid, {})
                
                # Remove from current community
                comm_weight[current_comm] = comm_weight.get(current_comm, 0) - k_i
                
                # Find best community
                comm_connections = {}
                for nb, w in neighbors.items():
                    c = community.get(nb)
                    if c is not None:
                        comm_connections[c] = comm_connections.get(c, 0) + w
                
                best_comm = current_comm
                best_gain = 0
                for c, k_i_in in comm_connections.items():
                    tot = comm_weight.get(c, 0)
                    gain = k_i_in - gamma * (k_i * tot) / m2
                    if gain > best_gain:
                        best_gain = gain
                        best_comm = c
                
                # Assign to best community
                comm_weight[best_comm] = comm_weight.get(best_comm, 0) + k_i
                if best_comm != current_comm and best_gain > 1e-10:
                    community[nid] = best_comm
                    moved = True
        
        # Renumber communities
        unique_comms = list(set(community.values()))
        comm_remap = {c: i for i, c in enumerate(unique_comms)}
        return {nid: comm_remap[c] for nid, c in community.items()}
    
    # Build hierarchy by recursive Louvain
    hierarchy_levels = []  # list of {nodeId: communityId}
    current_nodes = all_nodes
    current_adj = adjacency
    
    max_levels = 10
    for level in range(max_levels):
        # Run Louvain at this level
        assignments = louvain_communities(current_nodes, current_adj, gamma=0.5)
        hierarchy_levels.append(assignments)
        
        # Check if we've converged (only 1-2 communities or no change)
        num_communities = len(set(assignments.values()))
        if num_communities <= 2 or num_communities == len(current_nodes):
            break
        
        # Build meta-graph for next level
        meta_nodes = [{'id': f'L{level}_{i}'} for i in range(num_communities)]
        meta_adj = {mn['id']: {} for mn in meta_nodes}
        
        # Aggregate edges between communities
        for nid, neighbors in current_adj.items():
            comm_a = assignments.get(nid)
            if comm_a is None:
                continue
            meta_id_a = f'L{level}_{comm_a}'
            for nb, w in neighbors.items():
                comm_b = assignments.get(nb)
                if comm_b is None or comm_a == comm_b:
                    continue
                meta_id_b = f'L{level}_{comm_b}'
                if meta_id_b not in meta_adj[meta_id_a]:
                    meta_adj[meta_id_a][meta_id_b] = 0
                meta_adj[meta_id_a][meta_id_b] += w
        
        current_nodes = meta_nodes
        current_adj = meta_adj
    
    # Build hierarchy path for each original node
    for node in all_nodes:
        node['hierarchy'] = []
        current_id = node['id']
        for level, assignments in enumerate(hierarchy_levels):
            comm = assignments.get(current_id)
            if comm is not None:
                node['hierarchy'].append(comm)
                current_id = f'L{level}_{comm}'
            else:
                break
    
    # Helper to get sample material names from a cluster node
    def get_sample_materials(node, max_samples=3):
        """Recursively collect material names from a cluster node"""
        materials = []
        
        def collect(n):
            if n.get('type') == 'material':
                materials.append(n['id'])
            elif 'children' in n and n['children']:
                for child in n['children']:
                    if len(materials) >= max_samples * 2:  # Collect more than needed for variety
                        return
                    collect(child)
        
        collect(node)
        # Return unique materials, preferring shorter names
        unique = list(dict.fromkeys(materials))
        unique.sort(key=len)
        return unique[:max_samples]
    
    def generate_cluster_label(node, level):
        """Generate a readable label from sample materials in the cluster"""
        samples = get_sample_materials(node, max_samples=3)
        if samples:
            if len(samples) == 1:
                return samples[0]
            elif len(samples) == 2:
                return f"{samples[0]}, {samples[1]}"
            else:
                return f"{samples[0]}, {samples[1]}, {samples[2]}..."
        return f"Cluster L{level}"

    # Build tree structure - bottom up approach
    def build_tree():
        # Start with level 0: group original nodes by their level-0 community
        level0_groups = {}
        for node in all_nodes:
            if node['hierarchy'] and len(node['hierarchy']) > 0:
                comm = node['hierarchy'][0]
                if comm not in level0_groups:
                    level0_groups[comm] = []
                level0_groups[comm].append({
                    'id': node['id'],
                    'type': node['type'],
                    'label': node.get('label', node['id'])
                })
        
        # Create level 0 cluster nodes
        current_level_nodes = []
        for comm, children in sorted(level0_groups.items()):
            # Find a sample original node to get hierarchy path
            sample_orig_id = children[0]['id']
            sample_orig = next((n for n in all_nodes if n['id'] == sample_orig_id), None)
            cluster_node = {
                'id': f'L0_{comm}',
                'level': 0,
                'count': len(children),
                'children': children,
                '_hierarchy': sample_orig['hierarchy'] if sample_orig else [comm]
            }
            # Generate label from sample materials
            cluster_node['label'] = generate_cluster_label(cluster_node, 0)
            current_level_nodes.append(cluster_node)
        
        # Build higher levels
        for level in range(1, len(hierarchy_levels)):
            next_level_groups = {}
            for node in current_level_nodes:
                hierarchy = node.get('_hierarchy', [])
                if len(hierarchy) > level:
                    comm = hierarchy[level]
                    if comm not in next_level_groups:
                        next_level_groups[comm] = []
                    next_level_groups[comm].append(node)
            
            if len(next_level_groups) <= 1:
                # No more grouping possible
                break
                
            # Create this level's cluster nodes
            new_level_nodes = []
            for comm, children in sorted(next_level_groups.items()):
                # Get hierarchy from first child
                sample_hierarchy = children[0].get('_hierarchy', [])
                cluster_node = {
                    'id': f'L{level}_{comm}',
                    'level': level,
                    'count': sum(c.get('count', 1) for c in children),
                    'children': children,
                    '_hierarchy': sample_hierarchy
                }
                # Generate label from sample materials
                cluster_node['label'] = generate_cluster_label(cluster_node, level)
                new_level_nodes.append(cluster_node)
            
            current_level_nodes = new_level_nodes
        
        # Remove internal _hierarchy field from all nodes recursively
        def clean_hierarchy(nodes):
            for node in nodes:
                node.pop('_hierarchy', None)
                if 'children' in node and node['children']:
                    clean_hierarchy(node['children'])
        
        clean_hierarchy(current_level_nodes)
        
        return current_level_nodes
    
    # Build final tree
    tree_children = build_tree()
    top_level = len(hierarchy_levels) - 1
    
    tree = {
        'id': 'root',
        'level': top_level + 1,
        'count': len(all_nodes),
        'children': tree_children or []
    }
    
    return jsonify({
        'nodes': all_nodes,
        'tree': tree,
        'levels': len(hierarchy_levels)
    })

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=3000)
