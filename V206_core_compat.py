# -*- coding: utf-8 -*-
"""V206 核心业务；兼容 API 205 与 Schema 205。"""
from __future__ import annotations
import hashlib,re,secrets,uuid,sqlite3
from V207_shared_db import now_ms,dumps,loads
VERSION="206.0.7"; SCHEMA_VERSION=205; CHANNELS={"whatsapp","instagram","facebook","messenger","telegram","other"}
OBS_KEYS={"displayName","observedPhone","avatarUrl","observed"}; MANUAL={"manualName":"manual_name","manualPhone":"manual_phone","remark":"remark","status":"status","business":"business_json"}
TRANSIENT={"capturedAt","scanAt","observedAt","requestId","sessionTimestamp","timestamp"}
def uid(p):return p+"_"+uuid.uuid4().hex
def hash_obj(v):return hashlib.sha256(dumps(v).encode()).hexdigest()
def ok(**kw):return dict(ok=True,**kw),200
def err(code,message,status=400,**kw):return dict(ok=False,code=code,message=message,**kw),status
def stable(v):
 if isinstance(v,dict):return {k:stable(x) for k,x in sorted(v.items()) if k not in TRANSIENT}
 if isinstance(v,list):return [stable(x) for x in v]
 return v
def workspace(c,wid):return c.execute("SELECT * FROM workspaces WHERE workspace_id=? AND status='active'",(wid,)).fetchone()
def public_device(r):
 if not r:return None
 d=dict(r);d["metadata"]=loads(d.pop("metadata_json"),{}) or {};return d
def public_source(r):
 if not r:return None
 d=dict(r);d["metadata"]=loads(d.pop("metadata_json"),{}) or {};return d
def public_contact(c,r):
 if not r:return None
 d=dict(r);d["observed"]=loads(d.pop("observed_json"),{}) or {};d["business"]=loads(d.pop("business_json"),{}) or {}
 d["tags"]=[dict(x) for x in c.execute("SELECT t.* FROM tags t JOIN contact_tags ct ON t.tag_id=ct.tag_id WHERE ct.contact_id=? ORDER BY t.sort_order,t.name",(d["contact_id"],))]
 d["customFields"]={x[0]:loads(x[1]) for x in c.execute("SELECT field_key,value_json FROM contact_custom_values WHERE contact_id=?",(d["contact_id"],))}
 s=c.execute("SELECT * FROM sources WHERE source_id=?",(d["source_id"],)).fetchone();dev=c.execute("SELECT * FROM devices WHERE device_id=?",(d["last_observed_device_id"],)).fetchone() if d["last_observed_device_id"] else None
 d["workspace"]={"workspace_id":d["workspace_id"],"name":c.execute("SELECT name FROM workspaces WHERE workspace_id=?",(d["workspace_id"],)).fetchone()[0]}
 d["source"]={k:s[k] for k in ("source_id","source_name","channel","account_identity")} if s else None
 d["lastObservedDevice"]={k:dev[k] for k in ("device_id","device_name","computer_name","installation_id")} if dev else None
 return d
def register_device(db,p):
 wid=str(p.get("workspace_id") or "default");did=str(p.get("device_id") or "").strip();iid=str(p.get("installation_id") or "").strip();name=str(p.get("device_name") or "").strip()[:120];computer=str(p.get("computer_name") or "").strip()[:120]
 if not did or not iid or not name:return err("INVALID_DEVICE","device_id、installation_id 和 device_name 必填")
 with db.tx() as c:
  if not workspace(c,wid):return err("WORKSPACE_NOT_FOUND","工作区不存在",404)
  by_i=c.execute("SELECT * FROM devices WHERE workspace_id=? AND installation_id=?",(wid,iid)).fetchone();by_d=c.execute("SELECT * FROM devices WHERE device_id=?",(did,)).fetchone()
  if by_i and by_i["device_id"]!=did:return err("INSTALLATION_CONFLICT","安装实例已绑定其他设备",409)
  if by_d and (by_d["workspace_id"]!=wid or by_d["installation_id"]!=iid):return err("DEVICE_ID_CONFLICT","设备 ID 已被其他安装实例使用",409)
  t=now_ms();c.execute("INSERT INTO devices VALUES(?,?,?,?,?,'active',?,?,?) ON CONFLICT(device_id) DO UPDATE SET device_name=excluded.device_name,computer_name=excluded.computer_name,last_seen_at=excluded.last_seen_at,metadata_json=excluded.metadata_json",(did,wid,iid,name,computer,t,t,dumps(p.get("metadata") or {})))
  r=c.execute("SELECT * FROM devices WHERE device_id=?",(did,)).fetchone()
  if r["status"]!='active':return err("DEVICE_DISABLED","设备已禁用",403)
  return ok(device=public_device(r))
def touch_relation(c,wid,sid,did,op,observe=False):
 t=now_ms();c.execute("INSERT INTO source_devices(workspace_id,source_id,device_id,first_seen_at,last_seen_at,event_count,contact_observe_count,last_operation) VALUES(?,?,?,?,?,1,?,?) ON CONFLICT(workspace_id,source_id,device_id) DO UPDATE SET last_seen_at=excluded.last_seen_at,event_count=source_devices.event_count+1,contact_observe_count=source_devices.contact_observe_count+excluded.contact_observe_count,last_operation=excluded.last_operation",(wid,sid,did,t,t,1 if observe else 0,op))
def register_source(db,p):
 wid=str(p.get("workspace_id") or "default");did=str(p.get("device_id") or "");ch=str(p.get("channel") or "").lower().strip();ai=str(p.get("account_identity") or "").strip()[:240];name=str(p.get("source_name") or ai).strip()[:120]
 if ch not in CHANNELS:return err("INVALID_CHANNEL","渠道不在 V205 支持列表中")
 if not ai:return err("INVALID_ACCOUNT_IDENTITY","账号身份不能为空")
 with db.tx() as c:
  dev=c.execute("SELECT * FROM devices WHERE device_id=? AND workspace_id=? AND status='active'",(did,wid)).fetchone()
  if not dev:return err("DEVICE_NOT_FOUND","设备不存在或已禁用",404)
  old=c.execute("SELECT * FROM sources WHERE workspace_id=? AND channel=? AND account_identity=?",(wid,ch,ai)).fetchone();sid=old["source_id"] if old else uid("src");t=now_ms()
  c.execute("INSERT INTO sources VALUES(?,?,?,?,?,'active',?,?,?,?) ON CONFLICT(workspace_id,channel,account_identity) DO UPDATE SET source_name=excluded.source_name,last_seen_at=excluded.last_seen_at,last_device_id=excluded.last_device_id,metadata_json=excluded.metadata_json",(sid,wid,ch,ai,name,t,t,did,dumps(p.get("metadata") or {})))
  touch_relation(c,wid,sid,did,"source.register")
  src=c.execute("SELECT * FROM sources WHERE source_id=?",(sid,)).fetchone();ws=c.execute("SELECT * FROM workspaces WHERE workspace_id=?",(wid,)).fetchone()
  return ok(workspace={"workspace_id":wid,"name":ws["name"]},source=public_source(src),device=public_device(dev))
def context(db,wid,did,sid=None):
 with db.tx(False) as c:
  ws=workspace(c,wid);dev=c.execute("SELECT * FROM devices WHERE device_id=? AND workspace_id=?",(did,wid)).fetchone();src=c.execute("SELECT * FROM sources WHERE source_id=? AND workspace_id=?",(sid,wid)).fetchone() if sid else None
  if not ws:return err("WORKSPACE_NOT_FOUND","工作区不存在",404)
  if not dev:return err("DEVICE_NOT_FOUND","设备不存在",404)
  if sid and not src:return err("SOURCE_NOT_FOUND","来源不存在",404)
  return ok(version=VERSION,schemaVersion=SCHEMA_VERSION,workspace={"workspace_id":wid,"name":ws["name"]},source=public_source(src),device=public_device(dev))
def add_change(c,wid,typ,eid,op,ver,sid,did,payload,event):c.execute("INSERT INTO changes(workspace_id,entity_type,entity_id,operation,version,source_id,device_id,changed_at,payload_json,event_id) VALUES(?,?,?,?,?,?,?,?,?,?)",(wid,typ,eid,op,ver,sid,did,now_ms(),dumps(payload),event))
def apply_event(db,e):
 if len(dumps(e).encode("utf-8"))>262144:return err("EVENT_TOO_LARGE","单事件不能超过 256 KB",413)
 for k in ("eventId","workspaceId","deviceId","installationId","entityType","operation"):
  if not e.get(k):return err("INVALID_EVENT","缺少必填事件字段："+k)
 eid=str(e["eventId"]);wid=str(e["workspaceId"]);did=str(e["deviceId"]);sid=str(e.get("sourceId") or "");p=e.get("payload") or {};ph=hash_obj({k:e.get(k) for k in ("workspaceId","deviceId","installationId","sourceId","entityType","entityId","operation","baseVersion")} | {"payload":p})
 with db.tx() as c:
  old=c.execute("SELECT payload_hash,result_json FROM events WHERE event_id=?",(eid,)).fetchone()
  if old:
   if old[0]!=ph:return err("EVENT_ID_REUSED","eventId 已被不同载荷使用",409)
   x=loads(old[1],{}) or {};status=int(x.pop("_http",200));x["idempotentReplay"]=True;return x,status
  dev=c.execute("SELECT * FROM devices WHERE device_id=? AND workspace_id=? AND status='active'",(did,wid)).fetchone()
  if not dev:return err("DEVICE_NOT_FOUND","设备不存在或已禁用",404)
  if str(e.get("installationId") or "")!=str(dev["installation_id"]):return err("INSTALLATION_MISMATCH","事件安装实例与注册设备不一致",409)
  src=c.execute("SELECT * FROM sources WHERE source_id=? AND workspace_id=? AND status='active'",(sid,wid)).fetchone() if sid else None
  if sid and not src:return err("SOURCE_NOT_FOUND","来源不存在或已禁用",404)
  t=now_ms();c.execute("INSERT INTO events(event_id,workspace_id,device_id,installation_id,source_id,session_id,request_id,entity_type,entity_id,operation,base_version,payload_json,payload_hash,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'processing',?)",(eid,wid,did,e.get("installationId"),sid or None,e.get("sessionId"),e.get("requestId"),e["entityType"],e.get("entityId"),e["operation"],e.get("baseVersion"),dumps(p),ph,t))
  if e["entityType"]!="contact":result,status=err("UNSUPPORTED_ENTITY","V205.0 仅支持 contact 事件")
  else:result,status=_contact(c,e,dev,src)
  stored=dict(result);stored["_http"]=status;c.execute("UPDATE events SET status=?,result_version=?,error_code=?,applied_at=?,result_json=? WHERE event_id=?",("applied" if result.get("ok") else "rejected",result.get("version"),result.get("code"),now_ms(),dumps(stored),eid));return result,status
def _contact(c,e,dev,src):
 wid=e["workspaceId"];did=e["deviceId"];sid=e.get("sourceId");op=e["operation"];p=e.get("payload") or {};eid=e["eventId"]
 row=c.execute("SELECT * FROM contacts WHERE contact_id=? AND workspace_id=?",(e.get("entityId"),wid)).fetchone() if e.get("entityId") else None
 if op=="contact.observe":
  ch=str(p.get("channel") or "").lower();ext=str(p.get("externalContactId") or "")
  if not src or not ext:return err("INVALID_OBSERVATION","观察事件缺少有效来源或外部联系人 ID")
  if ch!=src["channel"]:return err("CHANNEL_MISMATCH","事件渠道与来源渠道不一致",409)
  row=c.execute("SELECT * FROM contacts WHERE workspace_id=? AND source_id=? AND channel=? AND external_contact_id=?",(wid,sid,ch,ext)).fetchone();obs={k:(stable(p.get(k)) if k=="observed" else p.get(k)) for k in OBS_KEYS if k in p};oh=hash_obj(obs);t=now_ms();touch_relation(c,wid,sid,did,op,True);c.execute("UPDATE sources SET last_seen_at=?,last_device_id=? WHERE source_id=?",(t,did,sid))
  if not row:
   cid=uid("ct");c.execute("INSERT INTO contacts(contact_id,workspace_id,source_id,channel,external_contact_id,display_name,observed_phone,avatar_url,observed_json,observation_hash,last_observed_device_id,last_observed_at,created_at,updated_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(cid,wid,sid,ch,ext,str(p.get("displayName") or ""),str(p.get("observedPhone") or ""),str(p.get("avatarUrl") or ""),dumps(stable(p.get("observed") or {})),oh,did,t,t,t,t));ver=1;action="create"
  else:
   cid=row["contact_id"]
   if row["observation_hash"]==oh:
    device_changed=str(row["last_observed_device_id"] or "")!=str(did);c.execute("UPDATE contacts SET last_observed_device_id=?,last_observed_at=?,last_seen_at=? WHERE contact_id=?",(did,t,t,cid));data=public_contact(c,c.execute("SELECT * FROM contacts WHERE contact_id=?",(cid,)).fetchone())
    if device_changed:add_change(c,wid,"contact",cid,"observe-device",row["version"],sid,did,data,eid)
    return dict(ok=True,eventId=eid,entityId=cid,version=row["version"],unchanged=True,deviceChanged=device_changed,contact=data),200
   ver=row["version"]+1;c.execute("UPDATE contacts SET display_name=?,observed_phone=?,avatar_url=?,observed_json=?,observation_hash=?,last_observed_device_id=?,last_observed_at=?,version=?,updated_at=?,last_seen_at=? WHERE contact_id=?",(str(p.get("displayName") or ""),str(p.get("observedPhone") or ""),str(p.get("avatarUrl") or ""),dumps(stable(p.get("observed") or {})),oh,did,t,ver,t,t,cid));action="observe"
  data=public_contact(c,c.execute("SELECT * FROM contacts WHERE contact_id=?",(cid,)).fetchone());add_change(c,wid,"contact",cid,action,ver,sid,did,data,eid);return dict(ok=True,eventId=eid,entityId=cid,version=ver,contact=data),200
 if not row:return err("CONTACT_NOT_FOUND","联系人不存在",404)
 if not sid or str(sid)!=str(row["source_id"]):return err("SOURCE_CONTEXT_MISMATCH","事件来源与联系人来源不一致",409)
 if e.get("baseVersion") is None or int(e["baseVersion"])!=row["version"]:return err("VERSION_CONFLICT","联系人版本冲突",409,currentVersion=row["version"],current=public_contact(c,row))
 cid=row["contact_id"];before=public_contact(c,row);t=now_ms();ver=row["version"]+1
 if op=="contact.patch":
  sets=[];vals=[]
  for api,col in MANUAL.items():
   if api in p:sets.append(col+"=?");vals.append(dumps(p[api] or {}) if col=="business_json" else str(p[api] or ""))
  custom=p.get("customFields") if isinstance(p.get("customFields"),dict) else {}
  if not sets and not custom:return err("EMPTY_PATCH","没有可修改的人工字段")
  for key,value in custom.items():
   key=str(key)
   if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}",key):return err("INVALID_CUSTOM_FIELD","自定义字段键无效")
   fd=c.execute("SELECT field_type,enabled FROM custom_field_definitions WHERE workspace_id=? AND field_key=?",(wid,key)).fetchone()
   if not fd or not fd["enabled"]:return err("FIELD_NOT_DEFINED","自定义字段未定义或已停用",400,fieldKey=key)
   typ=fd["field_type"]
   mismatch=(typ=="number" and (isinstance(value,bool) or not isinstance(value,(int,float)))) or (typ=="boolean" and not isinstance(value,bool)) or (typ in ("text","date") and not isinstance(value,str))
   if mismatch:return err("FIELD_TYPE_MISMATCH","自定义字段类型不匹配",400,fieldKey=key,expectedType=typ)
   c.execute("INSERT INTO contact_custom_values VALUES(?,?,?,?,?) ON CONFLICT(contact_id,field_key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at,updated_by=excluded.updated_by",(cid,key,dumps(value),t,did))
  sets.extend(["version=?","updated_at=?"]);vals.extend([ver,t,cid]);c.execute("UPDATE contacts SET "+",".join(sets)+" WHERE contact_id=?",vals);action="patch"
 elif op=="contact.delete":
  q=c.execute("SELECT * FROM delete_confirmations WHERE confirmation_id=? AND workspace_id=? AND entity_id=?",(str(p.get("confirmationId") or ""),wid,cid)).fetchone()
  if not q or q["used_at"] or q["expires_at"]<t or q["expected_version"]!=row["version"]:return err("INVALID_CONFIRMATION","删除确认凭证无效、过期或已使用",409)
  c.execute("UPDATE delete_confirmations SET used_at=? WHERE confirmation_id=?",(t,q["confirmation_id"]));c.execute("UPDATE contacts SET deleted_at=?,deleted_by=?,delete_reason=?,version=?,updated_at=? WHERE contact_id=?",(t,did,str(p.get("reason") or ""),ver,t,cid));action="delete"
 elif op=="contact.restore":
  if row["deleted_at"] is None:return err("NOT_DELETED","联系人未被删除",409)
  c.execute("UPDATE contacts SET deleted_at=NULL,deleted_by=NULL,delete_reason=NULL,version=?,updated_at=? WHERE contact_id=?",(ver,t,cid));action="restore"
 else:return err("UNSUPPORTED_OPERATION","不支持的联系人操作")
 touch_relation(c,wid,sid or row["source_id"],did,op);after=public_contact(c,c.execute("SELECT * FROM contacts WHERE contact_id=?",(cid,)).fetchone());add_change(c,wid,"contact",cid,action,ver,row["source_id"],did,after,eid);c.execute("INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(wid,did,did,action,"contact",cid,dumps(before),dumps(after),str(p.get("reason") or ""),t));return dict(ok=True,eventId=eid,entityId=cid,version=ver,contact=after),200
def delete_preview(db,wid,did,cid,version):
 with db.tx() as c:
  if not c.execute("SELECT 1 FROM devices WHERE device_id=? AND workspace_id=? AND status='active'",(did,wid)).fetchone():return err("DEVICE_NOT_FOUND","设备不存在或已禁用",404)
  r=c.execute("SELECT * FROM contacts WHERE contact_id=? AND workspace_id=?",(cid,wid)).fetchone()
  if not r:return err("CONTACT_NOT_FOUND","联系人不存在",404)
  if int(version)!=r["version"]:return err("VERSION_CONFLICT","联系人版本冲突",409,currentVersion=r["version"])
  x="del_"+secrets.token_hex(16);impact=hash_obj({"contactId":cid,"version":version});exp=now_ms()+300000;c.execute("INSERT INTO delete_confirmations VALUES(?,?,?,?,?,?,?,?,?)",(x,wid,"contact",cid,int(version),impact,exp,None,did));return ok(confirmationId=x,expectedVersion=int(version),impact={"contactId":cid,"softDelete":True},expiresAt=exp)
def list_contacts(db,qs):
 wid=str(qs.get("workspace_id") or "default");limit=min(max(int(qs.get("limit") or 200),1),1000);after=max(int(qs.get("cursor") or qs.get("after_id") or 0),0);where=["c.workspace_id=?","c.rowid>?"];args=[wid,after]
 if not str(qs.get("include_deleted") or "").lower() in ("1","true"):where.append("c.deleted_at IS NULL")
 for key,col in (("source_id","c.source_id"),("channel","c.channel"),("device_id","c.last_observed_device_id")):
  if qs.get(key):where.append(col+"=?");args.append(str(qs[key]))
 if qs.get("updated_after"):where.append("c.updated_at>?");args.append(int(qs["updated_after"]))
 if qs.get("search"):where.append("(c.display_name LIKE ? OR c.manual_name LIKE ? OR c.observed_phone LIKE ? OR c.manual_phone LIKE ? OR c.remark LIKE ?)");q="%"+str(qs["search"])+"%";args.extend([q]*5)
 with db.tx(False) as c:
  rows=c.execute("SELECT c.rowid AS _cursor,c.* FROM contacts c WHERE "+" AND ".join(where)+" ORDER BY c.rowid LIMIT ?",args+[limit+1]).fetchall();more=len(rows)>limit;rows=rows[:limit];items=[public_contact(c,r) for r in rows];nxt=rows[-1]["_cursor"] if rows else after;return ok(items=items,page={"limit":limit,"next_cursor":nxt,"has_more":more})
def changes(db,wid,after=0,limit=500):
 limit=min(max(int(limit),1),2000)
 with db.tx(False) as c:
  rows=c.execute("SELECT * FROM changes WHERE workspace_id=? AND change_id>? ORDER BY change_id LIMIT ?",(wid,int(after),limit)).fetchall();items=[]
  for r in rows:d=dict(r);d["payload"]=loads(d.pop("payload_json"),{});items.append(d)
  return ok(items=items,nextCursor=items[-1]["change_id"] if items else int(after),hasMore=len(items)==limit)


def get_workspace(db,wid="default"):
 with db.tx(False) as c:
  r=c.execute("SELECT * FROM workspaces WHERE workspace_id=?",(wid,)).fetchone()
  return ok(workspace=dict(r)) if r else err("WORKSPACE_NOT_FOUND","工作区不存在",404)
def update_workspace(db,wid,p):
 name=str(p.get("name") or "").strip()[:120]
 if not name:return err("INVALID_WORKSPACE","工作区名称不能为空")
 with db.tx() as c:
  if not c.execute("SELECT 1 FROM workspaces WHERE workspace_id=?",(wid,)).fetchone():return err("WORKSPACE_NOT_FOUND","工作区不存在",404)
  c.execute("UPDATE workspaces SET name=?,updated_at=? WHERE workspace_id=?",(name,now_ms(),wid));return ok(workspace=dict(c.execute("SELECT * FROM workspaces WHERE workspace_id=?",(wid,)).fetchone()))
def list_sources(db,wid="default"):
 with db.tx(False) as c:return ok(items=[public_source(x) for x in c.execute("SELECT * FROM sources WHERE workspace_id=? ORDER BY source_name,channel",(wid,))])
def list_source_devices(db,wid="default",sid=None):
 q="SELECT sd.*,s.source_name,s.channel,s.account_identity,d.device_name,d.computer_name,d.installation_id,d.status AS device_status FROM source_devices sd JOIN sources s ON s.source_id=sd.source_id JOIN devices d ON d.device_id=sd.device_id WHERE sd.workspace_id=?";a=[wid]
 if sid:q+=" AND sd.source_id=?";a.append(sid)
 q+=" ORDER BY sd.last_seen_at DESC"
 with db.tx(False) as c:return ok(items=[dict(x) for x in c.execute(q,a)])
def get_contact(db,wid,cid):
 with db.tx(False) as c:
  r=c.execute("SELECT * FROM contacts WHERE workspace_id=? AND contact_id=?",(wid,cid)).fetchone();return ok(contact=public_contact(c,r)) if r else err("CONTACT_NOT_FOUND","联系人不存在",404)


def list_devices(db,wid="default"):
 with db.tx(False) as c:return ok(items=[public_device(x) for x in c.execute("SELECT * FROM devices WHERE workspace_id=? ORDER BY status,device_name",(wid,))])
def set_device_status(db,wid,did,status):
 status=str(status or '').lower()
 if status not in ('active','disabled'):return err('INVALID_STATUS','设备状态只能是 active 或 disabled')
 with db.tx() as c:
  r=c.execute("SELECT * FROM devices WHERE workspace_id=? AND device_id=?",(wid,did)).fetchone()
  if not r:return err('DEVICE_NOT_FOUND','设备不存在',404)
  c.execute("UPDATE devices SET status=?,last_seen_at=? WHERE workspace_id=? AND device_id=?",(status,now_ms(),wid,did));return ok(device=public_device(c.execute("SELECT * FROM devices WHERE device_id=?",(did,)).fetchone()))
def set_source_status(db,wid,sid,status):
 status=str(status or '').lower()
 if status not in ('active','disabled'):return err('INVALID_STATUS','来源状态只能是 active 或 disabled')
 with db.tx() as c:
  r=c.execute("SELECT * FROM sources WHERE workspace_id=? AND source_id=?",(wid,sid)).fetchone()
  if not r:return err('SOURCE_NOT_FOUND','来源不存在',404)
  c.execute("UPDATE sources SET status=?,last_seen_at=? WHERE workspace_id=? AND source_id=?",(status,now_ms(),wid,sid));return ok(source=public_source(c.execute("SELECT * FROM sources WHERE source_id=?",(sid,)).fetchone()))
def list_tags(db,wid='default'):
 with db.tx(False) as c:return ok(items=[dict(x) for x in c.execute("SELECT * FROM tags WHERE workspace_id=? ORDER BY sort_order,name",(wid,))])
def save_tag(db,wid,p):
 tid=str(p.get('tag_id') or '').strip() or uid('tag');name=str(p.get('name') or '').strip()[:80]
 if not name:return err('INVALID_TAG','标签名称不能为空')
 t=now_ms()
 with db.tx() as c:
  try:c.execute("INSERT INTO tags VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(tag_id) DO UPDATE SET name=excluded.name,color=excluded.color,category=excluded.category,sort_order=excluded.sort_order,enabled=excluded.enabled,updated_at=excluded.updated_at",(tid,wid,name,str(p.get('color') or '#64748b')[:20],str(p.get('category') or '')[:80],int(p.get('sort_order') or 0),1 if p.get('enabled',True) else 0,t,t))
  except sqlite3.IntegrityError:return err('TAG_EXISTS','标签名称已存在',409)
  return ok(tag=dict(c.execute("SELECT * FROM tags WHERE tag_id=?",(tid,)).fetchone()))
def delete_tag(db,wid,tid):
 with db.tx() as c:
  if not c.execute("SELECT 1 FROM tags WHERE tag_id=? AND workspace_id=?",(tid,wid)).fetchone():return err('TAG_NOT_FOUND','标签不存在',404)
  used=int(c.execute("SELECT COUNT(*) FROM contact_tags WHERE tag_id=?",(tid,)).fetchone()[0])
  if used:return err('TAG_IN_USE','标签仍被联系人使用，请先解除联系人标签关系',409,contactCount=used)
  c.execute("DELETE FROM tags WHERE tag_id=? AND workspace_id=?",(tid,wid));return ok(deleted=True)
def list_field_definitions(db,wid='default'):
 with db.tx(False) as c:return ok(items=[dict(x) for x in c.execute("SELECT * FROM custom_field_definitions WHERE workspace_id=? ORDER BY sort_order,field_key",(wid,))])
def save_field_definition(db,wid,p):
 key=str(p.get('field_key') or '').strip()
 if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}',key):return err('INVALID_FIELD_KEY','字段键名无效')
 typ=str(p.get('field_type') or 'text')
 if typ not in ('text','number','date','boolean','json'):return err('INVALID_FIELD_TYPE','字段类型无效')
 t=now_ms()
 with db.tx() as c:
  c.execute("INSERT INTO custom_field_definitions VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(workspace_id,field_key) DO UPDATE SET label=excluded.label,field_type=excluded.field_type,sort_order=excluded.sort_order,enabled=excluded.enabled,updated_at=excluded.updated_at",(wid,key,str(p.get('label') or key)[:120],typ,int(p.get('sort_order') or 0),1 if p.get('enabled',True) else 0,t,t));return ok(field=dict(c.execute("SELECT * FROM custom_field_definitions WHERE workspace_id=? AND field_key=?",(wid,key)).fetchone()))
def delete_field_definition(db,wid,key):
 with db.tx() as c:
  if not c.execute("SELECT 1 FROM custom_field_definitions WHERE workspace_id=? AND field_key=?",(wid,key)).fetchone():return err('FIELD_NOT_FOUND','字段定义不存在',404)
  c.execute("DELETE FROM custom_field_definitions WHERE workspace_id=? AND field_key=?",(wid,key));return ok(deleted=True)
def set_contact_tags(db,wid,cid,tag_ids,did,base_version):
 if not isinstance(tag_ids,list):return err('INVALID_TAGS','tag_ids 必须是数组')
 if base_version is None:return err('BASE_VERSION_REQUIRED','base_version 必填')
 try:base_version=int(base_version)
 except (TypeError,ValueError):return err('INVALID_BASE_VERSION','base_version 必须是整数')
 did=str(did or '').strip()
 if not did:return err('DEVICE_ID_REQUIRED','device_id 必填')
 with db.tx() as c:
  dev=c.execute("SELECT 1 FROM devices WHERE workspace_id=? AND device_id=? AND status='active'",(wid,did)).fetchone()
  if not dev:return err('DEVICE_NOT_FOUND','设备不存在或已禁用',404)
  row=c.execute("SELECT * FROM contacts WHERE workspace_id=? AND contact_id=?",(wid,cid)).fetchone()
  if not row:return err('CONTACT_NOT_FOUND','联系人不存在',404)
  if row['deleted_at'] is not None:return err('CONTACT_DELETED','联系人已删除',409)
  if base_version!=int(row['version']):return err('VERSION_CONFLICT','联系人版本冲突',409,currentVersion=row['version'],current=public_contact(c,row))
  ids=[];seen=set()
  for value in tag_ids:
   tid=str(value or '').strip()
   if not tid or tid in seen:continue
   tag=c.execute("SELECT 1 FROM tags WHERE workspace_id=? AND tag_id=? AND enabled=1",(wid,tid)).fetchone()
   if not tag:return err('TAG_NOT_FOUND','标签不存在或已停用',404,tagId=tid)
   seen.add(tid);ids.append(tid)
  old_ids=sorted(x['tag_id'] for x in c.execute("SELECT tag_id FROM contact_tags WHERE contact_id=?",(cid,)).fetchall())
  if old_ids==sorted(ids):return ok(unchanged=True,version=row['version'],contact=public_contact(c,row),tagIds=ids)
  before=public_contact(c,row);t=now_ms();ver=int(row['version'])+1
  c.execute("DELETE FROM contact_tags WHERE contact_id=?",(cid,))
  for tid in ids:c.execute("INSERT INTO contact_tags VALUES(?,?,?)",(cid,tid,t))
  c.execute("UPDATE contacts SET version=?,updated_at=? WHERE workspace_id=? AND contact_id=?",(ver,t,wid,cid))
  current=c.execute("SELECT * FROM contacts WHERE workspace_id=? AND contact_id=?",(wid,cid)).fetchone();after=public_contact(c,current);event='tags_'+uuid.uuid4().hex
  add_change(c,wid,'contact',cid,'tags',ver,row['source_id'],did,after,event)
  c.execute("INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(wid,did,did,'tags','contact',cid,dumps(before),dumps(after),'联系人标签调整',t))
  return ok(changed=True,version=ver,contact=after,tagIds=ids)


# ===== V205 综合管理后台专用业务（保持 Changes 与审计闭环） =====
def admin_patch_contact(db,wid,cid,p):
 actor=str(p.get('actor_id') or 'admin')[:120]
 with db.tx() as c:
  row=c.execute("SELECT * FROM contacts WHERE workspace_id=? AND contact_id=?",(wid,cid)).fetchone()
  if not row:return err('CONTACT_NOT_FOUND','联系人不存在',404)
  if row['deleted_at'] is not None:return err('CONTACT_DELETED','联系人已在回收站',409)
  try:base=int(p.get('base_version'))
  except (TypeError,ValueError):return err('BASE_VERSION_REQUIRED','base_version 必须是整数')
  if base!=int(row['version']):return err('VERSION_CONFLICT','联系人版本冲突，请刷新后重试',409,currentVersion=row['version'],current=public_contact(c,row))
  before=public_contact(c,row); sets=[];vals=[]; t=now_ms();ver=int(row['version'])+1
  for api,col in MANUAL.items():
   if api in p:sets.append(col+'=?');vals.append(dumps(p[api] or {}) if col=='business_json' else str(p[api] or ''))
  custom=p.get('customFields') if isinstance(p.get('customFields'),dict) else {}
  for key,value in custom.items():
   key=str(key);fd=c.execute("SELECT field_type,enabled FROM custom_field_definitions WHERE workspace_id=? AND field_key=?",(wid,key)).fetchone()
   if not fd or not fd['enabled']:return err('FIELD_NOT_DEFINED','自定义字段未定义或已停用',400,fieldKey=key)
   typ=fd['field_type']; mismatch=(typ=='number' and (isinstance(value,bool) or not isinstance(value,(int,float)))) or (typ=='boolean' and not isinstance(value,bool)) or (typ in ('text','date') and not isinstance(value,str))
   if mismatch:return err('FIELD_TYPE_MISMATCH','自定义字段类型不匹配',400,fieldKey=key,expectedType=typ)
   c.execute("INSERT INTO contact_custom_values VALUES(?,?,?,?,?) ON CONFLICT(contact_id,field_key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at,updated_by=excluded.updated_by",(cid,key,dumps(value),t,actor))
  if not sets and not custom:return err('EMPTY_PATCH','没有可修改的字段')
  sets.extend(['version=?','updated_at=?']);vals.extend([ver,t,cid]);c.execute("UPDATE contacts SET "+','.join(sets)+" WHERE contact_id=?",vals)
  after=public_contact(c,c.execute("SELECT * FROM contacts WHERE contact_id=?",(cid,)).fetchone());event='admin_'+uuid.uuid4().hex
  add_change(c,wid,'contact',cid,'admin-patch',ver,row['source_id'],None,after,event)
  c.execute("INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(wid,actor,None,'admin-patch','contact',cid,dumps(before),dumps(after),str(p.get('reason') or '管理后台修改'),t))
  return ok(contact=after,version=ver)
def admin_set_contact_tags(db,wid,cid,p):
 actor=str(p.get('actor_id') or 'admin')[:120];ids=p.get('tag_ids')
 if not isinstance(ids,list):return err('INVALID_TAGS','tag_ids 必须是数组')
 with db.tx() as c:
  row=c.execute("SELECT * FROM contacts WHERE workspace_id=? AND contact_id=?",(wid,cid)).fetchone()
  if not row:return err('CONTACT_NOT_FOUND','联系人不存在',404)
  try:base=int(p.get('base_version'))
  except (TypeError,ValueError):return err('BASE_VERSION_REQUIRED','base_version 必须是整数')
  if base!=int(row['version']):return err('VERSION_CONFLICT','联系人版本冲突，请刷新后重试',409,currentVersion=row['version'])
  clean=[]
  for x in ids:
   tid=str(x)
   if tid not in clean:
    if not c.execute("SELECT 1 FROM tags WHERE workspace_id=? AND tag_id=? AND enabled=1",(wid,tid)).fetchone():return err('TAG_NOT_FOUND','标签不存在或已停用',404,tagId=tid)
    clean.append(tid)
  before=public_contact(c,row);t=now_ms();ver=int(row['version'])+1;c.execute("DELETE FROM contact_tags WHERE contact_id=?",(cid,))
  for tid in clean:c.execute("INSERT INTO contact_tags VALUES(?,?,?)",(cid,tid,t))
  c.execute("UPDATE contacts SET version=?,updated_at=? WHERE contact_id=?",(ver,t,cid));after=public_contact(c,c.execute("SELECT * FROM contacts WHERE contact_id=?",(cid,)).fetchone());event='admin_tags_'+uuid.uuid4().hex
  add_change(c,wid,'contact',cid,'admin-tags',ver,row['source_id'],None,after,event);c.execute("INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(wid,actor,None,'admin-tags','contact',cid,dumps(before),dumps(after),'管理后台调整标签',t));return ok(contact=after,version=ver)
def admin_contact_lifecycle(db,wid,cid,action,p):
 actor=str(p.get('actor_id') or 'admin')[:120]
 with db.tx() as c:
  row=c.execute("SELECT * FROM contacts WHERE workspace_id=? AND contact_id=?",(wid,cid)).fetchone()
  if not row:return err('CONTACT_NOT_FOUND','联系人不存在',404)
  try:base=int(p.get('base_version'))
  except (TypeError,ValueError):return err('BASE_VERSION_REQUIRED','base_version 必须是整数')
  if base!=int(row['version']):return err('VERSION_CONFLICT','联系人版本冲突，请刷新后重试',409,currentVersion=row['version'])
  if action=='delete' and row['deleted_at'] is not None:return err('ALREADY_DELETED','联系人已在回收站',409)
  if action=='restore' and row['deleted_at'] is None:return err('NOT_DELETED','联系人不在回收站',409)
  before=public_contact(c,row);t=now_ms();ver=int(row['version'])+1
  if action=='delete':c.execute("UPDATE contacts SET deleted_at=?,deleted_by=?,delete_reason=?,version=?,updated_at=? WHERE contact_id=?",(t,actor,str(p.get('reason') or '管理后台删除'),ver,t,cid))
  else:c.execute("UPDATE contacts SET deleted_at=NULL,deleted_by=NULL,delete_reason=NULL,version=?,updated_at=? WHERE contact_id=?",(ver,t,cid))
  after=public_contact(c,c.execute("SELECT * FROM contacts WHERE contact_id=?",(cid,)).fetchone());event='admin_'+action+'_'+uuid.uuid4().hex
  add_change(c,wid,'contact',cid,'admin-'+action,ver,row['source_id'],None,after,event);c.execute("INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(wid,actor,None,'admin-'+action,'contact',cid,dumps(before),dumps(after),str(p.get('reason') or ''),t));return ok(contact=after,version=ver)
def admin_overview(db,wid='default'):
 with db.tx(False) as c:
  tables=['devices','sources','source_devices','contacts','tags','custom_field_definitions','events','changes','audit_logs']
  counts={x:int(c.execute('SELECT COUNT(*) FROM '+x+(" WHERE workspace_id=?" if x!='custom_field_definitions' else " WHERE workspace_id=?"),(wid,)).fetchone()[0]) for x in tables}
  counts['active_contacts']=int(c.execute("SELECT COUNT(*) FROM contacts WHERE workspace_id=? AND deleted_at IS NULL",(wid,)).fetchone()[0]);counts['deleted_contacts']=int(c.execute("SELECT COUNT(*) FROM contacts WHERE workspace_id=? AND deleted_at IS NOT NULL",(wid,)).fetchone()[0]);counts['rejected_events']=int(c.execute("SELECT COUNT(*) FROM events WHERE workspace_id=? AND status='rejected'",(wid,)).fetchone()[0])
  channels=[dict(x) for x in c.execute("SELECT channel,COUNT(*) count FROM contacts WHERE workspace_id=? AND deleted_at IS NULL GROUP BY channel ORDER BY count DESC",(wid,))]
  return ok(counts=counts,channels=channels,database=db.quick_check(),foreignKeyViolations=db.foreign_key_check(),version=VERSION,schemaVersion=SCHEMA_VERSION)
def admin_logs(db,wid,kind,limit=200):
 limit=min(max(int(limit),1),1000)
 with db.tx(False) as c:
  if kind=='audit':rows=c.execute("SELECT audit_id,actor_id,device_id,operation,entity_type,entity_id,reason,created_at,before_json,after_json FROM audit_logs WHERE workspace_id=? ORDER BY audit_id DESC LIMIT ?",(wid,limit)).fetchall()
  elif kind=='events':rows=c.execute("SELECT event_id,device_id,source_id,entity_type,entity_id,operation,base_version,status,result_version,error_code,created_at,applied_at FROM events WHERE workspace_id=? ORDER BY created_at DESC LIMIT ?",(wid,limit)).fetchall()
  elif kind=='changes':rows=c.execute("SELECT change_id,entity_type,entity_id,operation,version,source_id,device_id,changed_at,event_id FROM changes WHERE workspace_id=? ORDER BY change_id DESC LIMIT ?",(wid,limit)).fetchall()
  else:return err('INVALID_LOG_KIND','日志类型无效')
  return ok(items=[dict(x) for x in rows])
def admin_schema(db):
 with db.tx(False) as c:
  out=[]
  for r in c.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
   cols=[dict(x) for x in c.execute('PRAGMA table_info('+r['name']+')')];fks=[dict(x) for x in c.execute('PRAGMA foreign_key_list('+r['name']+')')];out.append({'name':r['name'],'sql':r['sql'],'columns':cols,'foreignKeys':fks})
  return ok(items=out)

# V206.0.7 更新说明（2026-09-17）：保持 Schema 205；配合客户端事件确认隔离、精准 dirty 上传与死信策略。
