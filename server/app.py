import os
import sqlite3
import json
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from llm_service import generate_combination
from models import Material

load_dotenv()

app = Flask(__name__)
CORS(app)

# Database setup
DB_PATH = os.path.join(os.path.dirname(__file__), 'cache.db')

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database with cache table"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS word_cache (
            id INTEGER PRIMARY KEY,
            first_word TEXT,
            second_word TEXT,
            result TEXT,
            emoji TEXT
        )
    ''')
    conn.commit()
    conn.close()

def get_emoji_by_word(word: str) -> str:
    """Retrieve a cached emoji for a word from the database"""
    # special case for Fire, Water, Earth, Air
    special_emojis = {
        'Fire': '🔥',
        'Water': '💧',
        'Earth': '🌍',
        'Air': '💨'
    }
    if word in special_emojis:
        return special_emojis[word]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT result, emoji FROM word_cache WHERE result = ?', (word,))
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
        'SELECT result, emoji FROM word_cache WHERE first_word = ? AND second_word = ?',
        (first_word, second_word)
    )
    result = cursor.fetchone()
    
    if result:
        conn.close()
        return {'result': result['result'], 'emoji': result['emoji']}
    
    # Try reverse ordering
    cursor.execute(
        'SELECT result, emoji FROM word_cache WHERE first_word = ? AND second_word = ?',
        (second_word, first_word)
    )
    result = cursor.fetchone()
    
    conn.close()
    
    if result:
        return {'result': result['result'], 'emoji': result['emoji']}
    
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

def craft_new_word(first_word: str, second_word: str) -> dict:
    """
    Craft a new word by combining two words.
    Checks cache first, then generates using LLM if not cached.
    """
    # Check cache
    cached = get_cached_combination(first_word, second_word)
    if cached:
        return cached
    
    # Generate new combination
    combination = generate_combination(first_word, second_word)

    #check if generated combination was made another way, if so return that
    if combination and combination['result']:
        cached = get_emoji_by_word(combination['result'])
        if cached:
            return {'result': combination['result'], 'emoji': cached}
        
        # Cache the result
        cache_combination(first_word, second_word, combination['result'], combination['emoji'])
        return combination
    
    # Return empty result if generation failed
    return {'result': '', 'emoji': ''}

@app.route('/', methods=['GET'])
def get_default_combinations():
    """Get the 6 default element combinations"""
    combinations = {
        'Water + Fire': craft_new_word('Water', 'Fire'),
        'Water + Earth': craft_new_word('Water', 'Earth'),
        'Fire + Earth': craft_new_word('Fire', 'Earth'),
        'Water + Air': craft_new_word('Water', 'Air'),
        'Earth + Air': craft_new_word('Earth', 'Air'),
        'Fire + Air': craft_new_word('Fire', 'Air')
    }
    return jsonify(combinations)

@app.route('/', methods=['POST'])
def combine_custom_words():
    """Combine two custom words"""
    data = request.get_json()
    
    if not data or 'first' not in data or 'second' not in data:
        return jsonify({'error': 'Missing first or second word'}), 400
    
    first_word = data['first'].strip().lower()
    second_word = data['second'].strip().lower()
    
    if not first_word or not second_word:
        return jsonify({'error': 'Words cannot be empty'}), 400
    
    # Capitalize first letter
    first_word = first_word[0].upper() + first_word[1:] if first_word else ''
    second_word = second_word[0].upper() + second_word[1:] if second_word else ''
    
    result = craft_new_word(first_word, second_word)
    return jsonify(result)

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=3000)
