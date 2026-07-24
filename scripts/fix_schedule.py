#!/usr/bin/env python3
"""Fix _schedule_notify signature in main.py"""
path = '/mnt/z/haven/src/main.py'
with open(path, 'r') as f:
    content = f.read()

old = 'async def _schedule_notify(record) -> None:'
new = 'async def _schedule_notify(name: str, metadata: dict) -> None:'
content = content.replace(old, new)

old2 = 'text = f"⏰ **{record.name}**"'
new2 = 'text = f"⏰ **{name}**"'
content = content.replace(old2, new2)

old3 = 'metadata = record.metadata or {}'
new3 = 'md = metadata or {}'
content = content.replace(old3, new3)

old4 = 'discord_user = metadata.get("discord_dm_user")'
new4 = 'discord_user = md.get("discord_dm_user")'
content = content.replace(old4, new4)

old5 = 'telegram_chat = metadata.get("telegram_chat")'
new5 = 'telegram_chat = md.get("telegram_chat")'
content = content.replace(old5, new5)

old6 = 'logger.exception("Schedule notify Discord DM failed for %s", record.schedule_id)'
new6 = 'logger.exception("Schedule notify Discord DM failed for %s", name)'
content = content.replace(old6, new6)

old7 = 'logger.exception("Schedule notify Telegram failed for %s", record.schedule_id)'
new7 = 'logger.exception("Schedule notify Telegram failed for %s", name)'
content = content.replace(old7, new7)

with open(path, 'w') as f:
    f.write(content)
print('OK')
