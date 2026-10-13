#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""停用旧版 18 位预制测试联系人（可选升级工具）。

只处理同时带有 business_json.testData=true 且 presetKey 为 demo-001..demo-018
的结构化测试记录；不按姓名、数量或模糊手机号匹配，避免误伤真实客户。
本工具不会修改组织、用户、角色、团队、标签、字典等其他预设。
"""
import argparse, json, sqlite3, time
from pathlib import Path
KEYS = frozenset('demo-%03d' % i for i in range(1, 19))

def _is_target(raw):
    try: value=json.loads(raw or '{}')
    except (TypeError, ValueError): return False
    return isinstance(value,dict) and value.get('testData') is True and value.get('presetKey') in KEYS

def remove_preset_test_contacts(db_path):
    con=sqlite3.connect(str(db_path),timeout=30); con.row_factory=sqlite3.Row
    try:
        cols={r[1] for r in con.execute('PRAGMA table_info(contacts)')}
        required={'contact_id','business_json','deleted_at','next_follow_up_at'}
        if not required.issubset(cols): raise RuntimeError('CONTACT_SCHEMA_UNSUPPORTED: '+','.join(sorted(required-cols)))
        rows=list(con.execute("SELECT contact_id,business_json FROM contacts WHERE deleted_at IS NULL AND business_json LIKE '%\"presetKey\"%'"))
        ids=[r['contact_id'] for r in rows if _is_target(r['business_json'])]
        now=int(time.time()*1000)
        con.execute('BEGIN IMMEDIATE')
        for cid in ids:
            # 保留审计链路，按产品软删除约定让联系人立即退出业务列表，并停止后续跟进。
            sets=['deleted_at=?','next_follow_up_at=NULL']
            vals=[now]
            if 'deleted_by' in cols: sets.append("deleted_by='system'")
            if 'delete_reason' in cols: sets.append("delete_reason='移除旧版预制测试联系人'")
            if 'updated_at' in cols: sets.append('updated_at=?'); vals.append(now)
            vals.append(cid)
            con.execute('UPDATE contacts SET '+','.join(sets)+' WHERE contact_id=?',vals)
        con.commit(); print('已停用旧版预制测试联系人：%d 位' % len(ids)); return len(ids)
    except Exception:
        con.rollback(); raise
    finally: con.close()

def main():
    ap=argparse.ArgumentParser(description='安全停用旧版18位预制测试联系人（不影响其他预设）')
    ap.add_argument('--db',required=True); args=ap.parse_args(); p=Path(args.db).expanduser().resolve()
    if not p.is_file(): raise RuntimeError('数据库不存在：'+str(p))
    remove_preset_test_contacts(p)
if __name__=='__main__': main()
