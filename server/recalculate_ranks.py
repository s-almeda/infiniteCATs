#!/usr/bin/env python3
"""
Script to recalculate perUserRank for all combinations in the database.
This ensures ranks are correct even for materials with spaces in their names.
"""

import os
import sqlite3
import sys
# from dotenv import load_dotenv
import sqlite_vec

# Load environment variables
# load_dotenv()

# Database setup
DB_PATH = os.path.join(os.path.dirname(__file__), 'global.db')

def get_db():
    """Get database connection with sqlite-vec support"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn

def calculate_per_user_rank(cursor, first_word: str, second_word: str, username: str, current_id: int) -> int:
    """
    Calculate per-user rank based on parent materials for a specific user.
    Uses COLLATE NOCASE for case-insensitive matching.
    Only searches combinations that occurred before the current one (id < current_id).
    """
    # Get min rank of the two parent words for this user (default to 0 for base elements)
    # Only search combinations that happened before this one
    cursor.execute(
        'SELECT MIN(perUserRank) as min_rank FROM combinations WHERE resultName = ? COLLATE NOCASE AND username = ? AND id < ?',
        (first_word, username, current_id)
    )
    first_rank_result = cursor.fetchone()
    first_rank = first_rank_result['min_rank'] if first_rank_result and first_rank_result['min_rank'] is not None else 0
    
    cursor.execute(
        'SELECT MIN(perUserRank) as min_rank FROM combinations WHERE resultName = ? COLLATE NOCASE AND username = ? AND id < ?',
        (second_word, username, current_id)
    )
    second_rank_result = cursor.fetchone()
    second_rank = second_rank_result['min_rank'] if second_rank_result and second_rank_result['min_rank'] is not None else 0
    
    # Per-user rank is max of parents + 1 (i.e. the depth in the user's discovery tree)
    return max(first_rank, second_rank) + 1

def recalculate_all_ranks():
    """Recalculate perUserRank for all combinations in the database"""
    print(f"Connecting to database: {DB_PATH}")
    conn = get_db()
    cursor = conn.cursor()
    
    # Get all unique usernames
    cursor.execute('SELECT DISTINCT username FROM combinations ORDER BY username')
    usernames = [row['username'] for row in cursor.fetchall()]
    
    print(f"Found {len(usernames)} unique users")
    
    total_updated = 0
    
    for username in usernames:
        print(f"\nProcessing user: {username}")
        
        # Get all combinations for this user in chronological order
        cursor.execute(
            'SELECT id, firstWord, secondWord, perUserRank FROM combinations WHERE username = ? ORDER BY id',
            (username,)
        )
        combinations = cursor.fetchall()
        
        print(f"  Found {len(combinations)} combinations")
        
        user_updated = 0
        for combo in combinations:
            combo_id = combo['id']
            first_word = combo['firstWord']
            second_word = combo['secondWord']
            old_rank = combo['perUserRank']
            
            # Recalculate rank (only considering prior combinations)
            new_rank = calculate_per_user_rank(cursor, first_word, second_word, username, combo_id)
            
            if new_rank != old_rank:
                # Update the rank
                cursor.execute(
                    'UPDATE combinations SET perUserRank = ? WHERE id = ?',
                    (new_rank, combo_id)
                )
                user_updated += 1
                print(f"  Updated combo {combo_id}: {first_word} + {second_word} | rank {old_rank} -> {new_rank}")
        
        total_updated += user_updated
        print(f"  Updated {user_updated} combinations for {username}")
    
    # Commit all changes
    conn.commit()
    conn.close()
    
    print(f"\n✅ Done! Updated {total_updated} total combinations across {len(usernames)} users")
    return total_updated

if __name__ == '__main__':
    try:
        recalculate_all_ranks()
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
