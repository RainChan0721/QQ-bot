# AGENTS.md — 供 AI 与开发者阅读的项目说明

## 项目定位

RCBot 是一个极简的 NoneBot2 插件项目，核心目标只有一个：**接收 NapCat 上报的加群请求，并在群内提供命令式审核能力**。

## 技术栈

- **框架**: NoneBot2 (v2.5.0+) + FastAPI 驱动（提供 WebSocket 服务端）
- **协议适配器**: nonebot-adapter-onebot (OneBot V11)
- **协议端**: NapCat（通过反向 WebSocket 连接到 NoneBot，支持 Docker 部署）
- **包管理**: uv + PEP 518 (`pyproject.toml`)
- **存储**: 纯内存 `dict`（key: `"{group_id}:{user_id}"`）

## 核心架构

### 数据流

1. NapCat 检测到加群请求 → 通过反向 WS 发送 `request.group.add` 事件到 NoneBot
2. `group_add_request` (on_request) 触发：
   - 调用 OneBot API `get_stranger_info` 获取昵称与等级
   - 将请求（含 `flag`）写入 `rcbot.store._pending`
   - 调用 `send_group_msg` 在对应群发送 3 行格式通知
3. 群管理员发送 `/<trigger> group accept|reject <QQ号>`（trigger 由 `.env` 的 `RCBOT_TRIGGER` 配置，默认 `RCBOT`）
4. `rcbot_cmd` (on_command) 触发：
   - 权限检查（群主 / 管理员 / SUPERUSER）
   - 从内存中取出 `flag`
   - 调用 `set_group_add_request` 完成审核
   - 从内存移除该请求

### 为什么用内存存储？

项目定位为轻量级本地 bot，审核操作通常发生在请求上报后的几分钟内，且重启频率低。若后续需要持久化，建议在 `rcbot/store.py` 中引入 `aiosqlite` 或 `sqlalchemy`，保持接口不变即可。

## 关键代码文件

| 文件 | 职责 |
|------|------|
| `bot.py` | 注册 Adapter、加载插件、启动服务 |
| `rcbot/store.py` | `GroupJoinRequest` 数据模型与内存 CRUD |
| `rcbot/plugins/group_manager/handler.py` | 事件监听 + 命令解析 + API 调用 + 群白名单校验 |
| `.env` | 运行时配置（HOST/PORT/SUPERUSERS/LOG_LEVEL/ALLOWED_GROUP_IDS） |

## 扩展指南

### 添加新的存储后端

修改 `rcbot/store.py`，保持以下函数签名不变：
- `add_request(req: GroupJoinRequest) -> None`
- `get_request(group_id: int, user_id: int) -> Optional[GroupJoinRequest]`
- `remove_request(group_id: int, user_id: int) -> Optional[GroupJoinRequest]`

### 修改通知格式

编辑 `handler.py` 中 `handle_group_request` 里的 `notice` 字符串变量即可。

### 添加更多命令

在 `handler.py` 中：
1. 定义新的 `on_command` 或 `on_regex` matcher
2. 使用 `CommandArg()` 提取参数
3. 调用 `bot.set_group_add_request` 或其他 OneBot API

## 常见陷阱

- **权限问题**: 如果机器人不是群管理员，`set_group_add_request` 会失败，但 NapCat/OneBot 通常不会返回明确错误。务必确保机器人有管理权限。
- **flag 失效**: OneBot 的 `flag` 有过期时间（通常很短），如果长时间不处理，accept/reject 会失效。建议收到请求后尽快处理。
- **多群冲突**: `flag` 在不同群之间理论上不会冲突，但存储 key 使用 `group_id:user_id` 组合，确保同一用户在不同群的请求互不影响。
- **群白名单**: 通过环境变量 `ALLOWED_GROUP_IDS` 限制 bot 只在指定群工作。若 bot 在大量群中存在，建议配置白名单以避免无关群的消息干扰。
- **Docker 网络**: 若 NapCat 跑在 Docker 容器内而 Bot 跑在宿主机，容器内 `127.0.0.1` 指向容器自身。NapCat 的反向 WS URL 应使用宿主机局域网 IP 或 `host.docker.internal`，并确保 Bot 监听 `0.0.0.0`。

## 测试建议

### 1. 独立测试脚本（无需 NoneBot 运行）

```bash
uv run python tests/test_mock.py
```

脚本覆盖：
- `store.py` 的 CRUD
- `parse_rcbot_command()` 命令解析
- `_is_allowed_group()` 白名单逻辑
- `handle_group_request()` 全流程 Mock（使用 `AsyncMock` 替代真实 Bot API）

### 2. TEST_MODE 自动模拟

在 `.env` 中设置 `TEST_MODE=true`（可选配 `TEST_GROUP_ID` 指定测试目标群），Bot 会在 **首个 OneBot 连接建立后** 自动构造并处理一条模拟的 `GroupRequestEvent`，日志会打印完整数据流诊断：

```
========== [TEST] 测试模式触发 ==========
[TEST] 模拟事件构造完成: group=123456789, user=987654321
[事件] 收到 request 事件: request_type=group, sub_type=add, ...
[存储] 新的进群请求已写入: ...
[TEST] ✅ 存储验证通过: GroupJoinRequest(...)
[TEST] ✅ send_group_msg 已被调用
========== [TEST] 测试模式结束 ==========
```

### 3. 手动单元测试示例

```python
from nonebot.adapters.onebot.v11 import GroupRequestEvent

event = GroupRequestEvent(
    time=1234567890,
    self_id=123456,
    post_type="request",
    request_type="group",
    sub_type="add",
    group_id=123456789,
    user_id=987654321,
    comment="测试",
    flag="test_flag_001"
)
```
