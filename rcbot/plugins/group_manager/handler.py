"""
进群请求处理插件

功能：
1. 监听 NapCat 上报的加群请求事件
2. 在对应群内发送格式化通知
3. 提供 /<trigger> group accept/reject 命令处理请求（trigger 可配置）
4. 提供 /<trigger> 同意/拒绝 快捷命令
5. 群黑名单自动拦截与手动添加

消息格式（共3行）：
第一行：进群用户昵称(QQ号)
第二行：等级: 用户等级
第三行：答案: 用户填入的答案
"""

import json

from nonebot import on_request, on_command, get_driver
from nonebot.adapters.onebot.v11 import Bot, GroupRequestEvent, GroupMessageEvent, Message
from nonebot.params import CommandArg
from nonebot.log import logger

from rcbot.store import (
    GroupJoinRequest,
    add_request,
    get_request,
    remove_request,
    is_blacklisted,
    add_to_blacklist,
    remove_from_blacklist,
)

# ========== 配置加载 ==========
# 统一通过 NoneBot driver.config 读取 .env，避免 os.getenv 读不到的问题

_driver = get_driver()
_config = _driver.config

TEST_MODE = getattr(_config, "test_mode", False)
_TEST_GROUP_ID: int | None = getattr(_config, "test_group_id", None)

if TEST_MODE:
    logger.info("========== TEST_MODE 已启用 ==========")
    if _TEST_GROUP_ID:
        logger.info(f"[TEST] 测试目标群: {_TEST_GROUP_ID}")
    else:
        logger.info("[TEST] 测试目标群: 未配置，将使用默认群号 123456789")

# 群白名单：仅在指定群聊内响应（空或不配置则允许所有群）
_ALLOWED_GROUP_IDS: set[int] = set()
_allowed_raw = getattr(_config, "allowed_group_ids", [])
if _allowed_raw:
    try:
        if isinstance(_allowed_raw, str):
            _allowed_raw = json.loads(_allowed_raw)
        _ALLOWED_GROUP_IDS = {int(gid) for gid in _allowed_raw}
        logger.info(f"群白名单已加载: {_ALLOWED_GROUP_IDS}")
    except Exception:
        logger.warning(f"ALLOWED_GROUP_IDS 解析失败: {_allowed_raw}，将允许所有群")
else:
    logger.info("群白名单未配置，允许所有群")


def _is_allowed_group(group_id: int) -> bool:
    """检查群号是否允许响应

    逻辑：
    - TEST_MODE=true 且 TEST_GROUP_ID 已配置时，只允许 TEST_GROUP_ID
    - 否则按 ALLOWED_GROUP_IDS 白名单判断（未配置则允许所有群）
    """
    if TEST_MODE and _TEST_GROUP_ID is not None:
        result = group_id == _TEST_GROUP_ID
        if not result:
            logger.debug(f"[白名单] TEST_MODE 限群: {group_id} != {_TEST_GROUP_ID}, 静默忽略")
        return result
    result = not _ALLOWED_GROUP_IDS or group_id in _ALLOWED_GROUP_IDS
    logger.debug(f"[白名单] group_id={group_id}, allowed_groups={_ALLOWED_GROUP_IDS or 'ALL'}, result={result}")
    return result


def parse_rcbot_command(text: str):
    """解析进群管理命令参数

    支持格式（trigger 由 RCBOT_TRIGGER 配置，默认 RCBOT）：
      /<trigger> group accept <QQ号>
      /<trigger> group reject <QQ号> [理由] [true]
      /<trigger> 同意 <QQ号>
      /<trigger> 拒绝 <QQ号> [理由] [true]

    返回: (action, target_qq, reason, blacklist)
    action: "accept" | "reject" | None
    target_qq: int | None
    reason: str
    blacklist: bool
    """
    parts = text.strip().split()
    logger.debug(f"[命令解析] 分割结果: {parts}")

    if not parts:
        logger.debug("[命令解析] 空参数")
        return None, None, "拒绝进群", False

    cmd = parts[0]

    # ===== 旧格式: group accept/reject/get =====
    if cmd == "group":
        if len(parts) < 2:
            logger.debug("[命令解析] group 格式参数不足")
            return None, None, "拒绝进群", False

        action = parts[1]

        # group get 不需要 QQ 号
        if action == "get":
            logger.debug("[命令解析] action=get")
            return "get", None, "拒绝进群", False

        if len(parts) < 3:
            logger.debug("[命令解析] group 格式参数不足")
            return None, None, "拒绝进群", False

        try:
            target_qq = int(parts[2])
        except ValueError:
            logger.debug(f"[命令解析] QQ号格式错误: {parts[2]}")
            return None, None, "拒绝进群", False

        if action not in ("accept", "reject"):
            logger.debug(f"[命令解析] 未知 action: {action}")
            return None, None, "拒绝进群", False

        # 检查最后是否是 true（不区分大小写）
        if len(parts) > 3 and parts[-1].lower() == "true":
            blacklist = True
            reason = " ".join(parts[3:-1]) if len(parts) > 4 else "拒绝进群"
        else:
            blacklist = False
            reason = " ".join(parts[3:]) if len(parts) > 3 else "拒绝进群"

        logger.debug(f"[命令解析] action={action}, target={target_qq}, reason={reason}, blacklist={blacklist}")
        return action, target_qq, reason, blacklist

    # ===== 快捷格式: 同意 =====
    if cmd == "同意":
        if len(parts) < 2:
            logger.debug("[命令解析] 同意 缺少 QQ号")
            return None, None, "拒绝进群", False
        try:
            target_qq = int(parts[1])
        except ValueError:
            logger.debug(f"[命令解析] QQ号格式错误: {parts[1]}")
            return None, None, "拒绝进群", False
        logger.debug(f"[命令解析] action=accept, target={target_qq}")
        return "accept", target_qq, "拒绝进群", False

    # ===== 快捷格式: 拒绝 =====
    if cmd == "拒绝":
        if len(parts) < 2:
            logger.debug("[命令解析] 拒绝 缺少 QQ号")
            return None, None, "拒绝进群", False
        try:
            target_qq = int(parts[1])
        except ValueError:
            logger.debug(f"[命令解析] QQ号格式错误: {parts[1]}")
            return None, None, "拒绝进群", False

        if len(parts) > 2 and parts[-1].lower() == "true":
            blacklist = True
            reason = " ".join(parts[2:-1]) if len(parts) > 3 else "拒绝进群"
        else:
            blacklist = False
            reason = " ".join(parts[2:]) if len(parts) > 2 else "拒绝进群"

        logger.debug(f"[命令解析] action=reject, target={target_qq}, reason={reason}, blacklist={blacklist}")
        return "reject", target_qq, reason, blacklist

    logger.debug(f"[命令解析] 未知命令前缀: {cmd}")
    return None, None, "拒绝进群", False


# ========== 事件处理器 ==========

# 监听群请求事件
group_add_request = on_request(priority=5)


@group_add_request.handle()
async def handle_group_request(bot: Bot, event: GroupRequestEvent):
    """处理进群请求事件"""
    logger.debug(
        f"[事件] 收到 request 事件: "
        f"request_type={event.request_type}, sub_type={event.sub_type}, "
        f"group_id={event.group_id}, user_id={event.user_id}, "
        f"flag={event.flag}, comment={event.comment!r}"
    )

    # 只处理主动加群（sub_type="add"），忽略邀请（invite）
    if event.request_type != "group" or event.sub_type != "add":
        logger.debug(f"[事件] 类型不匹配，跳过: request_type={event.request_type}, sub_type={event.sub_type}")
        return

    group_id = event.group_id
    if not _is_allowed_group(group_id):
        logger.info(f"[事件] 群 {group_id} 不在白名单内，忽略进群请求")
        return

    user_id = event.user_id
    comment = event.comment or "无"
    flag = event.flag

    # 黑名单自动拦截
    if is_blacklisted(group_id, user_id):
        logger.info(f"[黑名单] 用户 {user_id} 在群 {group_id} 黑名单中，自动拒绝")
        try:
            await bot.set_group_add_request(
                flag=flag, sub_type="add", approve=False, reason="你已被该群拉黑"
            )
        except Exception as e:
            logger.error(f"[API] 自动拒绝黑名单用户失败: {e}")
        # 不在群内发通知，静默处理
        return

    # 尝试获取用户昵称与等级
    nickname = str(user_id)
    level = 0
    try:
        logger.debug(f"[API] 调用 get_stranger_info: user_id={user_id}")
        info = await bot.get_stranger_info(user_id=user_id)
        logger.debug(f"[API] get_stranger_info 原始返回: {info}")
        nickname = info.get("nickname") or nickname
        # OneBot V11 标准没有 level 字段，各实现可能用 level / qage / age 或不返回
        level = info.get("level") or info.get("qage") or info.get("age") or 0
        if level:
            logger.debug(f"[API] 获取到用户等级/年龄: {level}")
        else:
            logger.debug("[API] 该协议端未返回等级信息")
    except Exception as e:
        logger.warning(f"[API] 获取用户 {user_id} 陌生人信息失败: {e}")

    # 存入内存
    req = GroupJoinRequest(
        group_id=group_id,
        user_id=user_id,
        flag=flag,
        comment=comment,
        nickname=nickname,
        level=level,
    )
    add_request(req)
    logger.info(f"[存储] 新的进群请求已写入: {nickname}({user_id}) -> 群 {group_id}, flag={flag}")

    # 在群内发送通知（严格3行格式）
    level_display = level if level else "未知"
    notice = (
        f"{nickname}({user_id})\n"
        f"等级: {level_display}\n"
        f"答案: {comment}"
    )
    logger.debug(f"[消息] 准备发送群通知到 group_id={group_id}:\n{notice}")
    try:
        await bot.send_group_msg(group_id=group_id, message=notice)
        logger.info(f"[消息] 群通知已发送: group_id={group_id}")
    except Exception as e:
        logger.error(f"[消息] 发送群通知失败: group_id={group_id}, error={e}")


# 进群管理命令 trigger（从 .env 读取，只能是英文）
_TRIGGER = getattr(_config, "rcbot_trigger", "RCBOT")
logger.info(f"[配置] 进群管理命令 trigger: {_TRIGGER}")

# ChatAI 开关状态，用于动态拼接帮助文本
_CHAT_AI_ENABLED = getattr(_config, "chat_ai_enabled", False)

# 注册命令 matcher（支持配置的大小写 + 全小写别名）
rcbot_cmd = on_command(_TRIGGER, aliases={_TRIGGER.lower()}, priority=5)


async def _check_permission(bot: Bot, event: GroupMessageEvent) -> bool:
    """检查用户是否有权限处理进群请求（群主/管理员/SUPERUSER）"""
    user_id = event.user_id
    group_id = event.group_id
    logger.debug(f"[权限] 检查用户 {user_id} 在群 {group_id} 的权限")

    superusers = bot.config.superusers
    logger.debug(f"[权限] 当前 SUPERUSERS: {superusers}")
    if str(user_id) in superusers:
        logger.info(f"[权限] 用户 {user_id} 是 SUPERUSER，放行")
        return True

    try:
        logger.debug(f"[API] 调用 get_group_member_info: group_id={group_id}, user_id={user_id}")
        member = await bot.get_group_member_info(group_id=group_id, user_id=user_id)
        role = member.get("role", "member")
        logger.debug(f"[API] get_group_member_info 返回: role={role}")
        if role in ("owner", "admin"):
            logger.info(f"[权限] 用户 {user_id} 是群 {group_id} 的 {role}，放行")
            return True
    except Exception as e:
        logger.warning(f"[API] 获取群成员信息失败: {e}")

    logger.info(f"[权限] 用户 {user_id} 无权限")
    return False


@rcbot_cmd.handle()
async def handle_rcbot(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    """处理进群管理命令"""
    group_id = event.group_id
    user_id = event.user_id
    raw_text = event.raw_message or ""
    logger.debug(f"[命令] 收到消息命令: user_id={user_id}, group_id={group_id}, raw={raw_text!r}")

    if not _is_allowed_group(group_id):
        logger.debug(f"[命令] 群 {group_id} 不在白名单内，静默忽略")
        return

    if not await _check_permission(bot, event):
        await rcbot_cmd.finish("权限不足：仅群主、管理员或超级用户可操作")
        return

    text = args.extract_plain_text().strip()
    logger.debug(f"[命令] 提取参数: {text!r}")

    action, target_qq, reason, blacklist = parse_rcbot_command(text)
    if action is None:
        logger.info("[命令] 参数解析失败，返回用法提示")
        help_text = (
            f"用法:\n"
            f"/{_TRIGGER} group get — 查看本群待处理请求\n"
            f"/{_TRIGGER} group accept [QQ号] — 同意进群\n"
            f"/{_TRIGGER} group reject [QQ号] [理由] [true] — 拒绝进群\n"
            f"/{_TRIGGER} 同意 [QQ号] — 同意进群（快捷版）\n"
            f"/{_TRIGGER} 拒绝 [QQ号] [理由] [true] — 拒绝进群（快捷版）\n"
            f"提示: 末尾加 true 可将用户加入群黑名单"
        )
        if _CHAT_AI_ENABLED:
            help_text += "\n@Bot [内容] AI聊天"
        await rcbot_cmd.finish(help_text)
        return

    # group get: 列出当前群所有待处理请求
    if action == "get":
        pending = list_requests(group_id)
        if not pending:
            await rcbot_cmd.finish("当前没有待处理的进群请求")
            return
        lines = [f"📋 群 {group_id} 待处理进群请求（共 {len(pending)} 条）:"]
        for idx, req in enumerate(pending, 1):
            lines.append(
                f"\n[{idx}] {req.nickname}({req.user_id})\n"
                f"    等级: {req.level if req.level else '未知'}\n"
                f"    答案: {req.comment}"
            )
        lines.append(f"\n使用 /{_TRIGGER} group accept <QQ号> 或 /{_TRIGGER} group reject <QQ号> [理由] 处理")
        await rcbot_cmd.finish("\n".join(lines))
        return

    req = get_request(group_id, target_qq)
    if req:
        logger.debug(f"[存储] 查询到待处理请求: {req}")
    else:
        logger.info(f"[存储] 未找到 {group_id}:{target_qq} 的待处理请求")
        await rcbot_cmd.finish(f"未找到 {target_qq} 的待处理进群请求")
        return

    _is_test_flag = TEST_MODE and req.flag.startswith("test_flag")

    if action == "accept":
        logger.info(f"[审核] 准备同意: group_id={group_id}, user_id={target_qq}, flag={req.flag}")
        try:
            if _is_test_flag:
                logger.warning("[审核] ⚠️ TEST_MODE 检测到测试 flag，跳过真实 set_group_add_request")
            else:
                logger.debug(f"[API] 调用 set_group_add_request: flag={req.flag}, approve=True")
                await bot.set_group_add_request(
                    flag=req.flag, sub_type="add", approve=True
                )
            remove_request(group_id, target_qq)
            logger.info(f"[审核] 已同意 {req.nickname}({target_qq}) 的进群请求")
        except Exception as e:
            logger.error(f"[API] 同意进群请求失败: {e}")
            await rcbot_cmd.finish(f"操作失败: {e}")
            return
        await rcbot_cmd.finish(f"已同意 {req.nickname}({target_qq}) 的进群请求")

    elif action == "reject":
        logger.info(f"[审核] 准备拒绝: group_id={group_id}, user_id={target_qq}, flag={req.flag}, reason={reason!r}, blacklist={blacklist}")
        try:
            if _is_test_flag:
                logger.warning("[审核] ⚠️ TEST_MODE 检测到测试 flag，跳过真实 set_group_add_request")
            else:
                logger.debug(f"[API] 调用 set_group_add_request: flag={req.flag}, approve=False, reason={reason!r}")
                await bot.set_group_add_request(
                    flag=req.flag, sub_type="add", approve=False, reason=reason
                )
            remove_request(group_id, target_qq)
            logger.info(f"[审核] 已拒绝 {req.nickname}({target_qq}) 的进群请求，理由: {reason}")
        except Exception as e:
            logger.error(f"[API] 拒绝进群请求失败: {e}")
            await rcbot_cmd.finish(f"操作失败: {e}")
            return

        # 处理黑名单
        if blacklist:
            if add_to_blacklist(group_id, target_qq):
                blacklist_msg = f"\n⚠️ 已将该用户加入群 {group_id} 黑名单"
            else:
                blacklist_msg = f"\nℹ️ 该用户已在群 {group_id} 黑名单中"
            logger.info(f"[黑名单] 拒绝时添加黑名单: group={group_id}, user={target_qq}, result={blacklist_msg.strip()}")
        else:
            blacklist_msg = ""

        await rcbot_cmd.finish(
            f"已拒绝 {req.nickname}({target_qq}) 的进群请求\n理由: {reason}{blacklist_msg}"
        )

    else:
        logger.info(f"[命令] 未知 action: {action}")
        help_text = (
            f"用法:\n"
            f"/{_TRIGGER} group get — 查看本群待处理请求\n"
            f"/{_TRIGGER} group accept [QQ号] — 同意进群\n"
            f"/{_TRIGGER} group reject [QQ号] [理由] [true] — 拒绝进群\n"
            f"/{_TRIGGER} 同意 [QQ号] — 同意进群（快捷版）\n"
            f"/{_TRIGGER} 拒绝 [QQ号] [理由] [true] — 拒绝进群（快捷版）\n"
            f"提示: 末尾加 true 可将用户加入群黑名单"
        )
        if _CHAT_AI_ENABLED:
            help_text += "\n@Bot [内容] AI聊天"
        await rcbot_cmd.finish(help_text)


# ========== 测试模式 ==========

if TEST_MODE:
    @_driver.on_bot_connect
    async def _test_on_connect(bot: Bot):
        """测试模式：Bot 连接后自动注入模拟进群请求"""
        logger.info("========== [TEST] 测试模式触发 ==========")
        logger.info(f"[TEST] 当前 Bot ID: {bot.self_id}")
        logger.info(f"[TEST] 白名单设置: {_ALLOWED_GROUP_IDS or '未配置(允许所有)'}")

        test_group = _TEST_GROUP_ID if _TEST_GROUP_ID else 123456789
        test_user = 987654321
        test_flag = "test_flag_auto_001"
        test_comment = "【测试模式】模拟的进群申请答案"

        logger.info(f"[TEST] 构造模拟事件: group={test_group}, user={test_user}")
        event = GroupRequestEvent(
            time=1234567890,
            self_id=int(bot.self_id),
            post_type="request",
            request_type="group",
            sub_type="add",
            group_id=test_group,
            user_id=test_user,
            comment=test_comment,
            flag=test_flag,
        )
        logger.info(f"[TEST] 事件字段: request_type={event.request_type}, sub_type={event.sub_type}")

        if _ALLOWED_GROUP_IDS and test_group not in _ALLOWED_GROUP_IDS:
            logger.warning(f"[TEST] 测试群 {test_group} 不在白名单中，临时加入以完成测试")
            _ALLOWED_GROUP_IDS.add(test_group)

        logger.info("[TEST] 开始调用 handle_group_request...")
        await handle_group_request(bot, event)

        req = get_request(test_group, test_user)
        if req:
            logger.info(f"[TEST] ✅ 存储验证通过: {req}")
        else:
            logger.error("[TEST] ❌ 存储验证失败: 请求未写入内存")

        if hasattr(bot.get_stranger_info, "called"):
            if bot.get_stranger_info.called:
                logger.info("[TEST] ✅ get_stranger_info 已被调用")
            else:
                logger.warning("[TEST] ⚠️ get_stranger_info 未被调用")
        else:
            logger.info("[TEST] ℹ️ get_stranger_info 已在真实环境中调用（日志由 NoneBot 打印）")

        if hasattr(bot.send_group_msg, "called"):
            if bot.send_group_msg.called:
                logger.info("[TEST] ✅ send_group_msg 已被调用")
                logger.info(f"[TEST] send_group_msg 参数: {bot.send_group_msg.call_args}")
            else:
                logger.warning("[TEST] ⚠️ send_group_msg 未被调用")
        else:
            logger.info("[TEST] ℹ️ send_group_msg 已在真实环境中调用（日志由 NoneBot 打印）")

        logger.warning("[TEST] 注意: 测试模式使用虚拟 flag，属于预期行为")
        logger.info("========== [TEST] 测试模式结束 ==========")
