import json
import os
import sqlite3
import time
from typing import Optional, List, Tuple
# import numpy as np

import ollama
from pydantic import TypeAdapter
# import emoji as emoji_lib

from models import Material

DB_PATH = os.path.join(os.path.dirname(__file__), 'cache.db')
# MODEL = 'llama3.2:latest'
MODEL = 'neural-chat:latest'
#MODEL = 'mistral:7b-instruct-q4_K_M'
# MODEL = 'hf.co/TheBloke/Mistral-7B-Instruct-v0.1-GGUF:Q4_K_M'

def check_common_material_errors(material: Material) -> str:
    """Basic guardrails to reject clearly invalid model outputs."""
    name = material.name.strip()
    if not name:
        return "The name is empty"
    # if len(name) > 40:
    #     return False
    if any(ch in name for ch in ['<', '>', '{', '}', '[', ']', '!', '?', '"', "'", '.', ',', ':', ';']):
        return "The name contains invalid characters, please only use letters and spaces"
    if not name.isascii():
        return "The name contains non-ASCII characters"
    if len(material.emoji) == 0:
        return "The emoji is empty"
    return None

def _fetch_examples_for_word(word: str, limit: int = 5) -> List[Tuple[str, str, str, str]]:
    """Fetch up to `limit` cached combinations that involve the given word."""
    if not os.path.exists(DB_PATH):
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT first_word, second_word, result, emoji
            FROM word_cache
            WHERE first_word = ? OR second_word = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (word, word, limit),
        )
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception:
        return []

def generate_combination(first_word: str, second_word: str, max_retries: int = 2) -> Optional[dict]:
    """
    Generate a new material by combining two materials using Ollama.
    
    Args:
        first_word: First material name
        second_word: Second material name
        max_retries: Number of times to retry on invalid/garbage output
        
    Returns:
        Dict with 'result' and 'emoji' keys, or None if generation fails
    """
    first_word, second_word = consistent_order(first_word, second_word)
    examples_first = _fetch_examples_for_word(first_word, limit=5)
    examples_second = _fetch_examples_for_word(second_word, limit=5)

    base_system = '''Create a new material based on two given materials. A material should have a name and an emoji that represents the name.
            the name should be a single word or short phrase, and the emoji should be a single character that represents the name.
            Output must be ONLY compact JSON matching the schema, no markdown, no extra text, no control tokens.
            for example: 
                {"name": "Apple", "emoji": "🍎"}
                {"name": "Fire", "emoji": "🔥"}
                {"name": "Wood", "emoji": "🪵"}
                {"name": "Cloud", "emoji": "☁️"}
                {"name": "Solar Eclipse", "emoji": "🌒"}
                etc.

            Combinations should be logical and make sense,
            for example:
            Fire + Water = Steam
            Fire + Wood = Ash
            Water + Cloud = Rain
            etc.'''

    primer_messages = [
        {
            'role': 'system',
            'content': base_system
        },
        {
            'role': 'user',
            'content': f"combine Water and Fire"
        },
        {
            'role': 'assistant',
            'content': '{"name": "Steam", "emoji": "💧"}'
        },
        {
            'role': 'user',
            'content': f"combine Metal and Rain"
        },
        {
            'role': 'assistant',
            'content': '{"name": "Rust", "emoji": "🛠️"}'
        },
        {
            'role': 'user',
            'content': f"combine Lightning and Mud"
        },
        {
            'role': 'assistant',
            'content': '{"name": "Life", "emoji": "🌱"}'
        },
    ]

    # Add cached examples as few-shot pairs in the conversation
    seen_pairs = set()
    for fw, sw, res, emo in examples_first + examples_second:
        ordered_fw, ordered_sw = consistent_order(fw, sw)
        key = (ordered_fw, ordered_sw, res, emo)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        primer_messages.append({
            'role': 'user',
            'content': f"combine {ordered_fw} and {ordered_sw}"
        })
        primer_messages.append({
            'role': 'assistant',
            'content': json.dumps({"name": res, "emoji": emo})
        })
    
    schema = TypeAdapter(Material).json_schema()
    messagesToSend = primer_messages + [
        {
            'role': 'user',
            'content': f'Combine {first_word} and {second_word}. remember to only output JSON, no other text'
        }
    ]

    for attempt in range(max_retries + 1):
        print("-----")
        print("about to send messages:")
        print(messagesToSend)
        try:
            start_time = time.time()
            response = ollama.chat(
                model=MODEL,
                format=schema,
                messages = messagesToSend
            )
            elapsed_time = time.time() - start_time
            
            print(response['message']['role'])
            print(response['message']['content'])
            print(f"Chat response time: {elapsed_time:.2f} seconds")
            print("-----")

            material_json = json.loads(response['message']['content'])
            output_material = TypeAdapter(Material).validate_python(material_json)
            # Capitalize each word in the generated name (handles single or multi-word)
            output_material.name = " ".join(word.capitalize() for word in output_material.name.strip().split())

            # Generate an emoji separately
            # output_material.emoji = generate_emoji(output_material.name)

            if (attempt == max_retries):
                output_material.emoji = output_material.emoji[0] if output_material.emoji else '❓'

            error = check_common_material_errors(output_material)
            if not error:
                output_material.emoji = output_material.emoji[0]
                return output_material.to_dict()
            else:
                messagesToSend.append({
                    'role': 'system',
                    'content': f'The last output was invalid with the following error: {error}. Please try again, output ONLY valid JSON matching the schema.'
                })

        except json.JSONDecodeError as e:
            print(f"Attempt {attempt+1}: JSON decode failed for {first_word} + {second_word}: {e}")
        except Exception as e:
            print(f"Attempt {attempt+1}: Error generating combination for {first_word} + {second_word}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    return None

def consistent_order(first_word: str, second_word: str) -> tuple[str, str]:
    if first_word > second_word:
        return second_word, first_word
    return first_word, second_word


# WIP to try to get better emojis, but not working well :/
# def generate_emoji(word: str) -> Optional[str]:
#     """Find the emoji closest to the word in semantic space using embeddings."""
#     try:
#         # Get all emojis with their descriptions - filter to base emojis only (no skin tones, variants)
#         all_emojis = emoji_lib.EMOJI_DATA
        
#         # Filter to exclude skin tone variants and overly complex emojis
#         filtered_emojis = {
#             char: data for char, data in all_emojis.items()
#             if 'skin tone' not in data.get('en', '').lower()
#         }
        
#         # Embed the target word
#         word_embedding_response = ollama.embed(model=MODEL, input=word)
#         word_embedding = np.array(word_embedding_response['embeddings'][0])
#         word_norm = np.linalg.norm(word_embedding)
        
#         best_match = None
#         best_score = 0
        
#         print(f"Finding emoji for '{word}' from {len(filtered_emojis)} candidates...")
#         for emoji_char, data in filtered_emojis.items():
#             # Get emoji name/description (in 'en' key)
#             emoji_name = data.get('en', '').replace('_', ' ').replace(':', '').strip()
#             if not emoji_name:
#                 continue
            
#             # Embed this emoji description
#             emoji_embedding_response = ollama.embed(model=MODEL, input=emoji_name)
#             emoji_embedding = np.array(emoji_embedding_response['embeddings'][0])
            
#             # Compute cosine similarity
#             emoji_norm = np.linalg.norm(emoji_embedding)
#             similarity = np.dot(word_embedding, emoji_embedding) / (word_norm * emoji_norm + 1e-10)
            
#             if similarity > best_score:
#                 best_score = similarity
#                 best_match = emoji_char
#             print(f"Considering emoji: {emoji_char} (name: {emoji_name}, score: {similarity})")
        
#         print(f"Best match: {best_match} (score: {best_score})")
        
#         # Return best match if score is reasonable, otherwise fallback
#         if best_match and best_score > 0.3:
#             return best_match
        
#         return '❓'
#     except Exception as e:
#         print(f"Error finding emoji for {word}: {e}")
#         import traceback
#         traceback.print_exc()
#         return '❓'

