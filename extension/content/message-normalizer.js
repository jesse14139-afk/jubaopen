"use strict";
/* Channel-neutral message contract. Adapters extract platform DOM; this module only validates and normalizes fields. */
window.JubaMessageProtocol=(()=>{
 const MAX_TEXT=65536;
 const clean=(value,max=MAX_TEXT)=>String(value??"").replace(/\u0000/g,"").replace(/[\u200B-\u200F\u202A-\u202E\u2060-\u206F\uFEFF\uFFFC]/g,"").trim().slice(0,max);
 const positiveTime=value=>{const n=Number(value);return Number.isFinite(n)&&n>0?Math.trunc(n):null};
 function translation(value){
  if(!value)return null;const source=typeof value==="string"?{text:value}:value;if(!source||typeof source!=="object")return null;
  const text=clean(source.text);if(!text)return null;
  return {text,source:clean(source.source||"platform",120)||"platform",visible:source.visible!==false,...(clean(source.targetLanguage,32)?{targetLanguage:clean(source.targetLanguage,32)}:{}),...(clean(source.confidence,16)?{confidence:clean(source.confidence,16)}:{})};
 }
 function separate(body,tr){
  const text=clean(body),translated=tr?.text||"";
  if(!text||!translated||text===translated||!text.endsWith(translated))return text;
  const original=text.slice(0,text.length-translated.length).trim();return original||text;
 }
 function normalize(input){
  const x=input&&typeof input==="object"?input:{};const platform=clean(x.platform,32);const metadata={...(x.metadata&&typeof x.metadata==="object"?x.metadata:{})};
  const tr=translation(x.translation||metadata.translation);if(tr)metadata.translation=tr;else delete metadata.translation;
  const occurredAt=positiveTime(x.occurredAt);const observedAt=positiveTime(metadata.observedAt)||Date.now();
  metadata.observedAt=observedAt;metadata.timestampResolved=metadata.timestampResolved===false?false:!!occurredAt;
  metadata.timestampConfidence=clean(metadata.timestampConfidence||(occurredAt?"high":"low"),16)||(occurredAt?"high":"low");
  metadata.captureMode=clean(metadata.captureMode||"dom",40)||"dom";
  metadata.messageContract="juba-channel-message-v1";if(platform)metadata.sourcePlatform=platform;
  const direction=x.direction==="outbound"?"outbound":x.direction==="system"?"system":"inbound";
  const contentType=clean(x.contentType||"unknown",32)||"unknown";const original=separate(x.text,tr);
  return {externalMessageId:clean(x.externalMessageId,500),clientEventId:clean(x.clientEventId||x.externalMessageId,500),direction,senderType:clean(x.senderType||(direction==="outbound"?"agent":direction==="inbound"?"contact":"system"),80),contentType,text:original||null,...(occurredAt?{occurredAt}:{}),metadata};
 }
 const capabilities=Object.freeze({
  whatsapp:Object.freeze({translation:"explicit",timestamp:"reliable",stableMessageId:true,historyBackfill:true}),
  telegram:Object.freeze({translation:"explicit-or-immersive",timestamp:"platform-dependent",stableMessageId:true,historyBackfill:true}),
  instagram:Object.freeze({translation:"probe-dependent",timestamp:"probe-dependent",stableMessageId:"probe-dependent",historyBackfill:true}),
  messenger:Object.freeze({translation:"probe-dependent",timestamp:"probe-dependent",stableMessageId:"probe-dependent",historyBackfill:true}),
  facebook:Object.freeze({translation:"probe-dependent",timestamp:"probe-dependent",stableMessageId:"probe-dependent",historyBackfill:true})
 });
 return Object.freeze({clean,translation,separate,normalize,capabilities});
})();
