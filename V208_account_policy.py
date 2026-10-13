# -*- coding: utf-8 -*-
"""V208.3.0 渠道账号业务场景与建档策略唯一规则源。"""
SCENES={
 'social_acquisition':{'purpose':'acquisition','policy':'manual_on_record','account_type':'chat','collection':1,'label':'社交获客'},
 'lead_intake':{'purpose':'conversion','policy':'first_inbound_message','account_type':'service','collection':1,'label':'接粉承接'},
 'conversion':{'purpose':'conversion','policy':'existing_contact_first','account_type':'chat','collection':1,'label':'转化成交'},
 'hybrid':{'purpose':'hybrid','policy':'manual_on_record','account_type':'chat','collection':1,'label':'混合使用'},
 'internal':{'purpose':'hybrid','policy':'disabled','account_type':'internal','collection':0,'label':'内部使用'},
}
POLICIES={'manual_on_record','first_inbound_message','existing_contact_first','disabled'}

def _value(body,*keys):
 for key in keys:
  if key in body:return body[key],True
 return None,False

def normalize_account_policy(body,require_scene=True):
 """Validate the public scene contract and derive every legacy storage field."""
 scene_value,scene_supplied=_value(body,'businessScene','business_scene')
 scene=str(scene_value or '').strip().lower()
 if not scene and not require_scene:return None
 if scene not in SCENES:raise ValueError('INVALID_BUSINESS_SCENE')
 spec=SCENES[scene]
 policy_value,policy_supplied=_value(body,'contactEntryPolicy','contact_entry_policy')
 if scene=='social_acquisition':policy_supplied=False
 supplied_policy=str(policy_value or '').strip().lower()
 policy=spec['policy']
 if policy_supplied and supplied_policy!=policy:raise ValueError('BUSINESS_POLICY_CONFLICT')
 result={'business_scene':scene,'contact_entry_policy':policy,'business_purpose':spec['purpose'],'account_type':spec['account_type'],'collection_enabled':spec['collection']}
 checks=(
  (('businessPurpose','business_purpose'),'business_purpose',lambda v:str(v or '').strip().lower()),
  (('accountType','account_type'),'account_type',lambda v:str(v or '').strip().lower()),
  (('collectionEnabled','collection_enabled'),'collection_enabled',lambda v:(1 if v else 0) if isinstance(v,bool) else None),
 )
 for keys,target,convert in checks:
  value,present=_value(body,*keys)
  if scene!='social_acquisition' and present and convert(value)!=result[target]:raise ValueError('BUSINESS_POLICY_CONFLICT')
 return result
