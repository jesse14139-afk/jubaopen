"use strict";
/* Runs in the WhatsApp page MAIN world. Only a small, validated identity snapshot is
   exposed through a DOM node; no message body or credential is exported. */
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
 const visibleHeader=()=>{
  const main=document.querySelector("#main,[data-testid='conversation-panel-wrapper'],[role='main']");
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
  const roots=[visibleHeader(),...[...document.querySelectorAll("#main .message-in,#main .message-out,[role='main'] [data-id]")].slice(-8)].filter(Boolean),seen=new WeakSet(),hits=[];
  const walk=(v,d=0)=>{if(v==null||d>5)return;if(typeof v==="string"){const j=jidOf(v);if(j)hits.push(j);return}if(typeof v!=="object"||seen.has(v))return;seen.add(v);const direct=jidOf(v);if(direct)hits.push(direct);for(const k of ["id","wid","jid","remoteJid","peerId","contactId","chatId","contact","chat","peer","remote","to","from","memoizedProps","pendingProps","return","child","sibling"]){try{walk(v[k],d+1)}catch(_){}}};
  for(const el of roots){for(const k of Object.getOwnPropertyNames(el)){if(/^__react(Fiber|Props|Container)\$/.test(k)||k.startsWith("__reactFiber$")||k.startsWith("__reactProps$")){try{walk(el[k])}catch(_){}}}}
  const own=ownFromStore(state.modules),count={};for(const j of hits)if(j!==own&&!j.endsWith("@broadcast"))count[j]=(count[j]||0)+1;return Object.entries(count).sort((a,b)=>b[1]-a[1])[0]?.[0]||"";
 };
 const allModels=c=>{try{if(Array.isArray(c?.models))return c.models;if(typeof c?.getModelsArray==="function")return c.getModelsArray();if(Array.isArray(c))return c}catch(_){}return []};
 const looksChat=m=>{try{return !!(m&&jidOf(m.id||m.__x_id||m.wid)&&(m.msgs||m.contact||m.isGroup!==undefined||m.formattedTitle||m.__x_formattedTitle))}catch(_){return false}};
 const collections=values=>{
  const out=[];for(const x of values){for(const v of [x,x?.default,x?.Chat,x?.ChatCollection,x?.Chats,x?.Msg,x?.Messages]){if(v&&!out.includes(v))out.push(v)}}return out;
 };
 const activeFromStore=(values,name)=>{
  const chats=[];
  for(const c of collections(values)){
   for(const fn of ["getActive","getActiveChat","getCurrentChat"]){try{const m=typeof c?.[fn]==="function"?c[fn]():null;if(looksChat(m))chats.push({m,score:1000})}catch(_){}}
   for(const m of allModels(c).slice(-5000)){if(!looksChat(m))continue;let score=0;try{if(m.active||m.__x_active||m.isActive)score+=800;if(name&&[m.formattedTitle,m.__x_formattedTitle,m.name,m.__x_name,m.contact?.name,m.contact?.pushname].some(x=>text(x)===name))score+=400}catch(_){}if(score)chats.push({m,score})}
  }
  chats.sort((a,b)=>b.score-a.score);return chats[0]?.m||null;
 };
 const messagePeer=(values)=>{
  const ids=[...document.querySelectorAll("#main [data-id],[role='main'] [data-id]")].slice(-30).map(e=>e.getAttribute("data-id")).filter(Boolean);
  if(!ids.length)return null;
  for(const c of collections(values)){
   if(typeof c?.get!=="function")continue;
   for(const id of ids.slice().reverse())try{const m=c.get(id);if(m){const j=jidOf(m.chat?.id||m.remote||m.to||m.from||m.id?.remote);if(j)return {id:j,model:m.chat||null}}}catch(_){}
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
 const phoneFrom=(model,jid)=>{for(const v of [model?.contact?.phoneNumber,model?.contact?.id,model?.phoneNumber,model?.id]){const j=jidOf(v);if(j?.endsWith("@c.us"))return "+"+j.split("@")[0]}return jid?.endsWith("@c.us")?"+"+jid.split("@")[0]:""};
 const publish=()=>{try{
  const name=headerName(),values=moduleValues(),chat=activeFromStore(values,name),msg=messagePeer(values),reactJid=reactPeer();
  const chatJid=jidOf(chat?.id||chat?.wid||chat?.contact?.id)||msg?.id||reactJid||"";
  const ownJid=ownFromStore(values);
  const storeName=safeName(chat?.formattedTitle)||safeName(chat?.__x_formattedTitle)||safeName(chat?.name)||safeName(chat?.contact?.name)||safeName(chat?.contact?.pushname);
  const displayName=storeName||safeName(name);
  const payload={v:1,seq:++state.seq,at:Date.now(),ownJid,chatJid,displayName,phone:phoneFrom(chat,chatJid),avatarUrl:avatar(),isGroup:chatJid.endsWith("@g.us"),source:chat?"store-chat":msg?"store-message":reactJid?"react-main":"page-none"};
  const raw=JSON.stringify(payload);if(raw===state.last)return;state.last=raw;
  let node=document.getElementById(SNAPSHOT_ID);if(!node){node=document.createElement("meta");node.id=SNAPSHOT_ID;node.setAttribute("data-juba-wa-bridge","1");(document.head||document.documentElement).appendChild(node)}node.setAttribute("content",raw);node.dispatchEvent(new CustomEvent("jubaopen-wa-snapshot"));
 }catch(_){}};
 addEventListener("jubaopen-wa-request",publish);setInterval(publish,1200);
 const start=()=>{publish();try{new MutationObserver(()=>{clearTimeout(start.t);start.t=setTimeout(publish,250)}).observe(document.documentElement,{subtree:true,childList:true})}catch(_){}};
 if(document.documentElement)start();else addEventListener("DOMContentLoaded",start,{once:true});
})();
