/* JubaOpen WhatsApp Web structure probe v1
Paste into DevTools Console on https://web.whatsapp.com after opening a direct chat.
Runs 30 seconds, downloads a local JSON report, and does not collect message text or upload data. */
(async()=>{
 "use strict";
 const started=Date.now(), duration=30000, samples=[];
 const jid=v=>{const m=String(v||"").match(/([0-9]{5,24})(?::[0-9]+)?@(c\.us|s\.whatsapp\.net|lid|g\.us)/i);return m?m[1]+"@"+(m[2].toLowerCase()==="s.whatsapp.net"?"c.us":m[2].toLowerCase()):""};
 const rect=e=>{if(!e)return null;const r=e.getBoundingClientRect();return {x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height),visible:r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight}};
 const attrs=e=>{const o={};if(!e)return o;for(const n of ["id","role","data-testid","aria-selected","aria-current","data-selected","data-id","data-chat-id","data-juba-wa-row-jid","data-juba-wa-row-source"])if(e.hasAttribute(n))o[n]=String(e.getAttribute(n)).slice(0,300);return o};
 const snap=()=>{
  const main=document.querySelector("#main,[data-testid='conversation-panel-wrapper'],[role='main']"), headers=main?[...main.querySelectorAll("header,[data-testid='conversation-header']")]:[], pane=document.querySelector("#pane-side"), bridge=document.getElementById("jubaopen-wa-page-snapshot-v1");
  let b={};try{const x=JSON.parse(bridge?.getAttribute("content")||"{}");b={v:x.v,seq:x.seq,ageMs:Date.now()-Number(x.at||0),ownJid:jid(x.ownJid),chatJid:jid(x.chatJid),source:x.source,aliasJids:(x.contactIdentityAliases||[]).map(a=>jid(a?.identityValue)).filter(Boolean),visibleRowCount:(x.visibleRows||[]).length,messageModelCount:x.messages?Object.keys(x.messages).length:0}}catch(e){b={parseError:String(e)}}
  const rows=pane?[...pane.querySelectorAll("[data-testid='cell-frame-container'],[role='listitem'],[role='row']")].slice(0,80).map(e=>({attrs:attrs(e),rect:rect(e),jid:jid(e.getAttribute("data-juba-wa-row-jid")||e.getAttribute("data-id")||e.getAttribute("data-chat-id"))})).filter(x=>x.rect?.visible):[];
  return {at:Date.now(),urlPath:location.pathname+location.search,visibility:document.visibilityState,main:{exists:!!main,attrs:attrs(main),rect:rect(main)},headers:headers.map(h=>({attrs:attrs(h),rect:rect(h)})),selectedRows:pane?[...pane.querySelectorAll("[aria-selected='true'],[data-selected='true'],[aria-current='true']")].slice(0,20).map(e=>({attrs:attrs(e),rect:rect(e)})):[],bridge:b,visibleRows:rows};
 };
 console.info("JubaOpen WA structure probe started: 30 seconds; no message text is collected.");
 while(Date.now()-started<duration){samples.push(snap());await new Promise(r=>setTimeout(r,500))}
 const report={tool:"JubaOpen WA structure probe",version:1,startedAt:new Date(started).toISOString(),endedAt:new Date().toISOString(),userAgent:navigator.userAgent,screen:{innerWidth,innerHeight,devicePixelRatio},privacy:"No message text, contact display name, avatar URL, storage, cookie, token, or network payload collected.",samples};
 const blob=new Blob([JSON.stringify(report,null,2)],{type:"application/json"}),a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=`juba-wa-structure-${Date.now()}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),5000);console.info("JubaOpen WA structure probe finished.",report);
 return report;
})()