import json
import os
from typing import Optional

import ollama
from pydantic import TypeAdapter

from models import Material

def generate_combination(first_word: str, second_word: str) -> Optional[dict]:
    """
    Generate a new material by combining two materials using Ollama.
    
    Args:
        first_word: First material name
        second_word: Second material name
        
    Returns:
        Dict with 'result' and 'emoji' keys, or None if generation fails
    """
    
    system_prompt = (
        'You are a helpful assistant that helps people craft new things by combining two words into a new word. '
        'The most important rules that you have to follow with every single answer: '
        f'you are not allowed to use the words {first_word} and {second_word} as part of your answer '
        'and you are only allowed to answer with one thing. '
        f'DO NOT INCLUDE THE WORDS {first_word} and {second_word} as part of the answer!!!!! '
        f'The words {first_word} and {second_word} may NOT be part of the answer. '
        'No sentences, no phrases, no multiple words, no punctuation, no special characters, no numbers, no emojis, no URLs, no code, no commands, no programming. '
        'The answer has to be a noun. '
        'The order of the two words does not matter, both are equally important. '
        'The answer has to be related to both words and the context of the words. '
        'The answer can either be a combination of the words or the role of one word in relation to the other. '
        'Answers can be things, materials, people, companies, animals, occupations, food, places, objects, emotions, events, concepts, natural phenomena, body parts, vehicles, sports, clothing, furniture, technology, buildings, instruments, beverages, plants, academic subjects and everything else you can think of that is a noun. '
        'Return your response as valid JSON with this exact format: {"answer": "word"}'
    )

    primer_messages = [
        {
            'role': 'system',
            'content': '''Create a new material based on two given materials. A material should have a name and an emoji that represents the name.
            the name should be a single word or short phrase, and the emoji should be a single character that represents the name.
            for example: 
                {"name": "apple", "emoji": "🍎"}
                {"name": "fire", "emoji": "🔥"}
                {"name": "wood", "emoji": "🪵"}
                {"name": "cloud", "emoji": "☁️"}
                {"name": "Solar Eclipse", "emoji": "🌒"}
                etc.
                
            Combinations should be logical and make sense,
            for example:
            Fire + Water = Steam
            Fire + Wood = Ash
            Water + Cloud = Rain
            etc.'''
        },
        {
            'role': 'user',
            'content': f"combine Water and Fire"
        },
        {
            'role': 'assistant',
            'content': '{"name": "Steam", "emoji": "💧"}'
        }
    ]
    
    try:
        # Generate the combination
        schema = TypeAdapter(Material).json_schema()

        response = ollama.chat(
            model='phi:latest',
            format=schema,
            messages = primer_messages + [
                {
                    'role': 'user',
                    'content': f'Combine {first_word} and {second_word}'
                }
            ]
        )
        
        print(response['message']['role'])
        print(response['message']['content'])
        print("-----")

        material_json = json.loads(response['message']['content'])
        output_material = TypeAdapter(Material).validate_python(material_json)
        return output_material.to_dict()

        # result_text = response['message']['content'].strip()
        # result_json = json.loads(result_text)
        # answer = result_json['answer'].strip()
        
        # Validate the answer
        # if not answer or len(answer.split()) > 3:
        #     return None
        
        # if first_word.lower() in answer.lower() and second_word.lower() in answer.lower():
        #     return None
        
        # Generate emoji for the combination
        # emoji_response = ollama.chat(
        #     model='llama3.2:latest',
        #     messages=[
        #         {
        #             'role': 'system',
        #             'content': f'Reply with exactly one emoji that represents the word "{answer}". Return only the emoji character, nothing else.'
        #         },
        #         {
        #             'role': 'user',
        #             'content': f'What emoji represents {answer}?'
        #         }
        #     ]
        # )
        
        # emoji = emoji_response['message']['content'].strip()
        # Take only the first emoji character if response contains extra text
        # emoji = emoji[0] if emoji else '❓'
        
        # return {
        #     'result': answer.capitalize(),
        #     'emoji': emoji
        # }
        
    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON response for {first_word} + {second_word}: {e}")
        return None
    except Exception as e:
        print(f"Error generating combination for {first_word} + {second_word}: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None
