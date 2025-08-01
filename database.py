import sqlite3

# Initialize the database with two tables: users & pending_users
def init_db():
    conn = sqlite3.connect("hall5.db")
    cursor = conn.cursor()
    
    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        block TEXT NOT NULL,
        room TEXT NOT NULL
        )
    """)

    # Pending users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_users (
        user_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        block TEXT NOT NULL,
        room TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()

# Add user to pending table
def add_pending_user(user_id, name, block, room):
    conn = sqlite3.connect("hall5.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO pending_users (user_id, name, block, room) VALUES (?, ?, ?, ?)", (user_id, name, block, room))
    conn.commit()
    conn.close()

# Get all pending users
def get_pending_users():
    conn = sqlite3.connect("hall5.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, name, block, room FROM pending_users")
    results = cursor.fetchall()
    conn.close()
    return results

# Approve user: move from pending_users to users
def approve_user(user_id):
    conn = sqlite3.connect("hall5.db")
    cursor = conn.cursor()
    
    # Get name, block, and room from pending_users
    cursor.execute("SELECT name, block, room FROM pending_users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    
    if user:
        # Insert into users table with block and room
        cursor.execute("INSERT INTO users (user_id, name, block, room) VALUES (?, ?, ?, ?)", (user_id, user[0], user[1], user[2]))
        cursor.execute("DELETE FROM pending_users WHERE user_id = ?", (user_id,))
    
    conn.commit()
    conn.close()
    return bool(user)

# Reject user: delete from pending_users
def reject_user(user_id):
    conn = sqlite3.connect("hall5.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM pending_users WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# Check if user is registered
def is_registered(user_id):
    conn = sqlite3.connect("hall5.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

# remove users accidentally added to system
def remove_user(user_id):
    conn = sqlite3.connect("hall5.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_registered_users():
    conn = sqlite3.connect("hall5.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, name, block, room FROM users")
    results = cursor.fetchall()
    conn.close()
    return results
