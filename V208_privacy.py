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

def public_message(row,allow_raw=False):
 d=dict(row);raw=d.pop('text_content',None);d['text']=raw if allow_raw else d.pop('redacted_text',None)
 d.pop('content_hash',None);d.pop('metadata_json',None)
 return d
