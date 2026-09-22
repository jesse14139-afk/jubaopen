#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P6 代码规范检查脚本：命名规范与 API 响应格式验证

本脚本检查：
1. Python 服务层变量命名规范（snake_case vs camelCase）
2. API 响应格式标准化（ok, code, message, data）
3. 数据库字段命名一致性

运行方式：
  python V207_p6_check.py

输出：
  - 命名不一致项
  - 非标准 API 响应
  - 建议修正清单
"""
import re, sys, json
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent

def check_api_response_format():
    """检查 API 响应格式是否标准化。"""
    issues = []
    service_files = list(ROOT.glob('*_service.py'))
    
    # 标准响应格式：{'ok': bool, 'code'?: str, 'message'?: str, ...}
    error_pattern = re.compile(r"return\s+\{[^}]*'ok'\s*:\s*False[^}]*\}")
    success_pattern = re.compile(r"return\s+\{[^}]*'ok'\s*:\s*True[^}]*\}")
    
    for f in service_files:
        content = f.read_text(encoding='utf-8')
        lines = content.split('\n')
        
        for i, line in enumerate(lines, 1):
            # 检查错误响应是否包含 code 和 message
            if "'ok':False" in line or "'ok': False" in line:
                if "'code'" not in line and "'message'" not in line:
                    issues.append({
                        'file': f.name,
                        'line': i,
                        'type': 'missing_error_fields',
                        'message': '错误响应缺少 code 或 message 字段'
                    })
    
    return issues

def check_naming_conventions():
    """检查命名规范一致性。"""
    issues = []
    service_files = list(ROOT.glob('*_service.py'))
    
    # API 参数应为 camelCase（前端传入）
    # 内部变量应为 snake_case（Python 标准）
    camel_pattern = re.compile(r"b\.get\('([a-z][a-zA-Z0-9]+)'\)")
    
    for f in service_files:
        content = f.read_text(encoding='utf-8')
        
        # 检查是否混用 camelCase 和 snake_case
        camel_matches = camel_pattern.findall(content)
        
        # 统计命名风格
        camel_case = [m for m in camel_matches if re.match(r'^[a-z]+[A-Z]', m)]
        snake_case = [m for m in camel_matches if '_' in m]
        
        if camel_case and snake_case:
            issues.append({
                'file': f.name,
                'type': 'mixed_naming',
                'camelCase_count': len(camel_case),
                'snake_case_count': len(snake_case),
                'message': f'混用命名风格：camelCase {len(camel_case)} 处，snake_case {len(snake_case)} 处'
            })
    
    return issues

def check_database_fields():
    """检查数据库字段命名一致性。"""
    issues = []
    
    db_file = ROOT / 'V207_shared_db.py'
    if not db_file.exists():
        return issues
    
    content = db_file.read_text(encoding='utf-8')
    
    # 提取 CREATE TABLE 语句中的字段名
    table_pattern = re.compile(r'CREATE TABLE[^(]*\(([^;]+)\)', re.DOTALL)
    field_pattern = re.compile(r'^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+', re.MULTILINE)
    
    tables = table_pattern.findall(content)
    
    for table_def in tables:
        fields = field_pattern.findall(table_def)
        
        # 检查是否有 camelCase 字段（应全部使用 snake_case）
        camel_fields = [f for f in fields if re.match(r'^[a-z]+[A-Z]', f)]
        
        if camel_fields:
            issues.append({
                'type': 'database_camelCase',
                'fields': camel_fields,
                'message': f'数据库字段使用 camelCase（应为 snake_case）：{", ".join(camel_fields)}'
            })
    
    return issues

def generate_report(api_issues, naming_issues, db_issues):
    """生成检查报告。"""
    print("="*70)
    print("P6 代码规范检查报告")
    print("="*70)
    
    # API 响应格式
    print("\n【1. API 响应格式检查】")
    if api_issues:
        print(f"  发现 {len(api_issues)} 处问题：")
        for issue in api_issues[:10]:  # 只显示前 10 个
            print(f"    - {issue['file']}:{issue['line']} - {issue['message']}")
        if len(api_issues) > 10:
            print(f"    ... 还有 {len(api_issues) - 10} 处问题")
    else:
        print("  ✓ 未发现问题")
    
    # 命名规范
    print("\n【2. 命名规范检查】")
    if naming_issues:
        print(f"  发现 {len(naming_issues)} 处问题：")
        for issue in naming_issues:
            print(f"    - {issue['file']}: {issue['message']}")
    else:
        print("  ✓ 命名规范一致")
    
    # 数据库字段
    print("\n【3. 数据库字段命名检查】")
    if db_issues:
        print(f"  发现 {len(db_issues)} 处问题：")
        for issue in db_issues:
            print(f"    - {issue['message']}")
    else:
        print("  ✓ 数据库字段命名规范")
    
    # 总结
    print("\n" + "="*70)
    total = len(api_issues) + len(naming_issues) + len(db_issues)
    if total == 0:
        print("✓ P6 代码规范检查通过，未发现问题")
    else:
        print(f"⚠ 发现 {total} 处需要关注的问题")
        print("\n建议：")
        print("  1. API 参数统一使用 camelCase（前端兼容）")
        print("  2. Python 内部变量统一使用 snake_case")
        print("  3. 数据库字段全部使用 snake_case")
        print("  4. 错误响应必须包含 'code' 和 'message' 字段")
    print("="*70)
    
    return total

def main():
    print("正在扫描代码规范...")
    
    api_issues = check_api_response_format()
    naming_issues = check_naming_conventions()
    db_issues = check_database_fields()
    
    total = generate_report(api_issues, naming_issues, db_issues)
    
    return 0 if total == 0 else 1

if __name__ == '__main__':
    sys.exit(main())
