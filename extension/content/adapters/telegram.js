"use strict";
window.JubaAdapters=window.JubaAdapters||{};
function tgId(value){const text=String(value||"");return (text.match(/(?:user_id|userId|id)["'\s:=]+([1-9][0-9]{3,19})/i)||[])[1]||""}
function tgPeerToken(value){const x=String(value??"").trim();let m=x.match(/^(?:tg:)?(-?[1-9][0-9]{3,19})$/);if(m)return m[1];m=x.match(/(?:peer_id|peerId|user_id|userId)["'\s:=]+(-?[1-9][0-9]{3,19})/i);if(m)return m[1];m=x.match(/(?:#|\/)(-?[1-9][0-9]{3,19})(?:\b|\/|$)/);return m?m[1]:""}
function tgPeerFromRow(row){for(const a of ["data-peer-id","data-peer","data-user-id","href"]){const id=tgPeerToken(row.getAttribute?.(a));if(id)return id}for(const n of row.querySelectorAll?.("[data-peer-id],[data-peer],[data-user-id],a[href]")||[])for(const a of ["data-peer-id","data-peer","data-user-id","href"]){const id=tgPeerToken(n.getAttribute?.(a));if(id)return id}
 const seen=new WeakSet();let found="",budget=0;const walk=(v,d=0,k="")=>{if(found||v==null||d>7||budget++>2500)return;if(typeof v==="string"||typeof v==="number"){if(/^(peer_?id|peerId|user_?id|userId)$/i.test(k))found=tgPeerToken(v);return}if(typeof v!=="object"||seen.has(v))return;seen.add(v);for(const key of Object.keys(v)){if(["stateNode","return","child","sibling","ownerDocument"].includes(key))continue;try{walk(v[key],d+1,key)}catch(_){}if(found)return}};
 for(const n of [row,...row.querySelectorAll?.("*")||[]].slice(0,160))for(const key of Object.keys(n)){if(key.startsWith("__reactProps$")||key.startsWith("__reactFiber$")||/(peer|dialog|chat)/i.test(key)){try{walk(n[key])}catch(_){}}if(found)return found}return ""}
function tgVisibleConversationRows(){const root=document.querySelector("#column-left,#LeftColumn,.left-column");if(!root)return [];const candidates=[...root.querySelectorAll(".chatlist-chat,.ListItem,.Chat,[role='listitem'],[role='row'],a[href]")],out=[],used=new Set();for(const seed of candidates){let row=seed.closest(".chatlist-chat,.ListItem,.Chat,[role='listitem'],[role='row']")||seed,rect;try{rect=row.getBoundingClientRect()}catch(_){continue}if(used.has(row)||rect.width<150||rect.height<38||rect.height>150||rect.bottom<=0||rect.top>=innerHeight)continue;const id=tgPeerFromRow(row);if(!id)continue;used.add(row);row.setAttribute("data-juba-external-conversation-id","tg:"+id);out.push({element:row,externalConversationId:"tg:"+id})}return out}
function resolveMessageTime(el){
 const candidates=[el.getAttribute("data-timestamp"),el.querySelector("[data-timestamp]")?.getAttribute("data-timestamp"),el.getAttribute("datetime"),el.querySelector("time[datetime]")?.getAttribute("datetime")];
 for(const raw of candidates){if(raw==null||raw==="")continue;const n=Number(raw);if(Number.isFinite(n)){const ms=n<100000000000?n*1000:n;if(ms>0)return ms}const parsed=Date.parse(raw);if(Number.isFinite(parsed))return parsed}return null;
}
/* Telegram can be translated by the Immersive Translate browser extension. Its injected
 * nodes are presentation-only and must never become part of authoritative source text. */
const TG_NATIVE_TRANSLATION_SELECTOR="[data-juba-translation],[data-translation-text],[data-testid*='translated-text' i],[data-testid*='translation-text' i],.translated-text,.translation-text,.message-translation,.MessageTranslation,[class~='translated-message'],[class*='translated-text' i],[class*='translation-text' i]";
const TG_IMMERSIVE_INNER_SELECTOR=".immersive-translate-target-inner,[data-immersive-translate-target-inner],[data-immersive-translate-translation-element-mark]";
const TG_IMMERSIVE_WRAPPER_SELECTOR=".immersive-translate-target-wrapper,.immersive-translate-target-translation-block-wrapper,.immersive-translate-target-translation-theme-none,[class*='immersive-translate-target-wrapper'],[class*='immersive-translate-target-translation-block-wrapper'],[data-immersive-translate-paragraph],[data-immersive-translate-walked],[data-immersive_translate_walked]";
const TG_TRANSLATION_SELECTOR=TG_NATIVE_TRANSLATION_SELECTOR+","+TG_IMMERSIVE_INNER_SELECTOR+","+TG_IMMERSIVE_WRAPPER_SELECTOR;
function tgCleanText(value){return window.JubaMessageProtocol.clean(value)}
function tgVisible(node){if(!node||node.hidden||node.getAttribute?.("aria-hidden")==="true")return false;const style=node.getAttribute?.("style")||"";return !/(?:display\s*:\s*none|visibility\s*:\s*hidden)/i.test(style)}
function tgImmersiveTranslationNodes(source){
 /* Prefer deepest marked nodes. Selecting both a wrapper and its child would duplicate a translation. */
 const marked=[...source.querySelectorAll(TG_IMMERSIVE_INNER_SELECTOR)].filter(tgVisible),leaves=marked.filter(node=>!marked.some(other=>other!==node&&node.contains(other)));
 if(leaves.length)return leaves;
 const wrappers=[...source.querySelectorAll(TG_IMMERSIVE_WRAPPER_SELECTOR)].filter(tgVisible);
 return wrappers.filter(node=>!wrappers.some(other=>other!==node&&node.contains(other)));
}
function tgMessageParts(el){
 const source=el.querySelector(".text-content,.message-content,.Message_text,.translatable-message,.message-text,.text")||el;
 const immersive=tgImmersiveTranslationNodes(source),native=[...source.querySelectorAll(TG_NATIVE_TRANSLATION_SELECTOR)].filter(node=>tgVisible(node)&&!immersive.some(x=>x===node||x.contains(node)||node.contains(x)));
 const nodes=immersive.length?immersive:native,translations=[];
 for(const node of nodes){
  if(node===source||node.closest("button,[role='button']"))continue;
  const value=tgCleanText(node.innerText||node.textContent);if(value&&!translations.includes(value))translations.push(value);
 }
 const clone=source.cloneNode(true);
 /* Remove outermost injected wrappers first; querySelectorAll returns document order. */
 for(const node of [...clone.querySelectorAll(TG_TRANSLATION_SELECTOR)])if(!node.parentElement?.closest(TG_TRANSLATION_SELECTOR))node.remove();
 for(const node of clone.querySelectorAll("time,.time,.message-time,.MessageMeta,.message-meta,.status,.message-status,.reactions,.reply-markup,[aria-label*='read' i],[aria-label*='sent' i],[data-testid*='status']"))node.remove();
 const original=tgCleanText(clone.innerText||clone.textContent).replace(/\s*[\u25A0-\u25FF\uFFFD]?\s*\d{1,2}:\d{2}\s*$/u,"").trim().slice(0,65536);
 const translated=translations.filter(value=>value&&value!==original).join("\n").slice(0,65536),immersiveDetected=immersive.length>0;
 return {original,translation:translated?{text:translated,source:immersiveDetected?"immersive-translate-dom":"telegram-explicit-dom",visible:true,confidence:"high"}:null,translationEvidence:translated?{method:immersiveDetected?"injected-translation-node":"platform-translation-node",provider:immersiveDetected?"immersive-translate":"telegram",nodeCount:nodes.length}:null};
}
function tgMessageText(el){return tgMessageParts(el).original}

function tgOwnIdentity(){
 const selectors=["[data-testid='left-column'] [data-user-id][data-self='true']",".LeftMainHeader [data-user-id]",".sidebar-header [data-user-id]","[data-self-user-id]"];
 for(const sel of selectors)for(const el of document.querySelectorAll(sel)){const id=el.getAttribute("data-self-user-id")||el.getAttribute("data-user-id");if(/^[1-9][0-9]{3,19}$/.test(id||""))return id}
 for(const key of ["user_auth","auth_user","currentUser","current_user"]){let v="";try{v=localStorage.getItem(key)||""}catch(_){}const id=tgId(v);if(id)return id}return "";
}
function tgAvatarUrl(){
 // Telegram Web K uses #column-center; avatar-photo is the header image confirmed in the live DOM.
 const direct=document.querySelector("#column-center img.avatar-photo");
 const candidates=[];
 if(direct)candidates.push(direct);
 const roots=[...document.querySelectorAll("#column-center,#MiddleColumn,.chat-info,.topbar,.ChatHeader,.chat-header")];
 const seen=new Set(candidates);
 for(const root of roots){
  for(const el of root.querySelectorAll("img.avatar-photo,img, [style*='background'], .avatar, .Avatar, .peer-avatar, [class*='avatar']")){
   if(!seen.has(el)){seen.add(el);candidates.push(el)}
  }
 }
 for(const el of candidates){
  const style=getComputedStyle(el),rect=el.getBoundingClientRect();
  if(style.display==='none'||style.visibility==='hidden'||Number(style.opacity)===0||rect.width<16||rect.height<16)continue;
  let url='';
  if(el.tagName==='IMG')url=el.currentSrc||el.src||el.getAttribute('src')||'';
  if(!url){const srcset=el.getAttribute('srcset')||el.getAttribute('data-srcset')||'';if(srcset){const choices=srcset.split(',').map(x=>x.trim().split(/\s+/)[0]).filter(Boolean);url=choices[choices.length-1]||''}}
  if(!url){const bg=style.backgroundImage||'';const m=bg.match(/url\(["']?(.*?)["']?\)/i);if(m)url=m[1]}
  if(!url)url=el.getAttribute('data-src')||el.getAttribute('data-original')||'';
  if(url&&url!=='none'&&!/^data:image\/svg/i.test(url)){
   try{url=new URL(url,location.href).href}catch(_){}
   if(/^(https?:|blob:|data:image\/)/i.test(url))return url;
  }
 }
 return '';
}
window.JubaAdapters.telegram={code:"telegram",capabilities:window.JubaMessageProtocol.capabilities.telegram,matches:()=>location.hostname==="web.telegram.org",
 visibleConversations:()=>tgVisibleConversationRows(),
 account(){const id=tgOwnIdentity();return id?{identityType:"telegram_user_id",identityValue:id}:null},
 conversation(){const active=document.querySelector(".chat.active,.Chat.active,#column-center .chat-info,#MiddleColumn .chat-info");const title=document.querySelector("#column-center .peer-title,#column-center .chat-info .title,#column-center header [dir='auto'],#MiddleColumn .peer-title,.chat-info .title,.topbar .peer-title")?.textContent||"";const path=location.hash+location.pathname;const peer=(path.match(/(?:#|\/)(-?\d{3,})/)||[])[1]||active?.getAttribute("data-peer-id")||document.querySelector("[data-peer-id].active")?.getAttribute("data-peer-id");if(!peer)return null;if(String(peer).startsWith("-"))return {unsupported:true,reason:"暂不采集 Telegram 群组/频道会话",externalConversationId:"tg:"+peer};const avatar=tgAvatarUrl();return {externalConversationId:"tg:"+peer,identity:{identityType:"telegram_user_id",identityValue:String(peer),displayName:title,phone:"",avatarUrl:avatar}}},
 messages(){
  const selectors=["#column-center [data-message-id]","#column-center [data-mid]","#column-center .message-list-item","#column-center .Message","#MiddleColumn [data-message-id]","#MiddleColumn [data-mid]",".message-list-item[data-mid]",".Message[data-message-id]"];
  const roots=[],ids=new Set();
  for(const el of document.querySelectorAll(selectors.join(","))){
   const holder=el.matches("[data-message-id],[data-mid]")?el:el.querySelector("[data-message-id],[data-mid]");
   const id=holder?.getAttribute("data-message-id")||holder?.getAttribute("data-mid")||el.getAttribute("data-message-id")||el.getAttribute("data-mid");
   if(!id||ids.has(String(id)))continue;ids.add(String(id));roots.push({el,id:String(id)});
  }
  return roots.slice(-500).map(({el,id},i)=>{const out=el.classList.contains("is-out")||el.classList.contains("own")||el.classList.contains("out")||!!el.closest(".is-out,.own,.out,[data-is-out='true'],[data-own='true']");const parts=tgMessageParts(el),text=parts.original;const occurredAt=resolveMessageTime(el),observedAt=Date.now();return window.JubaMessageProtocol.normalize({platform:"telegram",externalMessageId:"tg:"+id,clientEventId:"tg:"+id,direction:out?"outbound":"inbound",senderType:out?"agent":"contact",contentType:text?"text":(el.querySelector("img,video,audio")?"unknown":"system"),text,...(occurredAt?{occurredAt}:{}),translation:parts.translation,metadata:{visibleIndex:i,observedAt,captureMode:"dom-history",historyBackfill:true,...(parts.translationEvidence?{translationEvidence:parts.translationEvidence}:{}),timestampResolved:!!occurredAt,timestampSource:occurredAt?"telegram-dom-attribute":"unresolved",timestampConfidence:occurredAt?"high":"low"}})});
 }};