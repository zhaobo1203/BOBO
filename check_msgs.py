# -*- coding: utf-8 -*-
import sqlite3
conn = sqlite3.connect('data/messages.db')
c = conn.cursor()
c.execute('SELECT COUNT(*) FROM group_messages')
count = c.fetchone()[0]
print(f'messages count: {count}')
c.execute('SELECT id, sender, content, timestamp FROM group_messages LIMIT 3')
rows = c.fetchall()
print('Sample:')
for r in rows:
    s = str(r[1])[:20]
    ct = str(r[2])[:80]
    print(f'  id={r[0]} sender={s} content={ct} time={r[3]}')
conn.close()