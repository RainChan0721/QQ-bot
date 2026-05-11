"""
ChatAI 插件

功能：
1. 在群聊中被 @ 时触发 AI 对话
2. 支持读取被引用的消息作为上下文
3. 按群号持久化对话记忆
4. 回复时引用用户原消息

配置项（.env）：
- CHAT_AI_ENABLED: true/false
- CHAT_AI_API_KEY: OpenAI 格式 API 密钥
- CHAT_AI_BASE_URL: API 基础地址（可选）
- CHAT_AI_MODEL: 模型名称（默认 gpt-4o-mini）
- CHAT_AI_MAX_CONTEXT: 最大记忆轮数（默认 10）

Prompt 文件（从文件读取，支持按群自定义）：
- prompts/default.txt          默认系统提示词
- prompts/<group_id>.txt       指定群的自定义提示词（可选）
"""

from pathlib import Path

from nonebot import on_message, get_driver
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment
from nonebot.rule import to_me
from nonebot.log import logger
from openai import AsyncOpenAI

from .memory import load_memory, save_memory

# ========== Prompt 加载 ==========
_PROMPT_DIR = Path("prompts")
_DEFAULT_PROMPT_PATH = _PROMPT_DIR / "default.txt"


def _load_prompt(group_id: int) -> str:
    """加载系统提示词，优先读取群专属文件，其次 default.txt，最后内置默认"""
    group_path = _PROMPT_DIR / f"{group_id}.txt"
    for path in (group_path, _DEFAULT_PROMPT_PATH):
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    logger.debug(f"[ChatAI] 加载 prompt 文件: {path}")
                    return text
            except Exception as e:
                logger.warning(f"[ChatAI] 读取 prompt 文件失败 {path}: {e}")
    return "你是一个有帮助的QQ群助手，回答简洁友好。"


# ========== 配置加载 ==========
_driver = get_driver()
_config = _driver.config

ENABLED = getattr(_config, "chat_ai_enabled", False)
API_KEY = getattr(_config, "chat_ai_api_key", "")
BASE_URL = getattr(_config, "chat_ai_base_url", "https://api.openai.com/v1")
MODEL = getattr(_config, "chat_ai_model", "gpt-4o-mini")
MAX_CONTEXT = getattr(_config, "chat_ai_max_context", 10)

# TEST_MODE 限群（与 group_manager 保持一致）
TEST_MODE = getattr(_config, "test_mode", False)
_TEST_GROUP_ID: int | None = getattr(_config, "test_group_id", None)

client: AsyncOpenAI | None = None
if ENABLED:
    if API_KEY:
        client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)
        logger.info(f"[ChatAI] 已启用 | 模型: {MODEL} | 最大记忆: {MAX_CONTEXT} 轮")
        if TEST_MODE and _TEST_GROUP_ID:
            logger.info(f"[ChatAI] TEST_MODE 限群: 仅 {_TEST_GROUP_ID}")
    else:
        logger.warning("[ChatAI] 功能已启用但未配置 CHAT_AI_API_KEY，无法使用")

# 只响应群聊中 @Bot 的消息（to_me）
chat_matcher = on_message(rule=to_me(), priority=10, block=False)


@chat_matcher.handle()
async def handle_chat(bot: Bot, event: GroupMessageEvent):
    """处理被 @ 的群聊消息"""
    if not ENABLED or client is None:
        return

    group_id = event.group_id
    user_id = event.user_id

    # TEST_MODE 限群
    if TEST_MODE and _TEST_GROUP_ID is not None and group_id != _TEST_GROUP_ID:
        logger.debug(f"[ChatAI] TEST_MODE 限群: {group_id} != {_TEST_GROUP_ID}, 静默忽略")
        return

    user_msg = event.get_plaintext().strip()

    # 提取引用消息内容
    referenced_msg = ""
    for seg in event.message:
        if seg.type == "reply":
            try:
                msg_id = int(seg.data.get("id", 0))
                reply_data = await bot.get_msg(message_id=msg_id)
                raw_msg = reply_data.get("message", "")
                # 尝试提取纯文本
                if isinstance(raw_msg, list):
                    referenced_msg = "".join(
                        m.get("data", {}).get("text", "")
                        for m in raw_msg
                        if m.get("type") == "text"
                    )
                elif isinstance(raw_msg, str):
                    referenced_msg = raw_msg
                else:
                    referenced_msg = str(raw_msg)
                logger.debug(f"[ChatAI] 提取到引用消息: {referenced_msg!r}")
            except Exception as e:
                logger.debug(f"[ChatAI] 获取引用消息失败: {e}")
            break

    # 构建当前输入
    if referenced_msg:
        current_content = f"用户引用了之前的消息「{referenced_msg}」，并接着说：{user_msg}"
    else:
        current_content = user_msg

    if not current_content.strip():
        logger.debug("[ChatAI] 消息为空，跳过")
        return

    # 加载记忆与 prompt（按 user_id 隔离）
    memory = load_memory(group_id, user_id, MAX_CONTEXT)
    system_prompt = _load_prompt(group_id)
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(memory)
    messages.append({"role": "user", "content": current_content})

    logger.info(f"[ChatAI] 群 {group_id} 用户 {user_id} 调用 AI | 上下文轮数: {len(memory)//2} | 消息: {current_content[:50]}...")

    try:
        resp = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
        )
        reply = resp.choices[0].message.content
        if not reply:
            reply = "（AI 返回空内容）"
    except Exception as e:
        logger.error(f"[ChatAI] API 调用失败: {e}")
        await chat_matcher.finish("AI 暂时出错了，稍后再试吧~")
        return

    # 保存记忆（按 user_id 隔离）
    memory.append({"role": "user", "content": current_content})
    memory.append({"role": "assistant", "content": reply})
    save_memory(group_id, user_id, memory)

    # 发送回复并引用原消息
    logger.info(f"[ChatAI] 群 {group_id} 用户 {user_id} AI 回复: {reply[:80]}...")
    await bot.send_group_msg(
        group_id=group_id,
        message=MessageSegment.reply(event.message_id) + MessageSegment.text(reply),
    )
