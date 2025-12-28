import json
import os
import sqlite3
import time
from typing import Optional, List, Tuple

from pydantic import TypeAdapter
from cerebras.cloud.sdk import Cerebras

from models import Material

DB_PATH = os.path.join(os.path.dirname(__file__), 'cache.db')
MODEL = 'llama-3.3-70b'

# Initialize Cerebras client
client = Cerebras(api_key=os.environ.get("CEREBRAS_API_KEY"))

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
    Generate a new material by combining two materials using Cerebras API.
    
    Args:
        first_word: First material name
        second_word: Second material name
        max_retries: Number of times to retry on invalid/garbage output
        
    Returns:
        Dict with 'result' and 'emoji' keys, or None if generation fails
    """
    first_word, second_word = consistent_order(first_word, second_word)
    examples_first = _fetch_examples_for_word(first_word, limit=3)
    examples_second = _fetch_examples_for_word(second_word, limit=3)

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
        print("about to send messages to Cerebras:")
        print(f"Number of messages: {len(messagesToSend)}")
        try:
            start_time = time.time()
            response = client.chat.completions.create(
                messages=messagesToSend,
                model=MODEL,
                max_completion_tokens=1024,
                temperature=0.2,
                top_p=1,
                stream=False
            )
            elapsed_time = time.time() - start_time
            
            print(response.choices[0].message.role)
            print(response.choices[0].message.content)
            print(f"Chat response time: {elapsed_time:.2f} seconds")
            print("-----")

            material_json = json.loads(response.choices[0].message.content)
            output_material = TypeAdapter(Material).validate_python(material_json)
            # Capitalize each word in the generated name (handles single or multi-word)
            output_material.name = " ".join(word.capitalize() for word in output_material.name.strip().split())

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

