"use strict";
(()=>{
 const NODE_ID="jubaopen-meta-page-snapshot-v1",VERSION=18,MAX_MESSAGES=500;
 const state={timer:0,idleHandle:0,sequence:0,generation:1,lastRoute:"",activePane:null,paneObserver:null,paneParentObserver:null,cachedConversation:null,ownerGates:new Map(),conversationGates:new Map(),stableOwners:new Map(),stableConversations:new Map(),messageCaches:new Map(),orderCaches:new Map(),lastPublished:"",lastSemantic:"",viewerEvidenceCache:null,diagnostics:{errors:0,lastError:"",scan:{},scheduler:{runs:0,dropped:0,coalesced:0,scopedMutations:0,paneRebinds:0,stabilityRetries:0}}};
 const clean=(v,n=65536)=>String(v??"").replace(/\u0000/g,"").replace(/\s+/g," ").trim().slice(0,n);
 const visible=el=>{try{if(!el||!el.isConnected||el.getAttribute?.("aria-hidden")==="true")return false;const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>1&&r.height>1&&r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth&&s.display!=="none"&&s.visibility!=="hidden"&&Number(s.opacity||1)>0}catch(_){return false}};
 const igActionRoute=p=>/(?:^|\/)calluser(?:\/|$)/i.test(String(p||""));
 const platform=()=>{const h=location.hostname.toLowerCase(),p=location.pathname;if((h==="www.instagram.com"||h==="instagram.com")&&p.startsWith("/direct/")&&!igActionRoute(p))return "instagram";if(h==="www.messenger.com"||h==="messenger.com")return "messenger";if((h==="www.facebook.com"||h==="facebook.com")&&p.startsWith("/messages"))return "facebook";return ""};
 const route=()=>String(location.pathname+location.search+location.hash).slice(0,2048);
 const decode=v=>{try{return decodeURIComponent(v)}catch(_){return v}};
 const threadId=code=>{const p=String(location.pathname||"");if(code==="instagram"&&igActionRoute(p))return "";let m;if(code==="instagram")m=p.match(/\/direct\/t\/([^/?#]+)\/?/);else if(code==="facebook")m=p.match(/\/messages\/(?:e2ee\/)?t\/([^/?#]+)\/?/);else m=p.match(/\/t\/([^/?#]+)\/?/);return m?clean(decode(m[1]),256):""};
 const username=v=>{const x=clean(v,80).replace(/^@/,"").replace(/^\/+|\/+$/g,"").toLowerCase();return /^[a-z0-9._]{1,64}$/.test(x)&&!["direct","accounts","explore","reels","stories","messages","settings","help"].includes(x)?x:""};
 const profileUsername=v=>{try{const u=new URL(clean(v,2048),location.href);return username(u.pathname)}catch(_){return username(v)}};
 const numeric=(v,exclude="")=>{const x=clean(v,40);return /^\d{5,30}$/.test(x)&&x!==String(exclude||"")?x:""};
 const avatar=v=>{const x=clean(v,4096);return /^(https:|blob:)/i.test(x)&&!/^data:image\/svg/i.test(x)?x:""};
 function gate(store,key,signature,minMs=250,hits=2){const now=Date.now();let g=store.get(key);if(!g||g.signature!==signature){g={signature,firstAt:now,hits:1,accepted:false};store.set(key,g);return false}g.hits++;if(g.hits>=hits&&now-g.firstAt>=minMs)g.accepted=true;return g.accepted}
 function sameOwner(a,b){if(!a||!b)return false;if(a.identityType===b.identityType&&clean(a.identityValue,80)===clean(b.identityValue,80))return true;const au=username(a.displayName||""),bu=username(b.displayName||"");return a.identityType==="instagram_user_id"&&b.identityType==="instagram_username"&&au===username(b.identityValue)||b.identityType==="instagram_user_id"&&a.identityType==="instagram_username"&&bu===username(a.identityValue)}
 function reconcileOwner(code,candidate){const cached=state.stableOwners.get(code);if(candidate?.stable===true){state.stableOwners.set(code,{...candidate});return candidate}if(cached&&(!candidate||sameOwner(cached,candidate)))return {...cached,source:(cached.source+"+session-latch").slice(0,160),stable:true,confidence:"high"};return candidate}
 function cachedOwner(code){const x=state.stableOwners.get(code);return x?{...x,source:(x.source+"+route-latch").slice(0,160),stable:true,confidence:"high"}:null}
 function node(){let el=document.getElementById(NODE_ID);if(el)return el;el=document.createElement("meta");el.id=NODE_ID;el.setAttribute("data-owner","jubaopen");(document.head||document.documentElement)?.appendChild(el);return el}
 function reactRoots(root,maxNodes=900,deadline=performance.now()+45){const out=[],seen=new Set(),all=[root,...Array.from(root?.querySelectorAll?.("*")||[])],nodes=all.length<=maxNodes?all:Array.from({length:maxNodes},(_,i)=>all[Math.round(i*(all.length-1)/(maxNodes-1))]);for(const el of nodes){if(performance.now()>deadline)break;if(!el)continue;let keys=[];try{keys=Object.getOwnPropertyNames(el)}catch(_){}for(const k of keys){if(performance.now()>deadline)break;if(!(k.startsWith("__reactFiber$")||k.startsWith("__reactProps$")||k.startsWith("__reactInternalInstance$")))continue;try{const v=el[k];if(v&&!seen.has(v)){seen.add(v);out.push(v)}if(k.startsWith("__reactFiber$")){let f=v;for(let i=0;f&&i<24&&performance.now()<=deadline;i++,f=f.return)for(const x of [f.memoizedProps,f.pendingProps,f.memoizedState])if(x&&!seen.has(x)){seen.add(x);out.push(x)}}}catch(_){}}}return out}
 function idsForUsername(root,wanted,tid){const found=new Set(),seen=new Set(),started=performance.now(),deadline=started+12;let scanned=0;const CHILD_KEYS=["user","profile","owner","sender","participant","participants","thread","actor","account","node","edges","data","message","item"],ID_KEYS=["pk","pk_id","user_id","userId","id","instagram_user_id"];const walk=(v,d)=>{if(!v||typeof v!=="object"||d>8||scanned++>1200||seen.has(v)||performance.now()>deadline)return;seen.add(v);try{const u=username(v.username||v.user_name||"");if(u&&u===wanted)for(const k of ID_KEYS){const id=numeric(v[k],tid);if(id)found.add(id)}for(const k of CHILD_KEYS){let x;try{x=v[k]}catch(_){continue}if(Array.isArray(x)){for(const item of x.slice(0,24))walk(item,d+1)}else if(x&&typeof x==="object")walk(x,d+1)}}catch(_){}};for(const x of reactRoots(root,160,deadline)){if(performance.now()>deadline)break;walk(x,0)}return [...found]}
 function explicitViewerEvidence(tid=""){
  /* 账号级证据优先；重型 React/boot 扫描短时缓存，避免每次 mutation 全页扫描。 */
  const now=Date.now(),cached=state.viewerEvidenceCache;
  if(cached&&cached.tid===String(tid||"")&&now-cached.at<15000)return {...cached.value,usernames:[...cached.value.usernames],ids:[...cached.value.ids],sources:[...cached.value.sources]};
  const evidence=new Map(),usernames=new Set(),seen=new WeakSet();let scanned=0;
  const addId=(v,source,weight)=>{const x=numeric(v,tid);if(!x)return;let row=evidence.get(x);if(!row){row=new Map();evidence.set(x,row)}row.set(source,Math.max(row.get(source)||0,weight))};
  const addUser=v=>{const x=username(v);if(x)usernames.add(x)};
  try{const m=document.cookie.match(/(?:^|;\s*)ds_user_id=(\d{5,30})(?:;|$)/);if(m)addId(m[1],"cookie-ds_user_id",6000)}catch(_){}
  try{for(const k of ["IG_USER_ID","ig_user_id","ACCOUNT_ID","USER_ID"]){const v=localStorage.getItem(k);if(v)addId(v,"localStorage-"+k,/IG_USER_ID|ig_user_id/.test(k)?5200:3200)}for(const k of ["IG_USERNAME","username"]){const v=localStorage.getItem(k);if(v)addUser(v)}}catch(_){}
  const inspectViewer=(v,d=0)=>{if(!v||typeof v!=="object"||d>7||seen.has(v)||scanned++>2600)return;seen.add(v);
    for(const k of ["viewerID","viewerId","currentUserID","currentUserId","IG_USER_ID","ig_user_id"]){try{addId(v[k],"fiber-current-viewer",1800)}catch(_){}}
    for(const k of ["actorID","actorId"]){try{addId(v[k],"fiber-actor",450)}catch(_){}}
    for(const k of ["viewer","currentViewer","current_user","currentUser","loggedInUser","logged_in_user"]){try{const x=v[k];if(!x||typeof x!=="object")continue;for(const q of ["id","pk","pk_id","user_id","userId","actorID","actorId"])addId(x[q],"fiber-viewer-object",2200);for(const q of ["username","user_name"])addUser(x[q]);inspectViewer(x,d+1)}catch(_){}}
    for(const k of ["props","memoizedProps","memoizedState","pendingProps","data"]){try{const x=v[k];if(x&&typeof x==="object")inspectViewer(x,d+1)}catch(_){}}
  };
  const fiberDeadline=performance.now()+45;for(const x of reactRoots(document.documentElement,1000,fiberDeadline)){if(performance.now()>fiberDeadline)break;inspectViewer(x)}
  const scriptDeadline=performance.now()+30;for(const el of Array.from(document.scripts).slice(-160)){if(performance.now()>scriptDeadline)break;const t=el.textContent||"";if(!t||t.length>4000000)continue;
    const specs=[[/"(?:ds_user_id|IG_USER_ID|ig_user_id)"\s*:\s*"?(\d{5,30})"?/g,"boot-instagram-account",4000],[/"(?:viewerID|viewerId|currentUserID|currentUserId|USER_ID)"\s*:\s*"?(\d{5,30})"?/g,"boot-current-viewer",1600],[/"(?:actorID|actorId)"\s*:\s*"?(\d{5,30})"?/g,"boot-actor",350],[/"(?:viewer|currentViewer|current_user|currentUser|loggedInUser|logged_in_user)"\s*:\s*\{[\s\S]{0,1400}?"(?:id|pk|pk_id|user_id|userId)"\s*:\s*"?(\d{5,30})"?/g,"boot-viewer-object",2000]];
    for(const [rx,source,weight] of specs){let q,n=0;while((q=rx.exec(t))&&n++<12)addId(q[1],source,weight)}
    const urx=/"(?:viewer|currentViewer|current_user|currentUser|loggedInUser|logged_in_user)"\s*:\s*\{[\s\S]{0,1400}?"(?:username|user_name)"\s*:\s*"([A-Za-z0-9._]{1,64})"/g;let um,un=0;while((um=urx.exec(t))&&un++<8)addUser(um[1]);
  }
  const ranked=[...evidence].map(([id,parts])=>({id,score:[...parts.values()].reduce((a,b)=>a+b,0),sources:[...parts.keys()]})).sort((a,b)=>b.score-a.score),top=ranked[0],second=ranked[1],strong=!!top&&top.score>=3000,accepted=!!top&&top.score>=1400&&(strong||!second||top.score-second.score>=300);
  const value={ids:accepted?[top.id]:[],usernames:[...usernames],candidateCount:ranked.length,conflict:ranked.length>0&&!accepted,sources:accepted?top.sources:[],score:accepted?top.score:0};state.viewerEvidenceCache={at:now,tid:String(tid||""),value};return {...value,usernames:[...value.usernames],ids:[...value.ids],sources:[...value.sources]};
 }
 function igOwn(){
  const explicit=explicitViewerEvidence();
  if(explicit.ids.length===1){const id=explicit.ids[0],ok=gate(state.ownerGates,"ig-own-id",id,250,2);return {identityType:"instagram_user_id",identityValue:id,displayName:explicit.usernames.length===1?explicit.usernames[0]:"",source:(explicit.sources||["explicit-current-viewer"]).join("+").slice(0,160),role:"IS_OWNER",stable:ok,confidence:ok?"high":"medium"}}
  if(explicit.ids.length>1)return null;
  const candidates=[],roots=[...document.querySelectorAll('nav,header,[role="navigation"],[role="banner"]')].filter(r=>!r.closest('main,[role="main"]'));
  for(const d of document.querySelectorAll('[role="dialog"],[role="menu"]')){const t=clean(d.getAttribute("aria-label")||d.innerText,300);if(/switch accounts?|account center|your account|切换账号|账户中心|你的账号/i.test(t))roots.push(d)}
  const seen=new Set();for(const root of roots)for(const a of root.querySelectorAll('a[href]')){if(seen.has(a)||!visible(a))continue;seen.add(a);const href=a.getAttribute("href")||"",u=profileUsername(href);if(!u)continue;const label=clean(a.getAttribute("aria-label")||a.getAttribute("title")||a.textContent,100),r=a.getBoundingClientRect();let score=0;if(/profile|个人主页|主页|profil|perfil|your account|你的账号/i.test(label))score+=1000;if(a.querySelector("img"))score+=260;if(/^\/[A-Za-z0-9._]{1,64}\/?$/.test(href))score+=180;if(r.left<Math.min(360,innerWidth*.34))score+=220;if(root.matches('[role="dialog"],[role="menu"]'))score+=180;if(explicit.usernames.length===1&&explicit.usernames[0]===u)score+=1000;if(score>=320)candidates.push({u,score,label})}
  candidates.sort((a,b)=>b.score-a.score);if(!candidates.length)return null;const top=candidates[0],topIds=[...new Set(candidates.filter(x=>x.score===top.score).map(x=>x.u))];if(topIds.length!==1)return null;const ok=gate(state.ownerGates,"ig-own",top.u,250,2);return {identityType:"instagram_username",identityValue:top.u,displayName:top.u,source:"account-chrome-profile-link",role:"IS_OWNER",stable:ok,confidence:ok?"high":"medium"}}


 const IG_PATH=/^\/[A-Za-z0-9_.]{1,64}\/$/,IG_SELF=/^(主页|Profile|个人主页|Home)$/i;
 function igHeaderScopes(pane){
  /* metaPane may be the message/composer branch. The contact Header is often a sibling,
     so walk bounded ancestors and search their sibling branches instead of pane descendants only. */
  const scopes=[];if(!pane?.isConnected)return scopes;let branch=pane;
  for(let depth=0;branch&&depth<12;depth++){
   const parent=branch.parentElement;if(!parent)break;
   scopes.push({root:parent,branch,depth});
   if(parent.matches?.('main,[role="main"]'))break;
   branch=parent;
  }
  return scopes;
 }
 function igHeader(tid,pane){
  if(!pane?.isConnected)return null;
  const vw=Math.max(document.documentElement.clientWidth||0,innerWidth||0),pr=pane.getBoundingClientRect(),scopes=igHeaderScopes(pane),list=[],seen=new Set();
  for(const scope of scopes)for(const a of scope.root.querySelectorAll('a[href]')){
   if(seen.has(a)||!visible(a))continue;seen.add(a);
   const href=a.getAttribute("href")||"";if(igActionRoute(href))continue;
   let profilePath="";try{profilePath=new URL(href,location.href).pathname}catch(_){profilePath=href}
   if(!IG_PATH.test(profilePath))continue;
   const u=profileUsername(href),r=a.getBoundingClientRect(),label=clean(a.textContent,100);
   const inPane=pane.contains(a),sameBranch=scope.branch.contains(a);
   /* At the nearest useful ancestor the Header must be either inside a broad pane or
      in a sibling branch above the message/composer subtree. */
   if(!u||IG_SELF.test(label)||(!inPane&&sameBranch)||r.bottom>pr.top+190||r.right<pr.left-30||r.left>pr.right+30||(vw>=700&&r.left<Math.min(300,vw*.24)))continue;
   const title=!!a.querySelector("span[title]"),sibling=!inPane;
   const score=(title?1200:0)+(sibling?900:300)+(12-scope.depth)*45+r.left-r.top*.25;
   list.push({a,u,score,scope});
  }
  list.sort((a,b)=>b.score-a.score);if(!list.length)return null;
  const top=list[0],a=top.a,u=top.u,limit=top.scope.root;let n=a,best=null;
  for(let i=0;n&&i<14;i++,n=n.parentElement){
   const r=n.getBoundingClientRect();
   if(visible(n)&&r.bottom<=pr.top+190&&r.left>=pr.left-30&&r.right<=pr.right+30&&r.width>=160&&r.height>=28&&r.height<180)best=n;
   if(n===limit)break;
  }
  const header=best||a.closest("header");if(!header||!visible(header))return null;
  const title=a.querySelector("span[title]"),name=clean(title?.getAttribute("title")||a.textContent||u,200);let av="",avScore=Infinity,lr=a.getBoundingClientRect();
  for(const img of header.querySelectorAll("img")){if(!visible(img))continue;const src=avatar(img.currentSrc||img.src),r=img.getBoundingClientRect();if(!src||r.width<24||r.height<24||r.width>120||r.height>120)continue;const score=Math.abs((r.left+r.width/2)-(lr.left+lr.width/2))+Math.abs((r.top+r.height/2)-(lr.top+lr.height/2))*2+(r.left<lr.left?80:0);if(score<avScore){avScore=score;av=src}}
  const ids=idsForUsername(header,u,tid);return {header,a,username:u,name,avatarUrl:av,numericId:ids.length===1?ids[0]:"",identityConflict:ids.length>1,headerRelation:pane.contains(header)?"pane-descendant":"pane-sibling"};
 }
 function reactValues(el){
  /* Identity/header helper only. Message extraction uses the branch-bound parser below. */
  const values=[],seen=new WeakSet(),keys=["message","messageRef","slideMessageRef","currentMessageRef","viewerThreadRef","threadRef","senderRef","item","node","data","props","children","sender","author","actor","owner","user","thread","conversation","participants","participant"];
  const walk=(v,d=0)=>{if(!v||typeof v!=="object"||d>5||seen.has(v)||values.length>360)return;seen.add(v);values.push(v);for(const k of keys){try{const x=v[k];if(Array.isArray(x)){for(const q of x.slice(0,24))walk(q,d+1)}else if(x&&typeof x==="object")walk(x,d+1)}catch(_){}}};
  for(let n=el,d=0;n&&d<7;n=n.parentElement,d++){let names=[];try{names=Object.getOwnPropertyNames(n)}catch(_){}for(const k of names){if(!k.startsWith("__reactProps$")&&!k.startsWith("__reactFiber$")&&!k.startsWith("__reactInternalInstance$"))continue;try{const value=n[k];walk(k.startsWith("__reactFiber$")?value?.memoizedProps:value)}catch(_){}}}
  return values;
 }
 const reactProps=reactValues;
 function participantIds(root){const ids=new Set();for(const p of reactValues(root)){const arrays=[p.participants,p.participant_ids,p.participantIds,p.users,p.thread?.participants,p.conversation?.participants];for(const a of arrays){if(!Array.isArray(a))continue;for(const q of a.slice(0,40)){const id=numeric(typeof q==="object"?(q.id||q.pk||q.user_id||q.userId):q);if(id)ids.add(id)}}}return [...ids]}
 function conversationKind(root){
  /* Only structured thread fields are authoritative. UI prose, event text and member counts are forbidden. */
  let direct=false;const evidence=[];
  for(const p of reactValues(root)){
   for(const v of [p.viewerThreadRef?.is_group,p.threadRef?.is_group,p.isGroup,p.is_group,p.isGroupThread,p.thread?.isGroup,p.thread?.is_group,p.conversation?.isGroup]){if(v===true)return {kind:"group",confidence:"high",evidence:["react-thread-is-group"]};if(v===false)direct=true}
   for(const v of [p.threadType,p.thread_type,p.thread?.threadType,p.thread?.thread_type,p.conversation?.threadType]){const x=clean(v,80).toLowerCase();if(/^(group|group_chat|group_thread|multi_participant)$/.test(x))return {kind:"group",confidence:"high",evidence:["react-thread-type"]};if(/^(one_to_one|direct|single|private)$/.test(x))direct=true}
  }
  return {kind:direct?"direct":"unknown",confidence:direct?"high":"medium",evidence:direct?["structured-direct-thread"]:evidence};
 }
 const META_PARSER_CANDIDATE="hotfix28-shadow-v1";
 const MESSAGE_ID=/mid\.\$[A-Za-z0-9._$-]+/;
 const BRANCH_KEYS=["message","messages","messageRef","slideMessageRef","currentMessageRef","senderRef","threadRef","viewerThreadRef","item","node","edges","data","props","children","sender","author","actor","payload","result","content","updateQueue","memoCache","memoizedState"];
 const TRANSLATION_WRAPPER='.immersive-translate-target-wrapper,[data-immersive-translate-translation],.immersive-translate-target-translation-block-wrapper,.immersive-translate-target-translation-block';
 const TRANSLATION_LEAF='.immersive-translate-target-inner,[data-immersive-translate-translation],.immersive-translate-target-translation-block';
 const IG_REPLY_PREVIEW_SELECTOR='[data-reply-id],[data-testid*="reply-preview" i],[data-testid*="quoted" i],[data-testid*="replied" i],[aria-label^="Replying to" i],[aria-label^="Replied to" i],[aria-label^="You replied to" i],[aria-label^="回复了"],[aria-label^="回复给"]';
 const IG_REPLY_HEADER=/^(?:你回复了|回复了|回复给|you replied to|replied to|replying to)\s*[^\n]{0,160}$/i;
 const IG_MESSAGE_BOUNDARY_SELECTOR='[data-message-id],[data-mid],[role="article"],[role="row"],li,[data-testid*="message" i]';
 const IG_PENDING_STATUS=/^(?:正在发送|发送中|sending|sending…|sending\.\.\.|uploading|正在上传|retrying|重试中)$/i;
 const FB_REPLY_PREVIEW_SELECTOR='[data-reply-id],[data-testid*="reply-preview" i],[data-testid*="quoted" i],[data-testid*="replied" i],[aria-label^="You replied to" i],[aria-label^="Replied to" i],[aria-label^="Replying to" i],[aria-label^="你回复了"],[aria-label^="回复了"],[aria-label^="回复给"]';
 const FB_REPLY_HEADER=/^(?:你回复了\s*[^\n]{1,100}|[^\n]{1,80}\s*回复了你|you replied to\s+[^\n]{1,120}|[^\n]{1,100}\s+replied to you)$/i;
 const FB_A11Y_PREFIX=/^(?:Enter[,，]?\s*)?(?:消息由.{0,160}?发送于|message (?:sent by|from) .{0,160}? at|.{0,160}? sent (?:a )?message at)\s*(?:19|20)\d{2}[年\/.\-]\d{1,2}[月\/.\-]\d{1,2}日?\s+\d{1,2}[:：]\d{2}(?::\d{2})?\s*[:：]\s*/i;
 function fbAccessibilityBody(value){const x=clean(value,65536),m=x.match(FB_A11Y_PREFIX);return m?clean(x.slice(m[0].length),65536):""}
 const FB_DELIVERY_STATUS=/^(?:已发送|已送达|已读|发送中|正在发送|sent|delivered|seen|sending|sending[.…]{1,3})$/i;
 const FB_SYSTEM_NOTICE=/^(?:(?:新消息和(?:通话|谈话)|消息和(?:通话|谈话)).{0,90}端到端加密.{0,260}(?:读取|收听|分享|详细了解)|(?:new messages and calls|messages and calls).{0,100}end[- ]to[- ]end encrypted.{0,260}(?:read|listen|share|learn more)|你们可以互发消息.{0,260}(?:在线状态|是否阅读|消息)|you can now message and call each other.{0,260}|此人目前无法接收消息|this person is unavailable on messenger)$/i;
 function fbPresentationText(value){const x=clean(value,65536);return !!x&&(FB_DELIVERY_STATUS.test(x)||FB_SYSTEM_NOTICE.test(x)||/^(?:今天|昨天|today|yesterday)$/i.test(x))}
 function fbTextPolluted(value){const x=clean(value,65536);return !!x&&(FB_A11Y_PREFIX.test(x)||/^(?:Enter[,，]?\s*)?(?:消息由.{0,160}?发送于|message (?:sent by|from)|.{0,160}? sent (?:a )?message at)/i.test(x)||FB_REPLY_HEADER.test(x)||fbPresentationText(x))}
 function stripFacebookPresentationNodes(root){if(!root?.querySelectorAll)return;const nodes=[...root.querySelectorAll('span,div,p,font')].reverse();for(const n of nodes){if(n===root||n.children.length)continue;if(fbPresentationText(n.textContent||''))n.remove()}}
 function fbReplyHeaderLeaves(root){
  if(!root?.querySelectorAll)return [];
  return [...root.querySelectorAll('span,div,p')].filter(n=>!n.children.length&&FB_REPLY_HEADER.test(clean(n.textContent,260)));
 }
 function fbExplicitPreviewNode(el,root){
  const q=el?.closest?.(FB_REPLY_PREVIEW_SELECTOR);
  if(!q||q===root||!root?.contains?.(q))return null;
  /* v263 safety: generic aria-label reply markers can be attached to the whole
     composite reply bubble. Never classify such a container as quoted content. */
  const stable=q.hasAttribute?.('data-reply-id')||/reply-preview|quoted/i.test(clean(q.getAttribute?.('data-testid'),160));
  if(!stable)return null;
  const all=clean(root.innerText||root.textContent,65536),part=clean(q.innerText||q.textContent,65536);
  if(!part||part===all||q.querySelector?.(TRANSLATION_WRAPPER))return null;
  return q;
 }
 function fbReplyContext(){return null}
 function fbInReplyPreview(el,root){return !!fbExplicitPreviewNode(el,root)}
 function fbInExplicitReplyPreview(el,root){return !!fbExplicitPreviewNode(el,root)}
 function fbNestedMessageRoot(el,pane){const parent=el?.parentElement?.closest?.('[data-message-id],[data-mid]');return !!(parent&&parent!==el&&pane?.contains?.(parent))}
 function stripFacebookReplyPreviews(root){
  for(const q of [...root.querySelectorAll?.('[data-reply-id],[data-testid*="reply-preview" i],[data-testid*="quoted" i]')||[]]){
   if(q!==root&&fbExplicitPreviewNode(q,root))q.remove();
  }
  /* Never remove a semantic parent. Only the standalone title leaf is presentation. */
  for(const n of fbReplyHeaderLeaves(root))n.remove();
 }
 function fbReplyBodyLeaf(root){
  const headers=fbReplyHeaderLeaves(root);if(!headers.length)return "";
  const header=headers[headers.length-1],nodes=[];
  for(const n of root.querySelectorAll?.('span[dir="auto"],div[dir="auto"],p')||[]){
   if(n===header||n.contains?.(header)||header.contains?.(n)||n.children.length)continue;
   if(n.closest?.(`${TRANSLATION_WRAPPER},button,[role="button"],[role="menu"],[role="menuitem"]`))continue;
   if(fbExplicitPreviewNode(n,root))continue;
   const pos=header.compareDocumentPosition(n);if(!(pos&Node.DOCUMENT_POSITION_FOLLOWING))continue;
   const x=clean(n.textContent,65536);if(!x||FB_REPLY_HEADER.test(x)||fbPresentationText(x))continue;
   nodes.push({n,text:x});
  }
  /* Facebook orders reply title, quote, current body, then current translation.
     Translation wrappers were excluded, so the last independent text leaf is the
     current reply body. This fallback is used only for composite reply rows. */
  return nodes.length?nodes[nodes.length-1].text:"";
 }
 function fbOriginalText(root){
  if(!root)return "";const direct=fbReplyBodyLeaf(root);if(direct)return direct;
  const clone=root.cloneNode(true);stripFacebookReplyPreviews(clone);stripFacebookPresentationNodes(clone);
  for(const n of clone.querySelectorAll?.(`${TRANSLATION_WRAPPER},[data-translation-element-mark],font,button,[role="button"],[role="menu"],[role="menuitem"],[aria-haspopup="menu"],time,[datetime],[data-juba-time-marker]`)||[])n.remove();
  let value=clean(clone.innerText||clone.textContent,65536);const body=fbAccessibilityBody(value);if(body)value=body;return fbTextPolluted(value)?"":value
 }
 function facebookText(value,root){
  const structured=clean(value,65536),body=fbAccessibilityBody(structured);if(body)return {text:body,source:"facebook-a11y-body",polluted:false};
  if(structured&&!fbTextPolluted(structured))return {text:structured,source:"react-structured",polluted:false};
  const leaf=fbReplyBodyLeaf(root),dom=leaf||fbOriginalText(root);return {text:dom,source:leaf?"facebook-current-reply-body-v263":dom?"facebook-message-dom":"none",polluted:!dom&&!!structured}
 }
 function semanticReplyRoots(root){
 const out=[];if(!root?.querySelectorAll)return out;
 for(const leaf of root.querySelectorAll('span,div,p')){
  if(leaf.children.length)continue;const header=clean(leaf.textContent,240);
  if(!IG_REPLY_HEADER.test(header))continue;let q=leaf;
  for(let d=0;d<5&&q.parentElement&&q.parentElement!==root;d++){
   const p=q.parentElement,txt=clean(p.innerText||p.textContent,1200);
   if(!txt||txt.length>1000||!txt.startsWith(header))break;
   q=p;if(txt.length>header.length)break
  }
  const txt=clean(q.innerText||q.textContent,1200);
  if(q!==root&&txt.length>header.length&&!out.some(x=>x===q||x.contains(q)))out.push(q)
 }return out
}
 function igMessageBoundary(el,scope){
  if(!el)return scope||null;for(let n=el;n&&n!==scope;n=n.parentElement)if(n.matches?.(IG_MESSAGE_BOUNDARY_SELECTOR))return n;
  return scope?.matches?.(IG_MESSAGE_BOUNDARY_SELECTOR)?scope:scope||el
 }
 /* 210.0.24: IG may put "You replied to" on the complete outbound message row.
    A row is never its own quoted preview; only a strict descendant preview is excluded. */
 function inReplyPreview(el,root){const boundary=igMessageBoundary(el,root),q=el?.closest?.(IG_REPLY_PREVIEW_SELECTOR);if(q&&boundary&&q!==boundary&&boundary.contains?.(q))return true;return !!boundary&&semanticReplyRoots(boundary).some(x=>x===el||x.contains(el))}
 function stripSemanticReplyPreviews(root){for(const q of semanticReplyRoots(root))q.remove()}
 function igPendingSend(root){if(!root)return false;if(root.matches?.('[aria-busy="true"],[data-send-status="sending"],[data-status="sending"]')||root.querySelector?.('[aria-busy="true"],[data-send-status="sending"],[data-status="sending"],[role="progressbar"]'))return true;for(const n of root.querySelectorAll?.('[aria-label],[title],span,div,p')||[]){const label=clean(n.getAttribute?.('aria-label')||n.getAttribute?.('title'),120),direct=n.children.length?clean([...n.childNodes].filter(x=>x.nodeType===3).map(x=>x.nodeValue).join(' '),120):clean(n.textContent,120);if(IG_PENDING_STATUS.test(label)||IG_PENDING_STATUS.test(direct))return true}return false}
 function ownReactEntries(el){const out=[];let names=[];try{names=Object.getOwnPropertyNames(el)}catch(_){return out}for(const k of names){if(!k.startsWith("__reactProps$")&&!k.startsWith("__reactFiber$")&&!k.startsWith("__reactInternalInstance$"))continue;try{out.push({fiber:k.startsWith("__reactFiber$")?el[k]:null,value:el[k]})}catch(_){}}return out}
 function normalizeMessageId(v){const m=clean(v,900).match(MESSAGE_ID);return m?m[0]:""}
 function idsIn(objects){const out=new Set(),add=v=>{const id=normalizeMessageId(v);if(id)out.add(id)};for(const p of objects){for(const k of ["messageId","message_id","mid","double_tappable_id","offlineThreadingId","offline_threading_id","__id","id"])add(p?.[k]);for(const m of [p?.message,p?.messageRef,p?.slideMessageRef,p?.currentMessageRef,p?.item,p?.node])if(m&&typeof m==="object")for(const k of ["messageId","message_id","mid","double_tappable_id","offlineThreadingId","offline_threading_id","__id","id"])add(m[k])}return out}
 function walkBranch(value,out,seen,depth=0){if(!value||typeof value!=="object"||depth>7||seen.has(value)||out.length>900)return;seen.add(value);out.push(value);for(const k of BRANCH_KEYS){try{const x=value[k];if(Array.isArray(x)){for(const q of x.slice(0,50))walkBranch(q,out,seen,depth+1)}else if(x&&typeof x==="object")walkBranch(x,out,seen,depth+1)}catch(_){}}}
 function branchObjects(el){
  const out=[],seen=new WeakSet();
  for(const entry of ownReactEntries(el)){
   if(!entry.fiber){const layer=[];walkBranch(entry.value,layer,new WeakSet());const merged=new Set([...idsIn(out),...idsIn(layer)]);if(merged.size<=1)for(const x of layer)if(!seen.has(x)){seen.add(x);out.push(x)};continue}
   for(let f=entry.fiber,depth=0;f&&depth<14;depth++,f=f.return){
    const layer=[],layerSeen=new WeakSet();walkBranch(f.memoizedProps,layer,layerSeen);walkBranch(f.pendingProps,layer,layerSeen);if(depth<6)walkBranch(f.memoizedState,layer,layerSeen);
    const merged=new Set([...idsIn(out),...idsIn(layer)]);if(merged.size>1)break;
    for(const obj of layer)if(!seen.has(obj)){seen.add(obj);out.push(obj)}
   }
  }
  return out;
 }
 function metaI64(v,timeOnly=false){
  if(!Array.isArray(v)||v.length<2)return null;
  const a=Number(v[0]),b=Number(v[1]);if(!Number.isInteger(a)||!Number.isInteger(b))return null;
  const out=[];for(const [lo,hi] of [[a,b],[b,a]])try{const q=(BigInt(hi>>>0)<<32n)+BigInt(lo>>>0);if(q<=BigInt(Number.MAX_SAFE_INTEGER)){const n=Number(q);if(!timeOnly||(n>=315532800000&&n<4102444800000))if(!out.includes(n))out.push(n)}}catch(_){}
  return out.length===1?out[0]:null;
 }
 function timeValue(v){
  if(v===null||v===undefined||v==="")return null;
  const i64=metaI64(v,true);if(i64!==null)return i64;
  if(typeof v==="object")return null;
  if(typeof v==="string"&&!/^\d+(?:\.\d+)?$/.test(v.trim())){const t=Date.parse(v);return Number.isFinite(t)&&t>315532800000&&t<4102444800000?t:null}
  let n=Number(v);if(!Number.isFinite(n)||n<0)return null;
  if(n>1e18)n/=1e6;else if(n>1e15)n/=1e3;else if(n<1e11)n*=1000;
  n=Math.trunc(n);return n>315532800000&&n<4102444800000?n:null;
 }
 function sortValue(v){const n=metaI64(v);if(n!==null)return n;const q=Number(v);return Number.isSafeInteger(q)&&q>=0?q:null}
 function encryptedPayload(v){const x=clean(v,65536);return /^\d{5,}##\d{5,}[A-Za-z0-9+/=]{48,}\d{5,}##\d{5,}$/.test(x)||(/^[A-Za-z0-9+/=]{96,}$/.test(x)&&/[+/=]/.test(x))}
 function entityRecord(code,el,forcedId=""){
  const objects=branchObjects(el),ids=idsIn(objects);if(!objects.length||(!forcedId&&ids.size!==1))return null;
  const id=forcedId||[...ids][0];if(!id||(forcedId&&!ids.has(id)))return null;
  let text="",textScore=-1,sender="",time=null,timeField="",primarySortKey=null,secondarySortKey=null,direction="",admin=false,platformThreadId="",deliveryState="",bound=false;
  const takeText=(v,score)=>{if(typeof v!=="string")return;const x=clean(v,65536);if(x&&!encryptedPayload(x)&&score>textScore){text=x;textScore=score}};
  const takeFlags=m=>{if(!m||typeof m!=="object")return;sender=sender||clean(m.sender_fbid||m.senderId||m.sender_id||m.sender?.id||m.sender?.pk||m.author?.id||m.actor?.id,80);for(const k of ["timestamp_ms","timestampMsString","timestampMs","timestamp","timestamp_precise","clientTimestamp","client_timestamp","sentAt","sent_at","created_at","createdAt","date","datetime"]){const q=timeValue(m[k]);if(!time&&q){time=q;timeField=k}}primarySortKey=primarySortKey??sortValue(m.primarySortKey??m.primary_sort_key);secondarySortKey=secondarySortKey??sortValue(m.secondarySortKey??m.secondary_sort_key);if(m.isAdminMessage===true||m.is_admin_message===true)admin=true;const lifecycle=clean(m.sendStatus||m.send_status||m.deliveryStatus||m.delivery_status||m.status,40).toLowerCase();if(/^(sending|pending|uploading|retrying|queued)$/.test(lifecycle))deliveryState="pending";else if(/^(sent|delivered|read)$/.test(lifecycle))deliveryState=lifecycle;for(const v of [m.is_sender,m.isSender,m.isOwn,m.is_own,m.outgoing,m.isOutgoing,m.fromMe,m.from_me]){if(v===true)direction="outbound";else if(v===false&&!direction)direction="inbound"}const d=clean(m.direction,24).toLowerCase();if(["outbound","outgoing","sent"].includes(d))direction="outbound";else if(["inbound","incoming","received"].includes(d))direction="inbound"};
  for(const p of objects){const pid=normalizeMessageId(p.messageId||p.message_id||p.mid||p.offlineThreadingId||p.offline_threading_id||p.__id||p.id),associated=pid===id;for(const m of [p.message,p.currentMessageRef,p.slideMessageRef,p.messageRef,p.item,p.node]){if(!m||typeof m!=="object")continue;const mid=normalizeMessageId(m.messageId||m.message_id||m.mid||m.offlineThreadingId||m.offline_threading_id||m.__id||m.id);if(mid!==id)continue;bound=true;takeText(m.text,30);takeText(m.body,29);takeText(m.message_text,29);takeFlags(m)}if(associated||(!forcedId&&ids.size===1)){bound=true;takeText(p.text,20);takeText(p.body,19);takeFlags(p);platformThreadId=platformThreadId||clean(p.viewerThreadRef?.thread_fbid||p.threadRef?.thread_fbid||p.thread_fbid,100)}}
  if(!bound)return null;return {id,text,sender,time,timeField,primarySortKey,secondarySortKey,direction,admin,platformThreadId,deliveryState,el,score:70+(text?20:0)+(sender?8:0)+(time?12:0)+(direction?8:0)};
 }
 function subtreeAttributeIds(root){const ids=new Set(),add=v=>{const id=normalizeMessageId(v);if(id)ids.add(id)};add(root.getAttribute?.("data-message-id"));add(root.getAttribute?.("data-mid"));for(const n of root.querySelectorAll?.('[data-message-id],[data-mid]')||[]){add(n.getAttribute("data-message-id"));add(n.getAttribute("data-mid"));if(ids.size>1)break}return ids}
 function messageRoot(code,seed,pane,id){
  const explicit=seed?.closest?.('[data-message-id],[data-mid]');if(explicit&&pane.contains(explicit)&&subtreeAttributeIds(explicit).size===1)return explicit;
  /* 210.0.2: stop at the first bounded message row; never grow into a reply/thread wrapper. */
  let best=seed;const pr=pane.getBoundingClientRect();for(let n=seed,d=0;n&&n!==pane&&d<10;n=n.parentElement,d++){
   const rect=n.getBoundingClientRect();if(rect.height>Math.max(460,pr.height*.58)||rect.width>pr.width*.92)break;
   const ids=subtreeAttributeIds(n),objects=branchObjects(n);for(const x of idsIn(objects))ids.add(x);
   if(ids.size>1||ids.size===1&&!ids.has(id))break;if(ids.has(id))best=n;
   const role=n.getAttribute?.("role");if((role==="article"||role==="row"||n.matches?.('li,[data-testid*="message" i]'))&&ids.has(id))break;
  }return best
 }
 function translationFor(root,original){
  let source="immersive-translate-dom",nodes=[...root.querySelectorAll?.('.immersive-translate-target-inner')||[]];
  if(!nodes.length)nodes=[...root.querySelectorAll?.(TRANSLATION_LEAF)||[]].filter(n=>!n.querySelector?.(TRANSLATION_LEAF));
  if(!nodes.length){source="meta-native-dom";nodes=[...root.querySelectorAll?.('[data-translation],[data-testid*="translation" i],[aria-label*="translated" i],[aria-label*="译文"],[aria-label*="翻译结果"]')||[]].filter(n=>!n.matches?.('button,[role="button"]'))}
  const vals=[];for(const n of nodes){if(inReplyPreview(n,root))continue;const x=clean(n.innerText||n.textContent,65536);if(x&&x!==original&&!vals.includes(x))vals.push(x)}
  return vals.length===1?{text:vals[0],source,confidence:"high",visible:true}:null;
 }
 function facebookTranslationFor(root,original){
  /* 210.0.21: Facebook/Immersive Translate does not guarantee that the target is
     inside the data-message-id node.  It may be an adjacent child of the bounded
     single-message row.  Expand only while the scope still owns exactly one message
     id, then rank target leaves by source-body proximity.  Quoted/replied content is
     always excluded. */
  const selector='.immersive-translate-target-inner,[data-immersive-translate-translation],.immersive-translate-target-translation-block,.immersive-translate-target-translation-block-wrapper,[data-translation],[data-testid*="translation" i],[aria-label*="translated" i],[aria-label*="译文"],[aria-label*="翻译结果"],[class*="immersive-translate-target"],[class*="translation-target"]';
  const norm=v=>clean(v,65536).normalize("NFKC").replace(/\s+/g," ").trim();
  const originalNorm=norm(original);if(!originalNorm)return null;
  const nodeId=n=>clean(n?.getAttribute?.("data-message-id")||n?.getAttribute?.("data-mid"),600);
  const idsIn=n=>{const out=new Set();const add=x=>{const id=nodeId(x);if(id)out.add(id)};add(n);for(const x of n?.querySelectorAll?.('[data-message-id],[data-mid]')||[])add(x);return out};
  const rootId=nodeId(root)||[...idsIn(root)][0]||"";
  let scope=root;
  for(let p=root.parentElement,d=0;p&&d<4;d++,p=p.parentElement){const ids=idsIn(p),r=p.getBoundingClientRect?.(),rr=root.getBoundingClientRect?.();if(ids.size>1||(rootId&&ids.size===1&&!ids.has(rootId))||!r||!rr||r.height>Math.max(520,rr.height*4.5))break;scope=p}
  const owned=n=>{if(!n||!scope.contains(n))return false;for(let p=n;p&&p!==scope;p=p.parentElement){const id=nodeId(p);if(id&&rootId&&id!==rootId)return false}return true};
  const isTarget=n=>n?.matches?.(selector)||!!n?.closest?.('.immersive-translate-target-inner,[data-immersive-translate-translation],.immersive-translate-target-translation-block,[class*="immersive-translate-target"],[class*="translation-target"]');
  const sourceText=n=>{const c=n.cloneNode(true);for(const x of [...c.querySelectorAll?.(selector)||[]])x.remove();for(const x of [...c.querySelectorAll?.('[data-translation-element-mark]')||[]])if(isTarget(x)||x.tagName==='FONT')x.remove();return norm(c.innerText||c.textContent)};
  let anchors=[root,...root.querySelectorAll?.('span,div,p')||[]].filter(n=>owned(n)&&!fbInReplyPreview(n,scope)&&!isTarget(n)&&sourceText(n)&&(sourceText(n)===originalNorm||(originalNorm.length>=4&&sourceText(n).includes(originalNorm))));
  anchors.sort((a,b)=>(a.querySelectorAll?.('*').length||0)-(b.querySelectorAll?.('*').length||0));const bodyAnchor=anchors[0]||root;
  let nodes=[...scope.querySelectorAll?.(selector)||[]].filter(n=>owned(n)&&!fbInReplyPreview(n,scope));
  /* Some versions mark only a FONT leaf, while its parent carries the target class. */
  for(const n of scope.querySelectorAll?.('font[data-translation-element-mark],font[class*="immersive-translate"]')||[])if(owned(n)&&!fbInReplyPreview(n,scope)&&!nodes.includes(n))nodes.push(n);
  nodes=nodes.filter(n=>![...n.querySelectorAll?.(selector)||[]].some(d=>d!==n&&owned(d)&&!fbInReplyPreview(d,scope)));
  const br=bodyAnchor.getBoundingClientRect?.();const candidates=[];
  for(const n of nodes){const x=norm(n.innerText||n.textContent);if(!x||x===originalNorm||fbPresentationText(x))continue;const nr=n.getBoundingClientRect?.();const pos=bodyAnchor.compareDocumentPosition(n),following=!!(pos&Node.DOCUMENT_POSITION_FOLLOWING),inside=bodyAnchor.contains(n),sameParent=n.parentElement===bodyAnchor.parentElement||bodyAnchor.parentElement?.contains(n);if(!inside&&!following&&!sameParent)continue;const distance=br&&nr?Math.abs(nr.top-br.bottom)+Math.abs(nr.left-br.left)*.08:0;const score=(inside?3000:0)+(sameParent?1500:0)+(following?500:0)-distance-(x.includes(originalNorm)?2000:0);candidates.push({text:x,score})}
  candidates.sort((a,b)=>b.score-a.score||a.text.length-b.text.length);if(!candidates.length)return null;
  const best=candidates[0],ties=[...new Set(candidates.filter(x=>Math.abs(x.score-best.score)<1).map(x=>x.text))];if(ties.length!==1)return null;
  return {text:best.text,source:"facebook-message-owned-translation-dom-210021",confidence:bodyAnchor&&scope!==document.body?"high":"medium",visible:true};
 }

 function originalText(root){const clone=root.cloneNode(true);for(const n of clone.querySelectorAll?.(`${TRANSLATION_WRAPPER},[data-translation],[data-testid*="translation" i],[aria-label*="translated" i],[aria-label*="译文"],[aria-label*="翻译结果"]`)||[])n.remove();for(const n of clone.querySelectorAll?.('time,[data-juba-time-marker]')||[])if(!clean(n.textContent,100).match(/[A-Za-z\u4e00-\u9fff]{3,}/))n.remove();return clean(clone.innerText||clone.textContent,65536)}
 const IG_OPERATION_TEXT=/(?:leave a reaction|react to|reply to|more options|unsend|forward|copy|report|对.*(?:消息)?留下心情|回复来自|回复.*消息|查看更多选项|更多选项|撤回|转发|复制|举报)/i;
 function igOperationNode(el){if(!el||el.nodeType!==1)return false;const role=clean(el.getAttribute?.("role"),40),label=clean(el.getAttribute?.("aria-label")||el.getAttribute?.("title"),500);return el.matches?.('button,[role="button"],[role="menu"],[role="menuitem"],[aria-haspopup="menu"]')||role==="button"||IG_OPERATION_TEXT.test(label)}
 function igTextPolluted(value){const x=clean(value,65536);return IG_OPERATION_TEXT.test(x)||/(?:更多选项|more options).*(?:更多选项|more options)/i.test(x)}
 function igOriginalText(root){
  if(!root)return "";const clone=root.cloneNode(true);stripSemanticReplyPreviews(clone);
  for(const n of clone.querySelectorAll?.(`${TRANSLATION_WRAPPER},${IG_REPLY_PREVIEW_SELECTOR},button,[role="button"],[role="menu"],[role="menuitem"],[aria-haspopup="menu"],time,[datetime],[data-juba-time-marker]`)||[])n.remove();
  for(const n of [...clone.querySelectorAll?.('[aria-label],[title]')||[]])if(IG_OPERATION_TEXT.test(clean(n.getAttribute("aria-label")||n.getAttribute("title"),500)))n.remove();
  const leaves=[];for(const n of clone.querySelectorAll?.('span,div,p,a')||[]){if(n.children.length||n.closest?.(TRANSLATION_WRAPPER)||igOperationNode(n))continue;const x=clean(n.textContent,65536);if(x&&!IG_OPERATION_TEXT.test(x)&&!leaves.includes(x))leaves.push(x)}
  const value=clean(leaves.join(" "),65536);return igTextPolluted(value)?"":value
 }
 function parseDateText(value,base=new Date(),weekdayMode="past"){
  const x=clean(value,300);if(!x)return null;const clock=(h,ap)=>{h=+h;if(ap&&/^p/i.test(ap)&&h<12)h+=12;if(ap&&/^a/i.test(ap)&&h===12)h=0;return h};
  let m=x.match(/(20\d{2})[年\/-](\d{1,2})[月\/-](\d{1,2})日?(?:\s+|[,，]\s*)(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?/i);if(m)return new Date(+m[1],+m[2]-1,+m[3],clock(m[4],m[7]),+m[5],+(m[6]||0)).getTime();
  m=x.match(/(?:今天|Today)\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?/i);if(m)return new Date(base.getFullYear(),base.getMonth(),base.getDate(),clock(m[1],m[4]),+m[2],+(m[3]||0)).getTime();
  m=x.match(/(?:昨天|Yesterday)\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?/i);if(m)return new Date(base.getFullYear(),base.getMonth(),base.getDate()-1,clock(m[1],m[4]),+m[2],+(m[3]||0)).getTime();
  m=x.match(/^(?:(?:周|星期)([一二三四五六日天])|(Sun|Mon|Tue|Wed|Thu|Fri|Sat)(?:day)?)\s*[,，]?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?$/i);if(m){const zh={日:0,天:0,一:1,二:2,三:3,四:4,五:5,六:6},en={sun:0,mon:1,tue:2,wed:3,thu:4,fri:5,sat:6},target=m[1]?zh[m[1]]:en[m[2].slice(0,3).toLowerCase()],d=new Date(base.getFullYear(),base.getMonth(),base.getDate(),clock(m[3],m[6]),+m[4],+(m[5]||0));let delta=target-d.getDay();if(weekdayMode==="forward"){if(delta<0)delta+=7}else if(delta>0)delta-=7;d.setDate(d.getDate()+delta);return d.getTime()}
  m=x.match(/^(\d{1,2})[\/-](\d{1,2})(?:[\/-](20\d{2}))?\s+[,]?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?$/i);if(m){let year=+(m[3]||base.getFullYear()),d=new Date(year,+m[1]-1,+m[2],clock(m[4],m[7]),+m[5],+(m[6]||0));if(!m[3]&&d.getTime()>base.getTime()+86400000)d.setFullYear(year-1);return d.getTime()}
  if(/20\d{2}[-/]|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/i.test(x)){const t=Date.parse(x);if(Number.isFinite(t))return t}
  m=x.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?$/i);if(m)return new Date(base.getFullYear(),base.getMonth(),base.getDate(),clock(m[1],m[4]),+m[2],+(m[3]||0)).getTime();return null;
 }
 function directText(el){let x="";for(const n of el.childNodes||[])if(n.nodeType===3)x+=" "+n.nodeValue;return clean(x,300)}
 const READ_STATUS=/^(?:昨天)?已读$|^(?:seen|read|delivered|sent)(?:\s+(?:yesterday|today))?$/i;
 function dateMarkers(pane,code){
  const out=[],seen=new Set(),deadline=performance.now()+180;let scanned=0,lastTime=0,dayBase=new Date();
  const selector=code==="instagram"?'time,[datetime],span,div':'time,[datetime],[title],[aria-label],span,div';
  for(const el of pane.querySelectorAll(selector)){
   if(performance.now()>deadline||scanned++>16000)break;if(code==="instagram"&&igOperationNode(el))continue;
   const raw=clean(el.getAttribute?.("datetime")||(code==="instagram"?"":el.getAttribute?.("title")||el.getAttribute?.("aria-label"))||directText(el),300),bare=/^\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?$/i.test(raw),weekday=/^(?:(?:周|星期)[一二三四五六日天]|(?:Sun|Mon|Tue|Wed|Thu|Fri|Sat)(?:day)?)\s*[,，]?\s*\d{1,2}:\d{2}/i.test(raw),dated=/(?:20\d{2}|今天|昨天|Today|Yesterday|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)|\d{1,2}[\/-]\d{1,2})/i.test(raw);
   if(!raw||READ_STATUS.test(raw)||(!dated&&!weekday&&!bare&&!el.hasAttribute?.("datetime")))continue;
   let t=timeValue(el.getAttribute?.("datetime"));
   if(!t){
    if(code==="facebook"){
     /* FB relative labels are independent: weekday = most recent occurrence;
        a clock without a calendar label always belongs to today. Never inherit
        a preceding weekday/date marker. */
     t=parseDateText(raw,new Date(),"past");
    }else{
     t=parseDateText(raw,dayBase,lastTime?"forward":"past");
     if(bare&&lastTime&&t&&t<lastTime-43200000)t+=86400000;
    }
   }
   if(!t)continue;
   if(code!=="facebook"){dayBase=new Date(t);lastTime=t}
   const key=t+"|"+raw;if(seen.has(key))continue;seen.add(key);
   out.push({el,time:t,raw,precision:bare||weekday?"minute_group":timestampPrecision(raw),bareClock:bare,weekday,resolverVersion:code==="facebook"&&(bare||weekday)?"fb-relative-calendar-v3":weekday?"ig-weekday-sequence-v2":""})
  }
  return out
 }
 function timestampPrecision(value){const x=clean(value,300);if(!x)return "unresolved";if(/(?:T|\s)\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?/i.test(x)||/\d{1,2}:\d{2}:\d{2}/.test(x))return "exact";if(/\d{1,2}:\d{2}/.test(x))return "minute";return "group"}
 function timeFromDom(root,markers,code){const selector=code==="instagram"?'time,[datetime]':'time,[datetime],[title],[aria-label]';for(const el of [root,...root.querySelectorAll?.(selector)||[]]){if((code==="instagram"&&igOperationNode(el))||inReplyPreview(el,root))continue;const values=code==="instagram"?[[el.getAttribute?.("datetime"),"same-message-dom-datetime"]]:[[el.getAttribute?.("datetime"),"same-message-dom-datetime"],[el.getAttribute?.("title"),"same-message-title"],[el.getAttribute?.("aria-label"),"same-message-aria"],[directText(el),"same-message-visible-text"]];for(const [v,source] of values){const t=timeValue(v)||parseDateText(v);if(t){const precision=timestampPrecision(v),authenticity=source==="same-message-dom-datetime"&&precision==="exact"?"platform-dom-datetime":"display-time";return {time:t,source,authenticity,confidence:authenticity==="platform-dom-datetime"?"high":precision==="exact"?"medium":"medium",precision,resolverVersion:code==="facebook"&&(/^(?:\d{1,2}:\d{2}|(?:(?:周|星期)[一二三四五六日天]|(?:Sun|Mon|Tue|Wed|Thu|Fri|Sat)(?:day)?))/i.test(clean(v,300)))?"fb-relative-calendar-v3":""}}}}let best=null;for(const m of markers){const pos=m.el.compareDocumentPosition(root);if(pos&Node.DOCUMENT_POSITION_FOLLOWING)best=m}return best?{time:best.time,source:best.weekday?(code==="facebook"?"facebook-recent-weekday-v3":"preceding-weekday-marker-sequence-v2"):best.bareClock?(code==="facebook"?"facebook-today-clock-v3":"preceding-visible-clock"):"preceding-date-marker",authenticity:"display-time",confidence:best.weekday?"medium":best.bareClock?"medium":"low",precision:"minute_group",resolverVersion:best.resolverVersion||""}:null}
 function visualDirection(root,pane){const pr=pane.getBoundingClientRect(),mid=pr.left+pr.width/2;let target=null,best=-Infinity;for(const el of [root,...(root.querySelectorAll?.('div,span,p')||[])]){const t=clean(el.innerText||el.textContent,300);if(!t||inReplyPreview(el,root))continue;const q=el.getBoundingClientRect();if(q.width<12||q.width>pr.width*.82||q.height<8)continue;const offset=Math.abs((q.left+q.width/2)-mid),score=offset*3-Math.abs(q.width-pr.width*.28)-Math.min(q.height,300)*.05;if(score>best){best=score;target=el}}if(!target)return "";const q=target.getBoundingClientRect(),c=q.left+q.width/2,delta=Math.max(28,pr.width*.07);return c>mid+delta?"outbound":c<mid-delta?"inbound":""}
 function fbA11yDirection(root,body=""){
  const want=clean(body,4096).normalize("NFKC");let answer=null;
  for(const el of [root,...(root.querySelectorAll?.('[aria-label],[title]')||[])]){if(fbInReplyPreview(el,root))continue;const x=clean(el.getAttribute?.('aria-label')||el.getAttribute?.('title'),65536);if(!x||FB_REPLY_HEADER.test(x)||fbPresentationText(x))continue;
   const labelled=fbAccessibilityBody(x),got=clean(labelled,4096).normalize("NFKC");if(want&&got&&got!==want&&!got.includes(want)&&!want.includes(got))continue;
   let value="";if(/^(?:Enter[,，]?\s*)?(?:消息由(?:你|本人)发送于|message (?:sent by|from) (?:you|me)\b|you sent (?:a )?message\b)/i.test(x))value="outbound";/* 210.0.18: named sender may be the logged-in Page/business; use model/sender-id/geometry. */
   if(value){if(got&&want)return {value,source:"facebook-a11y-sender",confidence:"high"};if(!want&&!answer)answer={value,source:"facebook-a11y-sender",confidence:"medium"}}
  }return answer
 }
 function fbGeometryDirection(root,pane,body){const pr=pane.getBoundingClientRect(),want=clean(body,4096),mid=pr.left+pr.width/2;let chosen=null,best=-Infinity;for(const el of [root,...(root.querySelectorAll?.('div,span,p')||[])]){if(fbInReplyPreview(el,root))continue;const txt=clean(el.innerText||el.textContent,4096),q=el.getBoundingClientRect();if(!txt||q.width<10||q.height<7||q.width>pr.width*.84)continue;const exact=want&&txt===want,contains=want&&(txt.includes(want)||want.includes(txt));const center=q.left+q.width/2,offset=Math.abs(center-mid),score=(exact?10000:contains?5000:0)+offset*4-q.width*.15-q.height*.02;if(score>best){best=score;chosen=el}}if(!chosen)return null;const q=chosen.getBoundingClientRect(),ratio=(q.left+q.width/2-pr.left)/Math.max(pr.width,1);if(ratio>=.56)return {value:"outbound",source:"facebook-bubble-geometry",confidence:"high"};if(ratio<=.44)return {value:"inbound",source:"facebook-bubble-geometry",confidence:"high"};return null}
 function facebookDirection(root,pane,rec,ownIdentity,body){
  /* 210.0.20: the rendered bubble is the authoritative evidence for a visible
     Facebook message.  R2/210.0.18 returned a stale model direction before the
     right-side bubble was inspected, which flipped the first agent message. */
  const geometry=fbGeometryDirection(root,pane,body);if(geometry)return geometry;
  const sender=clean(rec?.sender,80),owner=clean(ownIdentity,80);if(sender&&owner)return {value:sender===owner?"outbound":"inbound",source:"facebook-message-sender-id",confidence:"high"};
  const a=fbA11yDirection(root,body);if(a)return a;
  const nativeId=!/^fbdom\d*\./i.test(clean(rec?.id,512)),nativeSource=/react-mid|data-message-id/i.test(clean(rec?.captureSource||rec?.source,120));
  if(nativeId&&nativeSource&&(rec?.direction==="inbound"||rec?.direction==="outbound"))return {value:rec.direction,source:"facebook-message-model",confidence:"medium"};
  return {value:"",source:"none",confidence:"low"}
 }
 function mediaImages(el){return [...el.querySelectorAll?.("img")||[]].filter(img=>{if(img.closest?.('header,nav,[role="navigation"],[role="banner"],[role="button"],button,[role="menu"],[role="menuitem"],a[href*="/accounts/"],a[href*="/profiles/"]'))return false;const r=img.getBoundingClientRect(),src=clean(img.currentSrc||img.src,4096),label=clean(img.getAttribute?.("alt")||img.getAttribute?.("aria-label"),300);if(r.width<36||r.height<36||!src||/avatar|profile|头像|reaction|seen|已读/i.test(label))return false;const style=getComputedStyle(img);if(style.borderRadius==="50%"&&Math.min(r.width,r.height)<=72)return false;return true})}
 function stickerImages(el){return mediaImages(el).filter(img=>{const r=img.getBoundingClientRect(),label=clean(img.getAttribute?.("alt")||img.getAttribute?.("aria-label")||img.getAttribute?.("data-testid"),300);return /sticker|gif|emoji|表情|贴纸/i.test(label)||(!clean(el.innerText||el.textContent,100)&&r.width>=72&&r.height>=72&&r.width<=360&&r.height<=360)})}
 function accessibleEmojiText(el){const vals=[];for(const n of el.querySelectorAll?.('[role="img"][aria-label],img[alt]')||[]){if(n.closest?.('button,[role="button"],[role="menu"],[role="menuitem"]'))continue;const v=clean(n.getAttribute("aria-label")||n.getAttribute("alt"),80);if(v&&/[\p{Extended_Pictographic}\u2600-\u27BF]/u.test(v)&&!vals.includes(v))vals.push(v)}return clean(vals.join(" "),500)}
 function contentType(el,text){if(el.querySelector?.("video"))return "video";if(el.querySelector?.("audio"))return "audio";if(el.querySelector?.('a[download]'))return "file";if(stickerImages(el).length)return "sticker";if(mediaImages(el).length)return text?"text":"image";return text?"text":"unknown"}
 function trustedEmptyMedia(root,rec,kind){if(!["image","video","audio","file","sticker"].includes(kind)||rec?.idConfidence!=="high")return false;const source=clean(rec?.source,80),strongId=/data-message-id|react-mid/.test(source)||root.hasAttribute?.("data-message-id")||root.hasAttribute?.("data-mid"),model=rec?.threadEvidenceStatus==="MODEL_CONFIRMED";if(!strongId&&!model)return false;if(kind==="image"&&!mediaImages(root).length)return false;return true}
 function collectReactCandidates(pane,deadline,maxNodes=1200){const out=[],seen=new Set(),all=[pane,...pane.querySelectorAll("*")];let scanned=0,budgetHit=false,timeHit=false;const visit=el=>{if(seen.has(el))return true;if(performance.now()>deadline){timeHit=true;return false}if(scanned++>=maxNodes){budgetHit=true;return false}seen.add(el);if(ownReactEntries(el).length)out.push(el);return true};for(let i=all.length-1;i>=0;i--)if(!visit(all[i]))break;if(!timeHit&&!budgetHit)for(let i=0;i<all.length;i++)if(!visit(all[i]))break;state.diagnostics.scan={domNodes:all.length,scannedNodes:scanned,reactCandidates:out.length,timeBudgetHit:timeHit,nodeBudgetHit:budgetHit,order:"bottom-first",at:Date.now()};return out}
 function fnv1a(value){let h=2166136261;for(let i=0;i<value.length;i++){h^=value.charCodeAt(i);h=Math.imul(h,16777619)}return (h>>>0).toString(36)}
 function domBaselineRows(code,pane){
  const pr=pane.getBoundingClientRect(),rows=[],seen=new Set(),add=(el,source)=>{
   if(!el||seen.has(el)||!pane.contains(el)||!visible(el)||el.matches?.(TRANSLATION_WRAPPER+','+TRANSLATION_LEAF)||el.closest?.(TRANSLATION_WRAPPER+','+TRANSLATION_LEAF)||el.closest?.('[contenteditable="true"],textarea,[role="dialog"],[role="menu"],nav')||(code==="facebook"?(fbNestedMessageRoot(el,pane)||fbInReplyPreview(el,pane)):inReplyPreview(el,pane))||igPendingSend(el))return;
   const r=el.getBoundingClientRect();if(r.width<18||r.height<12||r.height>Math.max(560,pr.height*.72)||r.right<pr.left||r.left>pr.right)return;
   let text=code==="instagram"?igOriginalText(el):code==="facebook"?fbOriginalText(el):originalText(el);if(code==="instagram"&&!text)text=accessibleEmojiText(el);const kind=contentType(el,text);if(!text&&!["image","video","audio","file","sticker"].includes(kind))return;
   const direction=code==="facebook"?(fbGeometryDirection(el,pane,text)?.value||fbA11yDirection(el,text)?.value||""):visualDirection(el,pane);if(!direction)return;
   seen.add(el);rows.push({el,source,text,kind,direction,top:r.top,left:r.left});
  };
  /* Stable semantic/attribute rows first. */
  for(const el of pane.querySelectorAll('[data-message-id],[data-mid],[role="article"],[role="row"],li,[data-testid*="message" i],[aria-label*="message" i],[aria-label*="消息"]'))add(el,"meta-dom-semantic-row");
  if(code==="instagram"){
   /* React-less fallback: start from visible textual/media leaves, then select the
      smallest side-aligned ancestor which still looks like one message bubble. */
   const leaves=pane.querySelectorAll('span[dir="auto"],div[dir="auto"],p,img,[role="img"],video');let scanned=0;
   for(const leaf of leaves){if(scanned++>2400)break;if(!visible(leaf)||leaf.matches?.(TRANSLATION_WRAPPER+','+TRANSLATION_LEAF)||leaf.closest?.(TRANSLATION_WRAPPER+','+TRANSLATION_LEAF)||leaf.closest?.('[contenteditable="true"],header,nav,[role="dialog"],[role="menu"]')||inReplyPreview(leaf,pane))continue;
    let best=null;for(let n=leaf,d=0;n&&n!==pane&&d<7;n=n.parentElement,d++){
     const r=n.getBoundingClientRect();if(r.width<18||r.height<12||r.width>pr.width*.88||r.height>420)continue;
     if(code==="facebook"?(fbA11yDirection(n)||fbGeometryDirection(n,pane,fbOriginalText(n))):visualDirection(n,pane))best=n;
     if(n.matches?.('[role="article"],[role="row"],li,[data-testid*="message" i]'))break;
    }if(best)add(best,"instagram-dom-leaf-row");
   }
  }
  rows.sort((a,b)=>a.top-b.top||a.left-b.left);
  /* Remove nested duplicates, preferring the smaller boundary. */
  return rows.filter((row,i,all)=>!all.some((other,j)=>j!==i&&row.el.contains(other.el)&&other.text===row.text&&other.el.getBoundingClientRect().height<=row.el.getBoundingClientRect().height));
 }
 function splitLeadingMessageDate(value,code){if(code!=="instagram")return null;const src=clean(value,65536),m=src.match(/^((?:19|20)\d{2})[\/年.\-](\d{1,2})(?:[\/月.\-](\d{1,2})日?)?\s+([01]?\d|2[0-3])[:：.](\d{2})\s+([\s\S]+)$/);if(!m||!m[3]||!clean(m[6],65536))return null;const d=new Date(Number(m[1]),Number(m[2])-1,Number(m[3]),Number(m[4]),Number(m[5]),0,0);if(!Number.isFinite(d.getTime()))return null;return {time:d.getTime(),text:clean(m[6],65536),raw:m[0].slice(0,m[0].length-m[6].length).trim()}}
function dedupeFacebookRowsInPlace(rows){
 const norm=v=>clean(v,65536).normalize("NFKC").replace(/\s+/g," ").trim();
 const groups=new Map();for(const row of rows){const t=Number(row.occurredAt)||0,key=[row.contentType,norm(row.text),t?Math.trunc(t/60000):"u"].join("|");if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row)}
 const drop=new Set();for(const list of groups.values()){const native=list.filter(x=>!/^fbdom\d*\./i.test(clean(x.externalMessageId,512))),fallback=list.filter(x=>/^fbdom\d*\./i.test(clean(x.externalMessageId,512)));const used=new Set();for(const f of fallback){let best=null,dist=Infinity;for(const n of native){if(used.has(n))continue;const d=Math.abs(Number(n.domOrdinal)-Number(f.domOrdinal));if(d<dist){dist=d;best=n}}if(best&&dist<=2){used.add(best);drop.add(f)}}}
 if(drop.size){const kept=rows.filter(x=>!drop.has(x));rows.splice(0,rows.length,...kept)}return rows
 }
function canonicalIgBody(value){const x=clean(value,65536).normalize("NFKC");return x.replace(/^(?:19|20)\d{2}[\/年.\-]\d{1,2}(?:[\/月.\-]\d{1,2}日?)?\s+(?:[01]?\d|2[0-3])[:：.]\d{2}\s+/,"")} function baselineFingerprint(code,tid,row,dt,occurrence){const body=code==="instagram"?canonicalIgBody(row.text):clean(row.text,4096).normalize("NFKC");const minute=dt?.time?Math.trunc(Number(dt.time)/60000):"unresolved";if(code==="facebook")return "fbdom1."+fnv1a([code,tid,row.kind,body,minute,occurrence].join("|"));return "dom4."+fnv1a([code,tid,row.direction,row.kind,body,minute,occurrence].join("|"))/* snapshot-neighbour excluded; mutable presentation fields excluded; unresolved DOM4 is never admitted */}
 function refineChronology(rows,code){
  /* DOM is chronological. Meta often exposes only one minute marker for several
     bubbles; use stable sub-minute offsets solely as an ordering key. */
  for(let i=0;i<rows.length;i++){rows[i].chronologyOrdinal=i+1;rows[i].displayOccurredAt=Number(rows[i].occurredAt)||null}
   if(code==="facebook"){for(const row of rows){const t=Number(row.occurredAt)||0;if(t&&row.timestampPrecision!=="exact"){row.occurredAt=Math.trunc(t/60000)*60000;row.displayOccurredAt=row.occurredAt;row.timeGroupAt=row.occurredAt;row.timestampPrecision="minute";row.timestampAuthenticity="facebook-display-minute";row.chronologyRefined=false}}return}
  let i=0;while(i<rows.length){const t=Number(rows[i].occurredAt)||0;if(!t){i++;continue}const minute=Math.trunc(t/60000),start=i;while(i+1<rows.length&&Number(rows[i+1].occurredAt)>0&&Math.trunc(Number(rows[i+1].occurredAt)/60000)===minute)i++;const end=i;
   if(end>start){let last=minute*60000-1;for(let k=start;k<=end;k++){const exact=rows[k].timestampPrecision==="exact"&&rows[k].timestampAuthenticity==="platform-message-record",original=Number(rows[k].occurredAt);if(exact&&original>last){last=original;continue}const room=Math.max(1,minute*60000+59999-last),remaining=end-k+1,step=Math.max(1,Math.floor(room/remaining));last=Math.min(minute*60000+59999,last+step);rows[k].occurredAt=last;rows[k].timeGroupAt=minute*60000;rows[k].timestampPrecision="minute_ordered";rows[k].timestampAuthenticity="dom-relative-order";rows[k].chronologyRefined=true}}
   i++;
  }
  /* 210.0.12: never invent timestamps for unanchored bubbles. */
  return rows
 }
 function extractMessages(code,tid,pane,ownIdentity=""){
  const generation=state.generation,routeBefore=route(),candidates=new Map(),pendingIds=new Set(),markers=dateMarkers(pane,code),deadline=performance.now()+(code==="instagram"?120:45);
   const put=(rec,root,source)=>{if(!rec?.id||!root)return;rec.captureSource=source;if(code==="instagram"&&(rec.deliveryState==="pending"||igPendingSend(root))){pendingIds.add(rec.id);return}if(inReplyPreview(root,pane))return;const structured=clean(rec.text,65536),fb=code==="facebook"?facebookText(structured,root):null,reply=null,domText=code==="instagram"?(structured?"":igOriginalText(root)):code==="facebook"?fb.text:originalText(root),chosen=code==="facebook"?fb.text:(structured||domText),textSource=code==="facebook"?fb.source:structured?"react-structured":domText?(code==="instagram"?"ig-text-leaf":"container-dom"):"none",tr=code==="facebook"?facebookTranslationFor(root,chosen):translationFor(root,chosen),area=Math.min(root.getBoundingClientRect().width*root.getBoundingClientRect().height/1000,40),polluted=code==="instagram"?igTextPolluted(chosen):code==="facebook"?fb.polluted:false,score=(rec.score||0)+(textSource==="react-structured"?70:domText?20:0)+(tr?15:0)+area-(polluted?200:0),old=candidates.get(rec.id);if(!old||score>old.score)candidates.set(rec.id,{...rec,el:root,text:polluted?"":chosen,reply,textSource,bodyPolluted:polluted,score,source})};
  /* Platform IDs remain the preferred source, but no React object is required. */
  for(const row of pane.querySelectorAll('[data-message-id],[data-mid]')){if(performance.now()>deadline)break;const id=normalizeMessageId(row.getAttribute("data-message-id")||row.getAttribute("data-mid"));if(!id)continue;let rec=null;for(const el of [row,...row.querySelectorAll("*")]){if(!ownReactEntries(el).length)continue;const q=entityRecord(code,el,id);if(q&&(!rec||q.score>rec.score))rec=q}rec=rec||{id,el:row,score:60,text:"",sender:"",time:null,primarySortKey:null,secondarySortKey:null,direction:"",admin:false,platformThreadId:"",deliveryState:"",idConfidence:"high",threadEvidenceStatus:"DOM_CONTEXT_CONFIRMED"};put(rec,row,"data-message-id")}
  /* Fiber/page model enriches DOM rows; it is no longer the only admission path. */
  for(const el of collectReactCandidates(pane,deadline,6000)){if(performance.now()>deadline)break;const rec=entityRecord(code,el);if(!rec)continue;rec.idConfidence="high";rec.threadEvidenceStatus=rec.platformThreadId&&clean(rec.platformThreadId,256)===clean(tid,256)?"MODEL_CONFIRMED":"DOM_CONTEXT_CONFIRMED";put(rec,messageRoot(code,el,pane,rec.id),code==="instagram"?"instagram-react-mid":"meta-react-mid")}
  /* DOM baseline fills messages whose Meta internals are absent or changed. */
  const baselines=domBaselineRows(code,pane),occurrences=new Map();
   for(let bi=0;bi<baselines.length;bi++){const row=baselines[bi],lead=splitLeadingMessageDate(row.text,code);if(lead)row.text=lead.text;if([...candidates.values()].some(x=>x.el===row.el||x.el.contains?.(row.el)||row.el.contains?.(x.el)))continue;const dt=timeFromDom(row.el,markers,code),base=[row.direction,row.kind,clean(row.text,4096).normalize("NFKC"),dt?.time?Math.trunc(dt.time/60000):"na"].join("|"),occKey=base,occ=(occurrences.get(occKey)||0)+1;occurrences.set(occKey,occ);const id=baselineFingerprint(code,tid,row,dt,occ);put({id,text:row.text,sender:"",time:dt?.time||null,primarySortKey:null,secondarySortKey:null,direction:row.direction,admin:false,platformThreadId:"",deliveryState:"",score:42,idConfidence:"medium",threadEvidenceStatus:"DOM_CONTEXT_CONFIRMED",domTimestamp:dt,domTextOnly:true},row.el,row.source)}
  if(generation!==state.generation||routeBefore!==route())return [];
  const ordered=[...candidates.values()].sort((a,b)=>{const ar=a.el.getBoundingClientRect(),br=b.el.getBoundingClientRect();return ar.top-br.top||ar.left-br.left}),out=[];
  for(let domOrdinal=0;domOrdinal<ordered.length;domOrdinal++){const rec=ordered[domOrdinal];if(rec.admin||rec.deliveryState==="pending"||(code==="instagram"&&igPendingSend(rec.el))){pendingIds.add(rec.id);continue}if(inReplyPreview(rec.el,pane))continue;const root=rec.el;let text=rec.text||(code==="instagram"?(igOriginalText(root)||accessibleEmojiText(root)):code==="facebook"?fbOriginalText(root):originalText(root));if(code==="facebook"&&fbTextPolluted(text))continue;let direction=rec.direction,directionSource=rec.direction?"same-message-entity-or-dom":"",directionConfidence=rec.direction?"high":"medium";if(code==="facebook"){const fd=facebookDirection(root,pane,rec,ownIdentity,text);direction=fd.value;directionSource=fd.source;directionConfidence=fd.confidence}else{if(!direction&&rec.sender&&ownIdentity){direction=clean(rec.sender,80)===clean(ownIdentity,80)?"outbound":"inbound";directionSource="same-message-sender";directionConfidence="high"}if(!direction){direction=visualDirection(root,pane);directionSource="same-message-layout";directionConfidence="medium"}}if(direction!=="inbound"&&direction!=="outbound")continue;const translation=code==="facebook"?facebookTranslationFor(root,text):translationFor(root,text),kind=contentType(root,text);let dt=rec.time?{time:rec.time,source:"platform-message-record:"+clean(rec.timeField||"timestamp",60),authenticity:"platform-message-record",confidence:"high",precision:"exact"}:timeFromDom(root,markers,code);const leading=!rec.time&&code==="instagram"?splitLeadingMessageDate(text,code):null;if(leading){text=leading.text;dt={time:leading.time,source:"same-message-visible-date-prefix",authenticity:"platform-dom-datetime",confidence:"high",precision:"minute",raw:leading.raw}}const mediaKind=["image","video","audio","file","sticker"].includes(kind);if(code==="instagram"&&!clean(text,65536)&&!mediaKind)continue;if(!text&&!translation&&kind==="unknown")continue;if(!text&&!translation&&!trustedEmptyMedia(root,rec,kind))continue;
   /* A differing deep thread ID is diagnostic unless it is a proven direct conflict;
      route/canonical aliases can legitimately differ on Meta E2EE. */
   const evidence=rec.threadEvidenceStatus||"DOM_CONTEXT_CONFIRMED";
   out.push({externalMessageId:rec.id,threadId:tid,platformThreadId:rec.platformThreadId||undefined,direction,contentType:kind,text:text||null,...(dt?.time?{occurredAt:dt.time,timestampSource:dt.source,timestampPrecision:dt.precision||(rec.time?"exact":"unresolved")}:{}),...(rec.primarySortKey!==null?{primarySortKey:rec.primarySortKey}:{}),...(rec.secondarySortKey!==null?{secondarySortKey:rec.secondarySortKey}:{}),...(translation?{translation}:{}),...(rec.reply?{reply:rec.reply}:{}),domOrdinal,idConfidence:rec.idConfidence||"high",directionConfidence,directionSource,platformCode:code,threadEvidenceStatus:evidence,admissionSource:evidence,discoverySource:rec.source,textSource:rec.textSource||"unknown",bodyPolluted:rec.bodyPolluted===true,deliveryState:"sent",hasMedia:["image","video","audio","file","sticker"].includes(kind),mediaEvidence:["image","video","audio","file","sticker"].includes(kind)?"same-message-dom-media":null,timestampResolved:!!dt?.time,timeConfidence:dt?.confidence||"none",timestampAuthenticity:dt?.authenticity||"unverified",timestampResolverVersion:dt?.resolverVersion||"",generation,routeSignature:routeBefore})}
  refineChronology(out,code);if(code==="facebook")dedupeFacebookRowsInPlace(out);const cacheKey=code+"|"+tid,cache=state.messageCaches.get(cacheKey)||new Map();
  for(const id of pendingIds)cache.delete(id);for(const m of out){const old=cache.get(m.externalMessageId);if(!old)cache.set(m.externalMessageId,m);else if(messageQuality(m)>=messageQuality(old)){const oldExact=old.timestampPrecision==="exact"&&old.timestampAuthenticity==="platform-message-record",nextExact=m.timestampPrecision==="exact"&&m.timestampAuthenticity==="platform-message-record",resolverUpgrade=((m.timestampResolverVersion==="ig-weekday-sequence-v2"&&old.timestampResolverVersion!=="ig-weekday-sequence-v2")||(m.timestampResolverVersion==="fb-relative-calendar-v3"&&old.timestampResolverVersion!=="fb-relative-calendar-v3"))&&!oldExact;cache.set(m.externalMessageId,{...old,...m,occurredAt:nextExact||resolverUpgrade?m.occurredAt:oldExact?old.occurredAt:(old.occurredAt||m.occurredAt),displayOccurredAt:resolverUpgrade?m.displayOccurredAt:(old.displayOccurredAt||m.displayOccurredAt),timeGroupAt:resolverUpgrade?m.timeGroupAt:(old.timeGroupAt||m.timeGroupAt),chronologyOrdinal:old.chronologyOrdinal||m.chronologyOrdinal,translation:m.translation||old.translation,reply:m.reply||old.reply,messageAliases:[...new Set([...(old.messageAliases||[]),...(m.messageAliases||[])])]})}else if(m.directionConfidence==="high"&&m.direction!==old.direction&&["same-message-sender","same-message-layout","facebook-message-sender-id","facebook-bubble-geometry","facebook-a11y-sender"].includes(m.directionSource)){cache.set(m.externalMessageId,{...old,direction:m.direction,directionSource:m.directionSource,directionConfidence:"high",deliveryState:m.deliveryState||old.deliveryState})}else if((m.reply&&!old.reply)||(m.translation&&(!old.translation||(m.translation.confidence==="high"&&old.translation.confidence!=="high")||(m.translation.source?.includes("210021")&&!old.translation.source?.includes("210021"))))){/* 210.2.62: delayed translation/reply enrichment is snapshot-quality independent. */cache.set(m.externalMessageId,{...old,...(m.reply&&!old.reply?{reply:m.reply}:{}),...(m.translation?{translation:m.translation}:{}),messageAliases:[...new Set([...(old.messageAliases||[]),...(m.messageAliases||[])])]})}}
  /* 210.0.1: fold a temporary DOM identity into one native Meta identity only when
     normalized body, direction and displayed minute form a bijection. Repeated
     legitimate native messages are never folded. */
  const entityBase=m=>[clean(m.text,65536).normalize("NFKC").toLowerCase(),m.direction].join("|");
  const groups=new Map();for(const m of cache.values()){if(!clean(m.text,65536))continue;const k=entityBase(m),g=groups.get(k)||{native:[],dom:[]};(String(m.externalMessageId).startsWith("dom.")?g.dom:g.native).push(m);groups.set(k,g)}
  for(const g of groups.values())if(g.native.length===1&&g.dom.length===1){const keep=g.native[0],tmp=g.dom[0],nt=Number(keep.occurredAt)||0,dt=Number(tmp.occurredAt)||0,sameMinute=nt&&dt&&Math.trunc(nt/60000)===Math.trunc(dt/60000),lifecycleUpgrade=nt&&!dt&&tmp.direction==="outbound"&&Date.now()-nt<86400000;if(sameMinute||lifecycleUpgrade){keep.messageAliases=[...new Set([...(keep.messageAliases||[]),tmp.externalMessageId])];cache.delete(tmp.externalMessageId)}}
  if(cache.size>1200){const rows=[...cache.values()].sort((a,b)=>(a.occurredAt||0)-(b.occurredAt||0)||a.domOrdinal-b.domOrdinal);cache.clear();for(const m of rows.slice(-1000))cache.set(m.externalMessageId,m)}
  state.messageCaches.set(cacheKey,cache);
  const visibleIds=out.map(m=>m.externalMessageId),previous=state.orderCaches.get(cacheKey)||[],alive=new Set(cache.keys()),base=previous.filter(id=>alive.has(id));let merged=[...base];
  if(!merged.length)merged=[...visibleIds];else for(let i=0;i<visibleIds.length;i++){const id=visibleIds[i];if(merged.includes(id))continue;let next="",prev="";for(let j=i+1;j<visibleIds.length;j++)if(merged.includes(visibleIds[j])){next=visibleIds[j];break}for(let j=i-1;j>=0;j--)if(merged.includes(visibleIds[j])){prev=visibleIds[j];break}if(next)merged.splice(merged.indexOf(next),0,id);else if(prev)merged.splice(merged.indexOf(prev)+1,0,id);else merged.push(id)}
  for(const id of cache.keys())if(!merged.includes(id))merged.push(id);state.orderCaches.set(cacheKey,merged);
  const platformOrdered=merged.map(id=>cache.get(id)).filter(m=>m&&m.threadId===tid&&m.generation===generation);for(let i=0;i<platformOrdered.length;i++){const x=platformOrdered[i];x.platformOrder=i+1;x.platformOrderSource="dom-overlap-merge";if(x.timestampAuthenticity==="display-time"&&Number(x.occurredAt)>0)x.timeGroupAt=Number(x.occurredAt)}
  return platformOrdered.slice(-MAX_MESSAGES);
 }
 function messageQuality(m){const source=clean(m?.textSource,40),body=clean(m?.text);return (body.length?20:0)+(source==="react-structured"?50:source==="ig-text-leaf"?25:0)-(m?.bodyPolluted||(m?.platformCode==="instagram"&&igTextPolluted(body))?120:0)+(clean(m?.translation?.text).length?12:0)+(Number(m?.occurredAt)>0?10:0)+(m?.timestampPrecision==="exact"?3:0)+(m?.directionConfidence==="high"?3:0)+(m?.threadEvidenceStatus==="MODEL_CONFIRMED"?15:m?.threadEvidenceStatus==="DOM_CONTEXT_CONFIRMED"?5:0)}
 function metaPane(){const composers=[...document.querySelectorAll('[contenteditable="true"],[role="textbox"],textarea')].filter(visible).filter(x=>/message|消息|回复|reply|send|发送|write/i.test(clean(x.getAttribute("aria-label")||x.getAttribute("placeholder")||x.getAttribute("data-lexical-editor"),120))||x.getAttribute("contenteditable")==="true"),anchored=[];for(const box of composers)for(let n=box,d=0;n&&d<14;n=n.parentElement,d++){const r=n.getBoundingClientRect();if(visible(n)&&r.width>=300&&r.height>=260)anchored.push({el:n,score:5000-d*80-Math.max(0,r.width-innerWidth*.82)});if(n.matches('main,[role="main"]'))break}if(anchored.length){anchored.sort((a,b)=>b.score-a.score);return anchored[0].el}const list=[];for(const el of document.querySelectorAll('div[role="main"],main,div[aria-label*="Conversation" i],div[aria-label*="聊天"],div[aria-label*="对话"]'))if(visible(el)){const r=el.getBoundingClientRect();if(r.width>=280&&r.height>=220)list.push({el,score:(el.getAttribute("role")==="main"?1400:0)+Math.min(r.width*r.height/1000,1800)-Math.abs((r.left+r.width/2)-innerWidth/2)/2})}list.sort((a,b)=>b.score-a.score);return list[0]?.el||null}
 function igConversation(tid){if(!tid||igActionRoute(location.pathname))return null;const pane=metaPane();if(!pane)return {threadId:tid,writable:false,confidence:"none",readonlyReason:"未定位到 Instagram 当前中央消息区域"};const h=igHeader(tid,pane);if(!h)return {threadId:tid,writable:false,confidence:"none",readonlyReason:"未定位到 Instagram 当前中央会话 Header"};const kind=conversationKind(h.header);if(kind.kind==="group")return {threadId:tid,unsupported:true,writable:false,confidence:"high",readonlyReason:"当前版本暂不采集 Instagram 群组会话",kindEvidence:kind.evidence};if(h.identityConflict)return {threadId:tid,writable:false,confidence:"none",readonlyReason:"Instagram Header 身份候选冲突"};let identity=h.numericId?{identityType:"instagram_user_id",identityValue:h.numericId,aliases:[{identityType:"instagram_username",identityValue:h.username,evidence:"same-central-header-react-object"}]}:{identityType:"instagram_username",identityValue:h.username};const cacheKey="instagram|"+tid,cached=state.stableConversations.get(cacheKey);if(!h.numericId&&cached?.username===h.username)identity={...cached.identity};const sig=[tid,identity.identityType,identity.identityValue].join("|"),stable=gate(state.conversationGates,"ig-conversation",sig,250,2);if(stable)state.stableConversations.set(cacheKey,{username:h.username,identity:{...identity}});return {threadId:tid,writable:stable,confidence:stable?"high":"medium",readonlyReason:stable?"":"正在核验 Instagram 当前会话身份；稳定前保持只读。",identity:{...identity,displayName:h.name,avatarUrl:h.avatarUrl,source:h.numericId?"header-fiber-username-match":"central-header-username",role:"IS_PARTICIPANT"},conversationKind:kind.kind,_pane:pane}}
 const BAD=/^(Messenger|Facebook|Chats?|聊天|收件箱|Inbox|搜索|Search|语音通话|视频通话|通话详情|聊天室详情|Conversation information|Chat information|Active now|在线|离线|Offline|端到端加密|End-to-end encrypted|详情|Info|个人资料|Profile|成员|Members?|昵称|Nicknames?|正在加载|Loading(?:\.\.\.)?)$/i;
 function fbProfileId(href){
  const raw=clean(href,2048);if(!raw)return "";
  try{
   const u=new URL(raw,location.origin),host=u.hostname.toLowerCase(),path=u.pathname.replace(/\/+/g,"/");
   if(!["facebook.com","www.facebook.com","m.facebook.com"].includes(host))return "";
   if(path==="/messages"||path.startsWith("/messages/")||path.startsWith("/t/")||path.startsWith("/e2ee/"))return "";
   if(path==="/profile.php")return numeric(u.searchParams.get("id"));
   const m=path.match(/^\/(\d{5,30})\/?$/);return m?m[1]:"";
  }catch(_){return ""}
 }
 function metaConversation(code,tid){
  if(!tid)return null;
  const pane=metaPane();
  if(!pane)return {threadId:tid,writable:false,confidence:"none",readonlyReason:"未定位到 Meta 中央聊天区域"};
  const pr=pane.getBoundingClientRect(),cand=[],seen=new Set();
  const add=(el,source)=>{
   if(!el||seen.has(el)||!visible(el))return;seen.add(el);
   const r=el.getBoundingClientRect(),translated=!!el.closest?.('[data-translation-element-mark]')||el.tagName==="FONT"||!!el.querySelector?.('[data-translation-element-mark]');
   if(translated)return;
   const direct=clean([...el.childNodes].filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent).join(" "),80);
   const name=clean(el.getAttribute("title")||direct||el.textContent,80);
   const topMin=Math.max(0,pr.top-180),topMax=pr.top+260;
   if(r.top<topMin||r.top>topMax||r.left<pr.left-25||r.right>pr.right+25||r.width<12||r.height<8||BAD.test(name)||!name)return;
   if(name.length>80||/[\r\n]/.test(name)||/^(?:\d+[分时天]|\d{1,2}:\d{2})/.test(name))return;
   const a=el.closest("a[href]")||el.querySelector?.("a[href]"),href=clean(a?.getAttribute("href"),500);
   let score=(r.top<145?700:0)+(r.left>=pr.left&&r.right<=pr.right?500:0)+(/^H[1-3]$/.test(el.tagName)||el.getAttribute("role")==="heading"?350:0)+(href?450:0)+(name.length<=45?150:0)+(source==="e2ee-header-direct-text"?420:0)+(direct===name?180:0);
   cand.push({el,name,href,score,source});
  };
  for(const el of document.querySelectorAll('h1,h2,h3,div[role="heading"],span[dir="auto"][title],a[href] span[dir="auto"]'))add(el,"central-header-semantic");
  if(!cand.length){
   /* Facebook E2EE headers can expose the participant name only as a plain span.
      Search a bounded conversation ancestry, reject browser-translation clones, and
      keep the existing participant-ID fail-closed gate below. */
   let root=pane;for(let i=0;i<5&&root.parentElement;i++)root=root.parentElement;
   const deadline=performance.now()+8,nodes=root.querySelectorAll("span");
   for(let i=0;i<nodes.length&&i<1200&&performance.now()<deadline;i++){
    const el=nodes[i];
    if(el.children.length>2||el.closest('nav,[role="navigation"],[role="dialog"],[role="menu"]'))continue;
    add(el,"e2ee-header-direct-text");
   }
  }
  cand.sort((a,b)=>b.score-a.score);
  if(!cand.length)return {threadId:tid,writable:false,confidence:"none",readonlyReason:"未定位到 Meta 当前会话标题"};
  const c=cand[0];let n=c.el,header=c.el;
  for(let i=0;n&&i<10;i++,n=n.parentElement){const r=n.getBoundingClientRect();if(visible(n)&&r.top<pr.top+260&&r.left>=pr.left-30&&r.right<=pr.right+30&&r.width>=160&&r.height>=28&&r.height<180)header=n;if(n===pane)break}
  const kind=conversationKind(header);
  if(kind.kind==="group")return {threadId:tid,unsupported:true,writable:false,confidence:"high",readonlyReason:"当前版本暂不采集 Meta 群组会话",kindEvidence:kind.evidence};
  const own=cachedOwner(code),ownId=clean(own?.identityValue,80),profilePid=fbProfileId(c.href),reactParticipants=[...new Set(participantIds(header).filter(id=>id&&id!==tid&&id!==ownId))],reactPid=reactParticipants.length===1?reactParticipants[0]:"";
  if(profilePid&&(profilePid===tid||profilePid===ownId))return {threadId:tid,writable:false,confidence:"none",readonlyReason:"Facebook 主页链接身份与线程号或本人身份冲突，已阻止写入",identityConflict:{profilePid,threadId:tid,ownId}};
  if(profilePid&&reactPid&&profilePid!==reactPid)return {threadId:tid,writable:false,confidence:"none",readonlyReason:"Facebook 主页链接身份与结构化参与者身份不一致，已阻止写入",identityConflict:{profilePid,reactPid}};
  if(reactParticipants.length>1)return {threadId:tid,writable:false,confidence:"none",readonlyReason:"Meta 当前会话存在多个参与者身份候选，已阻止写入",identityConflict:{reactParticipants}};
  const pid=profilePid||reactPid;
  if(!pid)return {threadId:tid,writable:false,confidence:"medium",readonlyReason:"当前会话尚未取得稳定 Facebook 联系人 ID；线程 ID 不再冒充联系人 ID",titleEvidence:{displayName:c.name,source:c.source}};
  let av="";for(const img of header.querySelectorAll("img")){if(visible(img)){av=avatar(img.currentSrc||img.src);if(av)break}}
  const sig=[code,tid,pid].join("|"),stable=gate(state.conversationGates,code+"-conversation",sig,250,2);
  return {threadId:tid,writable:stable,confidence:stable?"high":"medium",readonlyReason:stable?"":"正在核验 Meta 当前会话姓名、头像与联系人 ID；稳定前保持只读。",identity:{identityType:"facebook_user_id",identityValue:pid,displayName:c.name,avatarUrl:av,source:profilePid?"central-header-profile-link":c.source+"+header-react-participant",role:"IS_PARTICIPANT"},conversationKind:kind.kind,titleEvidence:{source:c.source},_pane:pane}
 }

 function ownMeta(code,tid){
  /* No Cookie/Token access. Evidence is limited to account chrome and explicit current-viewer fields. */
  const evidence=[],roots=[...document.querySelectorAll('header,nav,[role="banner"],[role="navigation"]')].filter(r=>!r.closest('main,[role="main"]'));
  const explicit=explicitViewerEvidence();for(const id of explicit.ids)evidence.push({id,source:(explicit.sources||["explicit-current-viewer"]).join("+"),weight:2600});
  for(const d of document.querySelectorAll('[role="dialog"],[role="menu"]')){const t=clean(d.getAttribute("aria-label")||d.innerText,400);if(/account|profile|账户|账号|个人主页/i.test(t))roots.push(d)}
  const add=(id,source,weight)=>{id=numeric(id);if(id)evidence.push({id,source,weight})};
  const seenAnchors=new Set();for(const root of roots)for(const a of root.querySelectorAll('a[href]')){if(seenAnchors.has(a)||!visible(a)||a.closest('main,[role="main"]'))continue;seenAnchors.add(a);const label=clean(a.getAttribute("aria-label")||a.getAttribute("title")||a.textContent,120);if(!/profile|个人主页|主页|查看你的个人主页|see your profile|your account|你的账号/i.test(label)&&!a.querySelector('img'))continue;add(fbProfileId(a.getAttribute("href")||""),"account-profile-link",1000)}
  const deadline=performance.now()+40,objects=roots.flatMap(r=>reactRoots(r,240,deadline)),visited=new WeakSet();let scanned=0;
  const walk=(v,d=0)=>{if(!v||typeof v!=="object"||d>5||visited.has(v)||scanned++>1600||performance.now()>deadline)return;visited.add(v);for(const k of ["actorID","actorId","viewerID","viewerId","currentUserID","currentUserId"]){try{add(v[k],"account-react-"+k,900)}catch(_){}}for(const k of ["viewer","actor","currentUser","account","profile","data"]){try{const x=v[k];if(x&&typeof x==="object")walk(x,d+1)}catch(_){}}};for(const x of objects)walk(x);
  const totals={};for(const e of evidence)totals[e.id]=(totals[e.id]||0)+e.weight;const ranked=Object.entries(totals).sort((a,b)=>b[1]-a[1]);if(!ranked.length||ranked.length>1&&ranked[0][1]===ranked[1][1])return null;const id=ranked[0][0],sources=[...new Set(evidence.filter(e=>e.id===id).map(e=>e.source))];const ok=gate(state.ownerGates,code+"-own",id,250,2);return {identityType:"facebook_user_id",identityValue:id,displayName:"",source:sources.join("+").slice(0,160),role:"IS_OWNER",stable:ok,confidence:ok?"high":"medium"}}

 function unavailableStatusClass(v){const t=clean(v,500);return /(?:无法显示消息|消息无法显示|内容可能已被.*删除|隐私设置隐藏|message (?:is )?unavailable|content (?:may have been )?deleted|content (?:is )?hidden)/i.test(t)?"MESSAGE_UNAVAILABLE":""}
 function collectStatusEvidence(code,tid,pane){
  if(code!=="instagram"||!pane)return [];
  const out=[],seen=new Set(),markers=dateMarkers(pane,code),nodes=pane.querySelectorAll('span,div,p,[role="button"],[role="row"],[role="article"]');let scanned=0;
  for(const leaf of nodes){if(scanned++>3000||!visible(leaf))continue;const raw=clean(leaf.innerText||leaf.textContent,500),uiStatusClass=unavailableStatusClass(raw);if(!uiStatusClass)continue;
   let root=leaf;for(let n=leaf,d=0;n&&n!==pane&&d<7;n=n.parentElement,d++){if(visualDirection(n,pane)){root=n;if(n.matches?.('[role="row"],[role="article"],li,[data-message-id],[data-mid]'))break}}
   const direction=visualDirection(root,pane);if(!direction)continue;const dt=timeFromDom(root,markers,code);if(!dt?.time)continue;
   const key=[tid,dt.time,direction,uiStatusClass].join('|');if(seen.has(key))continue;seen.add(key);
   out.push({probeMessageId:"status."+fnv1a(key),uiStatusClass,occurredAt:dt.time,direction,threadId:tid,timestampSource:dt.source||"status-dom",timestampPrecision:dt.precision||"minute",admissionSource:"DOM_CONTEXT_CONFIRMED"});
  }
  return out.slice(-50);
 }
 function build(reason){const code=platform(),tid=threadId(code);if(!code)return null;const refresh=!state.cachedConversation||state.cachedConversation.threadId!==tid||["start","pushState","replaceState","popstate","hashchange","context-retry","visibility","visibility-recovery","external-wake","account-ui","pane-rebind","owner-stability-retry"].includes(reason);let own=cachedOwner(code),conv=state.cachedConversation;/* 208.9.8: owner verification is an independent gate. A cached conversation must never suppress the second owner sample. */if(!own){own=code==="instagram"?reconcileOwner(code,igOwn()):reconcileOwner(code,ownMeta(code,tid));if(own&&own.stable!==true){state.diagnostics.scheduler.stabilityRetries++;schedule("owner-stability-retry",Math.max(280,260-(Date.now()-(state.ownerGates.get(code==="instagram"?(own.identityType==="instagram_user_id"?"ig-own-id":"ig-own"):code+"-own")?.firstAt||Date.now()))))}}if(refresh){conv=code==="instagram"?igConversation(tid):metaConversation(code,tid);if(conv?.writable===true)state.cachedConversation=conv}const sameIdentity=!!(own?.identityType&&conv?.identity?.identityType===own.identityType&&clean(conv.identity.identityValue,80)===clean(own.identityValue,80));let collision="";if(sameIdentity){collision="SELF_PARTICIPANT_COLLISION";conv={...conv,writable:false,confidence:"none",readonlyReason:"SELF_PARTICIPANT_COLLISION：本人身份与会话参与者身份相同，已阻止写入"}}state.activePane=conv?._pane||state.activePane;let messages=[];if(own?.stable&&conv?.writable&&!conv.unsupported&&state.activePane)messages=extractMessages(code,tid,state.activePane,clean(own.identityValue,80));const statusEvidence=own?.stable&&conv?.writable&&state.activePane?collectStatusEvidence(code,tid,state.activePane):[];const publicConv=conv?{...conv}:conv;if(publicConv)delete publicConv._pane;return {v:VERSION,at:Date.now(),sequence:state.sequence,generation:state.generation,platform:code,route:route(),ownIdentity:own,conversation:publicConv,messages,statusEvidence,diagnostics:{phase:code==="instagram"?"B":"C-D",reason,probeReady:true,identityWriteEnabled:!!(own?.stable&&conv?.writable&&!collision),messageRoots:messages.length,identityError:collision,accountEvidence:own?.source||"",accountStable:own?.stable===true,errors:state.diagnostics.errors,lastError:state.diagnostics.lastError,scan:state.diagnostics.scan||{},scheduler:{...state.diagnostics.scheduler}}}}
 function cancelScheduled(){clearTimeout(state.timer);state.timer=0;if(state.idleHandle&&"cancelIdleCallback" in window)cancelIdleCallback(state.idleHandle);else if(state.idleHandle)clearTimeout(state.idleHandle);state.idleHandle=0}
 function recoverPane(){
  const oldPane=state.activePane;if(oldPane?.isConnected)return;
  cancelScheduled();state.generation++;state.cachedConversation=null;state.activePane=null;state.paneObserver?.disconnect();state.paneObserver=null;state.paneParentObserver?.disconnect();state.paneParentObserver=null;state.diagnostics.scheduler.paneRebinds++;schedule("pane-rebind",60)
 }
 function bindPaneObserver(){
  const pane=state.activePane;if(!pane||!pane.isConnected)return;if(state.paneObserver?.__target===pane&&state.paneParentObserver?.__target===pane.parentElement)return;
  state.paneObserver?.disconnect();state.paneParentObserver?.disconnect();
  const observer=new MutationObserver(records=>{state.diagnostics.scheduler.scopedMutations+=records.length;schedule("message-mutation",120)});observer.__target=pane;observer.observe(pane,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:["data-message-id","data-mid","datetime","aria-label","class","style","data-translation","data-translation-element-mark","data-immersive-translate-translation"]});state.paneObserver=observer;
  const parent=pane.parentElement;if(parent&&parent!==document.documentElement&&parent!==document.body){const sentinel=new MutationObserver(()=>{if(!pane.isConnected||pane.parentElement!==parent)recoverPane()});sentinel.__target=parent;sentinel.observe(parent,{childList:true});state.paneParentObserver=sentinel}
 }
 /* 210.1.8: independently map hydrated Instagram inbox rows by stable IDs only. */
 const IG_THREAD_KEYS=/^(thread_id|threadId|threadID|thread_fbid|threadFbid|thread_key|threadKey|thread_pk|threadPk|thread_v2_id|threadV2Id|thread_v2Id|thread_id_v2|conversation_id|conversationId|conversation_fbid|conversationFbid)$/;
 function igValueThreadId(root){const seen=new WeakSet();let found="",budget=0;const walk=(v,d=0,k="")=>{if(found||d>9||budget++>5000||v==null)return;if(typeof v==="string"||typeof v==="number"){if(IG_THREAD_KEYS.test(k)){let x=clean(v,256).replace(/^ig:/i,"");const m=x.match(/\/direct\/(?:t|thread)\/([^/?#]+)/i);if(m)x=decode(m[1]);if(x&&/^[A-Za-z0-9_.:-]{3,256}$/.test(x))found=x}return}if(typeof v!=="object"||seen.has(v))return;seen.add(v);for(const key of Object.keys(v)){if(["stateNode","_owner","sibling","return","ownerDocument"].includes(key))continue;try{walk(v[key],d+1,key)}catch(_){}if(found)return}};walk(root);return found}
 function igInboxThreadId(el){const direct=clean(el?.getAttribute?.("data-thread-id")||el?.getAttribute?.("data-threadid")||el?.getAttribute?.("data-conversation-id"),256);if(direct)return direct.replace(/^ig:/i,"");const link=el?.matches?.('a[href*="/direct/"]')?el:el?.querySelector?.('a[href*="/direct/"]'),href=clean(link?.getAttribute?.("href"),2048),hm=href.match(/\/direct\/(?:t|thread)\/([^/?#]+)/i);if(hm)return decode(hm[1]);
  const nodes=[el,...(el?.querySelectorAll?.('a,img,[role="link"],[role="button"],[tabindex],div')||[])].slice(0,180);for(const n of nodes){for(const entry of ownReactEntries(n)){const id=igValueThreadId(entry);if(id)return id}}for(let n=el?.parentElement,i=0;n&&i<3;i++,n=n.parentElement){for(const entry of ownReactEntries(n)){const id=igValueThreadId(entry);if(id)return id}}return ""}
 function igVisualInboxRow(seed){let best=null,score=-1;for(let n=seed,i=0;n&&i<8;i++,n=n.parentElement){if(n===document.body||n===document.documentElement)break;const r=n.getBoundingClientRect();if(r.left<innerWidth*.58&&r.width>=180&&r.height>=44&&r.height<=145){const q=r.width-Math.abs(r.height-72)*4+i;if(q>score){best=n;score=q}}}return best}
 let igInboxSignature="",igInboxTimer=0;
 function markInstagramInboxRows(){if(platform()!=="instagram")return;const seeds=new Set(document.querySelectorAll('a[href*="/direct/t/"],a[href*="/direct/thread/"],[data-thread-id],[data-threadid],[data-conversation-id],[role="listitem"],[role="row"],[aria-selected],[aria-current]'));for(const img of document.querySelectorAll('img')){const r=img.getBoundingClientRect();if(visible(img)&&r.left<innerWidth*.52&&r.width>=28&&r.width<=100&&r.height>=28&&r.height<=100)seeds.add(img)}
  const marked=[];for(const seed of seeds){if(!visible(seed)||seed.closest?.("#jubaopen-interaction-host"))continue;const row=igVisualInboxRow(seed);if(!row)continue;const id=igInboxThreadId(row)||igInboxThreadId(seed);if(!id)continue;const ext="ig:"+id;row.setAttribute("data-juba-ig-thread-id",id);row.setAttribute("data-juba-external-conversation-id",ext);marked.push(ext)}
  const current=threadId("instagram");if(current){const routeLink=document.querySelector(`a[href*="/direct/t/${CSS.escape(current)}"],a[href*="/direct/thread/${CSS.escape(current)}"]`);let row=routeLink&&igVisualInboxRow(routeLink);if(!row){const selected=[...document.querySelectorAll('[aria-current="page"],[aria-selected="true"],[data-selected="true"]')].find(x=>{const r=x.getBoundingClientRect();return visible(x)&&r.left<innerWidth*.55&&r.height>=40&&r.height<=160});row=selected&&igVisualInboxRow(selected)}if(row){row.setAttribute("data-juba-ig-current","true");row.setAttribute("data-juba-ig-thread-id",current);row.setAttribute("data-juba-external-conversation-id","ig:"+current);marked.push("ig:"+current)}}
  const sig=[...new Set(marked)].sort().join("|");if(sig!==igInboxSignature){igInboxSignature=sig;dispatchEvent(new CustomEvent("jubaopen-meta-snapshot",{detail:{v:VERSION,at:Date.now(),platform:"instagram",reason:"inbox-rows"}}))}}
 function startIgInboxScanner(){if(igInboxTimer)return;const run=()=>{igInboxTimer=0;if(document.visibilityState==="visible")try{markInstagramInboxRows()}catch(e){state.diagnostics.errors++}igInboxTimer=setTimeout(run,document.visibilityState==="visible"?4000:15000)};run()}
 function publish(reason="message-mutation",expectedGeneration=state.generation){markInstagramInboxRows();state.timer=0;state.idleHandle=0;if(expectedGeneration!==state.generation){state.diagnostics.scheduler.dropped++;return}try{const r=route();if(r!==state.lastRoute){invalidateRoute("route-drift");schedule("context-retry",80);return}const snapshot=build(reason);if(!snapshot||expectedGeneration!==state.generation){state.diagnostics.scheduler.dropped++;return}const encoded=JSON.stringify(snapshot),semantic=JSON.stringify({platform:snapshot.platform,route:snapshot.route,generation:snapshot.generation,ownIdentity:snapshot.ownIdentity,conversation:snapshot.conversation,messages:snapshot.messages,statusEvidence:snapshot.statusEvidence,identityError:snapshot.diagnostics?.identityError||""}),changed=semantic!==state.lastSemantic;if(encoded!==state.lastPublished){node().setAttribute("content",encoded);state.lastPublished=encoded}if(changed||reason!=="heartbeat"){state.lastSemantic=semantic;dispatchEvent(new CustomEvent("jubaopen-meta-snapshot",{detail:{v:VERSION,at:snapshot.at,platform:snapshot.platform,sequence:snapshot.sequence,generation:expectedGeneration,changed}}))}state.diagnostics.scheduler.runs++;bindPaneObserver()}catch(e){state.diagnostics.errors++;state.diagnostics.lastError=clean(e?.message||e,300)}}
 function invalidateRoute(reason){cancelScheduled();state.generation++;state.lastRoute=route();state.sequence++;state.cachedConversation=null;state.activePane=null;state.paneObserver?.disconnect();state.paneObserver=null;state.paneParentObserver?.disconnect();state.paneParentObserver=null;state.conversationGates.clear();state.viewerEvidenceCache=null;const code=platform();if(!code)return;const tid=threadId(code),snapshot={v:VERSION,at:Date.now(),sequence:state.sequence,generation:state.generation,platform:code,route:state.lastRoute,ownIdentity:cachedOwner(code),conversation:tid?{threadId:tid,writable:false,confidence:"none",readonlyReason:"页面路由已变化，正在重新核验会话上下文"}:null,messages:[],diagnostics:{phase:"A",reason,probeReady:true,identityWriteEnabled:false,messageRoots:0,routeTransition:true,errors:state.diagnostics.errors,lastError:state.diagnostics.lastError,scheduler:{...state.diagnostics.scheduler}}};const encoded=JSON.stringify(snapshot);node().setAttribute("content",encoded);state.lastPublished=encoded;dispatchEvent(new CustomEvent("jubaopen-meta-snapshot",{detail:{v:VERSION,at:snapshot.at,platform:code,sequence:state.sequence,generation:state.generation,readonly:true}}))}
 function schedule(reason,delay=80){/* 210.0.6: first scheduled scan wins; high-frequency React mutations may coalesce but may not postpone it forever. */if(state.timer||state.idleHandle){state.diagnostics.scheduler.coalesced++;return}const generation=state.generation;state.timer=setTimeout(()=>{state.timer=0;const run=()=>publish(reason,generation);if("requestIdleCallback" in window)state.idleHandle=requestIdleCallback(run,{timeout:700});else state.idleHandle=setTimeout(run,0)},Math.max(0,delay))}
 for(const name of ["pushState","replaceState"]){const original=history[name];if(typeof original==="function"&&!original.__jubaWrapped){const wrapped=function(...args){const out=original.apply(this,args);invalidateRoute(name);schedule("context-retry",80);return out};wrapped.__jubaWrapped=true;history[name]=wrapped}}
 addEventListener("popstate",()=>{invalidateRoute("popstate");schedule("context-retry",80)});addEventListener("hashchange",()=>{invalidateRoute("hashchange");schedule("context-retry",80)});function forceForegroundRefresh(reason="visibility-recovery"){if(document.visibilityState!=="visible")return;cancelScheduled();if(state.activePane&&!state.activePane.isConnected){recoverPane();return}const r=route();if(r!==state.lastRoute){invalidateRoute(reason);schedule("context-retry",50);return}publish(reason,state.generation);setTimeout(()=>{cancelScheduled();publish("context-retry",state.generation)},500)}
 addEventListener("jubaopen-meta-force-refresh",()=>forceForegroundRefresh("external-wake"));addEventListener("visibilitychange",()=>{if(document.visibilityState==="visible")setTimeout(()=>forceForegroundRefresh("visibility-recovery"),20)});addEventListener("focus",()=>setTimeout(()=>forceForegroundRefresh("visibility-recovery"),30));addEventListener("pageshow",()=>setTimeout(()=>forceForegroundRefresh("visibility-recovery"),30));addEventListener("pointerup",e=>{if(!state.activePane?.contains?.(e.target)){state.viewerEvidenceCache=null;schedule("account-ui",180)}},true);addEventListener("scroll",e=>{const target=e.target;if(state.activePane&&(target===document||target===document.documentElement||state.activePane.contains?.(target)))schedule("history-scroll",100)},true);
 const start=()=>{state.lastRoute=route();publish("start",state.generation);schedule("context-retry",350);setTimeout(()=>schedule("context-retry",0),850);setInterval(()=>{if(document.visibilityState==="visible")startIgInboxScanner();schedule("heartbeat",80)},5000)};if(document.documentElement)start();else addEventListener("DOMContentLoaded",start,{once:true});
})();
