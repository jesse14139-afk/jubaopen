# -*- coding: utf-8 -*-
"""V208 客户转移服务：创建受作用域、账号授权与重复请求约束的待处理转移。"""
import uuid
from V207_shared_db import now_ms,dumps

def _err(code,message,status=400):
 return ({'ok':False,'code':code,'message':message},status)

def create_transfer(db,a,cid,p):
 to=str(p.get('toChannelAccountId') or '').strip()
 source=str(p.get('fromChannelAccountId') or '').strip() or None
 conversation=str(p.get('fromConversationId') or '').strip() or None
 method=str(p.get('transferMethod') or 'other').strip()
 reason=str(p.get('reason') or '').strip()
 allowed=('phone_shared','username_shared','invite_link','qr_code','manual_link','system_match','other')
 if not to or method not in allowed:return _err('INVALID_TRANSFER','转移参数无效')
 if len(reason)>1000:return _err('TRANSFER_REASON_TOO_LONG','转移原因不能超过 1000 个字符')
 if source and source==to:return _err('TRANSFER_TARGET_SAME','目标账号不能与来源账号相同',409)
 with db.tx() as c:
  ct=c.execute("SELECT 1 FROM contacts WHERE contact_id=? AND organization_id=? AND workspace_id=? AND team_id=? AND deleted_at IS NULL",(cid,a['organization_id'],a['workspace_id'],a['team_id'])).fetchone()
  if not ct:return _err('CONTACT_SCOPE_INVALID','客户不存在、已删除或不属于当前作用域',404)
  # 与账号列表接口保持同一授权口径：团队授权 + 当前用户授权（或平台管理员）。
  acc=c.execute("""SELECT 1 FROM channel_accounts x
   JOIN team_channel_accounts t ON t.channel_account_id=x.channel_account_id AND t.team_id=?
   WHERE x.channel_account_id=? AND x.organization_id=? AND x.status='active' AND x.collection_enabled=1
   AND (EXISTS(SELECT 1 FROM user_channel_account_grants g WHERE g.channel_account_id=x.channel_account_id AND g.user_id=?)
        OR EXISTS(SELECT 1 FROM platform_administrators pa WHERE pa.user_id=?))""",
   (a['team_id'],to,a['organization_id'],a['user_id'],a['user_id'])).fetchone()
  if not acc:return _err('TRANSFER_TARGET_UNAUTHORIZED','目标账号不存在或当前用户无权使用',403)
  if conversation:
   conv=c.execute("SELECT channel_account_id FROM conversations WHERE conversation_id=? AND contact_id=? AND organization_id=? AND workspace_id=? AND team_id=?",(conversation,cid,a['organization_id'],a['workspace_id'],a['team_id'])).fetchone()
   if not conv:return _err('TRANSFER_SOURCE_INVALID','来源会话不属于当前客户',403)
   if source and conv['channel_account_id']!=source:return _err('TRANSFER_SOURCE_INVALID','来源账号与来源会话不一致',409)
   source=conv['channel_account_id']
  elif source:
   conv=c.execute("SELECT 1 FROM conversations WHERE contact_id=? AND channel_account_id=? AND organization_id=? AND workspace_id=? AND team_id=?",(cid,source,a['organization_id'],a['workspace_id'],a['team_id'])).fetchone()
   if not conv:return _err('TRANSFER_SOURCE_INVALID','来源账号不属于当前客户会话',403)
  if source==to:return _err('TRANSFER_TARGET_SAME','目标账号不能与来源账号相同',409)
  duplicate=c.execute("SELECT transfer_id FROM contact_transfers WHERE contact_id=? AND to_channel_account_id=? AND status='pending' LIMIT 1",(cid,to)).fetchone()
  if duplicate:return ({'ok':False,'code':'TRANSFER_PENDING_EXISTS','message':'该客户到此目标账号已有待处理转移','transferId':duplicate['transfer_id']},409)
  n=now_ms();tid='trf_'+uuid.uuid4().hex
  c.execute("INSERT INTO contact_transfers(transfer_id,organization_id,workspace_id,team_id,contact_id,from_channel_account_id,from_conversation_id,to_channel_account_id,to_conversation_id,transfer_method,status,transferred_by,transferred_at,reason,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,'pending',?,?,?,?,?,?)",(tid,a['organization_id'],a['workspace_id'],a['team_id'],cid,source,conversation,to,p.get('toConversationId'),method,a['user_id'],n,reason,dumps(p.get('metadata') or {}),n,n))
  return ({'ok':True,'transferId':tid,'status':'pending'},201)
