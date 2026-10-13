#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Threads 平台数据库诊断说明。

210.3.4 已在 V208_collector_service._platform 中实施运行时
幂等注册。第一次收到 Threads 平台请求时会执行：

- 查询 platform_code=threads；
- 不存在则插入 plt_threads；
- 已存在但 disabled 则更新为 active；
- 再返回活动平台记录。

本文件只用于记录修复设计，不直接猜测数据库文件路径。
"""

PLATFORM_RECORD = {
    "platform_id": "plt_threads",
    "platform_code": "threads",
    "platform_name": "Threads",
    "platform_abbr": "THREADS",
    "platform_kind": "social",
    "status": "active",
}


if __name__ == "__main__":
    print("Threads platform runtime repair is installed.")
    print(PLATFORM_RECORD)
