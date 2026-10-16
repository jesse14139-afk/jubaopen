"use strict";
const KEYS=["serverUrl","installationId","pluginToken","pluginSessionId","expiresAt","deviceId"];
const CREDENTIAL_KEYS=["pluginToken","pluginSessionId","expiresAt","deviceId"];
const QUEUE_KEY="jubaMessageQueueV208",FOLLOW_KEY="jubaFollowUpNotificationsV208";const memory={flushing:false,followPolling:false};
async function config(){return chrome.storage.local.get(KEYS)}
async function installationId(){let c=await config();if(c.installationId)return c.installationId;const id="ins_"+crypto.randomUUID();await chrome.storage.local.set({installationId:id});return id}
function baseUrl(value){const raw=String(value||"").trim().replace(/\/$/,"");let u;try{u=new URL(raw)}catch(_){throw new Error("服务器地址无效")};const local=["127.0.0.1","localhost","[::1]"].includes(u.hostname);if(u.protocol!=="https:"&&!(local&&u.protocol==="http:"))throw new Error("非本机服务器必须使用 HTTPS");return raw}
async function loadQueue(){const x=await chrome.storage.local.get(QUEUE_KEY);return Array.isArray(x[QUEUE_KEY])?x[QUEUE_KEY]:[]}
const DEAD_KEY="jubaMessageDeadLetterV210244",QUEUE_MAX=2000,DEAD_MAX=10000,MAX_ATTEMPTS=5,RETRYABLE_CODES=new Set(["MESSAGE_INTERNAL_ERROR"]);
function capacityError(){return Object.assign(new Error("消息存储容量不足，已保留原队列；请导出或处理失败存档后重试"),{code:"QUEUE_CAPACITY_EXCEEDED"})}
function mergeDead(d,items,reason){const n=Date.now(),out=d.slice(),keys=new Set(out.map(m=>queueId(m)+"|"+messageRevision(m)));for(const m of items){const key=queueId(m)+"|"+messageRevision(m);if(keys.has(key))continue;keys.add(key);out.push({...m,_jubaDeadReason:reason||m?._jubaLastError?.code||"UNKNOWN",_jubaDeadAt:n})}if(out.length>DEAD_MAX)throw capacityError();return out}
async function appendDead(items,reason){if(!items.length)return;const x=await chrome.storage.local.get(DEAD_KEY),d=Array.isArray(x[DEAD_KEY])?x[DEAD_KEY]:[];await chrome.storage.local.set({[DEAD_KEY]:mergeDead(d,items,reason)})}
async function saveQueue(q){if(q.length>QUEUE_MAX)throw capacityError();await chrome.storage.local.set({[QUEUE_KEY]:q})}
async function invalidate(clearQueue=false){await chrome.storage.local.remove(clearQueue?[...CREDENTIAL_KEYS,QUEUE_KEY,FOLLOW_KEY]:[...CREDENTIAL_KEYS,FOLLOW_KEY])}
async function request(server,path,options={},token=""){let res;try{res=await fetch(baseUrl(server)+path,{method:options.method||"GET",headers:{...(token?{"Authorization":"Bearer "+token}:{}),"Content-Type":"application/json"},body:options.body===undefined?undefined:JSON.stringify(options.body)})}catch(cause){const e=new Error("无法连接 JubaOpen 服务，请检查服务是否启动、服务器地址及 HTTPS 设置");e.code="NETWORK_ERROR";e.cause=cause;throw e}let data={};try{data=await res.json()}catch(_){data={ok:false,code:"INVALID_RESPONSE",message:"服务器响应无效"}}if(res.status===401&&token)await invalidate();if(!res.ok||data.ok===false){const e=new Error(data.message||data.code||("HTTP "+res.status));e.code=data.code;e.status=res.status;e.payload=data;throw e}return data}
async function api(path,options={}){const c=await config();if(!c.serverUrl||!c.pluginToken||!c.expiresAt||Number(c.expiresAt)<=Date.now()){const e=new Error("插件尚未接入或凭证已失效");e.code="PLUGIN_UNAUTHORIZED";e.status=401;throw e}return request(c.serverUrl,path,options,c.pluginToken)}
async function enroll(value){const server=baseUrl(value.serverUrl),iid=await installationId();const out=await request(server,"/api/v207/collector/enroll",{method:"POST",body:{bindingCode:value.bindingCode,installationId:iid,deviceAlias:value.deviceAlias||"",computerAlias:value.computerAlias||"",clientVersion:chrome.runtime.getManifest().version,browser:"Chrome"}});await chrome.storage.local.set({serverUrl:server,installationId:iid,pluginToken:out.pluginToken,pluginSessionId:out.pluginSessionId,expiresAt:out.expiresAt,deviceId:out.deviceId});return out}
async function rebind(value){const c=await config(),server=baseUrl(value.serverUrl||c.serverUrl),iid=await installationId();const out=await request(server,"/api/v207/collector/rebind",{method:"POST",body:{rebindCode:value.rebindCode,installationId:iid,clientVersion:chrome.runtime.getManifest().version,browser:"Chrome"}});await chrome.storage.local.set({serverUrl:server,installationId:iid,pluginToken:out.pluginToken,pluginSessionId:out.pluginSessionId,expiresAt:out.expiresAt,deviceId:out.deviceId});return out}

async function followUpPoll(){
 if(memory.followPolling)return {ok:true,skipped:true};memory.followPolling=true;
 try{
  const iid=await installationId(),out=await api("/api/v207/collector/follow-up-notifications/poll",{method:"POST",body:{consumerType:"extension",consumerId:iid,limit:100}}),items=Array.isArray(out.items)?out.items:[],preferences=out.preferences||{},alerting=items.filter(x=>x.shouldAlert);
  await chrome.storage.local.set({[FOLLOW_KEY]:items,jubaFollowUpLastPollAt:Date.now(),jubaFollowUpLastError:"",jubaFollowUpDesktopEnabled:preferences.desktopNotifications===true});
  await chrome.action.setBadgeBackgroundColor({color:"#db2777"}).catch(()=>{});await chrome.action.setBadgeText({text:items.length?String(Math.min(items.length,99)):""}).catch(()=>{});
  // 桌面通知完全由插件 service worker 产生，不依赖管理页面或社交平台标签页。
  // 必须尊重用户保存到服务端的 desktopNotifications 偏好；网页内弹窗不受此开关影响。
  if(alerting.length&&preferences.desktopNotifications===true){
   const overdue=alerting.filter(x=>x.status==="overdue").length,first=alerting[0],privacy=preferences.privacyMode!==false;
   const body=privacy?`${overdue} 位已逾期 · 请点击查看通知中心`:`${overdue} 位已逾期 · 最早 ${first?.customerName||"客户"} · ${first?.platform?.abbr||"—"}`;
   await chrome.notifications.create("juba-followup-summary",{type:"basic",iconUrl:"icons/icon128.png",title:`${alerting.length} 位客户需要跟进`,message:body,priority:2,requireInteraction:true});
  }
  const tabs=await chrome.tabs.query({});
  for(const tab of tabs){if(!/^https:\/\/(web\.whatsapp\.com|www\.instagram\.com|www\.messenger\.com|www\.facebook\.com|web\.telegram\.org)\//.test(tab.url||""))continue;chrome.tabs.sendMessage(tab.id,{type:"jubaFollowUpSummary",items,preferences,shouldOpen:alerting.length>0}).catch(()=>{});}
  return out
 }catch(e){await chrome.storage.local.set({jubaFollowUpLastPollAt:Date.now(),jubaFollowUpLastError:e?.code||e?.message||"POLL_FAILED"}).catch(()=>{});if(![401].includes(e.status))console.warn("JubaOpen follow-up poll",e);throw e}
 finally{memory.followPolling=false}
}
async function followUpAction(id,action,body={}){const out=await api(`/api/v207/collector/follow-up-notifications/${encodeURIComponent(id)}/${action}`,{method:"POST",body});await followUpPoll();return out}
chrome.notifications.onClicked.addListener(async id=>{if(id!=="juba-followup-summary")return;const c=await config();if(!c.serverUrl)return;const root=baseUrl(c.serverUrl),url=root+"/admin#notifications",tabs=await chrome.tabs.query({url:root+"/*"});if(tabs.length){await chrome.tabs.update(tabs[0].id,{active:true,url});if(tabs[0].windowId!=null)await chrome.windows.update(tabs[0].windowId,{focused:true})}else await chrome.tabs.create({url});});

function queueId(m){const c=m.registrationContext||{},scope=m.conversationId||`${c.platformCode||""}:${c.channelAccountId||""}:${c.externalConversationId||""}`;return String(scope)+"|"+String(m.collectionGeneration||1)+"|"+String(m.externalMessageId||m.clientEventId||"")}
function messageRevision(m){const t=m?.metadata?.translation||{};return JSON.stringify([String(m?.direction||""),String(m?.contentType||""),String(m?.text||""),Number.isFinite(Number(m?.occurredAt))?Number(m.occurredAt):null,m?.metadata?.timestampResolved===false?false:true,String(t.text||""),String(t.source||t.provider||""),String(m?.metadata?.reply?.text||""),String(m?.metadata?.reply?.quotedExternalMessageId||"")])}
function messageCompleteness(m){const t=m?.metadata?.translation||{};return (String(m?.text||"").trim()?4:0)+(Number.isFinite(Number(m?.occurredAt))?3:0)+(m?.metadata?.timestampResolved===false?0:1)+(String(t.text||"").trim()?4:0)+(String(m?.metadata?.reply?.text||m?.metadata?.reply?.quotedExternalMessageId||"").trim()?2:0)}
async function enqueueUnlocked(items){const dx=await chrome.storage.local.get(DEAD_KEY),dead=Array.isArray(dx[DEAD_KEY])?dx[DEAD_KEY]:[];let q=await loadQueue(),positions=new Map(q.map((m,i)=>[queueId(m),i])),added=[];for(const m of items||[]){const id=queueId(m);if(!id||id.endsWith("|"))continue;const blocked=dead.find(x=>queueId(x)===id&&messageRevision(x)===messageRevision(m));if(blocked){rememberAck(m,{ok:false,code:blocked._jubaDeadReason||"MESSAGE_QUARANTINED",quarantined:true});continue}const pos=positions.get(id);if(pos===undefined){positions.set(id,q.length);q.push(m);added.push(id);continue}const prior=q[pos];if(messageRevision(prior)!==messageRevision(m)&&messageCompleteness(m)>=messageCompleteness(prior)){q[pos]=m;added.push(id)}}await saveQueue(q);return {queued:Math.min(q.length,QUEUE_MAX),added}}
// 210.2.44 WA 消息采集未入库修复：
// 1) 队列读改写全部串行化，避免上传途中新采集的消息被旧快照覆盖丢失；
// 2) 可重试失败移到队尾并计数，不再 break 阻塞后续消息；超过上限转入失败存档（不删除、可重放）；
// 3) 上传请求串行排队，不再返回 QUEUE_BUSY 误报；近期回执缓存供 waitForResult 查询。
memory.qlock=Promise.resolve();memory.chain=Promise.resolve();memory.acks=new Map();
function withQueueLock(fn){const r=memory.qlock.then(fn,fn);memory.qlock=r.catch(()=>{});return r}
function enqueue(items){return withQueueLock(()=>enqueueUnlocked(items))}
function stripLocal(m){const {_jubaAttempts,_jubaLastError,_jubaDeadReason,_jubaDeadAt,_jubaNextAttemptAt,...rest}=m||{};return rest}
function rememberAck(m,x){const id=queueId(m);memory.acks.delete(id);memory.acks.set(id,{rev:messageRevision(m),x});while(memory.acks.size>3000)memory.acks.delete(memory.acks.keys().next().value)}
function recentAck(m){const r=memory.acks.get(queueId(m));return r&&r.rev===messageRevision(m)?r.x:null}
function commitPart(done,retry,dead){return withQueueLock(async()=>{
 let q=await loadQueue();
 q=q.filter(m=>{const rev=done.get(queueId(m));return rev===undefined||rev!==messageRevision(m)});
 const ids=new Set(q.map(queueId));for(const m of retry)if(!ids.has(queueId(m)))q.push(m);
 const stored=await chrome.storage.local.get(DEAD_KEY),d=Array.isArray(stored[DEAD_KEY])?stored[DEAD_KEY]:[];if(q.length>QUEUE_MAX)throw capacityError();await chrome.storage.local.set({[QUEUE_KEY]:q,[DEAD_KEY]:mergeDead(d,dead)});
})}
async function flushOnce(){
 const acknowledgements={};let last=null;memory.flushing=true;
 try{
  const snapshot=(await loadQueue()).filter(m=>!m._jubaNextAttemptAt||m._jubaNextAttemptAt<=Date.now());
  for(let i=0;i<snapshot.length;i+=100){
   const part=snapshot.slice(i,i+100),waPart=part.filter(x=>String(x?.metadata?.platformCode||"").toLowerCase()==="whatsapp"),waTranslations=waPart.filter(x=>String(x?.metadata?.translation?.text||"").trim()).length;console.info("JubaOpen WA queue diagnostic",{version:"210.2.75",messages:waPart.length,translations:waTranslations,queued:snapshot.length});const out=await api("/api/v207/collector/messages/batch",{method:"POST",body:{messages:part.map(stripLocal)}}),results=Array.isArray(out.results)?out.results:[];last=out;
   if(results.length!==part.length)throw new Error("消息批次响应数量不一致");
   const done=new Map(),retry=[],dead=[];
    results.forEach((x,j)=>{const m=part[j],id=queueId(m);if(!x||typeof x.ok!=="boolean")throw new Error("消息回执格式无效");done.set(id,messageRevision(m));if(x.ok)return;
     const n=(Number(m._jubaAttempts)||0)+1,item={...m,_jubaAttempts:n,_jubaLastError:{code:x.code||"UNKNOWN"},_jubaNextAttemptAt:Date.now()+Math.min(300000,10000*2**(n-1))};
     if(RETRYABLE_CODES.has(x.code)&&n<MAX_ATTEMPTS)retry.push(item);else{dead.push(item);results[j]={...x,quarantined:true}}
     console.warn("JubaOpen message rejected",x.code||"UNKNOWN");});
   await commitPart(done,retry,dead);part.forEach((m,j)=>{acknowledgements[queueId(m)]=results[j];rememberAck(m,results[j])});
  }
  return {...(last||{}),acknowledgements};
 }catch(e){console.warn("JubaOpen persistent queue retained",e);return {error:e?.code||"QUEUE_FLUSH_FAILED",message:e?.message||String(e),acknowledgements}}
 finally{memory.flushing=false}
}
function flush(){const run=memory.chain.then(flushOnce,flushOnce);memory.chain=run.catch(()=>{});return run}
async function retryDeadLetters(){const moved=await withQueueLock(async()=>{const x=await chrome.storage.local.get(DEAD_KEY),d=Array.isArray(x[DEAD_KEY])?x[DEAD_KEY]:[];const q=await loadQueue(),ids=new Set(q.map(m=>queueId(m)+"|"+messageRevision(m))),remaining=[];let moved=0;for(const m of d){const c=stripLocal(m),key=queueId(c)+"|"+messageRevision(c);if(ids.has(key)){moved++;continue}if(q.length>=QUEUE_MAX){remaining.push(m);continue}if(q.some(x=>queueId(x)===queueId(c))){remaining.push(m);continue}q.push(c);ids.add(key);moved++}await chrome.storage.local.set({[QUEUE_KEY]:q,[DEAD_KEY]:remaining});return moved});if(moved)void flush();return {ok:true,moved}}
async function queueDiagnostics(){const q=await loadQueue(),x=await chrome.storage.local.get(DEAD_KEY),d=Array.isArray(x[DEAD_KEY])?x[DEAD_KEY]:[];return {queued:q.length,retrying:q.filter(m=>m._jubaAttempts).length,deadLetters:d.length,lastDead:d.slice(-5).map(m=>({externalMessageId:m.externalMessageId,reason:m._jubaDeadReason,error:m._jubaLastError}))}}
chrome.runtime.onMessage.addListener((m,_sender,reply)=>{(async()=>{if(m.type==="api")return api(m.path,m.options||{});if(m.type==="followUpPoll")return followUpPoll();if(m.type==="followUpAction")return followUpAction(m.notificationId,m.action,m.body||{});if(m.type==="enroll")return enroll(m.value||{});if(m.type==="rebind")return rebind(m.value||{});if(m.type==="clearConversationQueue")return withQueueLock(async()=>{let q=await loadQueue();q=q.filter(x=>String(x.conversationId||"")!==String(m.conversationId||"")||Number(x.collectionGeneration||1)>=Number(m.collectionGeneration||1));await saveQueue(q);return {ok:true,queued:q.length}});if(m.type==="queueDiagnostics")return queueDiagnostics();if(m.type==="retryDeadLetters")return retryDeadLetters();if(m.type==="queueMessages"){const items=m.messages||[],enqueued=await enqueue(items);if(m.waitForResult){const out=await flush(),acks=out?.acknowledgements||{},results=items.map(x=>acks[queueId(x)]||recentAck(x)||{ok:false,code:out?.error||"QUEUE_RESULT_PENDING"});return {...(out||{}),results,queued:enqueued.queued}}void flush();return {ok:true,queued:enqueued.queued}}if(m.type==="getConfig")return {...await config(),...await chrome.storage.local.get(["jubaFollowUpLastPollAt","jubaFollowUpLastError","jubaFollowUpDesktopEnabled"])};if(m.type==="clearConnection"){const c=await config();if(c.pluginToken)try{await api("/api/v207/collector/logout",{method:"POST",body:{}})}catch(_){}await invalidate();return {ok:true}}throw new Error("UNKNOWN_MESSAGE")})().then(x=>reply({ok:true,data:x})).catch(e=>reply({ok:false,error:e.message,code:e.code,status:e.status,payload:e.payload}));return true});
async function ensureBackgroundAlarms(){
 await chrome.alarms.create("heartbeat",{delayInMinutes:1+Math.random(),periodInMinutes:5});
 await chrome.alarms.create("messageFlush",{delayInMinutes:0.5+Math.random()*0.5,periodInMinutes:1});
 await chrome.alarms.create("followUpPoll",{delayInMinutes:0.5+Math.random()*0.25,periodInMinutes:1});
}
chrome.runtime.onInstalled.addListener(()=>{void ensureBackgroundAlarms();void installationId();void flush();void followUpPoll().catch(()=>{})});
chrome.runtime.onStartup.addListener(()=>{void ensureBackgroundAlarms();void flush();void followUpPoll().catch(()=>{})});
void ensureBackgroundAlarms();
chrome.alarms.onAlarm.addListener(async a=>{if(a.name==="messageFlush"){void flush();return}if(a.name==="followUpPoll"){void followUpPoll().catch(()=>{});return}if(a.name!=="heartbeat")return;const c=await config();if(!c.pluginToken||!c.pluginSessionId||!c.deviceId||Number(c.expiresAt)<Date.now())return;try{await api("/api/v207/collector/heartbeat",{method:"POST",body:{}})}catch(e){if(e.status!==401)console.warn("JubaOpen heartbeat",e)}});
