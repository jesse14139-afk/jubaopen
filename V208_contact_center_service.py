# -*- coding: utf-8 -*-
"""JubaOpen 客户管理中心。

只使用当前正式数据模型；不包含油猴字段、旧数据迁移或兼容逻辑。
"""
import json
import sqlite3
import logging
import re
import uuid
from V208_privacy import redact_text
from V207_shared_db import now_ms, dumps, loads
from V207_security import data_scope_clause_in_tx,can, is_platform_admin
from V221_identity_service import handle_admin as handle_identity_admin
from V208_follow_up_notification_service import FollowUpPlanConflict,sync_follow_up_plan_in_tx,poll_notifications,receipt_action,list_notifications,notification_summary,notification_subscription_settings,save_notification_subscriptions
from V208_conversation_service import (list_conversations, get_conversation, list_messages,
 transition_conversation, list_contact_timeline, delete_content, recollect_conversation)
from V208_transfer_service import create_transfer, get_transfer, list_transfers, transition_transfer, transfer_meta

STAGE_KEYS=('communication_stage','intention_stage','conversion_stage')
SORTS={
 'updated_at':'c.updated_at','created_at':'c.created_at','last_seen_at':'c.last_seen_at',
 'last_observed_at':'c.last_observed_at','last_touch_at':'c.last_touch_at',
 'next_follow_up_at':'c.next_follow_up_at','name':"COALESCE(NULLIF(trim(c.manual_name),''),c.display_name)",
 'status':"COALESCE(c.lifecycle_status,'')",'portrait':"(SELECT count(*) FROM contact_tags cst WHERE cst.contact_id=c.contact_id)",
 'progress':"COALESCE((SELECT fv.value_json FROM contact_custom_values fv WHERE fv.contact_id=c.contact_id AND fv.field_key IN ('communication_stage','intention_stage','conversion_stage','customer_stage','purchase_intent','follow_up_stage') ORDER BY fv.field_key LIMIT 1),'')",
 'channel':"COALESCE((SELECT p2.platform_name FROM contact_identities ci2 LEFT JOIN platforms p2 ON p2.platform_id=ci2.platform_id WHERE ci2.contact_id=c.contact_id ORDER BY ci2.is_primary DESC,ci2.last_seen_at DESC LIMIT 1),'')",
 'device':"COALESCE((SELECT d2.device_name FROM devices d2 WHERE d2.device_id=c.last_observed_device_id),'')",
 'owner':"COALESCE((SELECT u2.display_name FROM users u2 WHERE u2.user_id=c.owner_user_id),'')",
 'source':"COALESCE((SELECT s2.source_name FROM sources s2 WHERE s2.source_id=c.source_id),'')"
}


# Contact-center field semantics. field_role is authoritative; legacy keys remain compatible.
STAGE_LEGACY_KEYS = frozenset(("purchase_intent", "customer_stage", "follow_up_stage"))
SUPPORTED_CUSTOM_FIELD_TYPES = frozenset(("text", "single_select", "multi_select", "boolean", "number", "date", "json"))
MAX_TIMESTAMP_MS=253402300799999
LOGGER=logging.getLogger(__name__)

def _business(value):
 try:
  out=loads(value or '{}')
  return out if isinstance(out,dict) else {}
 except Exception:return {}

def _followup_reason(row):
 return str(_business((row or {}).get('business_json')).get('nextFollowUpReason') or '')[:500]

def _field_key(definition):
    return str((definition or {}).get("field_key") or (definition or {}).get("fieldKey") or "").strip()

def _field_role(definition):
    d = definition or {}
    key = _field_key(d)
    role = str(d.get("field_role") or d.get("fieldRole") or "").strip().lower()
    if role == "custom":
        return "custom"
    if role in ("stage", "progress") or role.startswith("stage_") or key in STAGE_LEGACY_KEYS:
        return "stage"
    # Existing rows created before field_role was introduced are business fields.
    return "custom"

def _is_stage_definition(definition):
    return _field_role(definition) == "stage"

def _is_custom_definition(definition):
    return _field_role(definition) == "custom"

def _definition_signature(definition):
    d = definition or {}
    options = d.get("options")
    if isinstance(options, str):
        try: options = json.loads(options)
        except Exception: pass
    return (str(d.get("field_type") or d.get("fieldType") or "text").lower(),
            str(d.get("label") or d.get("field_label") or d.get("fieldLabel") or ""),
            json.dumps(options if options is not None else [], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            _field_role(d))

def _column_key(definition, conflicted=False):
    key = _field_key(definition)
    workspace_id = definition.get("workspace_id") if definition else None
    return "custom:%s:%s" % (workspace_id, key) if conflicted else "custom:%s" % key

def _row_permissions(actor, contact, can_full, can_assigned, can_read_management=False):
    can_update = not contact.get("deleted_at") and _can_update_contact(actor, contact, can_full, can_assigned)
    return {
        "canUpdate": bool(can_update),
        "canUpdateBasic": bool(can_update),
        "canUpdateStatus": bool(can_update),
        "canUpdatePortrait": bool(can_update),
        "canUpdateStages": bool(can_update),
        "canUpdateCustomFields": bool(can_update),
        "canUpdateNextFollowUpAt": bool(can_update),
        "canReadManagementFields": bool(can_read_management),
    }

def _secure_contact_payload(payload, actor, can_full, can_assigned, can_read_management=False):
    def visit(value):
        if isinstance(value, list):
            for item in value: visit(item)
        elif isinstance(value, dict):
            looks_contact = "id" in value and ("workspace_id" in value or "workspaceId" in value or "baseVersion" in value or "version" in value)
            if looks_contact:
                value["permissions"] = _row_permissions(actor, value, can_full, can_assigned, can_read_management)
                if not can_read_management:
                    _strip_management_fields(value)
            for key in ("items", "contacts", "data", "contact"):
                child=value.get(key)
                if child is not None and child is not value: visit(child)
        return value
    return visit(payload)

def _strip_management_fields(contact):
    for key in ("source", "source_name", "sourceName"):
        contact.pop(key, None)
    return contact

def _rows(c,sql,args=()):return [dict(x) for x in c.execute(sql,args)]
def _one(c,sql,args=()):
 x=c.execute(sql,args).fetchone();return dict(x) if x else None
def _send(h,obj,status=200):return h.sendj(obj,status) or True
def _bad(h,code,message,status=400):return _send(h,{'ok':False,'code':code,'message':message},status)
def _int(v,default,lo=None,hi=None):
 try:x=int(v)
 except (TypeError,ValueError):x=default
 if lo is not None:x=max(lo,x)
 if hi is not None:x=min(hi,x)
 return x
def _strict_version(value):
 return value if not isinstance(value,bool) and isinstance(value,int) and value>=0 else None

def _valid_followup(value):
 return value is None or (not isinstance(value,bool) and isinstance(value,int) and 0<=value<=MAX_TIMESTAMP_MS)

def _empty_value(definition,value):
 typ=str((definition or {}).get('field_type') or 'text').lower()
 return value is None or (typ in ('text','single_select','date') and value=='') or (typ=='multi_select' and value==[])

def _json(v,default=None):
 try:return loads(v) if isinstance(v,str) else v
 except Exception:return default

def _platform(c,actor):
 try:return bool(c.execute('SELECT 1 FROM platform_administrators WHERE user_id=? LIMIT 1',(actor['user_id'],)).fetchone())
 except Exception:return False

def _can_any_scope(db,actor,permission,org):
 """Return whether an actor has a permission in any active RBAC scope in this organization."""
 if not actor or actor.get('organization_id')!=org:return False
 if is_platform_admin(db,actor):return True
 with db.tx(False) as c:
  bindings=_rows(c,"""SELECT DISTINCT b.scope_type,b.scope_id
   FROM role_bindings b
   JOIN roles r ON r.role_id=b.role_id AND r.status='active'
   JOIN role_permissions rp ON rp.role_id=b.role_id
   JOIN permissions p ON p.permission_key=rp.permission_key
   WHERE b.user_id=? AND b.organization_id=? AND b.status='active' AND rp.permission_key=?""",
   (actor['user_id'],org,permission))
 for b in bindings:
  typ,sid=b['scope_type'],b['scope_id']
  kw={'organization_id':org}
  if typ=='organization':pass
  elif typ=='workspace':kw['workspace_id']=sid
  elif typ=='department':kw['department_id']=sid
  elif typ=='team':kw['team_id']=sid
  elif typ=='self':kw['resource_user_id']=sid
  else:continue
  if can(db,actor,permission,**kw):return True
 return False

def _scope(c,actor,alias='c'):
 """Fail-closed contact rows derived from effective contact.read role bindings."""
 clause,args,info=data_scope_clause_in_tx(c,actor,'contact.read',actor['organization_id'],alias=alias)
 return clause,args,info['level']

def _allowed(c,actor,org,cid,include_deleted=False):
 scope,sp,_=_scope(c,actor)
 deleted='' if include_deleted else ' AND c.deleted_at IS NULL'
 return _one(c,f'SELECT c.* FROM contacts c WHERE c.organization_id=? AND c.contact_id=?{deleted} AND {scope}',[org,cid]+sp)

def _audit(c,actor,contact,before,after,operation,reason):
 c.execute("INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at,organization_id,team_id,scope_type,scope_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
  (contact['workspace_id'],actor['user_id'],None,operation,'contact',contact['contact_id'],dumps(before or {}),dumps(after or {}),str(reason or '').strip()[:500],now_ms(),contact['organization_id'],contact.get('team_id'),'workspace',contact['workspace_id']))
def _raw_definitions(c,workspace_ids):
 if not workspace_ids:return []
 marks=','.join('?' for _ in workspace_ids)
 out=_rows(c,f"SELECT workspace_id,field_key,label,field_type,sort_order,field_role,display_zone,is_quick_edit,options_json,placeholder FROM custom_field_definitions WHERE enabled=1 AND workspace_id IN ({marks}) ORDER BY sort_order,field_key",workspace_ids)
 for x in out:x['options']=_json(x.pop('options_json','[]'),[]) or []
 return out

def _definitions(c,workspace_ids):
 raw=_raw_definitions(c,workspace_ids)
 grouped={}
 for x in raw:grouped.setdefault(x['field_key'],[]).append(x)
 out=[]
 for key,items in grouped.items():
  signatures={_definition_signature(x) for x in items}
  if len(signatures)==1:
   x=dict(items[0]);x['columnKey']='custom:'+key;x['workspaceIds']=[i['workspace_id'] for i in items];x['definitionConflict']=False;x.pop('workspace_id',None);out.append(x)
  else:
   for item in items:
    x=dict(item);wid=x.pop('workspace_id');x['workspaceId']=wid;x['workspaceIds']=[wid];x['columnKey']='custom:'+wid+':'+key;x['definitionConflict']=True;out.append(x)
 return sorted(out,key=lambda x:(int(x.get('sort_order') or 0),x.get('field_key') or '',x.get('workspaceId') or ''))

def _filters(q):
 clauses=[];args=[]
 mapping={'workspace_id':'workspace_id','team_id':'team_id','owner_user_id':'owner_user_id','source_id':'source_id','last_observed_device_id':'last_observed_device_id'}
 for key,col in mapping.items():
  v=str(q.get(key) or q.get(''.join([key.split('_')[0]]+[p.title() for p in key.split('_')[1:]])) or '').strip()
  if v:clauses.append(f'c.{col}=?');args.append(v)
 deleted=str(q.get('deleted') or 'no').lower()
 if deleted in ('only','yes','1','true','deleted'):clauses.append('c.deleted_at IS NOT NULL')
 elif deleted not in ('all','any'):clauses.append('c.deleted_at IS NULL')
 platform=str(q.get('platform_id') or '').strip()
 if platform:clauses.append("EXISTS(SELECT 1 FROM contact_identities fi WHERE fi.contact_id=c.contact_id AND fi.platform_id=?)");args.append(platform)
 account=str(q.get('channel_account_id') or '').strip()
 if account:
  clauses.append("(EXISTS(SELECT 1 FROM conversations fv WHERE fv.contact_id=c.contact_id AND fv.channel_account_id=?) OR EXISTS(SELECT 1 FROM sources fs WHERE fs.source_id=c.source_id AND fs.channel_account_id=?))");args.extend([account,account])
 status=str(q.get('status_tag_id') or '').strip()
 if status:
  if status=='__unset__':clauses.append("NOT EXISTS(SELECT 1 FROM contact_tags ft JOIN tags tg ON tg.tag_id=ft.tag_id WHERE ft.contact_id=c.contact_id AND tg.tag_kind='status' AND tg.enabled=1)")
  else:clauses.append("EXISTS(SELECT 1 FROM contact_tags ft JOIN tags tg ON tg.tag_id=ft.tag_id WHERE ft.contact_id=c.contact_id AND tg.tag_kind='status' AND tg.enabled=1 AND tg.tag_id=?)");args.append(status)
 portrait=str(q.get('portrait_tag_id') or q.get('persona_tag_id') or '').strip()
 if portrait:clauses.append("EXISTS(SELECT 1 FROM contact_tags ft JOIN tags tg ON tg.tag_id=ft.tag_id WHERE ft.contact_id=c.contact_id AND tg.tag_kind='portrait' AND tg.enabled=1 AND tg.tag_id=?)");args.append(portrait)
 for key in STAGE_KEYS:
  v=str(q.get(key) or '').strip()
  if v:clauses.append("EXISTS(SELECT 1 FROM contact_custom_values fv WHERE fv.contact_id=c.contact_id AND fv.field_key=? AND fv.value_json=?)");args.extend([key,dumps(v)])
 for key,col in (('updated_from','updated_at'),('last_seen_from','last_seen_at'),('next_follow_up_from','next_follow_up_at')):
  if str(q.get(key) or '').strip():clauses.append(f'c.{col}>=?');args.append(_int(q.get(key),0,0))
 for key,col in (('updated_to','updated_at'),('last_seen_to','last_seen_at'),('next_follow_up_to','next_follow_up_at')):
  if str(q.get(key) or '').strip():clauses.append(f'c.{col}<=?');args.append(_int(q.get(key),0,0))
 term=str(q.get('q') or '').strip()
 if term:
  like='%'+term+'%'
  clauses.append("(c.contact_id LIKE ? OR c.manual_name LIKE ? OR c.display_name LIKE ? OR c.manual_phone LIKE ? OR c.observed_phone LIKE ? OR EXISTS(SELECT 1 FROM contact_identities qi WHERE qi.contact_id=c.contact_id AND (qi.identity_value LIKE ? OR qi.canonical_value LIKE ?)) OR EXISTS(SELECT 1 FROM conversations qv JOIN channel_accounts qa ON qa.channel_account_id=qv.channel_account_id WHERE qv.contact_id=c.contact_id AND qa.display_name LIKE ?) OR EXISTS(SELECT 1 FROM sources qs WHERE qs.source_id=c.source_id AND qs.source_name LIKE ?) OR EXISTS(SELECT 1 FROM contact_custom_values qcv WHERE qcv.contact_id=c.contact_id AND qcv.value_json LIKE ?))")
  args.extend([like]*10)
 return clauses,args

def _device_dto(x):
 if not x.get('last_observed_device_id'):return None
 sources={'admin':x.get('admin_device_name'),'user':x.get('user_device_alias'),'system':x.get('system_device_name'),'raw':x.get('raw_device_name')}
 source=next((k for k in ('admin','user','system','raw') if sources.get(k)), 'id')
 return {'id':x['last_observed_device_id'],'installationId':x.get('device_installation_id'),'status':x.get('device_status'),'firstSeenAt':x.get('device_first_seen_at'),'lastSeenAt':x.get('device_last_seen_at'),'name':x.get('device_name') or x['last_observed_device_id'],'nameSource':source,'names':sources}


def _trim_management(item,can_read_device_details=False):
 # Channel account and the device display name are part of the default business view.
 # Ownership, attribution source and workspace are management-only.
 for key in ('source',):item.pop(key,None)
 workspace=item.get('workspace')
 if isinstance(workspace,dict):item['workspace']={'id':workspace.get('id')}
 for touchpoint in item.get('touchpoints') or []:
  if isinstance(touchpoint,dict):touchpoint.pop('sourceName',None)
 device=item.get('lastObservedDevice')
 if isinstance(device,dict) and not can_read_device_details:
  item['lastObservedDevice']={'name':device.get('name'),'lastSeenAt':device.get('lastSeenAt')}
 return item

def _domain_permission(db,actor,contact,permission,full,assigned,platform=False):
 if not _can_update_contact(actor,contact,full,assigned):return False
 if platform:return True
 ctx={'workspace_id':contact.get('workspace_id'),'team_id':contact.get('team_id'),'resource_user_id':contact.get('owner_user_id'),'organization_id':contact.get('organization_id')}
 # Dedicated permissions are honored when configured; legacy installations fall back to contact.update.
 return bool(can(db,actor,permission,**ctx) or full or assigned)

def _enrich(c,base,field_keys=None,column_definitions=None,raw_definitions=None):
 if not base:return []
 ids=[x['contact_id'] for x in base];marks=','.join('?' for _ in ids)
 tags=_rows(c,f"SELECT ct.contact_id,t.tag_id,t.name,t.color,t.tag_kind FROM contact_tags ct JOIN tags t ON t.tag_id=ct.tag_id WHERE ct.contact_id IN ({marks}) AND t.enabled=1 ORDER BY t.sort_order,t.name",ids)
 by_tags={x:[] for x in ids}
 for x in tags:by_tags[x['contact_id']].append(x)
 field_sql=f"SELECT contact_id,field_key,value_json FROM contact_custom_values WHERE contact_id IN ({marks})";fargs=list(ids)
 if field_keys:
  km=','.join('?' for _ in field_keys);field_sql+=f' AND field_key IN ({km})';fargs+=field_keys
 vals=_rows(c,field_sql,fargs);by_vals={x:{} for x in ids}
 for x in vals:by_vals[x['contact_id']][x['field_key']]=_json(x['value_json'])
 role_by_workspace={}
 for d in raw_definitions or []:role_by_workspace[(d['workspace_id'],d['field_key'])]=_field_role(d)
 columns=column_definitions or []
 out=[]
 for x in base:
  cid=x['contact_id'];wid=x['workspace_id'];values=by_vals[cid];ts=by_tags[cid];st=next((t for t in ts if t['tag_kind']=='status'),None);por=[t for t in ts if t['tag_kind']=='portrait']
  stage_values={k:v for k,v in values.items() if role_by_workspace.get((wid,k),'stage' if k in STAGE_KEYS else 'custom')=='stage'}
  custom_values={k:v for k,v in values.items() if role_by_workspace.get((wid,k),'stage' if k in STAGE_KEYS else 'custom')=='custom'}
  field_cells={}
  for d in columns:
   column_key=d['columnKey'];applicable=wid in (d.get('workspaceIds') or [])
   if not applicable:field_cells[column_key]={'applicable':False,'state':'unavailable'};continue
   key=d['field_key'];value=values.get(key);has_value=key in values and value is not None and value!='' and value!=[]
   field_cells[column_key]={'applicable':True,'state':'value' if has_value else 'empty','value':value if key in values else None}
  item={
   'contactId':cid,'version':x['version'],'systemStatus':x['status'],'deletedAt':x['deleted_at'],
   'avatarUrl':x['avatar_url'],'manualName':x['manual_name'],'observedName':x['display_name'],
   'manualPhone':x['manual_phone'],'observedPhone':x['observed_phone'],'remark':x['remark'],
   'platform':({'id':x['platform_id'],'code':x['platform_code'],'abbr':x['platform_abbr'] or (x['platform_code'] or x['channel'] or '').upper(),'name':x['platform_name']} if x['platform_id'] or x['platform_code'] else {'id':None,'code':x['channel'],'abbr':(x['channel'] or '').upper(),'name':x['channel']}),
   'primaryIdentity':({'id':x['identity_id'],'type':x['identity_type'],'value':x['identity_value'],'canonicalValue':x['canonical_value'],'verificationStatus':x['verification_status'],'firstSeenAt':x['identity_first_seen_at'],'lastSeenAt':x['identity_last_seen_at']} if x['identity_id'] else None),
   'identityCount':x['identity_count'] or 0,'statusTag':({'id':st['tag_id'],'name':st['name'],'color':st['color']} if st else None),
   'portraitTags':[{'id':t['tag_id'],'name':t['name'],'color':t['color']} for t in por],
   'stages':stage_values,'customValues':custom_values,'fieldCells':field_cells,
   'owner':{'id':x['owner_user_id'],'name':x['owner_name']} if x['owner_user_id'] else None,
   'workspace':{'id':wid,'name':x['workspace_name']},'team':{'id':x['team_id'],'name':x['team_name']} if x['team_id'] else None,
   'source':{'id':x['source_id'],'name':x['source_name']} if x['source_id'] else None,
   'channelAccount':({'id':x['channel_account_id'],'name':x['channel_account_name']} if x['channel_account_id'] else None),
   'channelPlatform':({'id':x['channel_platform_id'],'code':x['channel_platform_code'],'abbr':x['channel_platform_abbr'] or (x['channel_platform_code'] or '').upper(),'name':x['channel_platform_name']} if x['channel_platform_id'] else None),
   'recentConversation':({'id':x['recent_conversation_id'],'status':x['recent_conversation_status'],'lastMessageAt':x['recent_message_at']} if x['recent_conversation_id'] else None),
   'channelBasis':'recentConversation' if x['recent_conversation_id'] else ('sourceBinding' if x['channel_account_id'] else ('primaryIdentity' if x['identity_id'] else None)),
   'lastObservedDevice':_device_dto(x),
   'nextFollowUpAt':x['next_follow_up_at'],'nextFollowUpReason':_followup_reason(x),'lastOutboundAt':x.get('last_outbound_at'),'followUpCompleted':bool(x.get('next_follow_up_at') and x.get('last_outbound_at') and int(x.get('last_outbound_at'))>=int(x.get('next_follow_up_at'))),'followUpCompletedAt':(x.get('last_outbound_at') if x.get('next_follow_up_at') and x.get('last_outbound_at') and int(x.get('last_outbound_at'))>=int(x.get('next_follow_up_at')) else None),'lastObservedAt':x['last_observed_at'],'lastSeenAt':x['last_seen_at'],'lastTouchAt':x['last_touch_at'],'createdAt':x['created_at'],'updatedAt':x['updated_at']
  };out.append(item)
 return out

BASE_SELECT="""SELECT c.*,
 w.name workspace_name,t.name team_name,u.display_name owner_name,s.source_name,
 d.admin_device_name,d.user_device_alias,d.system_device_name,d.device_name raw_device_name,
 d.installation_id device_installation_id,d.status device_status,d.first_seen_at device_first_seen_at,d.last_seen_at device_last_seen_at,
 COALESCE(NULLIF(d.admin_device_name,''),NULLIF(d.user_device_alias,''),NULLIF(d.system_device_name,''),NULLIF(d.device_name,''),d.device_id) device_name,
 pi.contact_identity_id identity_id,pi.identity_type,pi.identity_value,pi.canonical_value,pi.verification_status,pi.first_seen_at identity_first_seen_at,pi.last_seen_at identity_last_seen_at,pi.platform_id,
 p.platform_code,p.platform_name,p.platform_abbr,
 (SELECT MAX(COALESCE(cm.occurred_at,cm.collected_at)) FROM conversation_messages cm WHERE cm.contact_id=c.contact_id AND cm.direction='outbound' AND cm.sender_type='agent' AND cm.status='active') last_outbound_at,
 (SELECT count(*) FROM contact_identities ic WHERE ic.contact_id=c.contact_id) identity_count,
 COALESCE((SELECT v.channel_account_id FROM conversations v WHERE v.contact_id=c.contact_id ORDER BY COALESCE(v.last_message_at,0) DESC,COALESCE(v.last_collected_at,0) DESC,v.updated_at DESC LIMIT 1),s.channel_account_id) channel_account_id,
 (SELECT ca.display_name FROM channel_accounts ca WHERE ca.channel_account_id=COALESCE((SELECT v.channel_account_id FROM conversations v WHERE v.contact_id=c.contact_id ORDER BY COALESCE(v.last_message_at,0) DESC,COALESCE(v.last_collected_at,0) DESC,v.updated_at DESC LIMIT 1),s.channel_account_id)) channel_account_name,
 (SELECT v.conversation_id FROM conversations v WHERE v.contact_id=c.contact_id ORDER BY COALESCE(v.last_message_at,0) DESC,COALESCE(v.last_collected_at,0) DESC,v.updated_at DESC LIMIT 1) recent_conversation_id,
 (SELECT v.status FROM conversations v WHERE v.contact_id=c.contact_id ORDER BY COALESCE(v.last_message_at,0) DESC,COALESCE(v.last_collected_at,0) DESC,v.updated_at DESC LIMIT 1) recent_conversation_status,
 (SELECT v.last_message_at FROM conversations v WHERE v.contact_id=c.contact_id ORDER BY COALESCE(v.last_message_at,0) DESC,COALESCE(v.last_collected_at,0) DESC,v.updated_at DESC LIMIT 1) recent_message_at,
 COALESCE((SELECT v.platform_id FROM conversations v WHERE v.contact_id=c.contact_id ORDER BY COALESCE(v.last_message_at,0) DESC,COALESCE(v.last_collected_at,0) DESC,v.updated_at DESC LIMIT 1),(SELECT ca.platform_id FROM channel_accounts ca WHERE ca.channel_account_id=COALESCE((SELECT v.channel_account_id FROM conversations v WHERE v.contact_id=c.contact_id ORDER BY COALESCE(v.last_message_at,0) DESC,COALESCE(v.last_collected_at,0) DESC,v.updated_at DESC LIMIT 1),s.channel_account_id))) channel_platform_id,
 (SELECT pp.platform_code FROM platforms pp WHERE pp.platform_id=COALESCE((SELECT v.platform_id FROM conversations v WHERE v.contact_id=c.contact_id ORDER BY COALESCE(v.last_message_at,0) DESC,COALESCE(v.last_collected_at,0) DESC,v.updated_at DESC LIMIT 1),(SELECT ca.platform_id FROM channel_accounts ca WHERE ca.channel_account_id=COALESCE((SELECT v.channel_account_id FROM conversations v WHERE v.contact_id=c.contact_id ORDER BY COALESCE(v.last_message_at,0) DESC,COALESCE(v.last_collected_at,0) DESC,v.updated_at DESC LIMIT 1),s.channel_account_id)))) channel_platform_code,
 (SELECT pp.platform_abbr FROM platforms pp WHERE pp.platform_id=COALESCE((SELECT v.platform_id FROM conversations v WHERE v.contact_id=c.contact_id ORDER BY COALESCE(v.last_message_at,0) DESC,COALESCE(v.last_collected_at,0) DESC,v.updated_at DESC LIMIT 1),(SELECT ca.platform_id FROM channel_accounts ca WHERE ca.channel_account_id=COALESCE((SELECT v.channel_account_id FROM conversations v WHERE v.contact_id=c.contact_id ORDER BY COALESCE(v.last_message_at,0) DESC,COALESCE(v.last_collected_at,0) DESC,v.updated_at DESC LIMIT 1),s.channel_account_id)))) channel_platform_abbr,
 (SELECT pp.platform_name FROM platforms pp WHERE pp.platform_id=COALESCE((SELECT v.platform_id FROM conversations v WHERE v.contact_id=c.contact_id ORDER BY COALESCE(v.last_message_at,0) DESC,COALESCE(v.last_collected_at,0) DESC,v.updated_at DESC LIMIT 1),(SELECT ca.platform_id FROM channel_accounts ca WHERE ca.channel_account_id=COALESCE((SELECT v.channel_account_id FROM conversations v WHERE v.contact_id=c.contact_id ORDER BY COALESCE(v.last_message_at,0) DESC,COALESCE(v.last_collected_at,0) DESC,v.updated_at DESC LIMIT 1),s.channel_account_id)))) channel_platform_name
 FROM contacts c
 LEFT JOIN workspaces w ON w.workspace_id=c.workspace_id LEFT JOIN teams t ON t.team_id=c.team_id
 LEFT JOIN users u ON u.user_id=c.owner_user_id LEFT JOIN sources s ON s.source_id=c.source_id
 LEFT JOIN devices d ON d.device_id=c.last_observed_device_id
 LEFT JOIN contact_identities pi ON pi.contact_identity_id=(SELECT ii.contact_identity_id FROM contact_identities ii WHERE ii.contact_id=c.contact_id ORDER BY ii.is_primary DESC,ii.last_seen_at DESC,ii.contact_identity_id LIMIT 1)
 LEFT JOIN platforms p ON p.platform_id=pi.platform_id"""

def meta(db,actor,org):
 is_platform=is_platform_admin(db,actor)
 can_update=is_platform or _can_any_scope(db,actor,'contact.update',org) or _can_any_scope(db,actor,'contact.update.assigned',org)
 can_export=is_platform or _can_any_scope(db,actor,'contact.export',org)
 can_read_management=is_platform or _can_any_scope(db,actor,'contact.management.read',org)
 can_read_device_details=is_platform or _can_any_scope(db,actor,'device.read',org)
 can_read_sensitive=is_platform or _can_any_scope(db,actor,'pii.read.full',org)
 can_read_accounts=is_platform or _can_any_scope(db,actor,'account.read',org)
 can_read_audit=is_platform or _can_any_scope(db,actor,'audit.read',org)
 can_read_messages=is_platform or any(_can_any_scope(db,actor,p,org) for p in ('message.read.raw','message.read.team','message.read.self'))
 can_link_identity=is_platform or _can_any_scope(db,actor,'contact.identity.link',org)
 can_review_duplicate=is_platform or _can_any_scope(db,actor,'contact.duplicate.review',org)
 can_merge_contact=is_platform or _can_any_scope(db,actor,'contact.merge',org)
 can_team_access=is_platform or _can_any_scope(db,actor,'contact.team_access',org)
 can_delete_contact=is_platform or _can_any_scope(db,actor,'contact.delete',org)
 with db.tx(False) as c:
  scope,sp,scope_name=_scope(c,actor)
  visible="c.organization_id=?" if is_platform else "c.organization_id=? AND ("+scope+")"
  va=[org] if is_platform else [org]+sp
  workspaces=_rows(c,"SELECT workspace_id id,name FROM workspaces WHERE organization_id=? AND status='active' AND workspace_id IN (SELECT DISTINCT c.workspace_id FROM contacts c WHERE "+visible+") ORDER BY name",[org]+va)
  teams=_rows(c,"SELECT team_id id,name,workspace_id workspaceId FROM teams WHERE organization_id=? AND status='active' AND team_id IN (SELECT DISTINCT c.team_id FROM contacts c WHERE "+visible+" AND c.team_id IS NOT NULL) ORDER BY name",[org]+va)
  owners=_rows(c,"SELECT user_id id,display_name name FROM users WHERE organization_id=? AND status='active' AND user_id IN (SELECT DISTINCT c.owner_user_id FROM contacts c WHERE "+visible+" AND c.owner_user_id IS NOT NULL) ORDER BY display_name",[org]+va)
  sources=_rows(c,"SELECT source_id id,source_name name,workspace_id workspaceId,team_id teamId FROM sources WHERE organization_id=? AND status='active' AND source_id IN (SELECT DISTINCT c.source_id FROM contacts c WHERE "+visible+" AND c.source_id IS NOT NULL) ORDER BY source_name",[org]+va)
  devices=_rows(c,"SELECT device_id id,COALESCE(NULLIF(admin_device_name,''),NULLIF(user_device_alias,''),NULLIF(system_device_name,''),NULLIF(device_name,''),device_id) name FROM devices WHERE organization_id=? AND status='active' AND device_id IN (SELECT DISTINCT c.last_observed_device_id FROM contacts c WHERE "+visible+" AND c.last_observed_device_id IS NOT NULL) ORDER BY name",[org]+va)
  accounts=_rows(c,"SELECT channel_account_id id,display_name name,platform_id platformId FROM channel_accounts WHERE organization_id=? AND status='active' AND channel_account_id IN (SELECT DISTINCT v.channel_account_id FROM conversations v JOIN contacts c ON c.contact_id=v.contact_id WHERE "+visible+" UNION SELECT DISTINCT s.channel_account_id FROM sources s JOIN contacts c ON c.source_id=s.source_id WHERE "+visible+" AND s.channel_account_id IS NOT NULL) ORDER BY name",[org]+va+va)
  platform_ids={x['platformId'] for x in accounts if x.get('platformId')}
  platform_ids.update(x['id'] for x in _rows(c,"SELECT DISTINCT i.platform_id id FROM contact_identities i JOIN contacts c ON c.contact_id=i.contact_id WHERE "+visible+" AND i.platform_id IS NOT NULL",va))
  if platform_ids:
   marks=','.join('?' for _ in platform_ids);platforms=_rows(c,f"SELECT platform_id id,platform_code code,platform_abbr abbr,platform_name name FROM platforms WHERE status='active' AND platform_id IN ({marks}) ORDER BY platform_name",list(platform_ids))
  else:platforms=[]
  workspace_ids=[x['id'] for x in workspaces]
  if workspace_ids:
   marks=','.join('?' for _ in workspace_ids);tags=_rows(c,f"SELECT tag_id id,name,color,tag_kind kind,workspace_id workspaceId FROM tags WHERE enabled=1 AND tag_kind IN ('status','portrait') AND workspace_id IN ({marks}) ORDER BY sort_order,name",workspace_ids)
  else:tags=[]
  defs=_definitions(c,workspace_ids)
  public_workspaces=workspaces if can_read_management else []
  public_teams=teams if can_read_management else []
  public_owners=owners if can_read_management else []
  public_sources=sources if can_read_management else []
 return {'ok':True,'workspaces':public_workspaces,'teams':public_teams,'owners':public_owners,'platforms':platforms,'channelAccounts':accounts,'sources':public_sources,'devices':devices,'statusTags':[x for x in tags if x['kind']=='status'],'portraitTags':[x for x in tags if x['kind']=='portrait'],'fieldDefinitions':defs,'scope':scope_name,'permissions':{'read':True,'update':can_update,'readSensitive':can_read_sensitive,'readManagement':can_read_management,'readDeviceDetails':can_read_device_details,'readChannelAccountDetails':can_read_accounts,'readAudit':can_read_audit,'readMessageText':can_read_messages,'linkIdentity':can_link_identity,'reviewDuplicate':can_review_duplicate,'mergeContact':can_merge_contact,'teamAccess':can_team_access,'deleteContact':can_delete_contact,'export':can_export,'import':False}}
def governance_queue(db,actor,org,q):
 # A governance queue is a contact projection, so contact.read scope is always the outer predicate.
 page=_int(q.get('page'),1,1);size=_int(q.get('pageSize') or q.get('page_size'),200,1,500);off=(page-1)*size
 with db.tx(False) as c:
  scope,sp,scope_name=_scope(c,actor);where='c.organization_id=? AND c.deleted_at IS NULL AND ('+scope+')';args=[org]+sp
  total=c.execute('SELECT count(*) FROM contacts c WHERE '+where,args).fetchone()[0]
  raw=_rows(c,"SELECT c.contact_id,c.workspace_id,c.team_id,c.owner_user_id,c.manual_name,c.display_name,c.manual_phone,c.observed_phone,c.updated_at,w.name workspace_name,t.name team_name FROM contacts c LEFT JOIN workspaces w ON w.workspace_id=c.workspace_id LEFT JOIN teams t ON t.team_id=c.team_id WHERE "+where+' ORDER BY c.updated_at DESC,c.contact_id LIMIT ? OFFSET ?',args+[size,off])
 platform=is_platform_admin(db,actor);items=[]
 for r in raw:
  ctx={'workspace_id':r.get('workspace_id'),'team_id':r.get('team_id'),'resource_user_id':r.get('owner_user_id'),'organization_id':org}
  r['manual_phone']=_mask_sensitive_value(r.get('manual_phone'));r['observed_phone']=_mask_sensitive_value(r.get('observed_phone'))
  r['capabilities']={'read':True,'linkIdentity':bool(platform or can(db,actor,'contact.identity.link',**ctx)),'reviewDuplicate':bool(platform or can(db,actor,'contact.duplicate.review',**ctx)),'mergeContact':bool(platform or can(db,actor,'contact.merge',**ctx)),'teamAccess':bool(platform or can(db,actor,'contact.team_access',**ctx))}
  items.append(r)
 return {'ok':True,'items':items,'scope':scope_name,'pagination':{'page':page,'pageSize':size,'total':total,'pages':(total+size-1)//size}}

def listing(db,actor,org,q):
 page=_int(q.get('page'),1,1);size=_int(q.get('page_size') or q.get('pageSize'),50,1,200);off=(page-1)*size
 with db.tx(False) as c:
  scope,sp,scope_name=_scope(c,actor);fs,fp=_filters(q);where=['c.organization_id=?',scope]+fs;args=[org]+sp+fp
  sqlwhere=' AND '.join(where);total=c.execute('SELECT count(*) FROM contacts c WHERE '+sqlwhere,args).fetchone()[0]
  visible_workspaces=_rows(c,'SELECT DISTINCT c.workspace_id id FROM contacts c WHERE c.organization_id=? AND '+scope,[org]+sp)
  workspace_ids=[x['id'] for x in visible_workspaces];raw_defs=_raw_definitions(c,workspace_ids);columns=_definitions(c,workspace_ids)
  requested_sort=str(q.get('sort') or 'updated_at');sort_params=[]
  if requested_sort.startswith('custom:'):
   matching=[d for d in columns if d.get('columnKey')==requested_sort and _is_custom_definition(d)]
   if matching:
    sort="COALESCE((SELECT fv.value_json FROM contact_custom_values fv WHERE fv.contact_id=c.contact_id AND fv.field_key=? LIMIT 1),'')";sort_params=[matching[0]['field_key']]
   else:sort=SORTS['updated_at']
  else:sort=SORTS.get(requested_sort,SORTS['updated_at'])
  direction='ASC' if str(q.get('order') or 'desc').lower()=='asc' else 'DESC'
  raw=_rows(c,BASE_SELECT+' WHERE '+sqlwhere+f' ORDER BY {sort} {direction},c.contact_id LIMIT ? OFFSET ?',args+sort_params+[size,off])
  allowed=list(dict.fromkeys(x['field_key'] for x in raw_defs if _is_custom_definition(x)))
  requested=list(dict.fromkeys(x for x in str(q.get('fields') or '').split(',') if x in allowed))[:100];selected=requested or allowed
  selected_set=set(selected);selected_columns=[x for x in columns if _is_custom_definition(x) and x['field_key'] in selected_set]
  stage_keys=list(dict.fromkeys(list(STAGE_KEYS)+[x['field_key'] for x in raw_defs if _is_stage_definition(x)]))
  items=_enrich(c,raw,list(dict.fromkeys(stage_keys+selected)),selected_columns,raw_defs)
  platform=is_platform_admin(db,actor)
  for source,item in zip(raw,items):
   ctx={'workspace_id':source.get('workspace_id'),'team_id':source.get('team_id'),'resource_user_id':source.get('owner_user_id'),'organization_id':org}
   full=platform or can(db,actor,'contact.update',**ctx);assigned=False if full else can(db,actor,'contact.update.assigned',**ctx)
   read_management=platform or can(db,actor,'contact.management.read',**ctx)
   read_device_details=platform or can(db,actor,'device.read',**ctx)
   read_sensitive=platform or can(db,actor,'pii.read.full',**ctx)
   read_accounts=platform or can(db,actor,'account.read',**ctx)
   item['permissions']=_row_permissions(actor,source,full,assigned,read_management)
   item['permissions'].update({'canReadDeviceDetails':bool(read_device_details),'canReadSensitive':bool(read_sensitive),'canReadChannelAccountDetails':bool(read_accounts)})
   if not read_sensitive:
    item['manualPhoneMasked']=_mask_sensitive_value(item.get('manualPhone'));item['observedPhoneMasked']=_mask_sensitive_value(item.get('observedPhone'))
    item['manualPhone']=None;item['observedPhone']=None
    identity=item.get('primaryIdentity')
    if isinstance(identity,dict):
     masked=_mask_sensitive_value(identity.get('canonicalValue') or identity.get('value'));identity.pop('value',None);identity.pop('canonicalValue',None);identity['maskedValue']=masked
   if not read_accounts and isinstance(item.get('channelAccount'),dict):item['channelAccount']={'id':item['channelAccount'].get('id')}
   item['permissions'].update({'canUpdateBasic':_domain_permission(db,actor,source,'contact.update.basic',full,assigned,platform),'canUpdateStatus':_domain_permission(db,actor,source,'contact.update.status',full,assigned,platform),'canUpdatePortrait':_domain_permission(db,actor,source,'contact.update.portrait',full,assigned,platform),'canUpdateStages':_domain_permission(db,actor,source,'contact.update.stage',full,assigned,platform),'canUpdateCustomFields':_domain_permission(db,actor,source,'contact.update.custom',full,assigned,platform),'canUpdateNextFollowUpAt':_domain_permission(db,actor,source,'contact.update.followup',full,assigned,platform)})
   if not read_management:_trim_management(item,read_device_details)
   elif not read_device_details and isinstance(item.get('lastObservedDevice'),dict):item['lastObservedDevice']={'name':item['lastObservedDevice'].get('name'),'lastSeenAt':item['lastObservedDevice'].get('lastSeenAt')}
  now=now_ms();day=((now+8*3600000)//86400000)*86400000-8*3600000
  stats={'total':total,'todayNew':c.execute('SELECT count(*) FROM contacts c WHERE '+sqlwhere+' AND c.created_at>=?',args+[day]).fetchone()[0],'dueFollowUp':c.execute("SELECT count(*) FROM contacts c WHERE "+sqlwhere+" AND c.next_follow_up_at IS NOT NULL AND c.next_follow_up_at<=? AND NOT EXISTS (SELECT 1 FROM conversation_messages fm WHERE fm.contact_id=c.contact_id AND fm.direction='outbound' AND fm.sender_type='agent' AND fm.status='active' AND COALESCE(fm.occurred_at,fm.collected_at)>=c.next_follow_up_at)",args+[now]).fetchone()[0],'active7d':c.execute('SELECT count(*) FROM contacts c WHERE '+sqlwhere+' AND c.last_seen_at>=?',args+[now-7*86400000]).fetchone()[0]}
 return {'ok':True,'items':items,'stats':stats,'scope':scope_name,'pagination':{'page':page,'pageSize':size,'total':total,'pages':(total+size-1)//size}}

def _mask_sensitive_value(value):
 """为无 PII 权限的详情读取提供稳定脱敏；不返回可逆原值。"""
 if value is None:return None
 text=str(value)
 if not text:return ''
 if '@' in text:
  local,domain=text.split('@',1)
  return (local[:1]+'***@'+domain) if local else '***@'+domain
 digits=''.join(ch for ch in text if ch.isdigit())
 if len(digits)>=7:return text[:3]+'****'+text[-2:]
 if len(text)<=2:return '*'*len(text)
 return text[:1]+'***'+text[-1:]


def detail(db,actor,org,cid):
 with db.tx(False) as c:
  contact=_allowed(c,actor,org,cid,True)
  if not contact:return None
  raw=_rows(c,BASE_SELECT+' WHERE c.organization_id=? AND c.contact_id=?',(org,cid));raw_defs=_raw_definitions(c,[contact['workspace_id']]);columns=_definitions(c,[contact['workspace_id']]);item=_enrich(c,raw,None,columns,raw_defs)[0]
  item['identities']=_rows(c,"SELECT i.contact_identity_id id,i.identity_type type,i.identity_value value,i.canonical_value canonicalValue,i.verification_status verificationStatus,i.is_primary isPrimary,i.first_seen_at firstSeenAt,i.last_seen_at lastSeenAt,p.platform_name platformName,p.platform_abbr platformAbbr FROM contact_identities i LEFT JOIN platforms p ON p.platform_id=i.platform_id WHERE i.contact_id=? ORDER BY i.is_primary DESC,i.last_seen_at DESC",(cid,))
  item['conversations']=_rows(c,"SELECT v.conversation_id id,ca.display_name channelAccountName,p.platform_name platformName,v.status,v.last_message_at lastMessageAt FROM conversations v JOIN channel_accounts ca ON ca.channel_account_id=v.channel_account_id LEFT JOIN platforms p ON p.platform_id=v.platform_id WHERE v.contact_id=? ORDER BY v.last_message_at DESC LIMIT 20",(cid,))
  item['touchpoints']=_rows(c,"SELECT tp.touchpoint_type type,tp.direction,tp.initiated_by initiatedBy,tp.occurred_at occurredAt,s.source_name sourceName FROM source_touchpoints tp LEFT JOIN sources s ON s.source_id=tp.source_id WHERE tp.contact_id=? ORDER BY COALESCE(tp.occurred_at,tp.created_at) DESC LIMIT 20",(cid,))
  item['messages']=_rows(c,"""SELECT m.message_id messageId,m.conversation_id conversationId,m.direction,m.sender_type senderType,m.content_type contentType,m.redacted_text text,m.occurred_at occurredAt,m.collected_at collectedAt,m.status,m.content_deleted_at contentDeletedAt,m.metadata_json metadataJson,ca.display_name channelAccountName,p.platform_name platformName FROM conversation_messages m LEFT JOIN conversations v ON v.conversation_id=m.conversation_id LEFT JOIN channel_accounts ca ON ca.channel_account_id=v.channel_account_id LEFT JOIN platforms p ON p.platform_id=v.platform_id WHERE m.contact_id=? AND m.deleted_at IS NULL ORDER BY COALESCE(m.occurred_at,m.collected_at) DESC,m.message_id DESC LIMIT 100""",(cid,))
  item['audits']=_rows(c,"SELECT operation,actor_id actorId,reason,created_at createdAt FROM audit_logs WHERE entity_type='contact' AND entity_id=? ORDER BY created_at DESC LIMIT 30",(cid,))
  item['fieldDefinitions']=raw_defs
 auth_context={'workspace_id':contact.get('workspace_id'),'team_id':contact.get('team_id'),'resource_user_id':contact.get('owner_user_id'),'organization_id':org}
 can_full=is_platform_admin(db,actor) or can(db,actor,'contact.update',**auth_context)
 can_assigned=False if can_full else can(db,actor,'contact.update.assigned',**auth_context)
 read_management=is_platform_admin(db,actor) or can(db,actor,'contact.management.read',workspace_id=contact.get('workspace_id'),team_id=contact.get('team_id'),resource_user_id=contact.get('owner_user_id'),organization_id=org)
 read_device_details=is_platform_admin(db,actor) or can(db,actor,'device.read',**auth_context)
 read_sensitive=is_platform_admin(db,actor) or can(db,actor,'pii.read.full',**auth_context)
 read_account_details=is_platform_admin(db,actor) or can(db,actor,'account.read',**auth_context)
 read_audit=is_platform_admin(db,actor) or can(db,actor,'audit.read',**auth_context)
 read_audit_actor=is_platform_admin(db,actor) or can(db,actor,'audit.actor.read',**auth_context)
 read_message_text=is_platform_admin(db,actor) or can(db,actor,'message.read.raw',**auth_context) or can(db,actor,'message.read.team',**auth_context) or can(db,actor,'message.read.self',**auth_context)
 item['permissions']=_row_permissions(actor,contact,can_full,can_assigned,read_management);item['permissions'].update({'canReadDeviceDetails':bool(read_device_details),'canReadSensitive':bool(read_sensitive),'canReadChannelAccountDetails':bool(read_account_details),'canReadAudit':bool(read_audit),'canReadMessageText':bool(read_message_text)})
 platform=is_platform_admin(db,actor)
 item['permissions'].update({'canUpdateBasic':_domain_permission(db,actor,contact,'contact.update.basic',can_full,can_assigned,platform),'canUpdateStatus':_domain_permission(db,actor,contact,'contact.update.status',can_full,can_assigned,platform),'canUpdatePortrait':_domain_permission(db,actor,contact,'contact.update.portrait',can_full,can_assigned,platform),'canUpdateStages':_domain_permission(db,actor,contact,'contact.update.stage',can_full,can_assigned,platform),'canUpdateCustomFields':_domain_permission(db,actor,contact,'contact.update.custom',can_full,can_assigned,platform),'canUpdateNextFollowUpAt':_domain_permission(db,actor,contact,'contact.update.followup',can_full,can_assigned,platform)})
 item['canUpdate']=item['permissions']['canUpdate']
 item['permissions']['canReadSensitive']=bool(read_sensitive)
 item['permissions']['canReadChannelAccountDetails']=bool(read_account_details)
 if not read_sensitive:
  item['manualPhoneMasked']=_mask_sensitive_value(item.get('manualPhone'));item['observedPhoneMasked']=_mask_sensitive_value(item.get('observedPhone'))
  item['manualPhone']=None;item['observedPhone']=None
  primary=item.get('primaryIdentity')
  if isinstance(primary,dict):
   masked=_mask_sensitive_value(primary.get('canonicalValue') or primary.get('value'));primary.pop('value',None);primary.pop('canonicalValue',None);primary['maskedValue']=masked
  for identity in item.get('identities') or []:
   masked=_mask_sensitive_value(identity.get('canonicalValue') or identity.get('value'))
   identity.pop('value',None);identity.pop('canonicalValue',None);identity['maskedValue']=masked
 if not read_account_details:
  if isinstance(item.get('channelAccount'),dict):item['channelAccount']={'id':item['channelAccount'].get('id')}
  for conversation in item.get('conversations') or []:conversation.pop('channelAccountName',None)
 # 210.2.57: contact detail uses the canonical safe translation contract.
 for message in item.get('messages') or []:
  try:message_meta=json.loads(message.pop('metadataJson',None) or '{}')
  except Exception:message_meta={}
  safe_meta={k:message_meta.get(k) for k in ('timestampResolved','timestampSource','timestampConfidence') if k in message_meta}
  tr=message_meta.get('translation') if isinstance(message_meta,dict) else None
  if read_message_text and not message.get('contentDeletedAt') and isinstance(tr,dict) and tr.get('visible',True) is not False and isinstance(tr.get('text'),str):
   safe_meta['translation']={'text':redact_text(tr['text'])[0][:65536],'source':str(tr.get('source') or 'page')[:80],'visible':True}
  message['metadata']=safe_meta
 if not read_message_text:
  for message in item.get('messages') or []:message.pop('text',None)
 if not read_audit:item['audits']=[]
 elif not read_audit_actor:
  for audit in item.get('audits') or []:audit.pop('actorId',None)
 if not read_management:_trim_management(item,read_device_details)
 elif not read_device_details and isinstance(item.get('lastObservedDevice'),dict):item['lastObservedDevice']={'name':item['lastObservedDevice'].get('name'),'lastSeenAt':item['lastObservedDevice'].get('lastSeenAt')}
 return item


def delete_contact(db,actor,org,cid,b):
 if not isinstance(b,dict):return 'INVALID_BODY',None
 base=_strict_version(b.get('baseVersion'))
 if base is None:return 'VERSION_REQUIRED',None
 reason=str(b.get('reason') or '').strip()
 if not reason:return 'DELETE_REASON_REQUIRED',None
 if len(reason)>500:return 'DELETE_REASON_TOO_LONG',None
 with db.tx() as c:
  old=_allowed(c,actor,org,cid)
  if not old:return 'NOT_FOUND',None
  ctx={'workspace_id':old.get('workspace_id'),'team_id':old.get('team_id'),'resource_user_id':old.get('owner_user_id'),'organization_id':org}
  if not (is_platform_admin(db,actor) or can(db,actor,'contact.delete',**ctx)):return 'FORBIDDEN',None
  if base!=int(old.get('version') or 0):return 'CONFLICT',None
  n=now_ms()
  cur=c.execute('UPDATE contacts SET deleted_at=?,deleted_by=?,delete_reason=?,version=version+1,updated_at=? WHERE contact_id=? AND organization_id=? AND version=? AND deleted_at IS NULL',(n,actor['user_id'],reason,n,cid,org,base))
  if cur.rowcount!=1:return 'CONFLICT',None
  new=_one(c,'SELECT * FROM contacts WHERE contact_id=? AND organization_id=?',(cid,org))
  _audit(c,actor,old,{'deletedAt':old.get('deleted_at'),'deletedBy':old.get('deleted_by'),'deleteReason':old.get('delete_reason'),'version':base},{'deletedAt':n,'deletedBy':actor['user_id'],'deleteReason':reason,'version':base+1},'contact.delete',reason)
 return None,new

def update_basic(db,actor,org,cid,b):
 if not isinstance(b,dict):return 'INVALID_BODY',None
 base=_strict_version(b.get('baseVersion'))
 if base is None:return 'VERSION_REQUIRED',None
 with db.tx() as c:
  old=_allowed(c,actor,org,cid)
  if not old:return 'NOT_FOUND',None
  platform=is_platform_admin(db,actor);ctx={'workspace_id':old.get('workspace_id'),'team_id':old.get('team_id'),'resource_user_id':old.get('owner_user_id'),'organization_id':org}
  full=platform or can(db,actor,'contact.update',**ctx);assigned=False if full else can(db,actor,'contact.update.assigned',**ctx)
  if old.get('deleted_at') or not _can_update_contact(actor,old,full,assigned) or not _domain_permission(db,actor,old,'contact.update.basic',full,assigned,platform):return 'FORBIDDEN',None
  if base!=int(old.get('version') or 0):return 'CONFLICT',None
  name=str(b.get('manualName') if b.get('manualName') is not None else old.get('manual_name') or '').strip()
  phone=str(b.get('manualPhone') if b.get('manualPhone') is not None else old.get('manual_phone') or '').strip()
  remark=str(b.get('remark') if b.get('remark') is not None else old.get('remark') or '')
  if len(name)>200 or len(phone)>80 or len(remark)>4000:return 'FIELD_TOO_LONG',None
  before={'manualName':old.get('manual_name') or '','manualPhone':old.get('manual_phone') or '','remark':old.get('remark') or ''}
  after={'manualName':name,'manualPhone':phone,'remark':remark}
  if before==after:return None,old
  n=now_ms();cur=c.execute('UPDATE contacts SET manual_name=?,manual_phone=?,remark=?,version=version+1,updated_at=? WHERE contact_id=? AND organization_id=? AND version=?',(name,phone,remark,n,cid,org,base))
  if cur.rowcount!=1:return 'CONFLICT',None
  new=_one(c,'SELECT * FROM contacts WHERE contact_id=?',(cid,));_audit(c,actor,old,before,after,'contact-center-basic',b.get('reason'))
 return None,new


def update_tags(db,actor,org,cid,b):
 if not isinstance(b,dict):return 'INVALID_BODY',None
 payload={'baseVersion':b.get('baseVersion'),'reason':b.get('reason')}
 if 'statusTagId' in b:payload['statusTagId']=b.get('statusTagId')
 if 'portraitTagIds' in b:payload['portraitTagIds']=b.get('portraitTagIds')
 result=update_workbench(db,actor,org,cid,payload)
 if result.get('ok'):
  if result.get('item') is not None:return None,result['item']
  with db.tx(False) as c:return None,_one(c,'SELECT * FROM contacts WHERE contact_id=? AND organization_id=?',(cid,org))
 code=result.get('code')
 legacy={'BASE_VERSION_REQUIRED':'VERSION_REQUIRED','CONTACT_VERSION_CONFLICT':'CONFLICT','FIELD_UPDATE_FORBIDDEN':'FORBIDDEN'}
 return legacy.get(code,code or 'INVALID_TAG'),None


def update_fields(db,actor,org,cid,b):
 if not isinstance(b,dict) or not isinstance(b.get('values'),dict):return 'INVALID_FIELDS',None
 with db.tx(False) as c:
  old=_allowed(c,actor,org,cid)
  if not old:return 'NOT_FOUND',None
  defs={x['field_key']:x for x in _raw_definitions(c,[old['workspace_id']])}
 stages={};custom={}
 for key,value in b['values'].items():
  definition=defs.get(key)
  if not definition:return 'INVALID_FIELD',None
  (stages if _is_stage_definition(definition) else custom)[key]=value
 payload={'baseVersion':b.get('baseVersion'),'reason':b.get('reason')}
 if stages:payload['stages']=stages
 if custom:payload['customValues']=custom
 if not stages and not custom:
  base=_strict_version(b.get('baseVersion'))
  if base is None:return 'VERSION_REQUIRED',None
  if base!=int(old.get('version') or 0):return 'CONFLICT',None
  return None,old
 result=update_workbench(db,actor,org,cid,payload)
 if result.get('ok'):
  if result.get('item') is not None:return None,result['item']
  with db.tx(False) as c:return None,_one(c,'SELECT * FROM contacts WHERE contact_id=? AND organization_id=?',(cid,org))
 code=result.get('code');legacy={'BASE_VERSION_REQUIRED':'VERSION_REQUIRED','CONTACT_VERSION_CONFLICT':'CONFLICT','FIELD_UPDATE_FORBIDDEN':'FORBIDDEN','INVALID_CUSTOM_VALUES':'INVALID_FIELDS','INVALID_STAGES':'INVALID_FIELDS'}
 return legacy.get(code,code or 'INVALID_FIELDS'),None


def _option_values(definition):
 opts=(definition or {}).get('options') or []
 if isinstance(opts,str):
  try:opts=loads(opts)
  except Exception:opts=[]
 if not isinstance(opts,list):return []
 values=[]
 for x in opts:
  if isinstance(x,dict):
   value=next((x.get(k) for k in ('value','id','name','label') if x.get(k) is not None),None)
   if value is not None:values.append(str(value))
  else:values.append(str(x))
 return values

def _validate_stage_value(definition,value):
 opts=_option_values(definition)
 if value is None:return None
 values=value if isinstance(value,list) else [value]
 if len(values)>100 or any(not isinstance(x,str) or len(x)>4000 for x in values):return 'INVALID_FIELD_TYPE'
 if opts and any(x not in opts for x in values):return 'INVALID_OPTION'
 return None

def _normalize_stage_value(value):
 if value is None:return None
 values=value if isinstance(value,list) else [value]
 clean=[]
 for x in values:
  x=x.strip()
  if x and x not in clean:clean.append(x)
 return clean or None

def _validate_workbench_value(definition,value):
 typ=str((definition or {}).get('field_type') or (definition or {}).get('fieldType') or 'text').lower();opts=_option_values(definition)
 if value is None:return None
 if typ=='text':
  if not isinstance(value,str):return 'INVALID_FIELD_TYPE'
  if len(value)>4000:return 'FIELD_TOO_LONG'
 elif typ=='single_select':
  if not isinstance(value,str):return 'INVALID_FIELD_TYPE'
  if value and value not in opts:return 'INVALID_OPTION'
 elif typ=='multi_select':
  if not isinstance(value,list) or any(not isinstance(x,str) or x not in opts for x in value):return 'INVALID_OPTION'
 elif typ=='boolean':
  if not isinstance(value,bool):return 'INVALID_FIELD_TYPE'
 elif typ=='number':
  if isinstance(value,bool) or not isinstance(value,(int,float)):return 'INVALID_FIELD_TYPE'
 elif typ=='date':
  if isinstance(value,bool) or not isinstance(value,(int,str)):return 'INVALID_FIELD_TYPE'
 elif typ=='json':
  try:dumps(value)
  except Exception:return 'INVALID_FIELD_TYPE'
 else:return 'INVALID_FIELD_TYPE'
 return None

def _normalize_workbench_value(definition,value):
 typ=str((definition or {}).get('field_type') or 'text').lower()
 if value is None:return None
 if typ in ('text','single_select','date') and value=='':return None
 if typ=='multi_select' and value==[]:return None
 return value

def update_workbench(db,actor,org,cid,b):
 if not isinstance(b,dict):return {'ok':False,'code':'INVALID_BODY','message':'请求体必须是对象','status':400}
 base=_strict_version(b.get('baseVersion'))
 if base is None:return {'ok':False,'code':'BASE_VERSION_REQUIRED','message':'baseVersion 必须是非负整数','status':400}
 domains={'statusTagId','portraitTagIds','stages','customValues','nextFollowUpAt','nextFollowUpReason'}
 supplied=domains.intersection(b)
 if not supplied:return {'ok':False,'code':'NO_CHANGES','message':'未提供需要修改的工作台字段','status':400}
 if 'nextFollowUpAt' in b and not _valid_followup(b.get('nextFollowUpAt')):return {'ok':False,'code':'INVALID_NEXT_FOLLOW_UP_AT','message':'nextFollowUpAt 必须是有效的整数毫秒时间戳或 null','status':400}
 if 'nextFollowUpReason' in b and (not isinstance(b.get('nextFollowUpReason'),str) or len(b.get('nextFollowUpReason').strip())>500):return {'ok':False,'code':'INVALID_NEXT_FOLLOW_UP_REASON','message':'跟进事由必须是 500 字以内文本','status':400}
 stages=b.get('stages') if 'stages' in b else {}
 custom=b.get('customValues') if 'customValues' in b else {}
 if not isinstance(stages,dict):return {'ok':False,'code':'INVALID_STAGES','message':'stages 必须是对象','status':400}
 if not isinstance(custom,dict):return {'ok':False,'code':'INVALID_CUSTOM_VALUES','message':'customValues 必须是对象','status':400}
 if set(stages)&set(custom):return {'ok':False,'code':'FIELD_ROLE_CONFLICT','message':'进度字段不能同时作为自定义字段提交','fields':sorted(set(stages)&set(custom)),'status':400}
 portraits=b.get('portraitTagIds') if 'portraitTagIds' in b else None
 if portraits is not None and not isinstance(portraits,list):return {'ok':False,'code':'INVALID_TAG','message':'portraitTagIds 必须是数组','status':400}
 portraits=list(dict.fromkeys(str(x) for x in (portraits or []) if x)) if portraits is not None else None
 status=(str(b.get('statusTagId') or '').strip() if 'statusTagId' in b else None)
 try:
  with db.tx() as c:
   old=_allowed(c,actor,org,cid)
   if not old:return {'ok':False,'code':'NOT_FOUND','message':'客户不存在或无权访问','status':404}
   platform=is_platform_admin(db,actor);ctx={'workspace_id':old.get('workspace_id'),'team_id':old.get('team_id'),'resource_user_id':old.get('owner_user_id'),'organization_id':org}
   full=platform or can(db,actor,'contact.update',**ctx);assigned=False if full else can(db,actor,'contact.update.assigned',**ctx)
   if old.get('deleted_at') or not _can_update_contact(actor,old,full,assigned):return {'ok':False,'code':'FORBIDDEN','message':'无权修改该联系人','status':403}
   domain_permissions={'statusTagId':'contact.update.status','portraitTagIds':'contact.update.portrait','stages':'contact.update.stage','customValues':'contact.update.custom','nextFollowUpAt':'contact.update.followup','nextFollowUpReason':'contact.update.followup'}
   denied=[key for key in supplied if not _domain_permission(db,actor,old,domain_permissions[key],full,assigned,platform)]
   if denied:return {'ok':False,'code':'FIELD_UPDATE_FORBIDDEN','message':'无权修改部分工作台字段','fields':sorted(denied),'status':403}
   current=int(old.get('version') or 0)
   if base!=current:return {'ok':False,'code':'CONTACT_VERSION_CONFLICT','message':'客户资料已被其他用户更新','status':409,'currentVersion':current}
   defs={x['field_key']:x for x in _raw_definitions(c,[old['workspace_id']])}
   normalized_stages={};normalized_custom={}
   for key,value in stages.items():
    d=defs.get(key)
    if not d or not _is_stage_definition(d):return {'ok':False,'code':'INVALID_STAGE_FIELD','message':'进度字段不存在或角色不匹配','field':key,'status':400}
    err=_validate_stage_value(d,value)
    if err:return {'ok':False,'code':err,'message':'进度字段值不合法','field':key,'status':400}
    normalized_stages[key]=_normalize_stage_value(value)
   for key,value in custom.items():
    d=defs.get(key)
    if not d or not _is_custom_definition(d):return {'ok':False,'code':'INVALID_FIELD','message':'自定义字段不存在或角色不匹配','field':key,'status':400}
    err=_validate_workbench_value(d,value)
    if err:return {'ok':False,'code':err,'message':'自定义字段值不合法','field':key,'status':400}
    normalized_custom[key]=_normalize_workbench_value(d,value)
   wanted=(([status] if status else [])+(portraits or [])) if status is not None or portraits is not None else []
   if wanted:
    marks=','.join('?' for _ in wanted);rows=_rows(c,f'SELECT tag_id,tag_kind FROM tags WHERE workspace_id=? AND enabled=1 AND tag_id IN ({marks})',[old['workspace_id']]+wanted);kinds={x['tag_id']:x['tag_kind'] for x in rows}
    if any(x not in kinds for x in wanted) or (status and kinds.get(status)!='status') or any(kinds.get(x)!='portrait' for x in (portraits or [])):return {'ok':False,'code':'INVALID_TAG','message':'标签不存在、未启用或类型不匹配','status':400}
   submitted_values=dict(normalized_stages,**normalized_custom);field_keys=list(submitted_values);before_values={};existing_keys=set()
   if field_keys:
    marks=','.join('?' for _ in field_keys)
    for row in _rows(c,f'SELECT field_key,value_json FROM contact_custom_values WHERE contact_id=? AND field_key IN ({marks})',[cid]+field_keys):
     existing_keys.add(row['field_key']);before_values[row['field_key']]=_json(row['value_json'])
   before_tags=_rows(c,"SELECT t.tag_id,t.tag_kind FROM contact_tags ct JOIN tags t ON t.tag_id=ct.tag_id WHERE ct.contact_id=? AND t.tag_kind IN ('status','portrait')",(cid,))
   old_status=next((x['tag_id'] for x in before_tags if x['tag_kind']=='status'),None);old_portraits=[x['tag_id'] for x in before_tags if x['tag_kind']=='portrait']
   changed_values={k:v for k,v in submitted_values.items() if before_values.get(k)!=v or (v is None and k in existing_keys)}
   status_changed=status is not None and (status or None)!=old_status
   portraits_changed=portraits is not None and set(portraits)!=set(old_portraits)
   followup_changed='nextFollowUpAt' in b and b.get('nextFollowUpAt')!=old.get('next_follow_up_at')
   old_followup_reason=_followup_reason(old);new_followup_reason=str(b.get('nextFollowUpReason') or '').strip() if 'nextFollowUpReason' in b else old_followup_reason;followup_reason_changed=new_followup_reason!=old_followup_reason
   if not (changed_values or status_changed or portraits_changed or followup_changed or followup_reason_changed):
    return {'ok':True,'unchanged':True,'version':current}
   before={'version':current,'statusTagId':old_status,'portraitTagIds':old_portraits,'stages':{k:before_values.get(k) for k in normalized_stages},'customValues':{k:before_values.get(k) for k in normalized_custom},'nextFollowUpAt':old.get('next_follow_up_at'),'nextFollowUpReason':old_followup_reason}
   after={'version':current+1,'statusTagId':status if status is not None else old_status,'portraitTagIds':portraits if portraits is not None else old_portraits,'stages':dict(before['stages'],**normalized_stages),'customValues':dict(before['customValues'],**normalized_custom),'nextFollowUpAt':b.get('nextFollowUpAt') if 'nextFollowUpAt' in b else old.get('next_follow_up_at'),'nextFollowUpReason':new_followup_reason}
   n=now_ms();sets=['version=version+1','updated_at=?'];args=[n]
   if followup_changed:sets.append('next_follow_up_at=?');args.append(b.get('nextFollowUpAt'))
   if followup_reason_changed:
    business=_business(old.get('business_json'));business['nextFollowUpReason']=new_followup_reason if new_followup_reason else '';sets.append('business_json=?');args.append(dumps(business))
   args.extend([cid,org,base]);cur=c.execute('UPDATE contacts SET '+','.join(sets)+' WHERE contact_id=? AND organization_id=? AND version=?',args)
   if cur.rowcount!=1:return {'ok':False,'code':'CONTACT_VERSION_CONFLICT','message':'客户资料已被其他用户更新','status':409,'currentVersion':current}
   if followup_changed or followup_reason_changed:
    updated=dict(c.execute('SELECT * FROM contacts WHERE contact_id=?',(cid,)).fetchone());sync_follow_up_plan_in_tx(c,updated,after['nextFollowUpAt'],after['nextFollowUpReason'],actor['user_id'],n)
   if status_changed:
    c.execute("DELETE FROM contact_tags WHERE contact_id=? AND tag_id IN (SELECT tag_id FROM tags WHERE tag_kind='status')",(cid,))
    if status:c.execute('INSERT INTO contact_tags(contact_id,tag_id,created_at) VALUES(?,?,?)',(cid,status,n))
   if portraits_changed:
    c.execute("DELETE FROM contact_tags WHERE contact_id=? AND tag_id IN (SELECT tag_id FROM tags WHERE tag_kind='portrait')",(cid,))
    for tag in portraits:c.execute('INSERT INTO contact_tags(contact_id,tag_id,created_at) VALUES(?,?,?)',(cid,tag,n))
   for key,value in changed_values.items():
    if value is None:c.execute('DELETE FROM contact_custom_values WHERE contact_id=? AND field_key=?',(cid,key))
    else:c.execute("INSERT INTO contact_custom_values(contact_id,field_key,value_json,updated_at,updated_by) VALUES(?,?,?,?,?) ON CONFLICT(contact_id,field_key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at,updated_by=excluded.updated_by",(cid,key,dumps(value),n,actor['user_id']))
   _audit(c,actor,old,before,after,'contact-center-workbench',b.get('reason'))
   item=_one(c,'SELECT * FROM contacts WHERE contact_id=?',(cid,))
  return {'ok':True,'unchanged':False,'item':item,'version':current+1}
 except FollowUpPlanConflict:
  return {'ok':False,'code':'FOLLOW_UP_TIME_ALREADY_COMPLETED','message':'该时间已有已完成的跟进记录，请选择其他时间','status':409}
 except sqlite3.OperationalError:
  request_id=uuid.uuid4().hex
  LOGGER.exception('workbench database compatibility failure request_id=%s organization_id=%s contact_id=%s actor_id=%s',request_id,org,cid,(actor or {}).get('user_id'))
  return {'ok':False,'code':'FOLLOW_UP_DATABASE_INCOMPATIBLE','message':'跟进数据结构尚未完成升级，请重启服务后重试','requestId':request_id,'status':503}
 except Exception:
  request_id=uuid.uuid4().hex
  LOGGER.exception('workbench update failed request_id=%s organization_id=%s contact_id=%s actor_id=%s',request_id,org,cid,(actor or {}).get('user_id'))
  return {'ok':False,'code':'WORKBENCH_UPDATE_FAILED','message':'工作台更新失败','requestId':request_id,'status':500}

def _can_update_contact(actor,contact,can_full,can_assigned):
 if can_full:return True
 return bool(can_assigned and contact and contact.get('owner_user_id')==actor.get('user_id'))

def follow_up_reminders(db,actor,org,q):
 """Return every visible overdue follow-up; never derives reminders from a list page."""
 delay=_int(q.get('delay_minutes') or q.get('delayMinutes'),10,0,1440)
 cutoff=now_ms()-delay*60000
 with db.tx(False) as c:
  scope,sp,scope_name=_scope(c,actor)
  where="c.organization_id=? AND "+scope+" AND c.deleted_at IS NULL AND c.next_follow_up_at IS NOT NULL AND c.next_follow_up_at<=? AND NOT EXISTS (SELECT 1 FROM conversation_messages fm WHERE fm.contact_id=c.contact_id AND fm.direction='outbound' AND fm.sender_type='agent' AND fm.status='active' AND COALESCE(fm.occurred_at,fm.collected_at)>=c.next_follow_up_at)"
  rows=_rows(c,"SELECT c.contact_id,c.manual_name,c.display_name,c.next_follow_up_at,c.business_json,c.version FROM contacts c WHERE "+where+" ORDER BY c.next_follow_up_at,c.contact_id",[org]+sp+[cutoff])
 items=[{'contactId':x['contact_id'],'name':x.get('manual_name') or x.get('display_name') or '未命名客户','nextFollowUpAt':x['next_follow_up_at'],'nextFollowUpReason':_followup_reason(x),'version':x['version']} for x in rows]
 return {'ok':True,'items':items,'total':len(items),'scope':scope_name,'checkedAt':now_ms(),'delayMinutes':delay}

def _validate_preferences_payload(body, valid_dynamic_keys=None):
    if not isinstance(body, dict):
        raise ValueError("request body must be an object")
    encoded=json.dumps(body,ensure_ascii=False,separators=(",", ":")).encode("utf-8")
    if len(encoded)>65536:raise ValueError("preferences payload exceeds 64 KiB")
    base=body.get("baseVersion")
    if isinstance(base,bool):raise ValueError("baseVersion must be a non-negative integer")
    if isinstance(base,str) and re.fullmatch(r"0|[1-9][0-9]*",base):base=int(base)
    if not isinstance(base,int) or base<0:raise ValueError("baseVersion must be a non-negative integer")
    pref=body.get("preferences")
    if not isinstance(pref,dict):raise ValueError("preferences must be an object")
    widths=pref.get("columnWidths") or {};visibility=pref.get("columnVisibility") or {}
    if not isinstance(widths,dict) or len(widths)>120:raise ValueError("invalid columnWidths")
    if not isinstance(visibility,dict):raise ValueError("invalid columnVisibility")
    allowed_static={"customer","status","portrait","progress","channel","device","time","ownerTeam","sourceWorkspace","nextFollowUpAt","actions","selection"}
    clean_widths={}
    for raw_key,value in widths.items():
        key=str(raw_key)
        if len(key)>160:raise ValueError("column key too long")
        if key.startswith("custom:"):
            if valid_dynamic_keys is None or key not in valid_dynamic_keys:continue
        elif key not in allowed_static:continue
        try:value=int(value)
        except Exception:raise ValueError("invalid column width")
        clean_widths[key]=max(50,min(600,value)) if not key.startswith("custom:") else None
        if key.startswith("custom:"):clean_widths.pop(key,None)
    density=pref.get("density","standard")
    if density not in ("compact","standard","comfortable"):raise ValueError("invalid density")
    raw_order=pref.get("columnOrder") or []
    if not isinstance(raw_order,list) or len(raw_order)>120:raise ValueError("invalid columnOrder")
    clean_order=[]
    for raw_key in raw_order:
        key=str(raw_key)
        if len(key)>160:raise ValueError("column key too long")
        valid=(key in allowed_static) or (key.startswith("custom:") and valid_dynamic_keys is not None and key in valid_dynamic_keys)
        if valid and key not in clean_order:clean_order.append(key)
    reminder=pref.get("followUpReminder") or {}
    if not isinstance(reminder,dict):raise ValueError("invalid followUpReminder")
    first=_int(reminder.get("firstDelayMinutes"),10,0,1440);repeat=_int(reminder.get("repeatMinutes"),10,1,1440)
    volume=reminder.get("volume",0.6);duration=reminder.get("durationMs",500);frequency=reminder.get("frequency",760);snooze=reminder.get("snoozeMinutes",10)
    try:volume=float(volume);duration=int(duration);frequency=int(frequency);snooze=int(snooze)
    except Exception:raise ValueError("invalid reminder sound")
    sound_type=str(reminder.get("soundType") or "bright")
    if sound_type not in ("bright","soft","classic","urgent","tap","silent"):sound_type="bright"
    clean={"schemaVersion":3,"dynamicFieldMinWidth":_int(pref.get("dynamicFieldMinWidth"),140,100,360),
           "columnWidths":clean_widths,"columnOrder":clean_order,
           "columnVisibility":{"ownerTeam":bool(visibility.get("ownerTeam",False)),"sourceWorkspace":bool(visibility.get("sourceWorkspace",False))},
           "density":density,"followUpReminder":{"firstDelayMinutes":first,"repeatMinutes":repeat,"desktopNotifications":bool(reminder.get("desktopNotifications",False)),"privacyMode":bool(reminder.get("privacyMode",True)),"soundEnabled":bool(reminder.get("soundEnabled",True)),"soundType":sound_type,"volume":max(0,min(1,volume)),"durationMs":max(100,min(5000,duration)),"frequency":max(200,min(2000,frequency)),"snoozeMinutes":max(1,min(1440,snooze))}}
    return base,clean


def _preference_defaults():
 return {'schemaVersion':3,'dynamicFieldMinWidth':140,'columnWidths':{},'columnOrder':[],'columnVisibility':{'ownerTeam':False,'sourceWorkspace':False},'density':'standard','followUpReminder':{'firstDelayMinutes':10,'repeatMinutes':10,'desktopNotifications':False,'privacyMode':True,'soundEnabled':True,'soundType':'bright','volume':0.6,'durationMs':500,'frequency':760,'snoozeMinutes':10}}

def _clean_preferences(saved,valid_dynamic_keys):
 if not isinstance(saved,dict):return _preference_defaults()
 try:return _validate_preferences_payload({'baseVersion':0,'preferences':saved},valid_dynamic_keys)[1]
 except (ValueError,TypeError,OverflowError):return _preference_defaults()

def get_preferences(db,actor,org):
 with db.tx(False) as c:
  scope,scope_params,_=_scope(c,actor)
  workspace_ids=[r[0] for r in c.execute('SELECT DISTINCT c.workspace_id FROM contacts c WHERE c.organization_id=? AND '+scope,[org]+scope_params).fetchall()]
  valid_dynamic_keys={d['columnKey'] for d in _definitions(c,workspace_ids)}
  row=c.execute('SELECT preferences_json,version FROM user_contact_center_preferences WHERE organization_id=? AND user_id=?',(org,actor['user_id'])).fetchone()
 if not row:return {'ok':True,'preferences':_preference_defaults(),'version':0}
 return {'ok':True,'preferences':_clean_preferences(_json(row[0],{}),valid_dynamic_keys),'version':max(0,int(row[1] or 0))}

def save_preferences(db,actor,org,b):
 if not isinstance(b,dict) or not isinstance(b.get('preferences'),dict):return 'INVALID_PREFERENCES',None
 with db.tx() as c:
  scope,scope_params,_=_scope(c,actor)
  workspace_ids=[r[0] for r in c.execute('SELECT DISTINCT c.workspace_id FROM contacts c WHERE c.organization_id=? AND '+scope,[org]+scope_params).fetchall()]
  valid_dynamic_keys={d['columnKey'] for d in _definitions(c,workspace_ids)}
  try:base,clean=_validate_preferences_payload(b,valid_dynamic_keys)
  except (ValueError,TypeError,OverflowError):return 'INVALID_PREFERENCES',None
  row=c.execute('SELECT preferences_json,version FROM user_contact_center_preferences WHERE organization_id=? AND user_id=?',(org,actor['user_id'])).fetchone()
  current_version=max(0,int(row[1] or 0)) if row else 0
  if base!=current_version:
   current=_clean_preferences(_json(row[0],{}) if row else {},valid_dynamic_keys)
   return 'PREFERENCES_VERSION_CONFLICT',{'ok':False,'code':'PREFERENCES_VERSION_CONFLICT','message':'列表偏好已被其他会话更新','currentVersion':current_version,'preferences':current}
  now=now_ms();version=current_version+1
  if row:
   changed=c.execute('UPDATE user_contact_center_preferences SET preferences_json=?,version=?,updated_at=? WHERE organization_id=? AND user_id=? AND version=?',(dumps(clean),version,now,org,actor['user_id'],current_version)).rowcount
   if changed!=1:
    latest=c.execute('SELECT preferences_json,version FROM user_contact_center_preferences WHERE organization_id=? AND user_id=?',(org,actor['user_id'])).fetchone()
    latest_version=max(0,int(latest[1] or 0)) if latest else 0
    latest_pref=_clean_preferences(_json(latest[0],{}) if latest else {},valid_dynamic_keys)
    return 'PREFERENCES_VERSION_CONFLICT',{'ok':False,'code':'PREFERENCES_VERSION_CONFLICT','message':'列表偏好已被其他会话更新','currentVersion':latest_version,'preferences':latest_pref}
  else:
   try:c.execute('INSERT INTO user_contact_center_preferences(organization_id,user_id,preferences_json,version,updated_at) VALUES(?,?,?,?,?)',(org,actor['user_id'],dumps(clean),version,now))
   except Exception:
    latest=c.execute('SELECT preferences_json,version FROM user_contact_center_preferences WHERE organization_id=? AND user_id=?',(org,actor['user_id'])).fetchone()
    if not latest:raise
    latest_version=max(0,int(latest[1] or 0))
    latest_pref=_clean_preferences(_json(latest[0],{}),valid_dynamic_keys)
    return 'PREFERENCES_VERSION_CONFLICT',{'ok':False,'code':'PREFERENCES_VERSION_CONFLICT','message':'列表偏好已被其他会话更新','currentVersion':latest_version,'preferences':latest_pref}
 return None,{'ok':True,'preferences':clean,'version':version}

def _query_value(q,*keys):
 for key in keys:
  value=(q or {}).get(key)
  if isinstance(value,list):value=value[-1] if value else None
  if value not in (None,''):return str(value).strip()
 return ''

def _conversation_actor(db,actor,org,q,body=None):
 """Build and authorize an explicit management scope; never infer across teams."""
 body=body if isinstance(body,dict) else {}
 workspace_id=_query_value(q,'workspaceId','workspace_id') or str(body.get('workspaceId') or body.get('workspace_id') or actor.get('workspace_id') or '').strip()
 team_id=_query_value(q,'teamId','team_id') or str(body.get('teamId') or body.get('team_id') or actor.get('team_id') or '').strip()
 if not workspace_id or not team_id:return None,'SCOPE_REQUIRED'
 with db.tx(False) as c:
  valid=c.execute("SELECT 1 FROM teams t JOIN workspaces w ON w.workspace_id=t.workspace_id WHERE t.team_id=? AND t.workspace_id=? AND t.organization_id=? AND t.status='active' AND w.status='active'",(team_id,workspace_id,org)).fetchone()
 if not valid:return None,'SCOPE_INVALID'
 scoped=dict(actor);scoped.update({'organization_id':org,'workspace_id':workspace_id,'team_id':team_id})
 if is_platform_admin(db,actor) or can(db,actor,'conversation.read.team',workspace_id=workspace_id,team_id=team_id,organization_id=org):
  scoped['_conversation_access']='team';return scoped,None
 if can(db,actor,'conversation.read.self',workspace_id=workspace_id,team_id=team_id,resource_user_id=actor.get('user_id'),organization_id=org):
  scoped['_conversation_access']='self';return scoped,None
 return None,'FORBIDDEN'

def _handle_conversations(h,m,seg,q,actor,db,org):
 if len(seg)<2 or seg[1]!='conversations':return False
 body=None
 if m=='POST':body=h.body()
 scoped,error=_conversation_actor(db,actor,org,q,body)
 if error=='SCOPE_REQUIRED':return _bad(h,'SCOPE_REQUIRED','必须指定工作区和团队',400)
 if error=='SCOPE_INVALID':return _bad(h,'SCOPE_INVALID','工作区或团队无效',400)
 if error:return _bad(h,'FORBIDDEN','无会话读取权限',403)
 if len(seg)==2 and m=='GET':result,status=list_conversations(db,scoped,q);return _send(h,result,status)
 if len(seg)<3:return _bad(h,'NOT_FOUND','会话接口不存在',404)
 conversation_id=seg[2]
 if len(seg)==3 and m=='GET':result,status=get_conversation(db,scoped,conversation_id);return _send(h,result,status)
 if len(seg)==4 and seg[3]=='messages' and m=='GET':
  raw=_query_value(q,'raw').lower() in ('1','true','yes')
  if raw and not (is_platform_admin(db,actor) or can(db,actor,'message.read.raw',workspace_id=scoped['workspace_id'],team_id=scoped['team_id'],organization_id=org)):
   return _bad(h,'FORBIDDEN','无消息原文读取权限',403)
  result,status=list_messages(db,scoped,conversation_id,q.get('limit',100),q.get('before'),raw,q.get('cursor'),_query_value(q,'direction'),_query_value(q,'contentType'));return _send(h,result,status)
 if len(seg)==4 and seg[3]=='recollect' and m=='POST':
  if not (is_platform_admin(db,actor) or can(db,actor,'conversation.recollect',workspace_id=scoped['workspace_id'],team_id=scoped['team_id'],organization_id=org)):
   return _bad(h,'FORBIDDEN','无删除并重新采集权限',403)
  if not isinstance(body,dict):return _bad(h,'INVALID_BODY','请求正文必须是对象',400)
  result,status=recollect_conversation(db,scoped,conversation_id,body);return _send(h,result,status)
 if len(seg)==4 and seg[3] in ('close','archive','reopen') and m=='POST':
  permission={'close':'conversation.close','archive':'conversation.archive','reopen':'conversation.manage'}[seg[3]]
  if not (is_platform_admin(db,actor) or can(db,actor,permission,workspace_id=scoped['workspace_id'],team_id=scoped['team_id'],organization_id=org)):
   return _bad(h,'FORBIDDEN','无会话状态管理权限',403)
  if not isinstance(body,dict):return _bad(h,'INVALID_BODY','请求正文必须是对象',400)
  result,status=transition_conversation(db,scoped,conversation_id,seg[3],body);return _send(h,result,status)
 return _bad(h,'NOT_FOUND','会话接口不存在',404)

def _handle_conversation_resources(h,m,seg,q,actor,db,org):
 """Contact timeline and message-content deletion share conversation scope rules."""
 is_timeline=len(seg)==4 and seg[1]=='contacts' and seg[3]=='timeline' and m=='GET'
 is_delete=(len(seg)==4 and seg[1]=='messages' and seg[3]=='content' and m=='DELETE') or (len(seg)==4 and seg[1]=='messages' and seg[3]=='delete-content' and m=='POST')
 if not is_timeline and not is_delete:return False
 body=h.body() if is_delete else None
 if is_delete and not isinstance(body,dict):return _bad(h,'INVALID_BODY','请求正文必须是对象',400)
 scoped,error=_conversation_actor(db,actor,org,q,body)
 if error=='SCOPE_REQUIRED':return _bad(h,'SCOPE_REQUIRED','必须指定工作区和团队',400)
 if error=='SCOPE_INVALID':return _bad(h,'SCOPE_INVALID','工作区或团队无效',400)
 if error:return _bad(h,'FORBIDDEN','无会话读取权限',403)
 if is_timeline:
  raw=_query_value(q,'raw').lower() in ('1','true','yes')
  if raw and not (is_platform_admin(db,actor) or can(db,actor,'message.read.raw',workspace_id=scoped['workspace_id'],team_id=scoped['team_id'],organization_id=org)):
   return _bad(h,'FORBIDDEN','无消息原文读取权限',403)
  result,status=list_contact_timeline(db,scoped,seg[2],q,raw);return _send(h,result,status)
 if not (is_platform_admin(db,actor) or can(db,actor,'message.delete.content',workspace_id=scoped['workspace_id'],team_id=scoped['team_id'],organization_id=org)):
  return _bad(h,'FORBIDDEN','无消息正文删除权限',403)
 result,status=delete_content(db,scoped,seg[2],body.get('reason'));return _send(h,result,status)

def _transfer_actor(db,actor,org,q,body,permission):
 body=body if isinstance(body,dict) else {}
 workspace_id=_query_value(q,'workspaceId','workspace_id') or str(body.get('workspaceId') or body.get('workspace_id') or actor.get('workspace_id') or '').strip()
 team_id=_query_value(q,'teamId','team_id') or str(body.get('teamId') or body.get('team_id') or actor.get('team_id') or '').strip()
 if not workspace_id or not team_id:return None,'SCOPE_REQUIRED'
 with db.tx(False) as c:
  valid=c.execute("SELECT 1 FROM teams t JOIN workspaces w ON w.workspace_id=t.workspace_id WHERE t.team_id=? AND t.workspace_id=? AND t.organization_id=? AND t.status='active' AND w.status='active'",(team_id,workspace_id,org)).fetchone()
 if not valid:return None,'SCOPE_INVALID'
 if not (is_platform_admin(db,actor) or can(db,actor,permission,workspace_id=workspace_id,team_id=team_id,organization_id=org)):
  return None,'FORBIDDEN'
 scoped=dict(actor);scoped.update({'organization_id':org,'workspace_id':workspace_id,'team_id':team_id})
 return scoped,None

def _handle_transfers(h,m,seg,q,actor,db,org):
 is_meta=len(seg)==2 and seg[1]=='transfer-meta' and m=='GET'
 is_collection=len(seg)>=2 and seg[1]=='transfers'
 is_legacy_create=len(seg)==4 and seg[1]=='contacts' and seg[3]=='transfers' and m=='POST'
 is_direct_create=len(seg)==2 and seg[1]=='transfers' and m=='POST'
 if not is_meta and not is_collection and not is_legacy_create:return False
 body=h.body() if m=='POST' else None
 action=seg[3] if len(seg)==4 and is_collection else ''
 permission='transfer.create' if (is_legacy_create or is_direct_create) else {'match':'transfer.match','confirm':'transfer.confirm','reject':'transfer.reject','cancel':'transfer.cancel.self','fail':'transfer.manage','expire':'transfer.manage'}.get(action,'transfer.read.team')
 scoped,error=_transfer_actor(db,actor,org,q,body,permission)
 if error=='SCOPE_REQUIRED':return _bad(h,'SCOPE_REQUIRED','必须指定工作区和团队',400)
 if error=='SCOPE_INVALID':return _bad(h,'SCOPE_INVALID','工作区或团队无效',400)
 if error and permission=='transfer.read.team':
  scoped,error=_transfer_actor(db,actor,org,q,body,'transfer.read.self')
  if not error:scoped['_transfer_access']='self'
 if error and action=='cancel':
  scoped,error=_transfer_actor(db,actor,org,q,body,'transfer.manage')
  if not error:scoped['_transfer_manage']=True
 if error:return _bad(h,'FORBIDDEN','无客户转交权限',403)
 if action=='cancel' and (is_platform_admin(db,actor) or can(db,actor,'transfer.manage',workspace_id=scoped['workspace_id'],team_id=scoped['team_id'],organization_id=org)):
  scoped['_transfer_manage']=True
 if is_meta:return _send(h,*transfer_meta(db,scoped))
 if is_legacy_create:return _send(h,*create_transfer(db,scoped,seg[2],body))
 if is_direct_create:
  if not isinstance(body,dict):return _bad(h,'INVALID_BODY','请求正文必须是对象',400)
  return _send(h,*create_transfer(db,scoped,str(body.get('contactId') or ''),body))
 if len(seg)==2 and m=='GET':return _send(h,*list_transfers(db,scoped,q))
 if len(seg)==3 and m=='GET':return _send(h,*get_transfer(db,scoped,seg[2]))
 if len(seg)==4 and m=='POST' and action in ('match','confirm','reject','cancel','fail','expire'):
  if action=='cancel':
   manageable=is_platform_admin(db,actor) or can(db,actor,'transfer.manage',workspace_id=scoped['workspace_id'],team_id=scoped['team_id'],organization_id=org)
   if not manageable:
    own=isinstance(body,dict) and can(db,actor,'transfer.cancel.self',workspace_id=scoped['workspace_id'],team_id=scoped['team_id'],organization_id=org)
    with db.tx(False) as c:row=c.execute('SELECT requested_by FROM contact_transfers WHERE transfer_id=? AND organization_id=? AND workspace_id=? AND team_id=?',(seg[2],org,scoped['workspace_id'],scoped['team_id'])).fetchone()
    if not own or not row or row['requested_by']!=actor['user_id']:return _bad(h,'FORBIDDEN','只能取消本人发起的待处理转交',403)
  elif action in ('fail','expire') and not (is_platform_admin(db,actor) or can(db,actor,'transfer.manage',workspace_id=scoped['workspace_id'],team_id=scoped['team_id'],organization_id=org)):
   return _bad(h,'FORBIDDEN','无转交管理权限',403)
  return _send(h,*transition_transfer(db,scoped,seg[2],action,body))
 return _bad(h,'NOT_FOUND','客户转交接口不存在',404)

def handle(h,m,seg,q,actor,db,org):
 if not seg or seg[0]!='contact-center':return False
 _platform_guard=is_platform_admin(db,actor)
 if org!=actor['organization_id'] and not _platform_guard:return _bad(h,'FORBIDDEN','企业范围不匹配',403)
 conversation_handled=_handle_conversations(h,m,seg,q,actor,db,org)
 if conversation_handled is not False:return conversation_handled
 resource_handled=_handle_conversation_resources(h,m,seg,q,actor,db,org)
 if resource_handled is not False:return resource_handled
 transfer_handled=_handle_transfers(h,m,seg,q,actor,db,org)
 if transfer_handled is not False:return transfer_handled
 if not _platform_guard and not _can_any_scope(db,actor,'contact.read',org):return _bad(h,'FORBIDDEN','无客户读取权限',403)
 identity_handled=handle_identity_admin(h,m,seg,q,actor,db,org)
 if identity_handled is not False:return identity_handled
 if len(seg)==2 and seg[1]=='meta' and m=='GET':return _send(h,meta(db,actor,org))
 if len(seg)==2 and seg[1]=='governance-queue' and m=='GET':return _send(h,governance_queue(db,actor,org,q))
 if len(seg)==2 and seg[1]=='follow-up-reminders' and m=='GET':return _send(h,follow_up_reminders(db,actor,org,q))
 if len(seg)==2 and seg[1]=='notification-subscriptions':
  if m=='GET':return _send(h,*notification_subscription_settings(db,actor,org))
  if m=='PUT':return _send(h,*save_notification_subscriptions(db,actor,org,h.body()))
  return _bad(h,'METHOD_NOT_ALLOWED','不支持的通知代管操作',405)
 if len(seg)==2 and seg[1]=='follow-up-notifications' and m=='GET':return _send(h,*list_notifications(db,actor,q,org))
 if len(seg)==3 and seg[1]=='follow-up-notifications' and seg[2]=='summary' and m=='GET':return _send(h,*notification_summary(db,actor,org))
 if len(seg)==3 and seg[1]=='follow-up-notifications' and seg[2]=='poll' and m=='POST':return _send(h,*poll_notifications(db,actor,h.body(),org))
 if len(seg)==4 and seg[1]=='follow-up-notifications' and seg[3] in ('read','snooze','dismiss','complete') and m=='POST':return _send(h,*receipt_action(db,actor,seg[2],seg[3],h.body(),org))
 if len(seg)==2 and seg[1]=='preferences':
  if m=='GET':return _send(h,get_preferences(db,actor,org))
  if m=='PATCH':
   err,result=save_preferences(db,actor,org,h.body())
   if err=='PREFERENCES_VERSION_CONFLICT':return _send(h,result,409)
   return _bad(h,'INVALID_PREFERENCES','列表偏好格式不合法',400) if err else _send(h,result)
  return _bad(h,'NOT_FOUND','客户管理中心接口不存在',404)
 if len(seg)>=2 and seg[1]=='contacts':
  if len(seg)==2 and m=='GET':return _send(h,listing(db,actor,org,q))
  cid=seg[2] if len(seg)>2 else None
  if cid and len(seg)==3 and m=='GET':
   item=detail(db,actor,org,cid);return _send(h,{'ok':True,'item':item}) if item else _bad(h,'NOT_FOUND','客户不存在或无权访问',404)
  with db.tx(False) as c:
   editable=_allowed(c,actor,org,cid) if cid else None
  if not editable:return _bad(h,'NOT_FOUND','客户不存在或无权访问',404)
  b=h.body()
  if cid and len(seg)==3 and m=='DELETE':
   err,item=delete_contact(db,actor,org,cid,b)
   delete_codes={'INVALID_BODY':('INVALID_BODY','请求正文必须是对象',400),'VERSION_REQUIRED':('BASE_VERSION_REQUIRED','必须提供联系人版本',400),'DELETE_REASON_REQUIRED':('DELETE_REASON_REQUIRED','必须填写删除原因',400),'DELETE_REASON_TOO_LONG':('DELETE_REASON_TOO_LONG','删除原因不能超过 500 个字符',400),'NOT_FOUND':('NOT_FOUND','客户不存在或无权访问',404),'FORBIDDEN':('FORBIDDEN','无客户删除权限',403),'CONFLICT':('CONTACT_VERSION_CONFLICT','客户资料已被其他用户更新，请刷新后重试',409)}
   if err:return _bad(h,*delete_codes[err])
   return _send(h,{'ok':True,'contactId':cid,'version':item.get('version'),'deletedAt':item.get('deleted_at')})
  auth_context={'workspace_id':editable.get('workspace_id'),'team_id':editable.get('team_id'),'resource_user_id':editable.get('owner_user_id'),'organization_id':org}
  can_full_update=_platform_guard or can(db,actor,'contact.update',**auth_context)
  can_assigned_update=False if can_full_update else can(db,actor,'contact.update.assigned',**auth_context)
  if not _can_update_contact(actor,editable,can_full_update,can_assigned_update):return _bad(h,'FORBIDDEN','无客户修改权限',403)
  if cid and len(seg)==3 and m=='PATCH':err,item=update_basic(db,actor,org,cid,b)
  elif cid and len(seg)==4 and seg[3]=='tags' and m=='PATCH':err,item=update_tags(db,actor,org,cid,b)
  elif cid and len(seg)==4 and seg[3]=='fields' and m=='PATCH':err,item=update_fields(db,actor,org,cid,b)
  elif cid and len(seg)==4 and seg[3]=='workbench' and m=='PATCH':
   result=update_workbench(db,actor,org,cid,b)
   status=int(result.pop('status',200 if result.get('ok') else 400))
   return _send(h,result,status)
  else:return _bad(h,'NOT_FOUND','客户管理中心接口不存在',404)
  codes={'NOT_FOUND':('NOT_FOUND','客户不存在或无权访问',404),'VERSION_REQUIRED':('BASE_VERSION_REQUIRED','必须提供联系人版本',400),'CONFLICT':('CONTACT_VERSION_CONFLICT','客户资料已被其他用户更新，请刷新后重试',409),'FIELD_TOO_LONG':('CONTACT_FIELD_TOO_LONG','字段内容超过长度限制',400),'INVALID_TAG':('INVALID_TAG','标签不存在、未启用或类型不匹配',400),'INVALID_FIELDS':('INVALID_FIELDS','字段值必须是对象',400),'INVALID_FIELD':('INVALID_FIELD','字段不存在或未启用',400),'INVALID_OPTION':('INVALID_FIELD_OPTION','字段选项不合法',400)}
  if err:return _bad(h,*codes[err])
  return _send(h,{'ok':True,'item':item})
 return _bad(h,'NOT_FOUND','客户管理中心接口不存在',404)
