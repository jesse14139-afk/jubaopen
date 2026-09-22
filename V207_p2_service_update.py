#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V207 P2 Service Layer Updates
更新所有服务层代码，禁止直接使用 channel 字段，统一使用 platform_id
"""

P2_CHANNEL_SERVICE_PATCH = """
# ============================================================
# P2 渠道服务更新说明
# ============================================================

## V207_channel_service.py 需要修改的位置

### 1. 创建账号接口
OLD:
  channel = body.get('channel')
  if not channel or channel not in ['whatsapp','instagram','facebook','messenger','telegram']:
    return {'error':'INVALID_CHANNEL'},400

NEW:
  platform_id = body.get('platform_id')
  if not platform_id:
    return {'error':'PLATFORM_ID_REQUIRED','message':'platform_id is required'},400
  
  # 验证平台存在且激活
  platform = c.execute(
    "SELECT platform_code FROM platforms WHERE platform_id=? AND status='active'",
    (platform_id,)
  ).fetchone()
  if not platform:
    return {'error':'INVALID_PLATFORM','message':'Platform not found or inactive'},400

### 2. 查询账号接口
OLD:
  WHERE channel=?

NEW:
  WHERE platform_id=?

### 3. 账号列表过滤
OLD:
  channel_filter = query.get('channel')
  if channel_filter:
    sql += " AND channel=?"
    params.append(channel_filter)

NEW:
  platform_filter = query.get('platform_id')
  if platform_filter:
    sql += " AND platform_id=?"
    params.append(platform_filter)
  
  # 兼容：如果传入 channel，自动转换为 platform_id
  legacy_channel = query.get('channel')
  if legacy_channel and not platform_filter:
    platform_map = {
      'whatsapp': 'PLT-WHATSAPP',
      'instagram': 'PLT-INSTAGRAM',
      'facebook': 'PLT-FACEBOOK',
      'messenger': 'PLT-MESSENGER',
      'telegram': 'PLT-TELEGRAM'
    }
    if legacy_channel in platform_map:
      sql += " AND platform_id=?"
      params.append(platform_map[legacy_channel])

### 4. 响应数据增强
OLD:
  return {
    'channel_account_id': row[0],
    'channel': row[2],
    'display_name': row[3],
    ...
  }

NEW:
  platform_info = None
  if row[2]:  # platform_id exists
    platform_info = c.execute(
      "SELECT platform_code, platform_name FROM platforms WHERE platform_id=?",
      (row[2],)
    ).fetchone()
  
  return {
    'channel_account_id': row[0],
    'platform_id': row[2],
    'platform_code': platform_info[0] if platform_info else None,
    'platform_name': platform_info[1] if platform_info else None,
    'display_name': row[3],
    # channel 字段仅用于向后兼容
    'channel': platform_info[0].lower() if platform_info else None,
    ...
  }
"""

P2_SOURCE_SERVICE_PATCH = """
# ============================================================
# P2 来源服务更新说明
# ============================================================

## V207_source_service.py 需要修改的位置

### 1. 创建来源接口
NEW REQUIRED FIELDS:
  - platform_id: 必填
  - channel_type_id: 必填（关联到 channel_types 表）
  - source_type_code: 必填（关联到 source_type_definitions 表）
  - channel_account_id: 可选（但如果填写必须验证 platform 一致性）

VALIDATION:
  platform_id = body.get('platform_id')
  channel_type_id = body.get('channel_type_id')
  source_type_code = body.get('source_type_code')
  channel_account_id = body.get('channel_account_id')
  
  # 验证平台
  if not platform_id:
    return {'error':'PLATFORM_ID_REQUIRED'},400
  
  platform = c.execute(
    "SELECT 1 FROM platforms WHERE platform_id=? AND status='active'",
    (platform_id,)
  ).fetchone()
  if not platform:
    return {'error':'INVALID_PLATFORM'},400
  
  # 验证渠道类型
  if not channel_type_id:
    return {'error':'CHANNEL_TYPE_REQUIRED'},400
  
  channel_type = c.execute(
    "SELECT platform_id FROM channel_types WHERE channel_type_id=? AND status='active'",
    (channel_type_id,)
  ).fetchone()
  if not channel_type:
    return {'error':'INVALID_CHANNEL_TYPE'},400
  
  # 验证渠道类型与平台一致
  if channel_type[0] != platform_id:
    return {
      'error':'PLATFORM_MISMATCH',
      'message':f'Channel type belongs to {channel_type[0]}, not {platform_id}'
    },400
  
  # 验证来源类型
  if not source_type_code:
    return {'error':'SOURCE_TYPE_REQUIRED'},400
  
  source_type = c.execute(
    "SELECT 1 FROM source_type_definitions WHERE source_type_code=? AND status='active'",
    (source_type_code,)
  ).fetchone()
  if not source_type:
    return {'error':'INVALID_SOURCE_TYPE'},400
  
  # 如果指定了账号，验证账号平台一致性
  if channel_account_id:
    account = c.execute(
      "SELECT platform_id FROM channel_accounts WHERE channel_account_id=? AND status='active'",
      (channel_account_id,)
    ).fetchone()
    if not account:
      return {'error':'INVALID_ACCOUNT'},400
    if account[0] != platform_id:
      return {
        'error':'ACCOUNT_PLATFORM_MISMATCH',
        'message':f'Account belongs to {account[0]}, not {platform_id}'
      },400

### 2. 来源命名自动生成
RECOMMENDED FORMAT:
  [资源商]-[平台代码]-[账号简称]-[渠道类型]-[市场]-[业务线]-[YYYYMM]

EXAMPLE IMPLEMENTATION:
  def generate_source_name(c, platform_id, channel_type_id, account_id, market_code, business_line_code):
    # 获取平台代码
    platform_code = c.execute(
      "SELECT platform_code FROM platforms WHERE platform_id=?",
      (platform_id,)
    ).fetchone()[0]
    
    # 获取渠道类型名称简化
    channel_type_name = c.execute(
      "SELECT channel_type_name FROM channel_types WHERE channel_type_id=?",
      (channel_type_id,)
    ).fetchone()[0]
    
    # 获取账号显示名
    account_name = '自营'
    if account_id:
      acc = c.execute(
        "SELECT display_name FROM channel_accounts WHERE channel_account_id=?",
        (account_id,)
      ).fetchone()
      if acc:
        account_name = acc[0]
    
    # 当前年月
    import time
    yearmonth = time.strftime('%Y%m')
    
    return f"{account_name}-{platform_code}-{channel_type_name}-{market_code}-{business_line_code}-{yearmonth}"
"""

P2_ADMIN_API_PATCH = """
# ============================================================
# P2 管理 API 更新说明
# ============================================================

## V207_admin_api.py 需要修改的位置

### 1. 平台管理接口（已存在，需增强）
GET /api/v207/admin/platforms
  - 返回所有平台列表
  - 支持 status 过滤

POST /api/v207/admin/platforms
  - 创建新平台（需要企业管理员权限）

PUT /api/v207/admin/platforms/{platform_id}
  - 更新平台信息

### 2. 前端数据字典接口
GET /api/v207/admin/dictionaries
  返回所有字典的摘要：
  {
    "platforms": {"count": 8, "active": 7},
    "channel_types": {"count": 38, "active": 38},
    "source_types": {"count": 13, "active": 13}
  }

GET /api/v207/admin/dictionaries/platform-channels
  返回平台与渠道类型的关联：
  {
    "PLT-FACEBOOK": [
      {"channel_type_id": "...", "channel_type_name": "Facebook 动态广告"},
      {"channel_type_id": "...", "channel_type_name": "Facebook 群组推广"}
    ],
    ...
  }
"""

P2_FRONTEND_CHANGES = """
# ============================================================
# P2 前端更新清单
# ============================================================

## admin_v207.html 需要修改的位置

### 1. 账号创建表单
OLD:
  <select id="channel" required>
    <option value="whatsapp">WhatsApp</option>
    <option value="instagram">Instagram</option>
    <option value="facebook">Facebook</option>
    <option value="messenger">Messenger</option>
    <option value="telegram">Telegram</option>
  </select>

NEW:
  <select id="platform_id" required>
    <!-- 动态加载 -->
  </select>
  
  <script>
  async function loadPlatforms() {
    const resp = await fetch('/api/v207/admin/platforms?status=active');
    const data = await resp.json();
    const sel = document.getElementById('platform_id');
    data.items.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.platform_id;
      opt.textContent = p.platform_name;
      sel.appendChild(opt);
    });
  }
  </script>

### 2. 来源创建表单
NEW FIELDS:
  - 平台（下拉，必填）
  - 渠道类型（下拉，根据平台动态加载，必填）
  - 来源类型（下拉，固定13种，必填）
  - 平台账号（下拉，根据平台过滤，可选）
  - 市场（下拉，可选）
  - 业务线（下拉，可选）
  - 自动生成名称（按钮）

### 3. 账号列表筛选
OLD:
  <select id="filter_channel">
    <option value="">全部渠道</option>
    <option value="whatsapp">WhatsApp</option>
    ...
  </select>

NEW:
  <select id="filter_platform">
    <option value="">全部平台</option>
    <!-- 动态加载 -->
  </select>

### 4. 来源列表显示
NEW COLUMNS:
  - 平台
  - 渠道类型
  - 来源类型
  - 平台账号
  - 状态

REMOVE LEGACY:
  - 旧的 "渠道" 列（如果与平台混淆）
"""

def print_p2_implementation_guide():
    """打印 P2 实施指南"""
    print("\n" + "="*60)
    print("P2 阶段实施指南")
    print("="*60)
    
    print("\n【第一步】运行数据库迁移")
    print("  python V207_p2_migration.py data/jubaopen-v207.db")
    
    print("\n【第二步】更新服务层代码")
    print("  1. V207_channel_service.py")
    print("  2. V207_source_service.py")
    print("  3. V207_campaign_service.py")
    print("  4. V207_admin_api.py")
    
    print("\n【第三步】更新前端代码")
    print("  1. admin_v207.html - 账号管理页面")
    print("  2. admin_v207.html - 来源管理页面")
    print("  3. admin_v207.html - 数据字典页面")
    
    print("\n【第四步】回归测试")
    print("  1. 创建新平台账号（使用 platform_id）")
    print("  2. 创建新来源（使用 platform_id + channel_type_id + source_type_code）")
    print("  3. 验证旧账号仍可查看（兼容模式）")
    print("  4. 验证跨平台一致性检查")
    print("  5. 验证 NULL platform_id 被拒绝")
    
    print("\n" + "="*60)
    print("详细修改说明：")
    print("="*60)
    
    print(P2_CHANNEL_SERVICE_PATCH)
    print(P2_SOURCE_SERVICE_PATCH)
    print(P2_ADMIN_API_PATCH)
    print(P2_FRONTEND_CHANGES)


if __name__ == '__main__':
    print_p2_implementation_guide()
