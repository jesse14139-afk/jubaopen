# Jubaopen V207.8.0 / Schema 211 升级指南

**发布日期**: 2026-09-22  
**产品版本**: V207.8.0  
**Schema 版本**: 211  
**升级类型**: 渐进式升级（向后兼容）

---

## 一、升级概述

本次升级完成了从硬编码到数据字典的全面转型，包含 7 个阶段的实施：

- **P0: Schema 211 基线收口** - 消除旧接口旁路，统一审计机制
- **P1: 企业预设与组织初始化** - 5 平台 → 动态平台表，28 种渠道类型，8 种来源类型
- **P2: 移除五平台硬编码** - `platform_id` 外键替代 `channel IN (...)`
- **P3: 来源类型规范化** - `source_type_id` 关联独立字典
- **P4: 触点渠道类型关联** - `channel_type_id` 支持精细归因
- **P5: 活动业务线市场关联** - `business_line_id` 和 `market_id` 支持跨区域管理
- **P6: 代码规范统一** - 命名规范检查，API 响应标准化
- **P7: 测试与文档** - 综合测试脚本，升级验证工具

---

## 二、核心变更

### 2.1 数据库架构

| 变更类型 | 表/列 | 说明 |
|---------|------|------|
| 新增表 | `channel_types` | 渠道类型字典（28 种预设类型） |
| 新增表 | `source_type_definitions` | 来源类型字典（8 种预设类型） |
| 新增列 | `channel_accounts.platform_id` | 平台外键（P2） |
| 新增列 | `sources.platform_id` | 平台外键（P2） |
| 新增列 | `sources.source_type_id` | 来源类型外键（P3） |
| 新增列 | `source_touchpoints.channel_type_id` | 渠道类型外键（P4） |
| 新增列 | `campaigns.business_line_id` | 业务线外键（P5） |
| 新增列 | `campaigns.market_id` | 市场外键（P5） |
| 移除约束 | `channel_accounts.channel` | 移除 `CHECK(channel IN (...))` |
| 移除约束 | `sources.channel` | 移除 `CHECK(channel IN (...))` |

### 2.2 API 变更

#### 破坏性变更（需客户端适配）

| API | 变更内容 | 影响 |
|-----|---------|------|
| `POST /api/v207/center/user` | 已废弃 | 返回 410，必须使用 `POST /api/v207/admin/users` |
| `POST /api/v207/admin/accounts` | `platformId` 必填 | 不再接受单独的 `channel` 参数 |

#### 增强性变更（可选升级）

| API | 新增参数 | 说明 |
|-----|---------|------|
| `POST /api/v207/admin/sources` | `sourceTypeId` | 来源类型 ID（可选） |
| `POST /api/v207/admin/campaigns` | `businessLineId`, `marketId` | 业务线和市场 ID（可选） |
| `GET /api/v207/admin/dictionaries` | - | 新增字典摘要接口 |
| `GET /api/v207/admin/dictionaries/platform-channels` | - | 平台-渠道类型关联查询 |

#### 响应增强（自动生效）

所有查询接口现在返回完整的关联信息：

```json
{
  "ok": true,
  "items": [
    {
      "channel_account_id": "acc_xxx",
      "platform_id": "plt-whatsapp",
      "platform_name": "WhatsApp Business",
      "platform_code": "whatsapp"
    }
  ]
}
```

---

## 三、升级步骤

### 3.1 准备工作

1. **备份数据库**
   ```bash
   cp data/jubaopen-v207.db data/jubaopen-v207.db.backup-$(date +%Y%m%d)
   ```

2. **检查当前版本**
   ```bash
   sqlite3 data/jubaopen-v207.db "SELECT key, value FROM meta WHERE key='schema_version'"
   ```

3. **验证数据完整性**
   ```bash
   sqlite3 data/jubaopen-v207.db "PRAGMA integrity_check"
   ```

### 3.2 数据库升级

#### 自动升级（推荐）

重启服务，系统会自动运行所有迁移：

```bash
python V207_center_service.py
```

迁移会在首次启动时执行：
- ✅ `ensure_v211_030`: 创建渠道类型和来源类型表
- ✅ `ensure_v211_040`: sources 添加 source_type_id
- ✅ `ensure_v211_050`: 触点和活动增强

#### 手动验证迁移

```bash
sqlite3 data/jubaopen-v207.db << EOF
SELECT migration_id, migration_name, applied_at 
FROM schema_migrations 
WHERE migration_id LIKE 'V211_%' 
ORDER BY applied_at;
EOF
```

预期输出：
```
V211_030_channel_and_source_types|渠道类型与来源类型独立字典表|...
V211_040_sources_type_id|sources表添加source_type_id外键|...
V211_050_touchpoints_campaigns_enhance|触点渠道类型与活动业务线市场关联|...
```

### 3.3 初始化企业数据（仅首次）

如果是全新部署或需要初始化聚宝盆公司组织架构：

```bash
python V207_p1_init.py --db data/jubaopen-v207.db
```

这会创建：
- 1 个企业（聚宝盆公司）
- 1 个全球业务工作区
- 5 个部门
- 3 个业务团队
- 2 条业务线
- 16 个市场（含地域层级）
- 12 个职位

### 3.4 历史数据迁移

#### P2: 填充 platform_id

```bash
python V207_p2_migrate.py --db data/jubaopen-v207.db
```

预期输出：
```
正在迁移 channel_accounts...
  ✓ 账号 acc_001: whatsapp -> plt-whatsapp
  ...
✓ P2 数据迁移完成
  channel_accounts:     150 条
  identities:           300 条
  sources:              200 条
```

#### P3: 填充 source_type_id

```bash
python V207_p3_migrate.py --db data/jubaopen-v207.db
```

#### P4/P5: 填充触点和活动关联

```bash
python V207_p45_migrate.py --db data/jubaopen-v207.db
```

### 3.5 验证升级

运行综合测试脚本：

```bash
python V207_p7_test.py --db data/jubaopen-v207.db
```

预期输出：
```
======================================================================
Jubaopen V207.8.0 / Schema 211 综合测试
======================================================================

【P1: 企业组织预设测试】
  ✓ 企业存在
  ✓ 工作区：1 个
  ✓ 部门：5 个
  ✓ 团队：3 个
  ✓ 业务线：2 个
  ✓ 市场：16 个
  ✓ 职位：12 个

【P2: 平台字典测试】
  ✓ 平台：5 个
  ✓ 渠道类型：28 个
  ✓ 渠道账号 platform_id 填充率：100.0% (150/150)

【P3: 来源类型测试】
  ✓ 来源类型：8 个
  ✓ sources.source_type_id 列存在
  ✓ 来源 source_type_id 填充率：100.0% (200/200)

【P4/P5: 触点与活动测试】
  ✓ source_touchpoints.channel_type_id 列存在
  ✓ campaigns.business_line_id 和 market_id 列存在
  ✓ 触点 channel_type_id 填充率：98.5% (510/518)
  ✓ 活动业务线/市场填充率：92.0% (23/25)

【迁移记录检查】
  ✓ V211_030_channel_and_source_types: 渠道类型与来源类型独立字典表
  ✓ V211_040_sources_type_id: sources表添加source_type_id外键
  ✓ V211_050_touchpoints_campaigns_enhance: 触点渠道类型与活动业务线市场关联

======================================================================
✓ 所有测试通过
======================================================================
```

---

## 四、客户端适配

### 4.1 必须修改的代码

#### 旧用户创建接口（已废弃）

**旧代码**：
```javascript
POST /api/v207/center/user
{
  "username": "john_doe",
  "password": "...",
  "displayName": "John Doe"
}
```

**新代码**：
```javascript
POST /api/v207/admin/users
{
  "username": "john_doe",
  "displayName": "John Doe",
  "roleId": "role_xxx",           // 必填
  "positionId": "POS-SALES",      // 可选
  "teamIds": ["TEAM-JBP"]         // 可选
}
```

#### 渠道账号创建接口（强制 platformId）

**旧代码**：
```javascript
POST /api/v207/admin/accounts
{
  "channel": "whatsapp",
  "displayName": "客服专线"
}
```

**新代码**：
```javascript
POST /api/v207/admin/accounts
{
  "platformId": "plt-whatsapp",   // 必填
  "displayName": "客服专线"
}
```

### 4.2 推荐升级的代码

#### 来源创建（支持类型 ID）

```javascript
POST /api/v207/admin/sources
{
  "workspaceId": "ws-global",
  "name": "Facebook 广告-春季促销",
  "channel": "facebook",
  "accountIdentity": "fb_page_123456",
  "platformId": "plt-facebook",
  "sourceTypeId": "st-paid",      // 新增：精确类型
  "direction": "inbound"
}
```

#### 活动创建（支持业务线和市场）

```javascript
POST /api/v207/admin/campaigns
{
  "workspaceId": "ws-global",
  "name": "2026 春季欧洲促销",
  "type": "paid",
  "platformId": "plt-facebook",
  "businessLineId": "BL-QUANT",   // 新增：业务线
  "marketId": "MKT-EUROPE",       // 新增：目标市场
  "startAt": 1711929600000,
  "endAt": 1719705600000
}
```

### 4.3 前端适配建议

#### 渠道账号选择器

```vue
<template>
  <select v-model="form.platformId">
    <option v-for="p in platforms" :value="p.platform_id">
      {{ p.platform_name }}
    </option>
  </select>
</template>

<script>
export default {
  async mounted() {
    // 获取平台列表
    const res = await fetch('/api/v207/admin/platforms');
    this.platforms = res.items;
  }
}
</script>
```

#### 来源类型选择器

```vue
<template>
  <select v-model="form.sourceTypeId">
    <option value="">-- 请选择来源类型 --</option>
    <option v-for="st in sourceTypes" :value="st.source_type_id">
      {{ st.name }}
    </option>
  </select>
</template>

<script>
export default {
  async mounted() {
    const res = await fetch('/api/v207/admin/source-types');
    this.sourceTypes = res.items;
  }
}
</script>
```

---

## 五、回滚方案

### 5.1 紧急回滚（恢复备份）

如果升级后出现严重问题：

```bash
# 1. 停止服务
pkill -f V207_center_service.py

# 2. 恢复备份
cp data/jubaopen-v207.db.backup-20260922 data/jubaopen-v207.db

# 3. 重启服务
python V207_center_service.py
```

### 5.2 部分回滚（仅回退迁移）

如果只需要回退某个迁移：

```bash
sqlite3 data/jubaopen-v207.db << EOF
-- 删除迁移记录
DELETE FROM schema_migrations WHERE migration_id = 'V211_050_touchpoints_campaigns_enhance';

-- 删除新增列
ALTER TABLE source_touchpoints DROP COLUMN channel_type_id;
ALTER TABLE campaigns DROP COLUMN business_line_id;
ALTER TABLE campaigns DROP COLUMN market_id;
EOF
```

**注意**：SQLite 不支持 `DROP COLUMN`，实际需要重建表。不推荐手动回滚，建议使用备份恢复。

---

## 六、常见问题

### Q1: 升级后旧客户端报 "PLATFORM_ID_REQUIRED" 错误？

**原因**：旧代码使用 `channel` 参数创建渠道账号，新版本强制要求 `platformId`。

**解决**：
1. 更新客户端代码，传入 `platformId`
2. 临时兼容：在 `V207_channel_service.py` 中恢复 `channel` 到 `platformId` 的映射逻辑

### Q2: 历史数据 platform_id 填充率低于 100%？

**原因**：旧数据的 `channel` 字段值在 `platforms` 表中找不到匹配。

**解决**：
```bash
# 查看未匹配的渠道
sqlite3 data/jubaopen-v207.db << EOF
SELECT DISTINCT channel 
FROM channel_accounts 
WHERE platform_id IS NULL OR platform_id = '';
EOF

# 手动创建缺失的平台
sqlite3 data/jubaopen-v207.db << EOF
INSERT INTO platforms(platform_id, platform_code, platform_name, status, created_at, updated_at)
VALUES('plt-line', 'line', 'LINE Messaging', 'active', $(date +%s)000, $(date +%s)000);
EOF

# 重新运行迁移
python V207_p2_migrate.py --db data/jubaopen-v207.db
```

### Q3: 如何添加自定义渠道类型？

```bash
# 通过 API 添加
curl -X POST http://localhost:8000/api/v207/admin/channel-types \
  -H "Content-Type: application/json" \
  -d '{
    "platformId": "plt-telegram",
    "channelTypeCode": "tg_channel_post",
    "name": "Telegram 频道发布",
    "direction": "outbound"
  }'
```

### Q4: 归因分析如何按渠道类型聚合？

```sql
SELECT ct.name AS channel_type,
       COUNT(DISTINCT tp.touchpoint_id) AS touchpoints,
       COUNT(DISTINCT ca.contact_id) AS conversions,
       ROUND(CAST(COUNT(DISTINCT ca.contact_id) AS REAL) / COUNT(DISTINCT tp.touchpoint_id) * 100, 2) AS conversion_rate
FROM source_touchpoints tp
LEFT JOIN channel_types ct ON ct.channel_type_id = tp.channel_type_id
LEFT JOIN contact_attributions ca ON ca.touchpoint_id = tp.touchpoint_id
WHERE tp.occurred_at BETWEEN ? AND ?
GROUP BY ct.channel_type_id
ORDER BY conversions DESC;
```

---

## 七、升级检查清单

升级前：
- [ ] 备份生产数据库
- [ ] 在测试环境验证升级流程
- [ ] 通知相关开发团队 API 变更
- [ ] 准备回滚方案

升级中：
- [ ] 停止生产服务
- [ ] 执行数据库迁移
- [ ] 运行 P1 初始化脚本（仅首次）
- [ ] 运行 P2/P3/P45 数据迁移脚本
- [ ] 执行 P7 综合测试

升级后：
- [ ] 验证关键业务流程
- [ ] 检查客户端兼容性
- [ ] 监控服务日志和错误率
- [ ] 更新API 文档
- [ ] 通知用户新功能

---

## 八、技术支持

遇到问题请查阅：
- 详细实施报告：`docs/P*_implementation_report.md`
- 代码规范检查：`python V207_p6_check.py`
- 综合测试：`python V207_p7_test.py --db <path>`

**联系方式**：support@jubaopen.com

---

**升级文档版本**: 1.0  
**最后更新**: 2026-09-22
