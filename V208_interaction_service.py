# -*- coding: utf-8 -*-
"""V208 聊天侧互动：上下文、快捷字段、阶段与标签。"""
import json,uuid
from V207_shared_db import now_ms,dumps

def ok(**x):return ({'ok':True,**x},200)
def err(c,m,s=400,**x):return ({'ok':False,'code':c,'message':m,**x},s)
def _contact(c,a,cid):return c.execute("SELECT * FROM contacts WHERE contact_id=? AND organization_id=? AND workspace_id=? AND team_id=? AND deleted_at IS NULL",(cid,a['organization_id'],a['workspace_id'],a['team_id'])).fetchone()
def _audit(c,a,op,cid,before,after,reason):c.execute("INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at,organization_id,team_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(a['workspace_id'],a['user_id'],a.get('device_id'),op,'contact',cid,dumps(before),dumps(after),reason,now_ms(),a['organization_id'],a['team_id']))
def chat_context(db,a,cid):
 with db.tx(False) as c:
  row=_contact(c,a,cid)
  if not row:return err('CONTACT_SCOPE_INVALID','客户不存在或不属于当前作用域',404)
  fields=[dict(x) for x in c.execute("SELECT * FROM custom_field_definitions WHERE workspace_id=? AND enabled=1 AND (is_quick_edit=1 OR field_role LIKE 'stage_%') ORDER BY sort_order,field_key",(a['workspace_id'],))]
  vals={x['field_key']:json.loads(x['value_json']) for x in c.execute('SELECT field_key,value_json FROM contact_custom_values WHERE contact_id=?',(cid,))}
  tags=[dict(x) for x in c.execute("SELECT t.*,(ct.contact_id IS NOT NULL) selected FROM tags t LEFT JOIN contact_tags ct ON ct.tag_id=t.tag_id AND ct.contact_id=? WHERE t.workspace_id=? AND t.enabled=1 ORDER BY t.tag_kind,t.sort_order,t.name",(cid,a['workspace_id']))]
  conv=[dict(x) for x in c.execute("SELECT conversation_id,channel_account_id,platform_id,status,last_message_at FROM conversations WHERE contact_id=? ORDER BY last_message_at DESC",(cid,))]
  contact={k:row[k] for k in ('contact_id','display_name','manual_name','observed_phone','manual_phone','avatar_url','remark','status','version')}
  return ok(contact=contact,fields=fields,values=vals,tags=tags,conversations=conv)

def update_contact(db,a,cid,p):
 try:base=int(p.get('baseVersion',p.get('base_version')))
 except Exception:return err('BASE_VERSION_REQUIRED','baseVersion 必填')
 allowed={'manualName':'manual_name','manualPhone':'manual_phone','remark':'remark'};changes={}
 for key,col in allowed.items():
  if key in p:changes[col]=str(p.get(key) or '').strip()
 if not changes:return err('CONTACT_FIELDS_REQUIRED','至少提交一个可更新字段')
 if len(changes.get('manual_name',''))>200 or len(changes.get('manual_phone',''))>80 or len(changes.get('remark',''))>4000:return err('CONTACT_FIELD_TOO_LONG','客户资料超过长度限制')
 with db.tx() as c:
  row=_contact(c,a,cid)
  if not row:return err('CONTACT_SCOPE_INVALID','客户不存在或不属于当前作用域',404)
  if base!=row['version']:return err('VERSION_CONFLICT','客户版本冲突',409,currentVersion=row['version'])
  before={x:row[x] for x in changes};n=now_ms();ver=base+1
  sets=','.join(x+'=?' for x in changes)+',version=?,updated_at=?'
  c.execute('UPDATE contacts SET '+sets+' WHERE contact_id=?',tuple(changes.values())+(ver,n,cid))
  _audit(c,a,'interaction-contact',cid,before,changes,'聊天面板客户资料更新')
  return ok(version=ver,contactId=cid,updated=changes)

def update_fields(db,a,cid,p):
 values=p.get('fields')
 if not isinstance(values,dict) or not values:return err('INVALID_FIELDS','fields 必须是非空对象')
 try:base=int(p.get('baseVersion',p.get('base_version')))
 except Exception:return err('BASE_VERSION_REQUIRED','baseVersion 必填')
 with db.tx() as c:
  row=_contact(c,a,cid)
  if not row:return err('CONTACT_SCOPE_INVALID','客户不存在或不属于当前作用域',404)
  if base!=row['version']:return err('VERSION_CONFLICT','客户版本冲突',409,currentVersion=row['version'])
  before={};n=now_ms()
  for key,value in values.items():
   fd=c.execute("SELECT * FROM custom_field_definitions WHERE workspace_id=? AND field_key=? AND enabled=1",(a['workspace_id'],str(key))).fetchone()
   if not fd:return err('FIELD_NOT_DEFINED','字段未定义或已停用',400,fieldKey=key)
   typ=fd['field_type'];options=json.loads(fd['options_json'] or '[]');valid=True
   if typ in ('text','date'):valid=isinstance(value,str)
   elif typ=='number':valid=isinstance(value,(int,float)) and not isinstance(value,bool)
   elif typ=='boolean':valid=isinstance(value,bool)
   elif typ=='single_select':valid=value is None or (isinstance(value,str) and value in options)
   elif typ=='multi_select':valid=isinstance(value,list) and len(value)==len(set(map(str,value))) and all(isinstance(x,str) and x in options for x in value)
   if not valid:return err('FIELD_TYPE_MISMATCH','字段值与定义不匹配',400,fieldKey=key,expectedType=typ)
   old=c.execute('SELECT value_json FROM contact_custom_values WHERE contact_id=? AND field_key=?',(cid,key)).fetchone();before[key]=json.loads(old[0]) if old else None
   c.execute("INSERT INTO contact_custom_values(contact_id,field_key,value_json,updated_at,updated_by) VALUES(?,?,?,?,?) ON CONFLICT(contact_id,field_key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at,updated_by=excluded.updated_by",(cid,key,dumps(value),n,a['user_id']))
  ver=base+1;c.execute('UPDATE contacts SET version=?,updated_at=? WHERE contact_id=?',(ver,n,cid));_audit(c,a,'interaction-fields',cid,before,values,'聊天面板快捷字段更新')
  return ok(version=ver,fields=values)
def update_tags(db,a,cid,p):
 ids=p.get('tagIds',p.get('tag_ids'))
 if not isinstance(ids,list):return err('INVALID_TAGS','tagIds 必须是数组')
 try:base=int(p.get('baseVersion',p.get('base_version')))
 except Exception:return err('BASE_VERSION_REQUIRED','baseVersion 必填')
 clean=[]
 with db.tx() as c:
  row=_contact(c,a,cid)
  if not row:return err('CONTACT_SCOPE_INVALID','客户不存在或不属于当前作用域',404)
  if base!=row['version']:return err('VERSION_CONFLICT','客户版本冲突',409,currentVersion=row['version'])
  status_count=0
  for tid0 in ids:
   tid=str(tid0)
   if tid in clean:continue
   tag=c.execute('SELECT tag_kind FROM tags WHERE workspace_id=? AND tag_id=? AND enabled=1',(a['workspace_id'],tid)).fetchone()
   if not tag:return err('TAG_NOT_FOUND','标签不存在或已停用',404,tagId=tid)
   status_count+=tag['tag_kind']=='status';clean.append(tid)
  if status_count>1:return err('MULTIPLE_STATUS_TAGS','状态标签最多选择一个',409)
  old=[x[0] for x in c.execute('SELECT tag_id FROM contact_tags WHERE contact_id=?',(cid,))];n=now_ms()
  c.execute('DELETE FROM contact_tags WHERE contact_id=?',(cid,))
  for tid in clean:c.execute('INSERT INTO contact_tags(contact_id,tag_id,created_at) VALUES(?,?,?)',(cid,tid,n))
  ver=base+1;c.execute('UPDATE contacts SET version=?,updated_at=? WHERE contact_id=?',(ver,n,cid));_audit(c,a,'interaction-tags',cid,{'tagIds':old},{'tagIds':clean},'聊天面板标签更新')
  return ok(version=ver,tagIds=clean)
