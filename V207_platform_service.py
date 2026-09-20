# -*- coding: utf-8 -*-
"""V207 全局平台领域服务。平台写权限仅属于内置平台管理员。"""
import json, re, sqlite3
from V207_shared_db import now_ms, dumps
from V207_security import can, is_platform_admin

PLATFORM_KINDS = {'messaging','social','owned','offline','advertising','import','marketplace','crm','other'}
PLATFORM_STATUSES = {'active','disabled'}
SYSTEM_CODES = {'whatsapp','instagram','facebook','messenger','telegram','line','tiktok','website','offline','google_ads','meta_ads','import'}
CODE_RE = re.compile(r'^[a-z][a-z0-9_]{0,63}$')


def _row(c, sql, args=()):
    r=c.execute(sql,args).fetchone()
    return dict(r) if r else None


def _rows(c, sql, args=()): return [dict(x) for x in c.execute(sql,args)]
def _err(code,message,status=400,**extra): return ({'ok':False,'code':code,'message':message,**extra},status)

def _audit_scope(c,actor,body):
    wid=str((body or {}).get('workspaceId') or actor.get('workspace_id') or '').strip()
    if not wid: raise RuntimeError('AUDIT_SCOPE_REQUIRED')
    row=c.execute('SELECT organization_id FROM workspaces WHERE workspace_id=?',(wid,)).fetchone()
    if not row or row[0]!=actor.get('organization_id'): raise RuntimeError('AUDIT_SCOPE_INVALID')
    return wid

def _audit(c,actor,operation,entity_id,before,after,reason=None,workspace_id=None):
    if not workspace_id: raise RuntimeError('AUDIT_SCOPE_REQUIRED')
    c.execute('INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
              (workspace_id,actor['user_id'],None,operation,'platform',entity_id,dumps(before or {}),dumps(after or {}),reason,now_ms()))

def _json_object(body,key,old=None):
    if key not in body: return old if old is not None else {}
    value=body[key]
    if not isinstance(value,dict): raise ValueError(key)
    return value

def _validate(body, creating=False, old=None):
    old=old or {}
    if creating or 'code' in body:
        code=str(body.get('code') or '').strip().lower()
        if not CODE_RE.fullmatch(code): return None,_err('INVALID_PLATFORM_CODE','平台代码格式无效')
    else: code=old['platform_code']
    if not creating and 'code' in body and code!=old['platform_code']:
        return None,_err('PLATFORM_CODE_IMMUTABLE','平台代码创建后不可修改',409)
    name=str(body.get('name',old.get('platform_name',''))).strip()
    if not name or len(name)>128:return None,_err('INVALID_PLATFORM_NAME','平台名称必填且长度不能超过 128')
    kind=str(body.get('kind',old.get('platform_kind','other'))).strip().lower()
    if kind not in PLATFORM_KINDS:return None,_err('INVALID_PLATFORM_KIND','平台类型无效')
    status=str(body.get('status',old.get('status','active'))).strip().lower()
    if status not in PLATFORM_STATUSES:return None,_err('INVALID_PLATFORM_STATUS','平台状态无效')
    try:
        capabilities=_json_object(body,'capabilities',json.loads(old.get('capabilities_json') or '{}') if old else {})
        metadata=_json_object(body,'metadata',json.loads(old.get('metadata_json') or '{}') if old else {})
    except (ValueError,TypeError,json.JSONDecodeError):return None,_err('INVALID_PLATFORM_JSON','capabilities 和 metadata 必须是对象')
    return {'code':code,'name':name,'kind':kind,'status':status,'capabilities':capabilities,'metadata':metadata},None

def _references(c,pid):
    # 仅统计活跃/运行中的业务引用；字段均来自 V207.1 迁移。
    return {
      'channelAccounts':c.execute("SELECT count(*) FROM channel_accounts WHERE platform_id=? AND status='active'",(pid,)).fetchone()[0],
      'accountIdentities':c.execute("SELECT count(*) FROM channel_account_identities WHERE platform_id=? AND status='active'",(pid,)).fetchone()[0],
      'sources':c.execute("SELECT count(*) FROM sources WHERE platform_id=? AND status='active'",(pid,)).fetchone()[0],
      'campaigns':c.execute("SELECT count(*) FROM campaigns WHERE platform_id=? AND status IN ('draft','scheduled','active','running')",(pid,)).fetchone()[0],
    }

def handle(db,actor,method,platform_id=None,query=None,body=None):
    """返回 ``(响应对象, HTTP 状态)``。"""
    query=query or {};body=body or {}
    if method=='GET' and platform_id is None:
        if not (is_platform_admin(db,actor) or can(db,actor,'platform.read')):return _err('FORBIDDEN','无平台读取权限',403)
        status=str(query.get('status') or '').strip();kind=str(query.get('kind') or '').strip();code=str(query.get('code') or '').strip().lower()
        try: page=max(1,int(query.get('page',1)));size=min(200,max(1,int(query.get('pageSize',query.get('limit',50)))))
        except (TypeError,ValueError):page,size=1,50
        cond=[];args=[]
        if status: cond.append('status=?');args.append(status)
        if kind: cond.append('platform_kind=?');args.append(kind)
        if code: cond.append('platform_code=?');args.append(code)
        where=(' WHERE '+' AND '.join(cond)) if cond else ''
        with db.tx(False) as c:
            total=c.execute('SELECT count(*) FROM platforms'+where,tuple(args)).fetchone()[0]
            items=_rows(c,'SELECT * FROM platforms'+where+' ORDER BY platform_kind,platform_name LIMIT ? OFFSET ?',tuple(args)+(size,(page-1)*size))
        return {'ok':True,'items':items,'pagination':{'page':page,'pageSize':size,'total':total,'pages':(total+size-1)//size}},200
    if method=='GET' and platform_id:
        if not (is_platform_admin(db,actor) or can(db,actor,'platform.read')):return _err('FORBIDDEN','无平台读取权限',403)
        with db.tx(False) as c:item=_row(c,'SELECT * FROM platforms WHERE platform_id=?',(platform_id,))
        return ({'ok':True,'item':item},200) if item else _err('PLATFORM_NOT_FOUND','平台不存在',404)
    if not is_platform_admin(db,actor):return _err('FORBIDDEN','仅平台超级管理员可修改全局平台',403)
    try:
        with db.tx(False) as c: audit_workspace_id=_audit_scope(c,actor,body)
    except RuntimeError as e:
        return _err(str(e),'平台写操作必须提供属于当前企业的有效 workspaceId',400)
    if method=='POST' and platform_id is None:
        data,error=_validate(body,True)
        if error:return error
        pid='plt_'+data['code'];t=now_ms()
        try:
            with db.tx() as c:
                c.execute('INSERT INTO platforms(platform_id,platform_code,platform_name,platform_kind,status,capabilities_json,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                          (pid,data['code'],data['name'],data['kind'],data['status'],dumps(data['capabilities']),dumps(data['metadata']),t,t))
                item=_row(c,'SELECT * FROM platforms WHERE platform_id=?',(pid,));_audit(c,actor,'create',pid,{},item,body.get('reason'),audit_workspace_id)
        except sqlite3.IntegrityError:return _err('PLATFORM_CONFLICT','平台代码已存在',409)
        return {'ok':True,'platformId':pid,'item':item},201
    if method=='PATCH' and platform_id:
        with db.tx() as c:
            old=_row(c,'SELECT * FROM platforms WHERE platform_id=?',(platform_id,))
            if not old:return _err('PLATFORM_NOT_FOUND','平台不存在',404)
            data,error=_validate(body,False,old)
            if error:return error
            if old['status']=='active' and data['status']=='disabled':
                refs=_references(c,platform_id)
                if any(refs.values()):return _err('PLATFORM_IN_USE','平台仍被活跃业务对象引用',409,references=refs)
            c.execute('UPDATE platforms SET platform_name=?,platform_kind=?,status=?,capabilities_json=?,metadata_json=?,updated_at=? WHERE platform_id=?',
                      (data['name'],data['kind'],data['status'],dumps(data['capabilities']),dumps(data['metadata']),now_ms(),platform_id))
            item=_row(c,'SELECT * FROM platforms WHERE platform_id=?',(platform_id,));_audit(c,actor,'update',platform_id,old,item,body.get('reason'),audit_workspace_id)
        return {'ok':True,'item':item},200
    if method=='DELETE' and platform_id:
        with db.tx() as c:
            old=_row(c,'SELECT * FROM platforms WHERE platform_id=?',(platform_id,))
            if not old:return _err('PLATFORM_NOT_FOUND','平台不存在',404)
            if old['platform_code'] in SYSTEM_CODES:return _err('SYSTEM_PLATFORM_PROTECTED','系统预置平台不能删除',409)
            refs=_references(c,platform_id)
            if any(refs.values()):return _err('PLATFORM_IN_USE','平台仍被业务对象引用',409,references=refs)
            c.execute('DELETE FROM platforms WHERE platform_id=?',(platform_id,));_audit(c,actor,'delete',platform_id,old,{},body.get('reason'),audit_workspace_id)
        return {'ok':True},200
    return _err('METHOD_NOT_ALLOWED','不支持的平台操作',405)
