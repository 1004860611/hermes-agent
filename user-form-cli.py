#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用户信息登记表 - 命令行版本"""

import json
from pathlib import Path
from datetime import datetime

def get_input(prompt, required=True, validator=None):
    """获取用户输入"""
    while True:
        value = input(prompt).strip()
        if not value and required:
            print("❌ 此项为必填项，请输入！")
            continue
        if validator and not validator(value):
            continue
        return value

def get_gender():
    """选择性别"""
    print("\n请选择性别：")
    print("  1) 男")
    print("  2) 女")
    print("  3) 其他")
    
    while True:
        choice = input("请输入选项 (1/2/3): ").strip()
        if choice == '1':
            return 'male', '男'
        elif choice == '2':
            return 'female', '女'
        elif choice == '3':
            return 'other', '其他'
        else:
            print("❌ 无效选项，请输入 1、2 或 3")

def get_education():
    """选择学历"""
    print("\n请选择学历：")
    options = [
        ('high_school', '高中/中专'),
        ('associate', '大专'),
        ('bachelor', '本科'),
        ('master', '硕士'),
        ('doctor', '博士'),
        ('other', '其他')
    ]
    
    for i, (_, label) in enumerate(options, 1):
        print(f"  {i}) {label}")
    
    while True:
        choice = input("请输入选项 (1-6): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            idx = int(choice) - 1
            return options[idx][0], options[idx][1]
        else:
            print("❌ 无效选项，请输入 1-6")

def main():
    """主函数"""
    print("=" * 50)
    print("📋 用户信息登记表")
    print("=" * 50)
    
    # 收集信息
    name = get_input("\n请输入姓名：", required=True)
    
    gender_code, gender_label = get_gender()
    
    edu_code, edu_label = get_education()
    
    age = get_input(
        "请输入年龄：",
        required=True,
        validator=lambda x: x.isdigit() and 1 <= int(x) <= 150
    )
    
    # 构建数据
    data = {
        "name": name,
        "gender": gender_label,
        "education": edu_label,
        "age": int(age),
        "submit_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # 保存数据
    data_file = Path(__file__).parent / "user_data.json"
    
    # 读取现有数据
    existing_data = []
    if data_file.exists():
        with open(data_file, 'r', encoding='utf-8') as f:
            try:
                existing_data = json.load(f)
            except json.JSONDecodeError:
                existing_data = []
    
    # 添加新数据
    existing_data.append(data)
    
    # 保存
    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, ensure_ascii=False, indent=2)
    
    # 显示结果
    print("\n" + "=" * 50)
    print("✅ 提交成功！")
    print("=" * 50)
    print(f"\n📄 您填写的信息：")
    print(f"   姓名：{data['name']}")
    print(f"   性别：{data['gender']}")
    print(f"   学历：{data['education']}")
    print(f"   年龄：{data['age']} 岁")
    print(f"   提交时间：{data['submit_time']}")
    print(f"\n💾 数据已保存到：{data_file.absolute()}")
    print("=" * 50)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ 操作已取消")
    except EOFError:
        print("\n\n❌ 输入已结束")
