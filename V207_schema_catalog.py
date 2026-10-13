# -*- coding: utf-8 -*-
"""Schema 222 只读数据字典：合并运行时 SQLite 元数据与中文业务释义。"""
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
 'device_enrollments':('device','设备接入邀请表','保存管理员创建的设备接入邀请、预分配归属、绑定码摘要、有效期、核销设备及撤销状态。'),
 'device_rebind_requests':('device','设备换绑请求表','保存设备一次性换绑码摘要、目标归属、有效期、核销与撤销状态。'),
 'user_dashboard_pins':('identity','用户工作台置顶表','保存用户在管理工作台中置顶的功能入口及置顶时间。'),
 'channel_types':('channel','渠道类型定义表','定义不同平台支持的渠道形态、收发方向、启用状态和排序规则，供渠道账号与来源统一引用。'),
 'source_type_definitions':('source','来源类型定义表','维护直接访问、广告、推荐、导入等来源类型标准字典，统一来源识别、筛选和归因口径。'),
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
  'team_markets':('organization','团队市场关系表','描述团队负责或服务的市场，可标记唯一主市场。'),
  'team_business_lines':('organization','团队业务线关系表','描述团队参与的业务线，可标记唯一主业务线。'),
 'platforms':('platform','全局平台表','定义消息、社交、广告、自有及线下等全局渠道平台。'),
 'campaigns':('campaign','营销活动表','记录营销活动、平台、承接账号和工作区。'),
 'contact_identities':('contact','联系人外部身份表','保存联系人跨平台的邮箱、电话、用户名或社交身份。'),
 'source_links':('source','来源关系表','描述来源之间的父子、跳转、合并或业务链路。'),
 'source_touchpoints':('touchpoint','来源触点表','记录联系人、来源和活动在特定时间发生的互动。'),
 'contact_attributions':('attribution','联系人归因表','保存归因模型计算出的主要来源及贡献结果。')})

LABELS={
 'key':'键','value':'值','name':'名称','status':'状态','created_at':'创建时间','updated_at':'更新时间',
 'organization_id':'企业 ID','market_id':'市场 ID','business_line_id':'业务线 ID','department_id':'部门 ID','parent_market_id':'上级市场 ID','parent_business_line_id':'上级业务线 ID','parent_department_id':'上级部门 ID','workspace_id':'工作区 ID','team_id':'团队 ID','user_id':'用户 ID','role_id':'角色 ID',
 'local_name':'本地名称','currency_code':'货币代码','is_primary':'是否主关系','scope_type':'作用域类型','scope_id':'作用域 ID','permission_key':'权限编码','description':'说明','scope_level':'作用范围','login_name':'登录名','display_name':'显示名称',
 'password_hash':'密码摘要','salt':'密码盐值','iterations':'派生迭代次数','must_change':'是否强制改密',
 'session_id':'会话 ID','access_token_hash':'访问令牌摘要','expires_at':'过期时间','ip':'IP 地址','user_agent':'客户端标识','last_seen_at':'最后活动时间','revoked_at':'撤销时间',
 'channel_account_id':'渠道账号 ID','channel':'渠道类型','identity_id':'身份 ID','identity_type':'身份类型','identity_value':'身份原值','canonical_value':'规范化身份值','permission_scope':'授权范围','granted_by':'授权人','granted_at':'授权时间',
 'source_id':'来源 ID','source_name':'来源名称','account_identity':'来源账号身份','last_device_id':'最后设备 ID','metadata_json':'扩展元数据','first_seen_at':'首次发现时间','device_id':'设备 ID','event_count':'事件次数','contact_observe_count':'联系人观测次数','last_operation':'最后操作',
 'installation_id':'安装实例 ID','device_name':'设备名称','computer_name':'计算机名称','assigned_user_id':'分配用户 ID','system_device_name':'系统设备名称','system_computer_name':'系统计算机名称','user_device_alias':'用户设备别名','user_computer_alias':'用户计算机别名','admin_device_name':'管理员设备名称','admin_computer_name':'管理员计算机名称','assignment_id':'分配记录 ID','assigned_at':'分配时间','released_at':'解除时间',
 'contact_id':'联系人 ID','external_contact_id':'外部联系人 ID','observed_phone':'观测电话','avatar_url':'头像地址','observed_json':'观测资料','observation_hash':'观测摘要','manual_name':'人工姓名','manual_phone':'人工电话','remark':'备注','business_json':'业务扩展资料','last_observed_device_id':'最后观测设备 ID','last_observed_at':'最后观测时间','version':'数据版本','deleted_at':'删除时间','deleted_by':'删除人','delete_reason':'删除原因',
 'campaign_id':'活动 ID','campaign_name':'活动名称','campaign_code':'活动代码','campaign_type':'活动类型','platform_name':'平台名称','platform_code':'平台代码','platform_kind':'平台类型','touchpoint_type':'触点类型','path_position':'路径位置','verification_status':'验证状态','team_name':'团队名称','workspace_name':'工作区名称','security_event_id':'安全事件 ID','event_type':'事件类型','migration_id':'迁移编号','migration_name':'迁移名称','checksum':'校验值','applied_by':'执行人', 'source_link_id':'来源关系 ID','from_source_id':'父来源 ID','to_source_id':'子来源 ID','link_type':'关系类型','tag_id':'标签 ID','color':'颜色','category':'分类','sort_order':'排序值','enabled':'是否启用','field_key':'字段键','label':'字段名称','field_type':'字段类型','options':'候选选项','value_json':'字段值','updated_by':'更新人',
 'event_id':'事件 ID','request_id':'请求 ID','entity_type':'实体类型','entity_id':'实体 ID','operation':'操作类型','base_version':'基础版本','payload_json':'事件载荷','payload_hash':'载荷摘要','result_version':'结果版本','error_code':'错误编码','applied_at':'应用时间','result_json':'处理结果','change_id':'变更游标','changed_at':'变更时间',
 'audit_id':'审计 ID','actor_id':'操作者 ID','before_json':'变更前内容','after_json':'变更后内容','reason':'操作原因','confirmation_id':'确认凭证 ID','expected_version':'预期版本','impact_hash':'影响范围摘要','used_at':'使用时间','created_by':'创建人','revision':'配置修订号','items_json':'配置内容','stage':'业务阶段','owner_user_id':'负责人用户 ID','next_follow_up_at':'下次跟进时间','last_touch_at':'最后触达时间','pin_key':'置顶入口编码','pinned_at':'置顶时间'}

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
 'delete_confirmations.impact_hash':'删除预览影响范围的摘要，确认时用于防止范围变化。',
 'source_links.source_link_id':'来源关系的唯一标识。',
 'source_links.from_source_id':'关系起点的来源节点，指向 sources.source_id。',
 'source_links.to_source_id':'关系终点的来源节点，指向 sources.source_id。',
 'source_links.link_type':'关系类型，如父子、跳转、合并或业务链路。'}

LABELS.update({
 'enrollment_id':'设备接入邀请 ID','binding_code_hash':'绑定码摘要','consumed_at':'核销时间','consumed_device_id':'核销设备 ID',
 'created_by':'创建人','revoked_by':'撤销人','rebind_id':'换绑请求 ID','from_user_id':'原用户 ID','to_user_id':'目标用户 ID','from_team_id':'原团队 ID','to_team_id':'目标团队 ID','to_workspace_id':'目标工作区 ID','code_hash':'换绑码摘要','revoked_at':'撤销时间','channel_type_id':'渠道类型 ID','channel_type_code':'渠道类型编码',
 'source_type_id':'来源类型 ID','source_type_code':'来源类型编码','direction':'收发方向','is_active':'是否启用','sort_order':'排序顺序'
})


# Schema 219：联系人中心用户偏好。
TABLES.update({
 'user_contact_center_preferences':('identity','联系人中心用户偏好表','保存企业用户在联系人中心的界面筛选、排序及展示偏好，并通过版本号支持并发更新。')
})
LABELS.update({'preferences_json':'联系人中心偏好配置'})
SPECIAL.update({'user_contact_center_preferences.preferences_json':'保存联系人中心筛选、排序和展示设置的 JSON 配置。'})

# Schema 218/219：业务场景、来源解析、交互幂等与转化领域数据字典。
TABLES.update({
 'interaction_idempotency':('event','交互幂等记录表','保存交互操作的请求摘要与响应结果，防止客户端重试造成重复建档或重复写入。'),
 'source_resolution_logs':('source','来源解析日志表','记录来源解析器的输入摘要、解析方法、置信度、结果及错误，支持来源识别审计与排障。'),
 'contact_conversions':('attribution','联系人转化记录表','记录联系人转化金额、币种、状态、来源与归因关联，并支持幂等创建和受控状态流转。')
})
LABELS.update({
 'business_scene':'业务场景','contact_entry_policy':'联系人建档策略','default_market_id':'默认市场 ID','suggested_source_type_id':'建议来源类型 ID',
 'conversion_id':'转化 ID','conversion_status':'转化状态','amount_minor':'最小货币单位金额','converted_at':'转化时间','external_conversion_key':'外部转化幂等键',
 'idempotency_id':'幂等记录 ID','idempotency_key':'幂等键','request_hash':'请求摘要','response_json':'响应 JSON',
 'resolution_log_id':'来源解析日志 ID','input_digest':'解析输入摘要','resolver_version':'解析器版本','resolution_method':'解析方法','input_summary_json':'输入摘要 JSON',
 'event_key':'事件幂等键','source_fingerprint':'来源指纹','entry_url':'入口 URL','referrer_url':'引荐 URL',
 'platform_object_type':'平台对象类型','platform_object_id':'平台对象 ID','platform_actor_id':'平台主体 ID','platform_actor_name':'平台主体名称',
 'ad_set_name':'广告组名称','ad_name':'广告名称','utm_source':'UTM 来源','utm_medium':'UTM 媒介','utm_campaign':'UTM 活动',
 'utm_content':'UTM 内容','utm_term':'UTM 关键词','resolution_confidence':'解析置信度'
})
SPECIAL.update({
 'channel_accounts.business_scene':'定义渠道账号承载的业务场景，用于约束业务用途、采集开关与建档策略的合法组合。',
 'channel_accounts.contact_entry_policy':'定义渠道账号何时创建联系人，包括人工建档、首次入站消息、仅已有联系人或禁用。',
 'contact_conversions.conversion_status':'转化生命周期状态；支持 pending、won、lost、cancelled 和 refunded，并按状态机受控流转。',
 'contact_conversions.amount_minor':'以币种最小单位保存的整数金额，例如人民币分或美元美分。',
 'contact_conversions.external_conversion_key':'企业范围内的外部幂等键，用于避免同一外部转化被重复创建。',
 'interaction_idempotency.request_hash':'对规范化请求内容计算的摘要，用于识别同一幂等键下的参数冲突。',
 'interaction_idempotency.response_json':'首次成功操作的响应快照，以 JSON 文本保存并供安全重放。',
 'source_resolution_logs.input_digest':'对来源解析原始输入计算的不可逆摘要，支持去重与审计且不暴露原文。',
 'source_resolution_logs.resolution_method':'记录解析来源所采用的方法，例如确定性规则、平台对象映射或降级策略。',
 'source_resolution_logs.input_summary_json':'来源解析输入的脱敏摘要，以 JSON 文本保存用于诊断。',
 'sources.source_fingerprint':'由稳定来源属性生成的指纹，用于企业工作区范围内的来源去重。',
 'source_nodes.source_fingerprint':'来源节点视图中的稳定来源指纹，用于统一来源识别与去重。',
 'sources.resolution_confidence':'来源解析结果的置信度，取值用于衡量自动识别结果的可靠程度。',
 'source_nodes.resolution_confidence':'来源节点视图中的解析置信度，反映自动识别结果可靠程度。'
})

# Schema 222：跨平台会话、稳定消息分页与客户转交状态机。
TABLES.update({
 'contact_transfer_events':('contact','客户转交事件表','按时间顺序保存客户转交的创建、匹配、确认、拒绝、取消、失败、过期及目标会话关联事件。')
})
LABELS.update({
 'closed_at':'关闭时间','closed_by':'关闭人','archived_at':'归档时间','archived_by':'归档人',
 'last_message_id':'最后消息 ID','last_message_direction':'最后消息方向','last_message_type':'最后消息类型','last_message_preview':'最后消息摘要',
 'message_count':'消息总数','inbound_count':'入站消息数','outbound_count':'出站消息数',
 'reply_to_message_id':'回复消息 ID','attachment_count':'附件数量','has_sensitive_content':'是否包含敏感内容','source_event_id':'来源事件 ID','ingestion_version':'采集版本',
 'transfer_type':'转交类型','from_platform_id':'来源平台 ID','to_platform_id':'目标平台 ID','requested_by':'发起人','requested_at':'发起时间',
 'accepted_by':'确认人','accepted_at':'确认时间','rejected_by':'拒绝人','rejected_at':'拒绝时间','cancelled_by':'取消人','cancelled_at':'取消时间',
 'failed_at':'失败时间','expired_at':'过期处理时间','rejection_reason':'拒绝原因','failure_code':'失败编码','failure_reason':'失败原因',
 'matched_identity_id':'匹配身份 ID','match_confidence':'匹配置信度','match_evidence_json':'匹配证据 JSON','from_status':'原状态','to_status':'目标状态','details_json':'事件详情 JSON'
})
SPECIAL.update({
 'conversations.closed_at':'会话被关闭的毫秒时间戳；重新打开后清空。','conversations.closed_by':'执行会话关闭操作的用户标识。',
 'conversations.archived_at':'会话被归档的毫秒时间戳；恢复后清空。','conversations.archived_by':'执行会话归档操作的用户标识。',
 'conversations.last_message_id':'列表摘要对应的最后一条消息标识，避免列表查询重复扫描消息表。',
 'conversations.last_message_direction':'最后消息的入站或出站方向，用于列表筛选和展示。','conversations.last_message_type':'最后消息的内容类型。',
 'conversations.last_message_preview':'已脱敏的最后消息摘要，可在不读取原文时安全展示。','conversations.message_count':'会话累计消息总数的缓存计数。',
 'conversations.inbound_count':'会话累计入站消息数的缓存计数。','conversations.outbound_count':'会话累计出站消息数的缓存计数。',
 'conversation_messages.reply_to_message_id':'当前消息所回复的消息标识，用于还原引用关系。','conversation_messages.attachment_count':'当前消息包含的附件数量。',
 'conversation_messages.has_sensitive_content':'标识消息是否检测到敏感内容，常规读取仍使用脱敏正文。','conversation_messages.source_event_id':'采集端来源事件标识，用于追踪和辅助去重。',
 'conversation_messages.ingestion_version':'消息采集和规范化规则版本，用于后续审计。',
 'contact_transfers.transfer_type':'转交业务类型；当前页面开放跨渠道转交。','contact_transfers.from_platform_id':'来源会话所属平台标识。',
 'contact_transfers.to_platform_id':'目标渠道账号所属平台标识。','contact_transfers.requested_by':'发起客户转交的用户标识。','contact_transfers.requested_at':'转交申请创建的毫秒时间戳。',
 'contact_transfers.accepted_by':'最终确认转交的用户标识。','contact_transfers.accepted_at':'转交确认完成的毫秒时间戳。','contact_transfers.rejected_by':'拒绝转交的用户标识。',
 'contact_transfers.rejected_at':'转交被拒绝的毫秒时间戳。','contact_transfers.cancelled_by':'取消转交的用户标识。','contact_transfers.cancelled_at':'转交被取消的毫秒时间戳。',
 'contact_transfers.failed_at':'转交被标记失败的毫秒时间戳。','contact_transfers.expired_at':'系统或用户将转交处理为过期的时间。','contact_transfers.rejection_reason':'拒绝转交时填写的业务原因。',
 'contact_transfers.failure_code':'转交失败的标准错误编码。','contact_transfers.failure_reason':'转交失败的详细业务原因。','contact_transfers.matched_identity_id':'用于确认同一客户的目标平台身份标识。',
 'contact_transfers.match_confidence':'身份与目标会话匹配置信度。','contact_transfers.match_evidence_json':'脱敏后的身份匹配证据 JSON。',
 'contact_transfer_events.from_status':'事件发生前的转交状态。','contact_transfer_events.to_status':'事件完成后的转交状态。','contact_transfer_events.details_json':'事件附加信息 JSON，用于时间线和审计排障。'
})

SENSITIVE={'password_hash','salt','access_token_hash','identity_value','observed_phone','manual_phone','payload_json','before_json','after_json','result_json','ip','user_agent'}
JSON_FIELDS={x for x in LABELS if x.endswith('_json')}|{'items_json'}
TIME_FIELDS={x for x in LABELS if x.endswith('_at')}

LOGICAL_RELATIONS=[
 ('organizations','organization_id','teams','organization_id','企业拥有团队'),('organizations','organization_id','users','organization_id','企业拥有用户'),('organizations','organization_id','workspaces','organization_id','企业拥有工作区'),('users','user_id','user_credentials','user_id','用户拥有认证凭证'),('users','user_id','sessions','user_id','用户产生登录会话'),('users','user_id','organization_memberships','user_id','用户加入企业'),('roles','role_id','organization_memberships','role_id','企业成员使用角色'),('users','user_id','team_memberships','user_id','用户加入团队'),('teams','team_id','team_memberships','team_id','团队包含成员'),('roles','role_id','role_permissions','role_id','角色包含权限'),('permissions','permission_key','role_permissions','permission_key','权限授予角色'),('organizations','organization_id','channel_accounts','organization_id','企业管理渠道账号'),('channel_accounts','channel_account_id','channel_account_identities','channel_account_id','账号包含外部身份'),('teams','team_id','team_channel_accounts','team_id','团队获得账号授权'),('channel_accounts','channel_account_id','team_channel_accounts','channel_account_id','账号授权给团队'),('channel_accounts','channel_account_id','sources','channel_account_id','来源归并到账号'),('sources','source_id','source_devices','source_id','来源出现于设备'),('devices','device_id','source_devices','device_id','设备观测来源'),('sources','source_id','contacts','source_id','来源产生联系人'),('devices','device_id','contacts','last_observed_device_id','设备最后观测联系人'),('contacts','contact_id','contact_tags','contact_id','联系人拥有标签'),('tags','tag_id','contact_tags','tag_id','标签关联联系人'),('contacts','contact_id','contact_custom_values','contact_id','联系人拥有扩展值'),('devices','device_id','device_assignments','device_id','设备具有分配历史'),('organizations','organization_id','device_enrollments','organization_id','企业创建设备接入邀请'),('workspaces','workspace_id','device_enrollments','workspace_id','工作区承载设备接入邀请'),('teams','team_id','device_enrollments','team_id','团队预分配设备接入邀请'),('users','user_id','device_enrollments','assigned_user_id','用户被预分配设备'),('devices','device_id','device_enrollments','consumed_device_id','正式设备核销接入邀请'),('platforms','platform_id','channel_types','platform_id','平台定义渠道类型'),('source_type_definitions','source_type_id','sources','source_type_id','来源引用标准类型')]

# 物理外键通用语义映射：(fromField, toTable) -> 关系动作描述
FK_REL_DESCRIPTIONS={
 ('organization_id','organizations'):'归属企业',
 ('workspace_id','workspaces'):'归属工作区',
 ('team_id','teams'):'归属团队',
 ('user_id','users'):'关联用户',
 ('role_id','roles'):'关联角色',
 ('contact_id','contacts'):'关联联系人',
 ('source_id','sources'):'关联来源',
 ('device_id','devices'):'关联设备',
 ('channel_account_id','channel_accounts'):'关联渠道账号',
 ('market_id','markets'):'关联市场',
 ('business_line_id','business_lines'):'关联业务线',
 ('department_id','departments'):'关联部门',
 ('platform_id','platforms'):'关联平台',
 ('parent_market_id','markets'):'上级市场为',
 ('parent_business_line_id','business_lines'):'上级业务线为',
 ('parent_department_id','departments'):'上级部门为',
 ('from_source_id','sources'):'父来源为',
 ('to_source_id','sources'):'子来源为',
 ('last_device_id','devices'):'最后观测设备为',
 ('assigned_user_id','users'):'分配给用户',
 ('granted_by','users'):'授权人为',
 ('deleted_by','users'):'删除人为',
 ('updated_by','users'):'更新人为',
 ('created_by','users'):'创建人为',
}

def _short_label(table):
    l=TABLES.get(table,(None,table))[1]
    return l[:-1] if l.endswith('表') and len(l)>1 else l

def _physical_fk_description(from_table,from_field,to_table,to_field):
    """物理外键释义：优先逻辑关联精确匹配，其次「表名+动作」语义映射，最后表名拼接。"""
    ldesc=next((rel[4] for rel in LOGICAL_RELATIONS if rel[0]==from_table and rel[1]==from_field and rel[2]==to_table and rel[3]==to_field),None)
    if ldesc:return ldesc
    fl=_short_label(from_table)
    action=FK_REL_DESCRIPTIONS.get((from_field,to_table))
    if action:return fl+action
    return fl+'关联'+_short_label(to_table)


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
 return '保存“'+label+'”对应的业务值。'

def _quote_identifier(name):
 """仅为已从 sqlite_schema 读取的对象名生成 PRAGMA 安全标识符。"""
 return '"'+str(name).replace('"','""')+'"'

def _infer_category(name,object_type='table'):
 rules=(
  (('schema_','meta','workspace_configs'),'system'),
  (('organizations','departments','teams','business_lines','markets','workspace_teams','workspace_business_lines','workspace_markets','team_markets','team_business_lines'),'organization'),
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


# 210.1.16 follow-up notification center catalog
# Keep Schema 222 documentation in the source-controlled, read-only catalog used by release_gate.py.
TABLES.update({
 'follow_up_notifications':('contact','客户跟进通知表','保存客户跟进计划、到期状态、负责人、渠道快照及完成或取消证据。'),
 'follow_up_notification_receipts':('contact','客户跟进通知回执表','按接收用户保存提醒、阅读、稍后、不再提醒及消费者领取租约。'),
 'platform_admin_notification_subscriptions':('contact','平台管理员通知代管表','记录平台超级管理员按企业选择代管的业务员通知范围。'),
})
LABELS.update({
 'notification_id':'通知标识','receipt_id':'回执标识','recipient_user_id':'接收用户','owner_user_id':'负责人',
 'follow_up_at':'计划跟进时间','follow_up_reason':'跟进事由','customer_name':'客户名称快照',
 'platform_code':'平台代码','platform_abbr':'平台简称','channel_account_name':'渠道账号名称',
 'source_device_id':'来源设备标识','source_device_name':'来源设备名称','completed_at':'完成时间',
 'completed_by_user_id':'完成人员','completion_mode':'完成方式','completion_message_id':'完成依据消息',
 'completion_evidence_json':'完成证据','cancelled_at':'取消时间','cancellation_reason':'取消或改期原因',
 'first_due_at':'首次到期时间','last_scanned_at':'最近扫描时间','contact_version':'联系人版本快照',
 'first_alerted_at':'首次提醒时间','last_alerted_at':'最近提醒时间','next_alert_at':'下次提醒时间',
 'alert_count':'提醒次数','read_at':'阅读时间','snooze_until':'稍后提醒截止时间','dismissed_at':'不再提醒时间',
 'claimed_by_consumer':'领取消费者','claim_expires_at':'领取租约到期时间',
 'last_consumer_type':'最近消费者类型','last_consumer_id':'最近消费者标识',
})
SPECIAL.update({
 'follow_up_notifications.notification_id':'客户跟进通知计划的唯一标识。',
 'follow_up_notifications.organization_id':'通知所属企业，用于租户隔离。',
 'follow_up_notifications.workspace_id':'通知所属工作区。',
 'follow_up_notifications.team_id':'客户及通知当前所属团队。',
 'follow_up_notifications.contact_id':'需要执行跟进的客户标识。',
 'follow_up_notifications.owner_user_id':'通知生成时的客户负责人；负责人变化后重新同步回执。',
 'follow_up_notifications.follow_up_at':'客户计划跟进的毫秒级 Unix 时间戳。',
 'follow_up_notifications.follow_up_reason':'设置跟进计划时填写的业务事由。',
 'follow_up_notifications.customer_name':'生成或同步通知时保存的客户名称快照。',
 'follow_up_notifications.platform_id':'客户最近会话对应的平台标识。',
 'follow_up_notifications.platform_code':'客户最近会话对应的平台代码快照。',
 'follow_up_notifications.platform_abbr':'客户最近会话对应的平台简称快照。',
 'follow_up_notifications.channel_account_id':'客户最近会话使用的渠道账号标识。',
 'follow_up_notifications.channel_account_name':'客户最近会话使用的渠道账号名称快照。',
 'follow_up_notifications.source_device_id':'最近观测该客户的来源设备标识。',
 'follow_up_notifications.source_device_name':'最近观测该客户的来源设备名称快照。',
 'follow_up_notifications.status':'通知生命周期状态，包括待到期、已到期、逾期、完成、取消或改期替代。',
 'follow_up_notifications.completed_at':'通知任务完成时的毫秒级 Unix 时间戳。',
 'follow_up_notifications.completed_by_user_id':'执行或触发完成动作的用户标识。',
 'follow_up_notifications.completion_mode':'完成方式，例如人工完成、出站消息或对账完成。',
 'follow_up_notifications.completion_message_id':'自动完成通知时作为证据的出站消息标识。',
 'follow_up_notifications.completion_evidence_json':'以 JSON 文本保存通知完成依据和上下文。',
 'follow_up_notifications.cancelled_at':'通知被取消或改期替代时的毫秒级 Unix 时间戳。',
 'follow_up_notifications.cancellation_reason':'记录取消、改期或被新计划替代的业务原因。',
 'follow_up_notifications.first_due_at':'通知首次进入已到期状态的毫秒级 Unix 时间戳。',
 'follow_up_notifications.last_scanned_at':'扫描器最近检查并对账该通知的毫秒级 Unix 时间戳。',
 'follow_up_notifications.contact_version':'最近同步通知时保存的联系人乐观锁版本。',
 'follow_up_notifications.version':'通知主记录的乐观锁版本。',
 'follow_up_notifications.created_at':'通知主记录创建时的毫秒级 Unix 时间戳。',
 'follow_up_notifications.updated_at':'通知主记录最后更新时的毫秒级 Unix 时间戳。',
 'follow_up_notification_receipts.receipt_id':'每位通知接收人的回执唯一标识。',
 'follow_up_notification_receipts.notification_id':'回执所关联的客户跟进通知标识。',
 'follow_up_notification_receipts.organization_id':'回执所属企业，用于租户隔离。',
 'follow_up_notification_receipts.recipient_user_id':'实际接收铃声、桌面通知及待处理任务的用户标识。',
 'follow_up_notification_receipts.status':'个人回执状态，包括未读、已读、稍后提醒、不再提醒或关闭。',
 'follow_up_notification_receipts.first_alerted_at':'该接收人首次收到提醒的毫秒级 Unix 时间戳。',
 'follow_up_notification_receipts.last_alerted_at':'该接收人最近一次收到提醒的毫秒级 Unix 时间戳。',
 'follow_up_notification_receipts.next_alert_at':'根据首次延迟或重复周期计算的下次允许提醒时间。',
 'follow_up_notification_receipts.alert_count':'该接收人已经触发的提醒累计次数。',
 'follow_up_notification_receipts.read_at':'接收人首次标记已读时的毫秒级 Unix 时间戳。',
 'follow_up_notification_receipts.snooze_until':'服务端依据用户偏好计算的稍后提醒截止时间。',
 'follow_up_notification_receipts.dismissed_at':'接收人选择不再提醒时的毫秒级 Unix 时间戳。',
 'follow_up_notification_receipts.claimed_by_consumer':'当前原子领取该提醒的管理中心或扩展消费者标识。',
 'follow_up_notification_receipts.claim_expires_at':'当前消费者领取租约失效的毫秒级 Unix 时间戳。',
 'follow_up_notification_receipts.last_consumer_type':'最近处理该回执的消费者类型。',
 'follow_up_notification_receipts.last_consumer_id':'最近处理该回执的消费者实例标识。',
 'follow_up_notification_receipts.version':'个人回执记录的乐观锁版本。',
 'follow_up_notification_receipts.created_at':'个人回执创建时的毫秒级 Unix 时间戳。',
 'follow_up_notification_receipts.updated_at':'个人回执最后更新时的毫秒级 Unix 时间戳。',
})

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
    physical=[{'fromField':f['from'],'toTable':f['table'],'toField':f['to'],'on_delete':f['on_delete'],'on_update':f['on_update'],'kind':'physical','description':_physical_fk_description(name,fname,f['table'],f['to'])} for f in fks if f['from']==fname]
    logical=[{'toTable':rel[2],'toField':rel[3],'description':rel[4],'kind':'logical','evidence':'V207_schema_catalog.LOGICAL_RELATIONS'} for rel in LOGICAL_RELATIONS if rel[0]==name and rel[1]==fname]
    if physical:tags.append('FK')
    elif logical:tags.append('逻辑关联')
    for f in physical:
     _pdesc=_physical_fk_description(name,fname,f['toTable'],f['toField'])
     physical_relations.append({'fromTable':name,'fromField':fname,'toTable':f['toTable'],'toField':f['toField'],'description':_pdesc,'kind':'physical','cardinality':'N:1','onDelete':f['on_delete'],'onUpdate':f['on_update'],'evidence':'PRAGMA foreign_key_list'})
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

# V207.5.0-dev 更新说明（2026-09-20）：改用 table_xinfo/index_xinfo，覆盖全部表、视图、触发器；取消业务记录计数，补充分类、覆盖率、物理及逻辑关系诊断。

# V207.5.0-dev 更新说明（2026-09-20）：运行时提取表、视图、字段、索引和物理外键，并合并中文释义、逻辑关联与文档覆盖率；全程不读取业务记录。


# ============================================================
# 【字典补丁 v1】2026-09 全库审计补充：V207.7 新表登记 + 缺失字段释义 + 全量逻辑关系
# 说明：本补丁为纯追加式（update/extend），不修改上方任何原有定义。
# ============================================================

# ---- 1. 补登记 5 张 V207.7 新增表（原"未分类"来源）----
TABLES.update({
    'positions':               ('organization','职位表','定义企业内职位及其部门归属，职位编码在企业内唯一。'),
    'user_positions':          ('organization','用户职位关系表','建立用户与职位的多对多关系，可标记唯一主职位。'),
    'role_bindings':           ('rbac','角色绑定表','按平台、企业、工作区、部门、团队或个人作用域将角色授予用户，是统一授权模型核心。'),
    'platform_administrators': ('identity','平台管理员表','登记平台级管理员及其内置标记与首次登录引导状态。'),
    'rbac_confirmations':      ('audit','RBAC 确认凭证表','为高风险授权操作签发短期二次确认凭证，含令牌摘要、过期时间与一次性消费标记。'),
})

# ---- 2. 补字段级释义（消除"XX 的持久化字段"兜底文案）----
LABELS.update({
    # 归因组
    'attribution_id':'归因记录 ID','attribution_type':'归因类型','attribution_weight':'归因权重',
    'confidence':'置信度','attributed_at':'归因时间','touchpoint_id':'触点 ID',
    # 职位组
    'position_id':'职位 ID','code':'编码','binding_id':'绑定记录 ID',
    # RBAC 新表组
    'action_key':'操作动作编码','token_digest':'确认令牌摘要','context_json':'操作上下文',
    'consumed_at':'消费时间','onboarding_completed':'是否完成首次引导','is_builtin':'是否内置',
    'link_type':'关系类型','occurred_at':'发生时间','link_id':'关系 ID',
    'grant_reason':'授权原因','grant_type':'授权类型','approved_by':'授权审批人',
})

SPECIAL.update({
    'positions.code':                     '企业内职位编码，与 organization_id 联合唯一。',
    'positions.department_id':            '可选；为空表示职位直属企业不挂部门。',
    'role_bindings.scope_type':           '授权作用域层级：platform/organization/workspace/department/team/self。',
    'role_bindings.scope_id':             '作用域对象 ID，含义随 scope_type 变化；self 时对应用户自身。',
    'role_bindings.granted_by':           '授权操作者，用户删除时置空以保留审计线索。',
    'role_bindings.grant_reason':         '角色授权的业务原因，授权操作必须填写并保留审计。',
    'role_bindings.grant_type':           '授权类型：standard/temporary/acting/emergency；非标准授权必须设置到期时间。',
    'role_bindings.approved_by':          '授权审批人用户 ID，用于追溯高风险授权责任。',
    'platform_administrators.is_builtin': '是否系统内置管理员，内置账号不可删除。',
    'rbac_confirmations.token_digest':    '确认令牌摘要，原文不落库，单次有效。',
    'rbac_confirmations.expires_at':      '凭证过期时间（约 5 分钟 TTL），过期即作废。',
    'rbac_confirmations.consumed_at':     '凭证被使用的时间；非空表示已消费不可复用。',
    'contact_attributions.confidence':    '归因置信度，unknown 表示模型未给出确定判断。',
    'contact_attributions.is_primary':    '同一联系人的多条归因中仅一条主关系。',
})

# ---- 3. 补全逻辑关系（物理外键中文释义 + 纯业务逻辑关联）----
# 注意：个别字段名基于命名规范推断，部署后请刷新页面核对"实体关系目录"；
#       若某条未生效，将字段名改为该表实际列名即可。
LOGICAL_RELATIONS.extend([
    # 职位域
    ('positions','organization_id','organizations','organization_id','职位归属企业'),
    ('positions','department_id','departments','department_id','职位归属部门（可空）'),
    ('user_positions','user_id','users','user_id','用户担任职位'),
    ('user_positions','position_id','positions','position_id','职位被用户担任'),
    ('user_positions','organization_id','organizations','organization_id','任职关系限定企业'),
    # 统一授权域
    ('role_bindings','user_id','users','user_id','角色绑定授予用户'),
    ('role_bindings','role_id','roles','role_id','绑定的角色'),
    ('role_bindings','organization_id','organizations','organization_id','企业级绑定限定企业'),
    ('role_bindings','granted_by','users','user_id','授权操作者'),
    ('role_bindings','approved_by','users','user_id','授权审批人'),
    ('platform_administrators','user_id','users','user_id','平台管理员对应登录用户'),
    ('rbac_confirmations','user_id','users','user_id','确认凭证所属用户'),
    # 归因主链路
    ('contact_attributions','contact_id','contacts','contact_id','归因指向的联系人'),
    ('contact_attributions','source_id','sources','source_id','归因贡献来源'),
    ('contact_attributions','touchpoint_id','source_touchpoints','touchpoint_id','归因贡献触点'),
    # 触点链路
    ('source_touchpoints','contact_id','contacts','contact_id','触点所属联系人'),
    ('source_touchpoints','source_id','sources','source_id','触点发生的来源'),
    ('source_touchpoints','campaign_id','campaigns','campaign_id','触点关联的营销活动'),
    # 活动与渠道
    ('campaigns','channel_account_id','channel_accounts','channel_id','活动承接的渠道账号'),
    ('campaigns','workspace_id','workspaces','workspace_id','活动归属工作区'),
    ('channel_accounts','platform_id','platforms','platform_id','渠道账号所属全局平台'),
    # 组织层级
    ('departments','parent_department_id','departments','department_id','部门上级（自引用层级）'),
    ('business_lines','parent_business_line_id','business_lines','business_line_id','业务线上级（自引用层级）'),
    ('markets','parent_market_id','markets','market_id','市场上级（自引用层级）'),
    ('teams','organization_id','organizations','organization_id','团队归属企业'),
])

# ============================================================
# 【Schema 214 中文数据字典完整性补丁】2026-09-24
# 基线：61 张物理表、668 个物理字段；禁止表用途或字段中文名称回退。
# ============================================================
TABLES.update({
    'plugin_sessions': ('identity','插件会话凭证表','保存插件独立访问凭证的摘要、用户与设备绑定范围、有效期、撤销状态及客户端版本，不授予后台管理会话权限。'),
    'device_channel_account_bindings': ('device','设备渠道账号绑定表','记录采集设备与外部渠道账号的发现、绑定及最后核验关系，用于确定消息采集归属。'),
    'conversations': ('contact','渠道会话表','保存工作区内联系人身份与渠道账号之间的外部会话标识、会话类型及消息时间范围。'),
    'conversation_messages': ('contact','会话消息表','保存渠道会话消息的幂等标识、发送方、内容类型、脱敏正文、采集时间及正文删除审计状态。'),
    'contact_transfers': ('contact','联系人跨渠道转移表','记录联系人在渠道账号或会话之间的转移来源、目标、方式、操作者及确认状态。'),
    'account_binding_slots': ('channel','账号绑定槽位表','保存用户在工作区和团队范围内可认领的平台账号槽位、匹配预期、审批策略及认领结果。'),
    'account_identity_discoveries': ('channel','账号身份发现表','记录插件发现的平台身份、规范化值、审批状态、冲突原因及管理员处理结果。'),
})

LABELS.update({
    'ip_address':'IP 地址','platform_id':'平台 ID','start_at':'开始时间','end_at':'结束时间',
    'valid_from':'生效开始时间','valid_to':'生效结束时间','account_type':'账号类型',
    'business_purpose':'业务用途','collection_enabled':'是否启用采集','contact_identity_id':'联系人身份 ID',
    'transfer_id':'转移记录 ID','from_channel_account_id':'来源渠道账号 ID','from_conversation_id':'来源会话 ID',
    'to_channel_account_id':'目标渠道账号 ID','to_conversation_id':'目标会话 ID','transfer_method':'转移方式',
    'transferred_by':'转移操作者','transferred_at':'转移时间','confirmed_by':'确认人','confirmed_at':'确认时间',
    'message_id':'消息 ID','conversation_id':'会话 ID','external_message_id':'外部消息 ID',
    'client_event_id':'客户端事件 ID','sender_type':'发送方类型','sender_external_id':'发送方外部 ID',
    'content_type':'内容类型','text_content':'消息正文','redacted_text':'脱敏正文','content_hash':'内容摘要',
    'pii_flags_json':'个人信息标记','collected_at':'采集时间','edited_at':'编辑时间',
    'content_deleted_at':'正文删除时间','content_deleted_by':'正文删除人','content_delete_reason':'正文删除原因',
    'external_conversation_id':'外部会话 ID','conversation_type':'会话类型','first_message_at':'首条消息时间',
    'last_message_at':'末条消息时间','last_collected_at':'最后采集时间','field_role':'字段角色',
    'display_zone':'展示区域','is_quick_edit':'是否支持快捷编辑','options_json':'候选选项配置',
    'placeholder':'输入提示','external_account_key':'外部账号键','bound_at':'绑定时间','bound_by':'绑定操作者',
    'last_verified_at':'最后核验时间','market_type':'市场类型','country_code':'国家代码',
    'region_code':'区域代码','timezone':'时区','resource':'权限资源','action':'权限动作',
    'scope_mask':'作用域掩码','risk_level':'风险等级','module_code':'权限模块编码','recommendation':'授权建议','related_pages_json':'关联页面清单','related_apis_json':'关联接口清单','capabilities_json':'平台能力配置',
    'platform_abbr':'平台简称','plugin_session_id':'插件会话 ID','token_hash':'令牌摘要',
    'issued_at':'签发时间','revoked_reason':'撤销原因','client_version':'客户端版本',
    'role_code':'角色编码','is_system':'是否系统内置','detail_json':'事件详情',
    'initiated_by':'发起方','external_event_id':'外部事件 ID','source_type':'来源类型',
    'source_subtype':'来源子类型','parent_source_id':'上级来源 ID','external_key':'外部业务键',
    'landing_url':'落地页地址','tracking_code':'追踪代码','tag_kind':'标签种类',
    'membership_type':'成员关系类型','joined_at':'加入时间','left_at':'离开时间',
    'failed_attempts':'连续失败次数','locked_until':'锁定截止时间','last_failed_at':'最后失败时间',
    'relation_type':'关系类型','access_level':'访问级别',
    'slot_id':'绑定槽位 ID','expected_phone':'预期电话号码','expected_username':'预期用户名',
    'claim_policy':'认领策略','claimed_identity_type':'已认领身份类型','claimed_canonical_value':'已认领规范值',
    'claimed_device_id':'认领设备 ID','claimed_at':'认领时间','disabled_at':'禁用时间','disabled_by':'禁用操作者',
    'discovery_id':'身份发现 ID','auxiliary_json':'辅助信息','reason_code':'原因编码',
    'resolved_at':'处理时间','resolved_by':'处理操作者','resolution_reason':'处理原因',
})

SPECIAL.update({
    'channel_accounts.business_purpose':'渠道账号的业务用途，仅允许 acquisition（获客）、conversion（转化）或 hybrid（混合）。',
    'channel_accounts.collection_enabled':'控制该渠道账号是否允许 Collector 采集消息，必须保存为布尔值。',
    'plugin_sessions.token_hash':'插件访问令牌的不可逆摘要；数据库不保存令牌明文。',
    'plugin_sessions.revoked_reason':'插件会话被主动撤销或安全策略终止时记录的原因。',
    'device_channel_account_bindings.external_account_key':'设备侧发现的外部账号稳定键，用于解析或匹配正式渠道账号。',
    'conversation_messages.client_event_id':'采集客户端生成的幂等键，用于阻止同一消息被重复写入。',
    'conversation_messages.text_content':'原始消息正文，读取时必须具备 message.read.raw 权限。',
    'conversation_messages.redacted_text':'移除或掩码个人敏感信息后可用于常规展示的消息正文。',
    'conversation_messages.pii_flags_json':'记录正文中识别出的个人敏感信息类型及处理标记的 JSON。',
    'conversation_messages.content_deleted_at':'非空表示消息正文已按审计流程删除，但消息结构和审计信息仍保留。',
    'contact_transfers.transfer_method':'联系人跨渠道转移方式，用于区分人工、规则或系统自动转移。',
    'custom_field_definitions.field_role':'自定义字段在业务流程中的角色，用于约束用途和展示行为。',
    'custom_field_definitions.display_zone':'自定义字段在联系人界面中的展示区域。',
    'custom_field_definitions.is_quick_edit':'控制该字段是否允许在联系人快捷编辑区直接修改。',
    'custom_field_definitions.options_json':'选择类字段的候选项配置 JSON，写入时执行严格结构校验。',
    'tags.tag_kind':'标签种类；status 表示状态标签，并对单个联系人执行单选约束。',
    'permissions.scope_mask':'权限允许作用的范围掩码，用于限制平台、企业、工作区或个人层级。',
    'permissions.module_code':'权限所属功能模块的稳定编码，用于权限目录分组和管理界面导航。',
    'permissions.recommendation':'该权限的最小授权、风险控制和定期复核建议。',
    'permissions.related_pages_json':'使用该权限的前端页面编码清单，以 JSON 数组保存。',
    'permissions.related_apis_json':'受该权限保护的服务端接口清单，以 JSON 数组保存。',
    'user_credentials.failed_attempts':'当前连续认证失败次数，成功登录后按认证策略清零。',
    'user_credentials.locked_until':'账号因连续认证失败被锁定至该时间；为空表示未锁定。',
    'account_binding_slots.claim_policy':'账号认领策略；auto 表示满足唯一槽位和身份预期时自动认领，approval 表示必须由管理员审批。',
    'account_binding_slots.claimed_canonical_value':'槽位成功认领后保存的平台身份规范值，用于后续一致性核验。',
    'account_binding_slots.expected_phone':'管理员预设的电话号码期望值；自动认领时必须与规范化后的插件身份一致。',
    'account_binding_slots.expected_username':'管理员预设的平台用户名期望值；自动认领时必须与规范化后的插件身份一致。',
    'account_identity_discoveries.canonical_value':'插件上报身份经平台规则规范化后的稳定值，用于幂等发现、冲突检测和审批。',
    'account_identity_discoveries.auxiliary_json':'保存身份发现过程中的非主键辅助信息 JSON，不作为授权判断的唯一依据。',
    'account_identity_discoveries.reason_code':'记录待审批、冲突或无法自动认领的机器可读原因编码。',
    'account_identity_discoveries.resolution_reason':'管理员审批、拒绝或其他处理决定的文字依据。',
})


# Schema 214 账号认领域逻辑关系（同时补充物理外键的中文业务语义）。
LOGICAL_RELATIONS.extend([
    ('account_binding_slots','organization_id','organizations','organization_id','绑定槽位归属企业'),
    ('account_binding_slots','workspace_id','workspaces','workspace_id','绑定槽位限定工作区'),
    ('account_binding_slots','team_id','teams','team_id','绑定槽位限定团队'),
    ('account_binding_slots','user_id','users','user_id','绑定槽位分配用户'),
    ('account_binding_slots','platform_id','platforms','platform_id','绑定槽位对应平台'),
    ('account_binding_slots','channel_account_id','channel_accounts','channel_account_id','绑定槽位预分配渠道账号'),
    ('account_identity_discoveries','organization_id','organizations','organization_id','身份发现归属企业'),
    ('account_identity_discoveries','workspace_id','workspaces','workspace_id','身份发现发生工作区'),
    ('account_identity_discoveries','team_id','teams','team_id','身份发现发生团队'),
    ('account_identity_discoveries','user_id','users','user_id','身份发现所属用户'),
    ('account_identity_discoveries','platform_id','platforms','platform_id','身份发现对应平台'),
    ('account_identity_discoveries','slot_id','account_binding_slots','slot_id','身份发现匹配绑定槽位'),
    ('account_identity_discoveries','channel_account_id','channel_accounts','channel_account_id','身份发现解析渠道账号'),
])

# 【Schema 221 客户身份与访问控制数据字典】2026-09-30
TABLES.update({
    'contact_team_access': ('contact','客户团队访问授权表','记录客户对团队的访问授权级别、授权来源、生效状态及授予和撤销审计信息。'),
    'contact_match_reviews': ('contact','客户重复匹配审核表','记录两个疑似重复客户之间的匹配类型、证据、审核结论及审核操作信息。'),
    'contact_merge_history': ('contact','客户合并历史表','记录源客户合并至目标客户时的合并前版本、字段解决方案、影响范围及执行审计信息。'),
})

LABELS.update({
    'access_id':'访问授权 ID',
    'review_id':'匹配审核 ID',
    'contact_id_a':'候选客户 A ID',
    'contact_id_b':'候选客户 B ID',
    'match_type':'匹配类型',
    'evidence_json':'匹配证据',
    'reviewed_by':'审核人',
    'reviewed_at':'审核时间',
    'merge_id':'客户合并 ID',
    'target_contact_id':'目标客户 ID',
    'source_contact_id':'源客户 ID',
    'target_version_before':'目标客户合并前版本',
    'source_version_before':'源客户合并前版本',
    'resolution_json':'字段解决方案',
    'impact_json':'合并影响范围',
    'merged_by':'合并执行人',
})

SPECIAL.update({
    'contact_team_access.access_id':'客户团队访问授权记录的唯一标识，用于授权变更和撤销审计。',
    'contact_match_reviews.review_id':'疑似重复客户匹配审核记录的唯一标识。',
    'contact_match_reviews.contact_id_a':'参与重复匹配判断的第一位候选客户标识。',
    'contact_match_reviews.contact_id_b':'参与重复匹配判断的第二位候选客户标识。',
    'contact_match_reviews.match_type':'说明疑似重复关系的识别类型，例如身份、联系方式或人工规则匹配。',
    'contact_match_reviews.evidence_json':'以 JSON 文本保存支持或排除重复判断的结构化匹配证据。',
    'contact_match_reviews.reviewed_by':'记录执行重复匹配审核并作出结论的用户标识。',
    'contact_match_reviews.reviewed_at':'记录重复匹配审核完成时的毫秒级 Unix 时间戳；为空表示尚未审核。',
    'contact_merge_history.merge_id':'一次不可变客户合并审计记录的唯一标识。',
    'contact_merge_history.target_contact_id':'合并后保留并承接业务数据的目标客户标识。',
    'contact_merge_history.source_contact_id':'合并后被归并至目标客户的源客户标识。',
    'contact_merge_history.target_version_before':'执行合并前目标客户的版本号，用于并发校验和审计追踪。',
    'contact_merge_history.source_version_before':'执行合并前源客户的版本号，用于并发校验和审计追踪。',
    'contact_merge_history.resolution_json':'以 JSON 文本保存冲突字段的选择、覆盖或合并解决方案。',
    'contact_merge_history.impact_json':'以 JSON 文本保存本次合并影响的身份、关系及业务记录范围。',
    'contact_merge_history.merged_by':'记录执行并确认客户合并操作的用户标识。',
})



# 【Schema 222 跨平台会话与客户转交数据字典】2026-09-30
TABLES.update({
 'contact_transfer_events':('audit','客户转交事件表','按时间记录客户跨渠道转交的创建、匹配、确认、拒绝、取消、失败、过期及目标会话关联事件。'),
 'contact_transfers':('contact','客户跨渠道转交表','保存客户从来源平台会话转向目标渠道账号的状态、匹配证据、幂等键、版本及处理审计信息。'),
 'conversations':('contact','跨平台渠道会话表','保存客户在各平台渠道账号中的独立会话及状态、负责人、最后消息摘要和聚合计数。'),
 'conversation_messages':('contact','跨平台会话消息表','保存消息原始归属、稳定排序时间、回复关系、敏感标记、附件数量和采集版本。'),
})
LABELS.update({
 'transfer_type':'转交类型','from_platform_id':'来源平台 ID','to_platform_id':'目标平台 ID',
 'requested_by':'发起人','requested_at':'发起时间','accepted_by':'接收人','accepted_at':'接收时间',
 'rejected_by':'拒绝人','rejected_at':'拒绝时间','cancelled_by':'取消人','cancelled_at':'取消时间',
 'failed_at':'失败时间','expired_at':'实际过期时间','rejection_reason':'拒绝原因','failure_code':'失败编码',
 'failure_reason':'失败原因','matched_identity_id':'匹配身份 ID','match_confidence':'匹配置信度',
 'match_evidence_json':'匹配证据 JSON','from_status':'原状态','to_status':'目标状态','details_json':'事件详情 JSON',
 'reply_to_message_id':'回复消息 ID','attachment_count':'附件数量','has_sensitive_content':'是否含敏感内容',
 'source_event_id':'来源事件 ID','ingestion_version':'采集版本','closed_at':'关闭时间','closed_by':'关闭人',
 'archived_at':'归档时间','archived_by':'归档人','last_message_id':'最后消息 ID',
 'last_message_direction':'最后消息方向','last_message_type':'最后消息类型','last_message_preview':'最后消息摘要',
 'message_count':'消息总数','inbound_count':'入站消息数','outbound_count':'出站消息数',
})
SPECIAL.update({
 'contact_transfer_events.from_status':'事件发生前的转交状态；创建事件允许为空。',
 'contact_transfer_events.to_status':'事件完成后的转交状态，用于重建不可变状态时间线。',
 'contact_transfer_events.details_json':'保存匹配证据更新、关联结果等事件扩展信息的 JSON。',
 'contact_transfers.match_evidence_json':'保存身份、号码或用户名等脱敏匹配依据的结构化 JSON。',
 'contact_transfers.match_confidence':'目标身份匹配置信度，范围为零到一百。',
 'conversation_messages.has_sensitive_content':'标识消息是否检测到敏感内容，常规读取优先返回脱敏正文。',
 'conversation_messages.source_event_id':'采集端来源事件标识，用于跨批次追踪和诊断。',
 'conversation_messages.ingestion_version':'记录写入消息时使用的采集协议版本。',
 'conversations.last_message_preview':'会话列表直接使用的脱敏末条消息摘要，避免重复聚合查询。',
 'conversations.message_count':'会话消息总数的增量汇总值，用于列表和统计快速读取。',
 'conversations.inbound_count':'会话入站消息增量汇总值。',
 'conversations.outbound_count':'会话出站消息增量汇总值。',
})

# 【V210.1.11 WhatsApp 可信身份与会话别名数据字典】2026-10-04
TABLES.update({
 'conversation_external_aliases':('contact','会话外部身份别名表','记录直接会话观测到的平台原生会话标识及其可信证据，使 LID 与 JID 切换时仍复用同一会话。'),
 'whatsapp_identity_links':('contact','WhatsApp 身份映射表','记录从同一 WhatsApp Chat 或 Contact 模型共同观测到的 LID、JID 与内部客户之间的可信映射。'),
})
LABELS.update({
 'alias_id':'会话别名 ID','alias_type':'会话别名类型','alias_value':'会话别名值',
 'evidence_source':'可信证据来源','link_id':'身份映射 ID','lid_canonical':'LID 规范值',
 'jid_canonical':'JID 规范值','verification_status':'核验状态','first_seen_at':'首次观测时间',
 'last_seen_at':'最后观测时间','metadata_json':'扩展元数据 JSON',
})
SPECIAL.update({
 'conversation_external_aliases.alias_id':'会话外部身份别名记录的全局唯一标识。',
 'conversation_external_aliases.alias_type':'标明别名是 WhatsApp LID、WhatsApp JID 或其他平台原生会话标识。',
 'conversation_external_aliases.alias_value':'从平台原生模型观测到的会话或联系人身份值；不得由显示名称或页面手机号文本推导。',
 'conversation_external_aliases.evidence_source':'记录会话别名的可信来源，用于阻止基于页面展示文本建立身份关联。',
 'whatsapp_identity_links.link_id':'一组可信 WhatsApp LID 与 JID 映射记录的全局唯一标识。',
 'whatsapp_identity_links.lid_canonical':'经过标准化的 WhatsApp LID；在企业、工作区和平台范围内唯一。',
 'whatsapp_identity_links.jid_canonical':'经过标准化的 WhatsApp JID；在企业、工作区和平台范围内唯一。',
 'whatsapp_identity_links.evidence_source':'证明 LID 与 JID 同时来自同一 WhatsApp Chat 或 Contact 模型的证据来源。',
 'whatsapp_identity_links.verification_status':'身份映射核验状态，仅允许 observed、verified 或 revoked。',
})
LOGICAL_RELATIONS.extend([
 ('conversation_external_aliases','conversation_id','conversations','conversation_id','会话别名所属的内部会话'),
 ('conversation_external_aliases','contact_id','contacts','contact_id','会话别名解析到的内部客户'),
 ('whatsapp_identity_links','contact_id','contacts','contact_id','WhatsApp 身份映射所属的内部客户'),
])
