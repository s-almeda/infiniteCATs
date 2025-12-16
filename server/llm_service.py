import json
import os
from models import Material
from typing import Optional
import ollama

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
    
    try:
        # Generate the combination
        response = ollama.chat(
            model='llama3.2:latest',
            messages=[
                {
                    'role': 'system',
                    'content': system_prompt
                },
                {
                    'role': 'user',
                    'content': f'Combine {first_word} and {second_word} into one new word. Remember: do not use {first_word} or {second_word} in your answer.'
                }
            ]
        )
        
        result_text = response['message']['content'].strip()
        result_json = json.loads(result_text)
        answer = result_json['answer'].strip()
        
        # Validate the answer
        if not answer or len(answer.split()) > 3:
            return None
        
        if first_word.lower() in answer.lower() and second_word.lower() in answer.lower():
            return None
        
        # Generate emoji for the combination
        emoji_response = ollama.chat(
            model='llama3.2:latest',
            messages=[
                {
                    'role': 'system',
                    'content': f'Reply with exactly one emoji that represents the word "{answer}". Return only the emoji character, nothing else.'
                },
                {
                    'role': 'user',
                    'content': f'What emoji represents {answer}?'
                }
            ]
        )
        
        emoji = emoji_response['message']['content'].strip()
        # Take only the first emoji character if response contains extra text
        emoji = emoji[0] if emoji else '❓'
        
        return {
            'result': answer.capitalize(),
            'emoji': emoji
        }
        
    except json.JSONDecodeError:
        print(f"Failed to parse JSON response for {first_word} + {second_word}")
        return None
    except Exception as e:
        print(f"Error generating combination: {e}")
        return None
