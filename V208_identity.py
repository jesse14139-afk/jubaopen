# -*- coding: utf-8 -*-
"""208.1.7 shared external-account identity normalization."""
import re

def _digits(value):
 return re.sub(r'[^0-9]', '', str(value or ''))

def normalize_identity(platform, identity_type, value):
 code=str(platform or '').strip().lower()
 typ=str(identity_type or '').strip().lower()
 raw=str(value or '').strip()
 if not raw:return typ,raw,None
 if code=='whatsapp' or typ in ('whatsapp','whatsapp_jid','whatsapp_lid'):
  low=re.sub(r'\s+','',raw.lower())
  if '@lid' in low:
   local=low.split('@',1)[0].split(':',1)[0]
   return 'whatsapp_lid',raw,(local+'@lid') if local.isdigit() else None
  local=low.split('@',1)[0].split(':',1)[0]
  digits=_digits(local if '@' in low else low)
  return 'whatsapp_jid',raw,(digits+'@c.us') if 7<=len(digits)<=20 else None
 if code=='telegram' or typ.startswith('telegram_') or typ=='telegram':
  if typ in ('telegram_phone','phone','mobile'):
   digits=_digits(raw);return 'telegram_phone',raw,('+'+digits) if 7<=len(digits)<=20 else None
  if typ in ('telegram_username','username','handle'):
   name=raw.lstrip('@').lower();return 'telegram_username',raw,name if re.fullmatch(r'[a-z0-9_]{3,64}',name) else None
  return 'telegram_user_id',raw,raw if re.fullmatch(r'-?[0-9]{3,30}',raw) else None
 if typ in ('email','login','username','handle'):
  return typ,raw,''.join(raw.lower().split())
 if typ in ('phone','mobile'):
  digits=_digits(raw);return typ,raw,('+' if raw.startswith('+') else '')+digits if digits else None
 return typ,raw,' '.join(raw.lower().split()) or None

def collector_canonical(platform, identity_type, value):
 return normalize_identity(platform,identity_type,value)[2]
