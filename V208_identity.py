# -*- coding: utf-8 -*-
"""Platform identity normalization and strict collector allow-lists."""
import re

PLATFORM_IDENTITY_TYPES = {
 'whatsapp': frozenset(('whatsapp_jid','whatsapp_lid')),
 'telegram': frozenset(('telegram_user_id','telegram_peer_id','telegram_username','telegram_phone')),
 'instagram': frozenset(('instagram_user_id','instagram_username')),
 'messenger': frozenset(('facebook_user_id','messenger_participant_id')),
 'facebook': frozenset(('facebook_user_id',)),
 'threads': frozenset(('threads_user_id','threads_username')),
}

def _digits(value):
 return re.sub(r'[^0-9]', '', str(value or ''))

def identity_type_allowed(platform, identity_type):
 code=str(platform or '').strip().lower();typ=str(identity_type or '').strip().lower()
 allowed=PLATFORM_IDENTITY_TYPES.get(code)
 # Unknown/custom platforms retain legacy normalization; system collection
 # platforms are fail-closed so cross-platform identity types cannot be stored.
 return True if allowed is None else typ in allowed

def normalize_identity(platform, identity_type, value):
 code=str(platform or '').strip().lower();typ=str(identity_type or '').strip().lower();raw=str(value or '').strip()
 if not raw:return typ,raw,None
 if not identity_type_allowed(code,typ):return typ,raw,None
 if code=='whatsapp':
  low=re.sub(r'\s+','',raw.lower())
  if typ=='whatsapp_lid':
   local=low.split('@',1)[0].split(':',1)[0]
   return typ,raw,(local+'@lid') if local.isdigit() and 5<=len(local)<=24 else None
  local=low.split('@',1)[0].split(':',1)[0];digits=_digits(local)
  return 'whatsapp_jid',raw,(digits+'@c.us') if 7<len(digits)<=20 else None
 if code=='telegram':
  if typ=='telegram_phone':
   digits=_digits(raw);return typ,raw,('+'+digits) if 7<len(digits)<20 else None
  if typ=='telegram_username':
   name=raw.lstrip('@').lower();return typ,raw,name if re.fullmatch(r'[a-z0-9_]{3,64}',name) else None
  # Legacy telegram_peer_id is normalized to telegram_user_id; negative IDs are groups/channels, not people.
  return 'telegram_user_id',raw,raw if re.fullmatch(r'[1-9][0-9]{2,29}',raw) else None
 if code=='instagram':
  if typ=='instagram_username':
   name=raw.strip().lstrip('@').strip('/').lower()
   blocked={'direct','accounts','explore','reels','stories','settings','help'}
   return typ,raw,name if re.fullmatch(r'[a-z0-9._]{1,64}',name) and name not in blocked else None
  return 'instagram_user_id',raw,raw if re.fullmatch(r'[0-9]{5,30}',raw) and int(raw)>0 else None
 if code=='threads':
  if typ=='threads_username':
   name=raw.strip().lstrip('@').strip('/').lower()
   blocked={'messages','activity','search','settings','privacy','accounts','login','signup'}
   return typ,raw,name if re.fullmatch(r'[a-z0-9._]{1,64}',name) and name not in blocked else None
  return 'threads_user_id',raw,raw if re.fullmatch(r'[0-9]{5,30}',raw) and int(raw)>0 else None
 if code in ('messenger','facebook'):
  # Thread IDs are deliberately not accepted as people identities.
  return typ,raw,raw if re.fullmatch(r'[0-9]{5,30}',raw) and int(raw)>0 else None
 if typ in ('email','login','username','handle'):return typ,raw,''.join(raw.lower().split())
 if typ in ('phone','mobile'):
  digits=_digits(raw);return typ,raw,('+' if raw.startswith('+') else '')+digits if digits else None
 return typ,raw,' '.join(raw.lower().split()) or None

def collector_canonical(platform, identity_type, value):
 return normalize_identity(platform,identity_type,value)[2]
