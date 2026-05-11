# RCBot - QQ 进群审核机器人

基于 [NoneBot2](https://github.com/nonebot/nonebot2) 与 [NapCat](https://github.com/NapNeko/NapCatQQ) 的 QQ 群进群请求处理机器人。

## 功能简介

- **自动捕获进群请求**：通过 NapCat 的 WebSocket 反向代理实时接收加群事件。
- **格式化群内通知**：收到请求后在群内发送标准化消息（昵称/QQ号、等级、答案）。
- **命令审核**：支持在群内使用 `/RCBOT` 命令快速同意或拒绝进群申请。
- **群黑名单**：拒绝时可拉黑用户，黑名单用户再次申请会被自动静默拒绝。
- **群聊 AI 对话**：被 @ 时调用 OpenAI 格式 API 回复，支持引用消息与群记忆。
- **权限控制**：仅允许群主、群管理员与配置中的超级用户操作。

## 快速开始

### 1. 环境要求

- Python >= 3.14
- [uv](https://docs.astral.sh/uv/)（本地包管理器）
- [NapCat](https://napneko.github.io/)（QQ 协议端，提供 OneBot V11 反向 WS）

### 2. 安装与配置

```bash
# 克隆仓库
git clone <你的仓库地址>
cd rcbot

# 创建虚拟环境并安装依赖（已存在 .venv 时会自动复用）
uv sync

# 复制环境变量示例并编辑
cp .env.example .env
nano .env
```

编辑 `.env` 文件，至少修改以下项：

```env
# 超级用户 QQ 号（JSON 数组格式）
# ⚠️ QQ 号必须是带双引号的字符串，不能是纯数字！
SUPERUSERS=["123456789"]

# （可选）群白名单，只在指定群处理请求和命令；为空则允许所有群
ALLOWED_GROUP_IDS=["123456789","987654321"]

# 测试模式：设为 true 时，Bot 首次连接 NapCat 后会自动注入模拟进群请求
# 用于在没有真实群环境时快速验证逻辑和日志输出
TEST_MODE=false

# 测试模式目标群号（纯数字），测试通知只发到该群；不配置则使用默认群号
TEST_GROUP_ID=123456789
```

### 3. 启动机器人

```bash
uv run python bot.py
```

服务默认监听 `0.0.0.0:8080`。

### 4. 配置 NapCat

在 NapCat 配置中添加反向 WebSocket 连接：

```json
{
  "ws_reverse": {
    "enabled": true,
    "url": "ws://127.0.0.1:8080/onebot/v11/ws",
    "reconnect_interval": 3000
  }
}
```

> **若 NapCat 与 Bot 部署在不同机器**，请将 `127.0.0.1` 替换为 Bot 所在服务器的实际 IP。

#### NapCat 使用 Docker 部署时的网络说明

如果 NapCat 跑在 Docker 容器内，而本 Bot 跑在宿主机本地，容器无法通过 `127.0.0.1` 访问宿主机。请按以下方式配置：

**方式一：使用宿主机局域网 IP（推荐，最稳定）**

将 NapCat 的反向 WS URL 改为宿主机的局域网 IP，例如：
```
ws://192.168.1.100:8080/onebot/v11/ws
```
确保 Bot 的 `.env` 中 `HOST=0.0.0.0`（已默认配置），这样容器才能访问到宿主机端口。

**方式二：使用 `host.docker.internal`（Docker Desktop / Mac / Windows）**
```
ws://host.docker.internal:8080/onebot/v11/ws
```
> Linux 原生 Docker 需要额外配置 `host.docker.internal` 支持，或在启动容器时添加 `--add-host=host.docker.internal:host-gateway`。

**方式三：Docker `--network host`（Linux  only）**
启动 NapCat 容器时使用 host 网络模式，容器与宿主机共享网络栈，此时可直接使用 `ws://127.0.0.1:8080/onebot/v11/ws`。

## 使用说明

当有人申请加群时，机器人会在该群内自动发送如下格式的消息：

```
用户昵称(123456789)
等级: 32
答案: 我是从github来的
```

管理员可使用以下命令处理（`RCBOT` 可在 `.env` 中通过 `RCBOT_TRIGGER` 自定义，只能是英文）：

| 命令 | 说明 |
|------|------|
| `/<trigger> group accept <QQ号>` | 同意该用户的进群请求 |
| `/<trigger> group reject <QQ号> [理由] [true]` | 拒绝该用户的进群请求；末尾加 `true` 可拉黑 |
| `/<trigger> 同意 <QQ号>` | 快捷同意 |
| `/<trigger> 拒绝 <QQ号> [理由] [true]` | 快捷拒绝；末尾加 `true` 可拉黑 |

### 群聊 AI 对话（可选）

在 `.env` 中开启并配置 `CHAT_AI_ENABLED=true` 后，在群里 **@Bot** 即可触发 AI 对话：

- 支持**引用消息**（回复某条消息时 @Bot，AI 会读取被引用的内容）
- 支持**群记忆**（按群号保存最近 N 轮对话上下文，持久化在 `data/chat_memory/`）
- AI 回复时会**引用你的原消息**

配置示例：
```env
CHAT_AI_ENABLED=true
CHAT_AI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
CHAT_AI_BASE_URL=https://api.openai.com/v1
CHAT_AI_MODEL=gpt-4o-mini
CHAT_AI_MAX_CONTEXT=10
```

**自定义 Prompt**：
在 `prompts/` 目录下创建文本文件即可设定 AI 人格：
- `prompts/default.txt` — 所有群的默认提示词
- `prompts/123456789.txt` — 仅对群 `123456789` 生效的专属提示词

所有 `.txt` 文件已加入 `.gitignore`，不会上传到仓库。

## 项目结构

```
.
├── bot.py                          # 程序入口
├── pyproject.toml                  # uv 项目配置与依赖
├── .env.example                    # 环境变量模板
├── .env                            # 本地环境变量（不上传）
├── README.md                       # 本文档
├── AGENTS.md                       # 供 AI / 开发者阅读的架构说明
├── rcbot/                          # 主包
│   ├── store.py                    # 内存存储（待处理请求 + 黑名单 JSON）
│   └── plugins/
│       ├── group_manager/          # 进群管理插件
│       │   ├── __init__.py
│       │   └── handler.py          # 事件与命令处理逻辑
│       └── chat_ai/                # 群聊 AI 对话插件
│           ├── __init__.py
│           ├── handler.py          # AI 调用与消息处理
│           └── memory.py           # 群记忆持久化
├── prompts/                        # AI 提示词文件（.txt 不上传，.example 为模板）
├── data/                           # 本地运行时数据（聊天记忆等，不上传）
├── tests/
│   └── test_mock.py                # 独立测试脚本
└── .venv/                          # uv 虚拟环境（不上传）
```

## 本地测试（无需 NapCat）

项目内置了独立测试脚本，可在不连接 NapCat 的情况下验证核心逻辑：

```bash
uv run python tests/test_mock.py
```

测试覆盖内容：
- 内存存储的增删改查
- `/RCBOT` 命令解析
- 群白名单校验
- Handler 全流程 Mock（模拟 Bot API + Event）

此外，开启 `TEST_MODE=true` 后，当 NapCat 首次连接时，Bot 会自动注入一条模拟进群请求，方便在真实环境中观察日志输出。配合 `TEST_GROUP_ID` 可限定测试通知只发到指定群，避免打扰其他群：

```env
TEST_MODE=true
TEST_GROUP_ID=123456789
```

## 注意事项

- **群白名单**：通过 `ALLOWED_GROUP_IDS` 配置可限定 bot 只在指定群聊工作，避免在无关群中响应命令或泄露审核信息。未配置则允许所有群。
- 所有待处理请求仅保存在**内存**中，重启机器人后数据会丢失。若需持久化，请自行接入数据库（如 SQLite）。
- 确保机器人账号在群内有**审核进群请求**的权限（通常为管理员或群主）。

## 开源协议

MIT
