"""
群聊记忆持久化模块

按群号分类存储对话上下文，文件内按 user_id 隔离。
文件路径: data/chat_memory/<group_id>.json
格式: {"3921344824": [{"role": "user", ...}, ...], "3879991885": [...]}
"""
import json
from pathlib import Path
from typing import List, Dict

from nonebot.log import logger

_DATA_DIR = Path("data/chat_memory")
_DATA_DIR.mkdir(parents=True, exist_ok=True)


def _get_path(group_id: int) -> Path:
    return _DATA_DIR / f"{group_id}.json"


def _load_all(group_id: int) -> Dict[str, List[Dict[str, str]]]:
    """加载指定群的完整记忆数据"""
    path = _get_path(group_id)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): v for k, v in data.items() if isinstance(v, list)}
        # 旧格式兼容（纯 list），直接丢弃
        return {}
    except Exception as e:
        logger.warning(f"[记忆] 加载群 {group_id} 记忆失败: {e}")
        return {}


def _save_all(group_id: int, data: Dict[str, List[Dict[str, str]]]) -> None:
    """保存指定群的完整记忆数据"""
    path = _get_path(group_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[记忆] 保存群 {group_id} 记忆失败: {e}")


def load_memory(group_id: int, user_id: int, max_context: int = 10) -> List[Dict[str, str]]:
    """加载指定群和用户的对话记忆"""
    all_data = _load_all(group_id)
    mem = all_data.get(str(user_id), [])
    return mem[-max_context:] if len(mem) > max_context else mem


def save_memory(group_id: int, user_id: int, memory: List[Dict[str, str]]) -> None:
    """保存指定群和用户的对话记忆"""
    all_data = _load_all(group_id)
    all_data[str(user_id)] = memory
    _save_all(group_id, all_data)
