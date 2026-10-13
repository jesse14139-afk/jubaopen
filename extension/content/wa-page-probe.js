"use strict";
/* Runs in the WhatsApp MAIN world. Exposes a bounded snapshot of the active chat and
   already-loaded message models to the isolated extension world. No credentials are exported. */
(()=>{
 const SNAPSHOT_ID="jubaopen-wa-page-snapshot-v1";
 const state={require:null,last:"",seq:0,modules:[],moduleScanAt:0};
 const jidOf=value=>{
  const seen=new WeakSet();
  const scan=(v,depth=0)=>{
   if(v==null||depth>3)return "";
   if(typeof v==="string"||typeof v==="number"){
    const s=String(v),m=s.match(/([0-9]{5,24})(?::[0-9]+)?@(c\.us|s\.whatsapp\.net|lid|g\.us|broadcast)/i);
    if(!m)return "";return m[1]+"@"+(m[2].toLowerCase()==="s.whatsapp.net"?"c.us":m[2].toLowerCase());
   }
   if(typeof v!=="object"||seen.has(v))return "";seen.add(v);
   for(const k of ["_serialized","serialized","id","wid","jid","userJid","remoteJid","peerId","contactId","chatId","__x_id"]){
    try{const x=v[k],j=scan(x,depth+1);if(j)return j}catch(_){}
   }
   try{if(v.user&&v.server)return scan(String(v.user)+"@"+String(v.server),depth+1)}catch(_){}
   return "";
  };return scan(value);
 };
 const text=value=>typeof value==="string"?value.trim().replace(/\s+/g," ").slice(0,200):"";
 const invalidName=/^(个人主页详情|联系人信息|联系方式|个人资料|群组信息|点击查看联系人信息|contact info(?:rmation)?|profile (?:details|info)|group info|click to view contact info|view contact info)$/i;
 const safeName=value=>{const v=text(value);return v&&!invalidName.test(v)?v:""};
 const mainPanel=()=>{const legacy=document.querySelector("#main,[data-testid='conversation-panel-wrapper']");if(legacy)return legacy;const panels=[...document.querySelectorAll("[role='main']")].filter(n=>!n.closest?.("#jubaopen-interaction-host,[data-juba-owned]")&&n.querySelectorAll("header,[data-testid='conversation-header']").length===1);return panels.length===1?panels[0]:null};
 const mainNodes=selector=>[...(mainPanel()?.querySelectorAll(selector)||[])];
 const visibleHeader=()=>{
  const main=mainPanel();
  if(!main)return null;
  const hs=[...main.querySelectorAll("header,[data-testid='conversation-header']")];
  return hs.find(h=>{try{const b=h.getBoundingClientRect();return b.width>50&&b.height>10}catch(_){return true}})||hs[0]||null;
 };
 const headerName=()=>{const h=visibleHeader();if(!h)return "";for(const e of h.querySelectorAll("[data-testid='conversation-info-header-chat-title'],[title],span[dir='auto']")){const v=safeName(e.getAttribute("title")||e.textContent);if(v&&!/^(online|typing|last seen|在线|正在输入)/i.test(v))return v}return ""};
 const avatar=()=>{const h=visibleHeader(),src=h?.querySelector("img[src]")?.src||"";return /^(https:|blob:|data:image\/)/.test(src)?src.slice(0,4096):""};
 const moduleValues=()=>{
  const now=Date.now();if(state.modules.length&&now-state.moduleScanAt<10000)return state.modules;
  const values=[],add=v=>{if(v&&(typeof v==="object"||typeof v==="function")&&!values.includes(v))values.push(v)};
  for(const k of ["Store","WAWebCollections","Debug","WPP"]){try{add(window[k]);add(window[k]?.Store);add(window[k]?.whatsapp);add(window[k]?.whatsapp?.Store)}catch(_){}}
  let req=state.require;
  if(!req){for(const key of Object.keys(window).filter(k=>/^webpackChunk/i.test(k))){try{const q=window[key];if(!Array.isArray(q)||typeof q.push!=="function")continue;const id="juba_"+Date.now()+"_"+Math.random();q.push([[id],{},r=>{req=r}]);if(req){state.require=req;break}}catch(_){}}}
  try{const cache=req?.c||{};for(const m of Object.values(cache).slice(0,12000)){const e=m?.exports;add(e);if(e&&typeof e==="object")for(const v of Object.values(e).slice(0,80))add(v)}}catch(_){}
  state.moduleScanAt=now;state.modules=values;return values;
 };
 const reactPeer=()=>{
  const roots=[visibleHeader(),...mainNodes(".message-in,.message-out,[data-id]").slice(-8)].filter(Boolean),seen=new WeakSet(),hits=[];
  const walk=(v,d=0)=>{if(v==null||d>5)return;if(typeof v==="string"){const j=jidOf(v);if(j)hits.push(j);return}if(typeof v!=="object"||seen.has(v))return;seen.add(v);const direct=jidOf(v);if(direct)hits.push(direct);for(const k of ["id","wid","jid","remoteJid","peerId","contactId","chatId","contact","chat","peer","remote","to","from","memoizedProps","pendingProps","return","child","sibling"]){try{walk(v[k],d+1)}catch(_){}}};
  for(const el of roots){for(const k of Object.getOwnPropertyNames(el)){if(/^__react(Fiber|Props|Container)\$/.test(k)||k.startsWith("__reactFiber$")||k.startsWith("__reactProps$")){try{walk(el[k])}catch(_){}}}}
  const own=ownFromStore(state.modules),count={};for(const j of hits)if(j!==own&&!j.endsWith("@broadcast"))count[j]=(count[j]||0)+1;return Object.entries(count).sort((a,b)=>b[1]-a[1])[0]?.[0]||"";
 };
 const allModels=c=>{try{
  if(!c)return [];if(Array.isArray(c))return c;
  for(const v of [c.models,c._models,c.__x_models,c.modelMap,c._modelMap]){if(Array.isArray(v))return v;if(v instanceof Map)return [...v.values()];if(v&&typeof v==="object"&&!Array.isArray(v)){const a=Object.values(v);if(a.length&&a.length<=10000)return a}}
  for(const fn of ["getModelsArray","toArray","getAll"]){if(typeof c?.[fn]==="function"){const v=c[fn]();if(Array.isArray(v))return v}}
  if(typeof c?.values==="function"){const a=[...c.values()];if(a.length<=10000)return a}
 }catch(_){}return []};
 const looksChat=m=>{try{return !!(m&&jidOf(m.id||m.__x_id||m.wid)&&(m.msgs||m.contact||m.isGroup!==undefined||m.formattedTitle||m.__x_formattedTitle))}catch(_){return false}};
 const collections=values=>{
  const out=[];for(const x of values){for(const v of [x,x?.default,x?.Chat,x?.ChatCollection,x?.Chats,x?.Msg,x?.Messages]){if(v&&!out.includes(v))out.push(v)}}return out;
 };
 const activeFromStore=(values,name,preferredJid)=>{
  const chats=[];
  for(const c of collections(values)){
   for(const fn of ["getActive","getActiveChat","getCurrentChat"]){try{const m=typeof c?.[fn]==="function"?c[fn]():null;if(looksChat(m))chats.push({m,score:1000})}catch(_){}}
   for(const m of allModels(c).slice(-5000)){if(!looksChat(m))continue;let score=0;try{if(m.active||m.__x_active||m.isActive)score+=800;if(preferredJid&&jidOf(m.id||m.__x_id||m.wid||m.contact?.id)===preferredJid)score+=1400;if(allModels(m.msgs||m.messages||m.__x_msgs).length)score+=100;if(name&&[m.formattedTitle,m.__x_formattedTitle,m.name,m.__x_name,m.contact?.name,m.contact?.pushname].some(x=>text(x)===name))score+=400}catch(_){}if(score)chats.push({m,score})}
  }
  chats.sort((a,b)=>b.score-a.score);return chats[0]?.m||null;
 };
 const messagePeer=(values)=>{
  const ids=mainNodes("[data-id]").slice(-30).map(e=>e.getAttribute("data-id")).filter(Boolean);
  if(!ids.length)return null;
  for(const c of collections(values)){
   if(typeof c?.get!=="function")continue;
   for(const id of ids.slice().reverse())try{const m=c.get(id);if(m){const j=jidOf(m.chat?.id||m.id?.remote||m.remote||((m.id?.fromMe??m.fromMe)===true?m.to:m.from));if(j)return {id:j,model:m.chat||null}}}catch(_){}
  }return null;
 };
 const ownFromStore=values=>{
  const candidates=[];
  const add=(v,score)=>{const j=jidOf(v);if(j&&/@(c\.us|lid)$/.test(j))candidates.push({j,score})};
  for(const x of values){try{
   for(const k of ["wid","me","user","userId","meUser","__x_wid"])add(x?.[k],700);
   for(const fn of ["getMaybeMeUser","getMeUser","getMyUser","getWid"]){if(typeof x?.[fn]==="function")add(x[fn](),900)}
   if(x?.Conn){add(x.Conn.wid,1000);add(x.Conn.me,950)}
  }catch(_){}}
  candidates.sort((a,b)=>b.score-a.score);return candidates[0]?.j||"";
 };
 const ownFromMessages=values=>{const ids=mainNodes("[data-id]").slice(-80).map(e=>e.getAttribute("data-id")).filter(x=>/(?:^|_)true(?:_|$)/i.test(String(x)));for(const c of collections(values)){if(typeof c?.get!=="function")continue;for(const id of ids.slice().reverse())try{const m=c.get(id);const j=jidOf(m?.from||m?.sender?.id||m?.author);if(j&&/@(c\.us|lid)$/.test(j))return j}catch(_){}}return ""};
 const phoneFrom=(model,jid)=>{for(const v of [model?.contact?.phoneNumber,model?.contact?.id,model?.phoneNumber,model?.id]){const j=jidOf(v);if(j?.endsWith("@c.us"))return "+"+j.split("@")[0]}return jid?.endsWith("@c.us")?"+"+jid.split("@")[0]:""};
 const modelId=m=>{try{const key=m?.id||m?.key||m?.__x_id;for(const v of [key?._serialized,key?.serialized,m?._serialized,m?.serialized])if(typeof v==="string"&&v.length<=500)return v;for(const v of [typeof key==="string"?key:"",typeof m?.key==="string"?m.key:""])if(v)return v.slice(0,500);const fromMe=typeof key?.fromMe==="boolean"?key.fromMe:typeof m?.fromMe==="boolean"?m.fromMe:null,remote=jidOf(key?.remote||m?.remote||m?.chat?.id||m?.chatId),token=key?.id||key?.stanzaId||m?.stanzaId||m?.messageId;if(typeof fromMe==="boolean"&&remote&&token!=null){const t=String(token);if(t&&t.length<=300&&!/[\s\x00-\x1f]/.test(t))return String(fromMe)+"_"+remote+"_"+t}return ""}catch(_){return ""}};
 const idAliases=v=>{const raw=String(v||""),out=[raw,raw.replace(/^msg_/,"")];try{out.push(decodeURIComponent(raw))}catch(_){}return [...new Set(out.filter(Boolean))]};
 const directJid=v=>{const j=jidOf(v);return /@(c\.us|lid)$/.test(j)?j:""};
 const rowName=row=>{if(!row)return "";for(const el of row.querySelectorAll("[title],span[dir='auto']")){const v=safeName(el.getAttribute?.("title")||el.textContent);if(v&&!/^(yesterday|today|昨天|今天|星期.|周.|\d{1,2}:\d{2}|\d{4}年)/i.test(v))return v}return ""};
 const rowPhone=row=>{const candidates=[row?.getAttribute?.("aria-label"),row?.innerText].filter(Boolean);for(const raw of candidates){const m=String(raw).match(/(?:^|\n|\s)(\+?[0-9][0-9 ()-]{5,22}[0-9])(?:\s|\n|$)/);if(m){const d=m[1].replace(/\D/g,"");if(d.length>=7&&d.length<=20)return d+"@c.us"}}return ""};
 const rowReactPeer=(row,own)=>{
  const hits=[],seen=new WeakSet(),add=v=>{const j=directJid(v);if(j&&j!==own&&!hits.includes(j))hits.push(j)};
  const walk=(v,d=0)=>{if(v==null||d>7)return;if(typeof v==="string"||typeof v==="number"){add(v);return}if(typeof v!=="object"||seen.has(v))return;seen.add(v);add(v);for(const k of ["id","_serialized","serialized","wid","jid","userJid","remoteJid","peerId","contactId","chatId","phoneNumber","__x_phoneNumber","__x_id","contact","chat","peer","remote","item","model","data","memoizedProps","pendingProps","memoizedState","stateNode","children","key"]){try{walk(v[k],d+1)}catch(_){}}};
  const nodes=[row,...row.querySelectorAll("*")].slice(0,350);for(const el of nodes)for(const k of Object.getOwnPropertyNames(el)){if(/^__react(Fiber|Props|Container)\$/.test(k)||k.startsWith("__reactFiber$")||k.startsWith("__reactProps$")){try{let f=el[k];for(let i=0;f&&i<12;i++,f=f.return){walk(f?.key,0);walk(f?.memoizedProps,0);walk(f?.pendingProps,0);walk(f?.memoizedState,0);walk(f?.stateNode,0);walk(f?.child?.memoizedProps,0);walk(f?.sibling?.memoizedProps,0);walk(f?.alternate?.memoizedProps,0)}}catch(_){}}}return hits[0]||"";
 };
 const chatIndex=values=>{const byName=new Map(),add=(name,jid)=>{name=safeName(name);jid=directJid(jid);if(!name||!jid)return;const key=name.toLocaleLowerCase(),old=byName.get(key);byName.set(key,old&&old!==jid?null:jid)};for(const c of collections(values))for(const m of allModels(c).slice(-6000)){if(!looksChat(m))continue;const jid=jidOf(m.id||m.__x_id||m.wid||m.contact?.id);for(const n of [m.formattedTitle,m.__x_formattedTitle,m.name,m.__x_name,m.contact?.name,m.contact?.pushname,m.contact?.formattedName])add(n,jid)}return byName};
 const visibleConversationRows=(values,own)=>{
  const pane=document.querySelector("#pane-side");if(!pane)return [];const index=chatIndex(values),out=[],seen=new Set(),cells=[...pane.querySelectorAll("[data-testid='cell-frame-container']")],seeds=cells.length?cells:[...pane.querySelectorAll("[role='listitem'],[role='row']")];
  for(const seed of seeds){const row=seed.matches?.("[data-testid='cell-frame-container']")?seed:(seed.closest("[data-testid='cell-frame-container']")||seed);if(seen.has(row))continue;seen.add(row);let r;try{r=row.getBoundingClientRect()}catch(_){continue}if(r.width<150||r.height<38||r.height>150||r.bottom<=0||r.top>=innerHeight)continue;const name=rowName(row);let jid=rowReactPeer(row,own);let source="row-react";if(!jid&&name){jid=index.get(name.toLocaleLowerCase())||"";source="store-title"}/* DOM phone text is profile data, never a WhatsApp identity. */if(jid&&jid!==own){row.setAttribute("data-juba-wa-row-jid",jid);row.setAttribute("data-juba-wa-row-source",source);out.push({jid,name:name.slice(0,120),source})}else{row.removeAttribute("data-juba-wa-row-jid");row.removeAttribute("data-juba-wa-row-source")}}
  return out.slice(0,100);
 };
 const modelIdentityAliases=chat=>{const out=[],seen=new Set(),add=v=>{const j=directJid(v);if(!j||seen.has(j))return;seen.add(j);out.push({identityType:j.endsWith("@lid")?"whatsapp_lid":"whatsapp_jid",identityValue:j,evidence:"wa-chat-contact-model"})};if(!chat||typeof chat!=="object")return out;for(const v of [chat.id,chat.__x_id,chat.wid,chat.jid,chat.contact?.id,chat.contact?.wid,chat.contact?.jid,chat.contact?.phoneNumber,chat.__x_contact?.id,chat.__x_contact?.wid,chat.__x_contact?.phoneNumber])add(v);return out.slice(0,8)};
 const waTidy=v=>String(v||"").replace(/[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\ufffc]/g,"").replace(/\r/g,"").trim();
 const waTranslationFromRoot=(root,original)=>{
  /* 210.2.59: message-root bounded extraction. Some translators append translated text to the
     original selectable-text node instead of creating the old target-inner node. */
  const selector="[data-juba-translation],[data-translation-text],[data-translation-element-mark],[data-immersive-translate-translation],[data-immersive-translate-target-inner],[data-immersive-translate-translation-element-mark],[class*='immersive-translate-target-inner'],[class*='immersive-translate-target-translation'],[class*='immersive-translate-translation'],font[class*='immersive-translate'],[data-testid*='translated' i],[data-testid*='translation' i],[data-testid*='translat' i],[aria-label*='translated' i],[aria-label*='translation' i],[aria-label*='翻译'],[aria-label*='译文']",foreign="[data-testid*='quoted' i],[data-testid*='reply-preview' i],[data-juba-owned],#jubaopen-interaction-host",values=[],evidence={explicitNodes:0,combinedNodes:0,leafCandidates:0};
  const add=(v,kind)=>{v=waTidy(v);if(!v||v===original||original&&original.includes(v)||values.includes(v))return;if(kind)evidence[kind]++;values.push(v)};
  for(const node of root.querySelectorAll(selector)){if(node.closest(foreign)||[...node.querySelectorAll(selector)].some(x=>x!==node))continue;add(node.innerText||node.textContent,"explicitNodes")}
  const textNodes=[...root.querySelectorAll("[data-testid='msg-text'],span.selectable-text,[data-testid*='caption'],[data-testid*='document-title']")].filter(x=>!x.closest(foreign));
  if(original)for(const node of textNodes){const value=waTidy(node.innerText||node.textContent);if(value.length>original.length&&value.startsWith(original)){const tail=waTidy(value.slice(original.length));if(tail)add(tail,"combinedNodes")}}
  if(!values.length&&original){const leaves=[];for(const node of textNodes){for(const leaf of [node,...node.querySelectorAll("span,font,div,p")]){if(leaf.children.length&&![...leaf.children].every(c=>!waTidy(c.innerText||c.textContent)))continue;const value=waTidy(leaf.innerText||leaf.textContent);if(value&&!leaves.includes(value))leaves.push(value)}}evidence.leafCandidates=leaves.length;const others=leaves.filter(x=>x!==original&&!original.includes(x)&&!x.includes(original));if(others.length===1)add(others[0],null)}
  const text=values.join("\n").slice(0,65536);return {translation:text?{text,source:"whatsapp-message-owned-root-v259",confidence:"high",visible:true}:null,evidence:{...evidence,rootTextLength:waTidy(root.innerText||root.textContent).length,originalLength:waTidy(original).length,translationLength:text.length}}
 };

 const reactMessageModels=(chatJid,aliases)=>{
  const out=[],found=new Set(),roots=mainNodes(".message-in,.message-out,[data-testid='msg-container']").slice(-600),allowed=new Set([chatJid,...aliases].filter(Boolean));
  for(const root of roots){let visits=0;const candidates=new Map(),seen=new WeakSet(),accept=v=>{if(!v||typeof v!=="object")return;const id=modelId(v);if(!id||found.has(id))return;const peer=jidOf(v?.id?.remote||v?.remote||v?.chat?.id||v?.chatId||v?.to||v?.from||v?.sender?.id||v?.author),fm=typeof v?.id?.fromMe==="boolean"?v.id.fromMe:typeof v?.fromMe==="boolean"?v.fromMe:typeof v?.__x_fromMe==="boolean"?v.__x_fromMe:null;if(peer&&allowed.has(peer)&&typeof fm==="boolean")candidates.set(id,v)},walk=(v,d=0)=>{if(v==null||d>7||visits++>4000||typeof v!=="object"||seen.has(v))return;seen.add(v);accept(v);for(const k of ["message","msg","model","data","item","value","current","props","memoizedProps","pendingProps","memoizedState","stateNode","child","sibling","alternate","children"]){try{walk(v[k],d+1)}catch(_){}}};for(const el of [root,...root.querySelectorAll("*")].slice(0,160))for(const k of Object.getOwnPropertyNames(el))if(/^__react(Fiber|Props|Container)\$/.test(k)||k.startsWith("__reactFiber$")||k.startsWith("__reactProps$"))try{walk(el[k])}catch(_){}const unique=[...candidates.entries()];if(unique.length!==1)continue;const [id,model]=unique[0];found.add(id);let original=model?.body??model?.__x_body??model?.caption??model?.__x_caption??model?.text??"";if(typeof original!=="string")original="";const detected=waTranslationFromRoot(root,original.trim());out.push({model,translation:detected.translation,translationEvidence:detected.evidence})}
  return out.slice(-600)
 };
 const loadedMessages=(values,chat,chatJid)=>{
  const out={},stats={chatModelCount:0,reactModelCount:0,acceptedModelCount:0,rejectedNoStableId:0,rejectedPeer:0,rejectedDirection:0,translationCount:0,explicitNodeCount:0,combinedNodeCount:0,translationCandidateRoots:0},aliasList=modelIdentityAliases(chat).map(x=>x.identityValue),aliases=new Set(aliasList);if(chatJid)aliases.add(chatJid);
  const modelPeer=m=>jidOf(m?.id?.remote||m?.remote||m?.chat?.id||m?.chatId||m?.to||m?.from||m?.sender?.id||m?.author);
  const add=(entry,source)=>{const m=entry?.model||entry,translation=entry?.translation||null,evidence=entry?.translationEvidence||{};stats.explicitNodeCount+=Number(evidence.explicitNodes||0);stats.combinedNodeCount+=Number(evidence.combinedNodes||0);if(Number(evidence.translationLength||0)>0)stats.translationCandidateRoots++;const mid=modelId(m);if(!mid){stats.rejectedNoStableId++;return}const peer=modelPeer(m);if(peer&&!aliases.has(peer)){stats.rejectedPeer++;return}const fromMe=typeof m?.id?.fromMe==="boolean"?m.id.fromMe:typeof m?.fromMe==="boolean"?m.fromMe:typeof m?.__x_fromMe==="boolean"?m.__x_fromMe:null;if(typeof fromMe!=="boolean"){stats.rejectedDirection++;return}let raw=m?.t??m?.timestamp??m?.__x_t??m?.msgTime??m?.messageTimestamp??m?.ts??0;if(raw&&typeof raw==="object")raw=raw.low??raw.value??raw.seconds??0;let at=Number(raw);if(!Number.isFinite(at)||at<0)at=0;let body=m?.body??m?.__x_body??m?.caption??m?.__x_caption??m?.text??null;if(typeof body!=="string")body=null;out[mid]={at,fromMe,text:body?body.slice(0,65536):null,type:String(m?.type||m?.__x_type||m?.mediaType||"").slice(0,40),peer:peer||chatJid,source,...(translation?{translation}:{})};stats.acceptedModelCount++;if(translation)stats.translationCount++};
  const collections=[chat?.msgs,chat?.messages,chat?.__x_msgs,chat?.messageCollection],chatModels=[];for(const c of collections)for(const m of allModels(c))if(m&&!chatModels.includes(m))chatModels.push(m);stats.chatModelCount=chatModels.length;for(const m of chatModels.slice(-600))add(m,"active-chat-model");
  const react=reactMessageModels(chatJid,aliasList);stats.reactModelCount=react.length;for(const m of react)add(m,"active-chat-react-model");return {messages:out,stats};
 };
 const writeSnapshot=(stable,status,errorCode="")=>{
  const fingerprint=JSON.stringify(stable);if(fingerprint!==state.last)state.last=fingerprint;
  const payload={v:10,seq:++state.seq,at:Date.now(),status,errorCode,...stable},raw=JSON.stringify(payload);
  let node=document.getElementById(SNAPSHOT_ID);if(!node){node=document.createElement("meta");node.id=SNAPSHOT_ID;node.setAttribute("data-juba-wa-bridge","1");node.setAttribute("data-juba-owned","1");(document.head||document.documentElement).appendChild(node)}
  node.setAttribute("content",raw);node.dispatchEvent(new CustomEvent("jubaopen-wa-snapshot"));window.dispatchEvent(new CustomEvent("jubaopen-wa-snapshot"));
 };
 const publish=()=>{try{
  const header=visibleHeader(),name=headerName(),values=moduleValues(),reactJid=reactPeer(),chat=activeFromStore(values,name,reactJid),msg=messagePeer(values);
  const chatJid=jidOf(chat?.id||chat?.wid||chat?.contact?.id)||msg?.id||reactJid||"";
  const ownJid=ownFromStore(values)||ownFromMessages(values);
  const storeName=safeName(chat?.formattedTitle)||safeName(chat?.__x_formattedTitle)||safeName(chat?.name)||safeName(chat?.contact?.name)||safeName(chat?.contact?.pushname);
  const displayName=storeName||safeName(name),open=!!header;
  const visibleRows=visibleConversationRows(values,ownJid);
  const loaded=loadedMessages(values,chat,chatJid);
  const identityEvidence={storeChat:!!chat,storeMessage:!!msg,reactMain:!!reactJid,unanimousMessagePeer:!!(msg?.id&&(!reactJid||msg.id===reactJid)),source:chat?"store-chat":msg?"store-message":reactJid?"react-main":"none"};
  const stable={ownJid,chatJid,displayName,contactIdentityAliases:modelIdentityAliases(chat),phone:phoneFrom(chat,chatJid),avatarUrl:avatar(),isGroup:chatJid.endsWith("@g.us"),source:identityEvidence.source,identityEvidence,open,visibleRows,messages:loaded.messages,messageStats:loaded.stats};
  const status=!open?"NO_OPEN_CHAT":chatJid?(ownJid?"READY":"ACCOUNT_IDENTITY_PENDING"):"CHAT_IDENTITY_PENDING";
  writeSnapshot(stable,status);
 }catch(error){writeSnapshot({ownJid:"",chatJid:"",displayName:"",contactIdentityAliases:[],phone:"",avatarUrl:"",isGroup:false,source:"probe-error",open:!!visibleHeader(),visibleRows:[],messages:{}},"PROBE_ERROR",String(error?.name||"Error").slice(0,40))}};
 addEventListener("jubaopen-wa-request",publish);setInterval(publish,1200);
 const jubaOwned=node=>node instanceof Element&&(node.id===SNAPSHOT_ID||node.id==="jubaopen-followup-overlay"||node.matches?.("[data-juba-owned],[data-juba-followup-badge]")||node.closest?.("#jubaopen-followup-overlay,[data-juba-owned]"));
 const relevantMutation=record=>{if(jubaOwned(record.target))return false;const changed=[...record.addedNodes,...record.removedNodes];return changed.some(node=>node.nodeType!==1||!jubaOwned(node))};
 const start=()=>{publish();try{new MutationObserver(records=>{if(!records.some(relevantMutation))return;clearTimeout(start.t);start.t=setTimeout(publish,250)}).observe(document.documentElement,{subtree:true,childList:true})}catch(_){}};
 if(document.documentElement)start();else addEventListener("DOMContentLoaded",start,{once:true});
})();
