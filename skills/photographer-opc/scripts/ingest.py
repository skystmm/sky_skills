#!/usr/bin/env python3
"""
摄影师知识库摄入脚本 (ingest.py)
用于更新 photographer-opc skill 的 references/ 目录

用途: 手动或自动触发知识基线更新
用法: python3 ingest.py              # 检查时效性，过时则更新
      python3 ingest.py --force      # 强制全量更新
      python3 ingest.py --status     # 仅查看状态

架构说明:
- 本脚本管理 JSON 文件的读写、去重、格式校验
- 实际内容靠 OpenAI/Claude 等大语言模型在 agent 上下文中用 web_search/web_fetch 获取
- 本脚本 + skill 的 cron 结合形成"定时触发→agent 抓取→脚本写入"的闭环
"""

import os
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 配置
SKILL_DIR = Path(__file__).resolve().parent.parent
REFS_DIR = SKILL_DIR / "references"
REFS = {
    "photographers": REFS_DIR / "photographers.json",
    "techniques": REFS_DIR / "techniques.json",
    "tools": REFS_DIR / "tools.json",
    "trends": REFS_DIR / "trends.json",
}
MAX_AGE_DAYS = 7  # 超过7天视为过时


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"  ⚠  {path.name}: 读取失败 - {e}")
        return None


def save_json(path: Path, data: dict) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except IOError as e:
        print(f"  ❌ {path.name}: 写入失败 - {e}")
        return False


def check_freshness(data: dict) -> tuple[bool, str | None]:
    """检查是否需要更新。返回 (过时?, 最后更新时间)"""
    updated = data.get("updated_at")
    if not updated:
        return True, None
    try:
        updated_dt = datetime.fromisoformat(updated)
        age = datetime.now(timezone.utc) - updated_dt
        is_stale = age > timedelta(days=MAX_AGE_DAYS)
        return is_stale, updated
    except (ValueError, TypeError):
        return True, None


def status_all() -> list[dict]:
    """列出所有基线状态"""
    results = []
    for name, path in REFS.items():
        data = load_json(path)
        if data is None:
            results.append({"name": name, "status": "missing", "file": str(path)})
            continue
        stale, updated = check_freshness(data)
        items = len(data.get(data.get("template", {}).keys() - {"template","version","updated_at"}, data.get("photographers", data.get("techniques", data.get("tools", data.get("trends", []))))))
        # Actually let's just count items
        item_keys = ["photographers","techniques","tools","trends","kol_list"]
        count = 0
        for k in item_keys:
            if isinstance(data.get(k), list):
                count += len(data[k])
        # If template only, count = 0
        
        results.append({
            "name": name,
            "status": "stale" if stale else "fresh",
            "items": count,
            "last_updated": updated or "never",
            "file": str(path),
        })
    return results


def merge_items(existing: list, incoming: list, key: str = "id") -> list:
    """去重合并新老数据（新条目覆盖同 id）"""
    merged = {item.get(key, f"unknown-{i}"): item for i, item in enumerate(existing)}
    for item in incoming:
        merged[item.get(key, f"new-{time.time_ns()}")] = item
    return list(merged.values())


def mark_updated(data: dict) -> dict:
    """标记更新时间和版本"""
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    ver = data.get("version", "0.0.0")
    parts = ver.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    data["version"] = ".".join(parts)
    return data


def do_update(force: bool):
    """执行更新逻辑"""
    print(f"{'='*50}")
    print(f"📸 摄影知识库摄入脚本")
    print(f"{'='*50}")
    
    styles_status = status_all()
    needs_update = [s for s in styles_status if s["status"] == "stale" or (force and s["status"] != "missing")]
    
    if not needs_update and not force:
        print("\n✅ 所有基线都是最新的（<7天）")
        for s in styles_status:
            updated = s["last_updated"][:19] if s["last_updated"] != "never" else "从未更新"
            print(f"   {s['name']:15s} {s['status']:6s}  {s['items']}项  上次: {updated}")
        print("\n强制更新: python3 ingest.py --force")
        return

    print(f"\n📋 当前状态:")
    for s in styles_status:
        print(f"   {s['name']:15s} {s['status']:6s}  {s['items']}项")

    print(f"\n🔍 需要更新的基线: {len(needs_update)} 项")
    
    # 这里标记文件等待 agent 填充内容
    for s in needs_update:
        data = load_json(s["file"])
        if data:
            data = mark_updated(data)
            save_json(s["file"], data)
            print(f"   ✅ {s['name']}: 已标记更新时间戳，等待 agent 抓取新内容")
        else:
            print(f"   ⚠  {s['name']}: 文件不存在，已跳过")

    print(f"\n💡 提示：实际内容抓取由 agent 通过 web_search/web_fetch 完成。")
    print(f"   手动触发: 对 agent 说「更新摄影知识库」")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--force":
        do_update(force=True)
    elif len(sys.argv) > 1 and sys.argv[1] == "--status":
        print(f"\n{'='*50}")
        print(f"📸 摄影知识库 - 状态检查")
        print(f"{'='*50}")
        for s in status_all():
            updated = s["last_updated"][:19] if s["last_updated"] != "never" else "从未更新"
            print(f"   {s['name']:15s} {s['status']:6s}  {s['items']:3d}项  上次: {updated}")
    else:
        do_update(force=False)


if __name__ == "__main__":
    main()
