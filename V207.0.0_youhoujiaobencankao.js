// ==UserScript==
// @name         V207.0.0- 聚宝盆客户信息管理系统（实时同步）
// @namespace    wa-remark-helper
// @version      207.0.0
// @description  V207.0.0 修复事件确认隔离、精准脏字段上传、死信队列及自动刷新状态可视化。
// @match        https://web.whatsapp.com/*
// @match        http://127.0.0.1:8765/dashboard*
// @match        http://localhost:8765/dashboard*
// @match        https://www.instagram.com/direct/*
// @match        https://www.messenger.com/*
// @match        https://www.facebook.com/messages/*
// @match        https://web.telegram.org/k/*
// @match        https://web.telegram.org/a/*
// 多机部署：远程打开 Dashboard 时，把下面的示例改成你的服务器地址（match 模式不写端口，会自动匹配任意端口，
// 例如 http://192.168.1.10:8765/dashboard 只需写 http://192.168.1.10/dashboard*），然后删掉本行与示例行开头的"//"：
// @match        http://192.168.1.10/dashboard*
// @grant        unsafeWindow
// @grant        GM_info
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_registerMenuCommand
// @grant        GM_setClipboard
// @grant        GM_xmlhttpRequest
// @grant        GM_addValueChangeListener
// @grant        GM_removeValueChangeListener
// @connect      *
// @run-at       document-idle
// ==/UserScript==

(function () {
  "use strict";

  // 旧命令协议：远程 Dashboard 模式（多机）。任何主机、只要端口 8765 + 路径 /dashboard 就挂载管理面板；
  // 需要在 Tampermonkey 中为本脚本的 @match 加入服务器地址（match 模式不写端口，任意端口均可匹配）。
  var STANDALONE_DASHBOARD_MODE = (/^\/dashboard\/?$/.test(location.pathname));

  // v124：系统名称、当前版本与导出文件名使用同一数据源。
  var SYSTEM_NAME_V124 = "聚宝盆客户信息管理系统";
  var SYSTEM_VERSION_V124 = (function () {
    try {
      var value = GM_info && GM_info.script && GM_info.script.version;
      return String(value || "206.0.7").replace(/^v/i, "").trim() || "206.0.7";
    } catch (e) { return "206.0.7"; }
  })();
  function getDisplayVersionV124() { return "v" + SYSTEM_VERSION_V124; }
  function padLocalTimeV124(value) { return String(value).padStart(2, "0"); }
  function getLocalExportTimeV124(date) {
    date = date instanceof Date ? date : new Date();
    return String(date.getFullYear()) + padLocalTimeV124(date.getMonth() + 1) +
      padLocalTimeV124(date.getDate()) + "_" + padLocalTimeV124(date.getHours()) +
      padLocalTimeV124(date.getMinutes()) + padLocalTimeV124(date.getSeconds());
  }
  function getExportFilenameV124(extension, date) {
    extension = String(extension || "").replace(/^\./, "");
    return SYSTEM_NAME_V124 + "_" + getDisplayVersionV124() + "_" +
      getLocalExportTimeV124(date) + (extension ? "." + extension : "");
  }

  // v124：严格基于完整 v123；统一三个导出入口的文件名，并将动态版本号嵌入标题右侧聚宝盆盆身。
  // v123：严格基于完整 v121.8；已存在的非空联系人清空后继续按原逻辑自动删除，
  //       并收集实际删除的联系人 ID，同步调用 batch-delete 删除 Python 服务端 SQLite 对应记录。
  //       不继承 v121.9、v121.10 或 v122 的改动。
  // v121.8：修复 Facebook/Messenger 姓名与头像错配；会话上下文必须连续复验通过后才允许写入。
  // v121.7：加固 Instagram 会话身份识别；历史 ig-thread 记录在验证阶段保持只读，
  //         禁止自动删除、覆盖、新增、迁移或合并，避免身份尚未稳定时破坏历史记录。
  // v121：基于完整 v117，保留 v120 WA 安全识别，并加入全渠道非破坏性身份注册表。
  // v117：跨窗口主监控选举；本地同步服务与原接口保持不变。
  // v111：关联组颜色收敛至电话栏，主记录与子记录稳定同色。
  // v100.4：管理面板编辑不中断（编辑锁、延迟刷新、中文输入法组合保护）。

  var STORAGE_KEY = "jubo_v205_ui_contacts";
  var SETTINGS_KEY = "wa_remarks_settings";
  // v121：身份层与旧业务资料分离。旧版本地资料库 仍为事实业务库，以下键只保存身份映射。
  var CRM_SCHEMA_KEY = "crm_identity_schema";
  var CRM_CUSTOMERS_KEY = "crm_customers";
  var CRM_ACCOUNTS_KEY = "crm_channel_accounts";
  var CRM_IDENTITIES_KEY = "crm_identities";
  var CRM_IDENTITY_INDEX_KEY = "crm_identity_index";
  var CRM_LEGACY_BINDINGS_KEY = "crm_legacy_bindings";
  var CRM_OBSERVATIONS_KEY = "crm_identity_observations";
  var CRM_CONFLICTS_KEY = "crm_identity_conflicts";
  var CRM_MIGRATION_LOG_KEY = "crm_migration_log";
  var CRM_MERGE_HISTORY_KEY = "crm_merge_history";
  // 旧命令协议：多机共用。服务地址不再硬编码——可在 Tampermonkey 菜单“设置同步服务地址”中
  // 指向中心服务端（局域网 IP 或公网地址），多台电脑/浏览器共用同一服务与共享库。
  var LOCAL_SYNC_URL = "http://127.0.0.1:8765";
  try { var __旧命令协议InitServerUrl = String(GM_getValue('jubo_v205_server_url', '') || '').trim().replace(/\/+$/, ''); if (__旧命令协议InitServerUrl) LOCAL_SYNC_URL = __旧命令协议InitServerUrl; } catch (e) {}
  function getLocalSyncServerUrl() {
    try { var u = String(GM_getValue('jubo_v205_server_url', '') || '').trim().replace(/\/+$/, ''); if (u) return u; } catch (e) {}
    return LOCAL_SYNC_URL;
  }
  function setLocalSyncServerUrl(u) {
    u = String(u || '').trim().replace(/\/+$/, '');
    try { GM_setValue('jubo_v205_server_url', u); } catch (e) {}
    LOCAL_SYNC_URL = u || 'http://127.0.0.1:8765';
    return LOCAL_SYNC_URL;
  }
  async function v207Login(){
    var org=prompt('企业 ID','org_default'); if(!org)return;
    var user=prompt('用户名','admin'); if(!user)return;
    var pwd=prompt('密码（输入仅用于本次登录）',''); if(!pwd)return;
    var r=await fetch(getLocalSyncServerUrl()+'/api/v207/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({organizationId:org,loginName:user,password:pwd})});
    var d=await r.json(); if(!r.ok||!d.accessToken){alert(d.message||d.code||'登录失败');return;}
    GM_setValue('jubo_v207_access_token',d.accessToken);alert('V207 登录成功：'+(d.user&&d.user.display_name||user));location.reload();
  }
  try{GM_registerMenuCommand('V207 企业账号登录',v207Login);GM_registerMenuCommand('V207 退出登录',function(){GM_deleteValue('jubo_v207_access_token');location.reload();});}catch(e){}
  function getLocalSyncAuthHeaders() {
    var headers = { 'Content-Type': 'application/json' };
    try { var t = String(GM_getValue('jubo_v207_access_token', '') || '').trim(); if (t) headers['Authorization'] = 'Bearer ' + t; } catch (e) {}
    return headers;
  }
  var LOCAL_SYNC_SOURCE_ID_KEY = "jubo_v205_ui_instance_id"; // 仅供旧 UI 内部临时键，不作为来源身份
  var LOCAL_SYNC_SOURCE_NAME_KEY = "jubo_v205_device_name";
  var LOCAL_SYNC_LAST_STATUS = { ok:false, message:"未连接", sources:[], contacts:[], stats:null };
  var LOCAL_SYNC_UPLOAD_KEY = "wa_local_sync_realtime_upload_enabled";
  var LOCAL_SYNC_AGGREGATE_KEY = "wa_local_sync_aggregate_enabled";
  var LOCAL_SYNC_AGGREGATE_TIMER = null;
  var LOCAL_SYNC_UPLOAD_TIMER = null;
  var LOCAL_SYNC_RUNNING = false;
  var LOCAL_SYNC_LAST_AUTO_AT = 0;
  // v112：同步运行控制——心跳、非重叠汇总、上传脏队列。
  var LOCAL_SYNC_HEARTBEAT_TIMER = null;
  var LOCAL_SYNC_HEARTBEAT_RUNNING = false;
  var LOCAL_SYNC_HEARTBEAT_INTERVAL = 5000;
  var LOCAL_SYNC_AGGREGATE_RUNNING = false;
  var LOCAL_SYNC_AGGREGATE_INTERVAL = 5000;
  // 旧快照协议-alpha1：汇总任务令牌与协议状态。
  var LOCAL_SYNC_AGGREGATE_STARTED_AT = 0;
  var LOCAL_SYNC_AGGREGATE_TASK_TOKEN = "";
  // V205：旧 V117/V128 Leader、租约、快照与 ACK 状态变量已物理移除。

  var FIELDS = [
    { key: "f1", label: "1." },
    { key: "f2", label: "2." },
    { key: "f3", label: "3." },
    { key: "f4", label: "4." },
    { key: "f5", label: "5." },
    { key: "f6", label: "6." },
    { key: "f7", label: "7." },
    { key: "f8", label: "闪光点" },
    { key: "remark", label: "说明" }
  ];

  var STAGES = [
    { key: "s1", label: "一切" },
    { key: "s2", label: "二切" },
    { key: "s3", label: "三切" }
  ];

  var DEFAULT_TAGS1 = [
    { key: "hot", label: "HOT高意向", color: "#e53935" },
    { key: "watch", label: "观察中", color: "#fb8c00" },
    { key: "done", label: "已成交", color: "#43a047" },
    { key: "lost", label: "已流失", color: "#9e9e9e" },
    { key: "other", label: "其他", color: "#5c6bc0" },
    { key: "", label: "无标签", color: "#cfd8dc" }
  ];

  var DEFAULT_TAGS2 = [
    { key: "vip", label: "高客单", color: "#8e24aa" },
    { key: "us", label: "美区", color: "#1e88e5" },
    { key: "eu", label: "欧区", color: "#00acc1" },
    { key: "b2b", label: "B2B批发", color: "#3949ab" },
    { key: "b2c", label: "终端零售", color: "#d81b60" },
    { key: "sample", label: "已寄样", color: "#f4511e" }
  ];

  function getTags1() {
    var s = getSettings();
    return (s && Array.isArray(s.customTags1) && s.customTags1.length) ? s.customTags1 : DEFAULT_TAGS1;
  }
  function setTags1(list) {
    setSettings({ customTags1: list });
    scheduleV204BusinessConfigSync();
  }

  function getTags2() {
    var s = getSettings();
    return (s && Array.isArray(s.customTags2) && s.customTags2.length) ? s.customTags2 : DEFAULT_TAGS2;
  }
  function setTags2(list) {
    setSettings({ customTags2: list });
    scheduleV204BusinessConfigSync();
  }

  
  function getTag1Color(key) {
    var list = getTags1();
    for (var i = 0; i < list.length; i++) {
      if (list[i].key === key) return list[i].color || '#cfd8dc';
    }
    return '#cfd8dc';
  }

  function getTag2Color(key) {
    var list = getTags2();
    for (var i = 0; i < list.length; i++) {
      if (list[i].key === key) return list[i].color || '#78909c';
    }
    return '#78909c';
  }

  var TAGS = getTags1();

  var PLATFORM_INFO = {
    main: { key: "main", label: "主记录", short: "主记录", color: "#6D4C41" },
    wa: { key: "wa", label: "WhatsApp", short: "WA", color: "#25D366" },
    ig: { key: "ig", label: "Instagram", short: "IG", color: "#E1306C" },
    fb: { key: "fb", label: "Messenger", short: "FB", color: "#0084FF" },
    tg: { key: "tg", label: "Telegram", short: "TG", color: "#26A5E4" }
  };
  function getPlatformInfo(p) {
    return PLATFORM_INFO[p] || PLATFORM_INFO.wa;
  }
  function inferPlatform(entry, id) {
    if (entry && entry.isMainRecord) return "main";
    if (typeof id === "string" && id.indexOf("MAIN::") === 0) return "main";
    if (entry && entry.platform) return entry.platform;
    if (typeof id === "string") {
      if (id.indexOf("ig:") === 0) return "ig";
      if (id.indexOf("fb:") === 0) return "fb";
      if (id.indexOf("tg:") === 0) return "tg";
    }
    return "wa";
  }

  function loadData() {
    try { return JSON.parse(GM_getValue(STORAGE_KEY, "{}")); } catch (e) { return {}; }
  }
  function hasMeaningfulUserData(entry) {
    if (!entry) return false;
    if (entry.manualPhone && String(entry.manualPhone).trim()) return true;
    if (entry.tag && String(entry.tag).trim()) return true;
    var tag2 = Array.isArray(entry.tag2) ? entry.tag2 : (entry.tag2 ? [entry.tag2] : []);
    if (tag2.some(function (x) { return String(x || '').trim(); })) return true;
    var stages = Array.isArray(entry.stages) ? entry.stages : (entry.stages ? [entry.stages] : []);
    if (stages.some(function (x) { return String(x || '').trim(); })) return true;
    var allFieldsV126 = getAllFieldDefinitionsV126(true);
    for (var i = 0; i < allFieldsV126.length; i++) {
      var k = allFieldsV126[i].key, v = entry[k];
      if (v !== undefined && v !== null && String(v).trim()) return true;
    }
    return false;
  }

  // v123：返回本次因业务字段全部为空而实际删除的本地联系人 ID，
  // 供 saveData 在写入本地后同步删除服务端记录。
  function pruneEmptyChannelRecords(data) {
    var deletedIds = [];
    try {
      Object.keys(data || {}).forEach(function (id) {
        var e = data[id];
        if (!e) return;
        if (typeof id === 'string' && id.indexOf('MAIN::') === 0) return;
        // 完整保留 v121.7：历史 ig-thread 验证记录绝不参与空联系人删除。
        if (isProtectedIgThreadIdV1217(id)) return;
        if (!hasMeaningfulUserData(e)) {
          delete data[id];
          // 其他来源汇总记录是只读数据，不能以当前 sourceId 请求服务端删除。
          if (!isV204ServerContact(id)) {
            deletedIds.push(id);
          }
        }
      });
    } catch (e) {}
    return deletedIds;
  }

  function isProtectedIgThreadIdV1217(id) {
    return typeof id==='string' && id.indexOf('ig-thread:')===0;
  }

  // v121.7 验证阶段保护：历史 ig-thread 记录只读、不可删除、覆盖、新增、迁移或合并。
  function preserveProtectedIgThreadRecordsV1217(nextData) {
    nextData=nextData && typeof nextData==='object' ? nextData : {};
    var stored={};
    try { stored=JSON.parse(GM_getValue(STORAGE_KEY, '{}')) || {}; } catch(e) { stored={}; }
    Object.keys(nextData).forEach(function(id) {
      if (isProtectedIgThreadIdV1217(id) && !Object.prototype.hasOwnProperty.call(stored,id)) delete nextData[id];
    });
    Object.keys(stored).forEach(function(id) {
      if (isProtectedIgThreadIdV1217(id)) nextData[id]=stored[id];
    });
    return nextData;
  }

  function saveData(data) {
    preserveProtectedIgThreadRecordsV1217(data);
    var autoDeletedIds = pruneEmptyChannelRecords(data);
    // prune 之后再恢复一次，避免空的历史临时记录被清理。
    preserveProtectedIgThreadRecordsV1217(data);
    // V207.0.0：写入前与持久化基线比较，只给用户实际改变的业务字段打 dirty 标记。
    try {
      var __old=JSON.parse(String(GM_getValue(STORAGE_KEY,'{}')||'{}'))||{};
      Object.keys(data||{}).forEach(function(__k){var __r=data[__k],__o=__old[__k]||{};if(!__r||typeof __r!=='object'||v105IsDerivedMainRecord(__k,__r))return;var __d=Array.isArray(__r.__dirtyFields)?__r.__dirtyFields.slice():[];
        ['remark','status','manualName','manualPhone','f1','f2','f3','f4','f5','f6','f7','f8','tag','tag2','stages'].forEach(function(__f){if(JSON.stringify(__r[__f])!==JSON.stringify(__o[__f])&&__d.indexOf(__f)<0)__d.push(__f);});
        var __cf=__r.customFields||{},__ocf=__o.customFields||{};Object.keys(__cf).forEach(function(__f){if(JSON.stringify(__cf[__f])!==JSON.stringify(__ocf[__f])&&__d.indexOf(__f)<0)__d.push(__f);});
        if(__d.length){__r.__dirtyFields=__d;__r.__dirtyAt=Date.now();__r.__dirtyBaseVersion=Number((__r.__v204||{}).version||0);}
      });
    } catch(__e) {}
    GM_setValue(STORAGE_KEY, JSON.stringify(data));
    // v123：先完成本地删除，再将同一批真实联系人 ID 发送给当前源的服务端删除接口。
    // batch-delete 为幂等操作；管理面板原有明确删除链路保持不变。
    // V202：自动清理只作用于本地临时空记录；服务端删除必须经过预检查与人工确认。
    if (autoDeletedIds.length) console.info('[V202] 已清理本地空记录，未触发服务端删除', autoDeletedIds.length);
    try { scheduleLocalSyncAutoUpload(); } catch(e) {}
  }


  // ========================================================
  // v121：全渠道稳定身份层（非破坏性、可审计、旧库兼容）
  // Customer -> ChannelAccount -> Identity -> legacyRecordId
  // 身份层绝不删除、改名或合并 旧版本地资料库 中的旧键。
  // ========================================================
  var CRM_SCHEMA_VERSION = 121;
  var __crmBootstrappedV121 = false;

  function crmLoadV121(key, fallback) {
    try {
      var raw = GM_getValue(key, '');
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) { return fallback; }
  }
  function crmSaveV121(key, value) { GM_setValue(key, JSON.stringify(value)); }
  function crmUuidV121(prefix) {
    try {
      if (typeof crypto !== 'undefined' && crypto.randomUUID) return prefix + '_' + crypto.randomUUID().replace(/-/g, '');
    } catch (e) {}
    return prefix + '_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
  }
  function crmIdentityKeyV121(platform, type, normalizedValue) {
    return [String(platform || '').toLowerCase(), String(type || '').toLowerCase(), String(normalizedValue || '').trim().toLowerCase()].join('|');
  }
  function crmNormalizeValueV121(platform, type, value) {
    var v = String(value == null ? '' : value).trim();
    if (!v) return '';
    if (platform === 'wa' || /username/.test(type)) v = v.toLowerCase();
    return v;
  }
  function crmTypeForLegacyV121(platform, legacyId) {
    var id = String(legacyId || '');
    if (platform === 'wa') {
      if (/@c\.us$/i.test(id)) return 'wa_c_us';
      if (/@lid$/i.test(id)) return 'wa_lid';
      if (/@g\.us$/i.test(id)) return 'wa_group_jid';
    }
    if (platform === 'ig' && /^ig:/i.test(id)) return 'ig_thread_id';
    if (platform === 'fb' && /^fb:/i.test(id)) return 'fb_thread_id';
    if (platform === 'tg' && /^tg:/i.test(id)) return 'tg_peer_thread_id';
    return 'legacy_contact_id';
  }
  function crmAppendAuditV121(key, item, max) {
    var list = crmLoadV121(key, []);
    if (!Array.isArray(list)) list = [];
    list.push(item);
    if (list.length > (max || 1000)) list = list.slice(list.length - (max || 1000));
    crmSaveV121(key, list);
  }
  function crmCreateLegacyEntityV121(legacyId, record, reason) {
    if (!legacyId || isMainKey(legacyId)) return null;
    var bindings = crmLoadV121(CRM_LEGACY_BINDINGS_KEY, {});
    if (bindings[legacyId] && bindings[legacyId].accountId) return bindings[legacyId];
    var customers = crmLoadV121(CRM_CUSTOMERS_KEY, {});
    var accounts = crmLoadV121(CRM_ACCOUNTS_KEY, {});
    var identities = crmLoadV121(CRM_IDENTITIES_KEY, {});
    var index = crmLoadV121(CRM_IDENTITY_INDEX_KEY, {});
    var now = Date.now(), platform = inferPlatform(record || {}, legacyId);
    if (platform === 'main') return null;
    var customerId = crmUuidV121('cus'), accountId = crmUuidV121('acc'), identityId = crmUuidV121('idn');
    customers[customerId] = { customerId:customerId, type:'person', status:'active', createdAt:now, updatedAt:now };
    accounts[accountId] = { accountId:accountId, customerId:customerId, platform:platform, displayName:String((record && record.name) || ''), status:'active', createdAt:now, updatedAt:now };
    var type = crmTypeForLegacyV121(platform, legacyId);
    var norm = crmNormalizeValueV121(platform, type, legacyId);
    identities[identityId] = { identityId:identityId, accountId:accountId, platform:platform, type:type, value:String(legacyId), normalizedValue:norm, status:'active', confidence:'legacy', source:'旧版本地资料库.key', firstSeenAt:now, lastConfirmedAt:now };
    var ik = crmIdentityKeyV121(platform, type, norm);
    if (!index[ik]) index[ik] = accountId;
    else if (index[ik] !== accountId) crmAppendAuditV121(CRM_CONFLICTS_KEY, { conflictId:crmUuidV121('con'), kind:'legacy-index-collision', identityKey:ik, accountIds:[index[ik], accountId], legacyRecordId:legacyId, createdAt:now, status:'open' }, 1000);
    bindings[legacyId] = { legacyRecordId:legacyId, customerId:customerId, accountId:accountId, platform:platform, status:'active', createdAt:now, reason:reason || 'bootstrap' };
    crmSaveV121(CRM_CUSTOMERS_KEY, customers); crmSaveV121(CRM_ACCOUNTS_KEY, accounts);
    crmSaveV121(CRM_IDENTITIES_KEY, identities); crmSaveV121(CRM_IDENTITY_INDEX_KEY, index);
    crmSaveV121(CRM_LEGACY_BINDINGS_KEY, bindings);
    return bindings[legacyId];
  }
  function crmBootstrapLegacyV121() {
    if (__crmBootstrappedV121) return;
    __crmBootstrappedV121 = true;
    var schema = crmLoadV121(CRM_SCHEMA_KEY, {}), data = loadData() || {}, made = 0, skippedMain = 0;
    Object.keys(data).forEach(function(legacyId) {
      if (isMainKey(legacyId)) { skippedMain++; return; }
      var before = crmLoadV121(CRM_LEGACY_BINDINGS_KEY, {})[legacyId];
      if (!before && crmCreateLegacyEntityV121(legacyId, data[legacyId], 'v121-nondestructive-bootstrap')) made++;
    });
    schema = Object.assign({}, schema, { version:CRM_SCHEMA_VERSION, mode:'non-destructive-dual-read', initializedAt:schema.initializedAt || Date.now(), lastBootstrappedAt:Date.now() });
    crmSaveV121(CRM_SCHEMA_KEY, schema);
    crmAppendAuditV121(CRM_MIGRATION_LOG_KEY, { migrationId:crmUuidV121('mig'), version:CRM_SCHEMA_VERSION, action:'legacy-bootstrap', createdEntities:made, skippedMainRecords:skippedMain, sourceRecordCount:Object.keys(data).length, destructive:false, at:Date.now() }, 500);
  }
  function crmIdentitiesFromInfoV121(info) {
    var out = [], p = info && info.platform, pid = String((info && (info.platformIdentityId || info.id)) || '');
    function add(type, value, confidence, source) {
      var norm = crmNormalizeValueV121(p, type, value);
      if (!norm) return;
      var k = crmIdentityKeyV121(p, type, norm);
      if (!out.some(function(x){ return x.key === k; })) out.push({ key:k, platform:p, type:type, value:String(value), normalizedValue:norm, confidence:confidence || 'direct', source:source || 'current-header' });
    }
    if (p === 'wa') {
      if (/@c\.us$/i.test(pid)) add('wa_c_us', pid, 'direct', 'wa.header.fiber');
      else if (/@lid$/i.test(pid)) add('wa_lid', pid, 'direct', 'wa.header.fiber');
      (info.aliases || []).forEach(function(v){ if (/@lid$/i.test(v)) add('wa_lid', v, 'direct', 'wa.header.fiber.alias'); });
    } else if (p === 'ig') {
      add('ig_thread_id', pid, 'direct', 'ig.direct.url');
      if (info.username) add('ig_username', info.username, 'observed', 'ig.header.profile-link');
    } else if (p === 'fb') add('fb_thread_id', pid, 'direct', 'fb.direct.url');
    else if (p === 'tg') {
      add('tg_peer_thread_id', pid, 'direct', 'tg.header.data-peer-id');
      var m = pid.match(/^tg:([^:]+)/i); if (m) add('tg_peer_id', m[1], 'direct', 'tg.header.data-peer-id');
    }
    add('legacy_contact_id', pid, 'compatibility', 'v121.current-platform-id');
    return out;
  }
  function crmResolveCurrentInfoV121(info) {
    if (!info || !info.id || info.chatType === 'group' || ((info.platform === 'ig' || info.platform === 'fb') && !info.writable)) return info;
    // V204：禁止读取或迁移旧身份库。
    var platformId = String(info.platformIdentityId || info.id), candidates = crmIdentitiesFromInfoV121(Object.assign({}, info, { platformIdentityId:platformId }));
    var index = crmLoadV121(CRM_IDENTITY_INDEX_KEY, {}), bindings = crmLoadV121(CRM_LEGACY_BINDINGS_KEY, {});
    var accountSet = {};
    candidates.forEach(function(x){ if (index[x.key]) accountSet[index[x.key]] = true; });
    if (bindings[platformId] && bindings[platformId].accountId) accountSet[bindings[platformId].accountId] = true;
    (info.aliases || []).forEach(function(a){ if (bindings[a] && bindings[a].accountId) accountSet[bindings[a].accountId] = true; });
    var accountIds = Object.keys(accountSet), accountId = '';
    if (accountIds.length > 1) {
      crmAppendAuditV121(CRM_CONFLICTS_KEY, { conflictId:crmUuidV121('con'), kind:'current-identities-map-to-multiple-accounts', platform:info.platform, platformIdentityId:platformId, accountIds:accountIds, identityKeys:candidates.map(function(x){return x.key;}), status:'open', createdAt:Date.now() }, 1000);
      accountId = bindings[platformId] ? bindings[platformId].accountId : accountIds[0];
    } else accountId = accountIds[0] || '';
    if (!accountId) {
      var existing = (loadData() || {})[platformId];
      var b = crmCreateLegacyEntityV121(platformId, existing || { name:info.name, platform:info.platform }, 'first-direct-observation');
      accountId = b && b.accountId;
      bindings = crmLoadV121(CRM_LEGACY_BINDINGS_KEY, {});
    }
    if (!accountId) return Object.assign(info, { platformIdentityId:platformId, identityResolutionStatus:'unresolved' });
    var accounts = crmLoadV121(CRM_ACCOUNTS_KEY, {}), identities = crmLoadV121(CRM_IDENTITIES_KEY, {}), customers = crmLoadV121(CRM_CUSTOMERS_KEY, {}), now = Date.now();
    var acc = accounts[accountId];
    if (!acc) return Object.assign(info, { platformIdentityId:platformId, identityResolutionStatus:'broken-account' });
    // 冲突时不覆盖既有索引；无冲突的新身份才挂到当前账号。
    candidates.forEach(function(x) {
      if (index[x.key] && index[x.key] !== accountId) return;
      index[x.key] = accountId;
      var found = Object.keys(identities).find(function(k){ var q=identities[k]; return q && q.accountId===accountId && q.platform===x.platform && q.type===x.type && q.normalizedValue===x.normalizedValue; });
      if (found) { identities[found].lastConfirmedAt=now; identities[found].status='active'; }
      else { var iid=crmUuidV121('idn'); identities[iid]={ identityId:iid, accountId:accountId, platform:x.platform, type:x.type, value:x.value, normalizedValue:x.normalizedValue, status:'active', confidence:x.confidence, source:x.source, firstSeenAt:now, lastConfirmedAt:now }; }
    });
    acc.displayName = String(info.name || acc.displayName || ''); acc.updatedAt = now; accounts[accountId] = acc;
    if (customers[acc.customerId]) customers[acc.customerId].updatedAt = now;
    var legacyIds = Object.keys(bindings).filter(function(k){ return bindings[k] && bindings[k].accountId === accountId; });
    // v121.7：已确认 IG 的事实写入目标固定为 ig:<numericUserId>；旧 ig-thread 仅可在身份层非破坏性共存。
    var confirmedIgTarget = info.platform==='ig' && info.identityStatus==='confirmed-contact' && /^ig:\d{5,30}$/.test(platformId);
    var legacyRecordId = confirmedIgTarget ? platformId : (bindings[platformId] ? platformId : (legacyIds.find(function(k){ return !!(loadData() || {})[k]; }) || platformId));
    if (!bindings[legacyRecordId]) bindings[legacyRecordId] = { legacyRecordId:legacyRecordId, customerId:acc.customerId, accountId:accountId, platform:info.platform, status:'active', createdAt:now, reason:confirmedIgTarget?'ig-numeric-formal-target':'direct-observation-binding' };
    crmSaveV121(CRM_IDENTITY_INDEX_KEY,index); crmSaveV121(CRM_IDENTITIES_KEY,identities); crmSaveV121(CRM_ACCOUNTS_KEY,accounts); crmSaveV121(CRM_CUSTOMERS_KEY,customers); crmSaveV121(CRM_LEGACY_BINDINGS_KEY,bindings);
    crmAppendAuditV121(CRM_OBSERVATIONS_KEY, { observationId:crmUuidV121('obs'), accountId:accountId, customerId:acc.customerId, platform:info.platform, platformIdentityId:platformId, identityKeys:candidates.map(function(x){return x.key;}), legacyRecordId:legacyRecordId, source:'current-conversation-header', observedAt:now }, 300);
    return Object.assign(info, { platformIdentityId:platformId, id:legacyRecordId, legacyRecordId:legacyRecordId, accountId:accountId, customerId:acc.customerId, identityResolutionStatus:accountIds.length > 1 ? 'conflict-preserved' : 'resolved' });
  }
  function crmDiagnosticsV121() {
    return { schema:crmLoadV121(CRM_SCHEMA_KEY,{}), customers:Object.keys(crmLoadV121(CRM_CUSTOMERS_KEY,{})).length, accounts:Object.keys(crmLoadV121(CRM_ACCOUNTS_KEY,{})).length, identities:Object.keys(crmLoadV121(CRM_IDENTITIES_KEY,{})).length, bindings:Object.keys(crmLoadV121(CRM_LEGACY_BINDINGS_KEY,{})).length, conflicts:crmLoadV121(CRM_CONFLICTS_KEY,[]).length, observations:crmLoadV121(CRM_OBSERVATIONS_KEY,[]).length, legacyRecords:Object.keys(loadData() || {}).length };
  }
  window.__CRM_V121__ = { diagnostics:crmDiagnosticsV121, bootstrap:crmBootstrapLegacyV121 };

  function getSettings() {
    try { return JSON.parse(GM_getValue(SETTINGS_KEY, "{}")); } catch (e) { return {}; }
  }
  function setSettings(patch) {
    var s = Object.assign({}, getSettings(), patch);
    GM_setValue(SETTINGS_KEY, JSON.stringify(s));
    return s;
  }

  function getFieldLabel(key) {
    var s = getSettings();
    var map = s.fieldLabels || {};
    if (map[key]) return map[key];
    for (var i = 0; i < FIELDS.length; i++) {
      if (FIELDS[i].key === key) return FIELDS[i].label;
    }
    return key;
  }
  function setFieldLabels(patchMap) {
    var s = getSettings();
    var map = Object.assign({}, s.fieldLabels || {}, patchMap);
    setSettings({ fieldLabels: map });
    scheduleV204BusinessConfigSync();
  }
  // v126：动态字段定义。字段稳定键永久不变，联系人值继续保存在 contact_json 顶层 cf_* 键中。
  function getCustomFieldDefinitionsV126(includeArchived) {
    var s = getSettings();
    var list = Array.isArray(s.customFieldDefinitions) ? s.customFieldDefinitions.slice() : [];
    return list.filter(function (f) {
      if (!f || !/^cf_[A-Za-z0-9_-]{6,96}$/.test(String(f.key || ''))) return false;
      return includeArchived || (f.enabled !== false && !f.archivedAt);
    }).sort(function (a, b) {
      var d = Number(a.sortOrder || 0) - Number(b.sortOrder || 0);
      return d || String(a.key).localeCompare(String(b.key));
    });
  }
  function getAllFieldDefinitionsV126(includeArchived) {
    var fixed = FIELDS.map(function (f, i) {
      return { key:f.key, label:getFieldLabel(f.key), type:(f.key === 'remark' || f.key === 'f8') ? 'textarea' : 'text', sortOrder:i, enabled:true, archivedAt:null, dynamic:false };
    });
    var custom = getCustomFieldDefinitionsV126(includeArchived).map(function (f) {
      return { key:String(f.key), label:String(f.label || f.key), type:String(f.type || f.fieldType || 'text'), sortOrder:Number(f.sortOrder || 0), enabled:f.enabled !== false, archivedAt:f.archivedAt || null, dynamic:true };
    });
    return fixed.concat(custom);
  }
  function isBusinessFieldKeyV126(key) {
    return getAllFieldDefinitionsV126(true).some(function (f) { return f.key === key; });
  }
  function getBusinessFieldDefinitionV126(key) {
    var a=getAllFieldDefinitionsV126(true); for(var i=0;i<a.length;i++) if(a[i].key===key) return a[i]; return null;
  }
  function setCustomFieldDefinitionsV126(list) {
    setSettings({ customFieldDefinitions:Array.isArray(list) ? list : [] });
    try { rebuildColumnsV126(); } catch(e) {}
    scheduleV204BusinessConfigSync();
    try { runLinkScan(); } catch(e) {}
    try { refreshPanelIfOpen(); } catch(e) {}
    try { currentChatId=null; renderNoteBar(); } catch(e) {}
  }
  function createCustomFieldKeyV126() {
    return 'cf_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2,10);
  }
  function normalizeBusinessLabelV126(v) {
    return String(v || '').replace(/\u3000/g,' ').trim().replace(/\s+/g,' ').toLocaleLowerCase();
  }

  function getStageLabel(key) {
    var s = getSettings();
    var map = s.stageLabels || {};
    if (map[key]) return map[key];
    for (var i = 0; i < STAGES.length; i++) {
      if (STAGES[i].key === key) return STAGES[i].label;
    }
    return key;
  }
  function setStageLabels(patchMap) {
    var s = getSettings();
    var map = Object.assign({}, s.stageLabels || {}, patchMap);
    setSettings({ stageLabels: map });
    scheduleV204BusinessConfigSync();
  }


// ==================== V204 标签与动态字段配置同步 ====================
  var V204_CONFIG_SYNC_TIMER = null;
  var V204_CONFIG_SYNCING = false;
  function v204ConfigTagId(category,key) {
    return 'ui:' + String(category || 'tag') + ':' + encodeURIComponent(String(key || ''));
  }
  function v204ConfigFieldType(type) {
    type=String(type||'text').toLowerCase();
    if(type==='textarea')return 'text';
    if(type==='checkbox')return 'boolean';
    return ['text','number','date','boolean','json'].indexOf(type)>=0?type:'text';
  }
  async function pushV204BusinessConfig() {
    if(V204_CONFIG_SYNCING)return false;
    V204_CONFIG_SYNCING=true;
    try {
      var id=v204Identity(), wantedTags={}, jobs=[];
      getTags1().forEach(function(x,i){var tid=v204ConfigTagId('tag',x.key);wantedTags[tid]=1;jobs.push(localSyncRequest('POST','/api/v207/tags',{workspace_id:id.workspaceId,tag_id:tid,name:String(x.label||x.key||''),color:x.color||'#78909c',category:'tag',sort_order:i,enabled:true}));});
      getTags2().forEach(function(x,i){var tid=v204ConfigTagId('persona',x.key);wantedTags[tid]=1;jobs.push(localSyncRequest('POST','/api/v207/tags',{workspace_id:id.workspaceId,tag_id:tid,name:String(x.label||x.key||''),color:x.color||'#78909c',category:'persona',sort_order:i,enabled:true}));});
      var remoteTags=await localSyncRequest('GET','/api/v207/tags?workspace_id='+encodeURIComponent(id.workspaceId));
      if(remoteTags.ok) (remoteTags.data.items||[]).forEach(function(x){if(/^ui:(tag|persona):/.test(String(x.tag_id||''))&&!wantedTags[x.tag_id])jobs.push(localSyncRequest('DELETE','/api/v207/tags/'+encodeURIComponent(x.tag_id)+'?workspace_id='+encodeURIComponent(id.workspaceId)));});
      var wantedFields={};
      for(var fixedIndex=1;fixedIndex<=8;fixedIndex++){var fixedKey='f'+fixedIndex;wantedFields[fixedKey]=1;jobs.push(localSyncRequest('POST','/api/v207/field-definitions',{workspace_id:id.workspaceId,field_key:fixedKey,label:getFieldLabel(fixedKey),field_type:'text',sort_order:100+fixedIndex,enabled:true}));}
      wantedFields['ui.stages']=1;jobs.push(localSyncRequest('POST','/api/v207/field-definitions',{workspace_id:id.workspaceId,field_key:'ui.stages',label:'阶段',field_type:'json',sort_order:9000,enabled:true}));
      getCustomFieldDefinitionsV126(true).forEach(function(f,i){var key=String(f.key||'');if(!key)return;wantedFields[key]=1;jobs.push(localSyncRequest('POST','/api/v207/field-definitions',{workspace_id:id.workspaceId,field_key:key,label:String(f.label||key),field_type:v204ConfigFieldType(f.type||f.fieldType),sort_order:Number(f.sortOrder||i),enabled:f.enabled!==false&&!f.archivedAt}));});
      var remoteFields=await localSyncRequest('GET','/api/v207/field-definitions?workspace_id='+encodeURIComponent(id.workspaceId));
      if(remoteFields.ok) (remoteFields.data.items||[]).forEach(function(x){if(/^cf_/.test(String(x.field_key||''))&&!wantedFields[x.field_key])jobs.push(localSyncRequest('DELETE','/api/v207/field-definitions/'+encodeURIComponent(x.field_key)+'?workspace_id='+encodeURIComponent(id.workspaceId)));});
      var out=await Promise.all(jobs), failed=out.filter(function(x){return !x.ok;});
      if(failed.length)throw new Error(failed[0].error||'V204 配置同步失败');
      return true;
    } catch(e) { console.error('[V204 config push]',e); return false; }
    finally { V204_CONFIG_SYNCING=false; }
  }
  function scheduleV204BusinessConfigSync() {
    clearTimeout(V204_CONFIG_SYNC_TIMER);
    V204_CONFIG_SYNC_TIMER=setTimeout(pushV204BusinessConfig,700);
  }
  async function pullV204BusinessConfig() {
    if(V204_CONFIG_SYNCING)return false;
    V204_CONFIG_SYNCING=true;
    try {
      var id=v204Identity();
      var tr=await localSyncRequest('GET','/api/v207/tags?workspace_id='+encodeURIComponent(id.workspaceId));
      var fr=await localSyncRequest('GET','/api/v207/field-definitions?workspace_id='+encodeURIComponent(id.workspaceId));
      if(!tr.ok||!fr.ok)return false;
      var tags=tr.data.items||[], t1=[],t2=[];
      tags.forEach(function(x){var m=/^ui:(tag|persona):(.*)$/.exec(String(x.tag_id||''));if(!m||x.enabled===0)return;var item={key:decodeURIComponent(m[2]),label:x.name,color:x.color};(m[1]==='tag'?t1:t2).push({item:item,sort:Number(x.sort_order||0)});});
      function sorted(a){return a.sort(function(x,y){return x.sort-y.sort;}).map(function(x){return x.item;});}
      var fields=(fr.data.items||[]).filter(function(x){return /^cf_/.test(String(x.field_key||''));}).map(function(x){return {key:x.field_key,label:x.label,type:x.field_type,sortOrder:Number(x.sort_order||0),enabled:x.enabled!==0,archivedAt:null};});
      var patch={customFieldDefinitions:fields};if(t1.length)patch.customTags1=sorted(t1);if(t2.length)patch.customTags2=sorted(t2);
      setSettings(patch);TAGS=getTags1();rebuildColumnsV126();runLinkScan();refreshPanelIfOpen();try{currentChatId=null;renderNoteBar();}catch(e){}
      if(!tags.length&&!fields.length)setTimeout(pushV204BusinessConfig,50);
      return true;
    } catch(e) { console.error('[V204 config pull]',e); return false; }
    finally { V204_CONFIG_SYNCING=false; }
  }
  function initV204BusinessConfig() { return pullV204BusinessConfig(); }

  function upsertField(id, baseInfo, key, value) {
    if (isProtectedIgThreadIdV1217(id)) return;
    var data = loadData();
    var existed = !!data[id];
    if (!existed && !String(value || '').trim()) return;
    data[id] = Object.assign({}, data[id] || {}, baseInfo || {}, { updatedAt: Date.now() });
    data[id][key] = value;
    // v123：统一交给 saveData/prune 收集自动删除 ID 并同步服务端。
    saveData(data);
  }
  function toggleStage(id, stageKey, checked) {
    if (isProtectedIgThreadIdV1217(id)) return;
    var data = loadData();
    var existed = !!data[id];
    if (!existed && !checked) return;
    if (!data[id]) data[id] = {};
    var arr = Array.isArray(data[id].stages) ? data[id].stages.slice() : [];
    var idx = arr.indexOf(stageKey);
    if (checked) { if (idx < 0) arr.push(stageKey); }
    else { if (idx >= 0) arr.splice(idx, 1); }
    data[id].stages = arr;
    data[id].updatedAt = Date.now();
    // v123：统一交给 saveData/prune 收集自动删除 ID 并同步服务端。
    saveData(data);
  }

  function escapeHtml(str) {
    return String(str || '').replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function autoResize(t) {
    t.style.height = 'auto';
    t.style.height = Math.min(t.scrollHeight, 150) + 'px';
  }

  function simpleHash(str) {
    var hash = 0;
    for (var i = 0; i < str.length; i++) {
      hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
    }
    return Math.abs(hash).toString(36);
  }

  function isPhoneLikeText(str) {
    if (!str) return false;
    var s = String(str).trim();
    if (!s) return false;
    if (!/^[+]?[0-9][0-9\s\-()]{5,}$/.test(s)) return false;
    var digitCount = (s.match(/[0-9]/g) || []).length;
    return digitCount >= 6;
  }

  function normalizePhone(str) {
    if (!str) return '';
    var digits = String(str).replace(/[^0-9]/g, '');
    if (digits.length < 7) return '';
    if (digits.length > 11) digits = digits.slice(-11);
    return digits;
  }

  function createCustomCheckbox(checked, onChange, size) {
    size = size || 14;
    var wrap = document.createElement('span');
    wrap.setAttribute('role', 'checkbox');
    wrap.setAttribute('aria-checked', checked ? 'true' : 'false');
    wrap.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;' +
      'width:' + size + 'px;height:' + size + 'px;min-width:' + size + 'px;border-radius:3px;' +
      'cursor:pointer;border:1.5px solid #8696a0;box-sizing:border-box;flex:0 0 auto;' +
      'user-select:none;font-size:' + Math.round(size * 0.78) + 'px;line-height:1;color:#fff;' +
      'transition:background .15s,border-color .15s;';
    wrap.__checked = !!checked;
    function paint() {
      if (wrap.__checked) {
        wrap.style.background = '#00a884';
        wrap.style.borderColor = '#00a884';
        wrap.textContent = '\u2713';
      } else {
        wrap.style.background = 'transparent';
        wrap.style.borderColor = '#8696a0';
        wrap.textContent = '';
      }
    }
    paint();
    wrap.addEventListener('click', function (e) {
      e.stopPropagation();
      wrap.__checked = !wrap.__checked;
      wrap.setAttribute('aria-checked', wrap.__checked ? 'true' : 'false');
      paint();
      if (typeof onChange === 'function') onChange(wrap.__checked);
    });
    wrap.setChecked = function (v) {
      wrap.__checked = !!v;
      wrap.setAttribute('aria-checked', wrap.__checked ? 'true' : 'false');
      paint();
    };
    return wrap;
  }

  function createCustomCheckboxDoc(doc, checked, onChange, size) {
    size = size || 13;
    var wrap = doc.createElement('span');
    wrap.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;' +
      'width:' + size + 'px;height:' + size + 'px;min-width:' + size + 'px;border-radius:3px;' +
      'cursor:pointer;border:1.5px solid #8696a0;box-sizing:border-box;flex:0 0 auto;' +
      'user-select:none;font-size:' + Math.round(size * 0.78) + 'px;line-height:1;color:#fff;';
    wrap.__checked = !!checked;
    function paint() {
      if (wrap.__indeterminate) {
        wrap.style.background = '#00a884';
        wrap.style.borderColor = '#00a884';
        wrap.textContent = '−';
      } else if (wrap.__checked) {
        wrap.style.background = '#00a884';
        wrap.style.borderColor = '#00a884';
        wrap.textContent = '\u2713';
      } else {
        wrap.style.background = 'transparent';
        wrap.style.borderColor = '#8696a0';
        wrap.textContent = '';
      }
    }
    paint();
    wrap.addEventListener('click', function (e) {
      e.stopPropagation();
      wrap.__indeterminate = false;
      wrap.__checked = !wrap.__checked;
      paint();
      if (typeof onChange === 'function') onChange(wrap.__checked);
    });
    wrap.setChecked = function (v) { wrap.__indeterminate = false; wrap.__checked = !!v; paint(); };
    wrap.setIndeterminate = function (v) { wrap.__indeterminate = !!v; paint(); };
    return wrap;
  }

  function looksLikeStatusText(text) {
    if (!text) return true;
    var t = text.trim();
    if (!t) return true;
    var patterns = [
      /最后上线/, /上次在线/, /^在线$/, /typing/i, /正在输入/,
      /^[0-9]{1,2}:[0-9]{2}$/, /星期[一二三四五六日天]/, /\bonline\b/i,
      /[0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日/, /^昨天/, /^今天/, /\byesterday\b/i, /\btoday\b/i,
      /^[0-9]{1,2}\/[0-9]{1,2}\/[0-9]{2,4}$/, /点击此处查看/, /查看联系人信息/
    ];
    return patterns.some(function (p) { return p.test(t); });
  }

  function getContactName(header) {
    var candidates = [];
    header.querySelectorAll('span[title]').forEach(function (el) {
      var v = el.getAttribute('title');
      if (v) candidates.push(v.trim());
    });
    header.querySelectorAll('span[dir="auto"]').forEach(function (el) {
      var v = el.textContent;
      if (v) candidates.push(v.trim());
    });
    for (var i = 0; i < candidates.length; i++) {
      var c = candidates[i];
      if (c && !looksLikeStatusText(c)) return c;
    }
    return '';
  }

  function getFiberKey(el) {
    if (!el) return null;
    var keys = [];
    try { keys = Object.getOwnPropertyNames(el); } catch (e) { try { keys = Object.keys(el); } catch (_) {} }
    for (var i = 0; i < keys.length; i++) {
      if (keys[i].indexOf('__reactFiber$') === 0 || keys[i].indexOf('__reactInternalInstance$') === 0) return keys[i];
    }
    return null;
  }

  // V206.0.6：React Fiber 常挂在 Header 后代节点而非 Header 自身。
  // 有界广度搜索避免遍历整页，也不读取消息集合等业务对象。
  function findReactFiberInHeaderV2063(root, maxDepth, maxNodes) {
    if (!root) return null;
    var queue = [{ node: root, depth: 0 }], visited = 0;
    maxDepth = maxDepth == null ? 8 : maxDepth;
    maxNodes = maxNodes == null ? 320 : maxNodes;
    while (queue.length && visited++ < maxNodes) {
      var item = queue.shift(), node = item.node, key = getFiberKey(node);
      if (key) return { node: node, key: key, fiber: node[key], depth: item.depth, visited: visited };
      if (item.depth >= maxDepth) continue;
      var children = node && node.children ? node.children : [];
      for (var i = 0; i < children.length; i++) queue.push({ node: children[i], depth: item.depth + 1 });
    }
    return null;
  }

  // ========================================================
  // v120：WhatsApp Header Fiber 精确身份识别
  // 只读取前 3 层 Fiber 的直接 contact/chat 字段及直接 children props；
  // 绝不进入 $2、collection、models、messages、participants 或共同群组对象。
  // ========================================================
  var __waIdentitySample = { key:'', count:0, lastAt:0 };
  var __waStableIdentity = null;
  var __waIdentityGeneration = 0;

  function normalizeWaJidV120(value) {
    if (value && typeof value === 'object') value = value._serialized;
    if (typeof value !== 'string') return '';
    var m = value.trim().toLowerCase().match(/^([0-9][0-9:._-]*@(c\.us|g\.us|lid))$/);
    return m ? m[1] : '';
  }

  function readWaDirectIdV120(value) {
    if (!value) return '';
    if (typeof value === 'string') return normalizeWaJidV120(value);
    return normalizeWaJidV120(value._serialized) ||
      normalizeWaJidV120(value.__x_id && value.__x_id._serialized) ||
      normalizeWaJidV120(value.id && value.id._serialized);
  }

  function collectWaDirectPropsV120(props, out) {
    if (!props || typeof props !== 'object') return;
    function readContact(contact) {
      if (!contact || typeof contact !== 'object') return;
      var id = readWaDirectIdV120(contact.__x_id || contact.id);
      var phone = readWaDirectIdV120(contact.__x_phoneNumber || contact.phoneNumber);
      if (id) out.contactIds[id] = true;
      if (phone && /@c\.us$/.test(phone)) out.phones[phone] = true;
    }
    function readChat(chat) {
      if (!chat || typeof chat !== 'object') return;
      var id = readWaDirectIdV120(chat.__x_id || chat.id);
      var phone = readWaDirectIdV120(chat.__x_phoneNumber || chat.phoneNumber);
      if (id) out.chatIds[id] = true;
      if (phone && /@c\.us$/.test(phone)) out.phones[phone] = true;
    }
    readContact(props.contact);
    readChat(props.chat);
    var children = Array.isArray(props.children) ? props.children : [props.children];
    children.forEach(function(child) {
      if (!child || !child.props) return;
      readContact(child.props.contact);
      readChat(child.props.chat);
    });
  }

  function detectWaDirectIdentityV120(header, headerName) {
    var found = findReactFiberInHeaderV2063(header, 8, 320);
    if (!found || !found.fiber) return { status:'unconfirmed', chatType:'unknown', writable:false, reason:'header-tree-no-fiber', canonicalId:'', aliases:[] };
    var out = { contactIds:{}, chatIds:{}, phones:{} };
    var fiber = found.fiber;
    // 从命中后代向 Fiber 父链检查；仍只读直接 props，不深挖消息/参与者集合。
    for (var depth = 0; fiber && depth <= 8; depth++, fiber = fiber.return) {
      try {
        collectWaDirectPropsV120(fiber.memoizedProps, out);
        if (fiber.pendingProps !== fiber.memoizedProps) collectWaDirectPropsV120(fiber.pendingProps, out);
      } catch (e) {}
    }
    var phones = Object.keys(out.phones);
    var ids = Object.keys(out.contactIds).concat(Object.keys(out.chatIds)).filter(function(v, i, a){ return a.indexOf(v) === i; });
    var groups = ids.filter(function(x){ return /@g\.us$/.test(x); });
    var lids = ids.filter(function(x){ return /@lid$/.test(x); });
    var directCus = ids.filter(function(x){ return /@c\.us$/.test(x); });
    var result = {
      status:'unconfirmed', chatType:'unknown', writable:false, canonicalId:'', aliases:[],
      headerName:String(headerName || '').trim(), phoneCandidates:phones,
      contactIdCandidates:Object.keys(out.contactIds), chatIdCandidates:Object.keys(out.chatIds)
    };
    if (groups.length === 1 && phones.length === 0 && lids.length === 0 && directCus.length === 0) {
      result.status='confirmed-group'; result.chatType='group'; result.canonicalId=groups[0]; result.reason='direct-group-id';
    } else if (groups.length) {
      result.status='identity-conflict'; result.reason='group-contact-conflict';
    } else if (phones.length === 1) {
      result.status='confirmed-contact'; result.chatType='contact'; result.writable=true; result.canonicalId=phones[0];
      result.aliases=ids.filter(function(x){ return x !== result.canonicalId && /@lid$/.test(x); }); result.reason='direct-contact-phone';
    } else if (phones.length === 0 && directCus.length === 1 && lids.length <= 1) {
      result.status='confirmed-contact'; result.chatType='contact'; result.writable=true; result.canonicalId=directCus[0];
      result.aliases=lids.slice(); result.reason='direct-contact-cus';
    } else if (phones.length === 0 && directCus.length === 0 && lids.length === 1) {
      result.status='confirmed-lid-fallback'; result.chatType='contact'; result.writable=false; result.canonicalId=lids[0]; result.reason='lid-readonly-fallback';
    } else {
      result.reason='direct-fields-not-unique';
    }
    return result;
  }

  function extractJidViaFiber(header, headerName) {
    var raw = detectWaDirectIdentityV120(header, headerName);
    var stableCandidate = raw && raw.canonicalId &&
      (raw.status === 'confirmed-contact' || raw.status === 'confirmed-group' || raw.status === 'confirmed-lid-fallback');
    if (!stableCandidate) {
      __waIdentitySample = { key:'', count:0, lastAt:0 };
      __waStableIdentity = null;
      return raw;
    }
    var sampleKey = [raw.status, raw.chatType, raw.canonicalId, raw.aliases.join(','), raw.headerName].join('|');
    var now = Date.now();
    if (__waIdentitySample.key !== sampleKey) {
      __waIdentitySample = { key:sampleKey, count:1, lastAt:now };
      __waStableIdentity = null;
      return Object.assign({}, raw, { status:'stabilizing', writable:false, reason:'waiting-second-sample' });
    }
    if (now - __waIdentitySample.lastAt >= 180) {
      __waIdentitySample.count++;
      __waIdentitySample.lastAt = now;
    }
    if (__waIdentitySample.count < 2) return Object.assign({}, raw, { status:'stabilizing', writable:false, reason:'waiting-second-sample' });
    if (!__waStableIdentity || __waStableIdentity.__sampleKey !== sampleKey) {
      __waIdentityGeneration++;
      __waStableIdentity = Object.assign({}, raw, { __sampleKey:sampleKey, generation:__waIdentityGeneration, confirmedAt:now });
    }
    window.__WA_V120_IDENTITY__ = __waStableIdentity;
    return __waStableIdentity;
  }

  function canWriteWaIdentityV120(info, token) {
    if (!info || info.platform !== 'wa') return true;
    if (!info.writable || info.chatType !== 'contact' || info.identityStatus !== 'confirmed-contact') return false;
    var waPlatformIdV121 = String(info.platformIdentityId || info.id || '');
    if (!/@c\.us$/.test(waPlatformIdV121)) return false;
    if (!__waStableIdentity || token !== __waStableIdentity.generation || waPlatformIdV121 !== __waStableIdentity.canonicalId) return false;
    var header = document.querySelector('#main header');
    if (!header || header !== info.headerEl) return false;
    var raw = detectWaDirectIdentityV120(header, getContactName(header) || '');
    return raw.status === 'confirmed-contact' && raw.writable === true && raw.canonicalId === waPlatformIdV121 && raw.headerName === __waStableIdentity.headerName;
  }

  function mergeWaAliasRecordV120(canonicalId, aliases) {
    if (!canonicalId || !/@c\.us$/.test(canonicalId) || !Array.isArray(aliases) || !aliases.length) return;
    var data = loadData(), changed = false;
    aliases.forEach(function(aliasId) {
      var old = data[aliasId];
      if (!old || aliasId === canonicalId) return;
      var target = data[canonicalId] ? Object.assign({}, data[canonicalId]) : {};
      ['tag2','stages'].forEach(function(k) {
        var a = Array.isArray(target[k]) ? target[k] : (target[k] ? [target[k]] : []);
        var b = Array.isArray(old[k]) ? old[k] : (old[k] ? [old[k]] : []);
        target[k] = a.concat(b).filter(function(v,i,arr){ return v && arr.indexOf(v) === i; });
      });
      Object.keys(old).forEach(function(k) {
        if (k === 'mainKey' || k === 'viewMode' || k === 'memberIds' || k === 'updatedAt' || k === 'tag2' || k === 'stages') return;
        if (target[k] == null || target[k] === '') target[k] = old[k];
        else if (JSON.stringify(target[k]) !== JSON.stringify(old[k])) {
          target.waIdentityMergeBackup = target.waIdentityMergeBackup || {};
          if (!Object.prototype.hasOwnProperty.call(target.waIdentityMergeBackup, k)) target.waIdentityMergeBackup[k] = old[k];
        }
      });
      target.platform = 'wa';
      target.waJidAliases = (Array.isArray(target.waJidAliases) ? target.waJidAliases : []).concat([aliasId]).filter(function(v,i,a){ return a.indexOf(v) === i; });
      target.updatedAt = Math.max(Number(target.updatedAt || 0), Number(old.updatedAt || 0), Date.now());
      data[canonicalId] = target;
      delete data[aliasId];
      changed = true;
    });
    if (changed) {
      saveData(data);
      try { runLinkScan(); } catch (e) {}
    }
  }

  function getFallbackIdFromAvatar(header) {
    var img = header.querySelector('img');
    if (img && img.src) return 'avatar:' + simpleHash(img.src);
    return null;
  }


  // ========================================================
  // v75.1：头像稳定缓存
  // 解决 TG/IG/FB 的 blob/临时头像 URL 在从其他平台打开管理面板时无法显示的问题。
  // 当前平台能访问头像时，将头像转为 dataURL 存入 avatarData；管理面板优先显示 avatarData。
  // ========================================================
  function cacheAvatarDataUrlIfNeeded(contactId, avatarUrl, identityInfo) {
    try {
      if (!contactId || !avatarUrl) return;
      if (identityInfo && identityInfo.platform === 'ig' && !canWriteIgIdentityV1212(identityInfo, identityInfo.igSessionToken)) return;
      if (avatarUrl.indexOf('data:image/') === 0) return;

      // v75.2：不仅缓存 TG blob，也缓存 IG / Instagram CDN / fbcdn 头像，解决从 WA 打开面板时 IG 头像不显示。
      var shouldCache =
        avatarUrl.indexOf('blob:') === 0 ||
        /instagram|cdninstagram|fbcdn/i.test(avatarUrl);

      if (!shouldCache) return;

      var data = loadData();
      var rec = data[contactId] || {};
      // v75.3：只有当头像 URL 没变时才跳过缓存；URL 变化则允许覆盖旧 avatarData，修复 IG 头像错乱固化问题。
      if (
        rec.avatarData &&
        rec.avatarData.indexOf('data:image/') === 0 &&
        rec.avatar === avatarUrl
      ) {
        return;
      }

      function saveAvatarData(dataUrl) {
        try {
          if (!dataUrl || dataUrl.indexOf('data:image/') !== 0) return;
          if (identityInfo && identityInfo.platform === 'ig' && !canWriteIgIdentityV1212(identityInfo, identityInfo.igSessionToken)) return;
          var data2 = loadData();
          if (!data2[contactId]) data2[contactId] = {};
          data2[contactId].avatar = avatarUrl;
          data2[contactId].avatarData = dataUrl;
          data2[contactId].updatedAt = Date.now();
          saveData(data2);
          try { refreshPanelIfOpen(); } catch (e) { }
        } catch (e) { }
      }

      function blobToDataUrl(blob) {
        try {
          var reader = new FileReader();
          reader.onload = function () { saveAvatarData(reader.result); };
          reader.readAsDataURL(blob);
        } catch (e) { }
      }

      // 1. blob URL：只能在当前来源页面 fetch，适合 Telegram。
      if (avatarUrl.indexOf('blob:') === 0) {
        fetch(avatarUrl)
          .then(function (res) { return res.blob(); })
          .then(blobToDataUrl)
          .catch(function () { });
        return;
      }

      // 2. 普通 https 图片：优先使用 Tampermonkey GM_xmlhttpRequest，绕过页面 CORS 限制，适合 IG/fbcdn。
      if (typeof GM_xmlhttpRequest === 'function') {
        var requestAvatar1062 = function(anonymous1062, retry1062) {
          GM_xmlhttpRequest({
            method: 'GET', url: avatarUrl, responseType: 'blob', anonymous: anonymous1062,
            timeout: 15000,
            headers: { 'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8' },
            onload: function (res) {
              try {
                if (res && res.status >= 200 && res.status < 400 && res.response && res.response.size) blobToDataUrl(res.response);
                else if (retry1062) retry1062();
              } catch (e) { if (retry1062) retry1062(); }
            },
            onerror: function () { if (retry1062) retry1062(); },
            ontimeout: function () { if (retry1062) retry1062(); }
          });
        };
        requestAvatar1062(true, function() { requestAvatar1062(false, null); });
        return;
      }

      // 3. 兜底 fetch。
      fetch(avatarUrl)
        .then(function (res) { return res.blob(); })
        .then(blobToDataUrl)
        .catch(function () { });

    } catch (e) { }
  }

  // ========================================================
  // v106.2：管理面板跨平台头像回退加载
  // 直接 URL 加载失败后，通过用户脚本跨域请求转为 dataURL；仅做运行时缓存，
  // 不把他源派生状态写回本地事实库，保持 v105 的同步边界不变。
  // ========================================================
  var AVATAR_DATA_CACHE_V1062 = Object.create(null);
  var AVATAR_PENDING_V1062 = Object.create(null);

  function v1062IsImageBlob(blob) {
    if (!blob || !blob.size) return false;
    var type = String(blob.type || '').toLowerCase();
    return !type || type.indexOf('image/') === 0 || type === 'application/octet-stream';
  }

  function v1062BlobToDataUrl(blob, done, fail) {
    try {
      if (!v1062IsImageBlob(blob)) { fail(); return; }
      var reader = new FileReader();
      reader.onload = function() {
        var value = String(reader.result || '');
        if (value.indexOf('data:image/') === 0 || value.indexOf('data:application/octet-stream') === 0) done(value);
        else fail();
      };
      reader.onerror = fail;
      reader.readAsDataURL(blob);
    } catch (e) { fail(); }
  }

  function v1062FetchAvatarDataUrl(url, callback) {
    url = String(url || '');
    if (!url || url.indexOf('blob:') === 0) { callback(''); return; }
    if (AVATAR_DATA_CACHE_V1062[url]) { callback(AVATAR_DATA_CACHE_V1062[url]); return; }
    if (AVATAR_PENDING_V1062[url]) { AVATAR_PENDING_V1062[url].push(callback); return; }
    AVATAR_PENDING_V1062[url] = [callback];
    function finish(value) {
      if (value) AVATAR_DATA_CACHE_V1062[url] = value;
      var list = AVATAR_PENDING_V1062[url] || [];
      delete AVATAR_PENDING_V1062[url];
      list.forEach(function(fn) { try { fn(value || ''); } catch (e) {} });
    }
    function request(anonymous, next) {
      try {
        if (typeof GM_xmlhttpRequest !== 'function') { next(); return; }
        GM_xmlhttpRequest({
          method:'GET', url:url, responseType:'blob', anonymous:anonymous,
          timeout:15000, headers:{'Accept':'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'},
          onload:function(res) {
            if (!res || res.status < 200 || res.status >= 400 || !res.response) { next(); return; }
            v1062BlobToDataUrl(res.response, finish, next);
          },
          onerror:next, ontimeout:next
        });
      } catch (e) { next(); }
    }
    // CDN 通常匿名请求更稳定；失败后再尝试携带当前环境凭证。
    request(true, function() { request(false, function() { finish(''); }); });
  }

  function v1062BindAvatarImage(img, row, preferredSrc) {
    if (!img) return;
    row = row || {};
    var stable = row.avatarData || row.__avatarData || '';
    var remote = row.avatar || row.__avatar || '';
    var first = preferredSrc || stable || remote;
    var fallbackUrl = remote && remote.indexOf('data:') !== 0 ? remote : (first && first.indexOf('data:') !== 0 ? first : '');
    var tried = false;
    img.setAttribute('referrerpolicy', 'no-referrer');
    img.alt = '头像';
    img.onerror = function() {
      if (tried || !fallbackUrl) { img.onerror = null; img.alt = '👤'; return; }
      tried = true;
      v1062FetchAvatarDataUrl(fallbackUrl, function(dataUrl) {
        if (dataUrl) { img.onerror = null; img.src = dataUrl; }
        else { img.onerror = null; img.alt = '👤'; }
      });
    };
    if (first) img.src = first;
  }

  function getWaHeaderInfo() {
    var header = document.querySelector('#main header');
    if (!header) return null;
    var name = getContactName(header) || '';
    if (!name) return null;
    var identity = extractJidViaFiber(header, name) || {status:'unconfirmed',writable:false,reason:'identity-unavailable',canonicalId:'',aliases:[]};
    // V206.0.6：身份状态只控制写权限，不再控制 UI 是否创建。
    // 临时 ID 仅存在于本页只读栏，不进入 CRM/同步写入链路。
    var readonlyIdentity = identity.status === 'stabilizing' || identity.status === 'unconfirmed' || identity.status === 'identity-conflict' || !identity.canonicalId;
    var avImg = header.querySelector('img[src*="whatsapp.net"]') || header.querySelector('img');
    var avatar = (avImg && avImg.src) ? avImg.src : '';
    var info = {
      id:(identity.canonicalId || ('wa-pending:' + simpleHash(location.href + '|' + name))), name:name, avatar:avatar, platform:'wa', headerEl:header,
      chatType:identity.chatType || 'unknown', writable:(!readonlyIdentity && identity.writable === true), identityStatus:identity.status,
      aliases:identity.aliases || [], waWriteToken:identity.generation, identityReason:identity.reason
    };
    // v121：禁止 v120 的 alias 改键/删除；身份别名交给 CRM Identity 层非破坏性登记。
    return info;
  }

  // ========================================================
  // FB / IG / TG 识别逻辑：恢复 58.1 稳定 DOM 查找函数，并接入 v75.1 avatar/avatarData
  // ========================================================

  var IG_USERNAME_LINK_RE = /^\/[A-Za-z0-9_.]{1,30}\/$/;
  var IG_EXCLUDED_PATHS = ['/reels/', '/explore/', '/accounts/', '/direct/'];
  var IG_SELF_LABELS = ['主页', 'Profile', '个人主页', 'Home'];
  var __igIdentityGateV1212 = { route:'', candidate:'', count:0, firstAt:0, token:0, accepted:null };
  // v121.3：当前 Direct 线程参与者身份缓存。键同时包含 threadId 与 Header username，禁止跨线程复用。
  var __igThreadIdentityCacheV1213 = Object.create(null);
  var __igThreadIdentityRequestSeqV1213 = 0;

  function igIdentityCacheKeyV1213(threadId, username) {
    return String(threadId || '') + '|' + String(username || '').toLowerCase();
  }


  // v121.7：冲突立即撤销当前页面已接受的 IG 身份；旧 UI 中保存的令牌同步失效。
  function igRevokeAcceptedIdentityV1217(threadId, username, reason) {
    var g=__igIdentityGateV1212, a=g.accepted;
    if (a && String(a.threadId)===String(threadId) && String(a.username||'').toLowerCase()===String(username||'').toLowerCase()) {
      g.token++;
      g.accepted=null;
    }
    if (reason) __igPassiveDiagV1216.lastError=String(reason);
  }

  function igNormalizeNumericIdV1213(value, threadId) {
    if (typeof value !== 'string' && typeof value !== 'number') return '';
    var text=String(value);
    return /^\d{5,30}$/.test(text) && text !== String(threadId || '') ? text : '';
  }

  // 只接受同一对象中 username 精确匹配的参与者；接口响应来自当前 threadId，仍不做模糊姓名匹配。
  function igFindParticipantInPayloadV1213(payload, username, threadId) {
    var wanted=String(username || '').toLowerCase(), found=Object.create(null), seen=new Set(), scanned=0;
    function walk(value, depth) {
      if (!value || typeof value !== 'object' || depth > 16 || scanned++ > 40000 || seen.has(value)) return;
      seen.add(value);
      try {
        var u=String(value.username || value.user_name || '').toLowerCase();
        if (u && u === wanted) {
          ['pk','pk_id','user_id','userId','id','instagram_user_id'].forEach(function(k) {
            var id=igNormalizeNumericIdV1213(value[k],threadId); if (id) found[id]=true;
          });
        }
        Object.keys(value).slice(0,250).forEach(function(k) {
          var child; try { child=value[k]; } catch(e) { return; }
          if (child && typeof child === 'object') walk(child,depth+1);
        });
      } catch(e) {}
    }
    walk(payload,0);
    var ids=Object.keys(found);
    return ids.length === 1 ? ids[0] : '';
  }

  // v121.6：零主动请求身份解析。通过 unsafeWindow 直接在页面上下文安装，不再依赖会被 CSP 拦截的内联 script。
  var __igPassiveDiagV1216 = {
    attempted:false, installed:false, handshake:false, installMethod:'',
    messages:0, nativeResponses:0, jsonPayloads:0, parseFailures:0, candidateBatches:0,
    lastUrl:'', lastSource:'', lastAt:0, lastError:'', nonce:''
  };

  function igCurrentHeaderUsernameV1216() {
    try {
      var link=findIgUsernameLink();
      return link ? String(link.getAttribute('href')||'').replace(/^\/+|\/+$/g,'').toLowerCase() : '';
    } catch(e) { return ''; }
  }

  function igWakeIfStillCurrentV1216(threadId, username) {
    if (igThreadIdV1212()===String(threadId||'') && igCurrentHeaderUsernameV1216()===String(username||'').toLowerCase()) {
      setTimeout(function(){ try { tick(); renderNoteBar(); } catch(e) {} },0);
    }
  }

  function igAcceptPassiveMessageV1216(detail) {
    try {
      if (!detail || typeof detail!=='object') return;
      if (detail.kind==='ready') {
        __igPassiveDiagV1216.installed=true;
        __igPassiveDiagV1216.handshake=true;
        __igPassiveDiagV1216.installMethod=String(detail.method||__igPassiveDiagV1216.installMethod||'unsafeWindow');
        __igPassiveDiagV1216.lastAt=Date.now();
        return;
      }
      if (detail.kind!=='response') return;
      __igPassiveDiagV1216.messages++;
      __igPassiveDiagV1216.nativeResponses++;
      __igPassiveDiagV1216.lastAt=Date.now();
      __igPassiveDiagV1216.lastUrl=String(detail.url||'').slice(0,500);
      __igPassiveDiagV1216.lastSource=String(detail.source||'page_response');
      if (!detail.parsed) { __igPassiveDiagV1216.parseFailures++; return; }
      __igPassiveDiagV1216.jsonPayloads++;
      if (!Array.isArray(detail.users)) return;
      var threadId=igThreadIdV1212(), username=igCurrentHeaderUsernameV1216();
      if (!threadId || !username) return;
      var ids=Object.create(null);
      detail.users.forEach(function(row) {
        if (!row || String(row.username||'').toLowerCase()!==username) return;
        var id=igNormalizeNumericIdV1213(row.id,threadId);
        if (id) ids[id]=true;
      });
      var values=Object.keys(ids), key=igIdentityCacheKeyV1213(threadId,username);
      if (!values.length) return;
      __igPassiveDiagV1216.candidateBatches++;
      if (values.length!==1) {
        var multiReason='同一页面响应中出现多个 username 匹配 ID';
        __igThreadIdentityCacheV1213[key]={status:'conflict',source:__igPassiveDiagV1216.lastSource,id:'',at:Date.now(),error:multiReason};
        igRevokeAcceptedIdentityV1217(threadId,username,multiReason);
        igWakeIfStillCurrentV1216(threadId,username);
        return;
      }
      var old=__igThreadIdentityCacheV1213[key];
      // conflict 在当前页面生命周期内保持粘滞，禁止被后续单批响应静默恢复。
      if (old && old.status==='conflict') {
        igRevokeAcceptedIdentityV1217(threadId,username,old.error || 'IG 身份缓存处于冲突状态');
      } else if (old && old.status==='ok' && old.id && old.id!==values[0]) {
        var conflictReason='被动响应 ID 与已缓存 ID 冲突';
        __igThreadIdentityCacheV1213[key]={status:'conflict',source:__igPassiveDiagV1216.lastSource,id:'',at:Date.now(),error:conflictReason};
        igRevokeAcceptedIdentityV1217(threadId,username,conflictReason);
      } else {
        __igThreadIdentityCacheV1213[key]={status:'ok',source:__igPassiveDiagV1216.lastSource,id:values[0],at:Date.now(),error:''};
      }
      igWakeIfStillCurrentV1216(threadId,username);
    } catch(e) { __igPassiveDiagV1216.lastError=String(e && e.message || e); }
  }

  function igPageObserverInstallerV1216(pageWin, secret, sink) {
    if (!pageWin || !secret || typeof sink!=='function') throw new Error('页面窗口或消息通道不可用');
    if (pageWin.__igPassiveObserverInstalledV1216) {
      sink({kind:'ready',method:'unsafeWindow-existing'});
      return;
    }
    pageWin.__igPassiveObserverInstalledV1216=true;
    function notify(detail) { try { sink(detail); } catch(e) {} }
    function extract(payload) {
      var found=Object.create(null), seen=new Set(), scanned=0;
      function walk(v,depth) {
        if (!v || typeof v!=='object' || depth>16 || scanned++>45000 || seen.has(v)) return;
        seen.add(v);
        try {
          var username=String(v.username||v.user_name||'').toLowerCase();
          if (/^[a-z0-9._]{1,30}$/.test(username)) {
            var ids=Object.create(null);
            ['pk','pk_id','user_id','userId','id','instagram_user_id'].forEach(function(k){
              var x=v[k];
              if ((typeof x==='string'||typeof x==='number') && /^\d{5,30}$/.test(String(x))) ids[String(x)]=true;
            });
            var values=Object.keys(ids);
            if (values.length===1) found[username+'|'+values[0]]={username:username,id:values[0]};
          }
          Object.keys(v).slice(0,250).forEach(function(k){
            if (k==='return'||k==='child'||k==='sibling'||k==='_owner') return;
            var x; try{x=v[k];}catch(e){return;}
            if (x && typeof x==='object') walk(x,depth+1);
          });
        } catch(e) {}
      }
      walk(payload,0);
      return Object.keys(found).slice(0,1000).map(function(k){return found[k];});
    }
    function eligible(url,contentType) {
      try {
        var u=new pageWin.URL(String(url||''),pageWin.location.href);
        if (u.origin!==pageWin.location.origin) return false;
        if (contentType && /json|javascript|text\/plain/i.test(contentType)) return true;
        return /graphql|api|ajax|direct|query/i.test(u.pathname+u.search);
      } catch(e) { return false; }
    }
    function consumeText(text,url,source) {
      if (!text || text.length>12000000) { notify({kind:'response',url:String(url||''),source:source,parsed:false,users:[]}); return; }
      try {
        var payload=JSON.parse(text);
        notify({kind:'response',url:String(url||''),source:source,parsed:true,users:extract(payload)});
      } catch(e) { notify({kind:'response',url:String(url||''),source:source,parsed:false,users:[]}); }
    }
    var originalFetch=pageWin.fetch;
    if (typeof originalFetch==='function') {
      var wrappedFetch=function(){
        var promise=originalFetch.apply(this,arguments);
        promise.then(function(resp){
          try {
            var ct=resp.headers && resp.headers.get('content-type') || '';
            if (!resp.ok || !eligible(resp.url,ct)) return;
            resp.clone().text().then(function(t){ consumeText(t,resp.url,'page_fetch'); }).catch(function(){
              notify({kind:'response',url:String(resp.url||''),source:'page_fetch',parsed:false,users:[]});
            });
          } catch(e) {}
        }).catch(function(){});
        return promise;
      };
      try { pageWin.fetch=wrappedFetch; } catch(e) { throw new Error('无法挂接页面 fetch: '+String(e&&e.message||e)); }
    }
    var XHR=pageWin.XMLHttpRequest;
    if (XHR && XHR.prototype) {
      var open=XHR.prototype.open, send=XHR.prototype.send;
      XHR.prototype.open=function(method,url){ try{this.__ig1216Url=url;}catch(e){} return open.apply(this,arguments); };
      XHR.prototype.send=function(){
        try { this.addEventListener('load',function(){
          try {
            var url=this.responseURL||this.__ig1216Url||'', ct=this.getResponseHeader('content-type')||'';
            if (this.status<200 || this.status>=300 || !eligible(url,ct)) return;
            var t=typeof this.responseText==='string' ? this.responseText : '';
            consumeText(t,url,'page_xhr');
          } catch(e) {}
        }); } catch(e) {}
        return send.apply(this,arguments);
      };
    }
    notify({kind:'ready',method:'unsafeWindow',secret:secret});
  }

  function installIgPassiveObserverV1216() {
    if (__igPassiveDiagV1216.attempted || location.hostname.indexOf('instagram.com')<0) return;
    __igPassiveDiagV1216.attempted=true;
    var nonce='ig1216-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
    __igPassiveDiagV1216.nonce=nonce;
    try {
      if (typeof unsafeWindow==='undefined' || !unsafeWindow) throw new Error('unsafeWindow 不可用；请确认脚本已授予 @grant unsafeWindow');
      __igPassiveDiagV1216.installMethod='unsafeWindow-pending';
      igPageObserverInstallerV1216(unsafeWindow,nonce,function(detail){ igAcceptPassiveMessageV1216(detail); });
      setTimeout(function(){
        if (!__igPassiveDiagV1216.handshake && !__igPassiveDiagV1216.lastError) {
          __igPassiveDiagV1216.lastError='页面监听未完成握手';
        }
      },1500);
    } catch(e) {
      __igPassiveDiagV1216.installed=false;
      __igPassiveDiagV1216.handshake=false;
      __igPassiveDiagV1216.lastError='页面上下文安装失败: '+String(e && e.message || e);
    }
  }

  // 保留旧函数名以减少调用面；v121.6 中它只标记等待，不产生网络请求。
  function igRequestThreadIdentityV1213(threadId, username) {
    if (!threadId || !username) return;
    var key=igIdentityCacheKeyV1213(threadId,username);
    if (!__igThreadIdentityCacheV1213[key]) {
      __igThreadIdentityCacheV1213[key]={status:'observing',source:'passive_page_response',id:'',at:Date.now(),error:''};
    }
  }

  function igCachedThreadIdentityV1213(threadId, username) {
    var key=igIdentityCacheKeyV1213(threadId,username), item=__igThreadIdentityCacheV1213[key];
    if (item && item.status==='ok' && item.id) return item.id;
    igRequestThreadIdentityV1213(threadId,username);
    return '';
  }

  function igVisibleV1212(el) {
    if (!el || !el.isConnected || el.getAttribute('aria-hidden') === 'true') return false;
    var r = el.getBoundingClientRect();
    if (!r || r.width <= 0 || r.height <= 0 || r.bottom <= 0 || r.right <= 0) return false;
    var st = window.getComputedStyle ? getComputedStyle(el) : null;
    return !st || (st.display !== 'none' && st.visibility !== 'hidden' && Number(st.opacity || 1) !== 0);
  }

  function igThreadIdV1212() {
    var m = location.pathname.match(/\/direct\/t\/([^\/?#]+)\/?/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  // 只选取右侧活动聊天 Header 的用户名链接；绝不从左侧会话列表或隐藏旧节点取值。
  function findIgUsernameLink() {
    var list = [], vw = Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0);
    document.querySelectorAll('a[href]').forEach(function(a) {
      var href = a.getAttribute('href') || '';
      if (!IG_USERNAME_LINK_RE.test(href) || IG_EXCLUDED_PATHS.indexOf(href) >= 0 || !igVisibleV1212(a)) return;
      var r = a.getBoundingClientRect(), text = (a.textContent || '').trim();
      if (IG_SELF_LABELS.indexOf(text) >= 0 || r.top < 0 || r.top > 220) return;
      // 桌面端必须位于聊天区域；窄屏允许全宽，但仍依赖 Header 尺寸和 Fiber 一致性复核。
      if (vw >= 700 && r.left < Math.min(300, vw * 0.24)) return;
      var title = a.querySelector('span[title]');
      var score = (title ? 1000 : 0) + r.left - r.top * 0.25;
      list.push({ el:a, score:score });
    });
    list.sort(function(a,b){ return b.score-a.score; });
    return list.length ? list[0].el : null;
  }

  function findIgHeaderContainer(usernameLink) {
    if (!usernameLink) return null;
    var node=usernameLink, best=null, hops=0;
    while (node && hops++ < 14) {
      var r=node.getBoundingClientRect();
      if (igVisibleV1212(node) && r.top < 220 && r.width > 260 && r.height >= 36 && r.height <= 180) best=node;
      if (r.height > 180) break;
      node=node.parentElement;
    }
    return best || usernameLink.closest('header') || null;
  }

  function igReactRootsV1212(el) {
    var out=[], rootSeen=new Set();
    function push(value) { if (value && !rootSeen.has(value)) { rootSeen.add(value); out.push(value); } }
    function add(node) {
      if (!node) return;
      Object.getOwnPropertyNames(node).forEach(function(k) {
        if (k.indexOf('__reactFiber$')===0 || k.indexOf('__reactProps$')===0 || k.indexOf('__reactInternalInstance$')===0) {
          try {
            var value=node[k]; push(value);
            // v121.3：沿当前 Header 的 Fiber return 链读取父组件数据，不横向进入 sibling/child。
            if (k.indexOf('__reactFiber$')===0 || k.indexOf('__reactInternalInstance$')===0) {
              var fiber=value, hops=0;
              while (fiber && hops++ < 35) { push(fiber.memoizedProps); push(fiber.pendingProps); push(fiber.memoizedState); fiber=fiber.return; }
            }
          } catch(e) {}
        }
      });
    }
    var node=el, up=0;
    while (node && up++ < 10) { add(node); node=node.parentElement; }
    if (el && el.querySelectorAll) Array.prototype.slice.call(el.querySelectorAll('*'),0,120).forEach(add);
    return out;
  }

  // Fiber 仅作为辅助来源；数字 ID 仍要求同一对象内 username 与当前 Header 完全一致。
  function extractIgNumericUserIdV1212(headerEl, username, threadId) {
    var wanted=String(username||'').toLowerCase(), roots=igReactRootsV1212(headerEl), seen=new Set(), scanned=0, found={};
    function walk(v,depth) {
      if (!v || typeof v!=='object' || depth>10 || scanned++>9000 || seen.has(v)) return;
      seen.add(v);
      try {
        var u=String(v.username || v.user_name || '').toLowerCase();
        if (u && u===wanted) {
          ['pk','pk_id','user_id','userId','id','instagram_user_id'].forEach(function(k){
            var x=v[k]; if ((typeof x==='number' || typeof x==='string') && /^\d{5,30}$/.test(String(x)) && String(x)!==String(threadId)) found[String(x)]=true;
          });
        }
        Object.keys(v).slice(0,100).forEach(function(k){
          if (k==='return' || k==='child' || k==='sibling' || k==='_owner') return;
          var x; try{x=v[k];}catch(e){return;}
          if (x && typeof x==='object') walk(x,depth+1);
        });
      } catch(e) {}
    }
    roots.forEach(function(r){ walk(r,0); });
    var ids=Object.keys(found);
    return ids.length===1 ? ids[0] : '';
  }

  function findIgAvatarForLink(usernameLink, headerEl) {
    try {
      if (!usernameLink || !headerEl) return '';
      var lr=usernameLink.getBoundingClientRect(), list=[];
      headerEl.querySelectorAll('img').forEach(function(img) {
        if (!igVisibleV1212(img) || !img.src || /emoji|sprite|favicon|blank/i.test(img.src)) return;
        var r=img.getBoundingClientRect();
        if (r.width<24 || r.height<24 || r.width>120 || r.height>120) return;
        var dx=Math.abs((r.left+r.width/2)-(lr.left+lr.width/2));
        var dy=Math.abs((r.top+r.height/2)-(lr.top+lr.height/2));
        if (dy<=90 && dx<=320) list.push({src:img.src,score:dx+dy*2+((r.left>lr.left)?80:0)});
      });
      list.sort(function(a,b){return a.score-b.score;});
      return list.length ? list[0].src : '';
    } catch(e) { return ''; }
  }

  function igGateCandidateV1212(raw) {
    var g=__igIdentityGateV1212, now=Date.now(), route=String(raw.threadId||''), key=route+'|'+raw.username+'|'+(raw.numericUserId||'');
    if (g.route!==route || g.candidate!==key) {
      g.route=route; g.candidate=key; g.count=1; g.firstAt=now; g.token++; g.accepted=null;
      return null;
    }
    if (now-g.firstAt < 250) return null;
    g.count++;
    if (g.count<2) return null;
    raw.igSessionToken=g.token;
    raw.identityStatus=raw.numericUserId ? 'confirmed-contact' : 'thread-only';
    raw.writable=!!raw.numericUserId;
    raw.provisional=!raw.numericUserId;
    raw.id=raw.numericUserId ? ('ig:'+raw.numericUserId) : ('ig-thread:'+raw.threadId);
    raw.platformIdentityId=raw.id;
    g.accepted={ token:g.token, threadId:raw.threadId, username:raw.username, id:raw.id, headerEl:raw.headerEl };
    return raw;
  }

  // v121.7：每次真正写入前重新读取当前路由、Header 与被动缓存，不信任旧快照。
  function canWriteIgIdentityV1212(info, token) {
    try {
      var a=__igIdentityGateV1212.accepted;
      if (!(info && info.platform==='ig' && info.writable && info.identityStatus==='confirmed-contact')) return false;
      if (info.identityResolutionStatus && info.identityResolutionStatus!=='resolved') return false;
      var currentThread=igThreadIdV1212();
      var currentUsername=igCurrentHeaderUsernameV1216();
      var wantedUsername=String(info.username||'').toLowerCase();
      var numericId=igNormalizeNumericIdV1213(info.numericUserId,currentThread);
      var expectedId=numericId ? ('ig:'+numericId) : '';
      var item=__igThreadIdentityCacheV1213[igIdentityCacheKeyV1213(currentThread,currentUsername)];
      return !!(a && a.token===token && token===info.igSessionToken &&
        currentThread && currentThread===String(info.threadId||'') &&
        currentUsername && currentUsername===wantedUsername &&
        item && item.status==='ok' && item.id===numericId &&
        expectedId && info.id===expectedId && info.platformIdentityId===expectedId &&
        a.id===expectedId && a.threadId===currentThread && String(a.username||'').toLowerCase()===currentUsername &&
        a.headerEl===info.headerEl && igVisibleV1212(info.headerEl));
    } catch(e) { return false; }
  }

  function getIgHeaderInfo() {
    if (location.hostname.indexOf('instagram.com')<0 || location.pathname.indexOf('/direct/')!==0) return null;
    var threadId=igThreadIdV1212(); if (!threadId) return null;
    var link=findIgUsernameLink(); if (!link) return null;
    var username=(link.getAttribute('href')||'').replace(/\//g,'').trim(); if (!username) return null;
    var headerEl=findIgHeaderContainer(link); if (!headerEl || !igVisibleV1212(headerEl)) return null;
    var title=link.querySelector('span[title]');
    var name=(title && title.getAttribute('title')) || (link.textContent||'').trim() || username;
    // v121.7：Fiber 只作为诊断候选；正式主键与写权限只由被动缓存 status:ok 授予。
    var passiveNumericId=igCachedThreadIdentityV1213(threadId,username);
    var fiberCandidateId=extractIgNumericUserIdV1212(headerEl,username,threadId);
    return igGateCandidateV1212({ name:name, username:username, avatar:findIgAvatarForLink(link,headerEl), platform:'ig', headerEl:headerEl, threadId:threadId, numericUserId:passiveNumericId, fiberCandidateId:fiberCandidateId });
  }

  // ========================================================
  // v121.8：FB/Messenger 当前会话上下文复验
  // threadId、姓名和头像必须来自同一中央聊天上下文；禁止按姓名全页反查。
  // SPA 切换期间连续采样未稳定时保持只读，防止上一会话资料写入下一会话。
  // ========================================================
  var __fbIdentityGateV1218 = { route:'', signature:'', hits:0, firstAt:0, token:0, accepted:null };

  function fbThreadIdV1218() {
    var m=String(location.pathname||'').match(/\/t\/([^\/?#]+)\/?/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function fbVisibleV1218(el) {
    if (!el || !el.isConnected || el.closest('#wa-remark-bar')) return false;
    var r=el.getBoundingClientRect();
    if (!r || r.width<1 || r.height<1 || r.bottom<=0 || r.right<=0 || r.top>=window.innerHeight || r.left>=window.innerWidth) return false;
    var cs=window.getComputedStyle(el);
    return cs.display!=='none' && cs.visibility!=='hidden' && Number(cs.opacity||1)>0;
  }

  function findFbMessagePane() {
    var selectors=['div[role="main"]','div[aria-label*="Conversation"]','div[aria-label*="conversation"]','div[aria-label*="对话"]','div[aria-label*="聊天"]'];
    var list=[];
    try { document.querySelectorAll(selectors.join(',')).forEach(function(el){ if (list.indexOf(el)<0) list.push(el); }); } catch(e) {}
    var best=null,bestScore=-Infinity;
    list.forEach(function(el){
      if (!fbVisibleV1218(el)) return;
      var r=el.getBoundingClientRect();
      if (r.width<280 || r.height<220 || r.left>window.innerWidth*0.88) return;
      var score=Math.min(r.width*r.height/1000,1800)-Math.abs((r.left+r.width/2)-window.innerWidth/2)/2;
      if (el.getAttribute('role')==='main') score+=1400;
      var aria=String(el.getAttribute('aria-label')||'');
      if (/conversation|对话|聊天/i.test(aria)) score+=1000;
      if (r.left<120 && r.width<window.innerWidth*.45) score-=1800;
      if (score>bestScore) { bestScore=score; best=el; }
    });
    return best;
  }

  function isFbBadHeaderText(t) {
    t=String(t||'').replace(/\s+/g,' ').trim();
    if (!t || t.length>80) return true;
    return /^(Messenger|Facebook|Chats?|聊天|收件箱|Inbox|搜索|Search|语音通话|视频通话|通话详情|聊天室详情|Conversation information|Chat information|Active now|在线|离线|Offline|端到端加密|End-to-end encrypted|详情|Info|个人资料|Profile|成员|Members?|昵称|Nicknames?|正在加载|Loading(?:\.\.\.)?)$/i.test(t);
  }

  function fbProfileHrefV1218(el) {
    if (!el) return '';
    var a=el.closest && el.closest('a[href]');
    if (!a && el.querySelector) a=el.querySelector('a[href]');
    if (!a) return '';
    var href=String(a.getAttribute('href')||'');
    if (!href || /\/messages(?:\/|$)|\/help(?:\/|$)|\/settings(?:\/|$)/i.test(href)) return '';
    return href;
  }

  function findFbHeaderContextV1218(pane) {
    if (!pane) return null;
    var pr=pane.getBoundingClientRect(), nodes=[];
    document.querySelectorAll('h1,h2,h3,div[role="heading"],span[dir="auto"][title],a[href] span[dir="auto"]').forEach(function(el){
      if (!fbVisibleV1218(el)) return;
      var r=el.getBoundingClientRect();
      if (r.top<0 || r.top>190 || r.left<pr.left-25 || r.right>pr.right+25) return;
      var text=String(el.getAttribute('title')||el.textContent||'').replace(/\s+/g,' ').trim();
      if (isFbBadHeaderText(text)) return;
      var score=0;
      if (r.top<145) score+=700;
      if (r.left>=pr.left && r.right<=pr.right) score+=500;
      if (/^H[1-3]$/.test(el.tagName)||el.getAttribute('role')==='heading') score+=350;
      if (fbProfileHrefV1218(el)) score+=450;
      if (text.length<=45) score+=150;
      score-=Math.abs((r.left+r.width/2)-(pr.left+pr.width/2))/8;
      nodes.push({el:el,text:text,score:score});
    });
    nodes.sort(function(a,b){return b.score-a.score;});
    if (!nodes.length) return null;
    var title=nodes[0], node=title.el, header=title.el, hops=0;
    while (node && hops<10) {
      var r=node.getBoundingClientRect();
      if (fbVisibleV1218(node) && r.top>=0 && r.top<190 && r.left>=pr.left-30 && r.right<=pr.right+30 && r.width>=160 && r.height>=28 && r.height<=180) header=node;
      if (node===pane) break;
      node=node.parentElement; hops++;
    }
    return {headerEl:header,titleEl:title.el,name:title.text,profileHref:fbProfileHrefV1218(title.el)};
  }

  function findFbAvatarV1218(ctx) {
    if (!ctx || !ctx.headerEl) return '';
    var titleRect=ctx.titleEl.getBoundingClientRect(), best=null, bestScore=-Infinity;
    ctx.headerEl.querySelectorAll('img,image').forEach(function(img){
      if (!fbVisibleV1218(img)) return;
      var r=img.getBoundingClientRect(), size=Math.min(r.width,r.height);
      if (size<24 || size>100 || r.top>190) return;
      var src=String(img.currentSrc||img.src||img.getAttribute('xlink:href')||img.getAttribute('href')||'').trim();
      if (!src || /^(data:image\/svg|javascript:)/i.test(src)) return;
      var score=300-Math.abs((r.top+r.height/2)-(titleRect.top+titleRect.height/2))*4;
      var link=img.closest && img.closest('a[href]');
      if (ctx.profileHref && link && String(link.getAttribute('href')||'')===ctx.profileHref) score+=900;
      if (r.right<=titleRect.left+35) score+=250;
      if (score>bestScore) {bestScore=score; best=src;}
    });
    return bestScore>=250 ? (best||'') : '';
  }

  function fbGateCandidateV1218(raw) {
    var g=__fbIdentityGateV1218, now=Date.now();
    var liveThread=fbThreadIdV1218();
    if (!raw || !liveThread || String(raw.threadId)!==liveThread || !raw.headerEl || !fbVisibleV1218(raw.headerEl) || isFbBadHeaderText(raw.name)) {
      g.accepted=null; g.token++; return raw ? Object.assign(raw,{writable:false,readonlyReason:'FB 当前会话身份尚未通过上下文校验'}) : null;
    }
    var sig=liveThread+'|'+String(raw.name||'')+'|'+String(raw.profileHref||'')+'|'+String(raw.avatar||'');
    if (g.route!==liveThread || g.signature!==sig) {
      g.route=liveThread; g.signature=sig; g.hits=1; g.firstAt=now; g.accepted=null; g.token++;
    } else {
      g.hits++;
    }
    // 至少跨 600ms 得到两次一致采样，避免同一轮函数调用造成假稳定。
    if (!g.accepted && g.hits>=2 && now-g.firstAt>=600) {
      g.accepted={token:g.token,threadId:liveThread,signature:sig,headerEl:raw.headerEl};
    }
    var ok=!!(g.accepted && g.accepted.token===g.token && g.accepted.threadId===liveThread && g.accepted.signature===sig && raw.headerEl.isConnected);
    raw.id='fb:'+liveThread; raw.writable=ok; raw.fbWriteToken=ok?g.token:null;
    raw.readonlyReason=ok?'':'正在核验 Messenger 当前会话的姓名与头像；稳定前保持只读。';
    return raw;
  }

  function canWriteFbIdentityV1218(info, token) {
    var g=__fbIdentityGateV1218, a=g.accepted, liveThread=fbThreadIdV1218();
    if (!info || info.platform!=='fb' || !a || token===null || token===undefined) return false;
    var sig=liveThread+'|'+String(info.name||'')+'|'+String(info.profileHref||'')+'|'+String(info.avatar||'');
    return info.writable===true && token===g.token && a.token===g.token && a.threadId===liveThread && a.signature===sig && String(info.threadId||'')===liveThread && info.headerEl===a.headerEl && a.headerEl.isConnected;
  }

  function getFbHeaderInfo() {
    var threadId=fbThreadIdV1218();
    if (!threadId) return null;
    var pane=findFbMessagePane();
    if (!pane) return fbGateCandidateV1218({id:'fb:'+threadId,threadId:threadId,name:'',avatar:'',platform:'fb',headerEl:null});
    var ctx=findFbHeaderContextV1218(pane);
    if (!ctx || !ctx.headerEl || !ctx.name) return fbGateCandidateV1218({id:'fb:'+threadId,threadId:threadId,name:'',avatar:'',platform:'fb',headerEl:ctx&&ctx.headerEl||null});
    var raw={id:'fb:'+threadId,threadId:threadId,name:ctx.name,avatar:'',platform:'fb',headerEl:ctx.headerEl,profileHref:ctx.profileHref||''};
    raw.avatar=findFbAvatarV1218(ctx);
    return fbGateCandidateV1218(raw);
  }

  // V206.0.6：兼容 Telegram Web K/A 两套 DOM。peer id 既可能在标题元素，
  // 也可能在其祖先/兄弟节点或 URL hash 中；只接受数字型稳定 peer id。
  function tgNormalizePeerIdV2065(value) {
    var text = String(value == null ? '' : value).trim();
    if (!text) return '';
    var m = /^(?:peer|user|chat|channel)?[:_\-]?(-?\d{3,})$/i.exec(text);
    if (m) return m[1];
    m = /(?:^|[?&#/=])(u|c|s)?(-?\d{3,})(?:$|[?&#/])/i.exec(text);
    return m ? ((m[1] && m[1].toLowerCase() !== 'u' && m[2].charAt(0) !== '-') ? '-' + m[2] : m[2]) : '';
  }
  function tgVisibleV2065(el) {
    if (!el || !el.isConnected || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1 && r.bottom > 0 && r.right > 0 && r.top < 180;
  }
  function findTgHeaderPeerTitle() {
    var selectors = [
      '.sidebar-header.topbar .peer-title', '.chat-info-container .peer-title',
      '.chat-utils .peer-title', '.topbar .peer-title',
      'header .peer-title', '[class*="topbar"] [class*="peer-title"]'
    ];
    var candidates = [];
    try {
      document.querySelectorAll(selectors.join(',')).forEach(function (el) {
        if (el.closest && el.closest('#column-right')) return;
        if (!tgVisibleV2065(el)) return;
        var text = String(el.textContent || el.getAttribute('title') || '').replace(/\s+/g, ' ').trim();
        if (!text || text.length > 120) return;
        if (candidates.indexOf(el) < 0) candidates.push(el);
      });
    } catch (e) {}
    candidates.sort(function (a, b) {
      var ra=a.getBoundingClientRect(), rb=b.getBoundingClientRect();
      var sa=(ra.top < 100 ? 1000 : 0)+ra.width*ra.height;
      var sb=(rb.top < 100 ? 1000 : 0)+rb.width*rb.height;
      return sb-sa;
    });
    return candidates[0] || null;
  }
  function findTgHeaderContainer(peerTitleEl) {
    var node=peerTitleEl, best=peerTitleEl, hops=0;
    while (node && hops < 12) {
      if (tgVisibleV2065(node)) {
        var r=node.getBoundingClientRect();
        if (r.height >= 35 && r.height <= 150 && r.width >= 220) best=node;
        if ((node.classList && (node.classList.contains('topbar') || node.classList.contains('chat-info-container'))) || node.tagName === 'HEADER') return node;
      }
      node=node.parentElement; hops++;
    }
    return best;
  }
  function tgPeerIdV2065(titleEl, headerEl) {
    var nodes=[], node=titleEl, hops=0, attrs=['data-peer-id','data-peer','data-user-id','data-chat-id','data-dialog-id'];
    while (node && hops < 8) { nodes.push(node); if (node===headerEl) break; node=node.parentElement; hops++; }
    if (headerEl && headerEl.querySelectorAll) {
      try { headerEl.querySelectorAll('[data-peer-id],[data-peer],[data-user-id],[data-chat-id],[data-dialog-id]').forEach(function(x){nodes.push(x);}); } catch(e) {}
    }
    for (var i=0;i<nodes.length;i++) for (var j=0;j<attrs.length;j++) {
      var id=tgNormalizePeerIdV2065(nodes[i].getAttribute && nodes[i].getAttribute(attrs[j]));
      if (id) return id;
    }
    return tgNormalizePeerIdV2065(location.hash) || tgNormalizePeerIdV2065(location.href);
  }
  function getTgHeaderInfo() {
    var peerTitleEl=findTgHeaderPeerTitle();
    if (!peerTitleEl) return null;
    var headerEl=findTgHeaderContainer(peerTitleEl);
    if (!headerEl) return null;
    var peerId=tgPeerIdV2065(peerTitleEl,headerEl);
    if (!peerId) return null;
    var threadId=tgNormalizePeerIdV2065(peerTitleEl.getAttribute('data-thread-id')) || '0';
    var name=String(peerTitleEl.textContent || peerTitleEl.getAttribute('title') || '').replace(/\s+/g,' ').trim();
    if (!name) return null;
    var subtitle='';
    try { var sub=headerEl.querySelector('.info .subtitle,.peer-subtitle,.status,[class*="subtitle"]'); subtitle=String(sub&&sub.textContent||'').toLowerCase(); } catch(e) {}
    var isGroup=/(members?|subscribers?|成员|订阅者|群组|group)/i.test(subtitle) || peerTitleEl.getAttribute('data-is-group')==='true';
    var avImg=headerEl.querySelector('.avatar img') || headerEl.querySelector('img');
    var avatar=(avImg && (avImg.currentSrc||avImg.src)) || '';
    var uniqueId='tg:'+peerId+(threadId!=='0'?':'+threadId:'');
    return {id:uniqueId,name:name,avatar:avatar,platform:'tg',headerEl:headerEl,
      peerId:peerId,threadId:threadId,chatType:isGroup?'group':'contact',
      identityStatus:isGroup?'confirmed-group':'confirmed-contact',writable:isGroup ? false : true,
      readonlyReason:isGroup?'当前为 Telegram 群组会话，已隔离客户资料读写。':''};
  }

  // V206.0.6：平台私有选择器失效时仍解析一个可见挂载锚点。
  // fallback 永远只读；不得把临时 route ID 写入联系人事实库。
  function visibleAnchorV2063(selectors) {
    var list = [];
    try { document.querySelectorAll(selectors.join(',')).forEach(function(el){ if (list.indexOf(el) < 0) list.push(el); }); } catch (e) {}
    var best = null, score = -1;
    list.forEach(function(el) {
      if (!el || !el.isConnected || el.id === NOTE_BAR_ID || (el.closest && el.closest('#' + NOTE_BAR_ID))) return;
      var r; try { r = el.getBoundingClientRect(); } catch (e) { return; }
      if (!r || r.width < 180 || r.height < 20 || r.bottom <= 0 || r.right <= 0 || r.top >= window.innerHeight) return;
      var value = Math.min(r.width, 1200) - Math.abs(r.top - 45) * 2 + (String(el.tagName).toLowerCase() === 'header' ? 1000 : 0);
      if (value > score) { score = value; best = el; }
    });
    return best;
  }
  function platformFallbackInfoV2063(platform, reason) {
    var selectors = platform === 'wa' ? ['#main header','#main','div[role="main"]'] :
      platform === 'ig' ? ['main header','main div[role="main"]','main'] :
      platform === 'fb' ? ['div[role="main"] header','div[role="main"]','main'] :
      ['.sidebar-header.topbar','.chat-info-container','.chat-utils','.chat','main','div[role="main"]'];
    var anchor = visibleAnchorV2063(selectors);
    if (!anchor) return null;
    var route = String(location.pathname || '') + String(location.search || '');
    var text = '';
    try {
      var title = anchor.querySelector('[title],h1,h2,h3,[dir="auto"],.peer-title');
      text = String(title && (title.getAttribute('title') || title.textContent) || '').replace(/\s+/g,' ').trim().slice(0,120);
    } catch (e) {}
    return { id:platform + '-pending:' + simpleHash(route), name:text || '当前聊天', avatar:'', platform:platform,
      headerEl:anchor, writable:false, identityStatus:'unconfirmed', identityReason:reason || 'platform-selector-fallback',
      readonlyReason:'已识别聊天区域，但稳定联系人身份尚未确认；面板保持只读并继续自动重试。', temporaryIdentity:true };
  }
  function preferResolvedOrFallbackV2063(info, platform, reason) {
    // 非空对象也可能只有 route ID 而没有可挂载 Header（Messenger 常见）。
    if (info && info.headerEl && info.headerEl.isConnected) return info;
    var fallback = platformFallbackInfoV2063(platform, reason);
    if (!fallback) return info;
    // 保留已解析出的路由 ID/名称用于诊断，但 fallback 必须保持只读。
    if (info && info.id) fallback.routeCandidateId = info.id;
    if (info && info.name && !fallback.name) fallback.name = info.name;
    return fallback;
  }
  function getContactInfoUnifiedRawV121() {
    var info = null;
    if (location.hostname.indexOf('instagram.com') >= 0) return preferResolvedOrFallbackV2063(getIgHeaderInfo(), 'ig','instagram-header-or-identity-unresolved');
    if ((location.hostname.indexOf('messenger.com') >= 0 || (location.hostname.indexOf('facebook.com') >= 0 && location.pathname.indexOf('/messages') >= 0))) return preferResolvedOrFallbackV2063(getFbHeaderInfo(), 'fb','messenger-header-or-route-unresolved');
    if (location.hostname.indexOf('web.telegram.org') >= 0) return preferResolvedOrFallbackV2063(getTgHeaderInfo(), 'tg','telegram-header-or-peer-unresolved');
    return preferResolvedOrFallbackV2063(getWaHeaderInfo(), 'wa','whatsapp-header-or-identity-unresolved');
  }
  function getContactInfoUnified() {
    var raw = getContactInfoUnifiedRawV121();
    if (!raw) return null;
    if (raw.writable === false || raw.temporaryIdentity) return raw;
    return crmResolveCurrentInfoV121(raw);
  }

  var currentChatId = null;
  var currentChatName = null;
  var currentChatPlatform = null;
  var managePanelWindow = null;
  var __linkedFieldEditModeByChat = {};
  var __linkedFieldFocusKeyByChat = {};

  // ========================================================
  // v43：WA 姓名实时同步
  // 当同一个联系人 ID 的显示姓名发生变化时，自动同步到存储数据与管理面板
  // 典型场景：WA 原本显示手机号，后来保存联系人后变成姓名
  // ========================================================
  var __lastSyncedNameByChatId = {};

  function shouldSyncContactName(info, oldName, newName) {
    if (!info || !info.id || !newName) return false;
    if (oldName === newName) return false;
    if (looksLikeStatusText(newName)) return false;
    return true;
  }

  function syncCurrentContactName(info) {
    try {
      if (!info || !info.id) return false;
      if (info.platform === 'wa' && !canWriteWaIdentityV120(info, info.waWriteToken)) return false;
      if (info.platform === 'ig' && !canWriteIgIdentityV1212(info, info.igSessionToken)) return false;
      if (info.platform === 'fb' && !canWriteFbIdentityV1218(info, info.fbWriteToken)) return false;

      var id = info.id;
      var newName = String(info.name || '').trim();
      var avatar = String(info.avatar || '').trim();

      var data = loadData();
      var rec = data[id];
      if (!rec) return false;

      var changed = false;

      // 1. 同步名称
      if (newName && !looksLikeStatusText(newName)) {
        var oldName = String(rec.name || '').trim();
        if (shouldSyncContactName(info, oldName, newName)) {
          rec.name = newName;
          changed = true;
        }
      }

      // 2. 同步头像
      if (avatar && rec.avatar !== avatar) {
        rec.avatar = avatar;
        changed = true;
      }
      if (avatar && avatar.indexOf('data:image/') === 0 && rec.avatarData !== avatar) {
        rec.avatarData = avatar;
        changed = true;
      }

      if (!changed) return false;

      rec.platform = rec.platform || info.platform || inferPlatform(rec, id);
      if (info.platform === 'ig' && info.username) rec.igUsername = info.username;
      rec.updatedAt = Date.now();
      data[id] = rec;

      if (rec.mainKey && data[rec.mainKey]) {
        var main = data[rec.mainKey];
        var memberIds = Array.isArray(main.memberIds) ? main.memberIds : [];
        var members = memberIds.map(function (mid) {
          var e = data[mid];
          return e ? Object.assign({ __id: mid, __platform: inferPlatform(e, mid) }, e) : null;
        }).filter(Boolean);

        if (members.length >= 2) {
          data[rec.mainKey] = buildMainRecordFromMembers(rec.mainKey, members, main);
        } else {
          if (newName) main.name = newName;
          if (avatar && !main.avatar) main.avatar = avatar;
          main.updatedAt = Date.now();
        }
      }

      saveData(data);
      refreshPanelIfOpen();
      return true;
    } catch (e) {
      return false;
    }
  }

  // ========================================================
  // 方案C：同人跨渠道关联 —— 核心数据层（已修复）
  // ========================================================
  var MAIN_PREFIX = 'MAIN::';

  function getMainKey(normalizedPhone) {
    return MAIN_PREFIX + normalizedPhone;
  }
  function isMainKey(id) {
    return typeof id === 'string' && id.indexOf(MAIN_PREFIX) === 0;
  }

  function buildTaggedValue(platform, value) {
    if (!value) return '';
    return String(value).trim();
  }

  function mergeFieldAcrossMembers(members, fieldKey) {
    var parts = [];
    var seen = {};
    members.forEach(function (m) {
      var v = m[fieldKey];
      if (v && String(v).trim()) {
        var text = buildTaggedValue(m.__platform || inferPlatform(m, m.__id), v);
        if (text && !seen[text]) { seen[text] = true; parts.push(text); }
      }
    });
    return parts.join(' / ');
  }

  function buildMainRecordFromMembers(mainKey, members, existingMain) {
    var main = existingMain ? Object.assign({}, existingMain) : {};
    main.isMainRecord = true;
    main.memberIds = members.map(function (m) { return m.__id; });
    // 主记录只作为关联索引与只读聚合展示层；备注字段每次由成员字段动态拼接，不作为可编辑底层数据
    main.__mergedFields = {};
    getAllFieldDefinitionsV126(false).forEach(function (f) {
      var merged = mergeFieldAcrossMembers(members, f.key);
      main[f.key] = merged || '';
      main.__mergedFields[f.key] = true;
    });

    // v73.1：主记录为只读聚合层，标签每次从成员重新计算，避免旧值滞留
    main.tag = '';
    for (var i = 0; i < members.length; i++) {
      if (members[i].tag) { main.tag = members[i].tag; break; }
    }
    // v54: 主记录自动计算所有子渠道画像并集
    var t2Set = {};
    members.forEach(function (m) {
      var arr = Array.isArray(m.tag2) ? m.tag2 : (m.tag2 ? [m.tag2] : []);
      arr.forEach(function (t) { if (t) t2Set[t] = true; });
    });
    main.tag2 = Object.keys(t2Set);
    // v73.1：跟进阶段也必须每次重新计算并集，不能只在主记录为空时计算
    var stageSet = {};
    members.forEach(function (m) {
      (Array.isArray(m.stages) ? m.stages : []).forEach(function (s) { stageSet[s] = true; });
    });
    main.stages = Object.keys(stageSet);
    var latest = members.slice().sort(function (a, b) { return (b.updatedAt || 0) - (a.updatedAt || 0); })[0];
    main.name = latest ? (latest.name || main.name || '') : (main.name || '');
    main.manualPhone = (members[0] && (members[0].manualPhone || '')) || main.manualPhone || '';
    main.updatedAt = Date.now();
    return main;
  }

  // v103：统一取得叶子联系人的当前规范化号码。
  function getRecordPhoneNormV103(rec) {
    if (!rec) return '';
    var phoneSrc = rec.manualPhone || (isPhoneLikeText(rec.name) ? rec.name : '');
    return normalizePhone(phoneSrc);
  }

  // v104：同步策略是跨源关联判断的第一事实；旧设置仅作为本源兼容回退。
  function getLinkPolicyDecisionV104(rec, norm) {
    if (!rec || !norm) return null;
    var phones = rec.linkPolicy && rec.linkPolicy.blockedPhones;
    if (!phones || !Object.prototype.hasOwnProperty.call(phones, norm)) return null;
    var state = phones[norm];
    if (typeof state === 'boolean') return state;
    if (!state || typeof state !== 'object' || typeof state.blocked !== 'boolean') return null;
    return state.blocked;
  }

  function setRecordLinkPolicyV104(rec, norm, blocked, updatedAt) {
    if (!rec || !norm) return false;
    var policy = rec.linkPolicy && typeof rec.linkPolicy === 'object' ? rec.linkPolicy : {};
    var phones = policy.blockedPhones && typeof policy.blockedPhones === 'object' ? policy.blockedPhones : {};
    phones[norm] = {
      blocked: !!blocked,
      updatedAt: Number(updatedAt || Date.now()),
      sourceId: (typeof getLocalSyncSourceId === 'function') ? getLocalSyncSourceId() : ''
    };
    policy.version = 1;
    policy.blockedPhones = phones;
    rec.linkPolicy = policy;
    return true;
  }

  function isAssociationBlockedV103(channelId, norm, settings, rec) {
    if (!channelId || !norm) return false;
    var decision = getLinkPolicyDecisionV104(rec, norm);
    if (decision !== null) return decision;
    settings = settings || getSettings();
    var map = settings.unlinkedAssociations || {};
    return !!(map[channelId] && map[channelId][norm]);
  }

  function migrateLegacyUnlinkedRulesV103(data, settings) {
    var legacy = settings.unlinkedMemberIds || {};
    var map = settings.unlinkedAssociations || {};
    var changed = false;
    Object.keys(legacy).forEach(function (id) {
      if (!legacy[id]) return;
      var rec = data[id];
      var norm = getRecordPhoneNormV103(rec);
      if (norm) {
        if (!map[id]) map[id] = {};
        if (!map[id][norm]) { map[id][norm] = true; changed = true; }
      }
      delete legacy[id];
      changed = true;
    });
    // 把 v103 本源设置迁入联系人记录，随后会随 batch-upsert 传播到所有源。
    Object.keys(map).forEach(function (id) {
      var rec = data[id];
      if (!rec || !map[id]) return;
      Object.keys(map[id]).forEach(function (norm) {
        if (!map[id][norm] || getLinkPolicyDecisionV104(rec, norm) !== null) return;
        setRecordLinkPolicyV104(rec, norm, true, Date.now());
        changed = true;
      });
    });
    if (changed || Number(settings.linkReconcileVersion || 0) < 104) {
      settings.unlinkedMemberIds = legacy;
      settings.unlinkedAssociations = map;
      settings.linkReconcileVersion = 104;
      GM_setValue(SETTINGS_KEY, JSON.stringify(settings));
      if (changed) saveData(data);
    }
    return settings;
  }

  // v103：完整关联对账。只修改 mainKey/viewMode 和 MAIN:: 索引，不回写联系人业务字段。
  function reconcileLinkStateV103(opts) {
    opts = opts || {};
    var data = loadData();
    var before = JSON.stringify(data);
    var settings = migrateLegacyUnlinkedRulesV103(data, getSettings());
    var phoneMap = {};
    var oldMains = {};

    Object.keys(data).forEach(function (id) {
      if (isMainKey(id)) { oldMains[id] = data[id]; return; }
      if (isProtectedIgThreadIdV1217(id)) return;
      var rec = data[id];
      if (!rec) return;
      var norm = getRecordPhoneNormV103(rec);
      if (!norm || isAssociationBlockedV103(id, norm, settings, rec)) return;
      if (!phoneMap[norm]) phoneMap[norm] = [];
      phoneMap[norm].push(Object.assign({ __id: id, __platform: inferPlatform(rec, id) }, rec));
    });

    var validGroups = {};
    Object.keys(phoneMap).forEach(function (norm) {
      if (phoneMap[norm].length >= 2) validGroups[norm] = phoneMap[norm];
    });

    // 先移除全部旧主记录及叶子上的旧关联元数据，再按当前事实重建。
    Object.keys(data).forEach(function (id) {
      if (isMainKey(id)) { delete data[id]; return; }
      if (isProtectedIgThreadIdV1217(id)) return;
      var rec = data[id];
      if (!rec) return;
      var norm = getRecordPhoneNormV103(rec);
      if (!norm || !validGroups[norm] || isAssociationBlockedV103(id, norm, settings, rec)) {
        delete rec.mainKey;
        delete rec.viewMode;
      }
    });

    Object.keys(validGroups).forEach(function (norm) {
      var members = validGroups[norm];
      var mainKey = getMainKey(norm);
      var main = buildMainRecordFromMembers(mainKey, members, oldMains[mainKey]);
      main.manualPhone = norm;
      data[mainKey] = main;
      members.forEach(function (m) {
        var rec = data[m.__id];
        if (!rec) return;
        var keepMode = rec.mainKey === mainKey && (rec.viewMode === 'shared' || rec.viewMode === 'independent');
        rec.mainKey = mainKey;
        if (!keepMode) rec.viewMode = 'shared';
      });
    });

    var after = JSON.stringify(data);
    if (after !== before || opts.alwaysSave) saveData(data);
    return {
      changed: after !== before,
      groupCount: Object.keys(validGroups).length,
      validGroups: validGroups
    };
  }

  function runLinkScan(opts) {
    // force 在 v103 中仅表示立即完整对账，绝不清空手动解绑规则。
    return reconcileLinkStateV103(opts || {});
  }

  // v103：本地存储关联的唯一真实性验证入口。
  function getValidStoredLinkInfo(channelId, data) {
    if (isProtectedIgThreadIdV1217(channelId)) return null;
    data = data || loadData();
    var rec = data[channelId];
    if (!rec || !rec.mainKey) return null;
    var norm = getRecordPhoneNormV103(rec);
    if (!norm || rec.mainKey !== getMainKey(norm)) return null;
    var settings = getSettings();
    if (isAssociationBlockedV103(channelId, norm, settings, rec)) return null;
    var main = data[rec.mainKey];
    if (!main || !main.isMainRecord) return null;
    var ids = Array.isArray(main.memberIds) ? main.memberIds.slice() : [];
    if (ids.length < 2 || ids.indexOf(channelId) < 0) return null;
    var validIds = ids.filter(function (id) {
      if (isProtectedIgThreadIdV1217(id)) return false;
      var member = data[id];
      return !!member && getRecordPhoneNormV103(member) === norm &&
        !isAssociationBlockedV103(id, norm, settings, member);
    });
    if (validIds.length < 2 || validIds.length !== ids.length || validIds.indexOf(channelId) < 0) return null;
    return {
      mainKey: rec.mainKey,
      main: main,
      viewMode: rec.viewMode || 'shared',
      memberIds: validIds,
      isLinked: true,
      memberCount: validIds.length
    };
  }

  function resolveEffectiveRecordId(channelId) {
    if (isMainKey(channelId)) return channelId;
    var data = loadData();
    var info = getValidStoredLinkInfo(channelId, data);
    if (!info || info.viewMode === 'independent') return channelId;
    return info.mainKey;
  }

  function resolveTagStageRecordId(channelId) {
    if (isMainKey(channelId)) return channelId;
    var info = getValidStoredLinkInfo(channelId, loadData());
    return info ? info.mainKey : channelId;
  }

  function getChannelLinkInfo(channelId) {
    return getValidStoredLinkInfo(channelId, loadData());
  }

  function getMergedReadonlyRecord(channelId) {
    var data = loadData();
    var linkInfo = getValidStoredLinkInfo(channelId, data);
    var out = {};
    if (!linkInfo) return data[channelId] || {};
    var members = linkInfo.memberIds.map(function (id) {
      var e = data[id];
      return e ? Object.assign({ __id: id, __platform: inferPlatform(e, id) }, e) : null;
    }).filter(Boolean);
    getAllFieldDefinitionsV126(false).forEach(function (f) { out[f.key] = mergeFieldAcrossMembers(members, f.key); });
    return out;
  }

  function setChannelViewMode(channelId, mode) {
    if (isProtectedIgThreadIdV1217(channelId)) return false;
    var data = loadData();
    if (!getValidStoredLinkInfo(channelId, data)) return false;
    data[channelId].viewMode = (mode === 'independent') ? 'independent' : 'shared';
    saveData(data);
    return true;
  }

  // v103：验证当前联系人是否处于有效的动态（含跨源）号码组。
  function hasValidDynamicAssociationV103(channelId, norm, settings) {
    if (isProtectedIgThreadIdV1217(channelId)) return false;
    if (!channelId || !norm || isAssociationBlockedV103(channelId, norm, settings, (loadData() || {})[channelId])) return false;
    var panelData = {};
    try { panelData = getPanelDisplayData() || {}; } catch (e) { panelData = loadData() || {}; }
    var foundTarget = false;
    var count = 0;
    Object.keys(panelData).forEach(function (id) {
      var rec = panelData[id];
      if (!rec || isProtectedIgThreadIdV1217(id)) return;
      try { if (isAnyMainRecordV93(id, rec)) return; } catch (e) { if (isMainKey(id)) return; }
      var memberNorm = getRecordPhoneNormV103(rec);
      if (memberNorm !== norm || isAssociationBlockedV103(id, norm, settings, rec)) return;
      count++;
      if (id === channelId) foundTarget = true;
    });
    return foundTarget && count >= 2;
  }

  function syncLinkPolicyAcrossSourcesV104() {
    setTimeout(async function () {
      try {
        var up = await localSyncUploadOnly();
        if (up && up.ok && isLocalSyncAggregateEnabled()) await localSyncRefreshAggregate();
        try { refreshPanelIfOpen(); } catch (e) {}
      } catch (e) {}
    }, 80);
  }

  function unlinkChannel(channelId, opts) {
    if (isProtectedIgThreadIdV1217(channelId)) return false;
    opts = opts || {};
    var data = loadData();
    var rec = data[channelId];
    if (!rec) return false;
    var norm = getRecordPhoneNormV103(rec);
    var storedInfo = getValidStoredLinkInfo(channelId, data);
    var settings = migrateLegacyUnlinkedRulesV103(data, getSettings());
    var dynamicLinked = norm ? hasValidDynamicAssociationV103(channelId, norm, settings) : false;
    var isActuallyLinked = !!storedInfo || dynamicLinked;
    var shouldBlock = opts.blockCurrentPhone !== false && isActuallyLinked && !!norm;
    if (shouldBlock) {
      var map = settings.unlinkedAssociations || {};
      if (!map[channelId]) map[channelId] = {};
      map[channelId][norm] = true;
      settings.unlinkedAssociations = map;
      settings.linkReconcileVersion = 104;
      GM_setValue(SETTINGS_KEY, JSON.stringify(settings));
      setRecordLinkPolicyV104(rec, norm, true, Date.now());
    }
    delete rec.mainKey;
    delete rec.viewMode;
    saveData(data);
    reconcileLinkStateV103();
    if (shouldBlock) syncLinkPolicyAcrossSourcesV104();
    return isActuallyLinked;
  }

  function unlinkAssociationMembersV103(members) {
    members = Array.isArray(members) ? members : [];
    var data = loadData();
    var settings = migrateLegacyUnlinkedRulesV103(data, getSettings());
    var map = settings.unlinkedAssociations || {};
    var blockedCount = 0;
    var now = Date.now();
    members.forEach(function (member) {
      var id = member && (member.__id || member.id);
      var rec = id ? data[id] : null;
      if (!id || !rec) return;
      var norm = getRecordPhoneNormV103(rec);
      if (!norm) return;
      if (!map[id]) map[id] = {};
      if (!map[id][norm]) blockedCount++;
      map[id][norm] = true;
      setRecordLinkPolicyV104(rec, norm, true, now);
      delete rec.mainKey;
      delete rec.viewMode;
    });
    settings.unlinkedAssociations = map;
    settings.linkReconcileVersion = 104;
    GM_setValue(SETTINGS_KEY, JSON.stringify(settings));
    saveData(data);
    reconcileLinkStateV103();
    if (blockedCount) syncLinkPolicyAcrossSourcesV104();
    return blockedCount;
  }

  function relinkChannelAllow(channelId) {
    if (isProtectedIgThreadIdV1217(channelId)) return false;
    var data = loadData();
    var rec = data[channelId];
    var norm = getRecordPhoneNormV103(rec);
    if (!rec || !norm) return false;
    var settings = migrateLegacyUnlinkedRulesV103(data, getSettings());
    var wasBlocked = isAssociationBlockedV103(channelId, norm, settings, rec);
    var map = settings.unlinkedAssociations || {};
    if (map[channelId]) {
      delete map[channelId][norm];
      if (!Object.keys(map[channelId]).length) delete map[channelId];
    }
    settings.unlinkedAssociations = map;
    settings.linkReconcileVersion = 104;
    GM_setValue(SETTINGS_KEY, JSON.stringify(settings));
    // 明确的 false 墓碑覆盖其他源可能缓存的旧 true，不能只删除策略。
    setRecordLinkPolicyV104(rec, norm, false, Date.now());
    saveData(data);
    reconcileLinkStateV103();
    syncLinkPolicyAcrossSourcesV104();
    return wasBlocked;
  }

  function upsertFieldSmart(channelId, baseInfo, key, value) {
    if (isProtectedIgThreadIdV1217(channelId)) return;
    if (isMainKey(channelId)) {
      upsertField(channelId, {}, key, value);
      try { refreshPanelIfOpen(); } catch (e) { }
      return;
    }
    // v131：他源汇总记录走服务端覆盖层，不写本地 GM 业务库、不进本源快照。
    if (isV204ServerContact(channelId)) { var payload=v204FieldPayload(key,value); if(!payload){try{showCopyToast('⚠️ 字段 '+key+' 尚未接入 V204');}catch(e){} return false;} return v204UiWriteResult(v204PatchContact(channelId,payload),'保存'); }
    var data = loadData();
    var existed = !!data[channelId];
    if (!existed && !String(value || '').trim()) return;
    data[channelId] = Object.assign({}, data[channelId] || {}, baseInfo || {});
    data[channelId][key] = value;
    data[channelId].updatedAt = Date.now();
    // v123：统一交给 saveData/prune 收集自动删除 ID 并同步服务端。
    saveData(data);
    try { runLinkScanAndRefreshPanelNow(); } catch (e) { try { runLinkScan(); } catch (e2) { } try { refreshPanelIfOpen(); } catch (e3) { } }
  }

  function toggleStageSmart(channelId, stageKey, checked) {
    if (isProtectedIgThreadIdV1217(channelId)) return;
    // v131：他源阶段变更走覆盖层，基于当前汇总值增量修改。
    if (isV204ServerContact(channelId)) { var ctx=v204ContactContext(channelId),arr=Array.isArray(ctx.contact.customFields&&ctx.contact.customFields['ui.stages'])?ctx.contact.customFields['ui.stages'].slice():[];var idx=arr.indexOf(stageKey);if(checked&&idx<0)arr.push(stageKey);if(!checked&&idx>=0)arr.splice(idx,1);return v204UiWriteResult(v204PatchContact(channelId,{customFields:{'ui.stages':arr}}),'阶段保存'); }
    var effectiveId = resolveTagStageRecordId(channelId);
    toggleStage(effectiveId, stageKey, checked);
    try { runLinkScanAndRefreshPanelNow(); } catch (e) { try { runLinkScan(); } catch (e2) { } try { refreshPanelIfOpen(); } catch (e3) { } }
  }
  function upsertTagSmart(channelId, baseInfo, value) {
    if (isProtectedIgThreadIdV1217(channelId)) return;
    if (isMainKey(channelId)) {
      upsertField(channelId, {}, 'tag', value);
      return;
    }
    // v131：他源标签走覆盖层。
    if (isV204ServerContact(channelId)) return v204UiWriteResult(v204ReplaceUiTags(channelId,'tag',value?[value]:[]),'标签保存');
    var hasValue = !!String(value || '').trim();
    var data = loadData();
    if (!data[channelId] && !hasValue) return;
    var effectiveId = resolveTagStageRecordId(channelId);
    upsertField(effectiveId, (effectiveId === channelId ? (baseInfo || {}) : {}), 'tag', value);
    try { runLinkScanAndRefreshPanelNow(); } catch (e) { try { runLinkScan(); } catch (e2) { } try { refreshPanelIfOpen(); } catch (e3) { } }
  }

  function upsertTag2Smart(channelId, tags2Array) {
    if (isProtectedIgThreadIdV1217(channelId)) return;
    // v131：他源画像走覆盖层。
    if (isV204ServerContact(channelId)) return v204UiWriteResult(v204ReplaceUiTags(channelId,'persona',(Array.isArray(tags2Array)?tags2Array:[]).filter(function(x){return String(x||'').trim();})),'画像保存');
    var data = loadData();
    var arr0 = Array.isArray(tags2Array) ? tags2Array.filter(function (x) { return String(x || '').trim(); }) : [];
    if (!data[channelId] && arr0.length === 0) return;
    if (!data[channelId]) data[channelId] = {};
    data[channelId].tag2 = arr0;
    data[channelId].updatedAt = Date.now();
    if (!hasMeaningfulUserData(data[channelId])) {
      // v123：saveData 会执行本地清理并同步删除服务端。
      saveData(data);
      try { refreshPanelIfOpen(); } catch (e) { }
      return;
    }

    // 若属于关联组，实时更新主记录汇集的画像并集
    if (data[channelId].mainKey && data[data[channelId].mainKey]) {
      var mainKey = data[channelId].mainKey;
      var main = data[mainKey];
      var memberIds = Array.isArray(main.memberIds) ? main.memberIds : [];
      var t2Set = {};
      memberIds.forEach(function (mid) {
        var mem = data[mid];
        if (mem) {
          var arr = Array.isArray(mem.tag2) ? mem.tag2 : (mem.tag2 ? [mem.tag2] : []);
          arr.forEach(function(t){ if (t) t2Set[t] = true; });
        }
      });
      main.tag2 = Object.keys(t2Set);
      main.updatedAt = Date.now();
    }
    saveData(data);
    try { runLinkScanAndRefreshPanelNow(); } catch (e) { }
  }

  function resolveDisplayContext(channelId) {
    var data = loadData();
    var linkInfo = getChannelLinkInfo(channelId);
    var effectiveId = resolveEffectiveRecordId(channelId);
    var tagStageId = resolveTagStageRecordId(channelId);
    return {
      effectiveId: effectiveId,
      effectiveRecord: data[effectiveId] || {},
      tagStageId: tagStageId,
      tagStageRecord: data[tagStageId] || {},
      linkInfo: linkInfo
    };
  }

  function getPlatformBadgeHtml(platform) {
    var info = getPlatformInfo(platform);
    return '<span style="display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;color:#fff;background:' +
      info.color + ';margin-left:6px;vertical-align:middle;">' + info.short + '</span>';
  }

  function getCollapseKey(platform) {
    if (platform === 'ig') return 'igBarCollapsed';
    if (platform === 'fb') return 'fbBarCollapsed';
    if (platform === 'tg') return 'tgBarCollapsed';
    return 'waBarCollapsed';
  }

  // V206.0.6：聊天备注栏唯一 DOM ID。
  // V206.0.6 挂载重构遗漏该声明，导致所有 NOTE_BAR_ID 引用抛出
  // ReferenceError，并阻断只读栏和可编辑栏的创建。
  var NOTE_BAR_ID = 'wa-remark-bar';

  var __barRepositionHandler = null;
  var __v206UiDiagnostics = {
    version: '206.0.7',
    lastStage: '',
    lastError: '',
    lastErrorAt: 0,
    renderCount: 0,
    preflight: null
  };

  function v206ReportUiError(stage, error) {
    var message = String(
      error && (error.stack || error.message) ||
      error ||
      'unknown error'
    );
    __v206UiDiagnostics.lastStage = String(stage || 'unknown');
    __v206UiDiagnostics.lastError = message;
    __v206UiDiagnostics.lastErrorAt = Date.now();
    console.error('[JUBO V206 UI][' + stage + ']', error);
  }

  __v206UiDiagnostics.getSnapshot = function () {
    var info = null;
    var bar = null;
    var snapshotError = '';

    try {
      info = getContactInfoUnifiedRawV121();
    } catch (error) {
      snapshotError = String(
        error && (error.stack || error.message) || error || ''
      );
    }

    try {
      bar = document.getElementById(NOTE_BAR_ID);
    } catch (error) {
      if (!snapshotError) {
        snapshotError = String(
          error && (error.stack || error.message) || error || ''
        );
      }
    }

    return {
      version: '206.0.7',
      url: location.href,
      hostname: location.hostname,
      platform: info && info.platform,
      contactId: info && info.id,
      contactName: info && info.name,
      writable: info && info.writable,
      temporaryIdentity: info && info.temporaryIdentity,
      identityStatus: info && info.identityStatus,
      identityReason: info && (
        info.identityReason || info.readonlyReason
      ),
      hasAnchor: !!(info && info.headerEl),
      anchorConnected: !!(
        info && info.headerEl && info.headerEl.isConnected
      ),
      barId: NOTE_BAR_ID,
      barMounted: !!bar,
      barConnected: !!(bar && bar.isConnected),
      barReadonly: !!(
        bar &&
        bar.getAttribute('data-identity-readonly') === '1'
      ),
      renderCount: __v206UiDiagnostics.renderCount,
      lastStage: __v206UiDiagnostics.lastStage,
      lastError: __v206UiDiagnostics.lastError,
      lastErrorAt: __v206UiDiagnostics.lastErrorAt,
      preflight: __v206UiDiagnostics.preflight,
      snapshotError: snapshotError,
      syncIdentity: (function(){try{var ch=v204Channel(info||{});return {channel:ch,configured:!!v204AccountIdentity(ch),account:v204AccountIdentity(ch)||''};}catch(e){return {configured:false,error:String(e&&e.message||e)};}})(),
      syncQueueLength: (function(){try{return v204EventQueue().length;}catch(e){return -1;}})(),
      syncLastRequest: (function(){try{return LOCAL_SYNC_LAST_STATUS.lastRequest||null;}catch(e){return null;}})()
    };
  };

  function v206ExportDiagnostics(api) {
    try {
      window.__JUBAO_V206_DIAG__ = api;
    } catch (error) {
      console.warn(
        '[JUBO V206 DIAG] 沙箱诊断对象导出失败',
        error
      );
    }

    try {
      if (
        typeof unsafeWindow !== 'undefined' &&
        unsafeWindow
      ) {
        unsafeWindow.__JUBAO_V206_DIAG__ = api;
      }
    } catch (error) {
      console.warn(
        '[JUBO V206 DIAG] 页面诊断对象导出失败',
        error
      );
    }
  }

  v206ExportDiagnostics(__v206UiDiagnostics);

    // ========================================================
  // v44：Messenger 红框主聊天列顶置挂载（完美贴合，随窗口自由缩放，杜绝多重叠加）
  // ========================================================
  function cleanupDuplicateBars() {
    var bars = document.querySelectorAll('#' + NOTE_BAR_ID);
    if (bars.length > 1) {
      for (var i = 0; i < bars.length - 1; i++) {
        bars[i].remove();
      }
    }
  }

  function findMessengerMainChatContainer(headerEl) {
    if (!(location.hostname.indexOf('messenger.com') >= 0 || (location.hostname.indexOf('facebook.com') >= 0 && location.pathname.indexOf('/messages') >= 0)) || !headerEl) return null;

    // 1. 最稳妥方式：如果 header 拥有直接父级容器，且该父级正是聊天主列
    var p = headerEl.parentElement;
    if (p && p !== document.body) {
      return { container: p, insertAfter: headerEl };
    }

    // 2. 向上追溯查找具有有效宽度的聊天区域容器（排除全屏顶层容器）
    var node = headerEl;
    var hops = 0;
    while (node && hops < 6) {
      if (node.parentElement && node.parentElement !== document.body) {
        var parent = node.parentElement;
        var rect = parent.getBoundingClientRect();
        // 严格限制：必须属于中栏范围（不能覆盖左侧会话栏，left >= 180，且不能是全屏宽度）
        if (rect.left >= 180 && rect.width >= 300 && rect.width < window.innerWidth * 0.95) {
          return { container: parent, insertAfter: node };
        }
      }
      node = node.parentElement;
      hops++;
    }

    return null;
  }

  function embedMessengerBar(bar, headerEl) {
    if (!(location.hostname.indexOf('messenger.com') >= 0 || (location.hostname.indexOf('facebook.com') >= 0 && location.pathname.indexOf('/messages') >= 0)) || !headerEl) return false;

    cleanupDuplicateBars();

    var target = findMessengerMainChatContainer(headerEl);
    if (target && target.container) {
      // 样式设为 100% 宽度的流式嵌入，随红框宽度自由变化
      bar.style.position = 'relative';
      bar.style.top = '0px';
      bar.style.left = '0px';
      bar.style.right = 'auto';
      bar.style.bottom = 'auto';
      bar.style.width = '100%';
      bar.style.minWidth = '280px';
      bar.style.maxWidth = '100%';
      bar.style.margin = '0';
      bar.style.boxSizing = 'border-box';
      bar.style.zIndex = '100';
      bar.style.flex = '0 0 auto';
      bar.style.alignSelf = 'stretch';
      bar.style.boxShadow = '0 2px 6px rgba(0,0,0,0.06)';

      if (target.insertAfter && target.insertAfter.parentElement === target.container) {
        if (target.insertAfter.nextSibling !== bar) {
          target.container.insertBefore(bar, target.insertAfter.nextSibling);
        }
      } else {
        if (bar.parentElement !== target.container) {
          target.container.insertBefore(bar, target.container.firstChild);
        }
      }
      return true;
    }

    // 兜底方案：绝不使用顶层 prepend，而是精准吸附在 header 正下方，杜绝跑到整页顶端
    if (bar.parentElement !== document.body) document.body.appendChild(bar);
    var hr = headerEl.getBoundingClientRect ? headerEl.getBoundingClientRect() : null;
    if (hr && hr.bottom > 0) {
      bar.style.position = 'fixed';
      bar.style.top = Math.round(hr.bottom) + 'px';
      bar.style.left = Math.round(hr.left) + 'px';
      bar.style.width = Math.max(320, Math.round(hr.width)) + 'px';
      bar.style.minWidth = '320px';
      bar.style.maxWidth = '1000px';
      bar.style.margin = '0';
      bar.style.boxSizing = 'border-box';
      bar.style.zIndex = '99999';
      return true;
    }
    return false;
  }

  function setupBarPhysicalIsolation(bar, headerEl) {
    function reposition() {
      // V206.0.6：本函数负责首次挂载，不能要求新建 bar 已经 isConnected。
      if (!bar) return;
      cleanupDuplicateBars();
      if (!headerEl || !headerEl.isConnected) headerEl = visibleAnchorV2063(['#main header','main header','div[role="main"]','main']);
      if (!headerEl || !headerEl.isConnected) {
        if (bar.parentElement !== document.body) document.body.appendChild(bar);
        bar.style.cssText += ';position:fixed!important;top:8px!important;left:50%!important;transform:translateX(-50%)!important;width:min(920px,96vw)!important;z-index:2147483646!important;display:flex!important;visibility:visible!important;opacity:1!important;';
        return;
      }
      if ((location.hostname.indexOf('messenger.com') >= 0 || (location.hostname.indexOf('facebook.com') >= 0 && location.pathname.indexOf('/messages') >= 0))) {
        if (embedMessengerBar(bar, headerEl)) return;
      }
      // WA / IG / TG 以及 Messenger 嵌入失败时的安全回退。
      if (bar.parentElement !== document.body) document.body.appendChild(bar);
      var hRect = headerEl.getBoundingClientRect();
      if (!hRect || hRect.width <= 0 || hRect.height <= 0) return;
      var minimumWidth = Math.min(320, window.innerWidth);
      var left = Math.max(0, Math.min(hRect.left, window.innerWidth - minimumWidth));
      var availableWidth = Math.max(minimumWidth, window.innerWidth - left);
      var width = Math.min(Math.max(minimumWidth, hRect.width), availableWidth);
      var top = Math.max(0, Math.min(hRect.bottom, window.innerHeight - 48));
      bar.style.position = 'fixed';
      bar.style.top = Math.round(top) + 'px';
      bar.style.left = Math.round(left) + 'px';
      bar.style.width = Math.round(width) + 'px';
      bar.style.minWidth = minimumWidth + 'px';
      bar.style.maxWidth = '100vw';
      bar.style.right = 'auto';
      bar.style.margin = '0';
      bar.style.zIndex = '2147483646';
      bar.style.display = 'flex'; bar.style.visibility = 'visible'; bar.style.opacity = '1';
      bar.style.boxSizing = 'border-box';
    }
    try { reposition(); } catch (error) { v206ReportUiError('reposition', error); }
    if (__barRepositionHandler) {
      window.removeEventListener('resize', __barRepositionHandler);
      window.removeEventListener('scroll', __barRepositionHandler, true);
    }
    __barRepositionHandler = function () {
      try { reposition(); } catch (error) { v206ReportUiError('viewport-reposition', error); }
    };
    window.addEventListener('resize', __barRepositionHandler);
    window.addEventListener('scroll', __barRepositionHandler, true);
    if (!bar.__eventIsolated) {
      bar.__eventIsolated = true;
      ['keydown', 'keyup', 'keypress', 'input'].forEach(function (type) {
        bar.addEventListener(type, function (e) { e.stopPropagation(); });
      });
    }
  }

  // ============ 悬浮条渲染（已接入合并视图/双轨制，修复关联徽标显示） ============
  

  // ========================================================
  // v92：聊天页跨源聚合显示
  // 默认显示同电话的跨源/跨渠道聚合数据；
  // 进入编辑状态后仍只编辑当前本源当前渠道。
  // ========================================================
  function getChatRowPhoneNormV92(record, fallbackName) {
    if (!record) record = {};
    var phoneSrc = record.manualPhone || '';
    try {
      if (!phoneSrc && typeof isPhoneLikeText === 'function' && isPhoneLikeText(fallbackName || record.name)) {
        phoneSrc = fallbackName || record.name || '';
      }
    } catch (e) { }
    return normalizePhone(phoneSrc);
  }

  function getChatRowSourceIdV92(record) {
    if (!record) return getLocalSyncSourceId();
    return record.__syncSourceId || record.sourceId || record.__sourceId || getLocalSyncSourceId();
  }

  function getChatRowSourceNameV92(record) {
    if (!record) return getLocalSyncSourceName();
    return record.__syncSourceName || record.sourceName || record.__sourceName || getLocalSyncSourceName();
  }


  // ========================================================
  // v93：严格识别任何来源的小主记录 / MAIN:: 记录
  // 跨源大主记录只聚合真实渠道叶子记录，避免二次聚合导致重复。
  // ========================================================
  function isAnyMainRecordV93(id, record) {
    // v93.1 修复：只判断“记录自身是不是 MAIN 主记录”，不要因为子记录挂着 mainKey/__mainKey 就过滤。
    // 子记录通常会有 mainKey = MAIN::phone，这是正常关联标记；如果把它当主记录排除，会导致主记录区整体消失。
    var sid = String(id || '');
    var ownId = String((record && (record.__id || record.id || record._localKey || record.key)) || '');

    try { if (typeof isMainKey === 'function' && isMainKey(sid)) return true; } catch (e) {}
    try { if (ownId && typeof isMainKey === 'function' && isMainKey(ownId)) return true; } catch (e) {}

    // 兼容同步包装后的外层 key：旧同步包装键：source::MAIN::phone
    if (sid.indexOf('MAIN::') >= 0) return true;
    if (ownId.indexOf('MAIN::') >= 0) return true;

    if (!record) return false;

    // 只有明确标记为聚合/主记录的对象才排除
    try { if (record.__isCrossSourceMain) return true; } catch (e) {}
    try { if (record.__isMainRecord) return true; } catch (e) {}
    try { if (record.__isGroup) return true; } catch (e) {}
    try { if (record.__platform === 'main' || record.platform === 'main') return true; } catch (e) {}

    // 注意：不要判断 record.mainKey / record.__mainKey。
    // 它们在真实 WA/IG/FB/TG 子记录上表示“归属哪个 MAIN”，不是“自己是 MAIN”。
    return false;
  }

  function buildCrossSourceChatContextV92(channelId, info) {
    var localData = loadData();
    var panelData = getPanelDisplayData();
    var localRecord = localData[channelId] || {};
    var localPhone = getChatRowPhoneNormV92(localRecord, info && info.name);

    if (!localPhone || isAssociationBlockedV103(channelId, localPhone, getSettings(), localRecord)) {
      return {
        isCrossSourceLinked: false,
        mainKey: null,
        memberCount: 0,
        sourceCount: 0,
        members: [],
        mergedRecord: localRecord
      };
    }

    var members = [];
    Object.keys(panelData || {}).forEach(function (id) {
      var record = panelData[id];
      if (!record) return;
      if (isAnyMainRecordV93(id, record)) return;
      var norm = getChatRowPhoneNormV92(record, record.name);
      if (!norm || norm !== localPhone) return;
      if (isAssociationBlockedV103(id, norm, getSettings(), record)) return;
      var platform = inferPlatform(record, id);
      members.push(Object.assign({
        __id: id,
        __platform: platform,
        __sourceId: getChatRowSourceIdV92(record),
        __sourceName: getChatRowSourceNameV92(record),
        __fromLocalSync: !!record.__fromLocalSync
      }, record));
    });

    if (!members.length) {
      return {
        isCrossSourceLinked: false,
        mainKey: null,
        memberCount: 0,
        sourceCount: 0,
        members: [],
        mergedRecord: localRecord
      };
    }

    var sourceSet = {};
    members.forEach(function (m) {
      var sid = m.__sourceId || m.__syncSourceId || m.sourceId || 'local';
      sourceSet[sid] = true;
    });

    var mainKey = getMainKey(localPhone);
    var merged = null;
    try {
      merged = buildMainRecordFromMembers(mainKey, members, null);
    } catch (e) {
      merged = localRecord;
    }
    if (!merged) merged = localRecord;

    merged.__id = mainKey;
    merged.__platform = 'main';
    merged.__isMainRecord = true;
    merged.__isCrossSourceMain = true;
    merged.__members = members;
    merged.__memberCount = members.length;
    merged.__sourceCount = Object.keys(sourceSet).length;
    merged.manualPhone = localPhone;

    return {
      isCrossSourceLinked: members.length >= 2,
      mainKey: mainKey,
      memberCount: members.length,
      sourceCount: Object.keys(sourceSet).length,
      members: members,
      mergedRecord: merged
    };
  }

var __v2065IdentityWizardRunning = false;
  var __v2065IdentityNoticeAt = 0;
  function v2065ChannelForInfo(info) {
    info=info||{};
    if(info.platform==='fb')return location.hostname==='www.messenger.com'?'messenger':'facebook';
    return v204Channel(info);
  }
  function v2065HasSyncIdentity(info) {
    var channel=v2065ChannelForInfo(info), account=v204AccountIdentity(channel);
    return !!account;
  }
  function v2065RequireSyncIdentity(info) {
    var channel=v2065ChannelForInfo(info);
    if (v204AccountIdentity(channel)) return true;
    var now=Date.now();
    if (!__v2065IdentityWizardRunning) {
      __v2065IdentityWizardRunning=true;
      if (now-__v2065IdentityNoticeAt>1200) {
        __v2065IdentityNoticeAt=now;
        try { alert('首次写入前必须先配置【'+channel+'】同步身份。\n\n系统将打开设备、账号和来源配置；配置成功后请重新输入，本次未配置身份的数据不会写入。'); } catch(e) {}
      }
      v204ConfigureIdentityMenu(channel).then(function(result){
        if(result&&result.ok){try{showCopyToast('✅ '+channel+' 身份配置完成，请重新输入');}catch(e){} v205WakeUpload('identity-configured',0);}
      }).catch(function(error){try{alert('身份配置失败：'+String(error&&error.message||error));}catch(e){}}).finally(function(){__v2065IdentityWizardRunning=false;});
    }
    return false;
  }

  function renderNoteBar() {
    var info = getContactInfoUnified();
    if (!info || !info.headerEl) {
      // V206：SPA 切换和身份二次采样期间保留最后一个有效栏，避免界面闪退。
      var oldBar = document.getElementById(NOTE_BAR_ID);
      if (oldBar) oldBar.setAttribute('data-v206-stabilizing', '1');
      return;
    }
    __v206UiDiagnostics.renderCount += 1;

    // v120：群组与仅 LID 会话只显示隔离提示，绝不进入客户数据读写链路。
    if ((info.platform === 'wa' || info.platform === 'ig' || info.platform === 'fb' || info.platform === 'tg') && !info.writable) {
      document.querySelectorAll('#' + NOTE_BAR_ID).forEach(function (b) { b.remove(); });
      currentChatId = info.id;
      currentChatName = info.name;
      currentChatPlatform = info.platform;
      var readonlyBar = document.createElement('div');
      readonlyBar.id = NOTE_BAR_ID;
      readonlyBar.setAttribute('data-identity-readonly', '1');
      readonlyBar.setAttribute('data-identity-key', String(info.id || '') + '|' + String(info.identityStatus || '') + '|' + String(info.identityReason || ''));
      readonlyBar.style.cssText = 'display:flex;align-items:center;gap:10px;padding:8px 12px;background:#fff7ed;border-bottom:1px solid #fdba74;color:#9a3412;font-size:13px;box-sizing:border-box;';
      var readonlyText = document.createElement('span');
      readonlyText.innerHTML = '<b>' + escapeHtml(info.name || (info.platform === 'fb' ? 'Messenger 会话' : (info.platform === 'ig' ? 'Instagram 会话' : 'WhatsApp 会话'))) + '</b>　' +
        (info.readonlyReason || (info.platform === 'ig' ? '正在核验 Instagram 当前线程的数字用户 ID；核验完成前保持只读。' : (info.platform === 'fb' ? '正在核验 Messenger 当前会话；核验完成前保持只读。' : (info.platform === 'tg' ? '正在核验 Telegram 当前会话；核验完成前保持只读。' : (info.chatType === 'group' ? '当前为群组会话，已隔离客户资料读写。' : '正在核验 WhatsApp 联系人身份；核验完成前保持只读。')))));
      readonlyBar.appendChild(readonlyText);
      var readonlyPanelBtn = document.createElement('button');
      readonlyPanelBtn.textContent = '📋 面板';
      readonlyPanelBtn.style.cssText = 'border:none;background:#9a3412;color:#fff;padding:3px 10px;border-radius:4px;cursor:pointer;font-size:12px;';
      readonlyPanelBtn.addEventListener('click', openManagePanel);
      readonlyBar.appendChild(readonlyPanelBtn);
      setupBarPhysicalIsolation(readonlyBar, info.headerEl);
      return;
    }

    // v75.1：缓存 blob 头像为 dataURL，避免从其他平台打开面板时 TG/IG/FB 头像失效
    try {
      if (info && info.id && info.avatar && (info.platform !== 'fb' || canWriteFbIdentityV1218(info, info.fbWriteToken))) cacheAvatarDataUrlIfNeeded(info.id, info.avatar, info);
    } catch (e) { }

    // v43：进入/刷新聊天时同步最新联系人姓名
    syncCurrentContactName(info);

    // V206：先复用当前节点；仅在会话或显示签名确实变化时重建。
    cleanupDuplicateBars();
    var bar = document.getElementById(NOTE_BAR_ID);

    // 先执行关联扫描，再判断是否复用旧悬浮条；修复 WA 刚形成关联后仍停留旧输入界面的问题
    try { runLinkScan(); } catch (e) { }

    var ctxForReuse = resolveDisplayContext(info.id);
    var linkSignature = '';
    if (ctxForReuse.linkInfo && ctxForReuse.linkInfo.isLinked) {
      linkSignature = ctxForReuse.linkInfo.mainKey + '::' + ctxForReuse.linkInfo.memberCount + '::' + (__linkedFieldEditModeByChat[info.id] ? 'edit' : 'readonly');
    } else {
      linkSignature = 'nolink::' + (__linkedFieldEditModeByChat[info.id] ? 'edit' : 'readonly');
    }

    if (info.id === currentChatId && info.name === currentChatName && info.platform === currentChatPlatform && bar && bar.__linkSignature === linkSignature && !__linkedFieldFocusKeyByChat[info.id]) {
      setupBarPhysicalIsolation(bar, info.headerEl);
      return;
    }
    currentChatId = info.id;
    currentChatName = info.name;
    currentChatPlatform = info.platform;
    if (bar) bar.remove();

    var ctx = ctxForReuse;
    // v92：聊天页默认显示同电话的跨源/跨渠道聚合数据
    var crossChatCtx = buildCrossSourceChatContextV92(info.id, info);
    var linkInfo = ctx.linkInfo || {};
    if (crossChatCtx && crossChatCtx.isCrossSourceLinked) {
      linkInfo = Object.assign({}, linkInfo, {
        isLinked: true,
        mainKey: crossChatCtx.mainKey,
        memberCount: crossChatCtx.memberCount,
        sourceCount: crossChatCtx.sourceCount,
        members: crossChatCtx.members,
        isCrossSourceLinked: true
      });
    }
    var linkedEditMode = !!__linkedFieldEditModeByChat[info.id];
    // 非编辑状态：显示跨源聚合记录；编辑状态：只编辑当前本源当前渠道自己的记录
    var effRecord = (crossChatCtx && crossChatCtx.isCrossSourceLinked && !linkedEditMode) ? crossChatCtx.mergedRecord : ((linkInfo && linkInfo.isLinked && !linkedEditMode) ? getMergedReadonlyRecord(info.id) : (loadData()[info.id] || {}));
    // 标签/阶段默认随跨源聚合显示；进入编辑状态后仍沿用当前渠道自身操作逻辑
    var tagStageRecord = (crossChatCtx && crossChatCtx.isCrossSourceLinked && !linkedEditMode) ? crossChatCtx.mergedRecord : ctx.tagStageRecord;
    var settings = getSettings();
    var collapseKey = getCollapseKey(info.platform);
    var collapsed = !!settings[collapseKey];

    var baseInfoForSave = { id:String(info.id||''), _localKey:String(info.id||''), name:info.name, platform:info.platform, channel:v2065ChannelForInfo(info) };
    if (info.platform === 'ig') {
      baseInfoForSave.igUsername = info.username;
      baseInfoForSave.igNumericUserId = info.numericUserId;
      baseInfoForSave.igThreadId = info.threadId;
      baseInfoForSave.igIdentityStatus = info.identityStatus;
    }
    if (info.platform === 'wa') {
      baseInfoForSave.waJidAliases = info.aliases || [];
      baseInfoForSave.waIdentityStatus = info.identityStatus;
    }
    var writeTokenV120 = info.waWriteToken;
    var writeTokenIgV1212 = info.igSessionToken;
    function allowChatWriteV120() {
      var sessionOk = true;
      if (info.platform === 'wa') sessionOk = canWriteWaIdentityV120(info, writeTokenV120);
      else if (info.platform === 'ig') sessionOk = canWriteIgIdentityV1212(info, writeTokenIgV1212);
      else if (info.platform === 'fb') sessionOk = canWriteFbIdentityV1218(info, info.fbWriteToken);
      else if (info.platform === 'tg') sessionOk = !!(info.writable && info.id && info.id.indexOf('tg:') === 0);
      if (!sessionOk) return false;
      return v2065RequireSyncIdentity(info);
    }
    function blockStaleWriteV120() {
      console.warn('[V207.0.0] 已阻止未配置同步身份或未通过实时复验的会话写入', info.id);
      currentChatId = null;
      setTimeout(renderNoteBar, 0);
      return false;
    }

    bar = document.createElement('div');
    bar.id = NOTE_BAR_ID;
    bar.__linkSignature = linkSignature;
    bar.style.cssText = 'display:flex;flex-direction:column;gap:4px;padding:6px 12px 10px;background:#f0f2f5;border-bottom:1px solid #d1d7db;font-size:13px;max-height:45vh;overflow-y:auto;box-sizing:border-box;';

    var infoLine = document.createElement('div');
    infoLine.style.cssText = 'color:#54656f;line-height:1.8;margin-bottom:2px;display:flex;flex-direction:column;gap:4px;';

    var firstRow = document.createElement('div');
    firstRow.style.cssText = 'display:flex;align-items:center;flex-wrap:wrap;gap:8px;';

    var nameSpan = document.createElement('span');
    nameSpan.innerHTML = '<b>\u59d3\u540d\uff1a</b>' + escapeHtml(info.name || '\u672a\u77e5') + getPlatformBadgeHtml(info.platform);
    firstRow.appendChild(nameSpan);

    if (linkInfo && linkInfo.isLinked) {
      var linkBadge = document.createElement('span');
      if (linkInfo.isCrossSourceLinked) {
        linkBadge.textContent = '\uD83D\uDD17 已跨源关联' + linkInfo.memberCount + '条';
        linkBadge.title = '该号码已关联到 ' + linkInfo.memberCount + ' 条跨源/跨渠道记录，默认显示聚合数据；输入时只编辑当前渠道';
      } else {
        linkBadge.textContent = '\uD83D\uDD17 \u5df2\u5173\u8054' + linkInfo.memberCount + '\u6e20\u9053';
        linkBadge.title = '\u8be5\u53f7\u7801\u5df2\u5173\u8054\u5230 ' + linkInfo.memberCount + ' \u4e2a\u6e20\u9053\uff0c\u6807\u7b7e/\u9636\u6bb5\u7edf\u4e00\u7ba1\u7406';
      }
      linkBadge.style.cssText = 'background:#00a884;color:#fff;font-size:11px;padding:2px 8px;border-radius:10px;cursor:default;';
      firstRow.appendChild(linkBadge);
    }

    var phoneLabel = document.createElement('span');
    phoneLabel.innerHTML = '<b>\u7535\u8bdd\uff1a</b>';
    firstRow.appendChild(phoneLabel);

    var phoneInput = document.createElement('input');
    phoneInput.type = 'text';
    phoneInput.placeholder = '\u624b\u52a8\u8f93\u5165\u7535\u8bdd\u53f7\u7801';
    phoneInput.value = (document.activeElement === phoneInput) ? phoneInput.value : (loadData()[info.id] || {}).manualPhone || '';
    phoneInput.style.cssText = 'border:1px solid #d1d7db;border-radius:4px;padding:2px 6px;font-size:12px;width:150px;background:#fff;color:#111b21;color-scheme:light;';
    var phoneTimer = null;

    phoneInput.addEventListener('input', function () {
      clearTimeout(phoneTimer);
      phoneTimer = setTimeout(function () {
        if (!allowChatWriteV120()) { blockStaleWriteV120(); return; }
        upsertField(info.id, baseInfoForSave, 'manualPhone', phoneInput.value.trim());
        try { runLinkScan(); } catch (e) { }
        refreshPanelIfOpen();
      }, 400);
    });
    firstRow.appendChild(phoneInput);

    var secondRow = document.createElement('div');
    secondRow.style.cssText = 'display:flex;align-items:center;flex-wrap:wrap;gap:6px;';

    var toggleBtn = document.createElement('button');
    toggleBtn.textContent = collapsed ? (String.fromCharCode(0x25bc) + ' \u5c55\u5f00') : (String.fromCharCode(0x25b2) + ' \u6536\u8d77');
    toggleBtn.style.cssText = 'border:none;background:#54656f;color:#fff;padding:3px 10px;border-radius:4px;cursor:pointer;font-size:12px;';
    toggleBtn.addEventListener('click', function () {
      var s = getSettings();
      var patch = {};
      patch[collapseKey] = !s[collapseKey];
      setSettings(patch);
      currentChatId = null;
      renderNoteBar();
    });

    var panelBtn = document.createElement('button');
    panelBtn.textContent = String.fromCodePoint(0x1F4CB) + ' \u9762\u677f';
    panelBtn.style.cssText = 'border:none;background:#00a884;color:#fff;padding:3px 10px;border-radius:4px;cursor:pointer;font-size:12px;';
    panelBtn.addEventListener('click', openManagePanel);

    secondRow.appendChild(toggleBtn);
    secondRow.appendChild(panelBtn);
    var syncCompact = document.createElement('span');
    syncCompact.id = 'wa-v205-compact-status';
    syncCompact.style.cssText = 'display:inline-flex;align-items:center;gap:3px;padding:3px 8px;border:1px solid #cbd5e1;border-radius:999px;background:#fff;color:#334155;font-size:11px;cursor:pointer;white-space:nowrap;';
    syncCompact.addEventListener('click', openManagePanel);
    secondRow.appendChild(syncCompact);
    setTimeout(v205RenderCompactStatus, 0);

    if (linkInfo && linkInfo.isLinked) {
      var editBtn = document.createElement('button');
      editBtn.textContent = linkedEditMode ? (String.fromCodePoint(0x2705) + ' 完成') : (String.fromCodePoint(0x270F) + ' 输入');
      editBtn.title = linkedEditMode ? '点击后返回关联聚合只读显示' : '点击后输入/编辑当前渠道自己的备注字段';
      editBtn.style.cssText = 'border:none;background:' + (linkedEditMode ? '#00a884' : '#5c6bc0') + ';color:#fff;padding:3px 10px;border-radius:4px;cursor:pointer;font-size:12px;';
      editBtn.addEventListener('click', function () {
        if (linkedEditMode) {
          // 完成：保存当前正在编辑的字段，然后返回聚合只读显示
          var active = document.activeElement;
          if (active && active.__waLinkedFieldKey) {
            try {
              if (!allowChatWriteV120()) { blockStaleWriteV120(); return; }
              upsertFieldSmart(info.id, baseInfoForSave, active.__waLinkedFieldKey, active.value);
              refreshPanelIfOpen();
            } catch (e) { }
          }
          __linkedFieldEditModeByChat[info.id] = false;
        } else {
          __linkedFieldEditModeByChat[info.id] = true;
        }
        delete __linkedFieldFocusKeyByChat[info.id];
        currentChatId = null;
        renderNoteBar();
      });
      secondRow.appendChild(editBtn);
    }

    var tagSelect = document.createElement('select');
    var curTagVal = tagStageRecord.tag || '';
    var curTagColor = getTag1Color(curTagVal);
    tagSelect.style.cssText = 'border:1px solid #d1d7db;border-radius:4px;padding:2px 4px;font-size:12px;width:96px;cursor:pointer;font-weight:600;background:' + (curTagVal ? curTagColor : '#fff') + ';color:' + (curTagVal ? '#fff' : '#111b21') + ';';
    getTags1().forEach(function (t) {
      var opt = document.createElement('option');
      opt.value = t.key;
      opt.textContent = t.label;
      opt.style.background = '#fff';
      opt.style.color = '#111b21';
      if (curTagVal === t.key) opt.selected = true;
      tagSelect.appendChild(opt);
    });
    tagSelect.addEventListener('change', function () {
      var cColor = getTag1Color(tagSelect.value);
      if (tagSelect.value) {
        tagSelect.style.background = cColor;
        tagSelect.style.color = '#fff';
      } else {
        tagSelect.style.background = '#fff';
        tagSelect.style.color = '#111b21';
      }
      if (!allowChatWriteV120()) { blockStaleWriteV120(); return; }
      upsertTagSmart(info.id, baseInfoForSave, tagSelect.value);
      refreshPanelIfOpen();
    });
    secondRow.appendChild(tagSelect);

    // v56：前端悬浮备注栏打通画像选择与显示
    var frontTag2Wrap = document.createElement('div');
    frontTag2Wrap.style.cssText = 'display:inline-flex;align-items:center;position:relative;vertical-align:middle;';
    var curFrontT2 = Array.isArray(tagStageRecord.tag2) ? tagStageRecord.tag2 : (tagStageRecord.tag2 ? [tagStageRecord.tag2] : []);
    var allT2List = getTags2();
    var frontTag2Btn = document.createElement('div');
    frontTag2Btn.style.cssText = 'display:inline-flex;align-items:center;gap:3px;cursor:pointer;padding:2px 6px;border-radius:4px;border:1px dashed #bbb;background:#fff;font-size:11px;user-select:none;min-height:18px;box-sizing:border-box;';
    frontTag2Btn.title = '点击设置联系人画像(多选)';
    if (!curFrontT2.length) {
      frontTag2Btn.innerHTML = '<span style="color:#54656f;">+画像</span>';
    } else {
      var bHtml = '';
      curFrontT2.forEach(function (k) {
        var def = allT2List.filter(function(x){ return x.key === k; })[0];
        var bg = def ? def.color : '#78909c';
        var lbl = def ? def.label : k;
        bHtml += '<span style="display:inline-block;padding:1px 5px;border-radius:10px;font-size:10px;color:#fff;background:' + bg + ';white-space:nowrap;line-height:1.2;">' + escapeHtml(lbl) + '</span>';
      });
      frontTag2Btn.innerHTML = bHtml;
    }
    frontTag2Btn.addEventListener('click', function (ev) {
      ev.stopPropagation();
      showTag2SelectDropdown(window, ev, info.id, curFrontT2, function (newTags) {
        if (!allowChatWriteV120()) { blockStaleWriteV120(); return; }
        upsertTag2Smart(info.id, newTags);
        currentChatId = null;
        renderNoteBar();
        refreshPanelIfOpen();
      });
    });
    frontTag2Wrap.appendChild(frontTag2Btn);
    secondRow.appendChild(frontTag2Wrap);

    var savedStages = Array.isArray(tagStageRecord.stages) ? tagStageRecord.stages : [];
    STAGES.forEach(function (st) {
      var lbl = document.createElement('label');
      lbl.style.cssText = 'display:flex;align-items:center;gap:3px;font-size:12px;color:#111b21;cursor:pointer;background:#fff;border:1px solid #d1d7db;border-radius:4px;padding:2px 8px;';
      var cb = createCustomCheckbox(savedStages.indexOf(st.key) >= 0, function (checked) {
        if (!allowChatWriteV120()) { blockStaleWriteV120(); return; }
        toggleStageSmart(info.id, st.key, checked);
        refreshPanelIfOpen();
      }, 14);
      lbl.appendChild(cb);
      var txt = document.createElement('span');
      txt.textContent = getStageLabel(st.key);
      lbl.appendChild(txt);
      secondRow.appendChild(lbl);
    });

    infoLine.appendChild(firstRow);
    infoLine.appendChild(secondRow);
    bar.appendChild(infoLine);

    if (!collapsed) {
      getAllFieldDefinitionsV126(false).forEach(function (field) {
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:flex-start;gap:6px;';

        var label = document.createElement('div');
        label.textContent = getFieldLabel(field.key);
        label.style.cssText = 'flex:0 0 80px;color:#111b21;font-weight:600;line-height:1.4;padding-top:4px;white-space:nowrap;';

        var textarea = document.createElement('textarea');
        textarea.value = effRecord[field.key] || '';
        textarea.rows = 1;

        var isLinkedReadonly = !!(linkInfo && linkInfo.isLinked && !linkedEditMode);
        textarea.readOnly = isLinkedReadonly;
        if (isLinkedReadonly) textarea.setAttribute('readonly', 'readonly');
        else textarea.removeAttribute('readonly');

        textarea.placeholder = isLinkedReadonly ? '双击可输入当前渠道内容' : '\u8f93\u5165\u5185\u5bb9...';
        textarea.style.cssText = 'flex:1;resize:none;overflow:hidden;min-height:20px;max-height:150px;border:1px solid #d1d7db;border-radius:6px;padding:4px 8px;font-size:13px;line-height:1.4;background:' + (isLinkedReadonly ? '#f7f8fa' : '#fff') + ';color:#111b21;box-sizing:border-box;cursor:' + (isLinkedReadonly ? 'pointer' : 'text') + ';';

        if (isLinkedReadonly) {
          textarea.title = '双击后输入/编辑当前渠道自己的内容';
          textarea.addEventListener('dblclick', function () {
            __linkedFieldEditModeByChat[info.id] = true;
            __linkedFieldFocusKeyByChat[info.id] = field.key;
            currentChatId = null;
            renderNoteBar();
          });
        }

        var saveTimer = null;
        function finishLinkedFieldEdit(shouldSave) {
          if (textarea.__waFinishing) return;
          textarea.__waFinishing = true;
          clearTimeout(saveTimer);
          if (shouldSave !== false) {
            if (!allowChatWriteV120()) { blockStaleWriteV120(); return; }
            upsertFieldSmart(info.id, baseInfoForSave, field.key, textarea.value);
            refreshPanelIfOpen();
          }
          if (linkInfo && linkInfo.isLinked) {
            __linkedFieldEditModeByChat[info.id] = false;
            delete __linkedFieldFocusKeyByChat[info.id];
            currentChatId = null;
            setTimeout(function () { renderNoteBar(); }, 0);
          }
        }
        if (!isLinkedReadonly) {
          textarea.__waLinkedFieldKey = field.key;
          textarea.addEventListener('input', function () {
            autoResize(textarea);
            // 输入中只自动保存草稿，不自动切回只读，避免 0.3 秒过快打断输入
            clearTimeout(saveTimer);
            saveTimer = setTimeout(function () {
              if (!allowChatWriteV120()) { blockStaleWriteV120(); return; }
            upsertFieldSmart(info.id, baseInfoForSave, field.key, textarea.value);
              refreshPanelIfOpen();
            }, 500);
          });
          textarea.addEventListener('keydown', function (e) {
            // Enter 保存并完成；Shift+Enter 保留为换行；Esc 取消并回到只读
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              finishLinkedFieldEdit(true);
            } else if (e.key === 'Escape') {
              e.preventDefault();
              finishLinkedFieldEdit(false);
            }
          });
          textarea.addEventListener('blur', function () {
            // 离开输入框后保存并返回只读
            finishLinkedFieldEdit(true);
          });
        }

        if (!isLinkedReadonly && __linkedFieldFocusKeyByChat[info.id] === field.key) {
          requestAnimationFrame(function () {
            try {
              textarea.focus();
              textarea.selectionStart = textarea.selectionEnd = textarea.value.length;
              autoResize(textarea);
            } catch (e) { }
            delete __linkedFieldFocusKeyByChat[info.id];
          });
        }

        row.appendChild(label);
        row.appendChild(textarea);
        bar.appendChild(row);
        requestAnimationFrame(function () { autoResize(textarea); });
      });
    }

    setupBarPhysicalIsolation(bar, info.headerEl);
  }

  // ============ 表格列定义 ============
  
  // === v64.0 视口计算与横滚保底参数 ===
  var MIN_FIELD_CHARS = 10;      // v72.3：1-说明九列每列最小汉字数（用户可设置）
  var CHAR_WIDTH_PX = 14;        // v72：中文字符基准宽度像素
  var FIELD_CELL_PADDING_PX = 12; // v72.3：单元格左右缓冲，降低4字宽度时过早横滚

  var FLEX_KEYS = [];
  var COLUMNS = [];
  function isFlexCol(key) { return FLEX_KEYS.indexOf(key) >= 0; }
  function rebuildColumnsV126() {
    var af=getAllFieldDefinitionsV126(false);
    FLEX_KEYS=af.map(function(f){return f.key;});
    COLUMNS=[
      { key:'__index',label:'#',width:36,minWidth:36,resizable:false },{ key:'__chk',label:'',width:34,minWidth:34,resizable:false },
      { key:'__source',label:'来源',width:120,minWidth:70,resizable:true },{ key:'__platform',label:'渠道',width:74,minWidth:50,resizable:true },
      { key:'__link',label:'关联',width:80,minWidth:50,resizable:true },{ key:'__id',label:'识别码',width:130,minWidth:80,resizable:true },
      { key:'__avatar',label:'头像',width:56,minWidth:46,resizable:true },{ key:'name',label:'姓名',width:120,minWidth:70,resizable:true },
      { key:'manualPhone',label:'电话',width:140,minWidth:80,resizable:true },{ key:'tag',label:'标签',width:110,minWidth:80,resizable:true },
      { key:'tag2',label:'画像',width:140,minWidth:90,resizable:true },{ key:'__stages',label:'跟进阶段',width:150,minWidth:100,resizable:true }
    ].concat(af.map(function(f){return {key:f.key,label:f.label,width:(f.type==='textarea'||f.key==='remark'?180:140),minWidth:80,resizable:true,fieldType:f.type,dynamic:!!f.dynamic};})).concat([
      { key:'updatedAt',label:'更新时间',width:110,minWidth:80,resizable:true },{ key:'__actions',label:'操作',width:90,minWidth:90,resizable:false }
    ]);
  }
  rebuildColumnsV126();
  function getColWidths() {
    var s = getSettings();
    return s.tableColWidths || {};
  }
  function saveColWidth(key, width) {
    var s = getSettings();
    var map = Object.assign({}, s.tableColWidths || {});
    map[key] = width;
    setSettings({ tableColWidths: map });
  }
  function getFieldColWeights() {
    var s = getSettings();
    return s.fieldColWeights || {};
  }
  function saveFieldColWeight(key, weight) {
    var s = getSettings();
    var map = Object.assign({}, s.fieldColWeights || {});
    map[key] = Math.max(0.45, Math.min(5, weight || 1));
    setSettings({ fieldColWeights: map });
  }
  function calcFieldContentScore(rows, key) {
    var maxLen = 0, sum = 0, count = 0;
    (rows || []).slice(0, 200).forEach(function (r) {
      var text = String((r && (r[key] || (r.raw && r.raw[key]))) || '').trim();
      if (!text) return;
      var len = text.replace(/\s+/g, '').length;
      maxLen = Math.max(maxLen, len);
      sum += len; count++;
    });
    var avg = count ? sum / count : 0;
    return Math.min(3, Math.log(1 + maxLen + avg) / 3);
  }
  function getFieldColLocked() {
    var s = getSettings();
    return s.fieldColLocked || {};
  }
  function setFieldColLocked(key, lockedVal) {
    var s = getSettings();
    var map = Object.assign({}, s.fieldColLocked || {});
    map[key] = !!lockedVal;
    setSettings({ fieldColLocked: map });
  }
  function toggleFieldColLocked(key) {
    var locked = getFieldColLocked();
    setFieldColLocked(key, !locked[key]);
  }
  function getLayoutMinViewportWidth() {
    var s = getSettings();
    return Math.max(800, parseInt(s.layoutMinViewportWidth || 1280, 10) || 1280);
  }
  function getFieldUnifiedWidthPx() {
    var s = getSettings();
    var raw = s.fieldUnifiedWidthPx;
    if (raw === undefined || raw === null || raw === '') raw = 220;
    var n = parseInt(raw, 10) || 220;
    return Math.max(60, Math.min(1200, n));
  }
  function isFieldUnifiedWidthAuto() {
    var s = getSettings();
    if (typeof s.fieldUnifiedWidthAuto === 'boolean') return s.fieldUnifiedWidthAuto;
    // 兼容 v75.4：旧设置为0/空时默认自适应；旧设置大于0时默认手动统一宽度。
    var old = parseInt(s.fieldUnifiedWidthPx || 0, 10) || 0;
    return old <= 0;
  }
  function calcAdaptiveFieldWidths(rows, containerWidth, widths) {
    // v75.5：新增“自适应”开关。勾选时忽略统一宽度；不勾选时按统一px宽度撑开9列并触发横滚。
    var unifiedW = getFieldUnifiedWidthPx();
    if (!isFieldUnifiedWidthAuto() && unifiedW > 0) {
      var fixedResult = {};
      FLEX_KEYS.forEach(function (k) { fixedResult[k] = unifiedW; });
      var viewportW0 = (managePanelWindow && managePanelWindow.innerWidth) || containerWidth || 1200;
      var minViewport0 = getLayoutMinViewportWidth();
      if (managePanelWindow) managePanelWindow.__v724LastLayoutWidth = Math.max(viewportW0, minViewport0);
      return fixedResult;
    }
    // v72.4：极简列宽模型
    // 1) 非说明区列使用固定/手动拖拽宽度；
    // 2) 说明区9列中，🔒列使用保存宽度，🔓列平均瓜分剩余宽度；
    // 3) 当前浏览器宽度低于“横滚触发宽度”时，按触发宽度布局，自然出现横向滚动。
    var viewportW = (managePanelWindow && managePanelWindow.innerWidth) || containerWidth || 1200;
    var minViewport = getLayoutMinViewportWidth();
    var layoutWidth = Math.max(viewportW, minViewport);
    var locked = getFieldColLocked();
    var result = {};

    var fixedTotal = 0;
    COLUMNS.forEach(function (c) {
      if (!isFlexCol(c.key)) {
        fixedTotal += parseInt((widths && widths[c.key]) || c.width || c.minWidth || 80, 10);
      }
    });

    var lockedTotal = 0;
    var freeKeys = [];
    FLEX_KEYS.forEach(function (k) {
      if (locked[k]) {
        var savedW = parseInt((widths && widths[k]) || 120, 10) || 120;
        result[k] = savedW;
        lockedTotal += savedW;
      } else {
        freeKeys.push(k);
      }
    });

    var safe = 64;
    var freeWidth = layoutWidth - fixedTotal - lockedTotal - safe;
    var each = freeKeys.length ? Math.max(60, Math.floor(freeWidth / freeKeys.length)) : 0;
    freeKeys.forEach(function (k) { result[k] = each; });

    if (managePanelWindow) managePanelWindow.__v724LastLayoutWidth = layoutWidth;
    return result;
  }
  function saveFieldDragAsWeight(key, actualWidth) {
    // v72.4：拖拽说明区列后保存实际宽度；是否固定由表头锁按钮控制
    saveColWidth(key, actualWidth);
  }
  function resetColWidths() {
    setSettings({ tableColWidths: {}, fieldColWeights: {}, fieldColLocked: {} });
  }

  function refreshPanelIfOpen() {
    if (managePanelWindow && !managePanelWindow.closed && managePanelWindow.__waRefresh) {
      try { managePanelWindow.__waRefresh(); } catch (e) { }
    }
  }

  // === v73.0 主记录聚合实时刷新：编辑子记录后重算 MAIN 并刷新管理面板 ===
  var __waV73LinkScanRefreshTimer = null;

  function scheduleLinkScanAndPanelRefresh(delay) {
    delay = typeof delay === 'number' ? delay : 120;
    if (__waV73LinkScanRefreshTimer) {
      clearTimeout(__waV73LinkScanRefreshTimer);
    }
    __waV73LinkScanRefreshTimer = setTimeout(function () {
      __waV73LinkScanRefreshTimer = null;
      try { runLinkScan(); } catch (e) { }
      try { refreshPanelIfOpen(); } catch (e) { }
    }, delay);
  }

  function runLinkScanAndRefreshPanelNow() {
    if (__waV73LinkScanRefreshTimer) {
      clearTimeout(__waV73LinkScanRefreshTimer);
      __waV73LinkScanRefreshTimer = null;
    }
    try { runLinkScan(); } catch (e) { }
    try { refreshPanelIfOpen(); } catch (e) { }
  }

  function buildManagePanelShell() {
    var html = '';
    html += '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="UTF-8">\n<title>聚宝盆客户信息管理系统</title>\n<style>\n';
    html += '*{box-sizing:border-box;}\n';
    html += ':root{--bg:#f0f2f5;--card:#fff;--text:#111b21;--sub:#54656f;--border:#d9dee3;--fieldbg:#fafafa;--empty:#fff0f0;--headbg:#eef1f4;}\n';
    html += 'body.dark{--bg:#0b141a;--card:#1f2c34;--text:#e9edef;--sub:#8696a0;--border:#2a3942;--fieldbg:#111b21;--empty:#3a1f22;--headbg:#233138;}\n';
    html += 'body{margin:0;padding:18px 20px;background:var(--bg);color:var(--text);font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;}\n';
    html += '.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px;}\n';
    html += '.toolbar h1{font-size:18px;margin:0 0 6px;flex:1 0 100%;}\n';
    html += '.wa-fortune-title{display:inline-flex!important;align-items:center!important;gap:9px!important;width:auto!important;flex:0 0 auto!important;padding:7px 14px!important;border:1px solid #d7a51e!important;border-radius:12px!important;background:linear-gradient(135deg,#65150f 0%,#9d2418 52%,#64120d 100%)!important;color:#ffe9a1!important;box-shadow:0 3px 10px rgba(126,31,18,.24),inset 0 1px 0 rgba(255,239,169,.24)!important;text-shadow:0 1px 1px rgba(65,12,7,.85)!important;letter-spacing:.5px!important;}\n';
    html += '.wa-fortune-title-text{font-weight:800;white-space:nowrap;}\n';
    html += '.wa-fortune-ingot{position:relative;display:inline-block;flex:0 0 auto;width:25px;height:15px;border:1px solid #b87500;border-radius:52% 52% 42% 42%;background:linear-gradient(180deg,#fff4a8 0%,#ffd34d 38%,#dc8b00 100%);box-shadow:inset 0 -2px 2px rgba(128,66,0,.28),0 1px 3px rgba(82,29,0,.35);transform:translateY(1px);overflow:hidden;}\n';
    html += '.wa-fortune-ingot:before{content:"";position:absolute;left:5px;right:5px;top:-1px;height:7px;border:1px solid #c78300;border-radius:50%;background:linear-gradient(180deg,#fff8bd,#ffc72d);box-shadow:inset 0 1px 1px rgba(255,255,255,.8);}.wa-fortune-ingot:after{content:"";position:absolute;left:2px;right:2px;bottom:1px;height:3px;border-radius:50%;background:rgba(255,238,130,.55);}\n';
    html += 'body.dark .wa-fortune-title{border-color:#e8b93b!important;box-shadow:0 3px 12px rgba(0,0,0,.4),inset 0 1px 0 rgba(255,239,169,.2)!important;}\n';
    html += 'input[type="text"]{padding:7px 12px;border:1px solid var(--border);border-radius:6px;font-size:13px;background:var(--card);color:var(--text);}\n';
    html += '#searchBox{width:200px;}\n';
    html += 'select{padding:6px 10px;border:1px solid var(--border);border-radius:6px;font-size:13px;background:var(--card);color:var(--text);}\n';
    html += '.btn{border:none;padding:7px 14px;border-radius:6px;cursor:pointer;font-size:13px;color:#fff;background:#00a884;}\n';
    html += '.btn.secondary{background:#54656f;}\n.btn.ghost{background:transparent;color:var(--text);border:1px solid var(--border);}\n.btn.danger{background:#e53935;}\n';
    html += '.btn:disabled{opacity:0.4;cursor:not-allowed;}\n';
    html += '.banner{background:#fff3cd;border:1px solid #ffe69c;color:#664d03;padding:10px 14px;border-radius:8px;margin-bottom:12px;font-size:13px;display:flex;justify-content:space-between;align-items:center;}\n';
    html += '.stats{font-size:13px;color:var(--sub);margin-bottom:10px;}\n.stats b{color:var(--text);}\n';
    html += '.platformbar,.tagbar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;}\n';
    html += '.platpill,.tagpill{border-radius:14px;padding:5px 14px;font-size:12px;cursor:pointer;color:#fff;display:flex;align-items:center;gap:6px;border:2px solid transparent;user-select:none;font-weight:600;}\n';
   // ✅ 修复后的标准代码：
    html += '.platpill.active,.tagpill.active{box-shadow:0 0 0 2px #fff,0 0 0 4.5px #00a884 !important;transform:scale(1.05);font-weight:700;z-index:10;}\n';
    html += '.platpill.active::before,.tagpill.active::before{content:\'✓ \';font-weight:900;}\n';
    html += 'body.dark .platpill.active,body.dark .tagpill.active{box-shadow:0 0 0 2px #1f2c34,0 0 0 4.5px #00a884 !important;}\n';

    html += '.batchbar{display:none;align-items:center;gap:8px;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:8px 12px;margin-bottom:10px;font-size:13px;}\n';
    html += '.batchbar.show{display:flex;}\n';
    html += '.dashboard{background:var(--card);border-radius:10px;padding:16px 20px;margin-bottom:14px;border:1px solid var(--border);display:none;}\n';
    html += '.dashboard.show{display:block;}\n.dash-row{margin-bottom:12px;}\n.dash-title{font-weight:700;font-size:13px;margin-bottom:6px;}\n';
    html += '.bar-item{display:flex;align-items:center;gap:8px;margin-bottom:4px;font-size:12px;}\n';
    html += '.bar-label{flex:0 0 110px;color:var(--sub);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}\n';
    html += '.bar-track{flex:1;height:14px;background:var(--fieldbg);border-radius:7px;overflow:hidden;}\n';
    html += '.bar-fill{height:100%;border-radius:7px;}\n.bar-val{flex:0 0 40px;text-align:right;color:var(--sub);}\n';
    html += '.main-group-section{background:var(--card);border:1.5px solid #6d4c41;border-radius:8px;margin-bottom:14px;overflow:hidden;display:none;box-shadow:0 2px 8px rgba(109,76,65,0.1);}\n';
html += '.main-group-header{display:flex;justify-content:space-between;align-items:center;padding:10px 14px;background:rgba(109,76,65,0.08);border-bottom:1px solid var(--border);cursor:pointer;user-select:none;}\n';
html += '.main-group-header h3{margin:0;font-size:14px;color:#6d4c41;display:flex;align-items:center;}\n';
html += '.main-group-table-container{overflow:auto;max-height:38vh;scrollbar-width:none;-ms-overflow-style:none;}\n';
    html += '.main-group-table-container::-webkit-scrollbar{width:0 !important;height:0 !important;display:none !important;}\n';
    html += '.main-group-table-container td{white-space:normal !important;word-break:break-word;}\n';
    html += '.main-group-table-container textarea.cell-input{white-space:pre-wrap !important;word-break:break-word;overflow:hidden;min-height:32px;}\n';
    html += '.sub-table-header{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;background:var(--headbg);border:1px solid var(--border);border-bottom:none;border-radius:8px 8px 0 0;margin-top:10px;}\n';
    html += '.sub-table-header h3{margin:0;font-size:14px;color:var(--text);display:flex;align-items:center;}\n';
    html += '.sub-table-header{gap:10px;flex-wrap:wrap;}\n';
    html += '.sub-table-cfg{display:inline-flex;align-items:center;gap:8px;font-size:12px;color:var(--text);background:var(--card);padding:3px 10px;border-radius:6px;border:1px solid var(--border);margin-left:auto;}\n';
    html += '.sub-table-cfg input{width:50px;padding:2px 4px;text-align:center;border:1px solid var(--border);border-radius:4px;background:var(--bg);color:var(--text);font-size:12px;}\n';
    html += '#mainTable,#mainGroupTable{table-layout:fixed !important;}\n';
    html += '#mainTable thead th,#mainGroupTable thead th{position:sticky !important;top:0 !important;z-index:30 !important;background:var(--headbg) !important;}\n';
    html += '#mainTable .col-sticky-avatar,#mainGroupTable .col-sticky-avatar{position:sticky !important;left:0 !important;z-index:16 !important;background:var(--card) !important;background-clip:padding-box !important;}\n';
    html += '#mainTable .col-sticky-name,#mainGroupTable .col-sticky-name{position:sticky !important;left:var(--v67-avatar-width,56px) !important;z-index:17 !important;background:var(--card) !important;background-clip:padding-box !important;}\n';
    html += '#mainTable thead th.col-sticky-avatar,#mainGroupTable thead th.col-sticky-avatar{z-index:50 !important;background:var(--headbg) !important;}\n';
    html += '#mainTable thead th.col-sticky-name,#mainGroupTable thead th.col-sticky-name{z-index:51 !important;background:var(--headbg) !important;}\n';
    html += 'body.dark #mainTable .col-sticky-avatar,body.dark #mainTable .col-sticky-name,body.dark #mainGroupTable .col-sticky-avatar,body.dark #mainGroupTable .col-sticky-name{background:var(--card) !important;}\n';
    html += '#waViewportBottomBar{position:fixed;left:0;right:0;bottom:0;height:16px;overflow-x:auto;overflow-y:hidden;background:rgba(240,242,245,.96);border-top:1px solid var(--border);z-index:999999;display:none;}\n';
    html += 'body.dark #waViewportBottomBar{background:rgba(11,20,26,.96);}\n';
    html += '#waViewportBottomBarInner{height:1px;}\n';

html += '.cell-readonly{background:var(--fieldbg) !important;color:var(--sub) !important;cursor:not-allowed !important;}\n';
html += '.table-container{background:var(--card);border:1px solid var(--border);border-radius:8px;overflow:auto;max-height:72vh;position:relative;}\n';
    html += '.table-scroll-clip{overflow:hidden;border:1px solid var(--border);border-top:0;border-radius:0 0 8px 8px;background:var(--card);position:relative;}\n';
    html += '.table-scroll-clip .table-container{border:0 !important;border-radius:0 !important;margin-bottom:-18px !important;padding-bottom:18px !important;padding-right:22px !important;box-sizing:border-box !important;}\n';
    html += '.table-scroll-clip .table-container table{margin-right:22px !important;}\n';
    html += '#mainGroupContainer{padding-right:22px !important;box-sizing:border-box !important;}\n';
    html += '#mainGroupContainer table{margin-right:22px !important;}\n';

    html += '.table-container::-webkit-scrollbar:horizontal{height:0 !important;display:none !important;}\n';
    html += 'table{border-collapse:separate;border-spacing:0;table-layout:fixed;width:100%;min-width:100%;}\n';
    html += 'thead th{position:sticky;top:0;background:var(--headbg);z-index:3;font-size:12px;font-weight:700;text-align:left;padding:8px 8px;border-bottom:2px solid var(--border);border-right:1px solid var(--border);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;box-sizing:border-box;height:36px;}\n';
    html += 'th .resize-handle{position:absolute;top:0;right:-4px;width:8px;height:100%;cursor:col-resize;z-index:6;}\n';
    html += 'th .resize-handle:hover, th .resize-handle.dragging{background:rgba(0,168,132,0.5);}\n';
    html += 'td{padding:6px 8px;border-bottom:1px solid var(--border);border-right:1px solid var(--border);font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;box-sizing:border-box;position:relative;vertical-align:top;}\n';
    html += '.wrap-mode td{white-space:normal;word-break:break-word;}\n';
    html += '.wrap-mode textarea.cell-input{white-space:pre-wrap;word-break:break-word;}\n';
    html += 'tr.row-wa td:first-child{box-shadow:inset 4px 0 0 0 #25D366;}\n';
    html += 'tr.row-ig td:first-child{box-shadow:inset 4px 0 0 0 #E1306C;}\n';
    html += 'tr.row-fb td:first-child{box-shadow:inset 4px 0 0 0 #0084FF;}\n';
    html += 'tr.row-tg td:first-child{box-shadow:inset 4px 0 0 0 #26A5E4;}\n';
    html += 'tr.row-multi td:first-child{box-shadow:inset 4px 0 0 0 #6d4c41;}\n';
    html += 'tr.row-multi{background:rgba(109,76,65,0.06);}\n';
    html += 'body.dark tr.row-multi{background:rgba(109,76,65,0.18);}\n';
    html += '.plat-badge{display:inline-flex;align-items:center;justify-content:center;box-sizing:border-box;min-width:28px;max-width:100%;height:20px;padding:1px 6px;border-radius:10px;font-family:inherit;font-size:10px!important;line-height:1!important;letter-spacing:0;font-weight:700;color:#fff;white-space:nowrap!important;word-break:normal!important;overflow:hidden;text-overflow:ellipsis;vertical-align:middle;}\n';
    html += 'tr:hover td{filter:brightness(0.96);}\nbody.dark tr:hover td{filter:brightness(1.15);}\n';
    html += 'td.cell-empty{background:var(--empty) !important;}\n';
    html += 'input.cell-input, textarea.cell-input{width:100%;box-sizing:border-box;border:none;outline:none;background:transparent;color:var(--text);font-size:13px;font-family:inherit;padding:6px 8px;margin:0;resize:none;line-height:1.4;display:block;}\n';
    html += 'textarea.cell-input{overflow:hidden;min-height:32px;}\n';
    html += 'input.cell-input:focus, textarea.cell-input:focus{background:var(--card);box-shadow:inset 0 0 0 1px #00a884;border-radius:3px;}\n';
    html += 'td.input-td{padding:0;}\n';
    html += 'td.cell-empty input.cell-input, td.cell-empty textarea.cell-input{color:var(--sub);}\n';
    html += '.tag-sel-inline{width:100%;border:1px solid var(--border);border-radius:4px;padding:2px 4px;font-size:12px;background:var(--card);color:var(--text);}\n';
    html += '.icon-btn{border:none;background:none;cursor:pointer;font-size:14px;padding:2px 4px;}\n';
    html += '.link-btn{border:1px solid #6d4c41;background:#6d4c41;color:#fff;border-radius:6px;padding:3px 8px;font-size:11px;cursor:pointer;white-space:nowrap;}\n';
    html += '.id-cell{white-space:nowrap;}\n';
    html += '.chk-wrap-th{display:flex;align-items:center;justify-content:center;height:100%;}\n';
    html += '#dropZone{position:fixed;inset:0;background:rgba(0,168,132,0.15);border:4px dashed #00a884;z-index:999;display:none;align-items:center;justify-content:center;font-size:22px;color:#00a884;font-weight:700;}\n';
    html += '.row-highlight-pulse{animation:pulseGlow 2.5s ease-in-out;}\n@keyframes pulseGlow{0%{background-color:rgba(0,168,132,0.45) !important;}50%{background-color:rgba(0,168,132,0.2) !important;}100%{background-color:transparent;}}\n.link-group-bg-0{background-color:rgba(37,211,102,0.06) !important;}\n.link-group-bg-1{background-color:rgba(0,132,255,0.06) !important;}\n.link-group-bg-2{background-color:rgba(225,48,108,0.06) !important;}\n.link-group-bg-3{background-color:rgba(109,76,65,0.08) !important;}\n.link-group-bg-4{background-color:rgba(156,39,176,0.06) !important;}\nbody.dark .link-group-bg-0{background-color:rgba(37,211,102,0.14) !important;}\nbody.dark .link-group-bg-1{background-color:rgba(0,132,255,0.14) !important;}\nbody.dark .link-group-bg-2{background-color:rgba(225,48,108,0.14) !important;}\nbody.dark .link-group-bg-3{background-color:rgba(109,76,65,0.2) !important;}\nbody.dark .link-group-bg-4{background-color:rgba(156,39,176,0.14) !important;}\n.lg-act-btn{border:none;border-radius:4px;padding:2px 6px;font-size:11px;cursor:pointer;margin:1px;white-space:nowrap;line-height:1.2;}\n.lg-act-toggle{background:#5c6bc0;color:#fff;}\n.lg-act-unlink{background:#e53935;color:#fff;}\n</style>\n</head>\n<body>\n';
    html += '<div id="dropZone">\u62d6\u653e CSV \u6587\u4ef6\u5230\u6b64\u5904\u5bfc\u5165</div>\n';
    html += '<div class="toolbar">\n<div class="wa-panel-title-line">\n<h1 class="wa-fortune-title"><span class="wa-fortune-ingot" aria-hidden="true"></span><span class="wa-fortune-title-text">聚宝盆客户信息管理系统</span><span class="wa-fortune-ingot" aria-hidden="true"></span></h1>\n';
    html += '<button class="btn ghost" id="darkBtn">' + String.fromCodePoint(0x1F319) + ' \u6df1\u8272\u6a21\u5f0f</button>\n';
    html += '<button class="btn secondary" id="exportBtn">' + String.fromCodePoint(0x2B07) + String.fromCodePoint(0xFE0F) + ' \u5bfc\u51faCSV</button>\n';
    html += '<button class="btn secondary" id="excelExportBtn">' + String.fromCodePoint(0x1F4CA) + ' 导出Excel</button>\n';
    html += '<button class="btn secondary" id="importBtn">' + String.fromCodePoint(0x2B06) + String.fromCodePoint(0xFE0F) + ' \u5bfc\u5165CSV</button>\n';
    html += '</div>\n';
    html += '<input type="text" id="searchBox" placeholder="\u641c\u7d22\u59d3\u540d/\u7535\u8bdd/\u5907\u6ce8...">\n';
    html += '<select id="sourceFilter" title="来源筛选"></select>\n';
    html += '<label id="remoteEditToggleLabel" style="display:inline-flex;align-items:center;gap:4px;font-size:12px;color:var(--text,#111b21);white-space:nowrap;cursor:pointer;" title="开启后，他源汇总数据可在本面板直接编辑/删除（保存到服务端覆盖层，不被来源浏览器快照覆盖）；关闭则恢复他源只读。"><input type="checkbox" id="remoteEditToggle" style="width:14px;height:14px;cursor:pointer;"> 他源可编辑</label>\n';
    html += '<select id="sortSelect"><optgroup label="时间"><option value="updatedAt_desc">按更新时间 ↓</option><option value="updatedAt_asc">按更新时间 ↑</option></optgroup><optgroup label="名称"><option value="name_asc">按姓名 A-Z</option><option value="name_desc">按姓名 Z-A</option></optgroup><optgroup label="来源与渠道"><option value="source_asc">按来源 A-Z</option><option value="source_desc">按来源 Z-A</option><option value="platform_order">按渠道顺序</option></optgroup><optgroup label="关联状态"><option value="unlinked_first">未关联优先</option><option value="linked_first">已关联优先</option></optgroup></select>\n';
    html += '<button class="btn ghost" id="clearFiltersBtn" title="清除搜索、来源、渠道和标签筛选">清除筛选</button>\n';
    html += '<button class="btn secondary" id="dashboardBtn">' + String.fromCodePoint(0x1F4CA) + ' \u6570\u636e\u770b\u677f</button>\n';
    html += '<button class="btn ghost" id="wrapBtn">' + String.fromCodePoint(0x1F4C4) + ' \u6362\u884c\u6a21\u5f0f</button>\n';
    html += '<button class="btn ghost" id="resetWidthBtn">' + String.fromCodePoint(0x1F504) + ' \u91cd\u7f6e\u5217\u5bbd</button>\n';
    html += '<input type="file" id="importFile" accept=".csv" style="display:none;">\n';
    html += '<button class="btn ghost" id="tagMgrBtn">🏷️ 标签设置</button>\n';
    html += '<button class="btn ghost" id="fieldNameBtn">' + String.fromCodePoint(0x270F) + String.fromCodePoint(0xFE0F) + ' 字段/阶段命名</button>\n';
    html += '<button class="btn ghost" id="rescanBtn">' + String.fromCodePoint(0x1F517) + ' \u91cd\u626b\u5173\u8054</button>\n';
    html += '</div>\n';
    html += '<div id="banner"></div>\n';
    html += '<div id="wa-local-sync-bar-wrap"></div>\n';
    html += '<div class="stats" id="statsBar"></div>\n';
    html += '<div class="platformbar" id="platformBar"></div>\n';
    html += '<div class="tagbar" id="tagBar"></div>\n';
    html += '<div class="batchbar" id="batchBar">\n<span id="batchCount">\u5df2\u9009\u4e2d 0 \u9879</span>\n';
    html += '<select id="batchTagSelect"></select>\n<button class="btn" id="batchApplyTagBtn">\u5e94\u7528\u6807\u7b7e</button>\n';
    html += '<button class="btn secondary" id="batchExportSelectedBtn">⬇️ 导出选中</button>\n<button class="btn danger" id="batchDeleteBtn">\u5220\u9664\u9009\u4e2d</button>\n<button class="btn ghost" id="batchClearBtn">\u53d6\u6d88\u9009\u62e9</button>\n</div>\n';
    html += '<div class="dashboard" id="dashboard"></div>\n';
    html += '<div class="main-group-section" id="mainGroupSection">\n' +
  '  <div class="main-group-header" id="mainGroupToggleBar">\n' +
  '    <h3><span>🔗 跨源/跨渠道主记录专区</span><span id="mainGroupCountBadge" style="font-size:12px;background:#6d4c41;color:#fff;padding:2px 8px;border-radius:10px;margin-left:8px;">0 组</span></h3>\n' +
  '    <button class="btn ghost" id="mainGroupCollapseBtn" style="padding:2px 10px;font-size:12px;">收起 ▲</button>\n' +
  '  </div>\n' +
  '  <div class="main-group-table-container" id="mainGroupContainer">\n' +
  '    <table id="mainGroupTable"><colgroup id="mainGroupColgroup"></colgroup><thead id="mainGroupHead"></thead><tbody id="mainGroupBody"></tbody></table>\n' +
  '  </div>\n' +
  '</div>\n';
html += '<div class="sub-table-header">\n' +
      '  <h3><span>📋 各渠道联系人明细列表</span><span id="detailCountBadge" style="font-size:12px;background:#00a884;color:#fff;padding:2px 8px;border-radius:10px;margin-left:8px;">0 条</span></h3>\n' +
      '  <div class="sub-table-cfg"><span style="font-weight:700;color:var(--text);">⚙️ 列宽</span><span id="cfgViewportWidth" style="color:var(--sub);">当前 --px</span><label>横滚低于 <input type="number" id="cfgMinChars" min="800" max="3000"> px</label><label id="cfgAutoWrap" style="display:inline-flex;align-items:center;gap:5px;padding:2px 8px;border-radius:999px;background:rgba(0,168,132,.10);color:#008f72;font-weight:700;"><input type="checkbox" id="cfgFieldUnifiedAuto" style="width:14px;height:14px;"> f1-说明自适应</label><label id="cfgWidthWrap">统一宽度 <input type="number" id="cfgFieldUnifiedWidth" min="60" max="1200" placeholder="220"> px</label><span id="cfgWidthHint" style="color:var(--sub);font-size:11px;">输入后按 Enter 应用</span></div>\n' +
      '</div>\n' +
      '<div class="table-scroll-clip"><div class="table-container" style="border-radius:0 0 8px 8px;"><table id="mainTable"><colgroup id="tableColgroup"></colgroup><thead id="tableHead"></thead><tbody id="tableBody"></tbody></table></div></div>\n';
    html += '<div id="waViewportBottomBar"><div id="waViewportBottomBarInner"></div></div>\n</body>\n</html>';
    return html;
  }

  

    // ================= v77 本机多数据源同步模块 BEGIN =================
    function localSyncSafeClone(obj) {
      try { return JSON.parse(JSON.stringify(obj || {})); } catch (e) { return {}; }
    }
    function getLocalSyncSourceId() {
      var id = GM_getValue(LOCAL_SYNC_SOURCE_ID_KEY, "");
      if (!id) {
        id = "src_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 10);
        GM_setValue(LOCAL_SYNC_SOURCE_ID_KEY, id);
      }
      return id;
    }
    function getLocalSyncSourceName() {
      var name = GM_getValue(LOCAL_SYNC_SOURCE_NAME_KEY, "");
      return name || ("未命名-" + getLocalSyncSourceId().slice(-6));
    }
    function setLocalSyncSourceName(name) {
      name = String(name || "").trim() || ("未命名-" + getLocalSyncSourceId().slice(-6));
      GM_setValue(LOCAL_SYNC_SOURCE_NAME_KEY, name);
      return name;
    }
    // ================= V205.0 客户端身份与事件协议 BEGIN =================
    var V204_INSTALLATION_ID_KEY='jubo_v205_installation_id';
    var V204_DEVICE_ID_KEY='jubo_v205_device_id';
    var V204_WORKSPACE_ID_KEY='jubo_v205_workspace_id';
    var V204_ACCOUNT_PROFILES_KEY='jubo_v205_account_bindings';
    var V204_ACTIVE_ACCOUNTS_KEY='jubo_v205_active_accounts';
    var V204_SOURCE_REGISTRY_KEY='jubo_v205_source_registry';
    var V204_CHANGE_CURSOR_KEY='jubo_v205_change_cursor';
    var V204_CONTACT_CACHE_KEY='jubo_v205_contact_cache';
    // V206.0.6：Changes 游标与联系人缓存按服务地址 + 工作区隔离。
    function v206SyncScope(){return encodeURIComponent(String(getLocalSyncServerUrl()||'')+'|'+String(v204Identity().workspaceId||'default'));}
    function v206CursorKey(){return V204_CHANGE_CURSOR_KEY+'::'+v206SyncScope();}
    function v206ContactCacheKey(){return V204_CONTACT_CACHE_KEY+'::'+v206SyncScope();}
    function v206ChannelShort(ch){return ({whatsapp:'WA',instagram:'IG',facebook:'FB',messenger:'MS',telegram:'TG',other:'OT'})[String(ch||'').toLowerCase()]||'OT';}

    function v204Id(prefix){
      try { if (typeof crypto!=='undefined' && crypto.randomUUID) return prefix+'_'+crypto.randomUUID().replace(/-/g,''); } catch(e) {}
      return prefix+'_'+Date.now().toString(36)+'_'+Math.random().toString(36).slice(2,14);
    }
    function v204Stored(key, fallback){
      var x=GM_getValue(key,null); if(x===null||x===undefined||x==='')return fallback;
      if(typeof x==='string'){try{return JSON.parse(x);}catch(e){return x;}} return x;
    }
    function v204Save(key,value){GM_setValue(key,value);return value;}
    function v204Identity(){
      var installationId=String(GM_getValue(V204_INSTALLATION_ID_KEY,'')||'');
      var deviceId=String(GM_getValue(V204_DEVICE_ID_KEY,'')||'');
      var workspaceId=String(GM_getValue(V204_WORKSPACE_ID_KEY,'default')||'default');
      if(!installationId){installationId=v204Id('ins');GM_setValue(V204_INSTALLATION_ID_KEY,installationId);}
      if(!deviceId){deviceId=v204Id('dev');GM_setValue(V204_DEVICE_ID_KEY,deviceId);}
      if(!workspaceId){workspaceId='default';GM_setValue(V204_WORKSPACE_ID_KEY,workspaceId);}
      return {workspaceId:workspaceId,deviceId:deviceId,installationId:installationId};
    }
    function v204Profiles(){var p=v204Stored(V204_ACCOUNT_PROFILES_KEY,{})||{};Object.keys(p).forEach(function(ch){if(p[ch]&&p[ch].accountIdentity){var old=p[ch];p[ch]={};p[ch][String(old.accountIdentity)]=old;}});return p;}
    function v204ActiveAccounts(){return v204Stored(V204_ACTIVE_ACCOUNTS_KEY,{})||{};}
    function v204AccountProfile(channel,account){var p=v204Profiles();return (p[channel]&&p[channel][account])||{};}
    function v204AccountIdentity(channel){
      // V206.0.6：纯读取，后台 Worker 禁止主动 prompt。身份向导只能由用户写入动作或菜单显式启动。
      var active=v204ActiveAccounts(),profiles=v204Profiles(),value=String(active[channel]||'');
      if(value&&profiles[channel]&&profiles[channel][value])return value;
      var accounts=Object.keys(profiles[channel]||{});
      if(accounts.length===1){value=accounts[0];active[channel]=value;v204Save(V204_ACTIVE_ACCOUNTS_KEY,active);return value;}
      return '';
    }
    function v204Registry(){var x=v204Stored(V204_SOURCE_REGISTRY_KEY,{})||{};if(!x.accounts)x.accounts={};return x;}
    function v204RememberSource(channel,source,accountIdentity){
      var x=v204Registry(),key=channel+'::'+String(accountIdentity||'');x.accounts[key]={channel:channel,sourceId:String(source.source_id||source.sourceId||''),sourceName:String(source.source_name||source.sourceName||''),accountIdentity:String(accountIdentity||''),updatedAt:Date.now()};x.updatedAt=Date.now();v204Save(V204_SOURCE_REGISTRY_KEY,x);
    }
    function v204Event(operation, sourceId, payload, entityId, baseVersion){
      var id=v204Identity();
      var e={eventId:v204Id('evt'),workspaceId:id.workspaceId,deviceId:id.deviceId,installationId:id.installationId,sourceId:sourceId||'',entityType:'contact',operation:operation,payload:payload||{}};
      if(entityId)e.entityId=entityId;if(baseVersion!==undefined&&baseVersion!==null)e.baseVersion=Number(baseVersion);return e;
    }
    var V204_EVENT_QUEUE_KEY='jubo_v205_event_queue';
    function v207Hash(v){v=String(v||'');var h=2166136261;for(var i=0;i<v.length;i++){h^=v.charCodeAt(i);h=Math.imul(h,16777619);}return (h>>>0).toString(36);}
    function v207QueueKey(){var id=v204Identity();return V204_EVENT_QUEUE_KEY+'::'+v207Hash(getLocalSyncServerUrl())+'::'+id.workspaceId+'::'+id.deviceId;}
    function v207DeadKey(){var id=v204Identity();return 'jubo_v205_event_dead_letter::'+v207Hash(getLocalSyncServerUrl())+'::'+id.workspaceId;}
    function v207DeadLetters(){var x=v204Stored(v207DeadKey(),[]);return Array.isArray(x)?x:[];}
    function v207DeadLetter(item,result){var x=v207DeadLetters();x.push({item:item,result:result,rejectedAt:Date.now()});v204Save(v207DeadKey(),x.slice(-2000));}
    function v207MigrateQueue(){var key=v207QueueKey(),q=v204Stored(key,null);if(Array.isArray(q))return q;var old=v204Stored(V204_EVENT_QUEUE_KEY,[]),id=v204Identity(),keep=[];(Array.isArray(old)?old:[]).forEach(function(x){var e=x&&x.event||{};if(e.workspaceId===id.workspaceId&&e.deviceId===id.deviceId&&e.installationId===id.installationId)keep.push(x);else v207DeadLetter(x,{code:'LEGACY_CONTEXT_MISMATCH',message:'旧事件上下文与当前服务器/设备不一致'});});v204Save(key,keep);v204Save(V204_EVENT_QUEUE_KEY,[]);return keep;}
    function v204EventQueue(){return v207MigrateQueue();}
    function v204SaveEventQueue(q){v204Save(v207QueueKey(),(q||[]).slice(-5000));return q;}
    function v204QueueEvent(e){var q=v204EventQueue(),key=e.operation+'|'+(e.sourceId||'')+'|'+(e.entityId||'')+'|'+((e.payload||{}).externalContactId||'');if(e.operation==='contact.observe')q=q.filter(function(x){return x._dedupeKey!==key;});q.push({event:e,_dedupeKey:key,attempts:0,createdAt:Date.now(),nextRetryAt:0,lastError:''});v204SaveEventQueue(q);return e;}
    async function v204FlushEventQueue(targetEventIds){var q=v204EventQueue(),now=Date.now(),target={};(targetEventIds||[]).forEach(function(x){target[String(x)]=1;});var scoped=!!(targetEventIds&&targetEventIds.length),ready=q.filter(function(x){return (!scoped||target[x.event.eventId])&&Number(x.nextRetryAt||0)<=now;}),done={},dead={},results=[],retrying=0,permanent={EVENT_ID_REUSED:1,CONTACT_NOT_FOUND:1,INVALID_EVENT:1,INVALID_OPERATION:1,INVALID_PAYLOAD:1,INVALID_OBSERVATION:1,BASE_VERSION_REQUIRED:1,INVALID_BASE_VERSION:1,CHANNEL_MISMATCH:1,SOURCE_CONTEXT_MISMATCH:1,INSTALLATION_MISMATCH:1,EVENT_TOO_LARGE:1,DEVICE_NOT_FOUND:1,SOURCE_NOT_FOUND:1,VERSION_CONFLICT:1};for(var i=0;i<ready.length;i+=500){var part=ready.slice(i,i+500),r=await localSyncRequest('POST','/api/v207/events/batch',{events:part.map(function(x){return x.event;})});if(!r.ok){part.forEach(function(x){x.attempts=Number(x.attempts||0)+1;x.lastError=String(r.error||(r.data&&r.data.code)||r.status||'提交失败');x.nextRetryAt=Date.now()+Math.min(300000,1000*Math.pow(2,Math.min(x.attempts,8)));retrying++;});continue;}var rr=(r.data&&r.data.results)||[];part.forEach(function(x,n){var z=rr[n]||{ok:false,code:'MISSING_EVENT_RESULT',message:'服务端未返回事件结果'};z.eventId=x.event.eventId;results.push(z);if(z.ok)done[x.event.eventId]=1;else if(permanent[String(z.code||'')]){dead[x.event.eventId]=1;v207DeadLetter(x,z);}else{x.attempts=Number(x.attempts||0)+1;x.lastError=String(z.message||z.code||'事件被拒绝');x.nextRetryAt=Date.now()+Math.min(300000,1000*Math.pow(2,Math.min(x.attempts,8)));retrying++;}});}q=q.filter(function(x){return !done[x.event.eventId]&&!dead[x.event.eventId];});v204SaveEventQueue(q);var rejected=results.filter(function(x){return !x.ok;}),targetRemaining=scoped?q.filter(function(x){return target[x.event.eventId];}).length:q.length;var out={ok:rejected.length===0&&retrying===0&&targetRemaining===0,currentBatchConfirmed:rejected.length===0&&retrying===0&&targetRemaining===0,queueDrained:q.length===0,submitted:ready.length,applied:results.filter(function(x){return x.ok;}).length,rejected:rejected,retrying:retrying,deferred:q.filter(function(x){return Number(x.nextRetryAt||0)>now;}).length,remaining:q.length,deadLetterCount:v207DeadLetters().length,results:results};try{v892SetRuntime({lastBatch:out,deadLetterCount:out.deadLetterCount});}catch(e){}return out;}
    function v204ShowQueue(){var q=v204EventQueue();alert('V205 事件队列：'+q.length+' 条\n'+JSON.stringify(q.slice(0,20),null,2));}
    function v204ClearContactCache(){GM_setValue(v206ContactCacheKey(),{contacts:{},initialized:false});GM_setValue(v206CursorKey(),0);localSyncFetchAllContacts().then(function(r){alert(r.ok?'已清空缓存并从服务端恢复':'恢复失败：'+(r.error||r.status));});}
    async function v204RegisterDevice(){
      var id=v204Identity();return localSyncRequest('POST','/api/v207/devices/register',{workspace_id:id.workspaceId,device_id:id.deviceId,installation_id:id.installationId,device_name:String(GM_getValue('jubo_v205_device_name','采集端-'+id.deviceId.slice(-6))||'').slice(0,120),computer_name:String(GM_getValue('jubo_v205_computer_name',navigator.platform||'browser')||'').slice(0,120),metadata:{client:'V205_REALTIME',userAgent:navigator.userAgent.slice(0,240)}});
    }
    async function v204RegisterSource(channel,accountOverride,profileOverride){
      // V206.0.6：允许身份向导用“待提交身份”完成远端注册；远端成功前不激活本地身份。
      var id=v204Identity(),account=String(accountOverride||v204AccountIdentity(channel)||'').trim();if(!account)return {ok:false,status:400,error:'未配置 '+channel+' 稳定账号身份',data:{code:'ACCOUNT_IDENTITY_REQUIRED',retryable:false}};
      var p=profileOverride||v204AccountProfile(channel,account)||{};
      var r=await localSyncRequest('POST','/api/v207/accounts/resolve',{host:location.hostname,path:location.pathname,channel:channel,identity:account}); if(r.ok&&r.data&&r.data.binding)r.data.source={source_id:r.data.binding.source_id,source_name:r.data.binding.source_name,channel:channel,account_identity:account,workspace_id:r.data.binding.workspace_id,team_id:r.data.binding.team_id};
      if(r.ok&&r.data&&r.data.source)v204RememberSource(channel,r.data.source,account);return r;
    }
    function v204Channel(x){
      var h=String(location.hostname||'').toLowerCase(),p=String(location.pathname||'');
      if(h==='web.whatsapp.com')return 'whatsapp';
      if(h==='www.instagram.com')return 'instagram';
      if(h==='www.messenger.com')return 'messenger';
      if(h==='www.facebook.com'&&p.indexOf('/messages')===0)return 'facebook';
      if(h==='web.telegram.org')return 'telegram';
      throw new Error('UNTRUSTED_CHANNEL：当前页面不是受信任渠道，禁止降级为 other');
    }
    function v204External(x,fallbackKey){x=x||{};return String(x.id||x._localKey||x.jid||x.threadId||fallbackKey||'').trim();}
    function v204ManualPayload(x,c){
      // V207.0.0：只读取明确 dirty 字段；禁止“值不同即全量回写”。
      var p={},custom={},dirty=Array.isArray(x.__dirtyFields)?x.__dirtyFields:[],serverCustom=c.customFields||{};
      function has(k){return dirty.indexOf(k)>=0;}
      [['remark','remark'],['status','status'],['manualName','manualName'],['manualPhone','manualPhone']].forEach(function(pair){if(has(pair[0]))p[pair[1]]=String(x[pair[0]]||'');});
      dirty.forEach(function(k){if(/^f[1-8]$/.test(k)||/^cf_[A-Za-z0-9_-]{6,77}$/.test(k)||k==='ui.stages'){var v=(x.customFields&&x.customFields[k]!==undefined)?x.customFields[k]:x[k];if(JSON.stringify(v)!==JSON.stringify(serverCustom[k]))custom[k]=v;}});
      if(Object.keys(custom).length)p.customFields=custom;return p;
    }
    function v204WrapContact(c){
      var dev=c.lastObservedDevice||{},src=c.source||{},deviceName=String(dev.device_name||src.source_name||((dev.device_id||'').slice(-8))||'未知设备');
      var legacy={name:c.display_name||'',displayName:c.display_name||'',phone:c.observed_phone||'',avatar:c.avatar_url||'',platform:c.channel||'other',channel:c.channel||'other',tag:'',tag2:[],stages:[]};
      legacy.id=legacy.id||c.external_contact_id;legacy._localKey=legacy._localKey||c.external_contact_id;
      if(c.remark!==undefined)legacy.remark=c.remark;if(c.status!==undefined)legacy.status=c.status;if(c.manual_name!==undefined)legacy.manualName=c.manual_name;if(c.manual_phone!==undefined)legacy.manualPhone=c.manual_phone;if(c.business!==undefined)legacy.business=c.business;
      Object.keys(c.customFields||{}).forEach(function(k){if(k==='ui.stages')legacy.stages=Array.isArray(c.customFields[k])?c.customFields[k].slice():[];else{legacy[k]=c.customFields[k];(legacy.customFields||(legacy.customFields={}))[k]=c.customFields[k];}});
      (Array.isArray(c.tags)?c.tags:[]).forEach(function(t){var m=/^ui:(tag|persona):(.*)$/.exec(String(t.tag_id||''));if(!m)return;var key;try{key=decodeURIComponent(m[2]);}catch(e){key=m[2];}if(m[1]==='tag')legacy.tag=key;else if(legacy.tag2.indexOf(key)<0)legacy.tag2.push(key);});
      legacy.__v204={contactId:c.contact_id,sourceId:c.source_id,externalId:c.external_contact_id,channel:c.channel||'other',version:Number(c.version||0),lastAckAt:Date.now()};
      legacy.__v206ProjectedVersion=Number(c.version||0);legacy.__v206ProjectedAt=Date.now();legacy.__v206DeviceName=deviceName;legacy.__v206ComputerName=String(dev.computer_name||'');legacy.__v206Channel=String(c.channel||'other');legacy.__v206ChannelShort=v206ChannelShort(c.channel);legacy.__v206SourceName=String(src.source_name||'');legacy.__v206AccountIdentity=String(src.account_identity||'');legacy.__serverDeletedAt=c.deleted_at||null;
      return {contactId:c.contact_id,sourceId:c.source_id,sourceName:deviceName,accountSourceName:String(src.source_name||''),accountIdentity:String(src.account_identity||''),deviceId:String(dev.device_id||''),deviceName:deviceName,computerName:String(dev.computer_name||''),channel:String(c.channel||'other'),channelShort:v206ChannelShort(c.channel),externalContactId:c.external_contact_id,data:legacy};
    }
    async function v204ListContacts(){
      var id=v204Identity(),all=[],after=0;
      for(var guard=0;guard<100;guard++){var r=await localSyncRequest('GET','/api/v207/contacts?workspace_id='+encodeURIComponent(id.workspaceId)+'&limit=1000&after_id='+after);if(!r.ok)return r;all=all.concat(r.data.items||[]);var page=r.data.page||{};after=Number(page.next_cursor||after);if(!page.has_more)return {ok:true,status:200,data:{items:all}};}
      return {ok:false,status:508,error:'联系人分页超过安全上限'};
    }
    function v204ContactCache(){
      var key=v206ContactCacheKey(),x=v204Stored(key,{})||{};
      if(!x.contacts||typeof x.contacts!=='object')x.contacts={};
      return x;
    }
    function v204SaveContactCache(x){x.updatedAt=Date.now();x.workspaceId=v204Identity().workspaceId;v204Save(v206ContactCacheKey(),x);return x;}
    function v204ApplyContactSnapshot(cache,contact){
      if(!contact||!contact.contact_id)return;
      var key=String(contact.contact_id);cache.contacts[key]=contact;
    }
    function v204CachedRows(){var c=v204ContactCache();return Object.keys(c.contacts).map(function(k){return c.contacts[k];}).filter(function(x){return x&&!x.deleted_at;});}
    function v206ProjectContactsToUi(contacts){
      // 静默投影：直接写 GM，不调用 saveData()，因此不会触发自动上传。
      var data={};try{data=loadData()||{};}catch(e){return {projected:0,affected:[]};}
      var projected=0,affected=[];
      (contacts||[]).forEach(function(c){if(!c||!c.contact_id)return;var observed=c.observed||{},localKey=String(observed.localKey||''),targetKey='',keys=Object.keys(data);
        for(var i=0;i<keys.length;i++){var row=data[keys[i]]||{},meta=row.__v204||{};if(String(meta.contactId||'')===String(c.contact_id)|| (localKey&&String(row._localKey||row.id||row.jid||row.threadId||keys[i])===localKey)){targetKey=keys[i];break;}}
        if(!targetKey&&localKey&&data[localKey])targetKey=localKey;if(!targetKey)return;
        var current=data[targetKey]||{},incoming=v204WrapContact(c).data;
        if(Number(current.__v206ProjectedVersion||0)>Number(c.version||0))return;
        ['manualName','manualPhone','remark','status','business','tag','tag2','stages','customFields','__v204','__v206ProjectedVersion','__v206ProjectedAt','__v206DeviceName','__v206ComputerName','__v206Channel','__v206ChannelShort','__v206SourceName','__v206AccountIdentity','__serverDeletedAt'].forEach(function(k){if(incoming[k]!==undefined)current[k]=incoming[k];});
        Object.keys(c.customFields||{}).forEach(function(k){current[k]=c.customFields[k];});data[targetKey]=current;projected++;affected.push(String(c.contact_id));
      });
      if(projected)GM_setValue(STORAGE_KEY,JSON.stringify(data));
      return {projected:projected,affected:affected};
    }
    // 联系人上下文在 V205 单一同步控制器中统一声明，避免重复函数覆盖。
    function isV204ServerContact(rowId){return !!v204ContactContext(rowId);}
    function v205LocalContact(rowId){
      if(rowId&&typeof rowId==='object')return rowId;
      var key=String(rowId||''),data={};try{data=loadData()||{};}catch(e){}
      if(data[key]&&typeof data[key]==='object')return data[key];
      var keys=Object.keys(data);for(var i=0;i<keys.length;i++){var x=data[keys[i]];if(!x||typeof x!=='object')continue;if(String(x._localKey||x.id||x.jid||x.threadId||'')===key)return x;}
      return null;
    }
    async function v205EnsureRemoteContact(rowId){
      var ctx=v204ContactContext(rowId);if(ctx)return {ok:true,status:200,data:{context:ctx,created:false}};
      var row=v205LocalContact(rowId);if(!row)return {ok:false,status:404,error:'V205 本地联系人不存在',data:{code:'LOCAL_CONTACT_NOT_FOUND'}};
      var channel=v204Channel(row),external=v204External(row,rowId);if(!external)return {ok:false,status:400,error:'联系人缺少稳定外部标识',data:{code:'EXTERNAL_CONTACT_ID_REQUIRED'}};
      var dev=await v204RegisterDevice();if(!dev.ok)return dev;
      var reg=await v204RegisterSource(channel);if(!reg.ok)return reg;
      var sourceId=String(reg.data&&reg.data.source&&(reg.data.source.source_id||reg.data.source.sourceId)||'');
      var payload={channel:channel,externalContactId:external,displayName:String(row.name||row.displayName||row.nickname||''),observedPhone:String(row.phone||row.phoneNumber||''),avatarUrl:String(row.avatar||row.avatarUrl||''),observed:{localKey:String(row._localKey||rowId||external),platformId:String(row.jid||row.threadId||row.id||''),username:String(row.username||''),profileUrl:String(row.profileUrl||row.profileHref||'')}};
      v204QueueEvent(v204Event('contact.observe',sourceId,payload));
      var sent=await v204FlushEventQueue();if(!sent.ok)return {ok:false,status:409,error:'联系人 Observe 未确认',data:sent};
      var pulled=await v204PullChanges();if(!pulled.ok)return pulled;
      var contact=v205FindContact(sourceId,channel,external),fresh=contact&&v204ContactContext(contact.contact_id);
      if(!fresh)return {ok:false,status:404,error:'Observe 已提交但未取得远端联系人映射',data:{code:'REMOTE_CONTACT_MAPPING_MISSING'}};
      return {ok:true,status:200,data:{context:fresh,created:true}};
    }
    async function v205PatchContact(rowId,payload){
      var ensured=await v205EnsureRemoteContact(rowId);if(!ensured.ok)return ensured;
      var ctx=ensured.data.context;
      for(var attempt=0;attempt<2;attempt++){
        v204QueueEvent(v204Event('contact.patch',ctx.sourceId,payload||{},ctx.contactId,ctx.version));
        var out=await v204FlushEventQueue();
        var bad=(out.results||[]).filter(function(x){return !x.ok;})[0]||null;
        if(bad&&bad.code==='VERSION_CONFLICT'&&attempt===0){
          if(bad.current){var cache=v204ContactCache();v204ApplyContactSnapshot(cache,bad.current);v204SaveContactCache(cache);}
          await v204PullChanges();ctx=v204ContactContext(ctx.contactId);if(ctx)continue;
        }
        await v204PullChanges();
        if(bad)return {ok:false,status:409,error:bad.message||bad.code||'联系人修改被拒绝',data:bad};
        if(!out.ok)return {ok:false,status:503,error:'修改事件尚未全部确认',data:out};
        return {ok:true,status:200,data:out};
      }
      return {ok:false,status:409,error:'联系人版本冲突，请刷新后重试',data:{code:'VERSION_CONFLICT'}};
    }
    async function v204PatchContact(rowId,payload){return v205PatchContact(rowId,payload);}
    async function v205ReplaceUiTags(rowId,category,keys){var ensured=await v205EnsureRemoteContact(rowId);if(!ensured.ok)return ensured;var ctx=ensured.data.context;var prefix='ui:'+category+':',preserved=(Array.isArray(ctx.contact.tags)?ctx.contact.tags:[]).map(function(t){return String(t.tag_id||'');}).filter(function(id){return id&&id.indexOf(prefix)!==0;});var added=(Array.isArray(keys)?keys:[keys]).map(function(k){return String(k||'').trim();}).filter(Boolean).map(function(k){return v204ConfigTagId(category,k);});var tagIds=preserved.concat(added).filter(function(x,i,a){return a.indexOf(x)===i;});var id=v204Identity(),res=await localSyncRequest('PATCH','/api/v207/contacts/'+encodeURIComponent(ctx.contactId)+'/tags',{workspace_id:id.workspaceId,device_id:id.deviceId,base_version:ctx.version,tag_ids:tagIds});if(res.ok&&res.data&&res.data.contact){var cache=v204ContactCache();v204ApplyContactSnapshot(cache,res.data.contact);v204SaveContactCache(cache);}await v204PullChanges();return res;}
    async function v204ReplaceUiTags(rowId,category,keys){return v205ReplaceUiTags(rowId,category,keys);}
    function v204UiWriteResult(promise,label){promise.then(function(res){if(res&&res.ok){try{localSyncRefreshAggregate().then(function(){try{refreshPanelIfOpen();}catch(e){}});}catch(e){}}else{try{showCopyToast('⚠️ '+label+'失败：'+remoteOverrideFailText(res));}catch(e){}}}).catch(function(e){try{showCopyToast('⚠️ '+label+'失败：'+String(e&&e.message||e));}catch(_e){}});return true;}
    function v204FieldPayload(key,value){if(['remark','status','manualName','manualPhone','business'].indexOf(key)>=0){var p={};p[key]=value;return p;}if(/^f[1-8]$/.test(key)||/^cf_[A-Za-z0-9_-]{6,77}$/.test(key)||key==='ui.stages'){var custom={};custom[key]=value;return {customFields:custom};}return null;}
    async function v204EnsureBaseline(){
      var id=v204Identity(),cache=v204ContactCache();
      if(cache.initialized&&String(cache.workspaceId||'')===String(id.workspaceId))return {ok:true,status:200,data:{items:v204CachedRows(),baseline:false}};
      var res=await v204ListContacts();if(!res.ok)return res;
      cache={contacts:{},initialized:true,workspaceId:id.workspaceId};(res.data.items||[]).forEach(function(c){v204ApplyContactSnapshot(cache,c);});v204SaveContactCache(cache);
      var projection=v206ProjectContactsToUi(res.data.items||[]);
      return {ok:true,status:200,data:{items:v204CachedRows(),baseline:true,projection:projection}};
    }
    async function v204PullChanges(){
      var baseline=await v204EnsureBaseline();if(!baseline.ok)return baseline;
      var id=v204Identity(),cursor=Number(GM_getValue(v206CursorKey(),0)||0),all=[],changedContacts=[],cache=v204ContactCache();
      for(var guard=0;guard<100;guard++){
        var r=await localSyncRequest('GET','/api/v207/changes?workspace_id='+encodeURIComponent(id.workspaceId)+'&after='+cursor+'&limit=1000');if(!r.ok)return r;
        var items=(r.data&&r.data.items)||[];items.sort(function(a,b){return Number(a.change_id||0)-Number(b.change_id||0);});
        items.forEach(function(change){var contact=change.payload&&(change.payload.contact||change.payload);if(contact&&contact.contact_id){v204ApplyContactSnapshot(cache,contact);changedContacts.push(contact);}});
        all=all.concat(items);cursor=Number(r.data.nextCursor||cursor);GM_setValue(v206CursorKey(),cursor);v204SaveContactCache(cache);
        if(!r.data.hasMore){var projection=v206ProjectContactsToUi(changedContacts);LOCAL_SYNC_LAST_STATUS.lastChanges=all.length;LOCAL_SYNC_LAST_STATUS.lastProjected=projection.projected;LOCAL_SYNC_LAST_STATUS.lastCursor=cursor;return {ok:true,status:200,data:{items:all,contacts:v204CachedRows(),nextCursor:cursor,projection:projection}};}
      }
      return {ok:false,status:508,error:'增量同步分页超过安全上限'};
    }
    // ================= V205.0 客户端身份与事件协议 END =================
    // V204：服务端联系人以 contact_id 与缓存元数据识别。
    function v105IsMainIdentity(value) {
      var text = String(value == null ? '' : value);
      return !!text && text.indexOf('MAIN::') >= 0;
    }
    function v105IsDerivedMainRecord(key, record) {
      if (v105IsMainIdentity(key)) return true;
      if (!record || typeof record !== 'object') return false;
      var ownId = record.id || record.__id || record._localKey || record.key || '';
      if (v105IsMainIdentity(ownId)) return true;
      return !!(
        record.isMainRecord || record.__isMainRecord || record.__isCrossSourceMain ||
        record.__isGroup || record.platform === 'main' || record.__platform === 'main'
      );
    }
    function v105SanitizeLeafForSync(key, record) {
      var ownId = record && (record._localKey || record.id || record.key || record.__id || '');
      // v121.1：旧同步包装键： 仅允许存在于汇总显示层，绝不上传为本源事实。
      if (isV204ServerContact(key) || isV204ServerContact(ownId)) return null;
      if (!record || typeof record !== 'object' || v105IsDerivedMainRecord(key, record)) return null;
      var clean = localSyncSafeClone(record);
      if (!clean || typeof clean !== 'object' || v105IsDerivedMainRecord(key, clean)) return null;
      // 仅移除聚合/界面/同步回读产生的派生状态；业务字段及 linkPolicy 原样保留。
      [
        'isMainRecord','memberIds','mainKey','viewMode','__mainKey','__members',
        '__memberCount','__sourceCount','__linkInfo','__candidateMainKey',
        '__associationBlocked','__mergedFields','__isMainRecord','__isCrossSourceMain',
        '__isGroup','__platform','__sourceId','__sourceName','__fromLocalSync',
        '__syncSourceId','__syncSourceName','__syncMergedKey','__rawId',
        '__rawMainKey','__rawInternalMainKey','__rawMemberIds'
      ].forEach(function(field) { delete clean[field]; });
      return clean;
    }
    function v105LeafIdsFromData(data) {
      return Object.keys(data || {}).filter(function(id) {
        return !!v105SanitizeLeafForSync(id, data[id]);
      });
    }
    function v105ExtractWrappedRecord(wrap) {
      if (!wrap || typeof wrap !== 'object') return null;
      return wrap.data || wrap.contact || wrap.item || null;
    }
    function v105IsWrappedMainRecord(wrap) {
      var raw = v105ExtractWrappedRecord(wrap);
      var cid = (wrap && wrap.contactId) || (raw && (raw.id || raw._localKey || raw.key)) || '';
      return v105IsDerivedMainRecord(cid, raw);
    }
    function v105IsLocalMainRecordId(id) {
      if (v105IsMainIdentity(id)) return true;
      try {
        var localData = loadData() || {};
        return v105IsDerivedMainRecord(id, localData[id]);
      } catch (e) { return false; }
    }
    function v105GuardSyncRequestBody(path, body) {
      // V205.0.1：旧快照请求体改写已退役；仅做安全深拷贝。
      return localSyncSafeClone(body || {});
    }
    function localSyncRequest(method, path, body) {
      path=String(path||'');
      if (!(path==='/api/health' || path==='/health' || /^\/api\/v205\//.test(path))) return Promise.resolve({ok:false,status:410,error:'旧协议已禁用',method:method,path:path,data:{ok:false,code:'LEGACY_API_GONE',message:'客户端禁止调用非 V205 接口'}});
      if (String(method || '').toUpperCase() === 'POST') {
        body = v105GuardSyncRequestBody(path, body);
        if (!body) return Promise.resolve({ ok:true, skipped:true, reason:'v105-main-record-is-sync-isolated', method:method, path:path });
      }
      return new Promise(function(resolve){
        var started = Date.now(), settled = false, requestHandle = null;
        function finish(ret) {
          if (settled) return;
          settled = true;
          clearTimeout(hardTimer);
          LOCAL_SYNC_LAST_STATUS.lastRequest = ret;
          resolve(ret);
        }
        var hardTimer = setTimeout(function(){
          try { if (requestHandle && typeof requestHandle.abort === 'function') requestHandle.abort(); } catch(e) {}
          finish({ ok:false, error:'请求硬超时', method:method, path:path, ms:Date.now()-started, hardTimeout:true });
        },12000);
        try {
          requestHandle = GM_xmlhttpRequest({
            method: method,
            url: getLocalSyncServerUrl() + path,
            headers: getLocalSyncAuthHeaders(),
            data: body ? JSON.stringify(body) : undefined,
            timeout: 8000,
            onload: function(res){
              var raw = res.responseText || "";
              try {
                var json = JSON.parse(raw || "{}");
                var healthy = (res.status >= 200 && res.status < 300 && json.ok !== false);
                finish({ ok:healthy, status:res.status, data:json, raw:raw, method:method, path:path, ms:Date.now()-started });
              } catch(e) {
                finish({ ok:false, status:res.status, error:"JSON解析失败: "+(e&&e.message||e), raw:raw, method:method, path:path, ms:Date.now()-started });
              }
            },
            onerror: function(err){ finish({ ok:false, error:"请求失败", detail:String(err||""), method:method, path:path, ms:Date.now()-started }); },
            ontimeout: function(){ finish({ ok:false, error:"请求超时", method:method, path:path, ms:Date.now()-started }); },
            onabort: function(){ finish({ ok:false, error:"请求已中止", method:method, path:path, ms:Date.now()-started }); }
          });
        } catch(e) {
          finish({ ok:false, error:"GM_xmlhttpRequest异常: "+(e&&e.message||e), method:method, path:path, ms:Date.now()-started });
        }
      });
    }

    function isLocalSyncRealtimeUploadEnabled() { return true; }
    function setLocalSyncRealtimeUploadEnabled(v) { return true; }
    function isLocalSyncAggregateEnabled() { return true; }
    function setLocalSyncAggregateEnabled(v) { return true; }
    

    // v89 跨源汇总只读保护：判断当前行是否为“其他源”汇总数据
    function isRemoteSyncRecord(row) {
      return !!(row && row.__fromLocalSync && row.__syncSourceId && row.__syncSourceId !== getLocalSyncSourceId());
    }
    function getRemoteSyncSourceLabel(row) {
      return (row && (row.__syncSourceName || row.__syncSourceId)) || '其他源';
    }
    function getRemoteSyncReadonlyTitle(row) {
      return '这是来自其他源【' + getRemoteSyncSourceLabel(row) + '】的汇总数据，请到来源浏览器/Profile 中编辑。';
    }
    // v131：他源可编辑开关（默认开启）。开启后他源行可编辑/删除，改动写入服务端覆盖层。
    function isRemoteEditableEnabled() {
      try { return getSettings().remoteEditableV131 !== false; } catch (e) { return true; }
    }
    function setRemoteEditableEnabled(v) {
      try { setSettings({ remoteEditableV131: !!v }); } catch (e) {}
    }
    function guardRemoteSyncEdit(row) {
      if (!isRemoteSyncRecord(row)) return false;
      if (isRemoteEditableEnabled()) return false;
      try {
        if (managePanelWindow && !managePanelWindow.closed) managePanelWindow.alert(getRemoteSyncReadonlyTitle(row));
        else alert(getRemoteSyncReadonlyTitle(row));
      } catch(e) { try { alert(getRemoteSyncReadonlyTitle(row)); } catch(_e) {} }
      return true;
    }
    // v106：来源名称按稳定 sourceId 配色；不再在来源徽标中重复显示禁止图标。
    // v106.2：同一来源固定颜色；不同来源避免占用同色，并使用高区分度调色板。
    var SOURCE_COLOR_BY_ID_V1061 = Object.create(null);
    var SOURCE_ID_BY_COLOR_V1061 = Object.create(null);
    function getSourceBadgeColorV106(row) {
      var key106 = String((row && (row.__syncSourceId || row.__sourceId || row.__syncSourceName || row.__sourceName)) || 'remote');
      if (SOURCE_COLOR_BY_ID_V1061[key106]) return SOURCE_COLOR_BY_ID_V1061[key106];
      var palette106 = ['#2563eb','#ea580c','#7c3aed','#059669','#dc2626','#0891b2','#a16207','#db2777','#4d7c0f','#475569'];
      var hash106 = 2166136261;
      for (var i106 = 0; i106 < key106.length; i106++) {
        hash106 ^= key106.charCodeAt(i106);
        hash106 = Math.imul(hash106, 16777619);
      }
      var start106 = (hash106 >>> 0) % palette106.length;
      var chosen106 = palette106[start106];
      for (var step106 = 0; step106 < palette106.length; step106++) {
        var candidate106 = palette106[(start106 + step106) % palette106.length];
        if (!SOURCE_ID_BY_COLOR_V1061[candidate106] || SOURCE_ID_BY_COLOR_V1061[candidate106] === key106) {
          chosen106 = candidate106;
          break;
        }
      }
      SOURCE_COLOR_BY_ID_V1061[key106] = chosen106;
      SOURCE_ID_BY_COLOR_V1061[chosen106] = key106;
      return chosen106;
    }
    function appendRemoteSyncReadonlyBadge(doc, parent, row) {
      var badge = doc.createElement('span');
      badge.className = 'wa-remote-readonly-badge wa-v106-source-badge';
      badge.textContent = getRemoteSyncSourceLabel(row);
      badge.style.setProperty('--wa-v106-source-color', getSourceBadgeColorV106(row));
      badge.title = getRemoteSyncReadonlyTitle(row);
      parent.appendChild(badge);
    }
    function appendLocalEditableBadge(doc, parent) {
      var badge = doc.createElement('span');
      badge.className = 'wa-local-origin-badge';
      badge.textContent = '本源';
      badge.title = '这是当前浏览器/Profile 的本源数据，可以编辑并上传。';
      parent.appendChild(badge);
    }
function getPanelDisplayData() {
      if (!isLocalSyncAggregateEnabled()) return loadData() || {};
      return getLocalSyncDisplayData();
    }
        // V205：上传由文件末端的事件队列 Worker 实现。


    async function localSyncRefreshAggregate() {
      var h = await localSyncHealthCheck({ silent:true });
      if (!h.ok) return { ok:false, stage:'health', error:h.error || ('HTTP ' + (h.status || '连接失败')) };

      var pair = await Promise.all([localSyncFetchSourcesAndStats(), localSyncFetchAllContacts()]);
      var meta = pair[0];
      var contacts = pair[1];
      if (!meta || !meta.ok) return { ok:false, stage:'metadata', error:(meta && meta.error) || '来源或统计读取失败' };
      if (!contacts || !contacts.ok) return { ok:false, stage:'contacts', error:contacts && (contacts.error || contacts.status) || '联系人汇总读取失败' };

      LOCAL_SYNC_LAST_STATUS.message = "接收更新完成";
      return { ok:true };
    }

    // ========================================================
    // V205 客户端诊断。
    // ========================================================
        // V205 无 Leader/租约诊断：只报告事件队列、Changes 游标与 Worker 状态。
    function v205ClientDiagnosticSnapshot() {
      var queue=[];
      try { queue=v204EventQueue(); } catch(e) {}
      return {
        version:'205.0.0', generatedAt:new Date().toISOString(),
        workers:{uploadRunning:!!V205_UPLOAD_RUNNING,pullScheduled:!!V205_PULL_TIMER,uploadScheduled:!!V205_UPLOAD_TIMER},
        eventQueue:{length:Array.isArray(queue)?queue.length:0},
        changes:{cursor:Number(GM_getValue(V204_CURSOR_KEY,0))||0},
        service:{url:getLocalSyncServerUrl(),connected:!!LOCAL_SYNC_LAST_STATUS.ok,message:LOCAL_SYNC_LAST_STATUS.message||''},
        lastRequest:LOCAL_SYNC_LAST_STATUS.lastRequest||null
      };
    }
    function localSyncDiagText() {
      return '聚宝盆 '+getDisplayVersionV124()+' / V205 同步诊断\n'+JSON.stringify(v205ClientDiagnosticSnapshot(),null,2);
    }

async function localSyncHealthCheck(options) {
      options = options || {};
      if (!options.silent) v892SetRuntime({ service:'busy', serviceError:'' });
      var res = await localSyncRequest("GET", "/api/health");
      var apiVersion=String(res.data&&res.data.apiVersion||''), schemaVersion=Number(res.data&&res.data.schemaVersion), productVersion=String(res.data&&(res.data.productVersion||res.data.version)||'');
      var compatible=!!(res.ok && res.data && schemaVersion===205 && (apiVersion==='205' || (!apiVersion && /^205\./.test(productVersion))));
      if(res.ok && !compatible){res.ok=false;res.error='服务版本不兼容：要求 V205 / Schema 205';res.data=res.data||{};res.data.code='VERSION_MISMATCH';}
      LOCAL_SYNC_LAST_STATUS.ok = compatible;
      LOCAL_SYNC_LAST_STATUS.message = compatible ? (res.data.productVersion ? "已连接（V" + res.data.productVersion + " / API 205）" : "已连接（V205）") : "未连接或版本不兼容";
      v892SetRuntime({
        service:res.ok ? 'ok' : 'error',
        lastHealthAt:Date.now(),
        serviceError:res.ok ? '' : ('连接失败：' + (res.error || res.status || '未知错误'))
      });
      return res;
    }

    // ================= v89.1 删除同步修复 BEGIN =================
    async function localSyncDeleteOne(rowId) {
      try {
        var ensured=await v205EnsureRemoteContact(rowId);if(!ensured.ok)return ensured;
        var ctx=ensured.data.context,id=v204Identity();
        var preview=await localSyncRequest('POST','/api/v207/delete-preview',{workspaceId:id.workspaceId,deviceId:id.deviceId,contactId:ctx.contactId,version:ctx.version});if(!preview.ok)return preview;
        v204QueueEvent(v204Event('contact.delete',ctx.sourceId,{confirmationId:preview.data.confirmationId,reason:'V205 客户端删除'},ctx.contactId,ctx.version));
        var flushed=await v204FlushEventQueue(),bad=(flushed.results||[]).filter(function(x){return !x.ok;})[0]||null;
        await v204PullChanges();
        if(bad)return {ok:false,status:409,error:bad.message||bad.code||'删除被拒绝',data:bad};
        LOCAL_SYNC_LAST_STATUS.message=flushed.ok?'已同步删除 1 条':'删除事件等待重试';
        return {ok:flushed.ok,status:flushed.ok?200:202,data:flushed,contactId:ctx.contactId};
      }catch(e){return {ok:false,error:String(e&&e.message||e)};}
    }
    async function localSyncBatchDelete(contactIds,options) {
      contactIds=(contactIds||[]).filter(function(id){return !!id&&!v105IsLocalMainRecordId(id);});
      var results=[];for(var i=0;i<contactIds.length;i++)results.push(await localSyncDeleteOne(contactIds[i]));
      var failed=results.filter(function(x){return !x.ok;});return {ok:!failed.length,status:failed.length?409:200,data:{total:results.length,failed:failed,results:results}};
    }
    async function v205RestoreContact(contactId,baseVersion){
      var id=v204Identity(),r=await localSyncRequest('PATCH','/api/v207/admin/contacts/'+encodeURIComponent(String(contactId||''))+'/restore',{workspace_id:id.workspaceId,actor_id:id.deviceId,base_version:Number(baseVersion),reason:'V205 客户端恢复'});
      if(r.ok&&r.data&&r.data.contact){var cache=v204ContactCache();v204ApplyContactSnapshot(cache,r.data.contact);v204SaveContactCache(cache);}await v204PullChanges();return r;
    }
    // V205 删除与恢复统一使用事件/生命周期接口。
    // ================= v89.1 删除同步修复 END =================

    // v99：同步展示协议。把来源端标签/画像/阶段的名称和颜色随联系人一起上传。
    function v99NormalizeStringArray(value99) {
      if (Array.isArray(value99)) {
        var out99 = [];
        value99.forEach(function(item99) {
          var v99 = item99;
          if (item99 && typeof item99 === 'object') v99 = item99.key || item99.value || item99.id || item99.label || '';
          v99 = String(v99 === undefined || v99 === null ? '' : v99).trim();
          if (v99 && out99.indexOf(v99) < 0) out99.push(v99);
        });
        return out99;
      }
      if (value99 && typeof value99 === 'object') {
        return Object.keys(value99).filter(function(key99) { return !!value99[key99]; });
      }
      if (typeof value99 === 'string') {
        var text99 = value99.trim();
        if (!text99) return [];
        if ((text99.charAt(0) === '[' && text99.charAt(text99.length - 1) === ']') || (text99.charAt(0) === '{' && text99.charAt(text99.length - 1) === '}')) {
          try { return v99NormalizeStringArray(JSON.parse(text99)); } catch(e99) {}
        }
        return text99.split(/[,，;；|]/).map(function(x99) { return x99.trim(); }).filter(Boolean);
      }
      return value99 === undefined || value99 === null || value99 === '' ? [] : [String(value99)];
    }
    function v99FindDefByKeyOrLabel(list99, value99) {
      value99 = String(value99 === undefined || value99 === null ? '' : value99).trim();
      for (var i99 = 0; i99 < (list99 || []).length; i99++) {
        var d99 = list99[i99] || {};
        if (String(d99.key || '') === value99 || String(d99.label || '') === value99) return d99;
      }
      return null;
    }
    function v99PresentationItem(value99, list99, fallbackColor99) {
      if (value99 && typeof value99 === 'object') {
        var objectKey99 = value99.key || value99.value || value99.id || value99.label || '';
        var objectDef99 = v99FindDefByKeyOrLabel(list99, objectKey99);
        return {
          key: String(objectKey99 || ''),
          label: String(value99.label || (objectDef99 && objectDef99.label) || objectKey99 || ''),
          color: String(value99.color || (objectDef99 && objectDef99.color) || fallbackColor99)
        };
      }
      var key99 = String(value99 === undefined || value99 === null ? '' : value99).trim();
      var def99 = v99FindDefByKeyOrLabel(list99, key99);
      return { key:key99, label:String((def99 && def99.label) || key99), color:String((def99 && def99.color) || fallbackColor99) };
    }
    function v99BuildPresentationSnapshot(item99) {
      item99 = item99 || {};
      var tag1Raw99 = item99.tag || '';
      var tag1Item99 = v99PresentationItem(tag1Raw99, getTags1(), '#78909c');
      var tag2Items99 = v99NormalizeStringArray(item99.tag2).map(function(key99) {
        return v99PresentationItem(key99, getTags2(), '#78909c');
      });
      var stageItems99 = v99NormalizeStringArray(item99.stages).map(function(key99) {
        return { key:key99, label:getStageLabel(key99), color:'#00a884' };
      });
      return { version:1, tag1:tag1Item99, tag2:tag2Items99, stages:stageItems99 };
    }

    // ==================== v131 他源覆盖层（方案 B） ====================
    // 他源行的编辑/删除不写本地 GM 业务库、不进本源快照，而是写入服务端
    // contact_overrides 表；/api/contacts 读取时由服务端合并覆盖并过滤墓碑，
    // 本源浏览器快照重传不会冲掉管理端改动。
    function isRemoteSyncWrappedId(value) { return isV204ServerContact(value); }
    function remoteOverrideToast(msg) { try { showCopyToast(msg); } catch (e) {} }
    function remoteOverrideFailText(res) { try { return ((res&&res.data&&(res.data.message||res.data.error||res.data.reason||res.data.code))||(res&&res.error)||(res&&res.status)||'连接失败'); } catch(e){return '连接失败';} }
    function remoteOverrideRefresh() { localSyncRefreshAggregate().then(function(){try{renderAll();}catch(e){}}).catch(function(){try{renderAll();}catch(e){}}); }
    function remoteOverrideSaveField(channelId,key,value){var payload=v204FieldPayload(key,value);if(!payload){remoteOverrideToast('⚠️ 字段 '+key+' 尚未接入 V204');return false;}return v204UiWriteResult(v204PatchContact(channelId,payload),'保存');}
    function remoteOverrideSaveStages(channelId,stageKey,checked){var ctx=v204ContactContext(channelId);if(!ctx)return false;var arr=Array.isArray(ctx.contact.customFields&&ctx.contact.customFields['ui.stages'])?ctx.contact.customFields['ui.stages'].slice():[],i=arr.indexOf(stageKey);if(checked&&i<0)arr.push(stageKey);if(!checked&&i>=0)arr.splice(i,1);return v204UiWriteResult(v204PatchContact(channelId,{customFields:{'ui.stages':arr}}),'阶段保存');}
    function remoteOverrideDelete(channelId){var ctx=v204ContactContext(channelId);if(!ctx){remoteOverrideToast('⚠️ V204 联系人不存在');return false;}var c=ctx.contact,msg='确认删除以下联系人？\n\n姓名：'+String(c.display_name||'未命名')+'\n电话：'+String(c.observed_phone||'无')+'\n来源：'+String(c.source_id||'')+'\n当前版本：'+ctx.version+'\n\n删除后联系人将进入回收站，可由管理员恢复。';var accepted=false;try{var w=(typeof managePanelWindow!=='undefined'&&managePanelWindow&&!managePanelWindow.closed)?managePanelWindow:window;accepted=!!w.confirm(msg);}catch(e){try{accepted=!!window.confirm(msg);}catch(_e){}}if(!accepted)return false;v204UiWriteResult(localSyncDeleteOne(ctx.contactId),'删除');return true;}
    function appendRemoteEditableBadge(doc, parent, row) {
      var badge = doc.createElement('span');
      badge.className = 'wa-remote-readonly-badge wa-v106-source-badge';
      badge.textContent = getRemoteSyncSourceLabel(row) + (isRemoteEditableEnabled() ? '·可编辑' : '');
      badge.style.setProperty('--wa-v106-source-color', getSourceBadgeColorV106(row));
      badge.title = isRemoteEditableEnabled()
        ? '这是来自其他源【' + getRemoteSyncSourceLabel(row) + '】的汇总数据；已开启“他源可编辑”，改动保存在服务端覆盖层，来源浏览器快照不会覆盖。'
        : getRemoteSyncReadonlyTitle(row);
      parent.appendChild(badge);
    }
    function v99ValidPresentationItem(item99) {
      return !!(item99 && typeof item99 === 'object' && (item99.key || item99.label));
    }
    function v99NormalizePresentation(record99) {
      record99 = record99 || {};
      var p99 = record99._presentation && typeof record99._presentation === 'object' ? record99._presentation : {};
      var tag1Raw99 = v99ValidPresentationItem(p99.tag1) ? p99.tag1 : (record99.tag || '');
      var tag1Item99 = v99PresentationItem(tag1Raw99, getTags1(), '#78909c');
      var tag2Raw99 = Array.isArray(p99.tag2) && p99.tag2.length ? p99.tag2 : v99NormalizeStringArray(record99.tag2);
      var tag2Items99 = tag2Raw99.map(function(x99) { return v99PresentationItem(x99, getTags2(), '#78909c'); }).filter(v99ValidPresentationItem);
      var stagesRaw99 = Array.isArray(p99.stages) && p99.stages.length ? p99.stages : v99NormalizeStringArray(record99.stages);
      var stageItems99 = stagesRaw99.map(function(x99) {
        if (x99 && typeof x99 === 'object') {
          var key99 = String(x99.key || x99.value || x99.id || x99.label || '');
          return { key:key99, label:String(x99.label || getStageLabel(key99)), color:String(x99.color || '#00a884') };
        }
        var key99 = String(x99 || '');
        return { key:key99, label:getStageLabel(key99), color:'#00a884' };
      }).filter(v99ValidPresentationItem);
      return { version:1, tag1:tag1Item99, tag2:tag2Items99, stages:stageItems99 };
    }
    function v99ResolveRemotePresentation(record99, allData99) {
      record99 = record99 || {};
      var target99 = record99;
      var mainKey99 = record99.mainKey || record99.__rawMainKey || record99.__mainKey || '';
      if (mainKey99 && allData99) {
        var direct99 = allData99[mainKey99];
        if (direct99) target99 = direct99;
      }
      var targetP99 = v99NormalizePresentation(target99);
      var ownP99 = v99NormalizePresentation(record99);
      if (!v99ValidPresentationItem(targetP99.tag1)) targetP99.tag1 = ownP99.tag1;
      if (!targetP99.tag2.length) targetP99.tag2 = ownP99.tag2;
      if (!targetP99.stages.length) targetP99.stages = ownP99.stages;
      return targetP99;
    }

    // ==================== 旧命令协议 下行指令通道（多机共用） ====================
    // 服务端维护每 source 的指令队列；本源浏览器（Leader 标签页）轮询拉取并执行，
    // 执行后回执 ack。用途：
    //   contact.update         —— 管理端在 Dashboard 编辑他源字段后，让来源浏览器本地收敛
    //   contact.delete         —— 管理端删除他源记录后，让来源浏览器本地删除（下次快照移除行）
    //   resync                 —— 全量重传（快照重建）
    //   shared-config.refresh  —— 刷新公共业务配置
    // 覆盖层/墓碑在数据收敛后由服务端自动清理（contact_overrides 不再永久叠加）。
    // V204：旧命令轮询、快照、租约与状态校准协议已物理移除。
    async function localSyncUploadAll() {
      var dev=await v204RegisterDevice();if(!dev.ok)return dev;
      var local={};try{local=loadData()||{};}catch(e){}
      var groups={};
      Object.keys(local).forEach(function(k){
        var x=local[k];if(!x||typeof x!=='object'||v105IsDerivedMainRecord(k,x))return;
        var ch=v204Channel(x),external=v204External(x,k);if(!external)return;
        (groups[ch]||(groups[ch]=[])).push({key:k,row:x,external:external});
      });
      var sourceMap={};
      for(var ch in groups){var reg=await v204RegisterSource(ch);if(!reg.ok)return reg;sourceMap[ch]=String(reg.data.source.source_id||'');}
      Object.keys(groups).forEach(function(ch){groups[ch].forEach(function(item){
        var x=item.row,external=item.external;
        var observed={localKey:String(x._localKey||item.key||external),platformId:String(x.jid||x.threadId||x.id||''),username:String(x.username||''),profileUrl:String(x.profileUrl||x.profileHref||'')};
        v204QueueEvent(v204Event('contact.observe',sourceMap[ch],{channel:ch,externalContactId:external,displayName:String(x.name||x.displayName||x.nickname||''),observedPhone:String(x.phone||x.phoneNumber||''),avatarUrl:String(x.avatar||x.avatarUrl||''),observed:observed}));
      });});
      var flushed=await v204FlushEventQueue(),delta=await v204PullChanges();
      if(delta.ok)LOCAL_SYNC_LAST_STATUS.contacts=(delta.data.contacts||v204CachedRows()).map(v204WrapContact);
      var result={ok:flushed.ok,status:flushed.ok?200:409,data:{queued:flushed.total,remaining:flushed.remaining,allApplied:flushed.ok}};
      LOCAL_SYNC_LAST_STATUS.ok=result.ok;LOCAL_SYNC_LAST_STATUS.message=result.ok?'V205 事件队列提交完成':'V205 队列仍有失败事件';LOCAL_SYNC_LAST_STATUS.lastRequest=result;return result;
    }
    async function localSyncFetchAllContacts() {var res=await v204PullChanges();if(res.ok){var rows=res.data.contacts||v204CachedRows();LOCAL_SYNC_LAST_STATUS.contacts=rows.map(v204WrapContact);LOCAL_SYNC_LAST_STATUS.ok=true;LOCAL_SYNC_LAST_STATUS.message='已应用 V204 增量变更';}else{LOCAL_SYNC_LAST_STATUS.ok=false;LOCAL_SYNC_LAST_STATUS.message='V204 增量拉取失败';}return res;}
    async function localSyncFetchSourcesAndStats() {
      var id=v204Identity(),pair=await Promise.all([localSyncRequest('GET','/api/v207/sources?workspace_id='+encodeURIComponent(id.workspaceId)),localSyncRequest('GET','/api/v207/runtime/diagnostics')]);var sr=pair[0],tr=pair[1];
      if(sr.ok&&sr.data&&Array.isArray(sr.data.items)){LOCAL_SYNC_LAST_STATUS.sources=sr.data.items;var profiles=v204Stored(V204_ACCOUNT_PROFILES_KEY,{})||{};sr.data.items.forEach(function(x){var group=profiles[x.channel]||{};var p=group[String(x.account_identity)]||null;if(p)v204RememberSource(x.channel,x,x.account_identity);});}
      if(tr.ok&&tr.data){var counts=tr.data.counts||{};LOCAL_SYNC_LAST_STATUS.stats={totalContacts:Number(counts.contacts||0),totalSources:Number(counts.sources||0),v204:tr.data};}
      return {ok:!!(sr.ok&&tr.ok),sources:sr,stats:tr,error:!sr.ok?'来源列表读取失败':(!tr.ok?'统计读取失败':'')};
    }
    function getLocalSyncDisplayData() {var merged={},contacts=LOCAL_SYNC_LAST_STATUS.contacts||[];contacts.forEach(function(wrap){if(!wrap)return;var raw=wrap.data||wrap.contact||wrap.item;if(!raw||typeof raw!=='object')return;var item=localSyncSafeClone(raw),key=String(wrap.contactId||(item.__v204&&item.__v204.contactId)||item.id||item._localKey);item.__id=key;item._localKey=key;item.__v204SourceId=wrap.sourceId||'';item.__v204SourceName=wrap.sourceName||'';item._presentation=v99NormalizePresentation(item);merged[key]=item;});return merged;}

    // ========================================================
    // V205 联系人增量同步与展示适配
    // ========================================================
        // V205：无 Leader、无租约、无跨标签页快照。
    function v205BackgroundRender() {
      try {
        var win=managePanelWindow;
        if(win && !win.closed && typeof win.__waRefresh==='function' && !(typeof win.__waIsDetailEditing==='function' && win.__waIsDetailEditing())) win.__waRefresh();
      } catch(e) {}
      try { currentChatId=null; renderNoteBar(); } catch(e) {}
    }

function v892SyncRuntime() {
      if (!LOCAL_SYNC_LAST_STATUS.runtime) {
        LOCAL_SYNC_LAST_STATUS.runtime = {
          service: 'unknown',
          upload: isLocalSyncRealtimeUploadEnabled() ? 'idle' : 'off',
          summary: isLocalSyncAggregateEnabled() ? 'idle' : 'off',
          localCount: 0,
          serverSourceCount: 0,
          totalSources: 0,
          totalContacts: 0,
          lastHealthAt: 0,
          lastUploadAt: 0,
          lastSummaryAt: 0,
          serviceError: '',
          uploadError: '',
          summaryError: '',
          lastError: ''
        };
      }
      return LOCAL_SYNC_LAST_STATUS.runtime;
    }

    function v892SetRuntime(patch) {
      var r = v892SyncRuntime();
      Object.keys(patch || {}).forEach(function(k) {
        r[k] = patch[k];
      });
      try { v892RenderSyncLights(); } catch(e) {}
      try { v205RenderCompactStatus(); } catch(e) {}
    }

    function v205RenderCompactStatus() {
      var el=document.getElementById('wa-v205-compact-status');
      if(!el && managePanelWindow && !managePanelWindow.closed) el=managePanelWindow.document.getElementById('wa-v205-compact-status');
      if(!el) return;
      var r=v892SyncRuntime(), q=0; try { q=v204EventQueue().length; } catch(e) {}
      var service=r.service==='ok'?'ok':(r.service==='error'?'error':'unknown');
      var upload=r.upload==='ok'?'ok':(r.upload==='error'||r.upload==='retry'?'error':'unknown');
      var summary=r.summary==='ok'?'ok':(r.summary==='error'?'error':'unknown');
      el.innerHTML='<span class="wa-sync-dot '+service+'"></span>连接 '+(service==='ok'?'✓':'·')+'　<span class="wa-sync-dot '+upload+'"></span>上传 '+(upload==='ok'?'✓':'·')+'　<span class="wa-sync-dot '+summary+'"></span>接收 '+(summary==='ok'?'✓':'·')+(q?'　待发 '+q:'');
      el.title='V205 无 Leader/租约同步\n服务：'+v892StatusText('service',r.service)+'\n上传：'+v892StatusText('upload',r.upload)+'\n接收：'+v892StatusText('summary',r.summary)+'\n待发事件：'+q;
    }

    function v892LocalCount() {
      try {
        var data = loadData() || {};
        return v105LeafIdsFromData(data).length;
      } catch(e) {
        return 0;
      }
    }

    function v892FmtTime(ts) {
      if (!ts) return '-';
      try {
        var d = new Date(ts);
        var p = function(n) { return n < 10 ? '0' + n : '' + n; };
        return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
      } catch(e) {
        return '-';
      }
    }

    function v892StatusText(type, value) {
      if (type === 'service') {
        if (value === 'ok') return '已连接';
        if (value === 'busy') return '检测中';
        if (value === 'error') return '已断开';
        return '未检测';
      }
      if (type === 'upload') {
        if (value === 'ok') return '上传成功';
        if (value === 'busy') return '上传中';
        if (value === 'pending') return '待上传';
        if (value === 'retry') return '等待重试';
        if (value === 'error') return '上传失败';
        if (value === 'idle') return '无待上传';
        return '关闭';
      }
      if (type === 'summary') {
        if (value === 'ok') return '已汇总';
        if (value === 'busy') return '汇总中';
        if (value === 'stale') return '汇总中断';
        if (value === 'error') return '汇总失败';
        if (value === 'idle') return '待刷新';
        return '关闭';
      }
      return value || '-';
    }

    function v892InjectSyncCss(doc) {
      try {
        doc = doc || ((managePanelWindow && !managePanelWindow.closed) ? managePanelWindow.document : document);
        if (!doc) return;

        var old = doc.getElementById('v892SyncCss');
        if (old) old.remove();

        var style = doc.createElement('style');
        style.id = 'v892SyncCss';
        style.textContent = ''
          + '.wa-panel-title-line{display:flex!important;align-items:center!important;gap:8px!important;flex-wrap:wrap!important;width:100%!important;margin-bottom:4px!important;}'
          + '.wa-panel-title-line h1{flex:0 0 auto!important;margin:0!important;}'
          + '.wa-version-basin{display:inline-flex;align-items:center;justify-content:center;width:62px;height:44px;flex:0 0 auto;filter:drop-shadow(0 2px 4px rgba(98,48,0,.38));cursor:default;}'
          + '.wa-version-basin svg{display:block;width:62px;height:44px;overflow:visible;}'
          + '.wa-version-basin-text{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;font-size:12px;font-weight:900;fill:#fff4b0;stroke:#6f160c;stroke-width:.8px;paint-order:stroke;letter-spacing:-.2px;}'
          + 'body.dark .wa-version-basin{filter:drop-shadow(0 2px 5px rgba(255,193,35,.28));}' 

          + '.wa-title-source-box{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--sub,#54656f);background:var(--card,#fff);border:1px solid var(--border,#d9dee3);border-radius:999px;padding:3px 8px;max-width:100%;}'
          + '.wa-title-source-input{width:auto;min-width:8ch;max-width:min(42ch,40vw);padding:2px 5px!important;border:1px solid var(--border,#d9dee3)!important;border-radius:6px!important;font-size:12px!important;height:23px!important;box-sizing:content-box!important;transition:width .12s ease;background:var(--card,#fff)!important;color:var(--text,#111)!important;}'
          + '.wa-title-source-id{font-size:11px;color:var(--sub,#64748b);max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}'

          + '.wa-title-actions{display:inline-flex;align-items:center;gap:6px;flex-wrap:wrap;}'

          + '#wa-local-sync-bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:7px 10px;margin:6px 0 8px;border:1px solid var(--border,#d9dee3);background:var(--card,#fff);border-radius:10px;font-size:12px;color:var(--text,#111);white-space:normal;overflow:visible;line-height:1.45;}'
          + '.wa-sync-status-mini{display:flex;align-items:center;gap:7px;flex-wrap:wrap;font-size:12px;line-height:1.5;white-space:normal;min-width:0;flex:1 1 100%;}'
          + '.wa-sync-status-item{display:inline-flex;align-items:center;gap:3px;white-space:nowrap;color:#334155;min-height:20px;}'
          + 'body.dark .wa-sync-status-item{color:#cbd5e1;}'

          + '.wa-sync-toggle-label{font-weight:700;cursor:pointer;user-select:none;}'
          + '.wa-sync-toggle-label input{margin:0 2px 0 0;vertical-align:middle;}'

          + '.wa-sync-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:2px;background:#9ca3af;flex:0 0 auto;}'
          + '.wa-sync-dot.ok{background:#16a34a;animation:v892PulseOk 1.5s infinite;}'
          + '.wa-sync-dot.busy{background:#eab308;animation:v892PulseBusy 1s infinite;}'
          + '.wa-sync-dot.idle{background:#2563eb;animation:v892PulseIdle 2s infinite;}'
          + '.wa-sync-dot.pending,.wa-sync-dot.retry,.wa-sync-dot.stale{background:#f59e0b;animation:v892PulseBusy 1.2s infinite;}'
          + '.wa-sync-dot.error{background:#dc2626;animation:v892PulseError .7s infinite;}'
          + '.wa-sync-dot.unknown{background:#94a3b8;animation:v892PulseIdle 2.2s infinite;}'
          + '.wa-sync-dot.off{background:#9ca3af;animation:none;}'

          + '.wa-sync-error-text{color:#dc2626;font-weight:700;max-width:520px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}'

          + '.wa-sync-btn{border:1px solid #cbd5e1;background:#fff;color:#334155;border-radius:999px;padding:4px 10px;font-size:12px;line-height:1.2;cursor:pointer;box-shadow:0 1px 2px rgba(15,23,42,.06);transition:all .15s ease;white-space:nowrap;}'
          + '.wa-sync-btn:hover{transform:translateY(-1px);box-shadow:0 3px 8px rgba(15,23,42,.12);border-color:#94a3b8;}'
          + '.wa-sync-btn:disabled{opacity:.55;cursor:not-allowed;transform:none;}'
          + '.wa-sync-btn.primary{background:#2563eb;color:#fff;border-color:#2563eb;}'
          + '.wa-sync-btn.green{background:#16a34a;color:#fff;border-color:#16a34a;}'
          + '.wa-sync-btn.purple{background:#7c3aed;color:#fff;border-color:#7c3aed;}'
          + '.wa-sync-btn.gray{background:#475569;color:#fff;border-color:#475569;}'
          + 'body.dark .wa-sync-btn{background:#1e293b;color:#e2e8f0;border-color:#334155;}'

          + '@media(max-width:900px){'
          + '.wa-title-source-id{max-width:180px;}'
          + '.wa-title-actions{flex:1 1 100%;}'
          + '}'


          + '.wa-v2021-health{border-color:#f9a8d4!important;background:linear-gradient(135deg,#fff7fb,#fff1f7)!important;color:#3f2433!important;box-shadow:0 8px 24px rgba(190,24,93,.10)!important}.wa-v2021-health>summary{background:linear-gradient(90deg,#fce7f3,#fff1f7)!important;color:#831843!important}.wa-v2021-body th{background:#fce7f3!important;color:#9d174d!important}.wa-v2021-body td,.wa-v2021-body th{border-color:#fbcfe8!important}.wa-sync-btn.primary,.wa-sync-btn.purple,.wa-sync-btn.green{background:#ec4899!important;border-color:#db2777!important}.wa-title-source-box{border-color:#f9a8d4!important;background:#fff1f7!important}.wa-sync-toggle-label{color:#9d174d!important}'
          + '@keyframes v892PulseOk{0%{box-shadow:0 0 0 0 rgba(22,163,74,.65);}70%{box-shadow:0 0 0 7px rgba(22,163,74,0);}100%{box-shadow:0 0 0 0 rgba(22,163,74,0);}}'
          + '@keyframes v892PulseBusy{0%{box-shadow:0 0 0 0 rgba(234,179,8,.7);}70%{box-shadow:0 0 0 7px rgba(234,179,8,0);}100%{box-shadow:0 0 0 0 rgba(234,179,8,0);}}'
          + '@keyframes v892PulseIdle{0%{box-shadow:0 0 0 0 rgba(37,99,235,.55);}70%{box-shadow:0 0 0 6px rgba(37,99,235,0);}100%{box-shadow:0 0 0 0 rgba(37,99,235,0);}}'
          + '@keyframes v892PulseError{0%{box-shadow:0 0 0 0 rgba(220,38,38,.8);}70%{box-shadow:0 0 0 7px rgba(220,38,38,0);}100%{box-shadow:0 0 0 0 rgba(220,38,38,0);}}';

        doc.head.appendChild(style);
      } catch(e) {}
    }


    function v894AutoSizeSourceInput(input) {
      try {
        if (!input) return;

        var doc = input.ownerDocument || document;
        var measurer = doc.getElementById('__waSourceInputMeasurer');
        if (!measurer) {
          measurer = doc.createElement('span');
          measurer.id = '__waSourceInputMeasurer';
          measurer.style.cssText =
            'position:absolute;left:-99999px;top:-99999px;visibility:hidden;white-space:pre;font-size:12px;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;font-weight:400;';
          doc.body.appendChild(measurer);
        }

        measurer.textContent = input.value || input.placeholder || '';
        var w = Math.ceil(measurer.getBoundingClientRect().width) + 18;
        var min = 8 * 12;
        var max = Math.max(180, Math.min(420, ((doc.defaultView && doc.defaultView.innerWidth) || 1200) * 0.4));

        input.style.width = Math.max(min, Math.min(max, w)) + 'px';
      } catch(e) {}
    }

    function v894EnsureTitleSourceBox(doc) {
      try {
        doc = doc || ((managePanelWindow && !managePanelWindow.closed) ? managePanelWindow.document : document);
        var toolbar = doc.querySelector('.toolbar');
        var h1 = toolbar && toolbar.querySelector('h1');
        if (!toolbar || !h1) return;

        if (!h1.parentElement.classList.contains('wa-panel-title-line')) {
          var line = doc.createElement('div');
          line.className = 'wa-panel-title-line';
          toolbar.insertBefore(line, h1);
          line.appendChild(h1);
        }

        var titleLine = h1.parentElement;
        // v124：移除旧 120 前置徽标；新聚宝盆位于系统名称后方，版本号显示在盆身内。
        var oldBasin117 = doc.getElementById('wa-v117-basin-badge');
        if (oldBasin117) oldBasin117.remove();
        if (!doc.getElementById('wa-v124-basin-badge')) {
          var basin124 = doc.createElement('span');
          basin124.id = 'wa-v124-basin-badge';
          basin124.className = 'wa-version-basin';
          basin124.title = SYSTEM_NAME_V124 + ' · ' + getDisplayVersionV124();
          basin124.setAttribute('role', 'img');
          basin124.setAttribute('aria-label', '当前版本 ' + getDisplayVersionV124());
          basin124.innerHTML = '<svg viewBox="0 0 92 66" aria-hidden="true">' +
            '<defs><linearGradient id="waBasinGoldV124" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#fff8b8"/><stop offset="45%" stop-color="#ffd43b"/><stop offset="100%" stop-color="#b66a00"/></linearGradient><linearGradient id="waBasinRedV124" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#d63b21"/><stop offset="100%" stop-color="#730906"/></linearGradient></defs>' +
            '<ellipse cx="28" cy="14" rx="11" ry="6" fill="url(#waBasinGoldV124)" stroke="#9a5700" stroke-width="2" transform="rotate(-15 28 14)"/><ellipse cx="46" cy="10" rx="12" ry="6" fill="url(#waBasinGoldV124)" stroke="#9a5700" stroke-width="2"/><ellipse cx="64" cy="14" rx="11" ry="6" fill="url(#waBasinGoldV124)" stroke="#9a5700" stroke-width="2" transform="rotate(15 64 14)"/>' +
            '<path d="M10 22 Q46 34 82 22 L77 34 Q46 45 15 34 Z" fill="url(#waBasinGoldV124)" stroke="#8c4e00" stroke-width="2"/><path d="M16 32 Q21 62 46 64 Q71 62 76 32 Q46 45 16 32 Z" fill="url(#waBasinRedV124)" stroke="#e2ad25" stroke-width="2.5"/><path d="M25 57 Q46 63 67 57" fill="none" stroke="#f6c847" stroke-width="2" opacity=".8"/>' +
            '<text class="wa-version-basin-text" x="46" y="53" text-anchor="middle">' + getDisplayVersionV124() + '</text></svg>';
          titleLine.insertBefore(basin124, h1.nextSibling);
        }
        var box = doc.getElementById('wa-title-source-box');

        if (!box) {
          box = doc.createElement('span');
          box.id = 'wa-title-source-box';
          box.className = 'wa-title-source-box';
          box.innerHTML =
            '<b>当前源：</b>' +
            '<input id="wa-local-sync-source-name" class="wa-title-source-input" value="' + escapeHtml(getLocalSyncSourceName()) + '" title="修改后失焦自动保存源名称">' +
            '<span id="wa-local-sync-source-id" class="wa-title-source-id">ID：' + escapeHtml(getLocalSyncSourceId()) + '</span>';
          titleLine.appendChild(box);
        }

        var actions = doc.getElementById('wa-title-sync-actions');
        if (!actions) {
          actions = doc.createElement('span');
          actions.id = 'wa-title-sync-actions';
          actions.className = 'wa-title-actions';
          actions.innerHTML = ''; // 旧来源注册：状态与链路已合并到下方综合面板
          var details=actions.querySelector('#wa-v202-runtime');
          if(details) details.addEventListener('toggle',async function(){if(!details.open)return;var out=actions.querySelector('#wa-v202-runtime-body');var r=await localSyncRequest('GET','/api/v207/runtime/diagnostics');out.textContent=JSON.stringify({server:r.data||r,client:v205ClientDiagnosticSnapshot(),lastRequest:LOCAL_SYNC_LAST_STATUS.lastRequest||null},null,2);});
          titleLine.appendChild(actions);
        }

        var inp = doc.getElementById('wa-local-sync-source-name');
        if (inp) v894AutoSizeSourceInput(inp);
      } catch(e) {}
    }

    function v892RenderSyncLights() {
      try {
        var doc = (managePanelWindow && !managePanelWindow.closed) ? managePanelWindow.document : document;
        var r = v892SyncRuntime();
        r.localCount = v892LocalCount();

        var service = r.service || 'unknown';
        var upload = isLocalSyncRealtimeUploadEnabled() ? (r.upload || 'idle') : 'off';
        var summary = isLocalSyncAggregateEnabled() ? (r.summary || 'idle') : 'off';

        function setHtml(id, html) {
          var el = doc.getElementById(id);
          if (el) el.innerHTML = html;
        }

        setHtml('wa-sync-service-state', '<span class="wa-sync-dot ' + service + '"></span>连接：<b>' + v892StatusText('service', service) + '</b>');
        setHtml('wa-sync-upload-state', '<span class="wa-sync-dot ' + upload + '"></span><b>' + v892StatusText('upload', upload) + '</b>');
        setHtml('wa-sync-summary-state', '<span class="wa-sync-dot ' + summary + '"></span><b>' + v892StatusText('summary', summary) + '</b>');
        setHtml('wa-sync-local-count', '<b>' + (r.localCount || 0) + '</b>');
        setHtml('wa-sync-server-count', '<b>' + (r.serverSourceCount || 0) + '</b>');
        setHtml('wa-sync-source-count', '<b>' + (r.totalSources || 0) + '</b>');
        setHtml('wa-sync-contact-count', '<b>' + (r.totalContacts || 0) + '</b>');
        setHtml('wa-sync-upload-time', '<b>' + v892FmtTime(r.lastUploadAt) + '</b>');
        setHtml('wa-sync-summary-time', '<b>' + v892FmtTime(r.lastSummaryAt) + '</b>');
        setHtml('wa-v205-worker-state','V205 单一事件 Worker');

        var err = doc.getElementById('wa-sync-error-text');
        if (err) {
          var errors = [r.serviceError, r.uploadError, r.summaryError, r.lastError].filter(Boolean);
          err.style.display = errors.length ? 'inline-flex' : 'none';
          err.title = errors.join('\n');
          err.textContent = errors.length ? ('错误：' + errors.join('；')) : '';
        }

        var upToggle = doc.getElementById('wa-local-sync-realtime-upload');
        if (upToggle) upToggle.checked = isLocalSyncRealtimeUploadEnabled();

        var aggToggle = doc.getElementById('wa-local-sync-aggregate');
        if (aggToggle) aggToggle.checked = isLocalSyncAggregateEnabled();

        var nameInput = doc.getElementById('wa-local-sync-source-name');
        if (nameInput && doc.activeElement !== nameInput) {
          nameInput.value = getLocalSyncSourceName();
          v894AutoSizeSourceInput(nameInput);
        }

        var idEl = doc.getElementById('wa-local-sync-source-id');
        if (idEl) idEl.textContent = 'ID：' + getLocalSyncSourceId();
        var us=v204Registry(), owned=Object.keys(us.accounts||{}), pending=v204EventQueue(), pendingCount=pending.length;
        var errors2=[r.serviceError,r.uploadError,r.summaryError,r.lastError].filter(Boolean);
        var overall=errors2.length||service==='error'?'异常':((upload==='busy'||summary==='busy'||pendingCount>0)?'处理中':'系统正常');
        setHtml('wa-v2021-overall',overall); setHtml('wa-v2021-service',v892StatusText('service',service));
        setHtml('wa-v2021-source',escapeHtml(getLocalSyncSourceName())); setHtml('wa-v2021-pending',pendingCount);
        setHtml('wa-v2021-summary',v892StatusText('summary',summary)); setHtml('wa-v2021-last',v892FmtTime(Math.max(Number(r.lastUploadAt||0),Number(r.lastSummaryAt||0))));
        setHtml('wa-v2021-owned',owned.length?'正常（'+owned.length+' 账号）':'尚未注册');
        setHtml('wa-v2021-source-map',owned.map(function(key){var a=us.accounts[key]||{};return escapeHtml(String(a.channel||key))+' → '+escapeHtml(String(a.sourceId||'').slice(0,12))+'…';}).join('<br>')||'首次上传时自动注册');
        var od=doc.getElementById('wa-v2021-overall-dot'); if(od) od.className='wa-sync-dot '+(overall==='异常'?'error':overall==='系统正常'?'ok':'busy');
        setHtml('wa-v2021-raw',escapeHtml(localSyncDiagText()+'\n\nV205 来源注册表：\n'+JSON.stringify(us,null,2)));
      } catch(e) {}
    }

    async function v892RefreshCounts() {
      try {
        await localSyncFetchSourcesAndStats();

        var r = v892SyncRuntime();

        if (LOCAL_SYNC_LAST_STATUS.sources) {
          r.totalSources = LOCAL_SYNC_LAST_STATUS.sources.length;
        }

        if (LOCAL_SYNC_LAST_STATUS.stats) {
          r.totalContacts = LOCAL_SYNC_LAST_STATUS.stats.totalContacts || 0;
        }

        var cr = await localSyncRequest(
          'GET',
          '/api/v207/contacts?workspace_id=' + encodeURIComponent(v204Identity().workspaceId) +
          '&source_id=' + encodeURIComponent(getLocalSyncSourceId()) + '&limit=1'
        );

        if (cr && cr.ok && cr.data) {
          r.serverSourceCount = Array.isArray(cr.data.items) ? cr.data.items.length : 0;
        }

        v892RenderSyncLights();
      } catch(e) {
        v892SetRuntime({
          lastError: '统计刷新失败：' + ((e && e.message) || e)
        });
      }
    }

    async function v892InitSyncStatus(renderAllFn) {
      var doc = (managePanelWindow && !managePanelWindow.closed) ? managePanelWindow.document : document;
      v892InjectSyncCss(doc);
      var runtime = v892SyncRuntime();
      runtime.upload = isLocalSyncRealtimeUploadEnabled() ? (runtime.upload === 'off' ? 'idle' : (runtime.upload || 'idle')) : 'off';
      runtime.summary = isLocalSyncAggregateEnabled() ? (runtime.summary === 'off' ? 'idle' : (runtime.summary || 'idle')) : 'off';
      v892RenderSyncLights();
      try {
        var health = await localSyncHealthCheck({ silent:false });
        if (health && health.ok) {
          await v892RefreshCounts();
          if (isLocalSyncAggregateEnabled()) v205SchedulePull(0);
          if (isLocalSyncRealtimeUploadEnabled()) v205WakeUpload('panel-init', 0);
        }
      } catch (error) {
        v892SetRuntime({ service:'error', serviceError:'初始化检测失败：' + String(error && error.message || error) });
        v206ReportUiError('sync-status-init', error);
      }
      v892RenderSyncLights();
      if (typeof renderAllFn === 'function') renderAllFn();
    }

    
    function v2021InjectHealthCss(doc){try{if(doc.getElementById('wa-v2021-health-css'))return;var st=doc.createElement('style');st.id='wa-v2021-health-css';st.textContent='.wa-v2021-health{display:block;width:100%;background:#fff;border:1px solid #dbe3ef;border-radius:8px;color:#26344d}.wa-v2021-health>summary{cursor:pointer;display:flex;align-items:center;gap:5px;padding:7px 10px;list-style:none;white-space:nowrap}.wa-v2021-health>summary small{color:#718096}.wa-v2021-body{padding:0 10px 10px}.wa-v2021-body table{width:100%;border-collapse:collapse;font-size:12px}.wa-v2021-body th,.wa-v2021-body td{padding:7px 9px;border:1px solid #e5eaf2;text-align:left}.wa-v2021-body th{background:#f4f7fb}.wa-v2021-advanced{margin-top:8px}.wa-v2021-advanced pre{max-height:240px;overflow:auto;background:#101827;color:#d8e4f5;padding:10px;border-radius:6px;white-space:pre-wrap}';(doc.head||doc.documentElement).appendChild(st);}catch(e){}}
    function buildLocalSyncBarHtml() {
      return '<details id="wa-v2021-health" class="wa-v2021-health">'
        + '<summary><span id="wa-v2021-overall-dot" class="wa-sync-dot unknown"></span><b id="wa-v2021-overall">系统检测中</b>'
        + '<span>｜服务 <b id="wa-v2021-service">—</b></span><span>｜本源 <b id="wa-v2021-source">—</b></span>'
        + '<span>｜待上传 <b id="wa-v2021-pending">0</b></span><span>｜汇总 <b id="wa-v2021-summary">—</b></span>'
        + '<span>｜最后同步 <b id="wa-v2021-last">—</b></span><small>（点击展开）</small></summary>'
        + '<div class="wa-v2021-body"><table><thead><tr><th>链路</th><th>状态</th><th>数量/时间</th><th>说明</th></tr></thead><tbody>'
        + '<tr><td>中心服务</td><td id="wa-sync-service-state"></td><td id="wa-v2021-service-time">实时</td><td>HTTP 健康检查与 SQLite</td></tr>'
        + '<tr><td>来源身份</td><td id="wa-v2021-owned"></td><td id="wa-sync-source-count"></td><td id="wa-v2021-source-map">渠道级服务端来源</td></tr>'
        + '<tr><td>上传链路</td><td id="wa-sync-upload-state"></td><td id="wa-sync-upload-time"></td><td><label><input type="checkbox" id="wa-local-sync-realtime-upload" '+(isLocalSyncRealtimeUploadEnabled()?'checked':'')+'> 实时上传</label></td></tr>'
        + '<tr><td>接收链路</td><td id="wa-sync-summary-state"></td><td id="wa-sync-summary-time"></td><td><label><input type="checkbox" id="wa-local-sync-aggregate" '+(isLocalSyncAggregateEnabled()?'checked':'')+'> 自动接收</label></td></tr>'
        + '<tr><td>数据计数</td><td>本地 <b id="wa-sync-local-count"></b></td><td>联系人 <b id="wa-sync-contact-count"></b></td><td>服务端来源 <b id="wa-sync-server-count"></b></td></tr>'
        + '<tr><td>页面协调</td><td id="wa-v205-worker-state">选举中</td><td>幂等事件</td><td>eventId 去重，无 Leader/租约</td></tr>'
        + '</tbody></table><div id="wa-sync-error-text" class="wa-sync-error-text" style="display:none"></div>'
        + '<details class="wa-v2021-advanced"><summary>高级诊断（技术信息）</summary><pre id="wa-v2021-raw">展开后点击“同步诊断”查看完整信息</pre></details></div></details>';
    }
    function bindLocalSyncBarEvents(renderAllFn, rootDoc) {
      var doc = rootDoc || (managePanelWindow && !managePanelWindow.closed ? managePanelWindow.document : document);
      var panelWin = (doc && doc.defaultView) || managePanelWindow || window;
      try{v205RestorePanelState(doc);}catch(e){}

      try {
        v892InjectSyncCss(doc);
        v2021InjectHealthCss(doc);
        v894EnsureTitleSourceBox(doc);
      } catch(e) {}

      var nameInput = doc.getElementById('wa-local-sync-source-name');
      var upToggle = doc.getElementById('wa-local-sync-realtime-upload');
      var aggToggle = doc.getElementById('wa-local-sync-aggregate');
      var uploadBtn = doc.getElementById('wa-local-sync-upload-once');
      var refreshBtn = doc.getElementById('wa-local-sync-refresh-aggregate');
      var checkBtn = doc.getElementById('wa-local-sync-check');
      var diagBtn = doc.getElementById('wa-local-sync-diag');
      var reconcileBtn = doc.getElementById('wa-local-sync-reconcile-source');

      function refresh() {
        if (typeof renderAllFn === 'function') renderAllFn();
      }

      function show(msg) {
        try {
          panelWin.alert(msg);
        } catch(e) {
          try { alert(msg); } catch(_e) {}
        }
      }

      function confirmSafe(msg) {
        try {
          return panelWin.confirm(msg);
        } catch(e) {
          try { return confirm(msg); } catch(_e) { return false; }
        }
      }

      function setBtnBusy(btn, text) {
        if (!btn) return;
        btn.disabled = true;
        btn.__oldText = btn.textContent;
        btn.textContent = text || '处理中...';
      }

      function restoreBtn(btn, fallbackText) {
        if (!btn) return;
        btn.disabled = false;
        btn.textContent = btn.__oldText || fallbackText || btn.textContent;
        delete btn.__oldText;
      }

      if (nameInput && !nameInput.__v897Bound) {
        nameInput.__v897Bound = true;
        nameInput.__v893OldValue = nameInput.value;

        nameInput.addEventListener('input', function() {
          v894AutoSizeSourceInput(nameInput);
        });

        async function autoSaveSourceName() {
          var newName = String(nameInput.value || '').trim();

          if (!newName) {
            nameInput.value = getLocalSyncSourceName();
            v894AutoSizeSourceInput(nameInput);
            return;
          }

          if (newName === nameInput.__v893OldValue) return;

          nameInput.__v893OldValue = setLocalSyncSourceName(newName);
          nameInput.value = nameInput.__v893OldValue;
          v894AutoSizeSourceInput(nameInput);

          if (isLocalSyncRealtimeUploadEnabled()) {
            try { scheduleLocalSyncAutoUpload(); } catch(e) {}
          }

          try { v892RenderSyncLights(); } catch(e) {}
          show('修改源名称成功');
        }

        nameInput.addEventListener('blur', autoSaveSourceName);
        nameInput.addEventListener('keydown', function(e) {
          if (e.key === 'Enter') {
            e.preventDefault();
            nameInput.blur();
          }
        });

        v894AutoSizeSourceInput(nameInput);
      }

      if (upToggle) {
        upToggle.onchange = async function() {
          var on = !!upToggle.checked;
          setLocalSyncRealtimeUploadEnabled(on);

          if (on) {
            v892SetRuntime({ upload:'busy', lastError:'' });

            var r = await localSyncUploadOnly();

            v892SetRuntime({
              upload: r && r.ok ? 'ok' : 'error',
              lastUploadAt: r && r.ok ? Date.now() : v892SyncRuntime().lastUploadAt,
              lastError: r && r.ok ? '' : ('上传失败：' + ((r && (r.error || r.status)) || '未知错误'))
            });

            await v892RefreshCounts();
          } else {
            clearTimeout(LOCAL_SYNC_UPLOAD_TIMER); v892SetRuntime({ upload:'off', uploadError:'' });
          }

          refresh();
        };
      }

      if (aggToggle) {
        aggToggle.onchange = async function() {
          var on = !!aggToggle.checked;
          setLocalSyncAggregateEnabled(on);

          if (on) {
            v892SetRuntime({ summary:'busy', lastError:'' });

            var r = await localSyncRefreshAggregate();

            v892SetRuntime({
              summary: r && r.ok ? 'ok' : 'error',
              lastSummaryAt: r && r.ok ? Date.now() : v892SyncRuntime().lastSummaryAt,
              lastError: r && r.ok ? '' : ('汇总失败：' + ((r && (r.error || r.status)) || '未知错误'))
            });

            await v892RefreshCounts();
            startLocalSyncAggregatePolling();
          } else {
            stopLocalSyncAggregatePolling();
            LOCAL_SYNC_LAST_STATUS.contacts = [];
            v892SetRuntime({ summary:'off', summaryError:'' });
          }

          refresh();
        };
      }

      if (uploadBtn) {
        uploadBtn.onclick = async function() {
          setBtnBusy(uploadBtn, '上传中...');
          v892SetRuntime({ upload:'busy', lastError:'' });

          try {
            var r = await localSyncUploadOnly();

            v892SetRuntime({
              upload: r && r.ok ? 'ok' : 'error',
              lastUploadAt: r && r.ok ? Date.now() : v892SyncRuntime().lastUploadAt,
              lastError: r && r.ok ? '' : ('上传失败：' + ((r && (r.error || r.status)) || '未知错误'))
            });

            await v892RefreshCounts();
            refresh();

            show(r && r.ok ? '本源上传完成。' : ('上传失败：' + ((r && (r.error || r.status)) || '请确认本地服务。')));
          } catch(e) {
            v892SetRuntime({
              upload:'error',
              lastError:'上传异常：' + ((e && e.message) || e)
            });
            show('上传失败：' + ((e && e.message) || e));
          } finally {
            restoreBtn(uploadBtn, '上传一次');
          }
        };
      }

      if (refreshBtn) {
        refreshBtn.onclick = async function() {
          setBtnBusy(refreshBtn, '刷新中...');
          v892SetRuntime({ summary:'busy', lastError:'' });

          try {
            var r = await localSyncRefreshAggregate();

            v892SetRuntime({
              summary: r && r.ok ? 'ok' : 'error',
              lastSummaryAt: r && r.ok ? Date.now() : v892SyncRuntime().lastSummaryAt,
              lastError: r && r.ok ? '' : ('刷新失败：' + ((r && (r.error || r.status)) || '未知错误'))
            });

            await v892RefreshCounts();
            refresh();

            show(r && r.ok ? '接收更新完成。' : ('刷新失败：' + ((r && (r.error || r.status)) || '请确认本地服务。')));
          } catch(e) {
            v892SetRuntime({
              summary:'error',
              lastError:'刷新异常：' + ((e && e.message) || e)
            });
            show('刷新失败：' + ((e && e.message) || e));
          } finally {
            restoreBtn(refreshBtn, '刷新汇总');
          }
        };
      }

      if (checkBtn) {
        checkBtn.onclick = async function() {
          setBtnBusy(checkBtn, '检测中...');
          v892SetRuntime({ service:'busy', lastError:'' });

          try {
            var r = await localSyncHealthCheck();
            await localSyncFetchSourcesAndStats();
            await v892RefreshCounts();

            v892SetRuntime({
              service: r && r.ok ? 'ok' : 'error',
              lastError: r && r.ok ? '' : ('连接失败：' + ((r && (r.error || r.status)) || '未知错误'))
            });

            refresh();

            show(r && r.ok ? '连接成功。' : ('连接失败：' + ((r && (r.error || r.status)) || '未知错误')));
          } catch(e) {
            v892SetRuntime({
              service:'error',
              lastError:'检测异常：' + ((e && e.message) || e)
            });
            show('连接检测失败：' + ((e && e.message) || e));
          } finally {
            restoreBtn(checkBtn, '检测连接');
          }
        };
      }

      if (diagBtn) {
        diagBtn.onclick = function() {
          show(localSyncDiagText() + '\n\nv89.7运行状态：\n' + JSON.stringify(v892SyncRuntime(), null, 2));
        };
      }

      if (reconcileBtn) {
        reconcileBtn.textContent = '重新上传本源';
        reconcileBtn.onclick = async function() {
          if (!confirmSafe('确定重新上传当前浏览器中的联系人吗？\n\nV205 将按统一事件协议提交本地联系人，不执行旧来源快照校准，也不会删除服务端其他联系人。')) return;
          setBtnBusy(reconcileBtn, '上传中...');
          v892SetRuntime({ upload:'busy', lastError:'' });
          try {
            var r=await localSyncUploadAll();
            await v204PullChanges();
            v892SetRuntime({upload:r&&r.ok?'ok':'error',lastUploadAt:r&&r.ok?Date.now():v892SyncRuntime().lastUploadAt,lastError:r&&r.ok?'':('上传失败：'+((r&&(r.error||r.status))||'未知错误'))});
            await v892RefreshCounts();
            if (isLocalSyncAggregateEnabled()) await localSyncRefreshAggregate();
            refresh();
            show(r&&r.ok?'V204 本源联系人重新上传完成。':('重新上传失败：'+((r&&(r.error||r.status))||'未知错误')));
          } catch(e) {
            v892SetRuntime({upload:'error',lastError:'上传异常：'+((e&&e.message)||e)});
            show('重新上传异常：'+((e&&e.message)||e));
          } finally { restoreBtn(reconcileBtn, '重新上传本源'); }
        };
      }

      setTimeout(v892RenderSyncLights, 0);
    }
    // ================= v77 本机多数据源同步模块 END =================

    function openManagePanel() {
    if (managePanelWindow && !managePanelWindow.closed) {
      managePanelWindow.focus();
      return;
    }
    runLinkScan();
    // v130：独立 Dashboard 直接复用当前顶层页面；渠道模式仍沿用原弹窗管理面板。
    var win = STANDALONE_DASHBOARD_MODE ? window : window.open('', 'wa_remark_manage_panel');
    if (!win) { alert('\u65b0\u6807\u7b7e\u9875\u88ab\u62e6\u622a\uff0c\u8bf7\u5141\u8bb8\u672c\u7ad9\u5f39\u51fa\u65b0\u9875\u9762\u540e\u91cd\u8bd5\u3002'); return; }
    managePanelWindow = win;
    win.document.open();
    win.document.write(buildManagePanelShell());
    win.document.close();
    if (STANDALONE_DASHBOARD_MODE) {
      try {
        win.document.documentElement.setAttribute('data-wa-dashboard-mode', 'standalone');
        win.document.title = '聚宝盆客户信息管理系统 v130 · 独立 Dashboard';
      } catch(e) {}
    }

      try {
        var v89Style = win.document.createElement('style');
        v89Style.textContent = '.wa-remote-readonly-row{background:#f8fafc!important;box-shadow:inset 4px 0 0 #94a3b8;}.wa-remote-readonly-row:hover{background:#f1f5f9!important;}.wa-remote-readonly-row textarea,.wa-remote-readonly-row input,.wa-remote-readonly-row select,.wa-remote-readonly-input{background:#f1f5f9!important;color:#64748b!important;cursor:not-allowed!important;}.wa-remote-readonly-badge{display:inline-block;padding:2px 7px;border-radius:999px;background:#e2e8f0;color:#334155;font-weight:700;font-size:12px;white-space:nowrap;line-height:1.4;}.wa-local-origin-badge{display:inline-block;padding:2px 7px;border-radius:999px;background:#dcfce7;color:#166534;font-weight:700;font-size:12px;white-space:nowrap;line-height:1.4;}.local-sync-readonly-tip{color:#64748b;font-size:12px;margin-left:8px;}body.dark .wa-remote-readonly-row{background:#1e293b!important;box-shadow:inset 4px 0 0 #64748b;}body.dark .wa-remote-readonly-row:hover{background:#263449!important;}body.dark .wa-remote-readonly-row textarea,body.dark .wa-remote-readonly-row input,body.dark .wa-remote-readonly-row select,body.dark .wa-remote-readonly-input{background:#0f172a!important;color:#94a3b8!important;}body.dark .wa-remote-readonly-badge{background:#334155;color:#cbd5e1;}body.dark .wa-local-origin-badge{background:#14532d;color:#bbf7d0;}.wa-v106-source-badge{display:inline-block!important;box-sizing:border-box;max-width:100%;padding:2px 7px!important;border:0!important;border-radius:999px!important;background:var(--wa-v106-source-color)!important;color:#fff!important;font-family:inherit;font-size:11px!important;font-weight:700;line-height:1.35;white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important;vertical-align:middle;}body.dark .wa-v106-source-badge{background:var(--wa-v106-source-color)!important;color:#fff!important;}';
        win.document.head.appendChild(v89Style);
      } catch(e) {}

      // v99：他源严格只读样式。底色覆盖每个 td；徽章自身样式与颜色不被行底色覆盖。
      try {
        var v99Style = win.document.createElement('style');
        v99Style.id = 'wa-v99-remote-readonly-style';
        v99Style.textContent = ''
          + ':root{--wa-v99-remote-bg:#cbd2d9;--wa-v99-remote-hover:#b8c1ca;--wa-v99-remote-text:#26313b;--wa-v99-remote-border:#9aa6b2;}'
          + 'tr.wa-remote-readonly-row, #mainTable tr.wa-remote-readonly-row>td, #mainTable tr.wa-remote-readonly-row>td.cell-empty, #mainTable tr.wa-remote-readonly-row>td.col-sticky-avatar, #mainTable tr.wa-remote-readonly-row>td.col-sticky-name, body.dark #mainTable tr.wa-remote-readonly-row>td.col-sticky-avatar, body.dark #mainTable tr.wa-remote-readonly-row>td.col-sticky-name{background:var(--wa-v99-remote-bg)!important;color:var(--wa-v99-remote-text)!important;filter:none!important;cursor:not-allowed!important;}'
          + 'tr.wa-remote-readonly-row:hover, #mainTable tr.wa-remote-readonly-row:hover>td, #mainTable tr.wa-remote-readonly-row:hover>td.cell-empty, #mainTable tr.wa-remote-readonly-row:hover>td.col-sticky-avatar, #mainTable tr.wa-remote-readonly-row:hover>td.col-sticky-name, body.dark #mainTable tr.wa-remote-readonly-row:hover>td.col-sticky-avatar, body.dark #mainTable tr.wa-remote-readonly-row:hover>td.col-sticky-name{background:var(--wa-v99-remote-hover)!important;color:var(--wa-v99-remote-text)!important;filter:none!important;cursor:not-allowed!important;}'
          + 'tr.wa-remote-readonly-row *{cursor:not-allowed!important;}'
          + 'tr.wa-remote-readonly-row .wa-v99-static{display:block;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;min-height:20px;color:var(--wa-v99-remote-text)!important;background:transparent!important;user-select:text;}'
          + 'tr.wa-remote-readonly-row .wa-v99-link-wrap{display:flex;gap:4px;align-items:center;flex-wrap:wrap;white-space:normal!important;overflow-wrap:anywhere;word-break:break-word;max-width:100%;}'
          + 'tr.wa-remote-readonly-row .wa-remote-readonly-badge{display:inline;white-space:normal!important;overflow-wrap:anywhere;word-break:break-word;background:transparent!important;color:var(--wa-v99-remote-text)!important;border:1px solid var(--wa-v99-remote-border);}'
          + 'tr.wa-remote-readonly-row .wa-v99-tag-badge, tr.wa-remote-readonly-row .wa-v99-image-badge{color:#fff!important;filter:none!important;box-shadow:none;}'
          + 'tr.wa-remote-readonly-row .wa-v99-stage-wrap{display:flex;gap:4px;flex-wrap:wrap;align-items:center;background:transparent!important;}'
          + 'tr.wa-remote-readonly-row .wa-v99-stage-badge{display:inline-flex;align-items:center;gap:3px;padding:2px 6px;border-radius:10px;font-size:10px;font-weight:600;line-height:1.25;white-space:nowrap;background:#00a884;color:#fff!important;border:1px solid #008f72;}'
          + 'tr.wa-remote-readonly-row .wa-v99-stage-empty{color:var(--wa-v99-remote-text)!important;background:transparent!important;}'
          + 'tr.wa-remote-readonly-row .wa-v99-copy{pointer-events:auto!important;cursor:pointer!important;opacity:1!important;}'
          + 'tr.wa-remote-readonly-row .wa-v99-copy *{cursor:pointer!important;}'
          + '.wa-v99-color-cfg{display:inline-flex;align-items:center;gap:7px;flex-wrap:wrap;padding-left:8px;border-left:1px solid var(--border);}'
          + '.wa-v99-color-cfg label{display:inline-flex;align-items:center;gap:3px;white-space:nowrap;}'
          + '.wa-v99-color-cfg input[type=color]{width:29px!important;height:24px;padding:1px!important;border:1px solid var(--border);border-radius:4px;background:var(--card);cursor:pointer;}'
          + '.wa-v99-color-cfg button{padding:3px 8px;border:1px solid var(--border);border-radius:5px;background:var(--card);color:var(--text);cursor:pointer;font-size:11px;}';
        win.document.head.appendChild(v99Style);

        // v106.1：必须在 v99 只读样式之后覆盖，否则其 background:transparent!important 会抹掉来源色。
        var v1061Style = win.document.createElement('style');
        v1061Style.id = 'wa-v1061-source-color-fix';
        v1061Style.textContent = ''
          + '#mainTable tr.wa-remote-readonly-row .wa-remote-readonly-badge.wa-v106-source-badge{'
          + 'display:inline-block!important;box-sizing:border-box!important;max-width:100%!important;'
          + 'padding:2px 7px!important;border:0!important;border-radius:999px!important;'
          + 'background:var(--wa-v106-source-color)!important;color:#fff!important;'
          + 'font-family:inherit!important;font-size:11px!important;font-weight:700!important;line-height:1.35!important;'
          + 'white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important;vertical-align:middle!important;}'
          + 'body.dark #mainTable tr.wa-remote-readonly-row .wa-remote-readonly-badge.wa-v106-source-badge{'
          + 'background:var(--wa-v106-source-color)!important;color:#fff!important;border:0!important;}';
        win.document.head.appendChild(v1061Style);

        // v111：电话关联色独立注入 head，避免样式文字泄漏到正文。
        var v111Style = win.document.createElement('style');
        v111Style.id = 'wa-v111-phone-group-style';
        v111Style.textContent = ''
          + '#mainTable td.v111-phone-cell,#mainGroupTable td.v111-phone-cell{background-color:var(--v111-phone-group-color)!important;background-image:none!important;filter:none!important;}'
          + '#mainTable td.v111-phone-cell.cell-empty,#mainGroupTable td.v111-phone-cell.cell-empty{background-color:var(--v111-phone-group-color)!important;}'
          + '#mainTable td.v111-phone-cell textarea.cell-input,#mainTable td.v111-phone-cell input.cell-input,#mainGroupTable td.v111-phone-cell textarea.cell-input,#mainGroupTable td.v111-phone-cell input.cell-input{background-color:transparent!important;background-image:none!important;color:var(--text)!important;}'
          + '#mainTable td.v111-phone-cell textarea.cell-input:focus,#mainTable td.v111-phone-cell input.cell-input:focus,#mainGroupTable td.v111-phone-cell textarea.cell-input:focus,#mainGroupTable td.v111-phone-cell input.cell-input:focus{background-color:transparent!important;background-image:none!important;box-shadow:inset 0 0 0 1px #00a884;}'
          + '#mainTable tr.wa-remote-readonly-row>td.v111-phone-cell,#mainTable tr.wa-remote-readonly-row:hover>td.v111-phone-cell,body.dark #mainTable tr.wa-remote-readonly-row>td.v111-phone-cell,body.dark #mainTable tr.wa-remote-readonly-row:hover>td.v111-phone-cell{background-color:var(--v111-phone-group-color)!important;background-image:none!important;color:var(--wa-v99-remote-text)!important;filter:none!important;}'
          + '#mainTable td.v111-phone-plain.cell-empty{background-color:var(--card)!important;background-image:none!important;}'
          + '#mainTable td.v111-phone-plain textarea.cell-input,#mainTable td.v111-phone-plain input.cell-input{background-color:transparent!important;background-image:none!important;}';
        win.document.head.appendChild(v111Style);
      } catch(e) {}


    var state = {
      search: '',
      tagFilter: '', selectedTags1: [], selectedTags2: [],
      platformFilter: '',
      sourceFilter: '',
      sort: 'updatedAt_desc',
      selected: {},
      wrapMode: (function () {
        var s = getSettings();
        return (typeof s.wrapMode === 'undefined') ? true : !!s.wrapMode;
      })(),
      dark: !!getSettings().darkMode,
      dashboardOpen: false,
      mainGroupCollapsed: false,
      expandedMainKeys: {}
    };

    function esc(s) {
      s = String(s == null ? '' : s);
      return s.replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
      });
    }
    function fmtTime(ts) {
      if (!ts) return '';
      var d = new Date(ts);
      var p2 = function (n) { return (n < 10 ? '0' : '') + n; };
      return (d.getMonth() + 1) + '/' + p2(d.getDate()) + ' ' + p2(d.getHours()) + ':' + p2(d.getMinutes());
    }

    function computeDisplayFields(row) {
      var rawName = row.name || '';
      var phone = row.manualPhone || '';
      var displayName = rawName;
      var nameNote = '';
      if (isPhoneLikeText(rawName)) {
        if (!phone) { phone = rawName; }
        displayName = '(\u672a\u4fdd\u5b58\u8054\u7cfb\u4eba)';
        nameNote = rawName;
      }
      return { displayName: displayName, nameNote: nameNote, displayPhone: phone };
    }

    // \u4fee\u590d\u540e\u7684 getAllRows\uff1a\u6b63\u786e\u4f7f\u7528 effectiveRecord / tagStageRecord \u5b57\u6bb5\u540d
    // v53: 下表明细严格读取各渠道本身的独立私有数据，彻底杜绝聚合数据回流污染
    function getRowPhoneNorm(e) {
      if (!e) return '';
      var phoneSrc = e.manualPhone || '';
      try {
        if (!phoneSrc && typeof isPhoneLikeText === 'function' && isPhoneLikeText(e.name)) {
          phoneSrc = e.name || '';
        }
      } catch (err) {}
      return normalizePhone(phoneSrc);
    }

    function getRowSourceId(e) {
      if (!e) return getLocalSyncSourceId();
      return e.__syncSourceId || e.sourceId || e.__sourceId || getLocalSyncSourceId();
    }

    function getRowSourceName(e) {
      if (!e) return getLocalSyncSourceName();
      return e.__syncSourceName || e.sourceName || e.__sourceName || getLocalSyncSourceName();
    }

    function countUniqueSources(members) {
      var set = {};
      (members || []).forEach(function (m) {
        var sid = m.__sourceId || m.__syncSourceId || m.sourceId || 'local';
        set[sid] = true;
      });
      return Object.keys(set).length;
    }

    // v103：管理面板动态关联只计算一次事实索引；主记录、明细状态与默认隐藏共用它。
    function buildCrossSourceLinkIndexV103() {
      var data = getPanelDisplayData();
      var settings = getSettings();
      var phoneMap = {};
      Object.keys(data || {}).forEach(function (id) {
        var e = data[id];
        if (!e || isAnyMainRecordV93(id, e)) return;
        var norm = getRowPhoneNorm(e);
        if (!norm || isAssociationBlockedV103(id, norm, settings, e)) return;
        if (!phoneMap[norm]) phoneMap[norm] = [];
        phoneMap[norm].push(Object.assign({
          __id: id,
          __platform: inferPlatform(e, id),
          __sourceId: getRowSourceId(e),
          __sourceName: getRowSourceName(e),
          __fromLocalSync: !!e.__fromLocalSync
        }, e));
      });

      var mainRows = [];
      var groupByMainKey = {};
      var linkByMemberId = {};
      Object.keys(phoneMap).forEach(function (norm) {
        var members = phoneMap[norm] || [];
        if (members.length < 2) return;
        var mainKey = getMainKey(norm);
        var main = buildMainRecordFromMembers(mainKey, members, null);
        main.__id = mainKey;
        main.__platform = 'main';
        main.__isMainRecord = true;
        main.__isGroup = true;
        main.__isCrossSourceMain = true;
        main.__mainKey = mainKey;
        main.__members = members;
        main.__memberCount = members.length;
        main.__sourceCount = countUniqueSources(members);
        main.memberIds = members.map(function (m) { return m.__id; });
        main.manualPhone = norm;
        main.tag = main.tag || '';
        main.tag2 = Array.isArray(main.tag2) ? main.tag2 : (main.tag2 ? [main.tag2] : []);
        main.stages = Array.isArray(main.stages) ? main.stages : (main.stages ? [main.stages] : []);
        mainRows.push(main);
        groupByMainKey[mainKey] = main;
        members.forEach(function (m) {
          linkByMemberId[m.__id] = {
            isLinked: true,
            type: 'dynamic',
            mainKey: mainKey,
            main: main,
            memberIds: main.memberIds.slice(),
            memberCount: members.length,
            sourceCount: main.__sourceCount
          };
        });
      });
      return { mainRows: mainRows, groupByMainKey: groupByMainKey, linkByMemberId: linkByMemberId };
    }

    function buildCrossSourceMainRows() {
      return buildCrossSourceLinkIndexV103().mainRows;
    }

    function getAllRows() {
      var data = getPanelDisplayData();
      var rows = [];
      var dynamicIndexV103 = buildCrossSourceLinkIndexV103();
      Object.keys(data || {}).forEach(function (id) {
        var e = data[id];
        if (!e) return;
        if (isAnyMainRecordV93(id, e)) return;
        var platform = inferPlatform(e, id);
        var row = Object.assign({
          __id: id,
          __platform: platform,
          __sourceId: getRowSourceId(e),
          __sourceName: getRowSourceName(e),
          __fromLocalSync: !!e.__fromLocalSync
        }, e);
        // v99：本源沿用原解析；他源必须在汇总数据中解析其命名空间主记录，不能查询当前 GM_storage。
        if (isRemoteSyncRecord(row)) {
          var rp99 = v99ResolveRemotePresentation(e, data);
          row.__v99Presentation = rp99;
          row.tag = (rp99.tag1 && rp99.tag1.key) || '';
          row.tag2 = rp99.tag2.map(function(x99) { return x99.key; });
          row.stages = rp99.stages.map(function(x99) { return x99.key; });
        } else {
          var ctx = resolveDisplayContext(id);
          row.tag = ctx.tagStageRecord ? (ctx.tagStageRecord.tag || '') : (e.tag || '');
          row.tag2 = v99NormalizeStringArray(e.tag2);
          row.stages = v99NormalizeStringArray(ctx.tagStageRecord ? ctx.tagStageRecord.stages : e.stages);
        }
        getAllFieldDefinitionsV126(false).forEach(function (f) { row[f.key] = (e[f.key] == null ? '' : e[f.key]); });
        var norm = getRowPhoneNorm(e);
        row.__associationBlocked = !!(norm && isAssociationBlockedV103(id, norm, getSettings(), e));
        row.__candidateMainKey = norm ? getMainKey(norm) : null;
        row.__linkInfo = dynamicIndexV103.linkByMemberId[id] || null;
        row.__mainKey = row.__linkInfo ? row.__linkInfo.mainKey : null;
        rows.push(row);
      });
      return rows;
    }

    function getAllRowsWithMain() {
      var rows = [];
      buildCrossSourceMainRows().forEach(function (r) { rows.push(r); });
      getAllRows().forEach(function (r) { rows.push(r); });
      return rows;
    }

    function getDisplayRows() {
      var all = getAllRows();
      var validMainKeys = {};

      // v100.1：只有真实生成的关联主记录，才允许折叠其明细联系人。
      // 单个联系人即使电话号码达到 7 位并生成了 __mainKey，也必须继续显示。
      buildCrossSourceMainRows().forEach(function (main) {
        validMainKeys[main.__id] = true;
      });

      return all.filter(function (r) {
        if (!r.__mainKey) return true;
        if (!validMainKeys[r.__mainKey]) return true;
        return !!state.expandedMainKeys[r.__mainKey];
      });
    }

    // v107.1：来源筛选只作用于内存展示，不写回联系人事实数据。
    function v1071RowMatchesSource(row, sourceFilter) {
      if (!sourceFilter) return true;
      var localId = getLocalSyncSourceId();
      var members = row && row.__isMainRecord && Array.isArray(row.__members) ? row.__members : [row];
      return members.some(function (m) {
        var sid = String((m && (m.__sourceId || m.__syncSourceId || m.sourceId)) || localId);
        if (sourceFilter === '__LOCAL__') return sid === localId;
        if (sourceFilter === '__REMOTE__') return sid !== localId;
        return sid === sourceFilter;
      });
    }

    function v1071SourceLabel(row) {
      var localId = getLocalSyncSourceId();
      var sid = String((row && (row.__sourceId || row.__syncSourceId || row.sourceId)) || localId);
      if (sid === localId) return getLocalSyncSourceName();
      return String((row && (row.__sourceName || row.__syncSourceName || row.sourceName)) || sid);
    }

    function getMainGroupRows() {
      var mainRows = buildCrossSourceMainRows();
      var selectedTags1 = state.selectedTags1 || (state.tagFilter ? [state.tagFilter] : []);
      var selectedTags2 = state.selectedTags2 || [];
      var targetPlat = state.platformFilter || '';
      var kw = state.search.trim().toLowerCase();
      return mainRows.filter(function (main) {
        var members = Array.isArray(main.__members) ? main.__members : [];
        var memberPlats = [];
        var allTags1 = [main.tag || ''];
        var allTags2 = Array.isArray(main.tag2) ? main.tag2.slice() : (main.tag2 ? [main.tag2] : []);
        members.forEach(function (m) {
          if (m.__platform && memberPlats.indexOf(m.__platform) < 0) memberPlats.push(m.__platform);
          if (m.tag && allTags1.indexOf(m.tag) < 0) allTags1.push(m.tag);
          var mArr2 = Array.isArray(m.tag2) ? m.tag2 : (m.tag2 ? [m.tag2] : []);
          mArr2.forEach(function (t) { if (t && allTags2.indexOf(t) < 0) allTags2.push(t); });
        });
        if (targetPlat && targetPlat !== 'main' && memberPlats.indexOf(targetPlat) < 0) return false;
        if (!v1071RowMatchesSource(main, state.sourceFilter)) return false;
        if (selectedTags1.length > 0) {
          var matchT1 = selectedTags1.some(function (t) { return allTags1.indexOf(t) >= 0; });
          if (!matchT1) return false;
        }
        if (selectedTags2.length > 0) {
          var matchT2 = selectedTags2.some(function (t) { return allTags2.indexOf(t) >= 0; });
          if (!matchT2) return false;
        }
        if (kw) {
          var hay = [main.name, main.manualPhone, main.remark, main.f1, main.f2, main.f3, main.f4, main.f5, main.f6, main.f7, main.f8]
            .concat(members.map(function (m) { return [m.name, m.manualPhone, m.remark, m.f1, m.f2, m.f3, m.f4, m.f5, m.f6, m.f7, m.f8, m.__sourceName].join(' '); }))
            .map(function (v) { return (v || '').toString().toLowerCase(); }).join(' ');
          if (hay.indexOf(kw) < 0) return false;
        }
        return true;
      });
    }

    function applyFilters(rows) {
      var kw = state.search.trim().toLowerCase();
      var selectedTags1 = state.selectedTags1 || (state.tagFilter ? [state.tagFilter] : []);
      var selectedTags2 = state.selectedTags2 || [];

      return rows.filter(function (r) {
        if (state.platformFilter && r.__platform !== state.platformFilter) return false;
        if (!v1071RowMatchesSource(r, state.sourceFilter)) return false;
        if (selectedTags1.length > 0) {
          var rt1 = r.tag || '';
          if (selectedTags1.indexOf(rt1) < 0) return false;
        }
        if (selectedTags2.length > 0) {
          var rt2 = Array.isArray(r.tag2) ? r.tag2 : (r.tag2 ? [r.tag2] : []);
          var hasT2 = selectedTags2.some(function(t){ return rt2.indexOf(t) >= 0; });
          if (!hasT2) return false;
        }
        if (kw) {
          var hay = [r.name, r.manualPhone, r.remark, r.f1, r.f2, r.f3, r.f4, r.f5, r.f6, r.f7, r.f8, r.__sourceName, r.__syncSourceName, v1071SourceLabel(r)]
            .map(function (v) { return (v || '').toString().toLowerCase(); }).join(' ');
          if (hay.indexOf(kw) < 0) return false;
        }
        return true;
      });
    }

    // v53: 展开的关联渠道强力置顶在列表最顶端，同组聚拢，其后为普通联系人
    function applySort(rows) {
      var expandedGroupRows = [];
      var normalRows = [];
      rows.forEach(function (r) {
        if (r.__mainKey && state.expandedMainKeys[r.__mainKey]) {
          expandedGroupRows.push(r);
        } else {
          normalRows.push(r);
        }
      });

      function sortFn(a, b) {
        var fallback = (b.updatedAt || 0) - (a.updatedAt || 0);
        if (state.sort === 'name_asc') return (a.name || '').localeCompare(b.name || '') || fallback;
        if (state.sort === 'name_desc') return (b.name || '').localeCompare(a.name || '') || fallback;
        if (state.sort === 'updatedAt_asc') return (a.updatedAt || 0) - (b.updatedAt || 0);
        if (state.sort === 'source_asc') return v1071SourceLabel(a).localeCompare(v1071SourceLabel(b)) || fallback;
        if (state.sort === 'source_desc') return v1071SourceLabel(b).localeCompare(v1071SourceLabel(a)) || fallback;
        if (state.sort === 'platform_order') {
          var order = { main:0, wa:1, whatsapp:1, ig:2, instagram:2, tg:3, telegram:3, fb:4, facebook:4, messenger:4 };
          var ap = Object.prototype.hasOwnProperty.call(order, a.__platform) ? order[a.__platform] : 99;
          var bp = Object.prototype.hasOwnProperty.call(order, b.__platform) ? order[b.__platform] : 99;
          return ap - bp || fallback;
        }
        if (state.sort === 'unlinked_first' || state.sort === 'linked_first') {
          var al = !!(a.__linkInfo || a.__mainKey || a.__isMainRecord);
          var bl = !!(b.__linkInfo || b.__mainKey || b.__isMainRecord);
          var d = (al === bl) ? 0 : (al ? 1 : -1);
          return (state.sort === 'linked_first' ? -d : d) || fallback;
        }
        return fallback;
      }

      normalRows.sort(sortFn);

      // 置顶的关联组成员按组聚拢
      var groupedExpanded = [];
      var visited = {};
      expandedGroupRows.forEach(function (r) {
        var mk = r.__mainKey;
        if (!visited[mk]) {
          visited[mk] = true;
          var members = expandedGroupRows.filter(function (item) { return item.__mainKey === mk; });
          members.sort(sortFn);
          members.forEach(function (m) { groupedExpanded.push(m); });
        }
      });

      return groupedExpanded.concat(normalRows);
    }

    function renderSourceFilter() {
      var sel = win.document.getElementById('sourceFilter');
      if (!sel) return;
      var rows = getAllRows();
      var localId = getLocalSyncSourceId();
      var localName = getLocalSyncSourceName();
      var counts = {};
      var names = {};
      rows.forEach(function (r) {
        var sid = String(r.__sourceId || localId);
        counts[sid] = (counts[sid] || 0) + 1;
        names[sid] = sid === localId ? localName : (r.__sourceName || sid);
      });
      var localCount = counts[localId] || 0;
      var remoteCount = rows.length - localCount;
      var html = '<option value="">全部来源 (' + rows.length + ')</option>' +
        '<option value="__LOCAL__">本源 · ' + esc(localName) + ' (' + localCount + ')</option>' +
        '<option value="__REMOTE__">全部他源 (' + remoteCount + ')</option>';
      Object.keys(counts).filter(function (sid) { return sid !== localId; }).sort(function (a, b) {
        return String(names[a]).localeCompare(String(names[b]));
      }).forEach(function (sid) {
        html += '<option value="' + esc(sid) + '">' + esc(names[sid]) + ' (' + counts[sid] + ')</option>';
      });
      sel.innerHTML = html;
      sel.value = state.sourceFilter || '';
      if (sel.value !== (state.sourceFilter || '')) state.sourceFilter = '';
    }

    function renderPlatformBar() {
      var bar = win.document.getElementById('platformBar');
      var rows = getAllRowsWithMain();
      var counts = {};
      rows.forEach(function (r) { counts[r.__platform] = (counts[r.__platform] || 0) + 1; });
      var html = '<span class="platpill" data-plat="" style="background:#37474f;">\u5168\u90e8 (' + rows.length + ')</span>';
      Object.keys(PLATFORM_INFO).forEach(function (k) {
        var info = PLATFORM_INFO[k];
        var c = counts[k] || 0;
        html += '<span class="platpill" data-plat="' + k + '" style="background:' + info.color + ';">' +
          info.short + ' (' + c + ')</span>';
      });
      bar.innerHTML = html;
      bar.querySelectorAll('.platpill').forEach(function (el) {
        if (el.getAttribute('data-plat') === state.platformFilter) el.classList.add('active');
        el.addEventListener('click', function () {
          var p = el.getAttribute('data-plat');
          state.platformFilter = p;
      renderAll();
        });
      });
    }

    function renderTagBar() {
      var bar = win.document.getElementById('tagBar');
      var rows = getAllRows();
      var t1List = getTags1();
      var t2List = getTags2();

      // 穿透统计：包括收起与展开的所有渠道及独立账号
      var counts1 = {};
      rows.forEach(function (r) {
        var t = r.tag || '';
        counts1[t] = (counts1[t] || 0) + 1;
      });

      var counts2 = {};
      rows.forEach(function (r) {
        var arr = Array.isArray(r.tag2) ? r.tag2 : (r.tag2 ? [r.tag2] : []);
        arr.forEach(function(t){ if (t) counts2[t] = (counts2[t] || 0) + 1; });
      });

      var html = '<div style="display:flex;flex-direction:column;gap:6px;width:100%;">';

      // 第一行：标签体系（最前面为 全部标签）
      var isT1AllActive = (!state.selectedTags1 || state.selectedTags1.length === 0);
      html += '<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">';
            html += '<span class="tagpill t1-pill' + (isT1AllActive ? ' active' : '') + '" data-t1="__ALL__" style="background:#54656f;">全部标签 (' + rows.length + ')</span>';

      t1List.forEach(function (t) {
        var c = counts1[t.key] || 0;
        var isAct = state.selectedTags1 && state.selectedTags1.indexOf(t.key) >= 0;
        html += '<span class="tagpill t1-pill' + (isAct ? ' active' : '') + '" data-t1="' + esc(t.key) + '" style="background:' + t.color + ' !important;">' +
          esc(t.label) + ' (' + c + ')</span>';
      });
      html += '</div>';

      // 第二行：画像体系（方案B画像多选）
      var isT2AllActive = (!state.selectedTags2 || state.selectedTags2.length === 0);
      html += '<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">';
            html += '<span class="tagpill t2-pill' + (isT2AllActive ? ' active' : '') + '" data-t2="__ALL__" style="background:#54656f;">全部画像</span>';

      t2List.forEach(function (t) {
        var c = counts2[t.key] || 0;
        var isAct = state.selectedTags2 && state.selectedTags2.indexOf(t.key) >= 0;
        html += '<span class="tagpill t2-pill' + (isAct ? ' active' : '') + '" data-t2="' + esc(t.key) + '" style="background:' + t.color + ' !important;">' +
          esc(t.label) + ' (' + c + ')</span>';
      });
      html += '</div>';

      html += '</div>';
      bar.innerHTML = html;

      // 绑定标签点击事件（支持多选并集，点击具体标签穿透展开关联组）
      bar.querySelectorAll('.t1-pill').forEach(function (el) {
        el.addEventListener('click', function () {
          var v = el.getAttribute('data-t1');
          if (v === '__ALL__') {
            state.selectedTags1 = [];
          } else {
            var idx = state.selectedTags1.indexOf(v);
            if (idx >= 0) {
              state.selectedTags1.splice(idx, 1);
            } else {
              state.selectedTags1.push(v);
            }

          }
          renderAll();
        });
      });

      // 绑定画像点击事件（支持多选画像筛选，穿透展开关联组）
      bar.querySelectorAll('.t2-pill').forEach(function (el) {
        el.addEventListener('click', function () {
          var v = el.getAttribute('data-t2');
          if (v === '__ALL__') {
            state.selectedTags2 = [];
          } else {
            var idx = state.selectedTags2.indexOf(v);
            if (idx >= 0) {
              state.selectedTags2.splice(idx, 1);
            } else {
              state.selectedTags2.push(v);
            }

          }
          renderAll();
        });
      });

      var batchSel = win.document.getElementById('batchTagSelect');
      if (batchSel) {
        batchSel.innerHTML = t1List.map(function (t) { return '<option value="' + t.key + '">' + t.label + '</option>'; }).join('');
      }
    }

    function renderStats() {
      var rows = getAllRowsWithMain();
      var filtered = applyFilters(rows);
      win.document.getElementById('statsBar').innerHTML =
        '\u5171 <b>' + rows.length + '</b> \u6761\u8bb0\u5f55\uff0c\u5f53\u524d\u7b5b\u9009\u51fa <b>' + filtered.length + '</b> \u6761';
    }

    function renderDashboard() {
      var dash = win.document.getElementById('dashboard');
      dash.classList.toggle('show', state.dashboardOpen);
      if (!state.dashboardOpen) return;
      var rows = getAllRowsWithMain(); // v90：总量与渠道分布包含主记录
      var childRowsOnly = getAllRows(); // v90：标签/阶段统计只算子记录，不算主记录

      function buildBarRows(counts, colorFn, labelFn, total) {
        var keys = Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; });
        return keys.map(function (k) {
          var c = counts[k];
          var pct = total ? Math.round(c / total * 100) : 0;
          return '<div class="bar-item"><div class="bar-label">' + esc(labelFn(k)) + '</div>' +
            '<div class="bar-track"><div class="bar-fill" style="width:' + pct + '%;background:' + colorFn(k) + ';"></div></div>' +
            '<div class="bar-val">' + c + '</div></div>';
        }).join('');
      }

      var platCounts = {};
      rows.forEach(function (r) { platCounts[r.__platform] = (platCounts[r.__platform] || 0) + 1; });
      var tagCounts = {};
      childRowsOnly.forEach(function (r) { var t = r.tag || ''; tagCounts[t] = (tagCounts[t] || 0) + 1; });
      var stageCounts = {};
      childRowsOnly.forEach(function (r) {
        var st = Array.isArray(r.stages) ? r.stages : [];
        if (!st.length) stageCounts['__none'] = (stageCounts['__none'] || 0) + 1;
        st.forEach(function (s) { stageCounts[s] = (stageCounts[s] || 0) + 1; });
      });

      var html = '';
      html += '<div class="dash-row"><div class="dash-title">\u6e20\u9053\u5206\u5e03</div>' +
        buildBarRows(platCounts, function (k) { return getPlatformInfo(k).color; }, function (k) { return getPlatformInfo(k).short; }, rows.length) + '</div>';
      html += '<div class="dash-row"><div class="dash-title">\u6807\u7b7e\u5206\u5e03</div>' +
        buildBarRows(tagCounts, function (k) { var t = TAGS.filter(function (x) { return x.key === k; })[0]; return t ? t.color : '#999'; },
          function (k) { var t = TAGS.filter(function (x) { return x.key === k; })[0]; return t ? t.label : '\u672a\u5206\u7c7b'; }, rows.length) + '</div>';
      html += '<div class="dash-row"><div class="dash-title">\u8ddf\u8fdb\u9636\u6bb5\u5206\u5e03</div>' +
        buildBarRows(stageCounts, function () { return '#00a884'; },
          function (k) { return k === '__none' ? '\u672a\u6807\u8bb0\u9636\u6bb5' : getStageLabel(k); }, rows.length) + '</div>';
      dash.innerHTML = html;
    }

    function upsertCell(id, key, val) {
      upsertFieldSmart(id, {}, key, val);
    }

    function deleteRow(id) {
      if (!id) return;
      v204UiWriteResult((async function(){
        var r=await localSyncDeleteOne(id);if(!r.ok)return r;
        var data=loadData();if(Object.prototype.hasOwnProperty.call(data,id)){delete data[id];saveData(data);}
        delete state.selected[id];reconcileLinkStateV103();
        try{runLinkScanAndRefreshPanelNow();}catch(e){}
        return r;
      })(),'删除');
    }

    function showCopyToast(msg) {
      try {
        var old = win.document.getElementById('__waCopyToast');
        if (old) old.remove();
        var el = win.document.createElement('div');
        el.id = '__waCopyToast';
        el.textContent = msg || '✅ 复制成功';
        el.style.cssText = 'position:fixed;right:24px;bottom:34px;z-index:999999;background:#00a884;color:#fff;padding:9px 16px;border-radius:8px;font-size:13px;font-weight:700;box-shadow:0 6px 20px rgba(0,0,0,.22);transition:opacity .25s,transform .25s;';
        win.document.body.appendChild(el);
        setTimeout(function(){ el.style.opacity='0'; el.style.transform='translateY(8px)'; }, 1300);
        setTimeout(function(){ if(el && el.parentNode) el.remove(); }, 1700);
      } catch(e) {}
    }

    function getFreshRowForCopy(row) {
      var fresh = Object.assign({}, row || {});
      try {
        var data = loadData();
        var id = row && row.__id;
        if (id && data[id]) {
          fresh = Object.assign({}, row, data[id]);
          fresh.__id = id;
          fresh.__platform = row.__platform || inferPlatform(data[id], id);
          fresh.__mainKey = row.__mainKey || data[id].mainKey || null;
          if (row.__isGroup) {
            fresh.__isGroup = true;
            fresh.__members = row.__members || [];
            fresh.__memberCount = row.__memberCount || (fresh.__members ? fresh.__members.length : 0);
          }
        }
      } catch(e) {}
      return fresh;
    }

    function copyContactText(row) {
      // v72.5：复制前主动让当前输入框失焦，配合 blur 即时保存，避免刚编辑内容仍停留在防抖队列
      try {
        var ae = win.document.activeElement;
        if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' || ae.tagName === 'SELECT')) ae.blur();
      } catch(e) {}

      var r = getFreshRowForCopy(row);
      var disp = computeDisplayFields(r);
      var info = getPlatformInfo(r.__platform || inferPlatform(r, r.__id || ''));
      var lines = [];
      lines.push('姓名：' + (disp.nameNote || r.name || ''));
      lines.push('电话：' + (r.manualPhone || disp.displayPhone || ''));
      lines.push('渠道：' + ((info && info.short) || r.__platform || ''));
      lines.push('识别码：' + (r.__id || ''));
      lines.push('标签：' + (function(){ var arr=getTags1(); for(var i=0;i<arr.length;i++){ if(arr[i].key===(r.tag||'')) return arr[i].label; } return r.tag || ''; })());
      lines.push('画像：' + (function(){ var t2=Array.isArray(r.tag2)?r.tag2:(r.tag2?[r.tag2]:[]); var defs=getTags2(); return t2.map(function(k){ for(var i=0;i<defs.length;i++){ if(defs[i].key===k) return defs[i].label; } return k; }).filter(Boolean).join(' / '); })());
      lines.push('跟进阶段：' + ((Array.isArray(r.stages) ? r.stages : []).map(function(k){ return getStageLabel(k); }).join(' / ')));
      getAllFieldDefinitionsV126(false).forEach(function (f) { lines.push(f.label + '：' + (r[f.key] == null ? '' : r[f.key])); });
      lines.push('更新时间：' + fmtTime(r.updatedAt));
      var text = lines.join('\n');

      function ok(){ showCopyToast('✅ 复制成功：已复制全部列资料'); }
      function fail(){ try { GM_setClipboard(text); ok(); } catch(e) { showCopyToast('⚠️ 复制失败，请检查浏览器剪贴板权限'); } }
      try {
        if (win.navigator.clipboard && win.navigator.clipboard.writeText) {
          var ret = win.navigator.clipboard.writeText(text);
          if (ret && ret.then) ret.then(ok).catch(fail); else ok();
        } else fail();
      } catch (e) { fail(); }
      try { GM_setClipboard(text); } catch (e) {}
      return text;
    }


    function v74GetMainMemberIds(mainRow) {
      if (!mainRow) return [];
      if (Array.isArray(mainRow.memberIds)) return mainRow.memberIds.slice();
      if (Array.isArray(mainRow.__members)) return mainRow.__members.map(function (m) { return m.__id; }).filter(Boolean);
      var data = loadData();
      var main = data[mainRow.__id] || {};
      return Array.isArray(main.memberIds) ? main.memberIds.slice() : [];
    }
    function v74GetMainSelectionState(mainRow) {
      var ids = v74GetMainMemberIds(mainRow);
      var total = ids.length + 1;
      var checkedCount = state.selected[mainRow.__id] ? 1 : 0;
      ids.forEach(function (id) { if (state.selected[id]) checkedCount++; });
      return { checked: total > 0 && checkedCount === total, indeterminate: checkedCount > 0 && checkedCount < total, count: checkedCount, total: total };
    }
    function v74SetMainSelected(mainRow, checked) {
      state.selected[mainRow.__id] = !!checked;
      v74GetMainMemberIds(mainRow).forEach(function (id) { state.selected[id] = !!checked; });
    }
    function v74SyncMainSelectionByDetail(detailRow) {
      if (!detailRow || !detailRow.__mainKey) return;
      var data = loadData();
      var main = data[detailRow.__mainKey];
      if (!main) return;
      var mids = Array.isArray(main.memberIds) ? main.memberIds : [];
      var all = mids.length && mids.every(function (id) { return !!state.selected[id]; });
      var any = mids.some(function (id) { return !!state.selected[id]; });
      state.selected[detailRow.__mainKey] = !!all;
    }
    function v74GetRowsSelectionState(rows) {
      var total = 0, checked = 0;
      (rows || []).forEach(function (r) {
        if (r.__isGroup || isMainKey(r.__id)) {
          var st = v74GetMainSelectionState(r);
          total += st.total; checked += st.count;
        } else {
          total++; if (state.selected[r.__id]) checked++;
        }
      });
      return { checked: total > 0 && checked === total, indeterminate: checked > 0 && checked < total, count: checked, total: total };
    }
    function v74GetSelectedIds() {
      return Object.keys(state.selected).filter(function (k) { return state.selected[k]; });
    }
    function v74GetSelectedSummary() {
      var ids = v74GetSelectedIds(), g = 0, d = 0;
      ids.forEach(function (id) { if (isMainKey(id)) g++; else d++; });
      return { ids: ids, groupCount: g, detailCount: d };
    }

    function updateBatchBar() {
      var summary = v74GetSelectedSummary();
      var bar = win.document.getElementById('batchBar');
      var total = summary.groupCount + summary.detailCount;
      bar.classList.toggle('show', total > 0);
      win.document.getElementById('batchCount').textContent = '已选 ' + summary.groupCount + '组 / ' + summary.detailCount + '条';
    }

    function autoResizeCell(t) {
      t.style.height = 'auto';
      t.style.height = t.scrollHeight + 'px';
    }

    // v111：稳定主记录键哈希为不透明纯色，不受显示顺序影响。
    var V111_PHONE_GROUP_COLORS = ['#d9f4e3','#dceaff','#f9dfe8','#eee2f6','#eee6dc','#fff0cf','#dff1f1','#e8e6fa'];
    function v111GetPhoneGroupColor(mainKey111) {
      var text111 = String(mainKey111 || '');
      var hash111 = 2166136261;
      for (var i111 = 0; i111 < text111.length; i111++) {
        hash111 ^= text111.charCodeAt(i111);
        hash111 = Math.imul(hash111, 16777619);
      }
      return V111_PHONE_GROUP_COLORS[(hash111 >>> 0) % V111_PHONE_GROUP_COLORS.length];
    }
    function v111ApplyPhoneCell(td111, mainKey111) {
      if (!td111) return;
      td111.classList.remove('cell-empty', 'v111-phone-cell');
      td111.classList.add('v111-phone-plain');
      td111.style.removeProperty('--v111-phone-group-color');
      td111.removeAttribute('data-v111-main-key');
      if (!mainKey111) return;
      td111.classList.remove('v111-phone-plain');
      td111.classList.add('v111-phone-cell');
      td111.style.setProperty('--v111-phone-group-color', v111GetPhoneGroupColor(mainKey111));
      td111.setAttribute('data-v111-main-key', String(mainKey111));
    }

    // v99：仅保存“他源底色”；悬停色、文字色和边框色均由底色自动计算。
    var V99_REMOTE_COLOR_DEFAULTS = { remoteReadonlyRowColor: '#cbd2d9' };
    function v99SafeColor(value, fallback) {
      value = String(value || '').trim();
      return /^#[0-9a-f]{6}$/i.test(value) ? value : fallback;
    }
    function v99HexToRgb(hex98) {
      hex98 = v99SafeColor(hex98, V99_REMOTE_COLOR_DEFAULTS.remoteReadonlyRowColor);
      return { r:parseInt(hex98.slice(1,3),16), g:parseInt(hex98.slice(3,5),16), b:parseInt(hex98.slice(5,7),16) };
    }
    function v99RgbToHex(r98, g98, b98) {
      function h98(n98) { n98 = Math.max(0, Math.min(255, Math.round(n98))); return n98.toString(16).padStart(2, '0'); }
      return '#' + h98(r98) + h98(g98) + h98(b98);
    }
    function v99MixColor(hex98, target98, amount98) {
      var c98 = v99HexToRgb(hex98);
      return v99RgbToHex(c98.r + (target98 - c98.r) * amount98, c98.g + (target98 - c98.g) * amount98, c98.b + (target98 - c98.b) * amount98);
    }
    function v99RelativeLuminance(hex98) {
      var c98 = v99HexToRgb(hex98);
      function channel98(v99) { v99 /= 255; return v99 <= 0.03928 ? v99 / 12.92 : Math.pow((v99 + 0.055) / 1.055, 2.4); }
      return 0.2126 * channel98(c98.r) + 0.7152 * channel98(c98.g) + 0.0722 * channel98(c98.b);
    }
    function v99GetRemoteColors() {
      var s98 = getSettings();
      var bg98 = v99SafeColor(s98.remoteReadonlyRowColor, V99_REMOTE_COLOR_DEFAULTS.remoteReadonlyRowColor);
      var dark98 = v99RelativeLuminance(bg98) < 0.36;
      return {
        bg: bg98,
        hover: v99MixColor(bg98, dark98 ? 255 : 0, dark98 ? 0.12 : 0.10),
        text: dark98 ? '#ffffff' : '#26313b',
        border: v99MixColor(bg98, dark98 ? 255 : 0, dark98 ? 0.30 : 0.24)
      };
    }
    function v99ApplyRemoteColors() {
      var c98 = v99GetRemoteColors();
      var root98 = win.document.documentElement;
      root98.style.setProperty('--wa-v99-remote-bg', c98.bg);
      root98.style.setProperty('--wa-v99-remote-hover', c98.hover);
      root98.style.setProperty('--wa-v99-remote-text', c98.text);
      root98.style.setProperty('--wa-v99-remote-border', c98.border);
    }
    function v99InitRemoteColorSettings() {
      var host98 = win.document.querySelector('.sub-table-cfg');
      if (!host98) return;
      // 清除 v97 遗留的独立悬停色、文字色，确保它们不再影响 v99。
      var old98 = getSettings();
      if (Object.prototype.hasOwnProperty.call(old98, 'remoteReadonlyRowHoverColor') || Object.prototype.hasOwnProperty.call(old98, 'remoteReadonlyTextColor')) {
        setSettings({ remoteReadonlyRowHoverColor: undefined, remoteReadonlyTextColor: undefined });
      }
      var box98 = win.document.getElementById('waV99RemoteColorCfg');
      var c98 = v99GetRemoteColors();
      if (!box98) {
        box98 = win.document.createElement('span');
        box98.id = 'waV99RemoteColorCfg';
        box98.className = 'wa-v99-color-cfg';
        box98.innerHTML = '<b>他源底色</b>'
          + '<label><input type="color" data-v99-key="remoteReadonlyRowColor" title="设置他源整行底色；文字和悬停颜色自动适配"></label>'
          + '<button type="button" id="waV99RemoteColorReset">重置</button>';
        host98.appendChild(box98);
        var input98 = box98.querySelector('[data-v99-key="remoteReadonlyRowColor"]');
        input98.addEventListener('input', function() {
          setSettings({ remoteReadonlyRowColor: input98.value, remoteReadonlyRowHoverColor: undefined, remoteReadonlyTextColor: undefined });
          v99ApplyRemoteColors();
        });
        box98.querySelector('#waV99RemoteColorReset').addEventListener('click', function() {
          setSettings({ remoteReadonlyRowColor: V99_REMOTE_COLOR_DEFAULTS.remoteReadonlyRowColor, remoteReadonlyRowHoverColor: undefined, remoteReadonlyTextColor: undefined });
          v99ApplyRemoteColors();
          input98.value = v99GetRemoteColors().bg;
        });
      }
      box98.querySelector('[data-v99-key="remoteReadonlyRowColor"]').value = c98.bg;
      v99ApplyRemoteColors();
    }

    function v99FindTagDef(list98, key98) {
      for (var i98 = 0; i98 < list98.length; i98++) if (list98[i98].key === key98) return list98[i98];
      return null;
    }
    // v100.3：按单元格实际宽度自适应省略识别码，并提供受控悬停浮层及单击复制。
    function v1003CopyText(text1003, successText1003) {
      text1003 = String(text1003 === undefined || text1003 === null ? '' : text1003);
      if (!text1003) return;
      var done1003 = false;
      function ok1003() {
        if (done1003) return;
        done1003 = true;
        showCopyToast('✅ ' + (successText1003 || '已复制'));
      }
      function fallback1003() {
        try { GM_setClipboard(text1003); ok1003(); }
        catch (err1003) { showCopyToast('⚠️ 复制失败，请检查浏览器剪贴板权限'); }
      }
      try {
        if (win.navigator.clipboard && win.navigator.clipboard.writeText) {
          var ret1003 = win.navigator.clipboard.writeText(text1003);
          if (ret1003 && ret1003.then) ret1003.then(ok1003).catch(fallback1003);
          else ok1003();
        } else fallback1003();
      } catch (err21003) { fallback1003(); }
    }
    function v1003GetTooltip() {
      var tip1003 = win.document.getElementById('waV1003IdentifierTip');
      if (!tip1003) {
        tip1003 = win.document.createElement('div');
        tip1003.id = 'waV1003IdentifierTip';
        tip1003.style.cssText = 'display:none;position:fixed;z-index:2147483647;max-width:420px;padding:7px 10px;border-radius:6px;background:rgba(17,27,33,.94);color:#fff;font-size:12px;line-height:1.45;overflow-wrap:anywhere;word-break:break-all;box-shadow:0 4px 14px rgba(0,0,0,.28);pointer-events:none;';
        win.document.body.appendChild(tip1003);
      }
      return tip1003;
    }
    function v1003BindTooltip(el1003, full1003) {
      var timer1003 = null;
      function hide1003() {
        if (timer1003) { win.clearTimeout(timer1003); timer1003 = null; }
        var tip1003 = win.document.getElementById('waV1003IdentifierTip');
        if (tip1003) tip1003.style.display = 'none';
      }
      el1003.addEventListener('mouseenter', function () {
        timer1003 = win.setTimeout(function () {
          var tip1003 = v1003GetTooltip();
          tip1003.textContent = full1003;
          tip1003.style.display = 'block';
          var r1003 = el1003.getBoundingClientRect();
          var left1003 = Math.max(8, Math.min(r1003.left, win.innerWidth - tip1003.offsetWidth - 8));
          var top1003 = r1003.bottom + 6;
          if (top1003 + tip1003.offsetHeight > win.innerHeight - 8) top1003 = Math.max(8, r1003.top - tip1003.offsetHeight - 6);
          tip1003.style.left = left1003 + 'px';
          tip1003.style.top = top1003 + 'px';
        }, 300);
      });
      el1003.addEventListener('mouseleave', hide1003);
      el1003.addEventListener('click', hide1003);
    }
    function v1003AppendAdaptiveIdentifier(td1003, value1003) {
      var full1003 = String(value1003 === undefined || value1003 === null ? '' : value1003);
      td1003.classList.add('v1003-id-cell');
      td1003.style.cssText += ';position:relative;overflow:hidden!important;white-space:nowrap!important;padding-left:12px!important;padding-right:8px!important;font-size:14px!important;vertical-align:middle;';
      var wrap1003 = win.document.createElement('span');
      wrap1003.className = 'v1003-identifier';
      wrap1003.style.cssText = 'position:relative;z-index:2;display:flex;align-items:center;width:100%;min-width:0;overflow:hidden;white-space:nowrap;cursor:copy;font-size:14px;line-height:1.45;box-sizing:border-box;';
      if (!full1003) {
        wrap1003.textContent = '-';
      } else {
        var suffixLen1003 = Math.min(6, Math.max(2, Math.floor(full1003.length / 4)));
        var prefix1003 = win.document.createElement('span');
        var suffix1003 = win.document.createElement('span');
        prefix1003.className = 'v1003-identifier-prefix';
        suffix1003.className = 'v1003-identifier-suffix';
        prefix1003.textContent = full1003.slice(0, -suffixLen1003);
        suffix1003.textContent = full1003.slice(-suffixLen1003);
        prefix1003.style.cssText = 'min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;';
        suffix1003.style.cssText = 'flex:0 0 auto;white-space:nowrap;';
        wrap1003.appendChild(prefix1003);
        wrap1003.appendChild(suffix1003);
        wrap1003.setAttribute('aria-label', full1003);
        v1003BindTooltip(wrap1003, full1003);
        wrap1003.addEventListener('click', function (e1003) {
          e1003.stopPropagation();
          v1003CopyText(full1003, '识别码已复制');
        });
      }
      td1003.appendChild(wrap1003);
    }
    function v1003EnableNameCopy(td1003, name1003) {
      var fullName1003 = String(name1003 === undefined || name1003 === null ? '' : name1003).trim();
      if (!fullName1003) return;
      td1003.style.cursor = 'copy';
      td1003.addEventListener('click', function (e1003) {
        e1003.stopPropagation();
        v1003CopyText(fullName1003, '姓名已复制');
      });
    }

    function v99AppendStatic(td98, text98, row98) {
      var el98 = win.document.createElement('div');
      el98.className = 'wa-v99-static';
      el98.textContent = (text98 === undefined || text98 === null || text98 === '') ? '' : String(text98);
      el98.title = getRemoteSyncReadonlyTitle(row98);
      td98.appendChild(el98);
    }
    function v99AppendTag1Badge(td99, row99) {
      var p99 = row99.__v99Presentation || v99NormalizePresentation(row99);
      var item99 = p99.tag1 || {};
      if (!item99.label && !item99.key) return;
      var badge99 = win.document.createElement('span');
      badge99.className = 'wa-v99-tag-badge';
      badge99.textContent = item99.label || item99.key;
      badge99.title = getRemoteSyncReadonlyTitle(row99);
      badge99.style.cssText = 'display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;color:#fff;background:' + (item99.color || '#78909c') + ';white-space:normal;overflow-wrap:anywhere;word-break:break-word;line-height:1.3;';
      td99.appendChild(badge99);
    }
    function v99AppendTag2Badges(td99, row99) {
      var p99 = row99.__v99Presentation || v99NormalizePresentation(row99);
      var values99 = Array.isArray(p99.tag2) ? p99.tag2 : [];
      var wrap99 = win.document.createElement('div');
      wrap99.style.cssText = 'display:flex;gap:3px;flex-wrap:wrap;align-items:center;min-height:22px;background:transparent;';
      wrap99.title = getRemoteSyncReadonlyTitle(row99);
      if (!values99.length) {
        var empty99 = win.document.createElement('span');
        empty99.className = 'wa-v99-static'; empty99.textContent = ''; wrap99.appendChild(empty99);
      } else values99.forEach(function(item99) {
        var badge99 = win.document.createElement('span');
        badge99.className = 'wa-v99-image-badge';
        badge99.textContent = item99.label || item99.key;
        badge99.style.cssText = 'display:inline-block;padding:1px 5px;border-radius:10px;font-size:10px;color:#fff;background:' + (item99.color || '#78909c') + ';white-space:normal;overflow-wrap:anywhere;word-break:break-word;line-height:1.2;';
        wrap99.appendChild(badge99);
      });
      td99.appendChild(wrap99);
    }
    function v99AppendStageBadges(td99, row99) {
      var p99 = row99.__v99Presentation || v99NormalizePresentation(row99);
      var stages99 = Array.isArray(p99.stages) ? p99.stages : [];
      var wrap99 = win.document.createElement('div');
      wrap99.className = 'wa-v99-stage-wrap';
      wrap99.title = getRemoteSyncReadonlyTitle(row99);
      if (!stages99.length) {
        var empty99 = win.document.createElement('span');
        empty99.className = 'wa-v99-stage-empty'; empty99.textContent = ''; wrap99.appendChild(empty99);
      } else stages99.forEach(function(item99) {
        var badge99 = win.document.createElement('span');
        badge99.className = 'wa-v99-stage-badge';
        badge99.textContent = '✓ ' + (item99.label || item99.key);
        badge99.style.background = item99.color || '#00a884';
        badge99.style.borderColor = item99.color || '#008f72';
        wrap99.appendChild(badge99);
      });
      td99.appendChild(wrap99);
    }
    // 他源从渲染层即为静态内容；v109 仅为姓名增加复制事件，仍不绑定编辑、切换、删除、解绑或弹窗事件。
    function v99RenderRemoteCell(td98, col98, row98, idx98, disp98) {
      td98.title = getRemoteSyncReadonlyTitle(row98);
      if (col98.key === '__index') {
        v99AppendStatic(td98, idx98 + 1, row98);
      } else if (col98.key === '__chk') {
        v99AppendStatic(td98, '🚫', row98);
      } else if (col98.key === '__source') {
        // v102: 来源及只读禁止标记从“关联”列迁移至“来源”列。
        var source98 = win.document.createElement('div');
        source98.className = 'wa-v99-link-wrap';
        appendRemoteSyncReadonlyBadge(win.document, source98, row98);
        td98.appendChild(source98);
      } else if (col98.key === '__platform') {
        var info106 = getPlatformInfo(row98.__platform);
        var platformBadge106 = win.document.createElement('span');
        platformBadge106.className = 'plat-badge';
        platformBadge106.style.background = info106.color;
        platformBadge106.textContent = info106.short;
        platformBadge106.title = getRemoteSyncReadonlyTitle(row98);
        td98.appendChild(platformBadge106);
      } else if (col98.key === '__link') {
        // v103：他源仍严格只读，但关联状态与同一动态事实索引保持一致。
        v99AppendStatic(td98, row98.__linkInfo ? ('已关联(' + row98.__linkInfo.memberCount + ')') : '', row98);
      } else if (col98.key === '__id') {
        td98.className = 'id-cell';
        v1003AppendAdaptiveIdentifier(td98, row98.__id);
      } else if (col98.key === '__avatar') {
        td98.classList.add('col-sticky-avatar');
        var src98 = row98.avatarData || row98.__avatarData || row98.__avatar || row98.avatar || '';
        if (src98) {
          var img98 = win.document.createElement('img');
          v1062BindAvatarImage(img98, row98, src98);
          img98.title = getRemoteSyncReadonlyTitle(row98);
          img98.style.cssText = 'width:34px;height:34px;border-radius:50%;object-fit:cover;display:block;margin:0 auto;cursor:not-allowed;';
          td98.appendChild(img98);
        } else v99AppendStatic(td98, '👤', row98);
      } else if (col98.key === 'name') {
        td98.classList.add('col-sticky-name');
        var remoteName109 = disp98.displayName || row98.name || '';
        v99AppendStatic(td98, remoteName109, row98);
        // v109：他源保持只读，但姓名允许像本源一样单击复制。
        v1003EnableNameCopy(td98, remoteName109);
        if (remoteName109) td98.title = '单击复制姓名；' + getRemoteSyncReadonlyTitle(row98);
      } else if (col98.key === 'manualPhone') {
        v99AppendStatic(td98, row98.manualPhone || disp98.displayPhone, row98);
      } else if (col98.key === 'tag') {
        v99AppendTag1Badge(td98, row98);
      } else if (col98.key === 'tag2') {
        v99AppendTag2Badges(td98, row98);
      } else if (col98.key === '__stages') {
        v99AppendStageBadges(td98, row98);
      } else if (col98.key === 'updatedAt') {
        v99AppendStatic(td98, fmtTime(row98.updatedAt), row98);
      } else if (col98.key === '__actions') {
        var copy98 = win.document.createElement('button');
        copy98.className = 'icon-btn wa-v99-copy'; copy98.textContent = '📋';
        copy98.title = '复制资料（他源允许复制姓名或整份资料，其他操作保持只读）';
        copy98.addEventListener('click', function(e98) { e98.stopPropagation(); copyContactText(row98); });
        td98.appendChild(copy98);
      } else if (isBusinessFieldKeyV126(col98.key)) {
        v99AppendStatic(td98, row98[col98.key] || '', row98);
      } else {
        v99AppendStatic(td98, row98[col98.key] || '', row98);
      }
    }

    function renderTable() {
      rebuildColumnsV126();
      if (typeof v1004IsDetailEditing === 'function' && v1004IsDetailEditing()) {
        v1004QueueRender();
        return;
      }
      var widths = getColWidths();
      var displayRows = getDisplayRows();

      var colgroup = win.document.getElementById('tableColgroup');
      colgroup.innerHTML = '';
      var containerEl = win.document.querySelector('.table-container');
      var containerWidth = (containerEl && containerEl.clientWidth) || ((win.innerWidth || 1200) - 60);
      var rowsForWidth = applySort(applyFilters(getDisplayRows()));
      var adaptiveWidths = calcAdaptiveFieldWidths(rowsForWidth, containerWidth, widths);

      COLUMNS.forEach(function (col) {
        var colEl = win.document.createElement('col');
        if (isFlexCol(col.key)) {
          colEl.style.width = (adaptiveWidths[col.key] || col.minWidth || 120) + 'px';
        } else {
          var w = widths[col.key] || col.width;
          colEl.style.width = w + 'px';
        }
        colgroup.appendChild(colEl);
      });

      var head = win.document.getElementById('tableHead');
      var trh = win.document.createElement('tr');
      COLUMNS.forEach(function (col) {
        var th = win.document.createElement('th');
        th.style.position = 'relative';
        if (col.key === '__avatar') th.classList.add('col-sticky-avatar');
        if (col.key === 'name') th.classList.add('col-sticky-name');
        if (isFlexCol(col.key)) {
          if (adaptiveWidths && adaptiveWidths[col.key]) th.style.width = adaptiveWidths[col.key] + 'px';
        } else {
          var initW = widths[col.key] || col.width;
          if (initW) th.style.width = initW + 'px';
        }
        if (col.key === '__chk') {
          var chkWrap = win.document.createElement('div');
          chkWrap.className = 'chk-wrap-th';
          var rowsNow = applySort(applyFilters(getDisplayRows()));
          var allState = v74GetRowsSelectionState(rowsNow);
          var chkAll = createCustomCheckboxDoc(win.document, allState.checked, function (checked) {
            var rows = applySort(applyFilters(getDisplayRows()));
            rows.forEach(function (r) { state.selected[r.__id] = checked; v74SyncMainSelectionByDetail(r); });
            renderAll();
          }, 14);
          if (allState.indeterminate) chkAll.setIndeterminate(true);
          chkWrap.appendChild(chkAll);
          th.appendChild(chkWrap);
        } else {
          var textSpan = win.document.createElement('span');
          textSpan.textContent = col.label;
          th.appendChild(textSpan);
          if (isFlexCol(col.key)) {
            var lockBtn = win.document.createElement('button');
            var lockedMap = getFieldColLocked();
            lockBtn.textContent = lockedMap[col.key] ? '🔒' : '🔓';
            lockBtn.title = lockedMap[col.key] ? '当前固定宽度，点击恢复自适应' : '当前自适应，点击固定当前宽度';
            lockBtn.style.cssText = 'margin-left:4px;border:none;background:transparent;cursor:pointer;font-size:12px;padding:0 2px;';
            lockBtn.addEventListener('click', function(e){ e.stopPropagation(); if (!getFieldColLocked()[col.key]) saveColWidth(col.key, th.offsetWidth || parseInt(th.style.width,10) || 120); toggleFieldColLocked(col.key); renderAll(); });
            th.appendChild(lockBtn);
          }
        }
        if (col.resizable) {
          var handle = win.document.createElement('div');
          handle.className = 'resize-handle';
          var startX, startW;
          handle.addEventListener('mousedown', function (ev) {
            ev.preventDefault();
            startX = ev.clientX;
            startW = th.offsetWidth;
            handle.classList.add('dragging');
            function syncWidth(nw) {
              th.style.width = nw + 'px';
              var idx = COLUMNS.indexOf(col);
              var colEls = colgroup.querySelectorAll('col');
              if (colEls[idx]) colEls[idx].style.width = nw + 'px';
              var mgColgroup = win.document.getElementById('mainGroupColgroup');
              if (mgColgroup) {
                var mgCols = mgColgroup.querySelectorAll('col');
                if (mgCols[idx]) mgCols[idx].style.width = nw + 'px';
              }
              var mgHeadThs = win.document.querySelectorAll('#mainGroupHead th');
              if (mgHeadThs && mgHeadThs[idx]) mgHeadThs[idx].style.width = nw + 'px';
            }
            function onMove(ev2) {
              var minW = col.minWidth || 50;
              var nw = Math.max(minW, startW + (ev2.clientX - startX));
              syncWidth(nw);
            }
            function onUp() {
              win.document.removeEventListener('mousemove', onMove);
              win.document.removeEventListener('mouseup', onUp);
              handle.classList.remove('dragging');
              if (isFlexCol(col.key)) { saveFieldDragAsWeight(col.key, th.offsetWidth); } else { saveColWidth(col.key, th.offsetWidth); }
            }
            win.document.addEventListener('mousemove', onMove);
            win.document.addEventListener('mouseup', onUp);
          });
          th.appendChild(handle);
        }
        trh.appendChild(th);
      });
      head.innerHTML = '';
      head.appendChild(trh);

      var body = win.document.getElementById('tableBody');
      body.innerHTML = '';
      var rows = applySort(applyFilters(displayRows));
      var detailBadge = win.document.getElementById('detailCountBadge');
      if (detailBadge) detailBadge.textContent = rows.length + ' 条';
      var pendingResize = [];

      rows.forEach(function (row, idx) {
        var disp = computeDisplayFields(row);
        var tr = win.document.createElement('tr');
        tr.className = 'row-' + row.__platform;
          if (isRemoteSyncRecord(row) && !isRemoteEditableEnabled()) { tr.classList.add('wa-remote-readonly-row'); tr.title = getRemoteSyncReadonlyTitle(row); delete state.selected[row.__id]; }
        if (row.__mainKey) {
          tr.setAttribute('data-main-key', row.__mainKey);
        }
        COLUMNS.forEach(function (col) {
          var td = win.document.createElement('td');
          if (isRemoteSyncRecord(row) && !isRemoteEditableEnabled()) {
            v99RenderRemoteCell(td, col, row, idx, disp);
            if (col.key === 'manualPhone') v111ApplyPhoneCell(td, row.__mainKey || '');
          } else if (col.key === '__index') {
            td.style.textAlign = 'center';
            td.style.color = 'var(--sub)';
            td.style.fontSize = '12px';
            td.style.userSelect = 'none';
            td.textContent = (idx + 1);
          } else if (col.key === '__chk') {
            td.style.textAlign = 'center';
            if (isRemoteSyncRecord(row) && !isRemoteEditableEnabled()) {
              var lock = win.document.createElement('span');
              lock.textContent = '🔒';
              lock.title = '其他源数据为只读，不能参与批量修改或删除';
              lock.style.cssText = 'font-size:14px;color:#64748b;cursor:not-allowed;';
              td.appendChild(lock);
            } else {
              var chk = createCustomCheckboxDoc(win.document, !!state.selected[row.__id], function (checked) {
                state.selected[row.__id] = checked;
                v74SyncMainSelectionByDetail(row);
                renderAll();
              }, 14);
              td.appendChild(chk);
            }
          } else if (col.key === '__source') {
            var sourceBox = win.document.createElement('div');
            sourceBox.style.cssText = 'display:flex;gap:4px;align-items:center;flex-wrap:wrap;max-width:100%;overflow:hidden;box-sizing:border-box;';
            if (isRemoteSyncRecord(row)) appendRemoteEditableBadge(win.document, sourceBox, row);
            else appendLocalEditableBadge(win.document, sourceBox);
            var blockedNorm103 = getRowPhoneNorm(row);
            if (blockedNorm103 && isAssociationBlockedV103(row.__id, blockedNorm103, getSettings(), row)) {
              var blockedBadge103 = win.document.createElement('span');
              blockedBadge103.textContent = '🚫';
              blockedBadge103.title = '已禁止此联系人按当前号码自动关联';
              sourceBox.appendChild(blockedBadge103);
            }
            td.appendChild(sourceBox);
          } else if (col.key === '__platform') {
            if (row.__isGroup) {
              td.innerHTML = '<span class="plat-badge" style="background:#6d4c41;">' + String.fromCodePoint(0x1F517) + ' \u7efc\u5408(' + row.__memberCount + ')</span>';
            } else {
              var info = getPlatformInfo(row.__platform);
              td.innerHTML = '<span class="plat-badge" style="background:' + info.color + ';">' + info.short + '</span>';
            }
              } else if (col.key === '__avatar') {
            td.classList.add('col-sticky-avatar');
            td.style.textAlign = 'center';
            td.style.verticalAlign = 'middle';
            td.style.padding = '3px';
            var avSrc = row.avatarData || row.__avatarData || row.__avatar || row.avatar || '';
            if (!avSrc && row.__members && Array.isArray(row.__members)) {
              for (var mi = 0; mi < row.__members.length; mi++) {
                var mAv = row.__members[mi].avatarData || row.__members[mi].__avatarData || row.__members[mi].avatar || row.__members[mi].__avatar;
                if (mAv) { avSrc = mAv; break; }
              }
            }
            if (avSrc) {
              var avImg = win.document.createElement('img');
              v1062BindAvatarImage(avImg, row, avSrc);
              avImg.style.cssText = 'width:34px;height:34px;border-radius:50%;object-fit:cover;border:1.5px solid var(--border,#d1d7db);display:block;margin:0 auto;cursor:pointer;transition:transform .15s;';
              avImg.title = '点击查看原图';
              (function(srcCopy) {
                avImg.onmouseover = function() { avImg.style.transform = 'scale(1.15)'; };
                avImg.onmouseout = function() { avImg.style.transform = 'scale(1)'; };
                avImg.onclick = function(e) { e.stopPropagation(); win.open(srcCopy, '_blank'); };
              })(avSrc);
              td.appendChild(avImg);
            } else {
              var avPh = win.document.createElement('div');
              avPh.style.cssText = 'width:34px;height:34px;border-radius:50%;background:var(--border,#e0e0e0);color:var(--sub,#888);display:flex;align-items:center;justify-content:center;font-size:14px;margin:0 auto;user-select:none;';
              avPh.title = '暂无头像';
              avPh.textContent = '👤';
              td.appendChild(avPh);
            }
          } else if (col.key === '__link') {
            td.classList.add('v1003-link-cell');
            td.style.cssText += ';position:relative;overflow:hidden!important;box-sizing:border-box;';
            if (isRemoteSyncRecord(row)) {
              td.innerHTML = row.__associationBlocked
                ? '<span style="color:#ef6c00;font-size:11px;font-weight:700;">已解绑（他源）</span>'
                : (row.__mainKey ? '<span style="color:#00a884;font-size:11px;font-weight:700;">已关联(' + Number(row.__linkInfo && row.__linkInfo.memberCount || 0) + ')（他源）</span>' : '');
            } else if (row.__mainKey) {
              var linkBox = win.document.createElement('div');
              linkBox.style.cssText = 'display:flex;gap:4px;align-items:center;flex-wrap:wrap;max-width:100%;overflow:hidden;box-sizing:border-box;';
              var badge = win.document.createElement('span');
              badge.style.cssText = 'display:inline-block;padding:2px 6px;border-radius:10px;font-size:11px;color:#fff;background:#00a884;white-space:nowrap;';
              var linkedCount105 = Number(row.__linkInfo && row.__linkInfo.memberCount || 0);
              if (!linkedCount105 && row.__linkInfo && Array.isArray(row.__linkInfo.memberIds)) linkedCount105 = row.__linkInfo.memberIds.length;
              badge.textContent = linkedCount105 >= 2 ? ('已关联(' + linkedCount105 + ')') : '已关联';
              linkBox.appendChild(badge);

              var unlinkBtn = win.document.createElement('button');
              unlinkBtn.className = 'lg-act-btn lg-act-unlink';
              unlinkBtn.textContent = '解绑';
              unlinkBtn.title = '解除该渠道的关联并恢复为独立联系人';
              unlinkBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                if (!win.confirm('确定解除渠道 [' + (row.name || row.__id) + '] 的关联吗？解除后将恢复为独立联系人。')) return;
                var ok104 = unlinkChannel(row.__id);
                renderAll();
                if (ok104) {
                  win.alert('已解除当前号码的关联；状态正在同步到其他源。可点击“恢复关联”撤销。');
                } else {
                  win.alert('该联系人当前没有可解除的有效号码关联，残留状态已清理。');
                }
              });
              linkBox.appendChild(unlinkBtn);
              td.appendChild(linkBox);
            } else if (row.__associationBlocked) {
              var restoreBox = win.document.createElement('div');
              restoreBox.style.cssText = 'display:flex;gap:4px;align-items:center;flex-wrap:wrap;max-width:100%;';
              var blockedBadge = win.document.createElement('span');
              blockedBadge.style.cssText = 'display:inline-block;padding:2px 6px;border-radius:10px;font-size:11px;color:#fff;background:#ef6c00;white-space:nowrap;';
              blockedBadge.textContent = '已解绑';
              restoreBox.appendChild(blockedBadge);
              var restoreBtn = win.document.createElement('button');
              restoreBtn.className = 'lg-act-btn';
              restoreBtn.textContent = '恢复关联';
              restoreBtn.title = '撤销当前号码的人工解绑规则并重新扫描';
              restoreBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                if (!win.confirm('确定恢复联系人 [' + (row.name || row.__id) + '] 当前号码的自动关联吗？')) return;
                var restored104 = relinkChannelAllow(row.__id);
                var scan104 = runLinkScan({ force:true });
                renderAll();
                if (!restored104) win.alert('当前号码没有有效的人工解绑规则。');
                else if (getValidStoredLinkInfo(row.__id)) win.alert('已恢复自动关联，并重新加入同号码关联组。');
                else win.alert('已恢复自动关联资格；当前有效同号码联系人不足两人，暂未生成主记录。');
              });
              restoreBox.appendChild(restoreBtn);
              td.appendChild(restoreBox);
            } else {
              td.innerHTML = '<span style="color:var(--sub);font-size:11px;">-</span>';
            }
          } else if (col.key === '__id') {
            td.className = 'id-cell';
            if (row.__isGroup) {
              td.textContent = '\u2605 ' + row.__id.replace('MAIN::', '\u4e3b\u8bb0\u5f55:');
              td.title = row.__id;
            } else {
              v1003AppendAdaptiveIdentifier(td, row.__id);
            }
          } else if (col.key === 'name') {
            td.classList.add('col-sticky-name');
            td.textContent = disp.displayName;
            if (disp.nameNote) {
              td.title = '\u539f\u59cb\u8bc6\u522b\u540d\u79f0\uff1a' + disp.nameNote;
              td.style.color = 'var(--sub)';
              td.style.fontStyle = 'italic';
            } else {
              td.title = disp.displayName;
            }
            v1003EnableNameCopy(td, disp.displayName);
          } else if (col.key === 'tag') {
            var sel = win.document.createElement('select');
            sel.className = 'tag-sel-inline';
            var curTagVal = row.tag || '';
            var curTagColor = getTag1Color(curTagVal);
            sel.style.background = (curTagVal ? curTagColor : 'transparent');
            sel.style.color = (curTagVal ? '#fff' : 'inherit');
            sel.style.fontWeight = '600';
            sel.style.border = '1px solid ' + (curTagVal ? curTagColor : 'var(--border)');
            var t1List = getTags1();
            t1List.forEach(function (t) {
              var opt = win.document.createElement('option');
              opt.value = t.key; opt.textContent = t.label;
              opt.style.background = 'var(--card, #fff)';
              opt.style.color = 'var(--text, #111b21)';
              if (curTagVal === t.key) opt.selected = true;
              sel.appendChild(opt);
            });
            if (isRemoteSyncRecord(row) && !isRemoteEditableEnabled()) { sel.disabled = true; sel.title = getRemoteSyncReadonlyTitle(row); sel.style.cursor = 'not-allowed'; sel.style.opacity = '0.75'; }
            sel.addEventListener('change', function () {
              var newCol = getTag1Color(sel.value);
              sel.style.background = (sel.value ? newCol : 'transparent');
              sel.style.color = (sel.value ? '#fff' : 'inherit');
              sel.style.borderColor = (sel.value ? newCol : 'var(--border)');
              if (guardRemoteSyncEdit(row)) { renderAll(); return; }
              upsertTagSmart(row.__id, {}, sel.value);
              renderAll();
            });
            td.appendChild(sel);
          } else if (col.key === 'tag2') {
            // v54 方案B：平时紧凑徽章显示，点击弹出悬浮勾选面板
            var curTags2 = Array.isArray(row.tag2) ? row.tag2 : (row.tag2 ? [row.tag2] : []);
            var t2List = getTags2();
            var badgeWrap = win.document.createElement('div');
            badgeWrap.style.cssText = 'display:flex;gap:3px;flex-wrap:wrap;align-items:center;cursor:pointer;min-height:22px;';
            badgeWrap.title = '点击选择画像(多选)';

            if (!curTags2.length) {
              badgeWrap.innerHTML = '<span style="font-size:11px;color:var(--sub);border:1px dashed var(--border);padding:1px 5px;border-radius:3px;">+画像</span>';
            } else {
              curTags2.forEach(function (tKey) {
                var def = t2List.filter(function(x){ return x.key === tKey; })[0];
                var bg = def ? def.color : '#78909c';
                var lbl = def ? def.label : tKey;
                var badge = win.document.createElement('span');
                badge.style.cssText = 'display:inline-block;padding:1px 5px;border-radius:10px;font-size:10px;color:#fff;background:' + bg + ';white-space:nowrap;line-height:1.2;';
                badge.textContent = lbl;
                badgeWrap.appendChild(badge);
              });
            }

            badgeWrap.addEventListener('click', function (ev) {
              ev.stopPropagation();
              showTag2SelectDropdown(win, ev, row.__id, curTags2, function (newTags) {
                upsertTag2Smart(row.__id, newTags);
                renderAll();
              });
            });
            td.appendChild(badgeWrap);
          } else if (col.key === '__stages') {
            var stArr = Array.isArray(row.stages) ? row.stages : [];
            var wrap = win.document.createElement('div');
            wrap.style.cssText = 'display:flex;gap:4px;flex-wrap:wrap;';
            STAGES.forEach(function (st) {
              var lbl = win.document.createElement('label');
              lbl.style.cssText = 'display:flex;align-items:center;gap:2px;font-size:11px;cursor:pointer;';
              var cb = createCustomCheckboxDoc(win.document, stArr.indexOf(st.key) >= 0, function (checked) {
                toggleStageSmart(row.__id, st.key, checked);
                renderAll();
              }, 13);
              lbl.appendChild(cb);
              var span = win.document.createElement('span');
              span.textContent = getStageLabel(st.key);
              lbl.appendChild(span);
              wrap.appendChild(lbl);
            });
            td.appendChild(wrap);
          } else if (col.key === 'updatedAt') {
            td.textContent = fmtTime(row.updatedAt);
          } else if (col.key === '__actions') {
            var copyBtn = win.document.createElement('button');
            copyBtn.className = 'icon-btn';
            copyBtn.textContent = String.fromCodePoint(0x1F4CB);
            copyBtn.title = '\u590d\u5236\u8d44\u6599';
            copyBtn.addEventListener('click', function () { copyContactText(row); });
            var delBtn = win.document.createElement('button');
            delBtn.className = 'icon-btn';
            delBtn.textContent = String.fromCodePoint(0x1F5D1) + String.fromCodePoint(0xFE0F);
            delBtn.title = row.__isGroup ? '\u89e3\u6563\u5206\u7ec4' : '\u5220\u9664';
            delBtn.addEventListener('click', function () {
              if (guardRemoteSyncEdit(row)) return;
              if (row.__isGroup) {
                if (win.confirm('\u8fd9\u662f\u4e00\u4e2a\u7efc\u5408\u5206\u7ec4\uff08' + row.__memberCount + ' \u4e2a\u6e20\u9053\uff09\uff0c\u786e\u5b9a\u89e3\u6563\u5e76\u5220\u9664\u5417\uff1f\u89e3\u6563\u540e\u5404\u6e20\u9053\u6062\u590d\u72ec\u7acb\u8bb0\u5f55\u3002')) {
                  unlinkAssociationMembersV103(row.__members.slice());
                  var d = loadData();
                  delete d[row.__id];
                  saveData(d);
                  renderAll();
                }
              } else {
                if (win.confirm('\u786e\u5b9a\u5220\u9664 ' + (row.name || row.__id) + ' \u7684\u8bb0\u5f55\uff1f')) {
                  deleteRow(row.__id);
                  delete state.selected[row.__id];
                  renderAll();
                }
              }
            });
            td.appendChild(copyBtn);
            td.appendChild(delBtn);
          } else if (col.key === 'manualPhone') {
            td.className = 'input-td';
            v111ApplyPhoneCell(td, row.__mainKey || '');
            var val = row.manualPhone || '';
            var isAutoFilled = (!val && disp.displayPhone);
            if (isAutoFilled) val = '';
            // v73.4：电话栏由 input 改为 textarea，支持自动换行，同时保留失焦保存和 Enter 确认
            var input = win.document.createElement('textarea');
            input.className = 'cell-input';
            input.value = val;
            input.rows = 1;
            input.placeholder = isAutoFilled ? disp.displayPhone + '\uff08\u81ea\u52a8\u8bc6\u522b\uff0c\u70b9\u51fb\u53ef\u7f16\u8f91\u4fdd\u5b58\uff09' : '';
            input.style.background = 'transparent';
            input.style.color = '#111b21';
            input.style.colorScheme = 'light';
            input.style.whiteSpace = 'pre-wrap';
            input.style.wordBreak = 'break-word';
            input.style.overflow = 'hidden';
            input.style.minHeight = '32px';
            input.__waDirty = false;
            input.addEventListener('compositionstart', function () { input.__v1004Composing = true; win.document.__v1004Composing = true; });
            input.addEventListener('compositionend', function () { input.__v1004Composing = false; win.document.__v1004Composing = false; v1004FlushPendingRender(); });
            input.addEventListener('input', function () {
              autoResizeCell(input);
              input.__waDirty = true;
              // v111：电话空值保持普通背景。
            });
            input.addEventListener('keydown', function (e) {
              if (e.key === 'Enter' && !e.shiftKey) {
                if (e.isComposing || this.__v1004Composing || (win.document && win.document.__v1004Composing)) return;
                e.preventDefault();
                e.stopPropagation();
                input.blur();
              }
            });
            input.addEventListener('blur', function () {
              autoResizeCell(input);
              if (!input.__waDirty) return;
              input.__waDirty = false;
              upsertCell(row.__id, 'manualPhone', input.value);
              // v111：电话空值保持普通背景。
            });
            td.appendChild(input);
            pendingResize.push(input);
          } else if (isBusinessFieldKeyV126(col.key)) {
            td.className = 'input-td';
            var val2 = row[col.key] || '';
            if (!val2) td.classList.add('cell-empty');
            var input2;
            if (col.key === 'remark' || col.key === 'f8' || state.wrapMode) {
              input2 = win.document.createElement('textarea');
              input2.className = 'cell-input';
              input2.value = val2;
              input2.rows = 1;
              pendingResize.push(input2);
            } else {
              input2 = win.document.createElement('input');
              var defV126=getBusinessFieldDefinitionV126(col.key); input2.type=(defV126&&defV126.type==='number')?'number':((defV126&&defV126.type==='date')?'date':'text');
              input2.className = 'cell-input';
              input2.value = val2;
            }
            // v73.2：管理面板文本字段输入过程中只更新本输入框状态，不保存、不聚合、不刷新整表；失焦后再统一保存并刷新 MAIN
            input2.__waDirty = false;
            input2.addEventListener('compositionstart', function () { input2.__v1004Composing = true; win.document.__v1004Composing = true; });
            input2.addEventListener('compositionend', function () { input2.__v1004Composing = false; win.document.__v1004Composing = false; v1004FlushPendingRender(); });
            input2.addEventListener('input', function () {
              autoResizeCell(input2);
              input2.__waDirty = true;
              td.classList.toggle('cell-empty', !input2.value);
            });
            // v73.3：Enter 确认保存，Shift+Enter 保留换行
            input2.addEventListener('keydown', function (e) {
              if (e.key === 'Enter' && !e.shiftKey) {
                if (e.isComposing || this.__v1004Composing || (win.document && win.document.__v1004Composing)) return;
                e.preventDefault();
                e.stopPropagation();
                input2.blur();
              }
            });
            input2.addEventListener('blur', function () {
              autoResizeCell(input2);
              if (!input2.__waDirty) return;
              input2.__waDirty = false;
              upsertCell(row.__id, col.key, input2.value);
              td.classList.toggle('cell-empty', !input2.value);
            });
            td.appendChild(input2);
          }
          tr.appendChild(td);
        });
        body.appendChild(tr);
      });
      body.parentElement.parentElement.classList.toggle('wrap-mode', state.wrapMode);

      win.requestAnimationFrame(function () {
        pendingResize.forEach(function (t) { autoResizeCell(t); });
      });

      renderMainGroupTable();
    }
    // ========================================================
    // v48 专属：渲染独立的主记录专区表格（强只读保护）
    // ========================================================
    function renderMainGroupTable() {
      rebuildColumnsV126();
      var mainSection = win.document.getElementById('mainGroupSection');
      var container = win.document.getElementById('mainGroupContainer');
      var badge = win.document.getElementById('mainGroupCountBadge');
      var collapseBtn = win.document.getElementById('mainGroupCollapseBtn');

      var mainRows = getMainGroupRows();
      if (!mainRows.length) {
        mainSection.style.display = 'none';
        return;
      }

      mainSection.style.display = 'block';
      badge.textContent = mainRows.length + ' 组';
      collapseBtn.textContent = state.mainGroupCollapsed ? '展开 ▼' : '收起 ▲';
      container.style.display = state.mainGroupCollapsed ? 'none' : 'block';

      var widths = getColWidths();
      var colgroup = win.document.getElementById('mainGroupColgroup');
      colgroup.innerHTML = '';
      var mgContainerWidth = (container && container.clientWidth) || ((win.innerWidth || 1200) - 60);
      var adaptiveWidths = calcAdaptiveFieldWidths(mainRows, mgContainerWidth, widths);
      COLUMNS.forEach(function (col) {
        var colEl = win.document.createElement('col');
        if (isFlexCol(col.key)) {
          colEl.style.width = (adaptiveWidths[col.key] || col.minWidth || 120) + 'px';
        } else {
          var w = widths[col.key] || col.width;
          colEl.style.width = w + 'px';
        }
        colgroup.appendChild(colEl);
      });

      var head = win.document.getElementById('mainGroupHead');
      var trh = win.document.createElement('tr');
      COLUMNS.forEach(function (col) {
        var th = win.document.createElement('th');
        th.style.position = 'relative';
        if (col.key === '__avatar') th.classList.add('col-sticky-avatar');
        if (col.key === 'name') th.classList.add('col-sticky-name');
        if (isFlexCol(col.key)) {
          if (adaptiveWidths && adaptiveWidths[col.key]) th.style.width = adaptiveWidths[col.key] + 'px';
        } else {
          var initW = widths[col.key] || col.width;
          if (initW) th.style.width = initW + 'px';
        }
        if (col.key === '__chk') {
          var chkWrap = win.document.createElement('div');
          chkWrap.className = 'chk-wrap-th';
          var mainState = v74GetRowsSelectionState(mainRows);
          var chkAllMain = createCustomCheckboxDoc(win.document, mainState.checked, function (checked) {
            mainRows.forEach(function (mr) { v74SetMainSelected(mr, checked); });
            renderAll();
          }, 14);
          if (mainState.indeterminate) chkAllMain.setIndeterminate(true);
          chkWrap.appendChild(chkAllMain);
          th.appendChild(chkWrap);
        } else {
          var textSpan = win.document.createElement('span');
          textSpan.textContent = col.label;
          th.appendChild(textSpan);
        }
        if (col.resizable) {
          var handle = win.document.createElement('div');
          handle.className = 'resize-handle';
          var startX, startW;
          handle.addEventListener('mousedown', function (ev) {
            ev.preventDefault();
            startX = ev.clientX;
            startW = th.offsetWidth;
            handle.classList.add('dragging');
            function syncWidth(nw) {
              th.style.width = nw + 'px';
              var idx = COLUMNS.indexOf(col);
              var colEls = colgroup.querySelectorAll('col');
              if (colEls[idx]) colEls[idx].style.width = nw + 'px';
              var mainColgroup = win.document.getElementById('tableColgroup');
              if (mainColgroup) {
                var mainCols = mainColgroup.querySelectorAll('col');
                if (mainCols[idx]) mainCols[idx].style.width = nw + 'px';
              }
              var mainHeadThs = win.document.querySelectorAll('#tableHead th');
              if (mainHeadThs && mainHeadThs[idx]) mainHeadThs[idx].style.width = nw + 'px';
            }
            function onMove(ev2) {
              var minW = col.minWidth || 50;
              var nw = Math.max(minW, startW + (ev2.clientX - startX));
              syncWidth(nw);
            }
            function onUp() {
              win.document.removeEventListener('mousemove', onMove);
              win.document.removeEventListener('mouseup', onUp);
              handle.classList.remove('dragging');
              if (isFlexCol(col.key)) { saveFieldDragAsWeight(col.key, th.offsetWidth); } else { saveColWidth(col.key, th.offsetWidth); }
            }
            win.document.addEventListener('mousemove', onMove);
            win.document.addEventListener('mouseup', onUp);
          });
          th.appendChild(handle);
        }
        trh.appendChild(th);
      });
      head.innerHTML = '';
      head.appendChild(trh);

      var body = win.document.getElementById('mainGroupBody');
      body.innerHTML = '';

      mainRows.forEach(function (row, idx) {
        var disp = computeDisplayFields(row);
        var tr = win.document.createElement('tr');
        tr.className = 'row-multi';

        COLUMNS.forEach(function (col) {
          var td = win.document.createElement('td');
          if (col.key === '__index') {
            td.style.textAlign = 'center';
            td.style.color = '#6d4c41';
            td.style.fontSize = '12px';
            td.style.fontWeight = 'bold';
            td.style.userSelect = 'none';
            td.textContent = (idx + 1);
          } else if (col.key === '__chk') {
            td.style.textAlign = 'center';
            var mainSelState = v74GetMainSelectionState(row);
            var mainChk = createCustomCheckboxDoc(win.document, mainSelState.checked, function (checked) {
              v74SetMainSelected(row, checked);
              renderAll();
            }, 14);
            if (mainSelState.indeterminate) mainChk.setIndeterminate(true);
            td.appendChild(mainChk);
          } else if (col.key === '__source') {
            td.textContent = '';
          } else if (col.key === '__platform') {
            td.innerHTML = '<span class="plat-badge" style="background:#6d4c41;">关联(' + row.__memberCount + ')</span>';
              } else if (col.key === '__avatar') {
            td.classList.add('col-sticky-avatar');
            td.style.textAlign = 'center';
            td.style.verticalAlign = 'middle';
            td.style.padding = '3px';
            var avSrc = row.avatarData || row.__avatarData || row.__avatar || row.avatar || '';
            if (!avSrc && row.__members && Array.isArray(row.__members)) {
              for (var mi = 0; mi < row.__members.length; mi++) {
                var mAv = row.__members[mi].avatarData || row.__members[mi].__avatarData || row.__members[mi].avatar || row.__members[mi].__avatar;
                if (mAv) { avSrc = mAv; break; }
              }
            }
            if (avSrc) {
              var avImg = win.document.createElement('img');
              v1062BindAvatarImage(avImg, row, avSrc);
              avImg.style.cssText = 'width:34px;height:34px;border-radius:50%;object-fit:cover;border:1.5px solid var(--border,#d1d7db);display:block;margin:0 auto;cursor:pointer;transition:transform .15s;';
              avImg.title = '点击查看原图';
              (function(srcCopy) {
                avImg.onmouseover = function() { avImg.style.transform = 'scale(1.15)'; };
                avImg.onmouseout = function() { avImg.style.transform = 'scale(1)'; };
                avImg.onclick = function(e) { e.stopPropagation(); win.open(srcCopy, '_blank'); };
              })(avSrc);
              td.appendChild(avImg);
            } else {
              var avPh = win.document.createElement('div');
              avPh.style.cssText = 'width:34px;height:34px;border-radius:50%;background:var(--border,#e0e0e0);color:var(--sub,#888);display:flex;align-items:center;justify-content:center;font-size:14px;margin:0 auto;user-select:none;';
              avPh.title = '暂无头像';
              avPh.textContent = '👤';
              td.appendChild(avPh);
            }
          } else if (col.key === '__link') {
            var isExp = !!state.expandedMainKeys[row.__id];
            var btn = win.document.createElement('button');
            btn.className = 'link-btn';
            btn.textContent = isExp ? '收起' : '展开';
            btn.title = isExp ? '收起并隐藏该组下表明细' : '在下方明细列表置顶展开并编辑本组 ' + row.__memberCount + ' 个独立渠道';
            btn.style.whiteSpace = 'normal';
            btn.style.wordBreak = 'break-word';
            btn.style.lineHeight = '1.25';
            btn.style.padding = '4px 6px';
            btn.style.fontSize = '12px';
            btn.style.textAlign = 'center';
            btn.style.display = 'inline-flex';
            btn.style.alignItems = 'center';
            btn.style.justifyContent = 'center';
            btn.style.maxWidth = '100%';
            btn.style.background = isExp ? '#54656f' : '#00a884';
            btn.style.borderColor = isExp ? '#54656f' : '#00a884';
            td.style.textAlign = 'center';
            td.style.verticalAlign = 'middle';
            btn.addEventListener('click', function () {
              if (state.expandedMainKeys[row.__id]) {
                delete state.expandedMainKeys[row.__id];
              } else {
                state.expandedMainKeys[row.__id] = true;
              }
              renderAll();
              if (state.expandedMainKeys[row.__id]) {
                var firstTarget = win.document.querySelector('tr[data-main-key="' + row.__id + '"]');
                if (firstTarget) {
                  firstTarget.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }
              }
            });
            td.appendChild(btn);
          } else if (col.key === '__id') {
            td.className = 'id-cell';
            td.textContent = '★ ' + row.__id.replace('MAIN::', '主记录:');
            td.title = row.__id;
          } else if (col.key === 'name') {
            td.classList.add('col-sticky-name');
            td.textContent = disp.displayName;
            td.title = disp.displayName;
            v1003EnableNameCopy(td, disp.displayName);
          } else if (col.key === 'tag') {
            var t1List = getTags1();
            var matchedTag = null;
            for (var i = 0; i < t1List.length; i++) {
              if (t1List[i].key === row.tag) { matchedTag = t1List[i]; break; }
            }
            var tagBg = matchedTag ? (matchedTag.color || '#cfd8dc') : '#cfd8dc';
            var tagTxt = matchedTag ? matchedTag.label : (row.tag || '无标签');
            td.innerHTML = '<span style="display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;color:#fff;background:' + tagBg + ';white-space:nowrap;line-height:1.3;">' + esc(tagTxt) + '</span>';
          } else if (col.key === 'tag2') {
            // 主记录自动汇集的画像并集徽章展示
            var curTags2 = Array.isArray(row.tag2) ? row.tag2 : (row.tag2 ? [row.tag2] : []);
            var t2List = getTags2();
            var badgeWrap = win.document.createElement('div');
            badgeWrap.style.cssText = 'display:flex;gap:3px;flex-wrap:wrap;align-items:center;';
            badgeWrap.title = '主记录自动汇总所有关联渠道的画像画像';
            if (!curTags2.length) {
              badgeWrap.textContent = '';
            } else {
              curTags2.forEach(function (tKey) {
                var def = t2List.filter(function(x){ return x.key === tKey; })[0];
                var bg = def ? def.color : '#78909c';
                var lbl = def ? def.label : tKey;
                var badge = win.document.createElement('span');
                badge.style.cssText = 'display:inline-block;padding:1px 5px;border-radius:10px;font-size:10px;color:#fff;background:' + bg + ';white-space:nowrap;line-height:1.2;';
                badge.textContent = lbl;
                badgeWrap.appendChild(badge);
              });
            }
            td.appendChild(badgeWrap);
          } else if (col.key === '__stages') {
            var stArr = Array.isArray(row.stages) ? row.stages : [];
            td.textContent = stArr.map(function (k) { return getStageLabel(k); }).join(' / ');
          } else if (col.key === 'updatedAt') {
            td.textContent = fmtTime(row.updatedAt);
          } else if (col.key === '__actions') {
            var copyBtn = win.document.createElement('button');
            copyBtn.className = 'icon-btn';
            copyBtn.textContent = '📋';
            copyBtn.title = '复制主记录资料';
            copyBtn.addEventListener('click', function () { copyContactText(row); });

            var delBtn = win.document.createElement('button');
            delBtn.className = 'icon-btn';
            delBtn.textContent = '🗑️';
            delBtn.title = '解散分组';
            delBtn.addEventListener('click', function () {
              if (win.confirm('这是跨渠道综合分组（' + row.__memberCount + ' 个渠道），确定解散吗？解散后各渠道恢复独立记录。')) {
                unlinkAssociationMembersV103(row.__members.slice());
                var d = loadData();
                delete d[row.__id];
                saveData(d);
                renderAll();
              }
            });
            td.appendChild(copyBtn);
            td.appendChild(delBtn);
          } else if (col.key === 'manualPhone') {
            td.className = 'input-td v1002-main-phone-cell';
            v111ApplyPhoneCell(td, row.__id);
            td.style.whiteSpace = 'normal';
            td.style.overflow = 'visible';
            td.style.verticalAlign = 'top';
            var inp = win.document.createElement('textarea');
            inp.className = 'cell-input cell-readonly v1002-main-phone-textarea';
            inp.readOnly = true;
            inp.rows = 1;
            inp.wrap = 'soft';
            inp.value = row.manualPhone || '';
            inp.title = '主记录电话为聚合信息，禁止直接修改。请点击[📋 查看明细]编辑各渠道独立信息。';
            inp.style.cssText += ';display:block;width:100%;min-width:0;min-height:32px;box-sizing:border-box;resize:none;overflow:hidden;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-all;line-height:1.4;';
            td.appendChild(inp);
            (function (phoneInput1002) {
              win.requestAnimationFrame(function () { autoResizeCell(phoneInput1002); });
            })(inp);
          } else if (isBusinessFieldKeyV126(col.key)) {
            td.className = 'input-td';
            var txt = win.document.createElement('textarea');
            txt.className = 'cell-input cell-readonly';
            txt.readOnly = true;
            txt.rows = 1;
            txt.value = row[col.key] || '';
            txt.title = '主记录说明为聚合信息，禁止直接修改。请点击[📋 查看明细]编辑各渠道独立信息。';
            td.appendChild(txt);
            win.requestAnimationFrame(function () { autoResizeCell(txt); });
          }
          tr.appendChild(td);
        });
        body.appendChild(tr);
      });
    }


    function renderBanner() {
      var s = getSettings();
      var banner = win.document.getElementById('banner');
      if (!banner) return;
      var last = s.lastBackupAt || 0;
      var allRows = getAllRows();
      var totalCount = allRows.length;
      if (totalCount === 0) {
        banner.style.display = 'none';
        banner.innerHTML = '';
        return;
      }
      var shouldWarn = false;
      var tipMsg = '';
      if (!last) {
        shouldWarn = true;
        tipMsg = '⚠️ 您尚未导出过备份数据，当前本地共有 ' + totalCount + ' 条联系人记录，建议立即导出备份以防数据丢失！';
      } else {
        var days = Math.floor((Date.now() - last) / 86400000);
        if (days >= 7) {
          shouldWarn = true;
          tipMsg = '⚠️ 您已有 ' + days + ' 天未导出备份数据，当前本地共有 ' + totalCount + ' 条联系人记录，建议定期导出 CSV 保存数据。';
        }
      }
      if (shouldWarn) {
        banner.style.display = 'flex';
        banner.innerHTML = '<span>' + tipMsg + '</span>' +
          '<button class="btn" id="bannerExportBtn" style="margin-left:12px;padding:4px 12px;font-size:12px;">立即导出 CSV</button>';
        var bBtn = win.document.getElementById('bannerExportBtn');
        if (bBtn) bBtn.addEventListener('click', doExport);
      } else {
        banner.style.display = 'none';
        banner.innerHTML = '';
      }
    }

    function v108CsvCell(v) {
      return '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"';
    }

    function v108DownloadCsv(lines, filename) {
      var csv = '\ufeff' + lines.join('\n');
      var blob = new win.Blob([csv], { type: 'text/csv;charset=utf-8;' });
      var url = win.URL.createObjectURL(blob);
      var a = win.document.createElement('a');
      a.href = url; a.download = filename;
      win.document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { try { win.URL.revokeObjectURL(url); } catch (e) {} }, 1000);
    }

    function doExport() {
      // v108：导出当前管理面板可见的数据全集；MAIN 仅作为只读快照，导入永不落库。
      var exportDateV124 = new Date();
      var exportedAt = exportDateV124.toISOString();
      var settings108 = getSettings() || {};
      var index108 = buildCrossSourceLinkIndexV103();
      var details108 = getAllRows();
      var mains108 = index108.mainRows || [];
      var exportFields108 = getAllFieldDefinitionsV126(true);
      var labels108 = {};
      exportFields108.forEach(function (f) { labels108[f.key] = f.label; });
      var lines = [];
      function add(a) { lines.push(a.map(v108CsvCell).join(',')); }
      add(['#V108_META','format','contacts-manager-v108']);
      add(['#V108_META','version',SYSTEM_VERSION_V124]);
      add(['#V108_META','exportedAt',exportedAt]);
      add(['#V108_META','sourceId',getLocalSyncSourceId()]);
      add(['#V108_META','sourceName',getLocalSyncSourceName()]);
      add(['#V108_META','detailCount',details108.length]);
      add(['#V108_META','mainCount',mains108.length]);
      add(['#V108_CONFIG','fieldLabels',JSON.stringify(labels108)]);
      add(['#V108_CONFIG','customFieldDefinitions',JSON.stringify(getCustomFieldDefinitionsV126(true))]);
      add(['#V108_CONFIG','stageLabels',JSON.stringify(settings108.stageLabels || {})]);
      add(['#V108_CONFIG','customTags1',JSON.stringify(getTags1())]);
      add(['#V108_CONFIG','customTags2',JSON.stringify(getTags2())]);
      add(['#V108_CONFIG','sourceColors',JSON.stringify(settings108.sourceColors || settings108.localSyncSourceColors || {})]);
      lines.push('');
      var headers108 = ['recordType','mainKey','parentMainKey','sourceId','sourceName','platform','id','name','manualPhone','avatar','tag','tag2','stages']
        .concat(exportFields108.map(function(f){ return f.key; }))
        .concat(exportFields108.map(function(f){ return f.key + '_label'; }))
        .concat(['updatedAt','memberIds','snapshotAt','snapshotModel']);
      add(headers108);
      function row108(type, id, e, parent) {
        e = e || {};
        var sid = type === 'MAIN' ? '' : getRowSourceId(e);
        var sname = type === 'MAIN' ? '' : getRowSourceName(e);
        var vals = [type, type === 'MAIN' ? id : '', parent || '', sid, sname,
          type === 'MAIN' ? 'main' : inferPlatform(e, id), id, e.name || '', e.manualPhone || '',
          (/^https?:\/\//i.test(String(e.avatar || '')) ? e.avatar : ''), e.tag || '',
          Array.isArray(e.tag2) ? e.tag2.join(';') : (e.tag2 || ''),
          Array.isArray(e.stages) ? e.stages.join(';') : (e.stages || '')];
        vals = vals.concat(exportFields108.map(function(f){ return e[f.key] == null ? '' : e[f.key]; }));
        vals = vals.concat(exportFields108.map(function(f){ return labels108[f.key] || f.label; }));
        vals = vals.concat([e.updatedAt || '', Array.isArray(e.memberIds) ? e.memberIds.join(';') : '', exportedAt,
          type === 'MAIN' ? 'dynamic-main-readonly' : 'detail-fact']);
        add(vals);
      }
      mains108.forEach(function(m){ row108('MAIN', m.__id, m, ''); });
      details108.forEach(function(d){ row108('DETAIL', d.__id, d, d.__mainKey || ''); });
      v108DownloadCsv(lines, getExportFilenameV124('csv', exportDateV124));
      setSettings({ lastBackupAt: Date.now() });
      renderBanner();
    }

    // v108.1：ExcelJS 工作簿导出。Excel 用于阅读、筛选和汇报；CSV 仍是正式恢复格式。
    function v1081Text(v) {
      if (v == null) return '';
      if (Array.isArray(v)) return v.join(';');
      return String(v);
    }

    function v1081Argb(color, fallback) {
      var value = String(color || '').trim().replace('#', '');
      if (/^[0-9a-fA-F]{3}$/.test(value)) value = value.split('').map(function (x) { return x + x; }).join('');
      if (!/^[0-9a-fA-F]{6}$/.test(value)) value = String(fallback || 'CFD8DC').replace('#', '');
      return ('FF' + value).toUpperCase();
    }

    function v1081PlatformColor(platform) {
      var map = { whatsapp:'#25D366', instagram:'#E1306C', facebook:'#0084FF', messenger:'#0084FF', telegram:'#26A5E4', main:'#6D4C41' };
      return map[String(platform || '').toLowerCase()] || '#78909C';
    }

    function v1081TagLabel(key, list) {
      var target = String(key || '');
      for (var i = 0; i < (list || []).length; i++) if (String(list[i].key || '') === target) return list[i].label || target;
      return target;
    }

    function v1081TagColor(key, list, fallback) {
      var target = String(key || '');
      for (var i = 0; i < (list || []).length; i++) if (String(list[i].key || '') === target) return list[i].color || fallback;
      return fallback;
    }

    function v1081SourceColor(row) {
      try {
        if (typeof getSourceBadgeColorV106 === 'function') return getSourceBadgeColorV106(row);
      } catch (e) {}
      return v1081PlatformColor(row && (row.__platform || row.platform));
    }

    function v1081DownloadBuffer(buffer, filename) {
      var blob = new win.Blob([buffer], { type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
      var url = win.URL.createObjectURL(blob);
      var a = win.document.createElement('a');
      a.href = url; a.download = filename;
      win.document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { try { win.URL.revokeObjectURL(url); } catch (e) {} }, 1500);
    }

    async function doExportExcel() {
      var btn = win.document.getElementById('excelExportBtn');
      var oldText = btn ? btn.textContent : '';
      try {
        if (typeof ExcelJS === 'undefined' || !ExcelJS.Workbook) {
          win.alert('ExcelJS 未内置；V202 无外部 CDN 依赖，请使用系统 CSV 导出功能。');
          return;
        }
        if (btn) { btn.disabled = true; btn.textContent = '正在生成Excel…'; }

        var exportDateV124 = new Date();
        var exportedAt = exportDateV124.toISOString();
        var settings = getSettings() || {};
        var index = buildCrossSourceLinkIndexV103();
        var details = getAllRows();
        var mains = index.mainRows || [];
        var tags1 = getTags1() || [];
        var tags2 = getTags2() || [];
        var excelFields126 = getAllFieldDefinitionsV126(true);
        var fieldLabels = {};
        excelFields126.forEach(function (f) { fieldLabels[f.key] = f.label; });

        var wb = new ExcelJS.Workbook();
        wb.creator = SYSTEM_NAME_V124 + ' ' + getDisplayVersionV124();
        wb.lastModifiedBy = SYSTEM_NAME_V124 + ' ' + getDisplayVersionV124();
        wb.created = new Date(); wb.modified = new Date();
        wb.subject = '联系人管理面板聚合快照';
        wb.title = '联系人管理完整聚合导出';
        wb.description = 'DETAIL 为事实明细；MAIN 为动态只读快照。CSV 仍是正式恢复格式。';

        var thinBorder = {
          top:{style:'thin',color:{argb:'FFD9E1E5'}}, left:{style:'thin',color:{argb:'FFD9E1E5'}},
          bottom:{style:'thin',color:{argb:'FFD9E1E5'}}, right:{style:'thin',color:{argb:'FFD9E1E5'}}
        };
        function styleHeader(ws, rowNo) {
          var row = ws.getRow(rowNo || 1);
          row.height = 28;
          row.eachCell(function (cell) {
            cell.font = { bold:true, color:{argb:'FFFFFFFF'} };
            cell.fill = { type:'pattern', pattern:'solid', fgColor:{argb:'FF00695C'} };
            cell.alignment = { vertical:'middle', horizontal:'center', wrapText:true };
            cell.border = thinBorder;
          });
        }
        function styleBody(ws, startRow) {
          for (var r = startRow || 2; r <= ws.rowCount; r++) {
            var row = ws.getRow(r);
            row.eachCell({includeEmpty:true}, function (cell) {
              cell.alignment = { vertical:'top', wrapText:true };
              cell.border = thinBorder;
              if (r % 2 === 0 && (!cell.fill || !cell.fill.type)) cell.fill = {type:'pattern',pattern:'solid',fgColor:{argb:'FFF7F9FA'}};
            });
          }
        }
        function setWidths(ws, widths) {
          widths.forEach(function (w, i) { ws.getColumn(i + 1).width = w; });
        }
        function addSheet(name) {
          return wb.addWorksheet(name, { views:[{state:'frozen', ySplit:1}], properties:{defaultRowHeight:20} });
        }
        function validAvatar(v) { return /^https?:\/\//i.test(String(v || '').trim()) ? String(v).trim() : ''; }
        function detailData(d) {
          return ['DETAIL', d.__mainKey || '', getRowSourceId(d), getRowSourceName(d), d.__platform || inferPlatform(d, d.__id),
            d.__id || '', d.name || '', d.manualPhone || '', validAvatar(d.avatar), d.tag || '',
            v1081Text(d.tag2), v1081Text(d.stages)]
            .concat(excelFields126.map(function (f) { return d[f.key] == null ? '' : d[f.key]; }))
            .concat([d.updatedAt || '', exportedAt, 'detail-fact']);
        }
        function mainData(m) {
          return ['MAIN', m.__id || '', '', '', 'main', m.__id || '', m.name || '', m.manualPhone || '', validAvatar(m.avatar), m.tag || '',
            v1081Text(m.tag2), v1081Text(m.stages)]
            .concat(excelFields126.map(function (f) { return m[f.key] == null ? '' : m[f.key]; }))
            .concat([m.updatedAt || '', exportedAt, 'dynamic-main-readonly']);
        }
        var machineHeaders = ['recordType','parentMainKey','sourceId','sourceName','platform','id','name','manualPhone','avatar','tag','tag2','stages']
          .concat(excelFields126.map(function (f) { return f.key + '｜' + fieldLabels[f.key]; }))
          .concat(['updatedAt','snapshotAt','snapshotModel']);

        // 1. 管理面板视图：MAIN 后紧跟其关联明细，支持 Excel 行分组折叠。
        var view = addSheet('管理面板视图');
        var viewHeaders = ['类型','来源','渠道','姓名','电话','标签','画像','阶段']
          .concat(excelFields126.map(function (f) { return fieldLabels[f.key]; }))
          .concat(['更新时间','记录ID','关联MAIN']);
        view.addRow(viewHeaders); styleHeader(view, 1);
        var byMain = {}, used = {};
        details.forEach(function (d) { if (d.__mainKey) (byMain[d.__mainKey] || (byMain[d.__mainKey] = [])).push(d); });
        function addViewRow(type, e, mainKey) {
          var platform = type === 'MAIN' ? 'main' : (e.__platform || inferPlatform(e, e.__id));
          var tag2Keys = Array.isArray(e.tag2) ? e.tag2 : (e.tag2 ? [e.tag2] : []);
          var stageKeys = Array.isArray(e.stages) ? e.stages : (e.stages ? [e.stages] : []);
          var vals = [type, type === 'MAIN' ? '动态聚合' : getRowSourceName(e), platform,
            e.name || '', e.manualPhone || '', v1081TagLabel(e.tag, tags1),
            tag2Keys.map(function(k){ return v1081TagLabel(k, tags2); }).join(';'),
            stageKeys.map(function(k){ return getStageLabel(k); }).join(';')]
            .concat(excelFields126.map(function(f){ return e[f.key] == null ? '' : e[f.key]; }))
            .concat([e.updatedAt || '', e.__id || '', mainKey || '']);
          var row = view.addRow(vals);
          row.height = 26;
          if (type === 'MAIN') {
            row.font = { bold:true, color:{argb:'FFFFFFFF'} };
            row.eachCell(function(c){ c.fill={type:'pattern',pattern:'solid',fgColor:{argb:'FF6D4C41'}}; c.border=thinBorder; c.alignment={vertical:'top',wrapText:true}; });
          } else {
            row.getCell(1).fill = {type:'pattern',pattern:'solid',fgColor:{argb:v1081Argb(v1081SourceColor(e))}};
            row.getCell(1).font = {bold:true,color:{argb:'FFFFFFFF'}};
            if (e.tag) row.getCell(6).fill = {type:'pattern',pattern:'solid',fgColor:{argb:v1081Argb(v1081TagColor(e.tag,tags1,'#CFD8DC'))}};
          }
          return row;
        }
        mains.forEach(function (m) {
          addViewRow('MAIN', m, m.__id || '');
          (byMain[m.__id] || []).forEach(function (d) { var rr=addViewRow('DETAIL',d,m.__id); rr.outlineLevel=1; used[d.__id]=true; });
        });
        details.forEach(function (d) { if (!used[d.__id]) addViewRow('DETAIL',d,d.__mainKey || ''); });
        view.autoFilter = {from:{row:1,column:1},to:{row:Math.max(1,view.rowCount),column:viewHeaders.length}};
        view.properties.outlineProperties = { summaryBelow:false, summaryRight:false };
        setWidths(view, [10,18,12,22,20,14,22,20].concat(excelFields126.map(function(){return 24;})).concat([20,28,28]));
        styleBody(view,2);

        // 2. DETAIL：机器可读事实明细；ID、电话、来源等统一使用文本。
        var detailWs = addSheet('联系人明细_DETAIL');
        detailWs.addRow(machineHeaders); styleHeader(detailWs,1);
        details.forEach(function(d){ detailWs.addRow(detailData(d)); });
        detailWs.autoFilter = {from:{row:1,column:1},to:{row:Math.max(1,detailWs.rowCount),column:machineHeaders.length}};
        setWidths(detailWs,[12,28,24,18,12,30,22,20,42,14,20,20].concat(excelFields126.map(function(){return 24;})).concat([20,24,20]));
        styleBody(detailWs,2);
        [2,3,6,8].forEach(function(c){ detailWs.getColumn(c).numFmt='@'; });

        // 3. MAIN：动态聚合快照，单独保护，任何导入流程均不得写回事实库。
        var mainWs = addSheet('主记录快照_MAIN');
        mainWs.addRow(machineHeaders.concat(['memberCount','sourceCount','memberIds'])); styleHeader(mainWs,1);
        mains.forEach(function(m){ mainWs.addRow(mainData(m).concat([m.__memberCount || 0,m.__sourceCount || 0,v1081Text(m.memberIds)])); });
        mainWs.autoFilter = {from:{row:1,column:1},to:{row:Math.max(1,mainWs.rowCount),column:machineHeaders.length+3}};
        setWidths(mainWs,[12,28,16,16,12,30,22,20,42,14,20,20].concat(excelFields126.map(function(){return 24;})).concat([20,24,24,14,14,48]));
        styleBody(mainWs,2);
        mainWs.eachRow(function(row){ row.eachCell(function(cell){ cell.protection={locked:true}; }); });
        await mainWs.protect('MAIN_READONLY_V1081', {selectLockedCells:true,selectUnlockedCells:false,formatCells:false,insertRows:false,deleteRows:false});

        // 4. 配置：稳定键与显示名称并存，同时保存颜色的文本值和单元格填充色。
        var configWs = addSheet('界面与字段配置');
        configWs.addRow(['配置类别','稳定键','显示名称/值','颜色','备注']); styleHeader(configWs,1);
        excelFields126.forEach(function(f){ configWs.addRow([f.dynamic?'动态字段':'固定字段',f.key,fieldLabels[f.key],'',(f.dynamic?('类型='+f.type+(f.archivedAt?'；已归档':'；启用')):'稳定键不可修改')]); });
        configWs.addRow(['原始配置','customFieldDefinitions',JSON.stringify(getCustomFieldDefinitionsV126(true)),'','JSON']);
        STAGES.forEach(function(st){ configWs.addRow(['阶段',st.key,getStageLabel(st.key),'','']); });
        tags1.forEach(function(t){ var r=configWs.addRow(['标签',t.key,t.label || t.key,t.color || '','']); r.getCell(4).fill={type:'pattern',pattern:'solid',fgColor:{argb:v1081Argb(t.color)}}; });
        tags2.forEach(function(t){ var r=configWs.addRow(['画像',t.key,t.label || t.key,t.color || '','']); r.getCell(4).fill={type:'pattern',pattern:'solid',fgColor:{argb:v1081Argb(t.color)}}; });
        var sourceSeen = {};
        details.forEach(function(d){ var sid=getRowSourceId(d), key=String(sid||''); if(sourceSeen[key])return; sourceSeen[key]=true; var color=v1081SourceColor(d); var r=configWs.addRow(['来源',sid,getRowSourceName(d),color,'']); r.getCell(4).fill={type:'pattern',pattern:'solid',fgColor:{argb:v1081Argb(color)}}; });
        configWs.addRow(['原始配置','stageLabels',JSON.stringify(settings.stageLabels || {}),'','JSON']);
        configWs.addRow(['原始配置','sourceColors',JSON.stringify(settings.sourceColors || settings.localSyncSourceColors || {}),'','JSON']);
        setWidths(configWs,[18,28,42,16,28]); styleBody(configWs,2);

        // 5. 备份元信息。
        var metaWs = addSheet('备份信息');
        metaWs.addRow(['项目','值','说明']); styleHeader(metaWs,1);
        [
          ['格式','contacts-manager-xlsx-v108.1.1','Excel 阅读快照'],['脚本版本',SYSTEM_VERSION_V124,''],['导出时间',exportedAt,'ISO 8601'],
          ['本机来源ID',getLocalSyncSourceId(),'文本'],['本机来源名称',getLocalSyncSourceName(),''],
          ['DETAIL数量',details.length,'事实明细'],['MAIN数量',mains.length,'动态只读快照'],
          ['导出范围','管理面板当前汇总的全部数据','包含本源与已加载他源'],
          ['头像策略','仅有效 HTTP/HTTPS 链接','blob: 永久跳过'],
          ['恢复建议','请使用助手导出的原始 CSV','v108.1.1 暂不导入 Excel']
        ].forEach(function(x){metaWs.addRow(x);});
        setWidths(metaWs,[22,48,40]); styleBody(metaWs,2);

        // 6. 面向使用者的安全说明。
        var helpWs = addSheet('导出说明');
        helpWs.addRow(['主题','说明']); styleHeader(helpWs,1);
        [
          ['管理面板视图','用于查看、筛选、打印和折叠关联明细；是导出时刻的静态快照。'],
          ['联系人明细_DETAIL','每行是一条真实联系人事实记录，稳定键、ID 和电话按文本保存。'],
          ['主记录快照_MAIN','MAIN 是动态聚合、只读快照，工作表已保护，永远不应写回联系人事实库。'],
          ['头像','只保存有效 HTTP/HTTPS 链接；不导出 blob: 临时头像，不嵌入图片。'],
          ['Excel导入','v108.1 不支持 Excel 导入，避免人工格式化或错误编辑造成覆盖风险。'],
          ['正式恢复','CSV 继续作为正式备份与恢复格式；请保留助手生成的原始 CSV。'],
          ['视觉差异','颜色、层级、列顺序、筛选和冻结已尽量还原；网页交互、弹窗和实时同步无法在 Excel 中复刻。']
        ].forEach(function(x){helpWs.addRow(x);});
        setWidths(helpWs,[24,100]); styleBody(helpWs,2);

        wb.worksheets.forEach(function(ws){ ws.pageSetup={orientation:'landscape',fitToPage:true,fitToWidth:1,fitToHeight:0,paperSize:9}; });
        var buffer = await wb.xlsx.writeBuffer();
        v1081DownloadBuffer(buffer, getExportFilenameV124('xlsx', exportDateV124));
        setSettings({lastBackupAt:Date.now(),lastExcelExportAt:Date.now()});
        renderBanner();
      } catch (err) {
        console.error('[v108.1.1 Excel export]', err);
        win.alert('Excel 导出失败：' + ((err && err.message) || err));
      } finally {
        if (btn) { btn.disabled=false; btn.textContent=oldText || '📊 导出Excel'; }
      }
    }

    function doExportSelected() {
      var selectedIds = v74GetSelectedIds();
      if (!selectedIds.length) { win.alert('请先勾选要导出的记录。'); return; }
      // v105：从当前动态关联索引导出快照，不依赖 MAIN 是否写入本地存储。
      var displayData105 = getPanelDisplayData();
      var index105 = buildCrossSourceLinkIndexV103();
      var exportRows105 = {};
      function addDetail105(id105) {
        var rec105 = displayData105[id105];
        if (rec105 && !isAnyMainRecordV93(id105, rec105)) exportRows105[id105] = rec105;
      }
      function addMain105(mainKey105) {
        var main105 = index105.groupByMainKey[mainKey105];
        if (!main105) return;
        exportRows105[mainKey105] = main105;
        (main105.__members || []).forEach(function(member105) {
          if (member105 && member105.__id) exportRows105[member105.__id] = member105;
        });
      }
      selectedIds.forEach(function(id105) {
        if (index105.groupByMainKey[id105]) {
          addMain105(id105);
          return;
        }
        addDetail105(id105);
        var link105 = index105.linkByMemberId[id105];
        if (link105 && link105.mainKey) addMain105(link105.mainKey);
      });
      var snapshotFields126 = getAllFieldDefinitionsV126(true);
      var headers = ['recordType','mainKey','parentMainKey','platform','id','name','manualPhone','avatar','avatarData','tag','tag2','stages'].concat(snapshotFields126.map(function (f) { return f.key; })).concat(['updatedAt','snapshotAt','snapshotModel']);
      var lines = [headers.join(',')];
      var selectedExportDateV124 = new Date();
      var snapshotAt105 = selectedExportDateV124.toISOString();
      Object.keys(exportRows105).forEach(function (id105) {
        var e105 = exportRows105[id105];
        if (!e105) return;
        var isMain105 = isAnyMainRecordV93(id105, e105);
        var parent105 = '';
        if (!isMain105) {
          var li105 = index105.linkByMemberId[id105];
          parent105 = li105 && li105.mainKey || '';
        }
        var vals105 = [isMain105 ? 'MAIN' : 'DETAIL', isMain105 ? id105 : '', parent105, isMain105 ? 'MAIN' : inferPlatform(e105, id105), id105, e105.name || '', e105.manualPhone || '', e105.avatar || '', e105.avatarData || '', e105.tag || '', Array.isArray(e105.tag2) ? e105.tag2.join(';') : (e105.tag2 || ''), Array.isArray(e105.stages) ? e105.stages.join(';') : (e105.stages || '')]
          .concat(snapshotFields126.map(function (f) { return e105[f.key] == null ? '' : e105[f.key]; }))
          .concat([e105.updatedAt || '', snapshotAt105, 'dynamic-main-readonly']);
        lines.push(vals105.map(function (v105) { return '"' + String(v105 == null ? '' : v105).replace(/"/g, '""') + '"'; }).join(','));
      });
      var csv = '\ufeff' + lines.join('\n');
      var blob = new win.Blob([csv], { type: 'text/csv;charset=utf-8;' });
      var url = win.URL.createObjectURL(blob);
      var a = win.document.createElement('a');
      a.href = url;
      a.download = getExportFilenameV124('csv', selectedExportDateV124);
      win.document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function(){ try{ win.URL.revokeObjectURL(url); }catch(e){} }, 1000);
    }

    function parseCsv(text) {
      var rows = [];
      var cur = [];
      var field = '';
      var inQ = false;
      for (var i = 0; i < text.length; i++) {
        var c = text[i];
        if (inQ) {
          if (c === '"') {
            if (text[i + 1] === '"') { field += '"'; i++; } else { inQ = false; }
          } else field += c;
        } else {
          if (c === '"') inQ = true;
          else if (c === ',') { cur.push(field); field = ''; }
          else if (c === '\n' || c === '\r') {
            if (c === '\r' && text[i + 1] === '\n') i++;
            cur.push(field); field = '';
            rows.push(cur); cur = [];
          } else field += c;
        }
      }
      if (field.length || cur.length) { cur.push(field); rows.push(cur); }
      return rows.filter(function (r) { return r.length > 1 || (r.length === 1 && r[0] !== ''); });
    }

    function v108SafeJson(v, fallback) {
      try { return JSON.parse(v); } catch (e) { return fallback; }
    }
    function v108IsHttpAvatar(v) { return /^https?:\/\//i.test(String(v || '').trim()); }
    function v126SerializableFields(obj) {
      var defs=getAllFieldDefinitionsV126(true).slice(), seen={};
      defs.forEach(function(f){seen[f.key]=true;});
      Object.keys(obj||{}).forEach(function(k){if(/^cf_[A-Za-z0-9_-]{6,96}$/.test(k)&&!seen[k]){seen[k]=true;defs.push({key:k,label:k,type:'text',dynamic:true});}});
      return defs;
    }
    function v108Comparable(e) {
      e = e || {}; var o = {};
      ['name','manualPhone','tag','platform'].forEach(function(k){ o[k] = e[k] || ''; });
      o.avatar = v108IsHttpAvatar(e.avatar) ? e.avatar : '';
      o.tag2 = (Array.isArray(e.tag2) ? e.tag2 : String(e.tag2 || '').split(';')).filter(Boolean).slice().sort();
      o.stages = (Array.isArray(e.stages) ? e.stages : String(e.stages || '').split(';')).filter(Boolean).slice().sort();
      v126SerializableFields(e).forEach(function(f){ o[f.key] = e[f.key] == null ? '' : e[f.key]; });
      return JSON.stringify(o);
    }
    function v108ParseImport(text) {
      var rows = parseCsv(String(text || '').replace(/^\ufeff/, ''));
      var out = { records:[], config:{}, meta:{}, legacy:false };
      var header = null, hi = -1;
      rows.forEach(function(r, idx) {
        if (r[0] === '#V108_META') out.meta[r[1]] = r[2] || '';
        else if (r[0] === '#V108_CONFIG') out.config[r[1]] = v108SafeJson(r[2], null);
        else if (!header && (r[0] === 'recordType' || r[0] === 'id')) { header = r; hi = idx; out.legacy = r[0] === 'id'; }
      });
      if (!header) return out;
      for (var i=hi+1;i<rows.length;i++) {
        var r=rows[i]; if (!r || !r.length) continue;
        var obj={}; header.forEach(function(h,j){ obj[h]=r[j] == null ? '' : r[j]; });
        if (out.legacy && obj.id) obj.recordType='DETAIL';
        if (obj.id) out.records.push(obj);
      }
      return out;
    }
    function v108TargetId(obj, localSid) {
      var sid = obj.sourceId || localSid;
      if (!sid || sid === localSid) return obj.id;
      return 'COPY::' + String(sid).replace(/[^a-zA-Z0-9_.-]/g,'_') + '::' + obj.id;
    }
    function v108MakeEntry(obj) {
      var e = {
        name:obj.name || '', platform:obj.platform || inferPlatform(null,obj.id), manualPhone:obj.manualPhone || '',
        avatar:v108IsHttpAvatar(obj.avatar) ? String(obj.avatar).trim() : '', tag:obj.tag || '',
        tag2:String(obj.tag2 || '').split(';').filter(Boolean), stages:String(obj.stages || '').split(';').filter(Boolean),
        updatedAt:parseInt(obj.updatedAt,10) || Date.now()
      };
      v126SerializableFields(obj).forEach(function(f){ e[f.key]=obj[f.key] == null ? '' : obj[f.key]; });
      return e;
    }
    function v108ShowImportPreview(parsed) {
      var localSid=getLocalSyncSourceId(), data=loadData() || {}, skippedMain=0;
      var items=[];
      parsed.records.forEach(function(obj,idx){
        if (String(obj.recordType||'DETAIL').toUpperCase()==='MAIN' || v105IsMainIdentity(obj.id) || String(obj.platform||'').toLowerCase()==='main') { skippedMain++; return; }
        var invalid=!obj.id || !obj.platform;
        var target=v108TargetId(obj,localSid), incoming=v108MakeEntry(obj), old=data[target];
        var status=invalid?'无效':(!old?'新增':(v108Comparable(old)===v108Comparable(incoming)?'相同':((parseInt(obj.updatedAt,10)||0)>(parseInt(old.updatedAt,10)||0)?'更新':'冲突')));
        items.push({idx:idx,obj:obj,target:target,incoming:incoming,status:status,checked:!invalid && status!=='相同'});
      });
      if (!items.length) { win.alert('没有可导入的 DETAIL 联系人。已安全跳过 MAIN：'+skippedMain+' 条。'); return; }
      var overlay=win.document.createElement('div');
      overlay.style.cssText='position:fixed;inset:0;z-index:2147483647;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;padding:24px;';
      var box=win.document.createElement('div');
      box.style.cssText='width:min(1100px,96vw);max-height:90vh;overflow:auto;background:#fff;color:#17212b;border-radius:12px;padding:18px;font:13px Arial;box-shadow:0 18px 60px rgba(0,0,0,.35);';
      box.innerHTML='<h2 style="margin:0 0 10px">v108 安全导入预览</h2><div style="color:#667;margin-bottom:10px">MAIN 永不导入，已跳过 '+skippedMain+' 条。异源记录将复制到独立命名空间，不覆盖本源 ID。</div>'+
        '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px"><select id="v108Source"><option value="">全部来源</option></select><input id="v108Search" placeholder="搜索姓名/电话/ID" style="flex:1;min-width:220px;padding:6px"><button id="v108All">全选可处理</button><button id="v108None">全不选</button></div>'+
        '<div id="v108Counts" style="margin-bottom:8px;font-weight:bold"></div><div style="overflow:auto;max-height:48vh"><table style="width:100%;border-collapse:collapse"><thead><tr><th>选择</th><th>状态</th><th>来源</th><th>渠道</th><th>姓名</th><th>电话</th><th>ID</th></tr></thead><tbody id="v108Body"></tbody></table></div>'+
        '<div style="margin-top:12px;padding:10px;background:#f5f7fa;border-radius:8px"><label><input type="checkbox" id="v108Fields" checked> 恢复字段名称</label>　<label><input type="checkbox" id="v108Tags" checked> 恢复标签及颜色</label>　<label><input type="checkbox" id="v108Colors"> 恢复来源颜色</label></div>'+
        '<div style="display:flex;justify-content:flex-end;gap:8px;margin-top:14px"><button id="v108Cancel">取消</button><button id="v108Apply" style="background:#00a884;color:#fff;border:0;border-radius:6px;padding:8px 18px">确认导入所选</button></div>';
      overlay.appendChild(box); win.document.body.appendChild(overlay);
      var sourceSel=box.querySelector('#v108Source'), search=box.querySelector('#v108Search'), body=box.querySelector('#v108Body');
      var sources={}; items.forEach(function(x){ var sid=x.obj.sourceId||localSid, sn=x.obj.sourceName||sid; sources[sid]=sn; });
      Object.keys(sources).forEach(function(sid){ var o=win.document.createElement('option');o.value=sid;o.textContent=sources[sid]+' ('+sid+')';sourceSel.appendChild(o); });
      function visible(x){ var q=String(search.value||'').toLowerCase(), sid=x.obj.sourceId||localSid; return (!sourceSel.value||sourceSel.value===sid) && (!q||[x.obj.name,x.obj.manualPhone,x.obj.id].join(' ').toLowerCase().indexOf(q)>=0); }
      function render(){ body.innerHTML=''; var counts={新增:0,更新:0,相同:0,冲突:0,无效:0}, chosen=0;
        items.forEach(function(x){counts[x.status]=(counts[x.status]||0)+1;if(x.checked)chosen++;if(!visible(x))return;var tr=win.document.createElement('tr');tr.style.borderTop='1px solid #ddd';
          var disabled=x.status==='无效'||x.status==='相同';tr.innerHTML='<td style="padding:6px"><input type="checkbox" '+(x.checked?'checked':'')+' '+(disabled?'disabled':'')+'></td><td>'+x.status+'</td><td>'+escapeHtml(x.obj.sourceName||x.obj.sourceId||'本源')+'</td><td>'+escapeHtml(x.obj.platform)+'</td><td>'+escapeHtml(x.obj.name)+'</td><td>'+escapeHtml(x.obj.manualPhone)+'</td><td title="'+escapeHtml(x.target)+'">'+escapeHtml(x.obj.id)+'</td>';
          var cb=tr.querySelector('input');cb.addEventListener('change',function(){x.checked=cb.checked;render();});body.appendChild(tr); });
        box.querySelector('#v108Counts').textContent='已选 '+chosen+'｜新增 '+counts['新增']+'｜更新 '+counts['更新']+'｜相同 '+counts['相同']+'｜冲突 '+counts['冲突']+'｜无效 '+counts['无效']; }
      sourceSel.onchange=render;search.oninput=render;
      box.querySelector('#v108All').onclick=function(){items.forEach(function(x){if(visible(x)&&x.status!=='无效'&&x.status!=='相同')x.checked=true;});render();};
      box.querySelector('#v108None').onclick=function(){items.forEach(function(x){if(visible(x))x.checked=false;});render();};
      box.querySelector('#v108Cancel').onclick=function(){overlay.remove();};
      box.querySelector('#v108Apply').onclick=function(){
        var selected=items.filter(function(x){return x.checked;}); if(!selected.length){win.alert('请至少选择一条记录。');return;}
        var beforeData=JSON.stringify(loadData()||{}), beforeSettings=JSON.stringify(getSettings()||{});
        GM_setValue('wa_remarks_v108_preimport_snapshot',JSON.stringify({at:Date.now(),data:beforeData,settings:beforeSettings}));
        try { var next=JSON.parse(beforeData); selected.forEach(function(x){next[x.target]=x.incoming;}); saveData(next);
          var patch={}; if(box.querySelector('#v108Fields').checked&&parsed.config.fieldLabels)patch.fieldLabels=parsed.config.fieldLabels;
          if(box.querySelector('#v108Fields').checked&&Array.isArray(parsed.config.customFieldDefinitions))patch.customFieldDefinitions=parsed.config.customFieldDefinitions;
          if(box.querySelector('#v108Fields').checked&&parsed.config.stageLabels)patch.stageLabels=parsed.config.stageLabels;
          if(box.querySelector('#v108Tags').checked&&parsed.config.customTags1)patch.customTags1=parsed.config.customTags1;
          if(box.querySelector('#v108Tags').checked&&parsed.config.customTags2)patch.customTags2=parsed.config.customTags2;
          if(box.querySelector('#v108Colors').checked&&parsed.config.sourceColors)patch.sourceColors=parsed.config.sourceColors;
          if(Object.keys(patch).length)setSettings(patch); rebuildColumnsV126(); scheduleV204BusinessConfigSync(); runLinkScan({force:true}); renderAll(); overlay.remove();
          try{scheduleLocalSyncAutoUpload();}catch(e){} win.alert('导入完成：'+selected.length+' 条 DETAIL。MAIN 已安全跳过 '+skippedMain+' 条。导入前快照已保存。');
        } catch(err) { GM_setValue(STORAGE_KEY,beforeData);GM_setValue(SETTINGS_KEY,beforeSettings);renderAll();win.alert('导入失败，已自动回滚：'+err.message); }
      }; render();
    }
    function doImport(text) {
      var parsed=v108ParseImport(text);
      if(!parsed.records.length){win.alert('未识别到可导入的 CSV 联系人数据。');return;}
      v108ShowImportPreview(parsed);
    }

    function applyDarkMode() {
      win.document.body.classList.toggle('dark', state.dark);
      win.document.getElementById('darkBtn').textContent = state.dark ? (String.fromCodePoint(0x2600) + String.fromCodePoint(0xFE0F) + ' \u6d45\u8272\u6a21\u5f0f') : (String.fromCodePoint(0x1F319) + ' \u6df1\u8272\u6a21\u5f0f');
    }


    function v66GetCfg(){
      return {
        minViewportWidth:getLayoutMinViewportWidth(),
        fieldUnifiedWidthPx:getFieldUnifiedWidthPx(),
        fieldUnifiedWidthAuto:isFieldUnifiedWidthAuto()
      };
    }
    function v66InitCfg(){
      var cfg=v66GetCfg(), a=win.document.getElementById('cfgMinChars'), fw=win.document.getElementById('cfgFieldUnifiedWidth'), fa=win.document.getElementById('cfgFieldUnifiedAuto'), vw=win.document.getElementById('cfgViewportWidth'), wrap=win.document.getElementById('cfgWidthWrap'), autoWrap=win.document.getElementById('cfgAutoWrap'), hint=win.document.getElementById('cfgWidthHint');
      if(vw) vw.textContent='当前 '+((win.innerWidth||0))+'px';
      if(!a) return;
      function syncAutoUi(){
        var auto = !!(fa && fa.checked);
        if(fw){ fw.disabled=auto; fw.style.opacity=auto?'0.45':'1'; fw.style.background=auto?'#eef2f7':''; }
        if(wrap){ wrap.style.opacity=auto?'0.62':'1'; }
        if(autoWrap){ autoWrap.style.background=auto?'rgba(0,168,132,.16)':'rgba(148,163,184,.16)'; autoWrap.style.color=auto?'#008f72':'var(--sub)'; }
        if(hint){ hint.textContent=auto?'当前：自适应':'当前：手动统一9列宽度 · Enter应用'; hint.style.color=auto?'var(--sub)':'#00a884'; }
      }
      function applyWidthCfg(){
        setSettings({
          layoutMinViewportWidth:parseInt(a.value,10)||1280,
          fieldUnifiedWidthAuto:!!(fa && fa.checked),
          fieldUnifiedWidthPx:parseInt(fw && fw.value,10)||220
        });
        renderAll();
      }
      if(!a.__v66Bound){
        a.__v66Bound=true;
        if(fa) fa.addEventListener('change',function(e){ e.stopPropagation(); syncAutoUi(); applyWidthCfg(); });
        [a, fw].forEach(function(inp){
          if(!inp) return;
          inp.addEventListener('keydown',function(e){
            if(e.key==='Enter'){
              e.preventDefault();
              e.stopPropagation();
              applyWidthCfg();
            }
          });
        });
      }
      a.value=cfg.minViewportWidth;
      if(fw) fw.value=cfg.fieldUnifiedWidthPx||220;
      if(fa) fa.checked=!!cfg.fieldUnifiedWidthAuto;
      syncAutoUi();
    }
    function v66SyncTableWidths(){
      var tables=[win.document.getElementById('mainTable'), win.document.getElementById('mainGroupTable')];
      tables.forEach(function(t){
        if(!t) return;
        var total=0;
        var cols=t.querySelectorAll('colgroup col');
        cols.forEach(function(c){ total += parseInt(c.style.width,10) || 0; });
        if(total>0){ t.style.width=total+'px'; t.style.minWidth=total+'px'; }
      });
    }
    function v66BindBottomScrollbar(){
      var bar=win.document.getElementById('waViewportBottomBar'),
          inner=win.document.getElementById('waViewportBottomBarInner'),
          detail=win.document.querySelector('.table-container'),
          main=win.document.getElementById('mainGroupContainer');
      if(!bar||!inner||!detail) return;

      // v69：只保留底部固定横滚，主记录区/明细列表内部横滚条通过 CSS 隐藏，但仍保留 scrollLeft 能力
      var rightSafe=32; // v71：右侧安全缓冲，避免最右操作栏被纵向滚动条/裁切层遮挡
      var full=Math.max(detail.scrollWidth||0, main?main.scrollWidth||0:0) + rightSafe;
      var cw=Math.max(detail.clientWidth||0, main?main.clientWidth||0:0, win.innerWidth||0);
      if(full>cw+8){
        bar.style.display='block';
        inner.style.width=full+'px';
      } else {
        bar.style.display='none';
      }

      function applyLeft(left,src){
        if(src!==bar && bar) bar.scrollLeft=left;
        if(src!==detail && detail) detail.scrollLeft=left;
        if(main && src!==main) main.scrollLeft=left;
      }

      if(bar.__v69Bound){
        applyLeft(bar.scrollLeft || detail.scrollLeft || (main ? main.scrollLeft : 0), null);
        return;
      }
      bar.__v69Bound=true;

      var syncing=false;
      function sync(left,src){
        if(syncing) return;
        syncing=true;
        applyLeft(left,src);
        syncing=false;
      }

      bar.addEventListener('scroll',function(){ sync(bar.scrollLeft,bar); });
      detail.addEventListener('scroll',function(){ sync(detail.scrollLeft,detail); });
      if(main) main.addEventListener('scroll',function(){ sync(main.scrollLeft,main); });

      // 触控板/横向滚轮场景：内部滚动条不可见，但横滑仍同步到底部横滚
      detail.addEventListener('wheel',function(e){
        if(Math.abs(e.deltaX)>Math.abs(e.deltaY)){
          setTimeout(function(){ sync(detail.scrollLeft,detail); },0);
        }
      },{passive:true});
      if(main){
        main.addEventListener('wheel',function(e){
          if(Math.abs(e.deltaX)>Math.abs(e.deltaY)){
            setTimeout(function(){ sync(main.scrollLeft,main); },0);
          }
        },{passive:true});
      }

      win.addEventListener('resize',function(){
        setTimeout(function(){
          v66SyncTableWidths();
          v67UpdateStickyOffsets();
          v66BindBottomScrollbar();
        },80);
      });
    }

    function v67UpdateStickyOffsets(){
      try{
        var saved=getColWidths ? getColWidths() : {};
        var avatarCol=COLUMNS.find(function(c){return c.key==='__avatar';});
        var avatarWidth=parseInt((saved&&saved.__avatar) || (avatarCol&&avatarCol.width) || 56,10) || 56;
        win.document.documentElement.style.setProperty('--v67-avatar-width', avatarWidth+'px');
        ['mainTable','mainGroupTable'].forEach(function(tid){
          var table=win.document.getElementById(tid); if(!table) return;
          var avs=table.querySelectorAll('.col-sticky-avatar'), nms=table.querySelectorAll('.col-sticky-name');
          avs.forEach(function(el){ el.style.left='0px'; });
          nms.forEach(function(el){ el.style.left=avatarWidth+'px'; });
        });
      }catch(e){}
    }

    function v66AfterRender(){ v66InitCfg(); v99InitRemoteColorSettings(); v99ApplyRemoteColors(); v66SyncTableWidths(); v67UpdateStickyOffsets(); setTimeout(function(){ v67UpdateStickyOffsets(); v66BindBottomScrollbar(); },50); }

    function ensureLocalSyncBarMount() {
      var doc = win.document;
      var wrap = doc.getElementById('wa-local-sync-bar-wrap');
      if (wrap) return wrap;
      wrap = doc.createElement('div');
      wrap.id = 'wa-local-sync-bar-wrap';
      var banner = doc.getElementById('banner');
      if (banner && banner.parentNode) banner.parentNode.insertBefore(wrap, banner.nextSibling);
      else if (doc.body) doc.body.insertBefore(wrap, doc.body.firstChild);
      return wrap;
    }

    // v100.4：管理面板明细编辑保护。
    // 后台自动接收、同步初始化、外部刷新或窗口缩放到达时，若用户正在编辑明细，
    // 只登记一次待刷新；失焦且不再处于中文输入法组合状态后再执行，避免重建 DOM 打断输入。
    var v1004PendingRender = false;
    var v1004FlushTimer = null;

    function v1004GetActiveDetailEditor() {
      try {
        var active = win.document.activeElement;
        if (!active || !active.matches) return null;
        if (!active.matches('#tableBody .cell-input:not([readonly]):not([disabled])')) return null;
        return active;
      } catch (e) { return null; }
    }

    function v1004IsDetailEditing() {
      var active = v1004GetActiveDetailEditor();
      return !!(active || (win.document && win.document.__v1004Composing));
    }

    function v1004QueueRender() {
      v1004PendingRender = true;
      return true;
    }

    function v1004FlushPendingRender() {
      clearTimeout(v1004FlushTimer);
      v1004FlushTimer = setTimeout(function () {
        if (!v1004PendingRender || v1004IsDetailEditing()) return;
        v1004PendingRender = false;
        renderAll(true);
      }, 30);
    }

    function v1004BindEditProtection() {
      var doc = win.document;
      if (!doc || doc.__v1004EditProtectionBound) return;
      doc.__v1004EditProtectionBound = true;

      doc.addEventListener('compositionstart', function (e) {
        if (e.target && e.target.matches && e.target.matches('#tableBody .cell-input:not([readonly]):not([disabled])')) {
          e.target.__v1004Composing = true;
          doc.__v1004Composing = true;
        }
      }, true);

      doc.addEventListener('compositionend', function (e) {
        if (e.target) e.target.__v1004Composing = false;
        doc.__v1004Composing = false;
        v1004FlushPendingRender();
      }, true);

      doc.addEventListener('focusout', function (e) {
        if (e.target && e.target.matches && e.target.matches('#tableBody .cell-input:not([readonly]):not([disabled])')) {
          v1004FlushPendingRender();
        }
      }, true);
    }

    function renderAll(v1004Force) {
      v1004BindEditProtection();
      if (!v1004Force && v1004IsDetailEditing()) {
        v1004QueueRender();
        try { v892RenderSyncLights(); } catch (e) {}
        return;
      }
      v1004PendingRender = false;
      var syncWrap = ensureLocalSyncBarMount();
      if (syncWrap) {
        if (!syncWrap.__v895SyncBarInited || !syncWrap.querySelector('#wa-local-sync-bar')) {
          syncWrap.innerHTML = buildLocalSyncBarHtml();
          syncWrap.__v895SyncBarInited = true;
          bindLocalSyncBarEvents(renderAll, win.document);
        } else {
          try {
            v894EnsureTitleSourceBox(win.document);
            v892RenderSyncLights();
          } catch(e) {}
        }
      }

      renderBanner();
      renderSourceFilter();
      renderPlatformBar();
      renderTagBar();
      renderStats();
      renderDashboard();
      renderTable();
      updateBatchBar();
      v66AfterRender();

      try { v892RenderSyncLights(); } catch(e) {}
    }

    win.__waRefresh = renderAll;
    win.__waIsDetailEditing = function(){ return v1004IsDetailEditing(); };
    if(!win.__v72ResizeBound){ win.__v72ResizeBound=true; var __v72rt=null; win.addEventListener('resize', function(){ clearTimeout(__v72rt); __v72rt=setTimeout(function(){ try{ renderAll(); v67UpdateStickyOffsets(); }catch(e){} },120); }); }

    win.document.getElementById('searchBox').addEventListener('input', function (e) {
      state.search = e.target.value;
      renderAll();
    });
    win.document.getElementById('sourceFilter').addEventListener('change', function (e) {
      state.sourceFilter = e.target.value;
      renderAll();
    });
    // v131：他源可编辑开关（默认开启）。改动写入服务端覆盖层；关闭后恢复他源只读。
    var remoteEditToggle = win.document.getElementById('remoteEditToggle');
    if (remoteEditToggle) {
      remoteEditToggle.checked = isRemoteEditableEnabled();
      remoteEditToggle.addEventListener('change', function () {
        setRemoteEditableEnabled(remoteEditToggle.checked);
        try {
          if (remoteEditToggle.checked) win.alert('已开启“他源可编辑”：他源行可编辑/删除，改动保存在服务端覆盖层，来源浏览器快照不会覆盖。');
          else win.alert('已关闭“他源可编辑”：他源行恢复只读。');
        } catch (e) {}
        renderAll();
      });
    }
    win.document.getElementById('clearFiltersBtn').addEventListener('click', function () {
      state.search = '';
      state.sourceFilter = '';
      state.platformFilter = '';
      state.tagFilter = '';
      state.selectedTags1 = [];
      state.selectedTags2 = [];
      var search = win.document.getElementById('searchBox');
      if (search) search.value = '';
      renderAll();
    });
    win.document.getElementById('sortSelect').addEventListener('change', function (e) {
      state.sort = e.target.value;
      renderTable();
    });
    win.document.getElementById('dashboardBtn').addEventListener('click', function () {
      state.dashboardOpen = !state.dashboardOpen;
      renderDashboard();
    });
    win.document.getElementById('wrapBtn').addEventListener('click', function () {
      state.wrapMode = !state.wrapMode;
      setSettings({ wrapMode: state.wrapMode });
      renderTable();
    });
    win.document.getElementById('resetWidthBtn').addEventListener('click', function () {
      if (win.confirm('\u786e\u5b9a\u8981\u91cd\u7f6e\u6240\u6709\u5217\u5bbd\u4e3a\u9ed8\u8ba4\u503c\u5417\uff1f')) {
        resetColWidths();
        renderTable();
      }
    });
    win.document.getElementById('darkBtn').addEventListener('click', function () {
      state.dark = !state.dark;
      setSettings({ darkMode: state.dark });
      applyDarkMode();
    });
    win.document.getElementById('exportBtn').addEventListener('click', doExport);
    win.document.getElementById('excelExportBtn').addEventListener('click', doExportExcel);
    win.document.getElementById('importBtn').addEventListener('click', function () {
      win.document.getElementById('importFile').click();
    });
    win.document.getElementById('importFile').addEventListener('change', function (e) {
      var file = e.target.files[0];
      if (!file) return;
      var reader = new win.FileReader();
      reader.onload = function () { doImport(reader.result); e.target.value = ''; };
      reader.readAsText(file, 'UTF-8');
    });
        win.document.getElementById('tagMgrBtn').addEventListener('click', function () {
      showTagManagerModal(win);
    });
    win.document.getElementById('fieldNameBtn').addEventListener('click', function () {
      openFieldNameEditor(win);
    });
    win.document.getElementById('mainGroupToggleBar').addEventListener('click', function () {
      state.mainGroupCollapsed = !state.mainGroupCollapsed;
      renderMainGroupTable();
    });

    win.document.getElementById('rescanBtn').addEventListener('click', function () {
      var r = runLinkScan({ force: true });
      renderAll();
      win.alert('\u91cd\u626b\u5b8c\u6210\uff0c\u5f53\u524d\u5171 ' + r.groupCount + ' \u4e2a\u5173\u8054\u7ec4\u3002');
    });
    win.document.getElementById('batchApplyTagBtn').addEventListener('click', function () {
      var tagVal = win.document.getElementById('batchTagSelect').value;
      Object.keys(state.selected).forEach(function (id) {
        if (state.selected[id]) upsertTagSmart(id, {}, tagVal);
      });
      renderAll();
    });
    var batchExportSelectedBtn = win.document.getElementById('batchExportSelectedBtn');
    if (batchExportSelectedBtn) batchExportSelectedBtn.addEventListener('click', doExportSelected);
    win.document.getElementById('batchDeleteBtn').addEventListener('click', function () {
      var ids=Object.keys(state.selected).filter(function(k){return state.selected[k]&&!v105IsLocalMainRecordId(k);});
      if(!ids.length)return;if(!win.confirm('确定删除选中的 '+ids.length+' 条联系人？删除后将进入回收站。'))return;
      v204UiWriteResult((async function(){
        var r=await localSyncBatchDelete(ids);if(!r.ok)return r;
        var data=loadData();ids.forEach(function(id){if(Object.prototype.hasOwnProperty.call(data,id))delete data[id];delete state.selected[id];});saveData(data);renderAll();return r;
      })(),'批量删除');
    });
    win.document.getElementById('batchClearBtn').addEventListener('click', function () {
      state.selected = {};
      renderAll();
    });

    var dropZone = win.document.getElementById('dropZone');
    win.document.body.addEventListener('dragover', function (e) { e.preventDefault(); dropZone.style.display = 'flex'; });
    win.document.body.addEventListener('dragleave', function () { dropZone.style.display = 'none'; });
    win.document.body.addEventListener('drop', function (e) {
      e.preventDefault();
      dropZone.style.display = 'none';
      var file = e.dataTransfer.files[0];
      if (!file) return;
      var reader = new win.FileReader();
      reader.onload = function () { doImport(reader.result); e.target.value = ''; };
      reader.readAsText(file, 'UTF-8');
    });

    applyDarkMode();
    renderAll();
    // v112：汇总轮询与心跳统一由 v892InitSyncStatus 启动，避免重复定时器。

    // v89.3：管理面板打开后自动检测连接、刷新统计，并在实时上传开启时补偿上传一次
    setTimeout(function(){
      v892InitSyncStatus(renderAll).catch(function(error){ v206ReportUiError('sync-status-init-call', error); });
    }, 300);
  }

  // ============ \u5173\u8054\u7ec4\u8be6\u60c5\u5f39\u7a97\uff08表格完整版：按渠道独立记录显示） ============
  function showLinkGroupPopup(hostWin, groupInfo, onChangeCallback) {
    var doc = hostWin.document;
    var old = doc.getElementById('__linkGroupPopupMask');
    if (old) old.remove();

    var mask = doc.createElement('div');
    mask.id = '__linkGroupPopupMask';
    mask.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:999999;display:flex;align-items:center;justify-content:center;padding:18px;';

    var box = doc.createElement('div');
    box.style.cssText = 'background:var(--bg,#fff);color:var(--text,#111b21);border-radius:10px;padding:16px 18px;width:calc(100vw - 24px);max-width:calc(100vw - 24px);max-height:88vh;overflow:hidden;box-shadow:0 8px 30px rgba(0,0,0,.3);display:flex;flex-direction:column;';

    function esc(s) {
      s = String(s == null ? '' : s);
      return s.replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; });
    }
    function fmtTime(ts) {
      if (!ts) return '';
      var d = new Date(ts);
      var p2 = function (n) { return (n < 10 ? '0' : '') + n; };
      return (d.getMonth() + 1) + '/' + p2(d.getDate()) + ' ' + p2(d.getHours()) + ':' + p2(d.getMinutes());
    }
    function fieldText(rec, key) {
      var v = rec && rec[key];
      return v == null ? '' : String(v);
    }
    function stageText(rec) {
      var arr = Array.isArray(rec && rec.stages) ? rec.stages : [];
      if (!arr.length) return '';
      return arr.map(function (k) { return getStageLabel(k); }).join(' / ');
    }
    function tagText(rec) {
      var key = (rec && rec.tag) || '';
      for (var i = 0; i < TAGS.length; i++) if (TAGS[i].key === key) return TAGS[i].label;
      return key || '无标签';
    }

    function renderContent() {
      // v103：弹窗每次打开/刷新前先对账，只展示通过真实关联验证的成员。
      reconcileLinkStateV103();
      var data = loadData();
      var main = data[groupInfo.mainKey];
      if (!main || !main.isMainRecord) { closePopup(); return; }
      var memberIds = Array.isArray(main.memberIds) ? main.memberIds : [];
      var members = memberIds.map(function (id) {
        var e = data[id];
        var info103 = getValidStoredLinkInfo(id, data);
        if (!e || !info103 || info103.mainKey !== groupInfo.mainKey) return null;
        // 保留并显示各渠道自己的独立记录，不让 MAIN 聚合字段回流。
        return Object.assign({ __id: id, __platform: inferPlatform(e, id) }, e);
      }).filter(Boolean);
      if (members.length < 2) { closePopup(); return; }

      var cols = [
        { key: '__actions', label: '操作', width: 210 },
        { key: '__platform', label: '渠道', width: 72 },
        { key: '__link', label: '关联', width: 82 },
        { key: '__id', label: '识别码', width: 180 },
        { key: '__avatar', label: '头像', width: 56 },
        { key: 'name', label: '姓名', width: 150 },
        { key: 'manualPhone', label: '电话', width: 135 },
        { key: 'tag', label: '标签', width: 105 },
        { key: '__stages', label: '跟进阶段', width: 120 }
      ].concat(getAllFieldDefinitionsV126(false).map(function (f) {
        return { key: f.key, label: getFieldLabel(f.key), width: (f.key === 'remark' ? 220 : 150) };
      })).concat([
        { key: 'updatedAt', label: '更新时间', width: 105 },
      ]);

      var html = '';
      html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;gap:12px;flex:0 0 auto;">' +
        '<div><h3 style="margin:0;font-size:16px;">' + String.fromCodePoint(0x1F517) + ' 关联详情（手机号：' + esc(groupInfo.phone || '未识别') + '）</h3>' +
        '<div style="font-size:12px;color:var(--sub,#667781);margin-top:5px;">共 ' + members.length + ' 个渠道已关联；下方按管理面板表格形式显示；电话、1-7、闪光点、说明可直接编辑，并强制保存到对应渠道自己的独立记录。</div></div>' +
        '<button id="__lgClose" style="border:none;background:none;font-size:22px;cursor:pointer;color:inherit;line-height:1;">×</button></div>';

      html += '<div style="overflow:auto;border:1px solid var(--border,#d9dee3);border-radius:8px;background:var(--card,#fff);flex:1 1 auto;">';
      html += '<table style="border-collapse:separate;border-spacing:0;table-layout:auto;min-width:100%;width:max-content;">';
      html += '<colgroup>' + cols.map(function (c) { return '<col style="width:' + c.width + 'px;">'; }).join('') + '</colgroup>';
      html += '<thead><tr>' + cols.map(function (c) {
        return '<th style="position:sticky;top:0;z-index:2;background:var(--headbg,#eef1f4);font-size:12px;font-weight:700;text-align:left;padding:8px;border-bottom:2px solid var(--border,#d9dee3);border-right:1px solid var(--border,#d9dee3);white-space:nowrap;">' + esc(c.label) + '</th>';
      }).join('') + '</tr></thead><tbody>';

      members.forEach(function (m) {
        var pinfo = getPlatformInfo(m.__platform);
        var vm = m.viewMode || 'shared';
        html += '<tr>';
        cols.forEach(function (col) {
          var tdStyle = 'padding:6px 8px;border-bottom:1px solid var(--border,#d9dee3);border-right:1px solid var(--border,#d9dee3);font-size:12px;vertical-align:top;white-space:normal;word-break:break-word;line-height:1.45;';
          var cell = '';
          if (col.key === '__platform') {
            cell = '<span style="display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;color:#fff;font-weight:600;background:' + pinfo.color + ';">' + esc(pinfo.short) + '</span>';
              } else if (col.key === '__avatar') {
            var mAvSrc = m.avatarData || m.__avatarData || m.__avatar || m.avatar || '';
            if (mAvSrc) {
              cell = '<img src="' + esc(mAvSrc) + '" referrerpolicy="no-referrer" style="width:34px;height:34px;border-radius:50%;object-fit:cover;border:1.5px solid var(--border,#d1d7db);display:block;margin:0 auto;cursor:pointer;" title="点击查看原图" onclick="window.open(\'' + esc(mAvSrc) + '\',\'_blank\')" />';
            } else {
              cell = '<div style="width:34px;height:34px;border-radius:50%;background:var(--border,#e0e0e0);color:var(--sub,#888);display:flex;align-items:center;justify-content:center;font-size:14px;margin:0 auto;user-select:none;" title="暂无头像">👤</div>';
            }
          } else if (col.key === '__link') {
            cell = '<span style="display:inline-block;padding:2px 7px;border-radius:10px;font-size:11px;color:#fff;background:#00a884;">已关联</span><br><span style="font-size:11px;color:var(--sub,#667781);">' + (vm === 'shared' ? '共享视图' : '独立视图') + '</span>';
          } else if (col.key === '__id') {
            cell = '<span title="' + esc(m.__id) + '">' + esc(m.__id) + '</span>';
          } else if (col.key === 'tag') {
            cell = esc(tagText(m));
          } else if (col.key === '__stages') {
            cell = esc(stageText(m));
          } else if (col.key === 'updatedAt') {
            cell = esc(fmtTime(m.updatedAt));
          } else if (col.key === '__actions') {
            cell = '<button class="__lgToggleView btn" data-id="' + esc(m.__id) + '" style="font-size:11px;padding:4px 8px;margin:0 5px 5px 0;">' + String.fromCodePoint(0x1F500) + ' 切换为' + (vm === 'shared' ? '独立' : '共享') + '</button>' +
              '<button class="__lgUnlink btn" data-id="' + esc(m.__id) + '" style="font-size:11px;padding:4px 8px;margin:0 0 5px 0;background:#e53935;color:#fff;">' + String.fromCodePoint(0x274C) + ' 解除关联</button>';
          } else {
            cell = esc(fieldText(m, col.key));
          }
          html += '<td style="' + tdStyle + '">' + cell + '</td>';
        });
        html += '</tr>';
      });

      html += '</tbody></table></div>';
      box.innerHTML = html;

      doc.getElementById('__lgClose').addEventListener('click', closePopup);
      box.querySelectorAll('.__lgToggleView').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var id = btn.getAttribute('data-id');
          var d = loadData();
          var cur = (d[id] && d[id].viewMode) || 'shared';
          setChannelViewMode(id, cur === 'shared' ? 'independent' : 'shared');
          renderContent();
          refreshPanelIfOpen();
        });
      });
      box.querySelectorAll('.__lgUnlink').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var id = btn.getAttribute('data-id');
          if (!hostWin.confirm('确定解除该渠道与当前分组的关联吗？解除后该渠道将使用自己的独立记录，且不会被自动重新关联。')) return;
          var ok103 = unlinkChannel(id);
          if (!ok103) hostWin.alert('该联系人当前没有有效关联，残留状态已清理。');
          if (onChangeCallback) onChangeCallback();
          var d2 = loadData();
          if (!d2[groupInfo.mainKey]) { closePopup(); return; }
          renderContent();
        });
      });
    }

    function closePopup() { mask.remove(); }
    mask.addEventListener('click', function (e) { if (e.target === mask) closePopup(); });
    mask.appendChild(box);
    doc.body.appendChild(mask);
    renderContent();
  }


  // ============ v54 方案B：轻量弹层多选画像选择器 ============
  function showTag2SelectDropdown(hostWin, ev, recordId, currentSelected, onSave) {
    var doc = hostWin.document;
    var old = doc.getElementById('__tag2Popover');
    if (old) old.remove();

    var t2List = getTags2();
    var pop = doc.createElement('div');
    pop.id = '__tag2Popover';
    pop.style.cssText = 'position:fixed;z-index:999999;background:var(--card,#fff);border:1px solid var(--border,#d9dee3);border-radius:8px;padding:10px 12px;box-shadow:0 6px 20px rgba(0,0,0,0.18);display:flex;flex-direction:column;gap:8px;min-width:180px;max-width:240px;';

    var r = ev.target.getBoundingClientRect();
    var left = Math.min(r.left, hostWin.innerWidth - 250);
    var top = Math.min(r.bottom + 4, hostWin.innerHeight - 260);
    pop.style.left = Math.max(10, left) + 'px';
    pop.style.top = Math.max(10, top) + 'px';

    var head = doc.createElement('div');
    head.style.cssText = 'display:flex;justify-content:space-between;align-items:center;font-size:12px;font-weight:700;color:var(--text);border-bottom:1px solid var(--border);padding-bottom:5px;';
    head.innerHTML = '<span>选择画像 (多选)</span><span id="__popClose" style="cursor:pointer;font-size:14px;color:var(--sub);">&times;</span>';
    pop.appendChild(head);

    var listWrap = doc.createElement('div');
    listWrap.style.cssText = 'display:flex;flex-direction:column;gap:5px;max-height:180px;overflow-y:auto;';

    var localSel = (currentSelected || []).slice();
    t2List.forEach(function (t) {
      var item = doc.createElement('label');
      item.style.cssText = 'display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;padding:2px 4px;border-radius:4px;';
      item.addEventListener('mouseenter', function(){ item.style.background = 'var(--fieldbg,#f0f2f5)'; });
      item.addEventListener('mouseleave', function(){ item.style.background = 'transparent'; });

      var cb = createCustomCheckboxDoc(doc, localSel.indexOf(t.key) >= 0, function (chk) {
        var idx = localSel.indexOf(t.key);
        if (chk) { if (idx < 0) localSel.push(t.key); }
        else { if (idx >= 0) localSel.splice(idx, 1); }
        // v76：画像多选改为勾选即保存，避免忘记点击“确定”
        if (onSave) onSave(localSel.slice());
      }, 13);

      var badge = doc.createElement('span');
      badge.style.cssText = 'padding:1px 6px;border-radius:8px;font-size:11px;color:#fff;background:' + t.color + ';';
      badge.textContent = t.label;

      item.appendChild(cb);
      item.appendChild(badge);
      listWrap.appendChild(item);
    });
    pop.appendChild(listWrap);

    // v76：取消底部“确定”按钮；画像勾选/取消勾选时已即时保存。

    doc.body.appendChild(pop);
    doc.getElementById('__popClose').addEventListener('click', function(){ pop.remove(); });

    var onDocClick = function (e) {
      if (!pop.contains(e.target)) {
        pop.remove();
        doc.removeEventListener('click', onDocClick, true);
      }
    };
    setTimeout(function(){ doc.addEventListener('click', onDocClick, true); }, 10);
  }

  // ============ v54 可视化标签管理弹窗 (标签 / 画像 增删改查及调色) ============
  function showTagManagerModal(hostWin) {
    var doc=hostWin.document,old=doc.getElementById('__tagMgrMask'); if(old)old.remove();
    var mask=doc.createElement('div'); mask.id='__tagMgrMask'; mask.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:999999;display:flex;align-items:center;justify-content:center;';
    var box=doc.createElement('div'); box.style.cssText='background:var(--bg,#fff);color:var(--text,#111b21);border-radius:12px;padding:22px;width:620px;max-width:94vw;max-height:88vh;overflow:auto;box-shadow:0 12px 36px rgba(0,0,0,.35);'; mask.appendChild(box);doc.body.appendChild(mask);
    var active='t1',t1=JSON.parse(JSON.stringify(getTags1())),t2=JSON.parse(JSON.stringify(getTags2())),drag=-1;
    function close(){mask.remove();}
    function uniqueName(list,base){var used={};list.forEach(function(x){used[normalizeBusinessLabelV126(x.label)]=1;});if(!used[normalizeBusinessLabelV126(base)])return base;var n=2;while(used[normalizeBusinessLabelV126(base+n)])n++;return base+n;}
    function validate(list,title){var seen={};for(var i=0;i<list.length;i++){var n=String(list[i].label||'').trim(),k=normalizeBusinessLabelV126(n);if(!n)return title+'名称不能为空。';if(seen[k])return title+'名称“'+n+'”重复，请修改后保存。';seen[k]=1;list[i].label=n;}return '';}
    function move(list,from,to){if(from<0||to<0||from>=list.length||to>=list.length||from===to)return;var x=list.splice(from,1)[0];list.splice(to,0,x);}
    function render(){
      box.innerHTML='';var head=doc.createElement('div');head.style.cssText='display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;';head.innerHTML='<h3 style="margin:0;font-size:16px;">🏷️ 标签与画像管理（拖动排序）</h3>';var x=doc.createElement('button');x.textContent='×';x.style.cssText='border:0;background:none;font-size:24px;cursor:pointer;color:inherit';x.onclick=close;head.appendChild(x);box.appendChild(head);
      var tabs=doc.createElement('div');tabs.style.cssText='display:flex;gap:8px;border-bottom:1px solid var(--border,#ddd);padding-bottom:10px;margin-bottom:10px;';[['t1','标签'],['t2','画像']].forEach(function(a){var b=doc.createElement('button');b.className='btn '+(active===a[0]?'':'ghost');b.textContent=a[1];b.onclick=function(){active=a[0];render();};tabs.appendChild(b);});box.appendChild(tabs);
      var list=active==='t1'?t1:t2,wrap=doc.createElement('div');wrap.style.cssText='display:flex;flex-direction:column;gap:8px;max-height:430px;overflow:auto;';
      list.forEach(function(item,idx){var row=doc.createElement('div');row.draggable=true;row.style.cssText='display:flex;align-items:center;gap:8px;background:var(--card,#f8fafc);border:1px solid var(--border,#ddd);padding:7px 9px;border-radius:7px;';
        var h=doc.createElement('span');h.textContent='☰';h.title='按住拖动排序';h.style.cssText='cursor:grab;font-size:18px;color:#8696a0;user-select:none';row.appendChild(h);
        var c=doc.createElement('input');c.type='color';c.value=item.color||'#00a884';c.oninput=function(){item.color=c.value;};c.style.cssText='width:34px;height:28px;border:0;padding:0';row.appendChild(c);
        var n=doc.createElement('input');n.type='text';n.value=item.label||'';n.oninput=function(){item.label=n.value;};n.style.cssText='flex:1;padding:6px;border:1px solid #ccd3d8;border-radius:5px';row.appendChild(n);
        function small(txt,title,fn,disabled){var b=doc.createElement('button');b.textContent=txt;b.title=title;b.disabled=!!disabled;b.onclick=fn;b.style.cssText='border:1px solid #ccd3d8;background:#fff;border-radius:4px;cursor:pointer;padding:3px 7px';return b;}
        row.appendChild(small('↑','上移',function(){move(list,idx,idx-1);render();},idx===0));row.appendChild(small('↓','下移',function(){move(list,idx,idx+1);render();},idx===list.length-1));row.appendChild(small('🗑️','删除',function(){list.splice(idx,1);render();},false));
        row.ondragstart=function(e){drag=idx;row.style.opacity='.45';if(e.dataTransfer)e.dataTransfer.effectAllowed='move';};row.ondragover=function(e){e.preventDefault();row.style.borderColor='#00a884';};row.ondragleave=function(){row.style.borderColor='var(--border,#ddd)';};row.ondrop=function(e){e.preventDefault();move(list,drag,idx);drag=-1;render();};row.ondragend=function(){drag=-1;row.style.opacity='1';};wrap.appendChild(row);
      });box.appendChild(wrap);
      var add=doc.createElement('button');add.className='btn ghost';add.style.cssText='width:100%;margin-top:10px;padding:8px;border-style:dashed';add.textContent='+ 新增'+(active==='t1'?'标签':'画像');add.onclick=function(){var persona=active==='t2',base=persona?'新画像':'新标签';list.push({key:(persona?'persona_':'tag_')+Date.now().toString(36)+'_'+Math.random().toString(36).slice(2,8),label:uniqueName(list,base),color:'#00a884'});render();};box.appendChild(add);
      var foot=doc.createElement('div');foot.style.cssText='display:flex;justify-content:flex-end;gap:10px;margin-top:16px;';var cancel=doc.createElement('button');cancel.className='btn ghost';cancel.textContent='取消';cancel.onclick=close;var save=doc.createElement('button');save.className='btn';save.textContent='保存配置';save.onclick=function(){var err=validate(t1,'标签')||validate(t2,'画像');if(err){hostWin.alert(err);return;}setTags1(t1);setTags2(t2);TAGS=getTags1();close();try{if(hostWin.__waRefresh)hostWin.__waRefresh();else refreshPanelIfOpen();}catch(e){}try{currentChatId=null;renderNoteBar();}catch(e){}};foot.appendChild(cancel);foot.appendChild(save);box.appendChild(foot);
    }
    mask.onclick=function(e){if(e.target===mask)close();};render();
  }

  // ============ 字段与阶段名称编辑弹窗 ============
  function openFieldNameEditor(hostWin) {
    var doc=hostWin.document,old=doc.getElementById('__fieldNameEditorMask');if(old)old.remove();
    var mask=doc.createElement('div');mask.id='__fieldNameEditorMask';mask.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:999999;display:flex;align-items:center;justify-content:center;';
    var box=doc.createElement('div');box.style.cssText='background:var(--bg,#fff);color:var(--text,#111b21);border-radius:10px;padding:18px 20px;width:680px;max-width:94vw;max-height:90vh;overflow:auto;box-shadow:0 8px 30px rgba(0,0,0,.3);';mask.appendChild(box);doc.body.appendChild(mask);
    var custom=JSON.parse(JSON.stringify(getCustomFieldDefinitionsV126(true)));
    function close(){mask.remove();}
    function countUse(key){var d=loadData(),n=0;Object.keys(d||{}).forEach(function(id){if(isMainKey(id))return;var v=d[id]&&d[id][key];if(v!=null&&String(v).trim())n++;});return n;}
    function move(from,to){if(from<0||to<0||from>=custom.length||to>=custom.length)return;var x=custom.splice(from,1)[0];custom.splice(to,0,x);render();}
    function render(){box.innerHTML='';var h=doc.createElement('div');h.style.cssText='display:flex;justify-content:space-between;align-items:center;margin-bottom:12px';h.innerHTML='<div><h3 style="margin:0">字段与阶段管理</h3><div style="font-size:12px;color:#667781;margin-top:4px">固定字段可重命名；自定义字段可新增、排序、归档和恢复。稳定键不会改变。</div></div>';var xb=doc.createElement('button');xb.textContent='×';xb.style.cssText='border:0;background:none;font-size:24px;cursor:pointer;color:inherit';xb.onclick=close;h.appendChild(xb);box.appendChild(h);
      var fixed=doc.createElement('div');fixed.innerHTML='<b>固定字段名称</b>';FIELDS.forEach(function(f){var r=doc.createElement('div');r.style.cssText='display:flex;gap:8px;align-items:center;margin-top:7px';r.innerHTML='<span style="width:55px;color:#667781;font-size:12px">'+f.key+'</span>';var i=doc.createElement('input');i.className='__fneInput';i.setAttribute('data-key',f.key);i.value=getFieldLabel(f.key);i.style.cssText='flex:1;padding:6px;border:1px solid #ccd3d8;border-radius:5px';r.appendChild(i);fixed.appendChild(r);});box.appendChild(fixed);
      var ch=doc.createElement('div');ch.style.cssText='display:flex;justify-content:space-between;align-items:center;margin-top:16px';ch.innerHTML='<b>自定义字段</b>';var add=doc.createElement('button');add.className='btn ghost';add.textContent='+ 新增字段';add.onclick=function(){custom.push({key:createCustomFieldKeyV126(),label:'新字段'+(custom.length+1),type:'text',sortOrder:custom.length,enabled:true,archivedAt:null});render();};ch.appendChild(add);box.appendChild(ch);
      var active=custom.filter(function(f){return f.enabled!==false&&!f.archivedAt;});active.forEach(function(f,ai){var idx=custom.indexOf(f),r=doc.createElement('div');r.style.cssText='display:flex;gap:7px;align-items:center;margin-top:7px;padding:7px;background:#f7f9fa;border-radius:6px';var key=doc.createElement('span');key.textContent=f.key;key.title=f.key;key.style.cssText='width:105px;overflow:hidden;text-overflow:ellipsis;font-size:11px;color:#667781';r.appendChild(key);var i=doc.createElement('input');i.value=f.label||'';i.oninput=function(){f.label=i.value};i.style.cssText='flex:1;padding:6px;border:1px solid #ccd3d8;border-radius:5px';r.appendChild(i);var sel=doc.createElement('select');[['text','单行文本'],['textarea','多行文本'],['number','数字'],['date','日期']].forEach(function(a){var o=doc.createElement('option');o.value=a[0];o.textContent=a[1];if((f.type||'text')===a[0])o.selected=true;sel.appendChild(o);});sel.onchange=function(){f.type=sel.value};r.appendChild(sel);function b(t,fn,dis){var x=doc.createElement('button');x.textContent=t;x.disabled=!!dis;x.onclick=fn;return x;}r.appendChild(b('↑',function(){var prev=custom.indexOf(active[ai-1]);move(idx,prev)},ai===0));r.appendChild(b('↓',function(){var next=custom.indexOf(active[ai+1]);move(idx,next)},ai===active.length-1));r.appendChild(b('归档',function(){var n=countUse(f.key);if(hostWin.confirm('字段“'+(f.label||f.key)+'”已被 '+n+' 位联系人使用。归档后隐藏但历史值保留，确定继续？')){f.enabled=false;f.archivedAt=Date.now();render();}},false));box.appendChild(r);});
      var archived=custom.filter(function(f){return f.enabled===false||f.archivedAt;});if(archived.length){var ah=doc.createElement('div');ah.innerHTML='<b>已归档字段</b>';ah.style.marginTop='16px';box.appendChild(ah);archived.forEach(function(f){var r=doc.createElement('div');r.style.cssText='display:flex;gap:8px;align-items:center;margin-top:6px;color:#667781';var s=doc.createElement('span');s.textContent=(f.label||f.key)+'（'+f.key+'）';s.style.flex='1';var b=doc.createElement('button');b.textContent='恢复';b.onclick=function(){f.enabled=true;f.archivedAt=null;render();};r.appendChild(s);r.appendChild(b);box.appendChild(r);});}
      var sh=doc.createElement('div');sh.innerHTML='<b>阶段名称</b>';sh.style.marginTop='16px';box.appendChild(sh);STAGES.forEach(function(st){var r=doc.createElement('div');r.style.cssText='display:flex;gap:8px;align-items:center;margin-top:7px';r.innerHTML='<span style="width:55px;color:#667781;font-size:12px">'+st.key+'</span>';var i=doc.createElement('input');i.className='__sneInput';i.setAttribute('data-key',st.key);i.value=getStageLabel(st.key);i.style.cssText='flex:1;padding:6px;border:1px solid #ccd3d8;border-radius:5px';r.appendChild(i);box.appendChild(r);});
      var foot=doc.createElement('div');foot.style.cssText='display:flex;justify-content:flex-end;gap:10px;margin-top:16px';var cancel=doc.createElement('button');cancel.textContent='取消';cancel.onclick=close;var save=doc.createElement('button');save.textContent='保存';save.className='btn';save.onclick=function(){var map={},names={},bad='';box.querySelectorAll('.__fneInput').forEach(function(i){var v=i.value.trim();map[i.getAttribute('data-key')]=v;if(!v)bad='固定字段名称不能为空。';});var sm={},sn={};box.querySelectorAll('.__sneInput').forEach(function(i){var v=i.value.trim(),k=normalizeBusinessLabelV126(v);sm[i.getAttribute('data-key')]=v;if(!v)bad='阶段名称不能为空。';else if(sn[k])bad='阶段名称不能重复。';sn[k]=1;});custom.forEach(function(f,i){f.label=String(f.label||'').trim();f.sortOrder=i;var k=normalizeBusinessLabelV126(f.label);if(!f.label)bad='自定义字段名称不能为空。';if(f.enabled!==false&&!f.archivedAt){if(names[k])bad='活动的自定义字段名称不能重复。';names[k]=1;}});if(bad){hostWin.alert(bad);return;}setFieldLabels(map);setStageLabels(sm);setCustomFieldDefinitionsV126(custom);close();};foot.appendChild(cancel);foot.appendChild(save);box.appendChild(foot);
    }mask.onclick=function(e){if(e.target===mask)close();};render();
  }

  // ========================================================
  // \u542f\u52a8\u903b\u8f91\uff1a\u8def\u7531\u76d1\u542c + \u60ac\u6d6e\u6761\u6302\u8f7d + \u83dc\u5355\u6ce8\u518c
  // ========================================================

  var __lastUrl = location.href;
  var __lastChatSignature = null;
  var __pollTimer = null;
  var __v206DomObserver = null;
  var __v206DomTimer = null;
  var __v206Ensuring = false;

  // \u4fee\u590d\uff1a\u76f4\u63a5\u57fa\u4e8e getContactInfoUnified() \u8bc6\u522b\u5230\u7684\u771f\u5b9e\u8054\u7cfb\u4ebaID\u4f5c\u4e3a\u7b7e\u540d
  // \u800c\u4e0d\u662f\u4f9d\u8d56\u4e0d\u53ef\u9760\u7684\u9875\u9762header\u6587\u672c\uff08\u65e7\u7248WA\u7b7e\u540d\u6c38\u8fdc\u4e0d\u53d8\u7684bug\u6839\u6e90\uff09
  function getChatSignature() {
    try {
      var info = getContactInfoUnified();
      if (info && info.id) {
        // v43：签名加入 name，使同一聊天内联系人名称变化时也能触发 renderNoteBar()
        return location.hostname + '::' + info.id + '::' + (info.name || '');
      }
      return location.hostname + '::' + location.href;
    } catch (e) {
      return location.href;
    }
  }

  function v206RunMountPreflight() {
    var errors = [];

    if (
      typeof NOTE_BAR_ID !== 'string' ||
      !NOTE_BAR_ID.trim()
    ) {
      errors.push('NOTE_BAR_ID 未定义或为空');
    }

    if (typeof renderNoteBar !== 'function') {
      errors.push('renderNoteBar 不可用');
    }

    if (typeof ensureNoteBarMounted !== 'function') {
      errors.push('ensureNoteBarMounted 不可用');
    }

    if (typeof setupBarPhysicalIsolation !== 'function') {
      errors.push('setupBarPhysicalIsolation 不可用');
    }

    __v206UiDiagnostics.preflight = {
      ok: errors.length === 0,
      errors: errors,
      checkedAt: Date.now()
    };

    if (errors.length) {
      throw new Error(
        '聊天备注栏启动自检失败：' + errors.join('；')
      );
    }

    return true;
  }

  function tick() {
    try {
      var sig = getChatSignature();
      var urlChanged = (location.href !== __lastUrl);
      if (urlChanged || sig !== __lastChatSignature) {
        __lastUrl = location.href;
        __lastChatSignature = sig;
        renderNoteBar();
      } else {
        ensureNoteBarMounted();
      }
    } catch (error) { v206ReportUiError('tick', error); }
  }

  function ensureNoteBarMounted() {
    try {
      if (location.hostname.indexOf('instagram.com') >= 0 && location.pathname.indexOf('/direct/') !== 0) {
        var oldBar = document.getElementById(NOTE_BAR_ID);
        if (oldBar) oldBar.remove();
        currentChatId = null;
        currentChatName = null;
        currentChatPlatform = null;
        return;
      }

      // v43：即使悬浮条已经存在，也定期同步当前聊天最新姓名
      var info = getContactInfoUnified();
      if (info && info.id && info.name) {
        syncCurrentContactName(info);
      }

      var bar = document.getElementById(NOTE_BAR_ID);
      if (bar && bar.getAttribute('data-identity-readonly') === '1' && info && info.writable === true) {
        renderNoteBar();
        return;
      }
      if (!bar || !bar.isConnected) {
        renderNoteBar();
      } else if (info && info.headerEl) {
        setupBarPhysicalIsolation(bar, info.headerEl);
      }
    } catch (error) { v206ReportUiError('ensure-mounted', error); }
  }

  function startPolling() {
    if (__pollTimer) return;
    __pollTimer = setInterval(tick, 900);
  }

  function stopPolling() {
    if (__pollTimer) {
      clearInterval(__pollTimer);
      __pollTimer = null;
    }
  }

  function installHistoryHooks() {
    if (history.pushState.__juboV206Wrapped) return;
    var origPush = history.pushState;
    var origReplace = history.replaceState;
    function notifyRouteChange() { setTimeout(tick, 50); }
    function wrappedPushState() {
      var ret = origPush.apply(this, arguments); notifyRouteChange(); return ret;
    }
    function wrappedReplaceState() {
      var ret = origReplace.apply(this, arguments); notifyRouteChange(); return ret;
    }
    wrappedPushState.__juboV206Wrapped = true;
    wrappedReplaceState.__juboV206Wrapped = true;
    history.pushState = wrappedPushState;
    history.replaceState = wrappedReplaceState;
    window.addEventListener('popstate', notifyRouteChange);
  }

  function installDomObserver() {
    try {
      if (__v206DomObserver || !document.body) return;
      __v206DomObserver = new MutationObserver(function (mutations) {
        var onlyOwnBar = mutations.length > 0 && mutations.every(function (mutation) {
          var target = mutation.target;
          return target && target.nodeType === 1 &&
            (target.id === NOTE_BAR_ID || (target.closest && target.closest('#' + NOTE_BAR_ID)));
        });
        if (onlyOwnBar) return;
        clearTimeout(__v206DomTimer);
        __v206DomTimer = setTimeout(function () {
          if (__v206Ensuring) return;
          __v206Ensuring = true;
          try { ensureNoteBarMounted(); }
          catch (error) { v206ReportUiError('dom-observer', error); }
          finally { __v206Ensuring = false; }
        }, 120);
      });
      __v206DomObserver.observe(document.body, { childList: true, subtree: true });
    } catch (error) { v206ReportUiError('install-dom-observer', error); }
  }

  async function v204ConfigureIdentityMenu(preferredChannel) {
    var id=v204Identity();
    var server=prompt('V205 服务地址',getLocalSyncServerUrl()); if(server===null)return {ok:false,cancelled:true}; setLocalSyncServerUrl(server);
    var token=prompt('访问 Token（可留空）',String(GM_getValue('jubo_v207_access_token','')||''));if(token===null)return {ok:false,cancelled:true};GM_setValue('jubo_v207_access_token',String(token||'').trim());
    var workspace=prompt('工作区 ID',String(GM_getValue('jubo_v205_workspace_id','default')||'default'));if(workspace===null)return {ok:false,cancelled:true};GM_setValue('jubo_v205_workspace_id',String(workspace||'default').trim()||'default');
    var deviceName=prompt('设备名称（每个浏览器 Profile 一台设备）',String(GM_getValue('jubo_v205_device_name','采集端-'+id.deviceId.slice(-6))||''));if(deviceName===null)return {ok:false,cancelled:true};GM_setValue('jubo_v205_device_name',String(deviceName||'').trim());
    var computerName=prompt('电脑名称（例如 DESKTOP-ABCD）',String(GM_getValue('jubo_v205_computer_name',navigator.platform||'')||''));if(computerName===null)return {ok:false,cancelled:true};GM_setValue('jubo_v205_computer_name',String(computerName||'').trim());
    var detectedChannel=String(preferredChannel||v204Channel({platform:location.hostname})).toLowerCase().trim();var channel=prompt('渠道：whatsapp / instagram / facebook / messenger / telegram / other',detectedChannel);if(channel===null)return {ok:false,cancelled:true};channel=String(channel||'').toLowerCase().trim();
    if(['whatsapp','instagram','facebook','messenger','telegram','other'].indexOf(channel)<0){alert('渠道无效');return {ok:false,error:'INVALID_CHANNEL'};}
    var profiles=v204Profiles(),active=v204ActiveAccounts(),known=Object.keys(profiles[channel]||{}),suggested=String(active[channel]||known[0]||'');
    var account=prompt('稳定账号身份（同渠道可配置多个；已有：'+(known.join(', ')||'无')+'）',suggested);if(account===null||!String(account).trim())return {ok:false,cancelled:true};account=String(account).trim();
    var old=(profiles[channel]&&profiles[channel][account])||{},sourceName=prompt('来源显示名称',String(old.sourceName||account));if(sourceName===null)return {ok:false,cancelled:true};
    var pendingProfile={accountIdentity:account,sourceName:String(sourceName||account).trim(),confirmedAt:Date.now()};
    var health=await localSyncHealthCheck({silent:true});if(!health.ok){alert('连接或版本检查失败：'+(health.error||health.status||'未知错误'));return health;}
    var dev=await v204RegisterDevice();if(!dev.ok){alert('设备注册失败：'+(dev.error||(dev.data&&dev.data.message)||dev.status));return dev;}
    var src=await v204RegisterSource(channel,account,pendingProfile);if(!src.ok){alert('来源注册失败：'+(src.error||(src.data&&src.data.message)||src.status));return src;}
    // 远端来源注册成功后，才原子式提交 Profile 与当前激活账号，杜绝失败后的半配置状态。
    if(!profiles[channel])profiles[channel]={};profiles[channel][account]=pendingProfile;active[channel]=account;v204Save(V204_ACCOUNT_PROFILES_KEY,profiles);v204Save(V204_ACTIVE_ACCOUNTS_KEY,active);
    var source=src.data.source||{};alert('V205 身份配置完成\n工作区：'+v204Identity().workspaceId+'\n渠道：'+channel+'\n账号：'+account+'\n来源：'+(source.source_name||sourceName)+'\n设备：'+GM_getValue('jubo_v205_device_name','')+'\n电脑：'+GM_getValue('jubo_v205_computer_name',''));return {ok:true,channel:channel,account:account,source:source};
  }
  function v204ShowIdentityMenu(){var id=v204Identity(),profiles=v204Stored(V204_ACCOUNT_PROFILES_KEY,{})||{};alert('V205 当前身份\ninstallation_id：'+id.installationId+'\ndevice_id：'+id.deviceId+'\nworkspace_id：'+id.workspaceId+'\n设备：'+String(GM_getValue('jubo_v205_device_name','')||'未配置')+'\n电脑：'+String(GM_getValue('jubo_v205_computer_name','')||'未配置')+'\n账号绑定：\n'+JSON.stringify(profiles,null,2));}
  function v204ResetChannelBinding(){var ch=prompt('输入渠道','whatsapp');if(ch===null)return;ch=String(ch).toLowerCase().trim();var p=v204Profiles(),a=v204ActiveAccounts(),known=Object.keys(p[ch]||{}),account=prompt('输入要移除的账号身份；留空仅取消当前激活账号。已有：'+known.join(', '),'');if(account===null)return;account=String(account).trim();if(account&&p[ch])delete p[ch][account];delete a[ch];v204Save(V204_ACCOUNT_PROFILES_KEY,p);v204Save(V204_ACTIVE_ACCOUNTS_KEY,a);alert(account?'已移除该账号绑定。':'已取消该渠道当前激活账号。');}

  function registerMenuCommands() {
    try {
      if (typeof GM_registerMenuCommand === 'function') {
        GM_registerMenuCommand('配置 V205 身份（设备/账号/来源）', function(){v204ConfigureIdentityMenu().catch(function(e){alert('配置失败：'+String(e&&e.message||e));});});
        GM_registerMenuCommand('查看 V205 当前身份', v204ShowIdentityMenu);
        GM_registerMenuCommand('重新绑定 V205 渠道账号', v204ResetChannelBinding);
        GM_registerMenuCommand('清空 V205 联系人缓存并重新拉取', v204ClearContactCache);
        GM_registerMenuCommand('查看 V205 事件队列', v204ShowQueue);
        GM_registerMenuCommand('恢复 V205 回收站联系人', function(){var cid=prompt('输入 contact_id');if(!cid)return;var ver=prompt('输入当前回收站版本号');if(ver===null||!/^\d+$/.test(String(ver))){alert('版本号无效');return;}v205RestoreContact(cid,Number(ver)).then(function(r){alert(r.ok?'恢复成功':'恢复失败：'+(r.error||(r.data&&r.data.message)||r.status));});});
        GM_registerMenuCommand('立即重试 V205 失败事件', function(){v204FlushEventQueue().then(function(r){alert('重试完成，剩余 '+r.remaining+' 条');});});
        GM_registerMenuCommand('v121.7 IG身份诊断', function() {
          var tid=igThreadIdV1212(), link=findIgUsernameLink(), user=link ? (link.getAttribute('href')||'').replace(/\//g,'') : '';
          var item=__igThreadIdentityCacheV1213[igIdentityCacheKeyV1213(tid,user)] || null, d=__igPassiveDiagV1216;
          alert('Thread ID: '+(tid||'(无)')+'\nHeader username: '+(user||'(无)')+'\n安装尝试: '+(d.attempted?'是':'否')+'\n页面握手: '+(d.handshake?'成功':'未成功')+'\n监听状态: '+(d.installed?'真实运行':'未运行')+'\n安装方式: '+(d.installMethod||'(无)')+'\n原生响应数: '+d.nativeResponses+'\n已解析 JSON: '+d.jsonPayloads+'\n解析失败数: '+d.parseFailures+'\n候选命中批次: '+d.candidateBatches+'\n数据来源: '+(item && item.source || 'passive_page_response')+'\n解析状态: '+(item ? item.status : 'observing')+'\n数字用户 ID: '+(item && item.id || '(未取得)')+'\n最近响应: '+(d.lastUrl||'(无)')+'\n错误: '+(item && item.error || d.lastError || '(无)'));
        });
      }
      if (typeof GM_registerMenuCommand === 'function') {
        GM_registerMenuCommand('打开聚宝盆客户信息管理系统', function () {
          openManagePanel();
        });
        GM_registerMenuCommand('\u624b\u52a8\u91cd\u626b\u540c\u4eba\u5173\u8054', function () {
          var r = runLinkScan({ force: true });
          alert('\u91cd\u626b\u5b8c\u6210\uff0c\u5f53\u524d\u5171 ' + r.groupCount + ' \u4e2a\u5173\u8054\u7ec4\u3002');
          refreshPanelIfOpen();
        });
        GM_registerMenuCommand('清理 IG 头像缓存并重新抓取', function () {
          try {
            var data = loadData();
            var count = 0;
            Object.keys(data).forEach(function (id) {
              if (id.indexOf('ig:') === 0 && data[id]) {
                delete data[id].avatar;
                delete data[id].avatarData;
                count++;
              }
            });
            saveData(data);
            refreshPanelIfOpen();
            alert('已清理 ' + count + ' 条 IG 头像缓存。请回到 Instagram 私信，逐个打开联系人聊天，让脚本重新抓取正确头像。');
          } catch (e) {
            alert('清理失败：' + e.message);
          }
        });
        // 旧命令协议：多机共用——同步服务地址 / 访问令牌 / 下行指令开关
        GM_registerMenuCommand('设置同步服务地址（多机共用）', function () {
          var cur = '';
          try { cur = getLocalSyncServerUrl(); } catch (e) {}
          var v = prompt('输入中心服务端地址，例如 http://192.168.1.10:8765\n（留空恢复默认 http://127.0.0.1:8765）', cur);
          if (v === null) return;
          try { setLocalSyncServerUrl(v); } catch (e) {}
          alert('已设置同步服务地址：' + getLocalSyncServerUrl() + '\n若服务端设置了令牌，请再用“设置访问令牌”菜单配置。');
        });
        GM_registerMenuCommand('设置访问令牌（可选）', function () {
          var cur = '';
          try { cur = String(GM_getValue('jubo_v207_access_token', '') || ''); } catch (e) {}
          var v = prompt('输入服务端 JUBO_TOKEN（留空表示不设令牌）', cur);
          if (v === null) return;
          try { GM_setValue('jubo_v207_access_token', String(v || '').trim()); } catch (e) {}
          alert('访问令牌已更新。');
        });
      }
    } catch (e) { }
  }


  // ==================== V205.0.0 单一同步控制器 ====================
  // V205 不再使用旧 Leader、上传租约、dirty/changeSeq/ackSeq 或快照汇总状态机。
  var V205_AUTO_UPLOAD_KEY='jubo_v205_auto_upload';
  var V205_AUTO_PULL_KEY='jubo_v205_auto_pull';
  var V205_PANEL_OPEN_KEY='jubo_v205_panel_open';
  var V205_UPLOAD_TIMER=null, V205_PULL_TIMER=null, V205_UPLOAD_RUNNING=false;

  function isLocalSyncRealtimeUploadEnabled(){ return GM_getValue(V205_AUTO_UPLOAD_KEY,true)!==false; }
  function setLocalSyncRealtimeUploadEnabled(v){ GM_setValue(V205_AUTO_UPLOAD_KEY,!!v); if(v)v205WakeUpload('user-enabled',0); return !!v; }
  function isLocalSyncAggregateEnabled(){ return GM_getValue(V205_AUTO_PULL_KEY,true)!==false; }
  function setLocalSyncAggregateEnabled(v){ GM_setValue(V205_AUTO_PULL_KEY,!!v); v205SchedulePull(!!v?0:-1); return !!v; }

  function v205FindContact(sourceId,channel,externalId){
    var rows=v204CachedRows(), sid=String(sourceId||''), ch=String(channel||''), ext=String(externalId||'');
    for(var i=0;i<rows.length;i++) if(String(rows[i].source_id||'')===sid && String(rows[i].channel||'')===ch && String(rows[i].external_contact_id||'')===ext) return rows[i];
    return null;
  }
  function v204ContactContext(rowId){
    var raw=rowId&&typeof rowId==='object'?rowId:null,key=String(raw&&(raw.contact_id||raw.contactId||raw._localKey||raw.id)||rowId||''), rows=v204CachedRows(), contact=null;
    for(var i=0;i<rows.length;i++){
      var r=rows[i],observed=r.observed||{};
      if(String(r.contact_id||'')===key || String(r.external_contact_id||'')===key || String(observed.localKey||'')===key){contact=r;break;}
    }
    return contact?{contactId:String(contact.contact_id),sourceId:String(contact.source_id),version:Number(contact.version||0),contact:contact}:null;
  }

  async function v205UploadAll(){
    var dev=await v204RegisterDevice();if(!dev.ok)return dev;var local={};try{local=loadData()||{};}catch(e){}
    var items=[];Object.keys(local).forEach(function(k){var x=local[k];if(!x||typeof x!=='object'||v105IsDerivedMainRecord(k,x))return;var ext=v204External(x,k),dirty=Array.isArray(x.__dirtyFields)&&x.__dirtyFields.length;if(ext&&(dirty||!(x.__v204&&x.__v204.contactId)))items.push({key:k,row:x,external:ext,channel:v204Channel(x)});});
    if(!items.length){var idle=await v204FlushEventQueue();return {ok:idle.ok||idle.submitted===0,status:200,data:{contacts:0,remaining:idle.remaining,deadLetterCount:idle.deadLetterCount}};}
    var sourceMap={};for(var i=0;i<items.length;i++){var ch=items[i].channel;if(!sourceMap[ch]){var reg=await v204RegisterSource(ch);if(!reg.ok)return reg;sourceMap[ch]=String(reg.data.source.source_id||'');}}
    var observeIds=[];items.forEach(function(item){var x=item.row;if(x.__v204&&x.__v204.contactId)return;var e=v204Event('contact.observe',sourceMap[item.channel],{channel:item.channel,externalContactId:item.external,displayName:String(x.name||x.displayName||x.nickname||''),observedPhone:String(x.phone||x.phoneNumber||''),avatarUrl:String(x.avatar||x.avatarUrl||''),observed:{localKey:String(x._localKey||item.key||item.external),platformId:String(x.jid||x.threadId||x.id||''),username:String(x.username||''),profileUrl:String(x.profileUrl||x.profileHref||'')}});v204QueueEvent(e);observeIds.push(e.eventId);});
    if(observeIds.length){var observed=await v204FlushEventQueue(observeIds);if(!observed.currentBatchConfirmed)return {ok:false,status:409,error:'当前联系人观察失败：'+((observed.rejected[0]||{}).code||'等待重试'),data:observed};var pulled=await v204PullChanges();if(!pulled.ok)return pulled;local=loadData()||{};items.forEach(function(item){item.row=local[item.key]||item.row;});}
    var patchIds=[];items.forEach(function(item){var x=item.row,m=x.__v204||{},c=m.contactId&&v204ContactCache().contacts[m.contactId];if(!c)c=v205FindContact(sourceMap[item.channel],item.channel,item.external);if(!c)return;var payload=v204ManualPayload(x,c);if(Object.keys(payload).length){var e=v204Event('contact.patch',c.source_id||sourceMap[item.channel],payload,c.contact_id,c.version);v204QueueEvent(e);patchIds.push(e.eventId);}});
    var patched=patchIds.length?await v204FlushEventQueue(patchIds):{currentBatchConfirmed:true,remaining:v204EventQueue().length,deadLetterCount:v207DeadLetters().length};if(!patched.currentBatchConfirmed)return {ok:false,status:409,error:'当前联系人字段同步失败：'+((patched.rejected&&patched.rejected[0]||{}).code||'等待重试'),data:patched};
    var confirmed=await v204PullChanges();if(!confirmed.ok)return confirmed;var latest=loadData()||{};items.forEach(function(item){var r=latest[item.key];if(r){delete r.__dirtyFields;delete r.__dirtyAt;delete r.__dirtyBaseVersion;}});GM_setValue(STORAGE_KEY,JSON.stringify(latest));LOCAL_SYNC_LAST_STATUS.contacts=(confirmed.data.contacts||v204CachedRows()).map(v204WrapContact);return {ok:true,status:200,data:{contacts:items.length,remaining:v204EventQueue().length,deadLetterCount:v207DeadLetters().length,confirmed:true}};
  }

  async function localSyncUploadAll(){ return v205UploadAll(); }
  async function localSyncUploadOnly(){
    if(V205_UPLOAD_RUNNING)return {ok:false,skipped:true,reason:'running',error:'上传任务正在运行'};
    V205_UPLOAD_RUNNING=true; LOCAL_SYNC_RUNNING=true; v892SetRuntime({upload:'busy',uploadError:''});
    try{
      var h=await localSyncHealthCheck({silent:true}); if(!h.ok){v892SetRuntime({service:'error',upload:'retry',uploadError:h.error||('HTTP '+(h.status||''))});return h;}
      var r=await v205UploadAll();
      v892SetRuntime({service:'ok',upload:r.ok?'ok':'retry',lastUploadAt:r.ok?Date.now():v892SyncRuntime().lastUploadAt,uploadError:r.ok?'':String(r.error||(r.data&&r.data.code)||'上传失败')});
      return r;
    }catch(e){v892SetRuntime({upload:'retry',uploadError:String(e&&e.message||e)});return {ok:false,error:String(e&&e.message||e)};}
    finally{V205_UPLOAD_RUNNING=false;LOCAL_SYNC_RUNNING=false;LOCAL_SYNC_LAST_AUTO_AT=Date.now();if(v204EventQueue().length&&isLocalSyncRealtimeUploadEnabled())v205WakeUpload('remaining',1800);}
  }
  function v205WakeUpload(reason,delay){
    if(!isLocalSyncRealtimeUploadEnabled())return;
    clearTimeout(V205_UPLOAD_TIMER);V205_UPLOAD_TIMER=setTimeout(function(){localSyncUploadOnly();},delay==null?700:delay);
    try{v892SetRuntime({upload:'pending'});}catch(e){}
  }
  function scheduleLocalSyncAutoUpload(reason){v205WakeUpload(reason||'local-save',700);}
  async function drainLocalSyncUploadQueue(reason){return localSyncUploadOnly();}
  function v205CheckPendingUpload(reason){if(v204EventQueue().length||reason==='local-save')v205WakeUpload(reason,0);}

  function v205SchedulePull(delay){
    clearTimeout(V205_PULL_TIMER);V205_PULL_TIMER=null;if(delay<0||!isLocalSyncAggregateEnabled())return;
    V205_PULL_TIMER=setTimeout(async function(){try{v892SetRuntime({refreshState:'checking',lastRefreshCheckAt:Date.now(),refreshInterval:document.visibilityState==='visible'?3000:15000});var r=await localSyncFetchAllContacts();if(r.ok&&r.data&&((r.data.items||[]).length||(r.data.projection&&r.data.projection.projected)))v205BackgroundRender();v892SetRuntime({summary:r.ok?'ok':'error',refreshState:r.ok?'ok':'error',lastRefreshSuccessAt:r.ok?Date.now():v892SyncRuntime().lastRefreshSuccessAt,lastChangesCount:r.ok&&r.data?(r.data.items||[]).length:0,lastProjectedCount:r.ok&&r.data&&r.data.projection?Number(r.data.projection.projected||0):0,lastSummaryAt:r.ok?Date.now():v892SyncRuntime().lastSummaryAt,summaryError:r.ok?'':String(r.error||r.status||'接收失败')});}finally{v205SchedulePull(document.visibilityState==='visible'?3000:15000);}},delay||0);
  }
  function startLocalSyncAggregatePolling(){v205SchedulePull(0);}
  function stopLocalSyncAggregatePolling(){clearTimeout(V205_PULL_TIMER);V205_PULL_TIMER=null;}
  function startLocalSyncHeartbeat(){ /* V205 由上传/Changes worker 自身探测服务 */ }
  function stopLocalSyncHeartbeat(){}
  function v205StartSyncWorkers(){
    if (v205StartSyncWorkers.__started) return;
    v205StartSyncWorkers.__started = true;
    // 每个客户端独立上传并按 Changes 游标拉取，不使用 Leader 或租约。
    ['focus','online','pageshow'].forEach(function(ev){window.addEventListener(ev,function(){if(isLocalSyncRealtimeUploadEnabled())v205WakeUpload(ev,0);if(isLocalSyncAggregateEnabled())v205SchedulePull(0);});});
    document.addEventListener('visibilitychange',function(){if(document.visibilityState==='visible'&&isLocalSyncAggregateEnabled())v205SchedulePull(0);});
    if(isLocalSyncAggregateEnabled())v205SchedulePull(0);
    if(isLocalSyncRealtimeUploadEnabled())v205WakeUpload('boot',500);
  }

  function v205RestorePanelState(doc){
    doc=doc||document;var d=doc.getElementById('wa-v2021-health');if(!d||d.__v205Bound)return;d.__v205Bound=true;d.open=GM_getValue(V205_PANEL_OPEN_KEY,false)===true;d.addEventListener('toggle',function(){GM_setValue(V205_PANEL_OPEN_KEY,!!d.open);});
  }
  // ==================== V205.0.1 END ====================

  function boot() {
    try {
      v206RunMountPreflight();
    } catch (error) {
      v206ReportUiError('mount-preflight', error);
      return;
    }
    try { v892InjectSyncCss(document); } catch(e) {}
    setTimeout(function(){ try { initV204BusinessConfig(); } catch(e) { console.error('[v125 shared config]',e); } },1200);

    // v130：Dashboard 仅启动管理面板、共享配置和同步协调器。
    // 明确跳过 IG 被动监听、History Hook、渠道 DOM Observer、聊天轮询和备注栏挂载。
    if (STANDALONE_DASHBOARD_MODE) {
      // V206.0.6：Dashboard 启动同步协调器，但不注册为聊天渠道。
      try { v205StartSyncWorkers(); } catch(e) { console.error('[V206 dashboard workers]', e); }
      try { openManagePanel(); } catch(e) { console.error('[V206 dashboard panel]', e); }
      return;
    }

    function bootStepV2063(name, fn) { try { fn(); } catch (e) { v206ReportUiError('boot-' + name, e); } }
    bootStepV2063('workers', v205StartSyncWorkers);
    bootStepV2063('ig-observer', installIgPassiveObserverV1216);
    bootStepV2063('menus', registerMenuCommands);
    bootStepV2063('history', installHistoryHooks);
    bootStepV2063('dom-observer', installDomObserver);
    bootStepV2063('polling', startPolling);
    setTimeout(function () {
      try {
        __lastChatSignature = getChatSignature();
        renderNoteBar();
      } catch (error) { v206ReportUiError('initial-render', error); }
    }, 800);
    try { runLinkScan(); } catch (e) { }
  }

  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    boot();
  } else {
    window.addEventListener('DOMContentLoaded', boot);
  }


  /*
  ===============================================================================
  v130 独立 Dashboard 更新说明
  ===============================================================================
  1. 新增 http://127.0.0.1:8765/dashboard 独立入口，直接复用完整管理面板。
  2. Dashboard 模式不执行渠道识别、聊天 Header、备注栏、History Hook 或 DOM Observer。
  3. 使用 V205 幂等事件与 Changes 增量同步。
  4. 当前 Profile/sourceId 的原始事实记录可编辑；其他来源记录保持严格静态只读。
  5. 跨源/跨渠道 MAIN 派生记录继续只读，聚合结果不会覆盖本地事实库。
  6. 不增加远程命令、WebSocket、长轮询或第二套前端。
  ===============================================================================
  */


  // v72.4 更新说明：
  // 1) 默认字段 remark 显示名由“备注”改为“说明”；
  // 2) 面板设置文案改为“1-说明列自适应：每列最小宽度”；
  // 3) 9个自适应字段（f1-f7、闪光点、说明）统一执行最小宽度；
  // 4) 单元格缓冲从24px降为12px，缓解设置4个汉字时过早出现横向滚动条；
  // 5) 自适应宽度算法保留真实可用空间，不足时先将9列压到最小宽度，再由整表自然横滚。


/*
================================================================================
v73.4 更新说明：电话栏自动换行版
================================================================================

1. 本次修复
- 修复管理面板明细列表中“电话”栏不能自动换行的问题。
- 原因是电话栏原来使用 input type=text，浏览器原生只支持单行显示。

2. 本次调整
- 明细列表电话栏 manualPhone 从 input 改为 textarea。
- 电话栏现在支持长号码/多段号码自动换行显示。
- 输入时自动调整高度，避免内容被遮挡。

3. 保留 v73.3 操作习惯
- Enter：确认保存。
- Shift + Enter：保留换行。
- 鼠标点其他地方：失焦保存。

4. 保留 v73.2 核心机制
- 输入过程中不保存、不聚合、不刷新整表。
- 失焦或 Enter 确认后保存。
- 保存后重新扫描关联并刷新 MAIN 主记录。

5. 测试建议
- 在明细列表电话栏输入较长号码，确认单元格可以自动换行。
- 按 Enter 确认保存，确认不会插入换行。
- 按 Shift + Enter，确认可以手动换行。
- 保存后确认 MAIN 主记录和关联关系正常刷新。

================================================================================
*/


  // v74 更新说明：
  // 1. 选择列不显示文字标题，仅保留 checkbox，节省横向空间。
  // 2. 明细列表支持表头全选、取消全选与半选状态。
  // 3. 主记录区 MAIN 增加 checkbox，并支持表头三态全选。
  // 4. MAIN 与 DETAIL 支持联动选择：勾选 MAIN 自动勾选该组全部明细。
  // 5. 勾选部分 DETAIL 时，MAIN 显示半选状态；勾选全部 DETAIL 时 MAIN 自动选中。
  // 6. 批量栏统计升级为“已选 X组 / Y条”。
  // 7. 新增“导出选中”按钮，导出选中的 MAIN 聚合记录与 DETAIL 明细记录。
  // 8. 选中 MAIN 时自动导出该组 MAIN + 全部成员明细；只选中 DETAIL 时自动补充父 MAIN。


/*
===============================================================================
v99 更新说明：其他源全行严格只读与颜色设置版
1. 基于纯净 v93.1，保留 isAnyMainRecordV93 对 MAIN:: 小主记录的排除修复。
2. 其他源明细行所有 td（含固定头像/姓名、空字段及悬停态）统一应用可配置颜色。
3. 其他源电话、标签、画像、阶段、f1-f8、说明全部使用静态展示，不进入本地写入链路。
4. 其他源不生成删除、解绑、编辑、头像点击等交互，操作栏仅保留复制。
5. 关联栏显示“🚫 来源名称”。
6. 面板列宽设置区增加底色、悬停色、文字色选择器及重置按钮，配置持久化到 wa_remarks_settings。
7. 保留本源明细电话 textarea 自动换行、Enter 保存及 Shift+Enter 换行逻辑。
===============================================================================
*/


  // ============================================================
  // v105 更新说明（基于完整 v104）
  // 1. 同步模型改为 leaf-facts-only：MAIN 主记录不上传、不发送删除、不作为校准保留项。
  // 2. 上传构造层与请求发送层双重过滤；叶子记录移除聚合/界面派生字段，linkPolicy 保留同步。
  // 3. 拉取及显示层双重隔离旧版本服务端遗留 MAIN，避免主记录再次参与聚合。
  // 4. 旧来源校准 仅提交叶子 ID，可在强制重建时安全清理服务端旧 MAIN，不删除本地聚合视图。
  // 5. 完整备份仅含本源叶子事实；CSV 导入跳过 MAIN；动态主记录及成员仍可复制、选中并导出只读快照。
  // 6. 明细关联栏统一显示“已关联(n)”，解绑/恢复及跨源 linkPolicy 行为保持不变。
  // ============================================================


  // v121 初始化：只建立身份映射，不改动 旧版本地资料库，也不触发旧库上传。
  // V204：旧身份扫描已永久禁用。
  try {
    GM_registerMenuCommand('v121 身份层诊断', function() {
      var d = crmDiagnosticsV121();
      alert('v121 身份层诊断\n\n' + JSON.stringify(d, null, 2));
    });
  } catch (e) {}

})();
;

// v72.4: 默认横滚触发宽度 1280px；说明区9列表头🔒/🔓控制固定或自适应。

/*
================================================================================
v73.2 更新说明：明细编辑失焦聚合刷新版
================================================================================

1. 修复问题
- 修复 v73.1 中管理面板明细区文本字段输入时被自动刷新打断的问题。
- v73.1 为了保证 MAIN 主记录实时聚合，在 input 输入事件中会触发 upsertCell()。
- upsertCell() 会进一步触发 upsertFieldSmart()、runLinkScanAndRefreshPanelNow() 和管理面板刷新。
- 管理面板刷新会重绘表格，导致正在编辑的 input/textarea 被销毁重建，从而出现光标丢失、输入中断。

2. 本次调整
- 管理面板明细区的文本字段改为“输入中只标记 dirty，失焦 blur 后保存”。
- 适用字段包括 f1-f7、闪光点 f8、说明 remark。
- 电话字段 manualPhone 也改为失焦后保存，避免号码输入到一半时触发错误关联扫描。
- 失焦后仍然会执行原有 upsertCell() 链路，从而保存数据、重算 MAIN 主记录并刷新管理面板。

3. 保持即时刷新的操作
- 标签选择。
- 画像/画像选择。
- 跟进阶段勾选。
- 删除记录。
- 批量操作。
- 其他非连续输入类操作。

4. 用户体验变化
- 在明细列表连续输入时，表格不会再自动重绘，输入不会被打断。
- 编辑完成后点击页面其他位置，字段自动保存。
- 保存后会自动重新聚合 MAIN 主记录，上方主记录区会显示最新聚合值。

5. 测试建议
- 在明细列表第 7 列连续输入一段长文本，确认输入过程中光标不丢失、不被打断。
- 输入完成后点击空白处，确认上方 MAIN 主记录第 7 列自动聚合更新。
- 修改电话字段后点击空白处，确认关联主记录重新计算。
- 测试标签、画像、阶段操作，确认仍然是点击后立即刷新。

================================================================================
*/


/*
===============================================================================
v120 WhatsApp 精确身份修复（严格基于完整 v117）
===============================================================================
1. 删除 WhatsApp Header Fiber 的无约束深度递归与“首个 JID 即采用”逻辑。
2. 只读取 Header 前 3 层 Fiber 的直接 contact/chat 与直接 children props 字段。
3. 普通联系人以 @c.us 为唯一主键，@lid 作为别名；发现旧 LID 记录时安全迁移并保留冲突备份。
4. @g.us 明确分类为群组，聊天页仅显示隔离提示，禁止客户资料创建、修改及延迟写入。
5. 仅 LID 联系人保持只读，不将 LID 或群组误当成可写普通客户。
6. 身份必须跨时间连续稳定采样两次才生效；切换聊天期间撤下旧备注栏。
7. 所有聊天页延迟保存均绑定身份写入令牌，旧会话回调无法写入新会话。
8. IG / FB / TG、管理面板、同步协议、跨窗口协调器与 v117 其他功能保持不变。
===============================================================================
*/

/*
===============================================================================
v77 更新说明：本机多数据源同步版
===============================================================================
1. 新增本机多数据源同步：支持同一台电脑上的 Chrome Default、Profile 1、Profile 2、多开目录、便携版 Chrome 等不同油猴运行环境作为独立数据源。
2. 每个脚本实例自动生成唯一 sourceId，并支持在管理面板顶部手动设置 sourceName。
3. 新增本地同步服务支持，默认连接 http://127.0.0.1:8765。
4. 新增“同步全部”和“拉取汇总”按钮。
5. 同步时上传当前 GM 存储中的完整联系人 JSON，不只上传姓名、电话、标签等少数字段。
6. 本地服务保存完整 contact_json，兼容平台、关联、识别码、头像、姓名、电话、标签、画像、跟进阶段、1-7字段、闪光点、说明、更新时间、MAIN/DETAIL 等现有字段。
7. 汇总数据只用于管理面板显示，不写回当前 Profile 的 GM 存储，避免污染原始数据。
8. 不扫描 Chrome User Data 文件夹，不读取 Tampermonkey / Chrome IndexedDB / LevelDB 数据库。
9. 本地同步服务未启动时，脚本自动降级为 v76 原本地数据模式，原功能不受影响。
10. 保留 v76 原有管理面板、悬浮备注栏、标签、画像、跟进阶段、CSV导入导出、批量操作、列宽即时设置等能力。
===============================================================================
*/

/*
===============================================================================
v85 更新说明：同步栏稳定显示修复版
===============================================================================
1. 以 v77 能正常显示联系人信息的稳定代码为基线，不改动联系人读取、列表渲染、筛选和 MAIN/DETAIL 主体链路。
2. 修复管理面板顶部“本地同步栏”不显示的问题：在面板 HTML 初始化阶段固定加入 wa-local-sync-bar-wrap 容器。
3. 新增 ensureLocalSyncBarMount() 保底函数，renderAll() 每次刷新都会确认同步栏容器存在，避免因为挂载点缺失导致同步栏消失。
4. 移除平台筛选点击事件中错误创建同步栏容器的逻辑，避免只有点击平台筛选后才出现同步栏，也避免重复挂载或作用域异常。
5. 修复 getLocalSyncDisplayData()：本地 旧版本地资料库 永远作为基础数据源；同步服务拉取到的其他来源联系人只追加显示，不再替换本地数据。
6. 当前来源 sourceId 的同步记录如果本地已经存在同 contactId，则优先显示本地版本，避免同步包装数据覆盖当前 Profile 的原始联系人。
7. 本地同步服务未启动、拉取失败或 contacts 为空时，管理面板继续显示本地联系人数据，不再因同步状态影响联系人列表。
===============================================================================
*/


/*
===============================================================================
v86 更新说明：同步连接诊断修复版
===============================================================================
1. 修复管理面板弹窗内“同步全部 / 拉取汇总”点击无反应的问题：事件绑定改为使用弹窗 win.document，而不是主页面 document。
2. 新增“检测连接”按钮，可主动请求 /api/health 并刷新同步栏连接状态。
3. 新增“同步诊断”按钮，输出 URL、当前源、本地记录数、汇总源数、汇总记录数、最近一次请求结果等信息。
4. 管理面板打开后自动执行一次健康检查和源/统计拉取，避免服务已启动但状态仍显示未连接。
5. 保持 v85 的本地数据优先策略：同步汇总只用于管理面板追加显示，不覆盖当前 GM 本地数据。
===============================================================================
*/


/*
===============================================================================
v88 更新说明：实时上传与汇总分离版
===============================================================================
1. 将 v87 的“实时同步”拆分为两个独立开关：
   - 实时上传本源：只负责将当前浏览器/Profile 的 GM 本源数据上传到本地同步服务。
   - 自动接收显示：只负责当前管理面板拉取并显示其他来源汇总数据。
2. 删除容易混淆的“立即同步”，改为：
   - 上传一次：只执行本源上传，不拉取汇总。
   - 刷新汇总：只执行汇总拉取，不上传本源。
3. saveData() 的自动同步只受“实时上传本源”控制，约 1.2 秒防抖上传。
4. 管理面板显示只受“自动接收显示”控制：关闭时严格只显示本源，开启时显示本源 + 其他来源。
5. 同步数据仍只作为显示层缓存，不写回当前 GM_storage，避免跨源数据污染。
===============================================================================
*/


/*
===============================================================================
v89.2 本地同步状态呼吸灯增强版 - 修复说明
===============================================================================

1. 新增本地同步状态呼吸灯：
   - 连接状态
   - 上传状态
   - 汇总状态

2. 新增真实同步状态显示：
   - 本地联系人数量
   - 服务端当前源联系人数量
   - 服务端汇总源数量
   - 服务端汇总记录数量
   - 最近上传时间
   - 最近汇总时间
   - 最近错误信息

3. 优化实时上传本源：
   - 页面初始化后自动补偿上传一次
   - 数据变化后仍保留 1.2 秒防抖上传
   - 上传过程显示黄色状态
   - 上传成功显示绿色状态
   - 上传失败显示红色状态并显示错误信息

4. 优化自动接收显示：
   - 页面初始化后自动刷新汇总
   - 汇总过程显示黄色状态
   - 汇总成功显示绿色状态和真实数量
   - 汇总失败显示红色状态并显示错误信息

5. 优化同步诊断：
   - 增加 v89.2 runtime 状态输出
   - 可查看连接、上传、汇总、本地数量、服务端本源数量、汇总源和汇总记录

6. 优化校准本源：
   - 将原“校准本源”按钮升级显示为“强制重建本源”
   - 执行逻辑改为：先清空服务端当前 sourceId，再全量上传当前浏览器 GM_storage
   - 只影响 Python sqlite 中当前 sourceId 数据，不会清空浏览器 GM_storage

7. 保留 v89.1 跨源只读保护：
   - 其他源汇总数据仍显示为只读
   - 不允许在当前源编辑或删除其他源数据

===============================================================================
*/


/*
===============================================================================
v89.3 本地同步栏精简版 - 修复说明
1. 当前源移动到同步栏最前面；源名称输入框失焦或 Enter 自动保存。
2. 取消保存源名按钮，保存成功提示“修改源名称成功”。
3. 删除重复的本地同步已连接文案，只保留呼吸灯连接状态。
4. 实时上传本源/自动接收显示精简为实时上传/自动接收，并和呼吸灯状态合并展示。
5. 基于 v89.2 源码做局部替换，避免继续臃肿追加。
===============================================================================
*/
/*
===============================================================================
v89.4 同步栏修复美化版
1. 当前源与 ID 移到管理面板标题后面。
2. 当前源输入框 8ch 起步，并随输入字符自动变宽。
3. 同步栏尽量一行显示，按钮圆角胶囊化美化。
4. 修复 v89.3 checkbox 被 v892RenderSyncLights 反复 innerHTML 重建，导致自动接收掉勾、事件丢失的问题。
5. 修复自动实时上传不更新上传状态和上传时间的问题。
6. v892RenderSyncLights 只更新固定状态节点，不再销毁开关 DOM。
===============================================================================
*/
/*
===============================================================================
v89.5 同步栏稳定自适应版
1. 当前源输入框改为真实文字宽度测量，不再仅按字符数估算。
2. 同步栏改为自然换行布局，按钮不再 margin-left:auto 顶右遮挡状态文字。
3. renderAll 不再每次重建同步栏，只在首次或缺失时初始化，解决状态跳动/空白。
4. 汇总轮询更新 runtime 状态和时间，减少显示异常。
===============================================================================
*/
/*
===============================================================================
v89.6 标题按钮与本源重建修复版
1. 上传一次 / 刷新汇总 / 强制重建本源 / 检测连接 / 同步诊断 五个按钮移动到标题行 ID 后面。
2. 同步栏仅保留连接、实时上传、自动接收、计数和时间状态。
3. 强制重建本源不再发送 contactIds: []。
4. 新增 V204 重新上传本源流程：
   - 读取当前 GM_storage 本地联系人 ID；
   - 通过 V205 事件批量重新上传本地联系人；
   - 再执行 localSyncUploadAll() 全量上传；
   - 最后刷新统计和汇总。
===============================================================================
*/

/*
===============================================================================
v89.7 本源重建点击修复版
===============================================================================
1. 修复 bindLocalSyncBarEvents() 内直接使用 win.confirm / win.alert 的问题。
   原因：win 是 openManagePanel() 里的局部变量，bindLocalSyncBarEvents() 访问不到。
2. 新增 panelWin：
   var panelWin = (doc && doc.defaultView) || managePanelWindow || window;
3. 新增 confirmSafe() 和 show()，所有弹窗都优先使用当前管理面板窗口。
4. “强制重建本源”点击后会立即：
   - 按钮变为“重建中...”
   - 上传状态变为 busy
5. 重建成功后弹出“本源重建成功”。
6. 重建失败后弹出“本源重建失败”，并提示点击“同步诊断”查看 lastRequest。
7. 无论成功失败，按钮都会在 finally 中恢复为“强制重建本源”。
===============================================================================
*/


/*
===============================================================================
v99 他源标签与跟进阶段完整显示版 - 更新说明
===============================================================================
1. 修复 v98 他源行直接读取当前 GM_storage，导致关联主记录中的标签和阶段丢失的问题。
2. 新增他源展示数据规范化层，兼容数组、单字符串、JSON 字符串、分隔字符串及对象映射。
3. 汇总合并时为他源 id、mainKey、__mainKey、memberIds 统一增加 sourceId 命名空间，恢复他源内部关联关系。
4. 上传协议升级为 schemaVersion 99，并新增 _presentation 展示快照：
   - 标签：保存 key、label、color；
   - 画像：保存多个 key、label、color；
   - 跟进阶段：保存 key、label、color。
5. 他源显示优先使用来源端展示快照；旧记录无快照时自动兼容本地定义和原始字段。
6. 标签、画像、跟进阶段继续保持纯静态只读，不绑定编辑、切换或删除事件。
7. 保留 v98 的他源底色、自动文字色、自动悬停色、关联栏换行、禁止光标及复制白名单。
8. 安装 v99 后，各来源执行一次“上传一次”或“强制重建本源”，即可为服务端旧记录补齐展示快照。
===============================================================================
*/

/*
===============================================================================
v100.1 修复长电话号码联系人隐藏 - 更新说明
===============================================================================
1. 基于纯净 v99 源码制作，仅修复管理面板中的联系人隐藏问题。
2. 修复电话号码达到 7 位纯数字后，单独联系人被赋予 __mainKey 并从明细列表隐藏的问题。
3. 现在仅当对应的关联主记录真实存在（同一规范化号码至少有 2 条联系人记录）时，
   才按原有展开/折叠状态隐藏或显示关联明细。
4. 单独联系人无论电话号码位数多少，都会继续显示在本源或他源明细列表中。
5. 未修改电话号码规范化、11 位处理、关联扫描、同步、标签、阶段及其他界面功能。
===============================================================================
*/

// ============================================================
// v100.2 更新说明（基于 v100.1）
// 1. 明细列表（本源与他源）的识别码改为单行中间省略，避免长识别码换行导致行高过大。
// 2. 鼠标悬停识别码可查看完整值；底层识别码、复制、导出、同步与关联逻辑均未改变。
// 3. 主记录专区电话栏由只读 input 改为只读 textarea，支持按列宽自动换行并自动增高。
// 4. 保留 v100.1 对“虚拟 __mainKey 导致单联系人隐藏”的修复，不改动数据结构及关联规则。
// ============================================================


// ============================================================
// v103 更新说明（基于完整 v102）
// 1. 同人关联扫描升级为完整对账：号码变化后自动退出旧组、清除悬空引用并解散不足两人的旧组。
// 2. “已关联”、默认隐藏、解绑、共享视图统一使用当前有效关联，不再把号码候选 MAIN 键当成真实关联。
// 3. 手动解绑改为“联系人 + 当前号码”；换用新号码后仍可正常参与关联，普通重扫不再清空解绑规则。
// 4. 本源、他源汇总、管理面板与聊天页动态关联统一遵守当前号码的禁止规则。
// 5. 首次运行兼容迁移 v102 的 unlinkedMemberIds，并自动清理历史脏关联；普通联系人业务字段不变。
// ============================================================

// v106：明细来源简化为“本源”/源名称并按 sourceId 稳定配色；所有叶子渠道统一使用 10px 单行小徽标。

// ============================================================
// v107.1 更新说明（严格基于原始 v106.2）
// 1. 来源菜单去除“仅本源”重复项，仅保留全部来源、本源·当前源、全部他源及具体他源。
// 2. 来源与搜索、渠道、标签、画像交叉筛选；搜索范围包含来源名称。
// 3. 新增来源、渠道顺序及关联状态排序；均为运行时派生，不修改事实数据。
// 4. 新增清除筛选；不改变排序、主题、换行及列宽。
// 5. 自动接收首次使用默认开启，尊重用户已保存的开关值，并启动实际轮询。
// 6. 导入、导出、标签、字段、重扫沿用 v106.2 静态 DOM 与原事件链，不动态迁移按钮。
// ============================================================

// ============================================================
// v107.2 更新说明
// 1. 渠道排序显示文字缩短为“按渠道顺序”。
// 2. 深色模式、导出CSV、导入CSV保留原按钮ID、样式及事件链，仅调整至第一排。
// ============================================================

// v108：完整聚合 CSV、动态 MAIN 只读快照、安全选择导入、配置可选恢复与失败回滚。

// ============================================================
// v111 版本更新说明
// ============================================================
// 1. 严格以完整 v109 为基础，未继承 v110 的错误样式拼接代码。
// 2. 停止应用旧 link-group-bg-* 关联组整行淡色，关联色仅用于电话单元格。
// 3. 主记录使用自身 MAIN 唯一键，子记录使用 row.__mainKey，二者生成完全相同的稳定纯色。
// 4. 颜色不再按显示顺序临时分配，排序、筛选、展开、收起和跨来源同步后保持不变。
// 5. 取消电话空值粉红背景；其他字段原有空值提示保持不变。
// 6. 取消本源电话输入框强制白底；主记录只读电话框与本源电话框均使用透明背景。
// 7. 保留他源整行灰色与严格只读；已关联他源记录的电话格由关联组纯色覆盖灰底。
// 8. 电话关联色优先于悬停、深色模式、只读底色和空值底色，编辑与复制功能不变。
// 9. v111 样式通过独立 style 元素写入管理面板 head，避免 CSS 源码显示在页面顶部。
// 10. 完整保留 v109 的金红主题、姓名复制、同步、筛选、CSV/Excel、导入回滚及 MAIN 保护。
//
// 脚本名称：v112、聚宝盆客户信息管理系统、同步状态实时检测
// 版本号：111
// 基础版本：v109
// ============================================================



/*
===============================================================================
v121 更新说明：全渠道稳定身份层（非破坏性兼容版）
===============================================================================
1. 完整保留 v117 业务功能与 v120 WhatsApp Header Fiber 安全识别、稳定采样、群组隔离和写入令牌。
2. 新增 Customer、ChannelAccount、Identity、LegacyBinding 四层结构，覆盖 WA、IG、FB、TG。
3. 旧版本地资料库 继续作为旧业务事实库；v121 不删除、不改名、不自动合并任何旧 contactId。
4. 禁用 v120 mergeWaAliasRecordV120 的自动删除路径；@c.us 与 @lid 只登记为同账号身份证据。
5. MAIN:: 聚合记录不迁移为真实客户；现有 MAIN/DETAIL、电话关联和同步协议保持不变。
6. 身份冲突只写入 crm_identity_conflicts，不静默覆盖索引，不按姓名或头像合并。
7. 当前聊天采用身份索引解析后回落到 legacyRecordId，确保现有资料继续可见、可编辑。
8. 身份层暂不上传旧本地同步服务；旧服务仍仅同步 旧版本地资料库，避免协议不兼容。
9. v121.1 修复同源 旧同步包装键： 汇总键误入 GM 本源：自动迁移业务字段到真实 ID，并清理服务端旧包装 ID。
10. 上传、请求校准双层禁止 旧同步包装键： 作为本源事实；汇总显示完全跳过当前源服务端副本。
11. 其他源 旧同步包装键： 仍严格只读；当前源异常包装键允许安全清理，修复过程保留审计摘要。
===============================================================================
*/


/*
===============================================================================
v124 更新说明：导出统一命名与聚宝盆版本徽标自动更新
===============================================================================
1. 严格基于完整 v123，保留联系人清空自动删除及服务端同步删除等全部既有逻辑。
2. 完整 CSV、Excel、选中记录 CSV 统一采用“系统名称_版本号_本地导出时间”命名。
3. 导出时间格式为 YYYYMMDD_HHmmss，使用浏览器本地时间。
4. 文件名、CSV 元信息、Excel 脚本版本复用 GM_info.script.version。
5. 移除标题前方写死 120 的旧徽标；聚宝盆 SVG 位于系统名称后方，版本显示在盆身内。
===============================================================================
*/

/* v125：标签/画像/字段名称/阶段名称公共配置同步；底层 tag、tag2、f1-f8、remark、s1-s3 保持不变。 */


/*
===============================================================================
v128.0.3-beta1 更新说明
===============================================================================
1. 保留 alpha2 上传任务令牌、5 秒续租、12 秒请求硬超时及 120 秒看门狗。
2. 增加 Leader、上传任务与跨标签上传租约剩余时间诊断，所有令牌仅显示脱敏摘要。
3. 增加成功、失败、看门狗、自修复累计次数及最近错误/修复原因。
4. 防御系统时间回拨造成的异常未来重试时间、Leader 租约和上传租约。
5. 修复 ackSeq 异常被规范化提前吞掉、任务结束后 uploadStartedAt 遗留等边界问题。
6. alpha1/alpha2 状态在原 wa_sync_upload_state_v128 键上无损补字段，不改业务数据。
7. 默认日志只记录 Leader 切换、上传结果、看门狗和状态修复等关键事件。
===============================================================================
*/

/*
===============================================================================
v128.0.4-rc1 更新说明
===============================================================================
1. 基于 v128.0.3-beta1 长稳验证通过的代码生成发布候选版本。
2. 不增加业务功能，不修改联系人字段、CRM 身份层、Python 后端或 SQLite 结构。
3. 保留 Leader 选举、上传任务令牌、租约续期、请求硬超时、看门狗与状态自修复逻辑。
4. 本次仅完成版本元数据、同步状态版本、诊断标题、关键日志前缀及发布说明收口。
5. 继续复用 wa_sync_upload_state_v128，原序列进度与同步状态可无损延续。
===============================================================================
*/

/*
===============================================================================
v128.1.0 正式版发布说明
===============================================================================
1. v128.0.4-rc1 已完成安装升级、多标签并发、离线恢复及本地服务重启回归。
2. 保留经验证的 Leader 唯一性、上传任务令牌、租约续期、请求硬超时与看门狗机制。
3. 保留同步诊断、关键事件日志、时间跳变防护和持久上传状态自修复。
4. 沿用 wa_sync_upload_state_v128，不迁移联系人数据、CRM 身份层或后端数据库结构。
5. 本次正式版晋升仅更新版本及发布标识，不改变 RC1 已验证的执行逻辑。
===============================================================================
*/
//（注：内容由AI生成）

/*
===============================================================================
V134 正式修复版更新说明（2026-09-15）
===============================================================================
1. 危险删除采用“服务端挑战—用户确认—刷新 Lease—原请求二次提交”的完整闭环。
2. 二次提交保持同一 Snapshot 内容、Snapshot Hash、Batch ID 与 Snapshot 序号，仅附加确认令牌并更新 Lease 凭据。
3. 409 及不可恢复的 4xx 冲突进入 blocked 状态，停止无限自动重试；网络和 5xx 临时故障继续退避重试。
4. 日志补充错误代码、来源、批次、序号和删除统计，并对 Lease Token、认证 Token 做脱敏处理。
5. 旧协议已在 V205 中退役。
6. 本文件须与 V134_中心同步服务.py、V134_shared_db.py 成套部署；升级前请停止服务并备份数据库。
===============================================================================
*/

/* V202 RC1：旧快照写入入口已由运行时事件适配层替代；旧函数仅作为历史兼容代码保留且不可由 UI 触发。 */


/*
===============================================================================
V206.0.6 更新说明（2026-09-17）
===============================================================================
1. 修复 Changes 拉取后只更新远端缓存、未投影到聊天界面本地兼容库的问题。
2. 增加服务端联系人静默投影；不调用 saveData，不触发自动上传。
3. 增量拉取发现变更后自动刷新管理面板并强制重绘当前聊天备注栏。
4. Changes 游标与联系人缓存按服务地址和工作区隔离，避免跨库、跨工作区串用。
5. 来源字段固定为最后观察设备名称；账号来源名称独立保存。
6. 渠道固定显示 WA / IG / FB / MS / TG / OT，无法识别时归入 other，不再默认 WhatsApp。
7. 服务端投影版本作为客户端编辑基线，仅实际发生差异的人工字段允许上传，阻止陈旧值反向覆盖。
8. 保持 API 205、Schema 205，不执行数据库结构迁移。
===============================================================================
*/

/* V207.0.0 版本更新说明（2026-09-17）：事件队列按服务器/工作区/设备隔离；旧上下文异常转入死信；本轮确认与全局队列分离；联系人保存采用 dirty 字段精准上传；停止已映射联系人重复 Observe；刷新周期统一为前台3秒/后台15秒并补充刷新诊断状态。API/Schema 保持205。 */
