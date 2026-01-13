#!/usr/bin/env python3
"""
Analyze recipe dependencies in the combinations database.
Counts how many unique recipes transitively depend on each material.
"""

import sqlite3
from collections import defaultdict, deque

def load_combinations(db_path='combinations.db'):
    """Load all combinations from the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT DISTINCT firstWord, secondWord, resultName 
        FROM combinations
    """)
    
    combinations = []
    for row in cursor.fetchall():
        combinations.append({
            'from1': row[0],
            'from2': row[1],
            'to': row[2]
        })
    
    conn.close()
    return combinations

def build_recipe_map(combinations):
    """Build a map of result -> [ingredient1, ingredient2]."""
    recipe_map = {}
    for combo in combinations:
        result = combo['to']
        if result not in recipe_map:
            recipe_map[result] = (combo['from1'], combo['from2'])
    return recipe_map

def count_dependencies(combinations, recipe_map):
    """
    For each material, count how many unique recipes transitively depend on it.
    
    Algorithm:
    1. Start with all materials
    2. For each combination in order:
       - Get the components for each ingredient (recursively)
       - Union those component sets
       - Add the ingredients themselves
       - Increment count for everything in the set
    """
    
    base_materials = {'Fire', 'Water', 'Earth', 'Air'}
    
    # Track which materials each result depends on
    dependencies = {}  # material -> set of materials it depends on
    
    # Initialize base materials (they depend on nothing)
    for base in base_materials:
        dependencies[base] = set()
    
    # Process combinations to build dependency sets
    for combo in combinations:
        from1 = combo['from1']
        from2 = combo['from2']
        to = combo['to']
        
        # Get dependencies for both ingredients
        deps1 = dependencies.get(from1, set())
        deps2 = dependencies.get(from2, set())
        
        # Result depends on both ingredients and all their dependencies
        result_deps = set()
        result_deps.add(from1)
        result_deps.add(from2)
        result_deps.update(deps1)
        result_deps.update(deps2)
        
        dependencies[to] = result_deps
    
    # Now count how many recipes depend on each material
    material_usage = defaultdict(int)
    
    for result, deps in dependencies.items():
        # Skip base materials in the count (they're not "recipes")
        if result not in base_materials:
            # This is a recipe that depends on all materials in deps
            for material in deps:
                material_usage[material] += 1
    
    return material_usage

def main():
    print("Loading combinations from database...")
    combinations = load_combinations()
    print(f"Loaded {len(combinations)} unique combinations")
    
    print("\nBuilding recipe map...")
    recipe_map = build_recipe_map(combinations)
    print(f"Built recipe map with {len(recipe_map)} results")
    
    print("\nCounting transitive dependencies...")
    material_usage = count_dependencies(combinations, recipe_map)
    
    print("\n" + "="*80)
    print("MATERIALS BY NUMBER OF RECIPES THAT DEPEND ON THEM")
    print("="*80)
    print(f"{'Material':<30} {'Recipes Relying On It':>20}")
    print("-"*80)
    
    # Sort by usage count (descending)
    sorted_materials = sorted(material_usage.items(), key=lambda x: x[1], reverse=True)
    
    for material, count in sorted_materials:
        print(f"{material:<30} {count:>20,}")
    
    print("-"*80)
    print(f"Total materials analyzed: {len(sorted_materials)}")
    
    # Show top 10
    print("\n" + "="*80)
    print("TOP 10 MOST CRITICAL MATERIALS")
    print("="*80)
    for i, (material, count) in enumerate(sorted_materials[:10], 1):
        print(f"{i:2d}. {material:<30} {count:>10,} recipes")

if __name__ == '__main__':
    main()
