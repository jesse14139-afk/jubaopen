"use strict";
(async()=>{
 const adapter=Object.values(window.JubaAdapters||{}).find(x=>x.matches());if(!adapter)return;
 window.JubaPanel.mount();
 let current="",seen=new Set(),verified=null,lastVerify=0,busy=false,failedSignature="",retryAfter=0;
 const call=(type,data)=>new Promise((resolve,reject)=>chrome.runtime.sendMessage({type,...data},r=>{if(r?.ok)resolve(r.data);else{const e=new Error(r?.error||"插件请求失败");e.code=r?.code;e.status=r?.status;e.payload=r?.payload;reject(e)}}));
 const errorText=e=>({
  FORBIDDEN:"当前用户缺少采集权限，请联系管理员检查角色授权。",
  ACCOUNT_NOT_AUTHORIZED:"当前登录的平台账号尚未登记，或未授权给当前用户。",
  ACCOUNT_IDENTITY_PENDING:"已检测到平台身份，但尚未登记。请复制下方标识交给管理员授权。",
  ACCOUNT_APPROVAL_PENDING:"已检测到当前平台账号，正在等待管理员审批。审批完成后请点击“重新检测”。",
  ACCOUNT_TEAM_NOT_AUTHORIZED:"平台身份已登记，但尚未授权给当前团队。",
  ACCOUNT_USER_NOT_AUTHORIZED:"平台身份已登记，但尚未授权给当前用户。",
  STABLE_ACCOUNT_IDENTITY_REQUIRED:"无法取得当前平台登录账号的稳定身份，请打开个人资料页后重试。",
  ACCOUNT_IDENTITY_CONFLICT:"当前平台身份存在重复登记，请联系管理员处理。",
  PLUGIN_UNAUTHORIZED:"插件授权已失效，请打开插件重新接入。",
  ACCOUNT_BINDING_REQUIRED:"当前插件实例尚未验证该平台账号。",
  ACCOUNT_IDENTITY_CHANGED:"平台登录账号已变化，请重新验证。",
  DEVICE_SCOPE_INVALID:"当前设备已停用或不属于授权团队。",
  DEVICE_USER_MISMATCH:"当前设备已分配给其他用户。",
  PLATFORM_NOT_FOUND:"当前平台未在系统中启用。"
 }[e?.code]||e?.message||"平台账号识别失败")+(e?.payload?.identityValue?"\n身份类型："+e.payload.identityType+"\n身份标识："+e.payload.identityValue+"\n请将以上信息交给管理员。":"");
 function reset(all=true){current="";seen=new Set();verified=null;lastVerify=0;window.__jubaConversationId=null;if(all){failedSignature="";retryAfter=0}}
 async function detect(account,force=false){
  const signature=account.identityType+":"+account.identityValue;
  if(!force&&verified?.signature===signature&&Date.now()-lastVerify<=180000)return verified;
  if(!force&&failedSignature===signature&&Date.now()<retryAfter)return null;
  current="";seen=new Set();window.__jubaConversationId=null;
  window.JubaPanel.status("正在验证当前平台账号…");
  try{
   const out=await call("api",{path:"/api/v207/collector/accounts/detect",options:{method:"POST",body:{platformCode:adapter.code,identityType:account.identityType,identityValue:account.identityValue}}});
   verified={signature,account,out:out.channelAccount};lastVerify=Date.now();failedSignature="";retryAfter=0;
   window.JubaPanel.status("账号已验证，等待打开会话");return verified;
  }catch(e){verified=null;failedSignature=signature;retryAfter=Date.now()+(e.status===401?60000:(e.status===403?600000:30000));if(e.code==="ACCOUNT_APPROVAL_PENDING"){const discovery=e.payload?.discoveryId?"\n审批单号："+e.payload.discoveryId:"";window.JubaPanel.status(errorText(e)+discovery,false,{label:"重新检测",run:async()=>{failedSignature="";retryAfter=0;await detect(account,true)}})}else window.JubaPanel.status(errorText(e),true);return null}
 }
 async function tick(){
  if(busy)return;busy=true;
  try{
   const account=await Promise.resolve(adapter.account());
   if(!account){reset(false);window.JubaPanel.status(adapter.code==="whatsapp"?"尚未取得 WhatsApp 本人稳定身份。请打开“设置 → 个人资料”，确保电话号码可见后保持页面打开再重试。":"尚未取得 Telegram 本人稳定身份。请打开设置/个人资料页后重试。",true);return}
   const v=await detect(account);if(!v)return;
   const conv=adapter.conversation();if(!conv){window.JubaPanel.status("账号已验证，请打开一个聊天会话");return}if(conv.unsupported){window.JubaPanel.status(conv.reason||"当前会话类型暂不支持");return}
   const key=v.signature+":"+conv.externalConversationId;
   if(key!==current){
    window.JubaPanel.status("正在识别当前聊天会话…");
    const out=await call("api",{path:"/api/v207/collector/conversations/resolve",options:{method:"POST",body:{platformCode:adapter.code,channelAccountId:v.out.channelAccountId,accountIdentity:account,externalConversationId:conv.externalConversationId,contactIdentity:conv.identity}}});
    current=key;seen=new Set();window.__jubaConversationId=out.conversation.conversation_id;await window.JubaPanel.load(out.contactId);
   }
   const messages=adapter.messages().filter(x=>!seen.has(x.externalMessageId));
   if(messages.length&&window.__jubaConversationId){messages.forEach(x=>x.conversationId=window.__jubaConversationId);await call("queueMessages",{messages});messages.forEach(x=>seen.add(x.externalMessageId))}
  }catch(e){if(e.status===401)reset();window.JubaPanel.status(errorText(e),true)}finally{busy=false}
 }
 const observer=new MutationObserver(()=>{clearTimeout(window.__jubaTimer);window.__jubaTimer=setTimeout(tick,700)});
 observer.observe(document.documentElement,{subtree:true,childList:true});setInterval(tick,5000);tick();
})();
