# -*- coding: utf-8 -*-
"""Observed profile-name validation shared by collector and compatibility paths."""
import re
_INVALID_OBSERVED_NAMES={
 '个人主页详情','联系人信息','联系方式','个人资料','群组信息','点击查看联系人信息',
 'contact info','contact information','profile details','profile info','group info',
 'click to view contact info','view contact info'
}
def sanitize_observed_name(value,limit=200):
 name=re.sub(r'\s+',' ',str(value or '')).strip()[:limit]
 if not name:return ''
 normalized=name.casefold().strip(' \t\r\n:：·-–—')
 if normalized in _INVALID_OBSERVED_NAMES:return ''
 if re.fullmatch(r'(online|typing(?:\.\.\.)?|last seen.*|在线|正在输入(?:中)?(?:…|\.\.\.)?)',normalized,re.I):return ''
 return name
