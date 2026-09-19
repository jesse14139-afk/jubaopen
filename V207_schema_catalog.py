# -*- coding: utf-8 -*-
"""Schema 207 只读数据字典：合并运行时 SQLite 元数据与中文业务释义。"""
from V207_version import SCHEMA_VERSION, PRODUCT_VERSION, CATALOG_VERSION

CATEGORIES={
 'system':('系统与元数据','Schema、迁移、配置及工作区基础边界'),
 'organization':('企业组织结构','企业、部门、团队、业务线、市场及业务空间关系'),
 'identity':('用户与身份','用户、凭证、登录会话及成员关系'),
 'rbac':('角色与权限','角色、原子权限及授权关系'),
 'platform':('全局平台','全局渠道平台及平台能力'),
 'channel':('企业渠道账号','企业账号、账号身份及授权'),
 'device':('设备与分配','设备注册、双命名、来源设备及人员分配'),
 'contact':('联系人与外部身份','联系人、外部身份、标签和自定义字段'),
 'source':('来源管理','来源节点、来源关系、来源分类及追踪信息'),
 'campaign':('活动管理','营销活动及其承接资源'),
 'touchpoint':('业务触点','客户与来源、活动发生的互动记录'),
 'attribution':('归因分析','触点和来源对联系人转化的贡献结果'),
 'event':('事件与同步','客户端事件及数据变更流'),
 'audit':('安全与审计','操作审计、高风险确认及迁移记录'),
 'compatibility':('兼容支持','V205/V206 协议兼容对象'),
 'uncategorized':('未分类','运行数据库中存在但尚未补充正式业务释义的对象')}

TABLES={
 'meta':('system','系统元数据表','保存 Schema 版本、产品版本及系统级键值。'),
 'organizations':('system','企业表','多租户系统的顶层隔离单位，企业资源均应归属该实体。'),
 'workspaces':('system','工作区表','承载来源、设备、联系人和配置的业务数据空间。'),
 'workspace_configs':('system','工作区配置表','保存带修订号的工作区配置 JSON。'),
 'users':('identity','用户表','保存企业内用户的登录标识、显示名称和状态。'),
 'user_credentials':('identity','用户凭证表','保存密码派生结果和强制改密状态，不保存明文密码。'),
 'sessions':('identity','登录会话表','保存访问令牌摘要、有效期、来源环境和撤销状态。'),
 'organization_memberships':('identity','企业成员关系表','关联用户、企业和企业级角色。'),
 'team_memberships':('identity','团队成员关系表','关联用户、团队和团队级角色。'),
 'roles':('rbac','角色表','定义平台、企业或团队范围的角色。'),
 'permissions':('rbac','权限项表','定义系统可校验的原子权限编码。'),
 'role_permissions':('rbac','角色权限关系表','建立角色与权限项的多对多关系。'),
 'channel_accounts':('channel','渠道账号表','企业正式管理的外部渠道账号，是授权和来源归并主体。'),
 'channel_account_identities':('channel','渠道账号身份表','保存账号在外部平台上的登录名、号码或其他身份。'),
 'team_channel_accounts':('channel','团队渠道账号授权表','控制团队可使用的渠道账号。'),
 'user_channel_account_grants':('channel','用户渠道账号授权表','对单个用户授予渠道账号使用范围。'),
 'sources':('channel','渠道来源兼容表','旧版来源物理表，继续支持 V206/V207 兼容接口。'),
 'source_nodes':('channel','来源节点视图','V207.1 统一来源节点领域视图，映射兼容物理表 sources。'),
 'source_devices':('channel','来源设备关系表','记录来源出现在哪些设备及其活动统计。'),
 'devices':('device','设备表','保存安装实例、系统名称、用户别名、管理员名称及归属。'),
 'device_assignments':('device','设备分配记录表','记录设备分配给用户和团队的时间历史。'),
 'contacts':('contact','联系人表','保存联系人观测资料、人工资料、业务状态、来源和软删除信息。'),
 'tags':('contact','标签定义表','定义工作区可用于联系人分类的标签。'),
 'contact_tags':('contact','联系人标签关系表','建立联系人和标签的多对多关系。'),
 'custom_field_definitions':('contact','自定义字段定义表','定义工作区联系人可使用的扩展字段。'),
 'contact_custom_values':('contact','联系人自定义字段值表','保存联系人扩展字段的 JSON 值。'),
 'events':('event','客户端事件表','接收设备上传的业务事件，支持幂等处理和结果追踪。'),
 'changes':('event','数据变更流表','记录实体变更游标，用于客户端增量同步。'),
 'audit_logs':('event','安全审计日志表','记录管理操作对象、前后状态、原因和操作者。'),
 'delete_confirmations':('event','删除确认凭证表','为高风险删除提供短期二次确认和版本校验。')}

TABLES.update({
 'schema_migrations':('audit','数据库迁移记录表','保存迁移编号、校验和、执行结果和时间。'),
 'security_events':('audit','安全事件表','记录登录失败、账号锁定及其他认证安全事件，供只读审计与风险追踪。'),
 'teams':('organization','团队表','企业内用户、账号、设备与工作区协作的管理单元。'),
 'departments':('organization','部门表','维护企业部门层级及团队归属。'),
 'business_lines':('organization','业务线表','维护企业业务线层级和业务空间关系。'),
 'markets':('organization','市场表','维护区域、国家、城市或细分市场层级。'),
 'workspace_teams':('organization','工作区团队关系表','描述主责、协作、合规或支持团队及访问级别。'),
 'workspace_business_lines':('organization','工作区业务线关系表','描述工作区与业务线的多对多业务关系。'),
 'workspace_markets':('organization','工作区市场关系表','描述工作区覆盖或服务的市场范围。'),
 'platforms':('platform','全局平台表','定义消息、社交、广告、自有及线下等全局渠道平台。'),
 'campaigns':('campaign','营销活动表','记录营销活动、平台、承接账号和工作区。'),
 'contact_identities':('contact','联系人外部身份表','保存联系人跨平台的邮箱、电话、用户名或社交身份。'),
 'source_links':('source','来源关系表','描述来源之间的父子、跳转、合并或业务链路。'),
 'source_touchpoints':('touchpoint','来源触点表','记录联系人、来源和活动在特定时间发生的互动。'),
 'contact_attributions':('attribution','联系人归因表','保存归因模型计算出的主要来源及贡献结果。')})

LABELS={
 'key':'键','value':'值','name':'名称','status':'状态','created_at':'创建时间','updated_at':'更新时间',
 'organization_id':'企业 ID','workspace_id':'工作区 ID','team_id':'团队 ID','user_id':'用户 ID','role_id':'角色 ID',
 'permission_key':'权限编码','description':'说明','scope_level':'作用范围','login_name':'登录名','display_name':'显示名称',
 'password_hash':'密码摘要','salt':'密码盐值','iterations':'派生迭代次数','must_change':'是否强制改密',
 'session_id':'会话 ID','access_token_hash':'访问令牌摘要','expires_at':'过期时间','ip':'IP 地址','user_agent':'客户端标识','last_seen_at':'最后活动时间','revoked_at':'撤销时间',
 'channel_account_id':'渠道账号 ID','channel':'渠道类型','identity_id':'身份 ID','identity_type':'身份类型','identity_value':'身份原值','canonical_value':'规范化身份值','permission_scope':'授权范围','granted_by':'授权人','granted_at':'授权时间',
 'source_id':'来源 ID','source_name':'来源名称','account_identity':'来源账号身份','last_device_id':'最后设备 ID','metadata_json':'扩展元数据','first_seen_at':'首次发现时间','device_id':'设备 ID','event_count':'事件次数','contact_observe_count':'联系人观测次数','last_operation':'最后操作',
 'installation_id':'安装实例 ID','device_name':'设备名称','computer_name':'计算机名称','assigned_user_id':'分配用户 ID','system_device_name':'系统设备名称','system_computer_name':'系统计算机名称','user_device_alias':'用户设备别名','user_computer_alias':'用户计算机别名','admin_device_name':'管理员设备名称','admin_computer_name':'管理员计算机名称','assignment_id':'分配记录 ID','assigned_at':'分配时间','released_at':'解除时间',
 'contact_id':'联系人 ID','external_contact_id':'外部联系人 ID','observed_phone':'观测电话','avatar_url':'头像地址','observed_json':'观测资料','observation_hash':'观测摘要','manual_name':'人工姓名','manual_phone':'人工电话','remark':'备注','business_json':'业务扩展资料','last_observed_device_id':'最后观测设备 ID','last_observed_at':'最后观测时间','version':'数据版本','deleted_at':'删除时间','deleted_by':'删除人','delete_reason':'删除原因',
 'tag_id':'标签 ID','color':'颜色','category':'分类','sort_order':'排序值','enabled':'是否启用','field_key':'字段键','label':'字段名称','field_type':'字段类型','options':'候选选项','value_json':'字段值','updated_by':'更新人',
 'event_id':'事件 ID','request_id':'请求 ID','entity_type':'实体类型','entity_id':'实体 ID','operation':'操作类型','base_version':'基础版本','payload_json':'事件载荷','payload_hash':'载荷摘要','result_version':'结果版本','error_code':'错误编码','applied_at':'应用时间','result_json':'处理结果','change_id':'变更游标','changed_at':'变更时间',
 'audit_id':'审计 ID','actor_id':'操作者 ID','before_json':'变更前内容','after_json':'变更后内容','reason':'操作原因','confirmation_id':'确认凭证 ID','expected_version':'预期版本','impact_hash':'影响范围摘要','used_at':'使用时间','created_by':'创建人','revision':'配置修订号','items_json':'配置内容'}

SPECIAL={
 'meta.key':'系统元数据项的唯一名称。','meta.value':'对应元数据项的文本值。',
 'sources.channel_account_id':'可选逻辑关联；将运行时来源归并到企业正式渠道账号。',
 'sources.account_identity':'外部渠道中识别到的账号身份，与渠道共同用于来源去重。',
 'channel_account_identities.identity_value':'外部身份原始值，仅授权管理页面可见，不能作为密码保存。',
 'channel_account_identities.canonical_value':'去空格并转小写后的匹配值，用于稳定识别账号。',
 'user_credentials.password_hash':'PBKDF2 派生后的密码摘要，属于高敏感字段，页面仅展示结构。',
 'user_credentials.salt':'密码派生盐值，属于认证敏感字段，页面不展示实际值。',
 'sessions.access_token_hash':'访问令牌的不可逆摘要，不保存令牌明文。',
 'contacts.observed_json':'设备自动观测到的资料 JSON；与人工维护资料分离。',
 'contacts.business_json':'联系人业务扩展 JSON，用于兼容动态业务信息。',
 'contacts.deleted_at':'非空表示联系人已软删除，历史数据仍保留。',
 'events.event_id':'客户端生成的幂等键，防止同一事件重复应用。',
 'changes.change_id':'SQLite 自增游标，客户端按该值获取增量变更。',
 'audit_logs.before_json':'写操作发生前的快照 JSON，仅结构页面不读取实际内容。',
 'audit_logs.after_json':'写操作发生后的快照 JSON，仅结构页面不读取实际内容。',
 'delete_confirmations.impact_hash':'删除预览影响范围的摘要，确认时用于防止范围变化。'}

SENSITIVE={'password_hash','salt','access_token_hash','identity_value','observed_phone','manual_phone','payload_json','before_json','after_json','result_json','ip','user_agent'}
JSON_FIELDS={x for x in LABELS if x.endswith('_json')}|{'items_json'}
TIME_FIELDS={x for x in LABELS if x.endswith('_at')}

LOGICAL_RELATIONS=[
 ('organizations','organization_id','teams','organization_id','企业拥有团队'),('organizations','organization_id','users','organization_id','企业拥有用户'),('organizations','organization_id','workspaces','organization_id','企业拥有工作区'),('users','user_id','user_credentials','user_id','用户拥有认证凭证'),('users','user_id','sessions','user_id','用户产生登录会话'),('users','user_id','organization_memberships','user_id','用户加入企业'),('roles','role_id','organization_memberships','role_id','企业成员使用角色'),('users','user_id','team_memberships','user_id','用户加入团队'),('teams','team_id','team_memberships','team_id','团队包含成员'),('roles','role_id','team_memberships','role_id','团队成员使用角色'),('roles','role_id','role_permissions','role_id','角色包含权限'),('permissions','permission_key','role_permissions','permission_key','权限授予角色'),('organizations','organization_id','channel_accounts','organization_id','企业管理渠道账号'),('channel_accounts','channel_account_id','channel_account_identities','channel_account_id','账号包含外部身份'),('teams','team_id','team_channel_accounts','team_id','团队获得账号授权'),('channel_accounts','channel_account_id','team_channel_accounts','channel_account_id','账号授权给团队'),('channel_accounts','channel_account_id','sources','channel_account_id','来源归并到账号'),('sources','source_id','source_devices','source_id','来源出现于设备'),('devices','device_id','source_devices','device_id','设备观测来源'),('sources','source_id','contacts','source_id','来源产生联系人'),('devices','device_id','contacts','last_observed_device_id','设备最后观测联系人'),('contacts','contact_id','contact_tags','contact_id','联系人拥有标签'),('tags','tag_id','contact_tags','tag_id','标签关联联系人'),('contacts','contact_id','contact_custom_values','contact_id','联系人拥有扩展值'),('devices','device_id','device_assignments','device_id','设备具有分配历史')]

def _field_description(table,name):
 key=table+'.'+name
 if key in SPECIAL:return SPECIAL[key]
 label=LABELS.get(name,name)
 if name in TIME_FIELDS:return label+'，以毫秒级 Unix 时间戳保存；为空表示尚未发生。'
 if name in JSON_FIELDS:return label+'，以 JSON 文本保存动态结构。'
 if name.endswith('_id'):return label+'，用于唯一标识实体或关联相关实体。'
 if name=='status':return '控制记录当前是否有效，常见值为 active（正常）或 disabled（停用）。'
 if name=='created_at':return '记录创建时的毫秒级 Unix 时间戳。'
 if name=='updated_at':return '记录最后更新时的毫秒级 Unix 时间戳。'
 return label+'的持久化字段。'

def _quote_identifier(name):
 """仅为已从 sqlite_schema 读取的对象名生成 PRAGMA 安全标识符。"""
 return '"'+str(name).replace('"','""')+'"'

def _infer_category(name,object_type='table'):
 rules=(
  (('schema_','meta','workspace_configs'),'system'),
  (('organizations','departments','teams','business_lines','markets','workspace_teams','workspace_business_lines','workspace_markets'),'organization'),
  (('users','user_credentials','sessions','organization_memberships','team_memberships'),'identity'),
  (('roles','permissions','role_permissions'),'rbac'),(('platforms',),'platform'),
  (('channel_','team_channel','user_channel'),'channel'),(('devices','device_','source_devices'),'device'),
  (('contacts','contact_identities','tags','contact_tags','custom_field','contact_custom'),'contact'),
  (('sources','source_nodes','source_links'),'source'),(('campaigns',),'campaign'),
  (('source_touchpoints',),'touchpoint'),(('contact_attributions',),'attribution'),
  (('events','changes'),'event'),(('audit_logs','delete_confirmations'),'audit'))
 for prefixes,category in rules:
  if any(name==x or name.startswith(x) for x in prefixes):return category
 return 'uncategorized'

def _scope_type(fields):
 names={x['name'] for x in fields}
 if 'organization_id' in names and 'workspace_id' in names:return 'organization+workspace'
 if 'organization_id' in names:return 'organization'
 if 'workspace_id' in names:return 'workspace'
 return 'global/system'

def build_schema_catalog(db):
 """只读取 sqlite_schema 与 PRAGMA 结构元数据；不读取任何业务表记录。"""
 with db.tx(False) as c:
  objects=[dict(x) for x in c.execute("SELECT name,type,sql FROM sqlite_schema WHERE type IN ('table','view','trigger') AND name NOT LIKE 'sqlite_%' ORDER BY type,name")]
  data_objects=[x for x in objects if x['type'] in ('table','view')]
  triggers=[{'name':x['name'],'sql':x['sql'] or ''} for x in objects if x['type']=='trigger']
  tables=[]; index_total=fk_total=field_total=undocumented=0; physical_relations=[]
  known_names={x['name'] for x in data_objects}
  for obj in data_objects:
   name=obj['name']; quoted=_quote_identifier(name)
   documented=name in TABLES
   cat,cn,purpose=TABLES.get(name,(_infer_category(name,obj['type']),name,'暂无正式业务释义；该对象由运行时 SQLite 元数据自动发现。'))
   raw_cols=[dict(x) for x in c.execute('PRAGMA table_xinfo('+quoted+')')]
   raw_idx=[dict(x) for x in c.execute('PRAGMA index_list('+quoted+')')] if obj['type']=='table' else []
   indexes=[]
   for ix in raw_idx:
    iq=_quote_identifier(ix['name'])
    cols=[dict(z) for z in c.execute('PRAGMA index_xinfo('+iq+')')]
    indexes.append({'name':ix['name'],'unique':bool(ix['unique']),'origin':ix['origin'],'partial':bool(ix.get('partial',0)),'columns':[z['name'] for z in cols if z.get('key') and z.get('name') is not None]})
   fks=[dict(x) for x in c.execute('PRAGMA foreign_key_list('+quoted+')')] if obj['type']=='table' else []
   fields=[]
   for x in raw_cols:
    fname=x['name'];tags=[]
    if x['pk']:tags.append('PK')
    if x['notnull']:tags.append('NOT NULL')
    if x.get('hidden'):tags.append('生成/隐藏列')
    if fname in JSON_FIELDS or fname.endswith('_json'):tags.append('JSON')
    if fname in TIME_FIELDS or fname.endswith('_at'):tags.append('时间戳')
    if fname in SENSITIVE:tags.append('敏感')
    physical=[f for f in fks if f['from']==fname]
    logical=[{'table':rel[2],'field':rel[3],'description':rel[4],'kind':'logical','evidence':'V207_schema_catalog.LOGICAL_RELATIONS'} for rel in LOGICAL_RELATIONS if rel[0]==name and rel[1]==fname]
    if physical:tags.append('FK')
    elif logical:tags.append('逻辑关联')
    for f in physical:
     physical_relations.append({'fromTable':name,'fromField':fname,'toTable':f['table'],'toField':f['to'],'description':'SQLite 物理外键','kind':'physical','cardinality':'N:1','onDelete':f['on_delete'],'onUpdate':f['on_update'],'evidence':'PRAGMA foreign_key_list'})
    fields.append({'position':x['cid']+1,'name':fname,'label':LABELS.get(fname,fname),'type':x['type'] or 'ANY','notNull':bool(x['notnull']),'primaryKeyOrder':x['pk'],'default':x['dflt_value'],'hidden':x.get('hidden',0),'tags':tags,'sensitive':fname in SENSITIVE,'description':_field_description(name,fname) if documented or fname in LABELS else '暂无业务释义。','physicalRelations':physical,'logicalRelations':logical})
   inbound=[]
   tables.append({'name':name,'label':cn,'category':cat,'purpose':purpose,'objectType':obj['type'],'documented':documented,'documentationStatus':'complete' if documented else 'missing','scopeType':_scope_type(fields),'fieldCount':len(fields),'fields':fields,'indexes':indexes,'physicalForeignKeys':fks,'createSql':obj['sql'] or '','inboundRelations':inbound})
   if not documented:undocumented+=1
   field_total+=len(fields);index_total+=len(indexes);fk_total+=len(fks)
  logical=[{'fromTable':a,'fromField':b,'toTable':ct,'toField':d,'description':e,'kind':'logical','cardinality':'business-defined','evidence':'V207_schema_catalog.LOGICAL_RELATIONS'} for a,b,ct,d,e in LOGICAL_RELATIONS if a in known_names and ct in known_names]
  all_rel=physical_relations+logical
  for t in tables:t['inboundRelations']=[x for x in all_rel if x['toTable']==t['name']]
  quick=c.execute('PRAGMA quick_check').fetchone()[0]
  issues=[list(x) for x in c.execute('PRAGMA foreign_key_check')]
 categories=[]
 for key,(label,desc) in CATEGORIES.items():
  subset=[t for t in tables if t['category']==key]
  categories.append({'key':key,'label':label,'description':desc,'tableCount':len(subset),'fieldCount':sum(t['fieldCount'] for t in subset)})
 coverage=round((len(tables)-undocumented)*100/len(tables),2) if tables else 100
 diagnostics=[]
 if undocumented:diagnostics.append({'severity':'warning','code':'UNDOCUMENTED_OBJECTS','count':undocumented,'message':'存在尚未补充正式中文业务释义的数据库对象。'})
 if issues:diagnostics.append({'severity':'error','code':'FOREIGN_KEY_ISSUES','count':len(issues),'message':'检测到物理外键完整性问题。'})
 return {'ok':True,'readOnly':True,'productVersion':PRODUCT_VERSION,'schemaVersion':SCHEMA_VERSION,'catalogVersion':CATALOG_VERSION,'summary':{'tableCount':sum(1 for x in tables if x['objectType']=='table'),'viewCount':sum(1 for x in tables if x['objectType']=='view'),'triggerCount':len(triggers),'fieldCount':field_total,'indexCount':index_total,'physicalForeignKeyCount':fk_total,'logicalRelationCount':len(logical),'undocumentedObjectCount':undocumented,'documentationCoverage':coverage},'categories':categories,'tables':tables,'relations':all_rel,'triggers':triggers,'diagnostics':diagnostics,'integrity':{'quickCheck':quick,'foreignKeyIssues':issues},'notes':['仅读取 sqlite_schema 与 PRAGMA 结构元数据，不查询业务表记录。','未登记对象不会隐藏，将归入自动推断分类或“未分类”。','FK 表示 SQLite 物理外键；逻辑关联由领域服务和作用域校验维护。']}

# V207.4.0-dev 更新说明（2026-09-20）：改用 table_xinfo/index_xinfo，覆盖全部表、视图、触发器；取消业务记录计数，补充分类、覆盖率、物理及逻辑关系诊断。

# V207.4.0-dev 更新说明（2026-09-20）：运行时提取表、视图、字段、索引和物理外键，并合并中文释义、逻辑关联与文档覆盖率；全程不读取业务记录。
