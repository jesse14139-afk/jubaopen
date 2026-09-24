# -*- coding: utf-8 -*-
"""V208 会话读取、原文审计和正文删除。"""
from V207_shared_db import now_ms,dumps
from V208_privacy import public_message

def err(c,m,s=400):return ({'ok':False,'code':c,'message':m},s)
def list_messages(db,a,conversation_id,limit=100,before=None,allow_raw=False):
 limit=min(max(int(limit),1),500);params=[conversation_id,a['organization_id'],a['workspace_id'],a['team_id']];extra=''
 if before:extra=' AND m.occurred_at<?';params.append(int(before))
 params.append(limit)
 with db.tx(allow_raw) as c:
  v=c.execute('SELECT * FROM conversations WHERE conversation_id=? AND organization_id=? AND workspace_id=? AND team_id=?',tuple(params[:4])).fetchone()
  if not v:return err('CONVERSATION_SCOPE_INVALID','会话不存在或无权访问',404)
  rows=c.execute('SELECT m.* FROM conversation_messages m WHERE m.conversation_id=?'+extra+' ORDER BY m.occurred_at DESC,m.message_id DESC LIMIT ?',tuple([conversation_id]+params[4:])).fetchall()
  if allow_raw:c.execute("INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at,organization_id,team_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(a['workspace_id'],a['user_id'],a.get('device_id'),'message.read.raw','conversation',conversation_id,'{}','{}','查看消息原文',now_ms(),a['organization_id'],a['team_id']))
  return ({'ok':True,'items':[public_message(x,allow_raw) for x in rows]},200)
def delete_content(db,a,message_id,reason):
 reason=str(reason or '').strip()
 if not reason:return err('REASON_REQUIRED','删除正文必须填写原因')
 with db.tx() as c:
  m=c.execute('SELECT * FROM conversation_messages WHERE message_id=? AND organization_id=? AND workspace_id=? AND team_id=?',(message_id,a['organization_id'],a['workspace_id'],a['team_id'])).fetchone()
  if not m:return err('MESSAGE_SCOPE_INVALID','消息不存在或无权访问',404)
  if m['content_deleted_at'] is not None:return err('CONTENT_ALREADY_DELETED','消息正文已经删除',409)
  n=now_ms();c.execute("UPDATE conversation_messages SET text_content=NULL,redacted_text=NULL,status='content_deleted',content_deleted_at=?,content_deleted_by=?,content_delete_reason=? WHERE message_id=?",(n,a['user_id'],reason,message_id))
  c.execute("INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at,organization_id,team_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(a['workspace_id'],a['user_id'],a.get('device_id'),'message.delete.content','message',message_id,dumps({'hadText':m['text_content'] is not None}),dumps({'status':'content_deleted'}),reason,n,a['organization_id'],a['team_id']))
  return ({'ok':True,'messageId':message_id,'contentDeletedAt':n},200)
