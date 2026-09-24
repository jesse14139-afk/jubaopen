#!/usr/bin/env python3
"""V208.1.7 / Schema 215 发布门禁：验证数据库结构、完整性和中文数据字典覆盖率。"""
import argparse,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from V207_shared_db import Database
from V207_schema_catalog import build_schema_catalog
ZH=re.compile(r'[\u4e00-\u9fff]')

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--db',required=True);args=ap.parse_args()
 catalog=build_schema_catalog(Database(args.db)); tables=[t for t in catalog['tables'] if t['objectType']=='table']
 views=[t for t in catalog['tables'] if t['objectType']=='view']
 bad_tables=[t['name'] for t in catalog['tables'] if not t['documented'] or not ZH.search(t['label']) or not ZH.search(t['purpose']) or '暂无' in t['purpose']]
 bad_fields=[t['name']+'.'+f['name'] for t in catalog['tables'] for f in t['fields'] if f['label']==f['name'] or not ZH.search(f['label']) or not ZH.search(f['description']) or '暂无' in f['description']]
 result={'ok':not bad_tables and not bad_fields and catalog['integrity']['quickCheck']=='ok' and not catalog['integrity']['foreignKeyIssues'] and len(tables)==61 and sum(t['fieldCount'] for t in tables)==668,
 'tableCount':len(tables),'tableFieldCount':sum(t['fieldCount'] for t in tables),'viewCount':len(views),'viewFieldCount':sum(t['fieldCount'] for t in views),'totalFieldCount':sum(t['fieldCount'] for t in catalog['tables']),'badTables':bad_tables,'badFields':bad_fields,'quickCheck':catalog['integrity']['quickCheck'],'foreignKeyIssueCount':len(catalog['integrity']['foreignKeyIssues']),'documentationCoverage':catalog['summary']['documentationCoverage']}
 print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['ok'] else 1
if __name__=='__main__':raise SystemExit(main())
