#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
JubaOpen 210.3.5 Threads 修复说明。

已确认的浏览器诊断证据：

1. Adapter conversation 身份持续有效：
   - identityType=threads_username
   - identityValue 非空
   - readonly=false
   - invalidConversationCallCount=0

2. chat-panel 发出的候选查询请求却包含：
   - contactIdentity={}

3. follow-ups/resolve 已发送：
   - platformCode=threads

   后端仍返回：
   - PLATFORM_REQUIRED
   - platformCode 无效

210.3.5 修复内容：

- 在 chat-panel API 边界兼容扁平及嵌套身份结构；
- contactIdentity 为空时重新读取 adapter conversation；
- 防止空对象绕过联系人身份验证；
- 在 resolve_follow_ups 原逻辑运行前，使用既有 _platform()
  幂等创建或启用 Threads 平台。
"""

VERSION = "210.3.5"

FIXES = {
    "contact_identity_contract": True,
    "empty_identity_object_repair": True,
    "refresh_conversation_before_request": True,
    "threads_follow_up_platform_preflight": True,
}


if __name__ == "__main__":
    print("JubaOpen", VERSION)

    for name, enabled in FIXES.items():
        print(f"{name}: {enabled}")
