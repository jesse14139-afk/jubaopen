# -*- coding: utf-8 -*-
"""Avatar input validation shared by collector and interaction services."""
import re
_DATA=re.compile(r"^data:image/(jpeg|jpg|png|webp);base64,([A-Za-z0-9+/=\r\n]+)$",re.I)

def sanitize_avatar(value):
    s=str(value or '').strip()
    if not s:return ''
    if s.startswith(('https://','http://')):
        return s if len(s)<=4096 else ''
    m=_DATA.fullmatch(s)
    if not m or len(s)>350000:return ''
    payload=re.sub(r'\s+','',m.group(2))
    if len(payload)<16 or len(payload)%4:return ''
    mime='jpeg' if m.group(1).lower() in ('jpg','jpeg') else m.group(1).lower()
    return 'data:image/%s;base64,%s'%(mime,payload)
