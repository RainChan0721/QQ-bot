"""
内存存储模块
用于暂存待处理的进群请求 + 群黑名单持久化
"""
import json
import os
from typing import Dict, Optional
from dataclasses import dataclass

from nonebot.log import logger


@dataclass
class GroupJoinRequest:
    """进群请求数据模型"""

    group_id: int
    user_id: int
    flag: str
    comment: str
    nickname: str = ""
    level: int = 0


# 内存存储字典，key 格式为 "group_id:user_id"
_pending: Dict[str, GroupJoinRequest] = {}


def _make_key(group_id: int, user_id: int) -> str:
    return f"{group_id}:{user_id}"


def add_request(req: GroupJoinRequest) -> None:
    """添加一条待处理请求"""
    _pending[_make_key(req.group_id, req.user_id)] = req


def get_request(group_id: int, user_id: int) -> Optional[GroupJoinRequest]:
    """获取指定群和用户的待处理请求"""
    return _pending.get(_make_key(group_id, user_id))


def remove_request(group_id: int, user_id: int) -> Optional[GroupJoinRequest]:
    """移除并返回指定请求"""
    return _pending.pop(_make_key(group_id, user_id), None)


def list_requests(group_id: int) -> list[GroupJoinRequest]:
    """列出指定群内所有待处理请求"""
    return [req for req in _pending.values() if req.group_id == group_id]


# ========== 群黑名单持久化 ==========

_BLACKLIST_PATH = os.path.join(os.getcwd(), "group_blacklist.json")
_blacklist: Dict[int, set[int]] = {}


def _load_blacklist() -> None:
    """从 JSON 文件加载群黑名单"""
    global _blacklist
    if not os.path.exists(_BLACKLIST_PATH):
        _blacklist = {}
        return
    try:
        with open(_BLACKLIST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 把 list 转成 set 方便查找
        _blacklist = {int(gid): set(int(uid) for uid in uids) for gid, uids in data.items()}
        total = sum(len(v) for v in _blacklist.values())
        logger.info(f"[黑名单] 已加载: {_BLACKLIST_PATH}, 共 {total} 条记录")
    except Exception as e:
        logger.warning(f"[黑名单] 加载失败: {e}")
        _blacklist = {}


def _save_blacklist() -> None:
    """保存群黑名单到 JSON 文件"""
    try:
        with open(_BLACKLIST_PATH, "w", encoding="utf-8") as f:
            data = {str(gid): sorted(uids) for gid, uids in _blacklist.items()}
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[黑名单] 保存失败: {e}")


def add_to_blacklist(group_id: int, user_id: int) -> bool:
    """将用户加入指定群的黑名单，返回是否为新添加"""
    _load_blacklist()
    if group_id not in _blacklist:
        _blacklist[group_id] = set()
    if user_id in _blacklist[group_id]:
        return False
    _blacklist[group_id].add(user_id)
    _save_blacklist()
    logger.info(f"[黑名单] 已添加: 群 {group_id} 的用户 {user_id}")
    return True


def remove_from_blacklist(group_id: int, user_id: int) -> bool:
    """将用户从指定群的黑名单移除，返回是否成功移除"""
    _load_blacklist()
    if group_id not in _blacklist or user_id not in _blacklist[group_id]:
        return False
    _blacklist[group_id].remove(user_id)
    if not _blacklist[group_id]:
        del _blacklist[group_id]
    _save_blacklist()
    logger.info(f"[黑名单] 已移除: 群 {group_id} 的用户 {user_id}")
    return True


def is_blacklisted(group_id: int, user_id: int) -> bool:
    """检查用户是否在指定群的黑名单中"""
    _load_blacklist()
    return user_id in _blacklist.get(group_id, set())


# 启动时预加载
_load_blacklist()
