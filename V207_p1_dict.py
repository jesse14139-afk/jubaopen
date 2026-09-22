#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P1 渠道类型与来源类型字典表定义（Schema 211 扩展）

本模块定义：
- channel_types：独立渠道类型字典，与平台和来源类型分离
- source_type_definitions：企业级来源类型字典

渠道类型回答"通过什么方式接触"，而非"在哪个平台"。
来源类型回答"客户以什么性质获得"，跨平台统一。

P2 阶段需要：
1. sources 表增加 channel_type_id 外键
2. sources.source_type 迁移为 source_type_code
3. channel_accounts 移除旧五平台硬编码
"""

# ===== 1. 渠道类型表定义 =====
CHANNEL_TYPES_DDL = """
CREATE TABLE IF NOT EXISTS channel_types(
    channel_type_id    TEXT PRIMARY KEY,
    platform_id        TEXT,                          -- 所属平台（可空表示跨平台通用）
    channel_type_code TEXT NOT NULL UNIQUE,         -- 内部编码，如 fb_group_promotion
    name              TEXT NOT NULL,                 -- 显示名称，如 "Facebook 群组推广"
    description       TEXT,
    direction         TEXT NOT NULL DEFAULT 'bidirectional'
                      CHECK(direction IN ('inbound','outbound','bidirectional')),
    is_active         INTEGER NOT NULL DEFAULT 1,
    sort_order        INTEGER NOT NULL DEFAULT 0,
    created_at        INTEGER NOT NULL,
    updated_at        INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_channel_type_platform ON channel_types(platform_id);
CREATE INDEX IF NOT EXISTS idx_channel_type_active ON channel_types(is_active);
"""

# ===== 2. 来源类型表定义 =====
SOURCE_TYPE_DEFINITIONS_DDL = """
CREATE TABLE IF NOT EXISTS source_type_definitions(
    source_type_id      TEXT PRIMARY KEY,
    source_type_code    TEXT NOT NULL UNIQUE,        -- 内部编码，如 paid_ad
    name                TEXT NOT NULL,                -- 显示名称，如 "付费广告"
    description         TEXT,
    is_active           INTEGER NOT NULL DEFAULT 1,
    sort_order          INTEGER NOT NULL DEFAULT 0,
    created_at          INTEGER NOT NULL,
    updated_at          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_source_type_active ON source_type_definitions(is_active);
"""

# ===== 3. 渠道类型预设数据 =====
CHANNEL_TYPES_SEED = [
    # Google
    ('ct-google-search-ad',    'google',     'google_search_ad',     'Google 搜索广告',      '在 Google 搜索结果中展示的广告',             'outbound',  1),
    ('ct-google-display-ad',   'google',     'google_display_ad',    'Google 展示广告',      '在 Google 展示网络中展示的广告',            'outbound',  2),
    ('ct-google-youtube-ad',   'google',     'google_youtube_ad',    'YouTube 广告',         '在 YouTube 平台投放的视频广告',            'outbound',  3),
    ('ct-google-remarketing',  'google',     'google_remarketing',   'Google 再营销',        '对曾访问过网站的用户再次投放广告',          'outbound',  4),
    ('ct-google-organic',      'google',     'google_organic_search','Google 自然搜索',      '通过 SEO 自然获得的搜索流量',              'inbound',   5),

    # Facebook
    ('ct-fb-feed-ad',          'facebook',   'fb_feed_ad',          'Facebook 动态广告',    '在用户动态中展示的广告',                   'outbound',  10),
    ('ct-fb-video-ad',         'facebook',   'fb_video_ad',         'Facebook 视频广告',   '在 Facebook 投放的视频广告',              'outbound',  11),
    ('ct-fb-lead-ad',         'facebook',   'fb_lead_ads',         'Facebook Lead Ads',   'Facebook 潜在客户表单广告',                'outbound',  12),
    ('ct-fb-page-content',     'facebook',   'fb_page_content',     'Facebook 主页内容',    '通过 Facebook 主页发布内容获客',          'inbound',   13),
    ('ct-fb-group-promotion',  'facebook',   'fb_group_promotion',  'Facebook 群组推广',   '在 Facebook 群组中进行推广',              'outbound',  14),
    ('ct-fb-group-interact',   'facebook',   'fb_group_interaction','Facebook 群组互动',    '在 Facebook 群组中与用户互动',            'bidirectional', 15),
    ('ct-fb-messenger',        'facebook',   'fb_messenger',        'Messenger 私信',       '通过 Facebook Messenger 进行沟通',        'bidirectional', 16),
    ('ct-fb-friend-outbound',  'facebook',   'fb_friend_outbound',  '企业主动好友申请',     '企业主动向用户发送好友申请',              'outbound',  17),
    ('ct-fb-friend-inbound',   'facebook',   'fb_friend_inbound',   '客户主动添加好友',     '客户主动向企业账号发送好友申请',          'inbound',   18),

    # Instagram
    ('ct-ig-feed',             'instagram',  'ig_feed',             'Instagram Feed',       'Instagram 信息流内容',                    'inbound',   20),
    ('ct-ig-story',            'instagram',  'ig_story',            'Instagram Story',      'Instagram 快拍内容',                     'inbound',   21),
    ('ct-ig-reels',            'instagram',  'ig_reels',            'Instagram Reels',     'Instagram 短视频内容',                    'inbound',   22),
    ('ct-ig-profile',          'instagram',  'ig_profile_content',  'Instagram 主页内容',   '通过 Instagram 主页内容吸引关注',         'inbound',   23),
    ('ct-ig-comment',          'instagram',  'ig_comment',          'Instagram 评论互动',    '通过评论与用户互动',                     'bidirectional', 24),
    ('ct-ig-dm-outbound',      'instagram',  'ig_dm_outbound',     'Instagram 主动私信',    '企业主动向用户发送私信',                  'outbound',  25),
    ('ct-ig-dm-inbound',       'instagram',  'ig_dm_inbound',      'Instagram 客户私信',    '客户主动向企业账号发送私信',              'inbound',   26),

    # TikTok
    ('ct-tk-feed-ad',          'tiktok',    'tk_feed_ad',          'TikTok 信息流广告',    '在 TikTok 信息流中展示的广告',            'outbound',  30),
    ('ct-tk-short-video',      'tiktok',    'tk_short_video',      'TikTok 短视频内容',    '通过 TikTok 短视频内容获客',             'inbound',   31),
    ('ct-tk-live',             'tiktok',    'tk_live',             'TikTok 直播',          '通过 TikTok 直播与用户互动',             'bidirectional', 32),
    ('ct-tk-profile',          'tiktok',    'tk_profile_visit',    'TikTok 主页访问',      '用户通过主页了解并关注',                 'inbound',   33),
    ('ct-tk-comment',          'tiktok',    'tk_comment',          'TikTok 评论互动',      '通过评论与用户互动',                     'bidirectional', 34),
    ('ct-tk-dm',              'tiktok',    'tk_dm',               'TikTok 私信',          '通过私信进行沟通',                       'bidirectional', 35),

    # WhatsApp
    ('ct-wa-click-to-chat',    'whatsapp',  'wa_click_to_chat',    'Click-to-WhatsApp',    '点击广告直接跳转 WhatsApp 聊天',         'outbound',  40),
    ('ct-wa-qr',              'whatsapp',  'wa_qr',               'WhatsApp 二维码',      '扫描二维码添加 WhatsApp 联系人',         'inbound',   41),
    ('ct-wa-link',            'whatsapp',  'wa_link',             'WhatsApp 链接转入',    '通过链接转入 WhatsApp 会话',             'inbound',   42),
    ('ct-wa-inbound-add',     'whatsapp',  'wa_inbound_add',      '客户主动添加',          '客户主动将企业账号加入联系人',           'inbound',   43),
    ('ct-wa-outbound-followup','whatsapp', 'wa_outbound_followup', '企业主动跟进',         '企业主动向客户发送消息',                 'outbound',  44),
    ('ct-wa-template',        'whatsapp',  'wa_template',         'WhatsApp 模板消息',    '通过预批准模板消息触达客户',             'outbound',  45),
    ('ct-wa-service',         'whatsapp',  'wa_service',          'WhatsApp 客户服务',    '通过 WhatsApp 提供客户服务',             'bidirectional', 46),

    # Telegram
    ('ct-tg-group',           'telegram',  'tg_group',            'Telegram 群组',        '在 Telegram 群组中与用户互动',           'bidirectional', 50),
    ('ct-tg-channel',         'telegram',  'tg_channel',          'Telegram 频道',         '通过 Telegram 频道发布内容',             'inbound',   51),
    ('ct-tg-bot',             'telegram',  'tg_bot',              'Telegram 机器人',      '通过 Telegram 机器人提供自动化服务',   'bidirectional', 52),
    ('ct-tg-invite-link',     'telegram',  'tg_invite_link',     'Telegram 邀请链接',    '通过邀请链接加入群组或关注频道',         'inbound',   53),
    ('ct-tg-inbound-dm',      'telegram',  'tg_inbound_dm',      '客户主动私信',          '客户主动向企业账号发送私信',              'inbound',   54),
    ('ct-tg-outbound-followup','telegram', 'tg_outbound_followup', '企业跟进',             '企业主动向客户发送消息',                 'outbound',  55),

    # 跨平台 / 通用
    ('ct-cross-platform',     None,         'cross_platform_transfer','跨平台转入',          '从其他平台转入当前平台',                 'inbound',   90),
    ('ct-website-form',       None,         'website_form',         '官网表单',              '通过官网联系表单提交',                   'inbound',   91),
    ('ct-website-chat',       None,         'website_chat',        '官网在线咨询',          '通过官网在线客服沟通',                   'inbound',   92),
    ('ct-email',              None,         'email',                'Email',                 '通过电子邮件联系',                       'bidirectional', 93),
    ('ct-sms',                None,         'sms',                  'SMS',                   '通过短信联系',                          'outbound',  94),
    ('ct-partner-referral',   None,         'partner_referral',    '合作伙伴推荐',          '由合作伙伴或资源商推荐',                 'inbound',   95),
    ('ct-customer-referral',  None,         'customer_referral',   '客户转介绍',            '由现有客户推荐新客户',                   'inbound',   96),
    ('ct-import',             None,         'import',               '名单导入',               '购买或导入的客户名单',                   'inbound',   97),
    ('ct-offline',            None,         'offline',              '线下活动',               '通过线下活动获客',                       'inbound',   98),
    ('ct-manual',             None,         'manual',               '人工录入',               '由业务人员手动创建的客户记录',           'outbound',  99),
]

# ===== 4. 来源类型预设数据 =====
SOURCE_TYPES_SEED = [
    ('st-paid-ad',       'paid_ad',             '付费广告',        '直接支付广告费用获得流量',            1),
    ('st-organic-content','organic_content',     '自然内容',        '通过非付费内容自然获得流量',         2),
    ('st-group-promotion','group_promotion',     '群组推广',        '在群组、频道或社群中推广获得',       3),
    ('st-social-outreach','social_outreach',     '主动社交开发',    '企业主动加好友、关注或私信',         4),
    ('st-social-inbound', 'social_inbound',     '客户主动联系',    '客户主动发起联系',                  5),
    ('st-partner-referral','partner_referral',   '合作方推荐',      '由合作伙伴或资源商推荐',             6),
    ('st-customer-referral','customer_referral','客户转介绍',      '由老客户推荐新客户',                 7),
    ('st-platform-transfer','platform_transfer', '跨平台转入',      '从其他平台转入当前平台',             8),
    ('st-website',        'website',              '官网',            '通过官网渠道获得',                   9),
    ('st-import',        'import',               '名单导入',        '购买或导入客户名单',                 10),
    ('st-offline',       'offline',              '线下来源',        '通过线下活动或会议获得',             11),
    ('st-direct',        'direct',               '直接访问',        '无法识别上游的直接接触',             12),
    ('st-unknown',       'unknown',              '未知',            '暂时无法归类的来源',                 13),
]


PLATFORM_CODE_ALIASES = {
    'google': 'google',
}

DICTIONARY_PLATFORMS = (
    ('google', 'Google', 'search'),
)


def ensure_dictionary_platforms(c, n):
    """补齐渠道字典引用的平台，避免渠道类型悬挂在不存在的平台代码上。"""
    for code, name, kind in DICTIONARY_PLATFORMS:
        c.execute(
            """INSERT OR IGNORE INTO platforms
               (platform_id, platform_code, platform_name, platform_kind, status, created_at, updated_at)
               VALUES(?,?,?,?,'active',?,?)""",
            ('plt_' + code, code, name, kind, n, n)
        )


def resolve_platform_id(c, raw):
    """把种子里的平台代码解析为 platforms.platform_id。"""
    if raw is None or not str(raw).strip():
        return None
    raw = str(raw).strip()
    if raw.startswith('plt_'):
        found = c.execute('SELECT platform_id FROM platforms WHERE platform_id=?', (raw,)).fetchone()
        return found[0] if found else None
    code = PLATFORM_CODE_ALIASES.get(raw, raw)
    found = c.execute('SELECT platform_id FROM platforms WHERE platform_code=?', (code,)).fetchone()
    return found[0] if found else None


def seed_channel_and_source_types(db, n=None):
    """
    初始化渠道类型和来源类型字典。
    幂等：已存在的记录不重复插入。
    """
    from V207_shared_db import now_ms
    if n is None:
        n = now_ms()

    results = {
        'channel_types_created': 0,
        'channel_types_existed': 0,
        'channel_types_relinked': 0,
        'source_types_created': 0,
        'source_types_existed': 0,
    }

    with db.tx() as c:
        ensure_dictionary_platforms(c, n)
        for row in CHANNEL_TYPES_SEED:
            ct_id, raw_platform_id, ct_code, name, desc, direction, sort_order = row
            platform_id = resolve_platform_id(c, raw_platform_id)
            existing = c.execute(
                "SELECT channel_type_id, platform_id FROM channel_types WHERE channel_type_id=?",
                (ct_id,)
            ).fetchone()
            if not existing:
                c.execute(
                    """INSERT INTO channel_types
                       (channel_type_id, platform_id, channel_type_code, name, description, direction, is_active, sort_order, created_at, updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (ct_id, platform_id, ct_code, name, desc or '', direction, 1, sort_order, n, n)
                )
                results['channel_types_created'] += 1
            else:
                current_platform_id = existing[1]
                if platform_id and current_platform_id in (None, '', raw_platform_id) and current_platform_id != platform_id:
                    c.execute(
                        "UPDATE channel_types SET platform_id=?, updated_at=? WHERE channel_type_id=?",
                        (platform_id, n, ct_id)
                    )
                    results['channel_types_relinked'] = results.get('channel_types_relinked', 0) + 1
                results['channel_types_existed'] += 1

        for row in SOURCE_TYPES_SEED:
            st_id, st_code, name, desc, sort_order = row
            existing = c.execute(
                "SELECT source_type_id FROM source_type_definitions WHERE source_type_id=?",
                (st_id,)
            ).fetchone()
            if not existing:
                c.execute(
                    """INSERT INTO source_type_definitions
                       (source_type_id, source_type_code, name, description, is_active, sort_order, created_at, updated_at)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (st_id, st_code, name, desc or '', 1, sort_order, n, n)
                )
                results['source_types_created'] += 1
            else:
                results['source_types_existed'] += 1

    return results


# ===== 5. V211 迁移记录 =====
CHANNEL_TYPES_MIGRATION_SQL = """
-- V211_030_channel_and_source_types
-- 渠道类型与来源类型独立字典表
-- 执行时间：2026-09-22
""" + CHANNEL_TYPES_DDL + SOURCE_TYPE_DEFINITIONS_DDL
