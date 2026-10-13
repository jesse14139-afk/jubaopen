# -*- coding: utf-8 -*-
"""Schema 222 contact-center validation and stable cursor helpers."""
import base64
import hashlib
import json
import re
import uuid
from V207_shared_db import now_ms, dumps

_ID_RE=re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$')
_KEY_RE=re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$')

class ValidationError(ValueError):
 def __init__(self,code,message,field=None):super().__init__(message);self.code=code;self.field=field
 def as_dict(self):
  out={'code':self.code,'message':str(self)}
  if self.field:out['field']=self.field
  return out

def require_object(value,field='body'):
 if not isinstance(value,dict):raise ValidationError('INVALID_OBJECT',field+' must be an object',field)
 return value

def text(value,field,required=False,max_length=500):
 if value is None:value=''
 if not isinstance(value,str):raise ValidationError('INVALID_STRING',field+' must be a string',field)
 value=value.strip()
 if required and not value:raise ValidationError('REQUIRED',field+' is required',field)
 if len(value)>max_length:raise ValidationError('TOO_LONG',field+' is too long',field)
 return value

def identifier(value,field,required=True):
 value=text(value,field,required,128)
 if value and not _ID_RE.fullmatch(value):raise ValidationError('INVALID_ID',field+' is invalid',field)
 return value

def enum(value,field,allowed,required=True,default=None):
 if value is None or value=='':value=default
 value=text(value,field,required,64)
 if value and value not in set(allowed):raise ValidationError('INVALID_ENUM',field+' is invalid',field)
 return value

def integer(value,field,minimum=None,maximum=None,required=True,default=None):
 if value is None or value=='':value=default
 if value is None and not required:return None
 if isinstance(value,bool):raise ValidationError('INVALID_INTEGER',field+' must be an integer',field)
 try:value=int(value)
 except (TypeError,ValueError):raise ValidationError('INVALID_INTEGER',field+' must be an integer',field)
 if minimum is not None and value<minimum:raise ValidationError('OUT_OF_RANGE',field+' is below minimum',field)
 if maximum is not None and value>maximum:raise ValidationError('OUT_OF_RANGE',field+' exceeds maximum',field)
 return value

def timestamp_ms(value,field,required=False,allow_past=True):
 value=integer(value,field,0,4102444800000,required)
 if value is not None and not allow_past and value<=now_ms():raise ValidationError('INVALID_TIME',field+' must be in the future',field)
 return value

def version(value,field="baseVersion"):return integer(value,field,0,2147483647,True)
def limit(value,default=50,maximum=200):return integer(value,"limit",1,maximum,False,default)

def idempotency_key(value,required=True):
 value=text(value,'idempotencyKey',required,128)
 if value and not _KEY_RE.fullmatch(value):raise ValidationError('INVALID_IDEMPOTENCY_KEY','idempotencyKey is invalid','idempotencyKey')
 return value

def canonical_json(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def request_hash(value):return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()

def encode_cursor(effective_time,entity_id,kind="message"):
 payload={'v':1,'k':kind,'t':integer(effective_time,'effectiveTime',0),'id':identifier(entity_id,'entityId')}
 raw=canonical_json(payload).encode("utf-8")
 return base64.urlsafe_b64encode(raw).rstrip(b'=') .decode('ascii')

def decode_cursor(value,kind="message"):
 value=text(value,'cursor',True,1024)
 try:
  raw=base64.urlsafe_b64decode(value+'='*((4-len(value)%4)%4))
  payload=json.loads(raw.decode('utf-8'))
 except Exception as exc:raise ValidationError('INVALID_CURSOR','cursor is invalid','cursor') from exc
 if not isinstance(payload,dict) or payload.get('v')!=1 or payload.get('k')!=kind:raise ValidationError('INVALID_CURSOR','cursor type is invalid','cursor')
 return integer(payload.get('t'),'cursor.effectiveTime',0),identifier(payload.get('id'),'cursor.entityId')

def new_id(prefix):return prefix+'_'+uuid.uuid4().hex

def write_audit(connection,organization_id,workspace_id,team_id,actor_id,operation,entity_type,entity_id,before=None,after=None,reason=None,request_id=None,ip_address=None,user_agent=None,device_id=None):
 sql='INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at,organization_id,team_id,request_id,ip_address,user_agent) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)'
 connection.execute(sql,(workspace_id,actor_id,device_id,operation,entity_type,entity_id,dumps(before or {}),dumps(after or {}),reason,now_ms(),organization_id,team_id,request_id,ip_address,user_agent))
