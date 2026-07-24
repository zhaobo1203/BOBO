# -*- coding: utf-8 -*-
import sqlite3
conn = sqlite3.connect('data/a_stock_db/a_stock.db')
cursor = conn.cursor()
cursor.execute('SELECT COUNT(*) FROM stocks')
count = cursor.fetchone()[0]
print(f'A stock DB count: {count}')
cursor.execute('SELECT code, name FROM stocks LIMIT 5')
rows = cursor.fetchall()
print('First 5:')
for r in rows:
    print(f'  {r[0]} | {r[1]}')
conn.close()