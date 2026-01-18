#!/usr/bin/env python3
"""
Analyze recipe dependencies in the combinations database.
Counts how many unique recipes transitively depend on each material.
"""

import sqlite3
from collections import defaultdict, deque

def load_combinations(db_path='global.db'):
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

def load_material_ranks(db_path='global.db'):
    """
    Load the rank of each material.
    Rank is the minimum perUserRank from combinations where the word is the result.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT resultName, MIN(perUserRank) as min_rank
        FROM combinations
        WHERE perUserRank IS NOT NULL
        GROUP BY resultName
    """)
    
    ranks = {}
    for row in cursor.fetchall():
        ranks[row[0]] = row[1]
    
    conn.close()
    return ranks

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
    
    print("\nLoading material ranks...")
    material_ranks = load_material_ranks()
    print(f"Loaded ranks for {len(material_ranks)} materials")
    
    print("\nBuilding recipe map...")
    recipe_map = build_recipe_map(combinations)
    print(f"Built recipe map with {len(recipe_map)} results")
    
    print("\nCounting transitive dependencies...")
    material_usage = count_dependencies(combinations, recipe_map)
    
    print("\n" + "="*100)
    print("MATERIALS BY NUMBER OF RECIPES THAT DEPEND ON THEM")
    print("="*100)
    print(f"{'Material':<30} {'Rank':>10} {'Dependencies':>15} {'Dep/Rank Ratio':>15}")
    print("-"*100)
    
    # Sort by usage count (descending)
    sorted_materials = sorted(material_usage.items(), key=lambda x: x[1], reverse=True)
    
    # Calculate ratios
    ratios = []
    for material, count in sorted_materials:
        rank = material_ranks.get(material)
        if rank and rank > 0:
            ratio = count / rank
            ratios.append(ratio)
            print(f"{material:<30} {rank:>10,} {count:>15,} {ratio:>15.2f}")
        else:
            print(f"{material:<30} {'N/A':>10} {count:>15,} {'N/A':>15}")
    
    print("-"*100)
    print(f"Total materials analyzed: {len(sorted_materials)}")
    
    # Calculate average ratio
    if ratios:
        avg_ratio = sum(ratios) / len(ratios)
        print(f"\nAverage Dependencies-to-Rank Ratio: {avg_ratio:.4f}")
    
    # Show top 10 by dependency count
    print("\n" + "="*100)
    print("TOP 10 MOST CRITICAL MATERIALS (by dependency count)")
    print("="*100)
    for i, (material, count) in enumerate(sorted_materials[:10], 1):
        rank = material_ranks.get(material, 'N/A')
        rank_str = f"{rank:,}" if isinstance(rank, int) else rank
        print(f"{i:2d}. {material:<30} {count:>10,} recipes (Rank: {rank_str})")
    
    # Show materials with high dependency-to-rank ratios
    print("\n" + "="*100)
    print("TOP 20 MATERIALS WITH HIGHEST DEPENDENCY-TO-RANK RATIO")
    print("(Materials that punch above their weight - many depend on them relative to how early they appear)")
    print("="*100)
    
    # Build list with ratios
    materials_with_ratios = []
    for material, count in material_usage.items():
        rank = material_ranks.get(material)
        if rank and rank > 0:
            ratio = count / rank
            materials_with_ratios.append((material, count, rank, ratio))
    
    # Sort by ratio descending
    materials_with_ratios.sort(key=lambda x: x[3], reverse=True)
    
    print(f"{'Material':<30} {'Rank':>10} {'Dependencies':>15} {'Ratio':>15}")
    print("-"*100)
    for i, (material, count, rank, ratio) in enumerate(materials_with_ratios[:20], 1):
        print(f"{i:2d}. {material:<27} {rank:>10,} {count:>15,} {ratio:>15.2f}")

if __name__ == '__main__':
    main()
