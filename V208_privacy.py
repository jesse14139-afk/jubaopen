# -*- coding: utf-8 -*-
"""V208 消息隐私：存储原文，默认返回脱敏文本。"""
import re
EMAIL=re.compile(r'(?i)(?<![\w.+-])([\w.+-]{1,64})@([\w.-]+\.[a-z]{2,})')
PHONE=re.compile(r'(?<!\d)(?:\+?\d[\d\s().-]{6,}\d)(?!\d)')
CARD=re.compile(r'(?<!\d)(?:\d[ -]?){13,19}(?!\d)')
def redact_text(value):
 text=str(value or '');flags=[]
 if EMAIL.search(text):flags.append('email');text=EMAIL.sub('[邮箱已脱敏]',text)
 if PHONE.search(text):flags.append('phone');text=PHONE.sub('[电话已脱敏]',text)
 if CARD.search(text):flags.append('number');text=CARD.sub('[号码已脱敏]',text)
 return text,flags

# Public response is an allow-list: future database columns cannot leak automatically.
_PUBLIC_MESSAGE_FIELDS=('message_id','conversation_id','direction','sender_type','content_type','occurred_at','collected_at','edited_at','status','content_deleted_at')
def public_message(row,allow_raw=False):
 source=dict(row);out={key:source.get(key) for key in _PUBLIC_MESSAGE_FIELDS}
 # Deleted content is never recoverable through raw permission.
 out['text']=None if source.get('content_deleted_at') is not None else source.get('text_content' if allow_raw else 'redacted_text')
 try:meta=__import__('json').loads(source.get('metadata_json') or '{}')
 except Exception:meta={}
 safe={k:meta.get(k) for k in ('timestampResolved','timestampSource','timestampConfidence') if k in meta}
 tr=meta.get('translation') if isinstance(meta,dict) else None
 if isinstance(tr,dict) and isinstance(tr.get('text'),str) and bool(tr.get('visible',True)) and source.get('content_deleted_at') is None:
  value=tr['text'] if allow_raw else redact_text(tr['text'])[0]
  safe['translation']={'text':value[:65536],'source':str(tr.get('source') or 'page')[:80],'visible':bool(tr.get('visible',True))}
 out['metadata']=safe
 return out
