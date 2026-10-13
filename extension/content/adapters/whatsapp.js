"use strict";
window.JubaAdapters=window.JubaAdapters||{};
const WA_ATTRS=["data-id","data-jid","data-lid","data-user","data-contact-id","data-chat-id","href","title","aria-label"];
function waDecode(v){try{return decodeURIComponent(String(v||""))}catch(_){return String(v||"")}}
function waAnyJid(v){const t=waDecode(v);const m=t.match(/([0-9]{5,24})(?::[0-9]+)?@(c\.us|s\.whatsapp\.net|lid|g\.us|broadcast)/i);if(!m)return "";let domain=m[2].toLowerCase();if(domain==="s.whatsapp.net")domain="c.us";return m[1]+"@"+domain}
function waDirectJid(v){const j=waAnyJid(v);return /@(c\.us|lid)$/.test(j)?j:""}
const WA_INVALID_NAME=/^(个人主页详情|联系人信息|联系方式|个人资料|群组信息|点击查看联系人信息|contact info(?:rmation)?|profile (?:details|info)|group info|click to view contact info|view contact info)$/i;
function waSafeName(v){const x=String(v||"").trim().replace(/\s+/g," ").slice(0,200);return x&&!WA_INVALID_NAME.test(x)?x:""}

const WA_BRIDGE_ID="jubaopen-wa-page-snapshot-v1";
let waBridgeRequestAt=0;
function waPageSnapshot(){
 const now=Date.now();
 if(now-waBridgeRequestAt>900){waBridgeRequestAt=now;try{window.dispatchEvent(new CustomEvent("jubaopen-wa-request"))}catch(_){}}
 const node=document.getElementById(WA_BRIDGE_ID);if(!node)return null;
 try{
  const x=JSON.parse(node.getAttribute("content")||"{}");
  if(![1,2,3,4,5,6,7,8,9,10].includes(Number(x?.v))||!Number.isFinite(Number(x.at))||now-Number(x.at)>15000)return null;
  const ownJid=waDirectJid(x.ownJid),chatJid=waAnyJid(x.chatJid),messages={},contactIdentityAliases=Array.isArray(x.contactIdentityAliases)?x.contactIdentityAliases.slice(0,8).map(a=>{const j=waDirectJid(a?.identityValue);return j?{identityType:j.endsWith("@lid")?"whatsapp_lid":"whatsapp_jid",identityValue:j,evidence:a?.evidence==="wa-chat-contact-model"?a.evidence:""}:null}).filter(a=>a&&a.evidence):[];
  if(x.messages&&typeof x.messages==="object")for(const [id,m] of Object.entries(x.messages).slice(0,600)){if(!id||!m||typeof m!=="object")continue;const at=Number(m.at),peer=waAnyJid(m.peer);const translation=m.translation&&typeof m.translation==="object"&&m.translation.visible!==false&&typeof m.translation.text==="string"&&m.translation.text.trim()?{text:m.translation.text.trim().slice(0,65536),source:String(m.translation.source||"wa-page-probe").slice(0,120),confidence:["high","medium","low"].includes(m.translation.confidence)?m.translation.confidence:"high",visible:true}:null;messages[String(id).slice(0,500)]={at:Number.isFinite(at)&&at>0?at:null,fromMe:typeof m.fromMe==="boolean"?m.fromMe:null,text:typeof m.text==="string"?m.text.slice(0,65536):null,type:String(m.type||"").slice(0,40),peer,source:["active-chat-model","active-chat-react-model"].includes(m.source)?m.source:"",...(translation?{translation}:{})}}
  const visibleRows=Array.isArray(x.visibleRows)?x.visibleRows.slice(0,100).map(r=>({jid:waDirectJid(r?.jid),name:waSafeName(r?.name),source:String(r?.source||"").slice(0,40)})).filter(r=>r.jid):[];
   return {ownJid,chatJid,contactIdentityAliases,visibleRows,status:String(x.status||"").slice(0,40),errorCode:String(x.errorCode||"").slice(0,40),open:!!x.open,displayName:waSafeName(x.displayName),phone:String(x.phone||"").trim().slice(0,64),avatarUrl:(()=>{const v=String(x.avatarUrl||"");if(/^data:image\/(?:jpeg|jpg|png|webp);base64,/i.test(v))return v.length<=350000?v:"";return /^(https:|blob:)/.test(v)&&v.length<=4096?v:""})(),isGroup:!!x.isGroup,source:String(x.source||"page-bridge").slice(0,80),bridgeVersion:Number(x.v),identityEvidence:{storeChat:!!x.identityEvidence?.storeChat,storeMessage:!!x.identityEvidence?.storeMessage,reactMain:!!x.identityEvidence?.reactMain,unanimousMessagePeer:!!x.identityEvidence?.unanimousMessagePeer,source:String(x.identityEvidence?.source||x.source||"").slice(0,40)},at:Number(x.at),messages,messageStats:{chatModelCount:Number(x.messageStats?.chatModelCount)||0,acceptedModelCount:Number(x.messageStats?.acceptedModelCount)||0,reactModelCount:Number(x.messageStats?.reactModelCount)||0,rejectedNoStableId:Number(x.messageStats?.rejectedNoStableId)||0,rejectedPeer:Number(x.messageStats?.rejectedPeer)||0,rejectedDirection:Number(x.messageStats?.rejectedDirection)||0,translationCount:Number(x.messageStats?.translationCount)||0,explicitNodeCount:Number(x.messageStats?.explicitNodeCount)||0,combinedNodeCount:Number(x.messageStats?.combinedNodeCount)||0,translationCandidateRoots:Number(x.messageStats?.translationCandidateRoots)||0}};
 }catch(_){return null}
}
function waPeerFromMessageId(value){
 const raw=waDecode(value);let m=raw.match(/(?:^|_)(?:true|false)_([0-9]{7,20})(?:@(?:c\.us|s\.whatsapp\.net))?(?:_|$)/i);
 if(!m)m=raw.match(/(?:^|_)([0-9]{7,20})@(?:c\.us|s\.whatsapp\.net)(?:_|$)/i);
 return m?m[1]+"@c.us":"";
}
// Prefer the legacy conversation panel; role-main fallback must own one chat header.
function waMainPanel(){
 const legacy=document.querySelector("#main,[data-testid='conversation-panel-wrapper']");if(legacy)return legacy;
 const panels=[...document.querySelectorAll("[role='main']")].filter(n=>!n.closest?.("#jubaopen-interaction-host,[data-juba-owned]")&&n.querySelectorAll("header,[data-testid='conversation-header']").length===1);
 return panels.length===1?panels[0]:null;
}
function waVisibleMainHeader(){
 const main=waMainPanel();if(!main)return null;
 const list=[...main.querySelectorAll("header,[data-testid='conversation-header']")];return list.find(h=>{try{const b=h.getBoundingClientRect();return b.width>50&&b.height>10}catch(_){return true}})||list[0]||null;
}
function waPhone(v){const d=String(v||"").replace(/[^0-9]/g,"");return d.length>=7&&d.length<=20?d+"@c.us":""}
function waValues(root,deep=true){const out=[];if(!root)return out;const nodes=[root];if(deep)nodes.push(...root.querySelectorAll("[data-id],[data-jid],[data-lid],[data-user],[data-contact-id],[data-chat-id],[href],[title],[aria-label]"));for(const el of nodes)for(const a of WA_ATTRS){const v=el.getAttribute?.(a);if(v)out.push(v)}return out}
function waJidsFrom(root,deep=true){const found=[];for(const v of waValues(root,deep)){const j=waAnyJid(v);if(j&&!found.includes(j))found.push(j)}return found}
function waFiberValues(root){const found=[];if(!(root instanceof Element))return found;const seen=new WeakSet();const add=v=>{const j=waAnyJid(typeof v==="string"?v:(v?._serialized||v?.serialized||v?.user&&v?.server?`${v.user}@${v.server}`:""));if(j&&!found.includes(j))found.push(j)};const walk=(v,depth)=>{if(v==null||depth>7)return;if(typeof v==="string"||typeof v==="number"){add(v);return}if(typeof v!=="object"||seen.has(v))return;seen.add(v);add(v);for(const k of ["id","_serialized","serialized","__x_id","wid","jid","userJid","remoteJid","peerId","contactId","chatId","phoneNumber","__x_phoneNumber","contact","chat","peer","remote","item","model","data","children","key"]){try{walk(v[k],depth+1)}catch(_){}}};for(const el of [root,...root.querySelectorAll("*")].slice(0,350)){for(const k of Object.getOwnPropertyNames(el)){if(k.startsWith("__reactFiber$")||k.startsWith("__reactProps$")||k.startsWith("__reactContainer$")){try{let f=el[k];for(let i=0;f&&i<12;i++,f=f.return){walk(f.key,0);walk(f.memoizedProps,0);walk(f.pendingProps,0);walk(f.memoizedState,0);walk(f.stateNode,0);walk(f.child?.memoizedProps,0);walk(f.sibling?.memoizedProps,0);walk(f.alternate?.memoizedProps,0)}}catch(_){}}}}return found}
function storageJid(store){try{for(let i=0;i<store.length;i++){const k=store.key(i)||"";if(!/(wid|jid|user|me|auth|account|registration)/i.test(k))continue;const j=waDirectJid(store.getItem(k));if(j)return j}}catch(_){}return ""}
function waOwnIdentity(){const bridge=waPageSnapshot();if(bridge?.ownJid)return bridge.ownJid;for(const sel of ["[data-own-jid]","[data-me-jid]","[data-self-jid]","[data-testid='profile-drawer']","[data-testid='drawer-left']"]){const el=document.querySelector(sel);const j=waJidsFrom(el).find(x=>/@(c\.us|lid)$/.test(x));if(j)return j}for(const box of document.querySelectorAll("[role='dialog'],aside")){if(!/(profile|个人资料|profil|perfil|профил|الملف)/i.test((box.innerText||"").slice(0,500)))continue;const j=waJidsFrom(box).find(x=>/@(c\.us|lid)$/.test(x))||waPhone(box.querySelector("a[href^='tel:']")?.getAttribute("href"));if(j)return j}return storageJid(localStorage)||storageJid(sessionStorage)}
function waVisibleConversationRows(){
 const pane=document.querySelector("#pane-side");if(!pane)return [];
 const cells=[...pane.querySelectorAll("[data-testid='cell-frame-container']")],seeds=cells.length?cells:[...pane.querySelectorAll("[role='listitem'],[role='row']")],rows=[],seen=new Set(),own=waOwnIdentity();
 for(const seed of seeds){const row=seed.matches?.("[data-testid='cell-frame-container']")?seed:(seed.closest("[data-testid='cell-frame-container']")||seed);if(seen.has(row)||row.closest("#jubaopen-interaction-host"))continue;seen.add(row);let rect;try{rect=row.getBoundingClientRect()}catch(_){continue}if(rect.width<150||rect.height<38||rect.height>150||rect.bottom<=0||rect.top>=innerHeight)continue;
  try{const bridgeJid=waDirectJid(row.getAttribute?.("data-juba-wa-row-jid"));const candidates=[bridgeJid,...waJidsFrom(row),...waFiberValues(row)].filter(Boolean),attributeValues=[];for(const element of [row,...row.querySelectorAll("[title],[aria-label]")]){if(!(element instanceof Element))continue;const value=element.getAttribute("title")||element.getAttribute("aria-label")||"";if(value)attributeValues.push(value)}for(const value of attributeValues){const jid=waDirectJid(value);if(jid)candidates.push(jid)}
   const jid=candidates.map(waAnyJid).find(x=>x&&x!==own&&/@(c\.us|lid)$/.test(x));if(jid)rows.push({element:row,externalConversationId:jid})
  }catch(_){/* One malformed/recycled WA row must never abort the remaining visible rows. */}
 }
 return rows;
}
function waSelectedRows(){const selectors=["#pane-side [aria-selected='true']","#pane-side [data-selected='true']","#pane-side [role='row'][aria-current='true']","#pane-side [role='listitem'][aria-current='true']"];const rows=[];for(const s of selectors)for(const el of document.querySelectorAll(s))if(!rows.includes(el))rows.push(el);return rows}
function waConversationCandidates(header){const own=waOwnIdentity(),weighted=[];const add=(j,w,source)=>{j=waAnyJid(j);if(!j||j===own||/@broadcast$/.test(j))return;weighted.push({jid:j,w,source})};const bridge=waPageSnapshot();if(bridge?.chatJid)add(bridge.chatJid,1000,bridge.source||"page-bridge");const route=(location.href.match(/(?:chat|phone)=([^&]+)/)||[])[1];if(route)add(route,100,"route");for(const row of waSelectedRows()){waJidsFrom(row).forEach(j=>add(j,90,"selected-row"));waFiberValues(row).forEach(j=>add(j,85,"selected-fiber"))}waJidsFrom(header).forEach(j=>add(j,80,"header"));waFiberValues(header).forEach(j=>add(j,75,"header-fiber"));for(const el of document.querySelectorAll("#main .message-in[data-id],#main .message-out[data-id],#main .message-in [data-id],#main .message-out [data-id]")){const raw=el.getAttribute("data-id");add(raw,55,"message-id");}const score={};for(const x of weighted){score[x.jid]=(score[x.jid]||0)+x.w}return Object.entries(score).sort((a,b)=>b[1]-a[1]).map(([jid,value])=>({jid,score:value,sources:weighted.filter(x=>x.jid===jid).map(x=>x.source)}))}
function waHeaderName(h){if(!(h instanceof Element))return "";for(const el of h.querySelectorAll("[data-testid='conversation-info-header-chat-title'],[title],span[dir='auto']")){const v=waSafeName(el.getAttribute("title")||el.textContent);if(v&&!/^(online|typing|last seen|在线|正在输入)/i.test(v))return v.slice(0,200)}return ""}
function waHeaderPhone(h,name,jid){const tel=document.querySelector("#main a[href^='tel:'],[role='dialog'] a[href^='tel:'],aside a[href^='tel:']")?.getAttribute("href")||"";let p=(tel.match(/\+?[0-9][0-9 ()-]{6,}/)||[])[0]||"";if(!p){const candidates=[name,...(h?.innerText||"").split("\n")];p=candidates.find(x=>/^\+?[0-9][0-9 ()-]{6,}$/.test(x.trim()))||""}if(!p&&jid.endsWith("@c.us"))p="+"+jid.split("@")[0];return p.trim()}
const WA_FOREIGN_CONTENT="[data-testid*='quoted' i],[data-testid*='reply-preview' i],[data-juba-owned],[data-juba-translation],#jubaopen-interaction-host";
const waRootIds=new WeakMap();
// Parse the entire remote field, never select a numeric suffix from a malformed JID.
function waParseMessageId(value){
 const raw=String(value||"");if(raw.length>500)return null;
 const decoded=waDecode(raw),m=decoded.match(/^(?:msg_)?(true|false)_([^_\s]+)_([^\s\x00-\x1f\x7f]+)$/i);if(!m)return null;
 const remote=m[2].match(/^([0-9]{5,24})(?::[0-9]{1,5})?@(c\.us|s\.whatsapp\.net|lid)$/i);
 const group=m[2].match(/^([0-9]{5,24}(?:-[0-9]{5,24})?)@g\.us$/i);
 if(!remote&&!group)return null;
 const peer=remote?remote[1]+"@"+(remote[2].toLowerCase()==="s.whatsapp.net"?"c.us":remote[2].toLowerCase()):group[1]+"@g.us";
 return {peer,fromMe:m[1].toLowerCase()==="true",raw};
}
function waSerializedId(v){return !!waParseMessageId(v)}
function waMessagePeer(v){return waParseMessageId(v)?.peer||""}
// Structural signatures use a fixed vocabulary only: no raw characters, numbers or tokens.
function waIdFormatSummary(values){const counts={};for(const value of values){const raw=String(value||""),x=waDecode(raw),m=x.match(/^(?:msg_)?(true|false)_([^_\s]+)_(.*)$/i);let key;
 if(raw.length>500)key="overlength";
 else if(m){const at=m[2].lastIndexOf("@"),user=at<0?m[2]:m[2].slice(0,at),domain=at<0?"":m[2].slice(at+1).toLowerCase();key=["serialized",raw===x?"plain":"encoded",/^[0-9]+$/.test(user)?"numeric-user":/^[0-9]+:[0-9]+$/.test(user)?"device-user":/^[0-9]+-[0-9]+$/.test(user)?"hyphen-user":"other-user",["c.us","s.whatsapp.net","lid","g.us"].includes(domain)?domain:at<0?"no-domain":"other-domain",m[3]?"token-present":"token-empty",waSerializedId(raw)?"accepted":"rejected"].join("/")}
 else key=/^(?:msg_)?(?:true|false)[_-]/i.test(x)?"fromme-prefix-other-layout":x.includes("@")?"jid-without-serialized-layout":"opaque-or-ui-id";
 counts[key]=(counts[key]||0)+1;}return counts;}
// ID carriers can wrap the bubble rather than occur inside it. Never reuse a
// cached ID across virtualized DOM recycling; never ascend into a multi-bubble carrier.
function waRawMessageId(el){
 const read=n=>n?.getAttribute?.("data-id")||"";
 const ids=[el,...el.querySelectorAll("[data-id]")].filter(n=>!n.closest?.(WA_FOREIGN_CONTENT)).map(read).filter(waSerializedId);
 const unique=[...new Set(ids)];if(unique.length)return unique.length===1?unique[0]:"";
 for(let n=el.parentElement,depth=0;n&&depth<5;depth++,n=n.parentElement){
  if(n.id==="main"||n.matches?.("[data-testid='conversation-panel-wrapper'],[role='main']"))break;
  if(n.closest?.(WA_FOREIGN_CONTENT))return "";
  const id=read(n);if(!waSerializedId(id))continue;
  const bubbles=[...n.querySelectorAll(".message-in,.message-out")].filter(x=>!x.closest?.(WA_FOREIGN_CONTENT));
  if(bubbles.length!==1||bubbles[0]!==el)return "";
  const all=[...new Set([id,...[...n.querySelectorAll("[data-id]")].filter(x=>!x.closest?.(WA_FOREIGN_CONTENT)).map(read).filter(waSerializedId)])];
  return all.length===1?id:"";
 }
 return "";
}
function waMessageRoots(){const main=waMainPanel();if(!main)return [];const roots=[],seen=new Set(),ids=new Set();for(const node of main.querySelectorAll(".message-in,.message-out,[data-testid='msg-container'],[data-id]")){if(node.closest?.(WA_FOREIGN_CONTENT))continue;const el=node.closest?.(".message-in,.message-out")||node.closest?.("[data-testid='msg-container']")||node;if(!main.contains(el)||seen.has(el))continue;seen.add(el);const id=waRawMessageId(el);if(!id||ids.has(id))continue;
 // Do not emit an outer carrier in addition to its nested semantic bubble.
 const nested=[...el.querySelectorAll(".message-in,.message-out")].filter(x=>!x.closest?.(WA_FOREIGN_CONTENT));if(nested.length)continue;
 ids.add(id);roots.push(el)}return roots.slice(-500)}
function waStructureDiagnostics(){
 const main=waMainPanel();if(!main)return {scanScope:"none",rawBubbleCount:0,rawIdCarrierCount:0,validIdCarrierCount:0,invalidIdCarrierCount:0,bridgeMessageCount:Object.keys(waPageSnapshot()?.messages||{}).length,extractionCode:"SCAN_SCOPE_MISSING"};
 const raw=[...main.querySelectorAll(".message-in,.message-out,[data-testid='msg-container']")].filter(n=>!n.closest?.(WA_FOREIGN_CONTENT)),carriers=[...main.querySelectorAll("[data-id]")].filter(n=>!n.closest?.(WA_FOREIGN_CONTENT)),valid=carriers.filter(n=>waSerializedId(n.getAttribute("data-id"))).length,roots=waMessageRoots();
 return {idFormatSummary:waIdFormatSummary(carriers.map(n=>n.getAttribute("data-id"))),scanScope:main.id==="main"?"legacy-main":main.getAttribute?.("data-testid")==="conversation-panel-wrapper"?"conversation-panel":"role-main",rawBubbleCount:raw.length,rawIdCarrierCount:carriers.length,validIdCarrierCount:valid,invalidIdCarrierCount:carriers.length-valid,bridgeMessageCount:Object.keys(waPageSnapshot()?.messages||{}).length,extractionCode:roots.length?"DOM_IDS_READY":valid?"ID_BINDING_REJECTED":carriers.length?"MESSAGE_ID_FORMAT_UNSUPPORTED":raw.length?"MESSAGE_IDS_NOT_EXPOSED":"NO_MESSAGE_NODES"};
}
function waModelRows(){
 const b=waPageSnapshot(),state=waContextState(),context=state.context;if(!context||!b||b.chatJid!==context.chatJid)return [];const accepted=new Set([context.chatJid,...(b.contactIdentityAliases||[]).map(a=>a.identityValue)]),rows=[];
 for(const [id,m] of Object.entries(b.messages||{})){const parsed=waParseMessageId(id),peer=m.peer||parsed?.peer||"";if(!parsed||!accepted.has(peer)||typeof m.fromMe!=="boolean"||parsed.fromMe!==m.fromMe)continue;const text=waCleanText(m.text||""),kind=String(m.type||"").toLowerCase(),map={chat:"text",image:"image",video:"video",audio:"audio",ptt:"audio",document:"file",sticker:"sticker",location:"location",vcard:"contact"},type=map[kind]||(text?"text":"unknown");if(!text&&type==="unknown")continue;rows.push({id,source:m.source||"active-chat-model",direction:m.fromMe?"outbound":"inbound",text,type,occurred:m.at?(Number(m.at)<1e12?Number(m.at)*1000:Number(m.at)):null,translation:m.translation||null})}return rows.slice(-500)
}
function waContextState(){
 const b=waPageSnapshot(),h=waVisibleMainHeader();
 if(!h)return {code:"NO_OPEN_CHAT",context:null,evidence:"none"};
 const own=b?.ownJid||waOwnIdentity();if(!own)return {code:"ACCOUNT_IDENTITY_PENDING",context:null,evidence:"none"};
 const selected=[...new Set(waSelectedRows().flatMap(r=>[r.getAttribute?.("data-juba-wa-row-jid"),...waJidsFrom(r,false)]).map(waAnyJid).filter(j=>j&&j!==own))];
 if(selected.length>1)return {code:"SELECTED_CHAT_AMBIGUOUS",context:null,evidence:"selected-row-conflict"};
 const messagePeers=[...new Set(waMessageRoots().map(el=>waMessagePeer(waRawMessageId(el))).filter(j=>j&&j!==own&&!/@broadcast$/.test(j)))];
 if(messagePeers.length>1)return {code:"MESSAGE_CHAT_AMBIGUOUS",context:null,evidence:"stable-message-id-conflict"};
 // A unanimous remote JID parsed from one or more valid WhatsApp stable message IDs is strong
 // conversation evidence. Titles, phone-looking text and geometry are never identity evidence.
 const messageJid=messagePeers.length===1?messagePeers[0]:"";
 const jid=b?.chatJid||selected[0]||messageJid||"";
 if(!jid||jid===own)return {code:"CHAT_IDENTITY_PENDING",context:null,evidence:"no-stable-jid"};
 const accepted=new Set([jid,...(b?.chatJid===jid?b.contactIdentityAliases||[]:[]).map(a=>a.identityValue)]);
 if(selected[0]&&!accepted.has(selected[0]))return {code:"SELECTED_CHAT_MISMATCH",context:null,evidence:"selected-vs-bridge"};
 if(messageJid&&!accepted.has(messageJid))return {code:"MESSAGE_CHAT_MISMATCH",context:null,evidence:"message-vs-context"};
 const source=b?.chatJid?`bridge-v${b.bridgeVersion||"legacy"}`:selected[0]?"selected-stable-jid":"unanimous-stable-message-id";
 const name=waHeaderName(h),context={signature:JSON.stringify([own,jid,name]),ownJid:own,chatJid:jid,identitySource:source};
 return {code:"READY",context,evidence:source,messagePeerCount:messagePeers.length};
}
function waContext(){return waContextState().context}
function waDiagnostics(){const state=waContextState(),b=waPageSnapshot(),roots=waMessageRoots(),context=state.context,accepted=new Set(context?[context.chatJid,...(b?.chatJid===context.chatJid?b.contactIdentityAliases||[]:[]).map(a=>a.identityValue)]:[]),domEligible=context?roots.filter(el=>accepted.has(waMessagePeer(waRawMessageId(el)))).length:0,modelEligible=context&&typeof waModelRows==="function"?waModelRows().length:0,st=b?.messageStats||{};return {...waStructureDiagnostics(),platform:"whatsapp",phase:state.code,contextCode:state.code,probeReady:!!b,probeStatus:b?.status||"BRIDGE_UNAVAILABLE",ownIdentityReady:!!(b?.ownJid||waOwnIdentity()),chatIdentityReady:!!context,accountConfidence:(b?.ownJid||waOwnIdentity())?"stable":"none",conversationConfidence:context?"verified":"none",conversationIdentitySource:context?.identitySource||state.evidence||"none",bridgeVersion:Number(b?.bridgeVersion)||0,stableMessagePeerCount:Number(state.messagePeerCount)||0,messageCount:roots.length,eligibleMessageCount:modelEligible||domEligible,blockedMessageCount:roots.length-domEligible,modelChatCount:st.chatModelCount||0,modelAcceptedCount:st.acceptedModelCount||0,reactModelCount:st.reactModelCount||0,modelRejectedPeer:st.rejectedPeer||0,modelRejectedId:st.rejectedNoStableId||0,modelRejectedDirection:st.rejectedDirection||0,probeTranslationCount:st.translationCount||0,probeExplicitNodeCount:st.explicitNodeCount||0,probeCombinedNodeCount:st.combinedNodeCount||0,probeTranslationCandidateRoots:st.translationCandidateRoots||0,messageSource:modelEligible?(st.reactModelCount?"current-chat-model+react":"active-chat-model"):domEligible?"dom-stable-id":"none",route:"active-chat",contextVersion:"wa-context-v260"}}

function waDirection(el,id){
 if(el.classList?.contains("message-out")||el.closest?.(".message-out,[data-testid*='outgoing' i]"))return {value:"outbound",source:"message-out"};
 if(el.classList?.contains("message-in")||el.closest?.(".message-in,[data-testid*='incoming' i]"))return {value:"inbound",source:"message-in"};
 const raw=waDecode(id),token=raw.match(/(?:^|_)(true|false)(?:_|$)/i);if(token)return {value:token[1].toLowerCase()==="true"?"outbound":"inbound",source:"serialized-fromMe"};
 if(/\bfrom_?me[=:]true\b/i.test(raw))return {value:"outbound",source:"serialized-fromMe"};if(/\bfrom_?me[=:]false\b/i.test(raw))return {value:"inbound",source:"serialized-fromMe"};
 const label=[el.getAttribute?.("aria-label"),el.querySelector?.("[aria-label]")?.getAttribute("aria-label"),el.querySelector?.("[data-pre-plain-text]")?.getAttribute("data-pre-plain-text")].filter(Boolean).join(" ");
 if(/(?:^|[\s,])(you|me|我|你)\s*:/i.test(label))return {value:"outbound",source:"accessible-sender"};
 const main=waMainPanel(),bubble=el.querySelector("[data-testid='msg-text'],span.selectable-text,[data-testid*='bubble' i]")?.parentElement||el;
 try{const mr=main.getBoundingClientRect(),br=bubble.getBoundingClientRect(),x=(br.left+br.right)/2,ratio=(x-mr.left)/Math.max(mr.width,1);if(ratio>=.61)return {value:"outbound",source:"panel-geometry"};if(ratio<=.49)return {value:"inbound",source:"panel-geometry"}}catch(_){}
 return null;
}
function waValidDateParts(v){if(!v)return null;const [y,m,d]=v,x=new Date(y,m-1,d);return y>=2000&&y<=2100&&x.getFullYear()===y&&x.getMonth()===m-1&&x.getDate()===d?v:null}
function waDateParts(raw){const x=String(raw||"").trim();if(!x)return null;let m=x.match(/(\d{4})\s*(?:年|[\/.\-])\s*(\d{1,2})\s*(?:月|[\/.\-])\s*(\d{1,2})\s*日?/);if(m)return waValidDateParts([+m[1],+m[2],+m[3]]);m=x.match(/(\d{1,2})\s*[\/.\-]\s*(\d{1,2})\s*[\/.\-]\s*(\d{2,4})/);if(!m)return null;let y=+m[3];if(y<100)y+=2000;const x1=+m[1],x2=+m[2];return waValidDateParts(x1>12?[y,x2,x1]:x2>12?[y,x1,x2]:[y,x2,x1])}
function waRelativeDate(raw){const t=String(raw||"").trim(),d=new Date();if(/^(today|今天|hoy|hoje|aujourd'hui|oggi|сегодня)$/i.test(t))return [d.getFullYear(),d.getMonth()+1,d.getDate()];if(/^(yesterday|昨天|ayer|ontem|hier|ieri|вчера)$/i.test(t)){d.setDate(d.getDate()-1);return [d.getFullYear(),d.getMonth()+1,d.getDate()]}return null}
function waNodeAttr(el,name){return el?.getAttribute?.(name)||el?.querySelector?.(`[${name}]`)?.getAttribute(name)||""}
function waDateBefore(el){const main=waMainPanel();if(!main)return null;try{const walker=document.createTreeWalker(main,NodeFilter.SHOW_ELEMENT),trail=[];let n;while((n=walker.nextNode())&&n!==el){if(n.contains?.(el))continue;for(const raw of [n.getAttribute?.("data-pre-plain-text"),n.getAttribute?.("aria-label"),n.textContent]){const t=String(raw||"").trim();if(t&&t.length<120&&(waRelativeDate(t)||waDateParts(t)))trail.push(t)}if(trail.length>160)trail.splice(0,trail.length-160)}for(let i=trail.length-1;i>=0;i--){const d=waRelativeDate(trail[i])||waDateParts(trail[i]);if(d)return d}}catch(_){}return null}
function waTime(el,model){const mat=Number(model?.at);if(Number.isFinite(mat)&&mat>0)return {value:mat<1e12?mat*1000:mat,source:"wa-message-model",confidence:"high",precision:"second"};const ts=waNodeAttr(el,"data-timestamp");if(/^\d{10,13}$/.test(ts)){const n=Number(ts);return {value:n<1e12?n*1000:n,source:"dom-timestamp",confidence:"high",precision:ts.length===10?"second":"millisecond"}}const pre=waNodeAttr(el,"data-pre-plain-text");let raw=pre,tm=raw.match(/(?:^|[^\d])(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM)?/i),dp=waRelativeDate(raw)||waDateParts(raw);if(!tm){raw=[el.getAttribute?.("aria-label"),...[...el.querySelectorAll("[data-testid*='msg-meta'],[aria-label]")].map(x=>x.getAttribute("aria-label")||x.textContent||"")].filter(Boolean).join(" ");tm=raw.match(/(?:^|[^\d])(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM)?/i);dp=waRelativeDate(raw)||waDateParts(raw)}if(tm&&!dp)dp=waDateBefore(el);if(!tm||!dp)return {value:null,source:"unresolved",confidence:"low",precision:"unknown"};let hour=+tm[1];if(tm[3]){if(hour===12)hour=0;if(tm[3].toUpperCase()==="PM")hour+=12}if(hour>23||+tm[2]>59)return {value:null,source:"unresolved",confidence:"low",precision:"unknown"};const d=new Date(dp[0],dp[1]-1,dp[2],hour,+tm[2]);return {value:Number.isNaN(d.getTime())?null:d.getTime(),source:waDateParts(pre)?"pre-plain-text":"date-context",confidence:waDateParts(pre)?"high":"medium",precision:"minute"}}
const WA_TRANSLATION_SELECTOR="[data-juba-translation],[data-translation-text],[data-testid*='translated-text' i],[data-testid*='translation-text' i],[data-testid*='translat' i],[aria-label*='translated' i],[aria-label*='translation' i],[aria-label*='翻译'],[aria-label*='译文'],.immersive-translate-target-inner,[data-immersive-translate-translation],[data-immersive-translate-target-inner],[data-immersive-translate-translation-element-mark],[data-translation-element-mark],[class*='immersive-translate-target-inner'],[class*='immersive-translate-target-translation-block'],font[class*='immersive-translate']";
const WA_TRANSLATION_WRAPPER=".immersive-translate-target-wrapper,.immersive-translate-target-translation-block-wrapper,.immersive-translate-target-translation-theme-none,[data-immersive-translate-paragraph],[data-immersive-translate-walked],[data-immersive_translate_walked],[class*='immersive-translate-target-wrapper'],[class*='immersive-translate-target-translation-block-wrapper']";
function waCleanText(v){return String(v||"").replace(/[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\ufffc]/g,"").trim()}
function waTranslationScope(el,id){
 /* 210.2.57: translation extensions often inject a sibling just outside .message-in/.message-out.
    Ascend only while the carrier owns exactly this one stable WA message ID. Never cross into a
    row/list carrier containing another message, so translations cannot drift between bubbles. */
 let best=el;
 for(let n=el.parentElement,depth=0;n&&depth<6;depth++,n=n.parentElement){
  if(n.id==="main"||n.matches?.("[data-testid='conversation-panel-wrapper'],[role='main']"))break;
  if(n.closest?.("#jubaopen-interaction-host,[data-juba-owned]"))break;
  const ids=[...new Set([n,...n.querySelectorAll("[data-id]")].map(x=>x.getAttribute?.("data-id")||"").filter(waSerializedId))];
  if(ids.length>1)break;
  if(ids.length===1&&ids[0]!==id)break;
  const bubbles=[...n.querySelectorAll(".message-in,.message-out,[data-testid='msg-container']")].filter(x=>!x.closest?.("[data-testid*='quoted' i],[data-testid*='reply-preview' i],#jubaopen-interaction-host"));
  const foreign=bubbles.some(x=>x!==el&&!el.contains(x)&&waRawMessageId(x)&&waRawMessageId(x)!==id);
  if(foreign)break;
  best=n;
 }
 return best
}
function waNodeVisible(x){try{const st=getComputedStyle(x),box=x.getBoundingClientRect();return st.display!=="none"&&st.visibility!=="hidden"&&st.opacity!=="0"&&(box.width>0||box.height>0)}catch(_){return true}}
function waTranslationNodes(el,id){
 const scope=waTranslationScope(el,id),selector=`${WA_TRANSLATION_SELECTOR},${WA_TRANSLATION_WRAPPER}`,all=[];
 for(const x of [scope,...scope.querySelectorAll(selector)]){
  if(!x.matches?.(selector)||x.closest?.("[data-testid*='quoted' i],[data-testid*='reply-preview' i],[data-juba-owned],#jubaopen-interaction-host"))continue;
  const owner=x.closest?.(".message-in,.message-out,[data-testid='msg-container']");if(owner&&owner!==el&&!el.contains(owner))continue;
  if(!waNodeVisible(x))continue;
  if(scope!==el){try{const a=el.getBoundingClientRect(),b=x.getBoundingClientRect(),overlap=Math.min(a.right,b.right)-Math.max(a.left,b.left),nearY=b.top<=a.bottom+360&&b.bottom>=a.top-60;if(overlap<Math.min(28,Math.max(8,b.width*.15))||!nearY)continue}catch(_){continue}}
  all.push(x)
 }
 return all.filter(x=>!all.some(y=>y!==x&&x.contains(y)&&waCleanText(y.innerText||y.textContent)))
}
function waTexts(el,model,id){
 const translationNodes=waTranslationNodes(el,id),explicit=[];
 for(const x of translationNodes){const t=waCleanText(x.innerText||x.textContent);if(t&&!explicit.includes(t))explicit.push(t)}
 const candidates=[],combined=[];
 for(const x of el.querySelectorAll("[data-testid='msg-text'],span.selectable-text,[data-testid*='caption'],[data-testid*='document-title']")){
  if(x.closest?.(WA_FOREIGN_CONTENT))continue;
  const raw=waCleanText(x.innerText||x.textContent);if(raw&&!candidates.includes(raw))candidates.push(raw);
  const clone=x.cloneNode(true);for(const n of clone.querySelectorAll(`${WA_TRANSLATION_SELECTOR},${WA_TRANSLATION_WRAPPER}`))n.remove();const t=waCleanText(clone.innerText||clone.textContent);if(t&&!translationNodes.some(z=>z===x||z.contains(x))&&!candidates.includes(t))candidates.push(t)
 }
 const modelText=waCleanText(typeof model?.text==="string"?model.text:""),original=(modelText||candidates.find(t=>!explicit.includes(t))||"").slice(0,65536),translations=[];
 for(const t of explicit)if(t&&t!==original&&!original.includes(t)&&!translations.includes(t))translations.push(t);
 if(original)for(const value of candidates)if(value.length>original.length&&value.startsWith(original)){const tail=waCleanText(value.slice(original.length));if(tail&&tail!==original&&!translations.includes(tail)){translations.push(tail);combined.push(tail)}}
 if(modelText&&!translations.length){const others=candidates.filter(t=>t!==modelText&&!modelText.includes(t)&&!t.includes(modelText));if(others.length===1)translations.push(others[0])}
 const immersive=translationNodes.some(x=>x.matches?.(".immersive-translate-target-inner,[data-immersive-translate-translation],[data-immersive-translate-target-inner],[data-immersive-translate-translation-element-mark],[data-translation-element-mark],[class*='immersive-translate']")||x.closest?.(WA_TRANSLATION_WRAPPER));
 return {original,translation:translations.join("\n").slice(0,65536),translationSource:explicit.length?(immersive?"immersive-translate":"semantic-dom"):combined.length?"combined-original-suffix":translations.length?"model-anchored-difference":"none",translationScope:translationNodes.length?(waTranslationScope(el,id)===el?"bubble":"single-message-carrier"):"none",translationNodeCount:translationNodes.length,translationCandidateCount:candidates.length,combinedTranslationCount:combined.length}
}

function waType(el,text){if(el.querySelector("[data-testid*='sticker']"))return "sticker";if(el.querySelector("audio,[data-testid*='audio'],[data-testid*='ptt']"))return "audio";if(el.querySelector("video,[data-testid*='video']"))return "video";if(el.querySelector("[data-testid*='document'],a[download]"))return "file";if(el.querySelector("[data-testid*='location'],a[href*='maps.google']"))return "location";if(el.querySelector("[data-testid*='contact-card'],[data-testid*='vcard']"))return "contact";if(el.querySelector("img[src^='blob:'],[data-testid*='image']"))return "image";return text?"text":"unknown"}
function waConversationShell(){const h=waVisibleMainHeader(),selected=waSelectedRows();return {open:!!h,selected:!!selected.length,signature:selected.map(row=>{const direct=[...waJidsFrom(row),...waFiberValues(row)].map(waAnyJid).find(j=>/@(c\.us|lid|g\.us)$/.test(j));if(direct)return direct;const test=row.getAttribute?.("data-testid")||row.querySelector?.("[data-testid]")?.getAttribute("data-testid")||"";return String(test).slice(0,120)}).join("|")}}
window.JubaAdapters.whatsapp={code:"whatsapp",capabilities:window.JubaMessageProtocol.capabilities.whatsapp,matches:()=>location.hostname==="web.whatsapp.com",
 context:()=>waContext(),
 diagnostics:()=>waDiagnostics(),
 visibleConversations:()=>waVisibleConversationRows(),
 conversationShell:()=>waConversationShell(),
 account(){const j=waOwnIdentity();return j?{identityType:j.endsWith("@lid")?"whatsapp_lid":"whatsapp_jid",identityValue:j}:null},
 conversation(){const bridge=waPageSnapshot(),h=waVisibleMainHeader();if(!h&&!bridge?.chatJid)return null;const context=waContext();if(!context)return null;const jid=context.chatJid,best={sources:["validated-context"]};if(jid.endsWith("@g.us"))return {unsupported:true,reason:"暂不采集 WhatsApp 群组会话",externalConversationId:jid};if(!/@(c\.us|lid)$/.test(jid))return null;const name=waSafeName(bridge?.chatJid===jid&&bridge.displayName)||waSafeName(waHeaderName(h))||jid.split("@")[0],img=h?.querySelector("img[src]"),phone=(bridge?.chatJid===jid&&bridge.phone)||waHeaderPhone(h,name,jid),avatar=(bridge?.chatJid===jid&&bridge.avatarUrl)||img?.src||"";const aliases=(bridge?.chatJid===jid?bridge.contactIdentityAliases:[])||[];return {externalConversationId:jid,contactIdentityAliases:aliases,identity:{identityType:jid.endsWith("@lid")?"whatsapp_lid":"whatsapp_jid",identityValue:jid,aliases,displayName:name,phone,avatarUrl:avatar,metadata:{identitySources:best.sources,bridgeAgeMs:bridge?Date.now()-bridge.at:null}}}},
 messages(){const context=waContext();if(!context)return [];const bridge=waPageSnapshot(),models=bridge?.messages||{},modelRows=waModelRows(),byId=new Map();for(const [i,r] of modelRows.entries()){const n=window.JubaMessageProtocol.normalize({platform:"whatsapp",externalMessageId:r.id,clientEventId:"wa:"+r.id,direction:r.direction,senderType:r.direction==="outbound"?"agent":"contact",contentType:r.type,text:r.text||null,...(r.occurred?{occurredAt:r.occurred}:{}),translation:r.translation,metadata:{platformCode:"whatsapp",identityVersion:"wa-translation-observable-v259",visibleIndex:i,originalTimestamp:r.occurred,timestampResolved:!!r.occurred,timestampSource:"wa-message-model",timestampConfidence:r.occurred?"high":"low",timestampPrecision:r.occurred?"second":"unknown",directionSource:"wa-message-model",directionConfidence:"high",hasMedia:r.type!=="text"&&r.type!=="unknown"}});byId.set(String(r.id),n)}const rows=waMessageRoots().map((el,i)=>{const id=waRawMessageId(el);if(!id)return null;const peer=waMessagePeer(id);if(peer!==context.chatJid&&!((bridge?.contactIdentityAliases||[]).some(a=>a.identityValue===peer)))return null;const base=byId.get(String(id))||byId.get(waDecode(id))||null,model=models[id]||models[waDecode(id)]||models[id.replace(/^msg_/,"")]||null,d0=waDirection(el,id),d=typeof model?.fromMe==="boolean"?{value:model.fromMe?"outbound":"inbound",source:"wa-message-model"}:base?{value:base.direction,source:"wa-message-model"}:d0;if(!d)return null;const parsed=waParseMessageId(id);if(!parsed||d.value!==(parsed.fromMe?"outbound":"inbound"))return null;const texts=waTexts(el,model||{text:base?.text},id),clock=waTime(el,model),type=waType(el,texts.original),out=d.value==="outbound",translation=texts.translation?{text:texts.translation,source:"whatsapp-message-owned-"+texts.translationSource+"-v259",visible:true,confidence:"high"}:null;return {id,i,d,texts,clock,type,out,translation,base}}).filter(Boolean),ranks=new Map();for(const r of rows){let occurred=r.clock.value;if(occurred&&r.clock.precision==="minute"){const rank=ranks.get(occurred)||0;ranks.set(occurred,rank+1);occurred+=rank}const b=r.base,n=window.JubaMessageProtocol.normalize({platform:"whatsapp",externalMessageId:r.id,clientEventId:"wa:"+r.id,direction:b?.direction||r.d.value,senderType:b?.senderType||(r.out?"agent":"contact"),contentType:b?.contentType||r.type,text:b?.text||r.texts.original||null,...(b?.occurredAt?{occurredAt:b.occurredAt}:occurred?{occurredAt:occurred}:{}),translation:r.translation||b?.metadata?.translation||model?.translation||null,metadata:{...(b?.metadata||{}),platformCode:"whatsapp",identityVersion:"wa-translation-observable-v259",visibleIndex:r.i,originalTimestamp:b?.occurredAt||r.clock.value,timestampResolved:!!(b?.occurredAt||occurred),timestampSource:b?.metadata?.timestampSource||r.clock.source,timestampConfidence:b?.metadata?.timestampConfidence||r.clock.confidence,timestampPrecision:b?.metadata?.timestampPrecision||r.clock.precision,directionSource:b?.metadata?.directionSource||r.d.source,directionConfidence:b?.metadata?.directionConfidence||(r.d.source==="panel-geometry"?"medium":"high"),hasMedia:(b?.contentType||r.type)!=="text"&&(b?.contentType||r.type)!=="unknown",translationScope:r.texts.translationScope,translationNodeCount:r.texts.translationNodeCount,translationCandidateCount:r.texts.translationCandidateCount,combinedTranslationCount:r.texts.combinedTranslationCount,probeTranslationAvailable:!!(b?.metadata?.translation||model?.translation),translationDiagnosticVersion:"wa-v259"}});byId.set(String(r.id),n)}return [...byId.values()] }
};
