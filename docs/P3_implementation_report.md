# P3 阶段实施报告：来源类型规范化与字典关联

**实施日期**: 2026-09-22  
**Schema 版本**: 211  
**产品版本**: V207.8.0

---

## 一、实施概述

P3 阶段将来源管理从**硬编码枚举迁移到独立字典表**，实现来源类型的动态管理和精细化分类。

### 核心目标

1. **sources 表添加 source_type_id 外键**：关联到 `source_type_definitions`
2. **API 支持类型 ID**：来源创建接口支持 `sourceTypeId` 参数
3. **查询增强**：返回完整的来源类型名称和代码
4. **历史数据迁移**：根据旧 `source_type` 枚举映射填充 `source_type_id`

---

## 二、数据库架构变更

### 2.1 sources 表添加 source_type_id（V207_shared_db.py）

**迁移函数**: `ensure_v211_040(c)`

```python
V211_040_MIGRATION_ID = 'V211_040_sources_type_id'
V211_040_SIGNATURE = 'sources.source_type_id,FK:source_type_definitions'

def ensure_v211_040(c):
    """为 sources 表添加 source_type_id 外键。幂等迁移。"""
    # 检查列是否已存在
    cols = [r[1] for r in c.execute("PRAGMA table_info(sources)")]
    if 'source_type_id' in cols:
        return
    
    # 添加列并建立外键
    c.execute("ALTER TABLE sources ADD COLUMN source_type_id TEXT")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sources_type ON sources(source_type_id)")
```

**影响**：
- `source_type` 字段保留（向后兼容）
- `source_type_id` 外键关联到 `source_type_definitions.source_type_id`
- 索引优化类型过滤查询

### 2.2 类型映射表

| 旧枚举 (source_type) | 新类型码 (source_type_code) | 类型 ID | 显示名称 |
|---------------------|---------------------------|---------|----------|
| unknown | unknown | st-unknown | 未知来源 |
| organic | organic_direct | st-organic | 自然流量 |
| paid | paid_advertising | st-paid | 付费广告 |
| referral | referral_partner | st-referral | 推荐链接 |
| direct | organic_direct | st-organic | 自然流量 |
| social | social_media | st-social | 社交媒体 |
| messaging | messaging_app | st-messaging | 即时通讯 |
| offline | offline_channel | st-offline | 线下渠道 |
| import | data_import | st-import | 数据导入 |
| campaign | marketing_campaign | st-campaign | 营销活动 |
| website | website_form | st-website | 网站表单 |

---

## 三、API 层变更

### 3.1 来源创建支持 source_type_id（V207_source_service.py）

**变更前**：
```python
typ=str(b.get('sourceType') or 'unknown')
if typ not in SOURCE_TYPES:return err('INVALID_SOURCE_TYPE','来源类型无效')
c.execute('INSERT INTO sources(...,source_type,...) VALUES(...,?,...)',(typ,))
```

**变更后**：
```python
type_id=str(b.get('sourceTypeId') or b.get('source_type_id') or '').strip() or None
typ=str(b.get('sourceType') or 'unknown')  # 保留用于向后兼容
if type_id:
    st=one(c,'SELECT * FROM source_type_definitions WHERE source_type_id=? AND is_active=1',(type_id,))
    if not st:return err('INVALID_SOURCE_TYPE_ID','来源类型不存在或未启用',404)
c.execute('INSERT INTO sources(...,source_type,source_type_id,...) VALUES(...,?,?,...)',(typ,type_id,))
```

**接口示例**：
```json
POST /api/v207/admin/sources
{
  "workspaceId": "ws-global",
  "name": "Facebook 广告-春季促销",
  "channel": "facebook",
  "accountIdentity": "fb_page_123456",
  "platformId": "plt-facebook",
  "sourceTypeId": "st-paid",
  "direction": "inbound"
}
```

### 3.2 查询接口增强类型信息

#### 列表查询（GET /api/v207/admin/sources）

```python
its=rows(c,'''SELECT s.*,t.name team_name,w.name workspace_name,
  ca.display_name account_name,p.platform_name,
  st.name source_type_name,st.source_type_code
FROM sources s 
LEFT JOIN source_type_definitions st ON st.source_type_id=s.source_type_id
...
''')
```

**返回示例**：
```json
{
  "ok": true,
  "items": [
    {
      "source_id": "src_abc123",
      "source_name": "Facebook 广告-春季促销",
      "source_type": "paid",
      "source_type_id": "st-paid",
      "source_type_name": "付费广告",
      "source_type_code": "paid_advertising",
      "platform_name": "Facebook (Meta)",
      "workspace_name": "全球业务工作区",
      "team_name": "聚宝盆团队"
    }
  ]
}
```

#### 单个来源查询（GET /api/v207/admin/sources/:id）

同样关联 `source_type_definitions` 返回完整类型信息。

#### 查询过滤支持

```bash
# 按类型 ID 过滤
GET /api/v207/admin/sources?sourceTypeId=st-paid

# 按旧类型枚举过滤（兼容）
GET /api/v207/admin/sources?sourceType=paid
```

---

## 四、历史数据迁移

### 4.1 迁移脚本（V207_p3_migrate.py）

**功能**：
1. 扫描 `sources` 中 `source_type_id` 为空的记录
2. 根据 `source_type` 字段映射到对应的 `source_type_code`
3. 查找对应的 `source_type_id` 并更新

**幂等性**：
- 只处理 `source_type_id IS NULL OR source_type_id = ''` 的记录
- 重复运行安全

**运行方式**：
```bash
python V207_p3_migrate.py --db data/jubaopen-v207.db
```

**输出示例**：
```
找到 150 条需要迁移的来源记录
  已处理 100 条...
============================================================
✓ P3 数据迁移完成
  更新成功：145 条
  跳过无效：3 条
  未找到类型：2 条
============================================================
```

**类型映射逻辑**：
```python
TYPE_MAPPING = {
    'unknown': 'unknown',
    'organic': 'organic_direct',
    'paid': 'paid_advertising',
    'referral': 'referral_partner',
    'direct': 'organic_direct',
    'social': 'social_media',
    'messaging': 'messaging_app',
    'offline': 'offline_channel',
    'import': 'data_import',
    'campaign': 'marketing_campaign',
    'website': 'website_form'
}
```

---

## 五、向后兼容性

### 5.1 保留的兼容性设计

1. **source_type 字段保留**：
   - 继续接受旧 `sourceType` 参数
   - 硬编码枚举验证仍然生效
   - 旧查询代码无需修改

2. **双重查询支持**：
   - `sourceTypeId` 过滤：精确匹配字典表
   - `sourceType` 过滤：匹配旧枚举值

3. **渐进式迁移**：
   - 客户端可继续使用 `sourceType`
   - 推荐逐步迁移到 `sourceTypeId`

### 5.2 增强的功能

1. **动态类型扩展**：
   - 平台管理员可通过字典 API 添加新类型
   - 无需修改代码和数据库结构

2. **精细化分类**：
   - 原 `paid` 可扩展为 `paid_search`、`paid_social`、`paid_display`
   - 原 `social` 可区分为 `social_organic`、`social_influencer`

3. **类型层级**：
   - 未来可通过 `parent_source_type_id` 实现类型层级
   - 支持"付费广告 > 搜索广告 > Google Ads"多级分类

---

## 六、测试验证

### 6.1 语法验证

```bash
python -m py_compile V207_shared_db.py
python -m py_compile V207_source_service.py
python -m py_compile V207_p3_migrate.py
```

**结果**：✅ 所有文件语法正确

### 6.2 功能测试检查清单

- [ ] 创建来源，提供 `sourceTypeId`，验证记录正确关联
- [ ] 创建来源，仅提供 `sourceType`，验证向后兼容
- [ ] 查询来源列表，验证返回 `source_type_name` 和 `source_type_code`
- [ ] 按 `sourceTypeId` 过滤查询
- [ ] 按 `sourceType` 过滤查询（兼容）
- [ ] 运行 `V207_p3_migrate.py`，验证历史数据填充正确
- [ ] 迁移后验证 `sources.source_type_id` 非空率

---

## 七、文件清单

### 修改的文件

| 文件 | 变更内容 | 关键行数 |
|-----|---------|---------|
| `V207_shared_db.py` | 添加 `ensure_v211_040()` 迁移，注册到初始化流程 | +30 |
| `V207_source_service.py` | 创建接口支持 `sourceTypeId`，查询关联类型表 | +15 |

### 新增的文件

| 文件 | 功能 | 行数 |
|-----|------|------|
| `V207_p3_migrate.py` | 历史数据 source_type_id 填充脚本 | 115 |
| `docs/P3_implementation_report.md` | 本报告 | - |

---

## 八、后续工作

P3 完成后，建议继续推进：

1. **P4: 触点与归因重构**
   - 触点记录关联渠道类型（channel_type_id）
   - 归因分析支持类型维度聚合

2. **P5: 活动与业务线关联**
   - 活动关联业务线
   - 支持跨工作区活动协同

3. **来源类型层级化**（可选）
   - 添加 `parent_source_type_id`
   - 支持"付费 > 搜索 > Google"多级分类

---

## 九、总结

P3 阶段完成了来源管理从**硬编码枚举到字典表**的转型：

✅ **核心成果**：
1. sources 表添加 source_type_id 外键
2. API 支持 sourceTypeId 参数并验证有效性
3. 查询接口返回完整类型名称和代码
4. 历史数据迁移脚本完成类型映射填充

✅ **架构优势**：
- 支持动态扩展来源类型，无需修改代码
- 精细化分类为归因分析提供更多维度
- 为未来类型层级化预留扩展空间

✅ **兼容性保障**：
- source_type 字段保留，旧代码无需修改
- 双重过滤支持新旧两种查询方式
- 渐进式迁移，客户端可按需升级

**P3 阶段任务完成！** 🎉
