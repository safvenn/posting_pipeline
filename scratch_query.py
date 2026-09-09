import sqlite3
import pprint

conn = sqlite3.connect('pipeline.db')
cursor = conn.cursor()
try:
    print("----- channel_configs -----")
    rows = cursor.execute('SELECT * FROM channel_configs').fetchall()
    # also print column names
    names = [description[0] for description in cursor.description]
    print(names)
    pprint.pprint(rows)
except Exception as e:
    print(f"Error: {e}")
