<h1 align="center">hermes-lark-streaming</h1>

<p align="center">
  <img src="https://img.shields.io/badge/项目-Vibe%20Coding-ff69b4" alt="Vibe Coding">
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-4caf50.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.11+-3776AB.svg" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/version-1.2.0-ff9800.svg" alt="Version">
</p>

<p align="center">
<a href="https://github.com/blackrion"><img src="https://img.shields.io/badge/GitHub-blackrion-181717?logo=github&logoColor=white" alt="GitHub"></a>
</p>

<p align="center">
<a href="README.md">English</a> | 中文版
</p>

为 Hermes Agent 提供飞书/Lark CardKit v2.0 流式消息卡片插件 — 实时 AI 响应展示，支持打字机效果、统一可折叠面板、交互式审批与澄清卡片等。

> 基于 [Aowen-Nowor/hermes-lark-streaming](https://github.com/Aowen-Nowor/hermes-lark-streaming) v1.1.3（最初 fork 自 [Cheerwhy/hermes-lark-streaming](https://github.com/Cheerwhy/hermes-lark-streaming) v0.7.0），从 [larksuite/openclaw-lark](https://github.com/larksuite/openclaw-lark)（MIT, ByteDance）移植了多项特性，并参考了 [baileyh8/hermes-feishu-streaming-card](https://github.com/baileyh8/hermes-feishu-streaming-card) 的设计。
>
> 📝 **个人 fork** — 由 [blackrion](https://github.com/blackrion) 维护，仅供自用。保留所有上游 MIT 协议条款。

---

## 功能特性

### 流式回复卡片

- **实时打字机效果** — 回答文本通过 CardKit `stream_element` API 逐字流入
- **统一可折叠面板** — 推理轮次和工具调用按时间线交错显示在单个面板中，保留真实发生顺序
- **状态化卡片头部** — 头部颜色和文本随状态变化：思考中（蓝色）、流式中（靛蓝）、已完成（绿色）、错误（红色）、授权（橙色）
- **两行页脚** — 第一行：状态 · 耗时 · 模型；第二行：Token · 缓存 · 上下文 · 费用

### 交互式审批卡片

当 Agent 尝试执行危险命令（如 `rm`、`git push --force`）时，自动发送交互式审批卡片：

- **命令预览** — 在代码块中展示完整命令（截断到 3000 字符）
- **四按钮审批** — ✅ 允许一次 · 🔁 本会话 · ⭐ 始终允许 · ❌ 拒绝
- **已决态** — 点击按钮后卡片更新为审批结果（已批准/已拒绝），显示操作者用户名
- 移植自 [openclaw-lark](https://github.com/larksuite/openclaw-lark) `buildConfirmCard()`（MIT, ByteDance）

### 交互式澄清卡片

当 Agent 使用 `clarify` 工具提问时，发送三态交互卡片：

- **待选择态** — 问题文本 + 选项列表 + 下拉选择框 + 文本输入框（500 字限制）
- **已提交态** — 软锁定，显示用户选择 + 重试按钮
- **已确认态** — 硬锁定，Hermes 处理完成后服务端更新为最终确认状态

### 网关消息卡片

所有非 AI 消息（斜杠命令、认证、错误、会话生命周期）自动转换为样式化的 CardKit 2.0 卡片，根据消息类别显示不同头部。

### 定时任务卡片

定时任务结果以样式化卡片投递，替代纯文本。

### 其他特性

- **Markdown 表格间距** — 标题、表格、代码块之间增加合理间距
- **工具参数脱敏** — 工具调用中的敏感 Header（`-H Authorization: ...`）、URL、文件路径在显示时自动脱敏
- **CardKit API 快速失败** — API 错误立即检测并记录，不再静默失败
- **缓存命中率** — 页脚显示 `cache_read/cache_write (命中率%)`，使用正确的计算公式
- **冲突刷新** — flush 控制器检测版本冲突并自动恢复
- **无效图片清理** — 渲染前清除损坏的图片引用

---

## 快速开始

### 前置要求

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) v0.17.0+（已运行，已配置飞书平台）
- Hermes CLI 支持插件系统（可用 `hermes plugins` 命令）

### 安装

```bash
# GitHub (SSH)
hermes plugins install git@github.com:blackrion/hermes-lark-streaming.git
# GitHub (HTTPS)
hermes plugins install https://github.com/blackrion/hermes-lark-streaming
```

提示时输入 `Y` 启用插件，然后重启网关：

```bash
hermes gateway restart
```

### 更新

```bash
hermes plugins update hermes-lark-streaming
hermes gateway restart
```

### 卸载

```bash
# 1. 先清理注入的配置（插件代码还在时执行）
HERMES_PYTHON=$(python3 ~/.hermes/plugins/hermes-lark-streaming/__main__.py python)
$HERMES_PYTHON ~/.hermes/plugins/hermes-lark-streaming/__main__.py cleanup

# 2. 卸载插件
hermes plugins uninstall hermes-lark-streaming

# 3. 重启网关
hermes gateway restart
```

### 验证安装

```bash
hermes plugins list
HERMES_PYTHON=$(python3 ~/.hermes/plugins/hermes-lark-streaming/__main__.py python)
$HERMES_PYTHON ~/.hermes/plugins/hermes-lark-streaming/__main__.py status
$HERMES_PYTHON ~/.hermes/plugins/hermes-lark-streaming/__main__.py doctor
```

---

## 配置说明

所有配置项位于 `~/.hermes/config.yaml` 的 `hermes_lark_streaming:` 节下。插件首次加载时自动注入默认配置。

```yaml
hermes_lark_streaming:
  enabled: true                # 启用流式卡片
  linear: true                 # 线性模式：单卡片原地更新（统一面板架构）
  panel_expanded: false        # 完成态卡片中面板是否保持展开
  streaming_panel_expanded: false  # 流式态卡片中面板是否保持展开
  print_strategy: delay        # "fast"（即时）或 "delay"（更丝滑打字机，默认）
  flush_interval_ms: 100       # 卡片刷新间隔（毫秒，70~2000，默认 100）
  card_ttl_sec: 600            # 卡片存活检测超时（秒）
  max_tool_steps: 20           # 统一面板最多显示的工具步骤数（1~100）
  max_reasoning_rounds: 20     # 统一面板最多显示的推理轮次数（1~100）

  footer:
    show_label: false          # 是否显示字段标签（模型、Token 等）
    # 默认两行布局：
    # fields:
    #   - [status, elapsed, model]
    #   - [tokens, cache, context, cost, compression_exhausted]
    #
    # 可用字段说明：
    #   status      — 回复状态（已完成 / 出错 / 已停止）
    #   elapsed     — AI 回复耗时
    #   model       — 使用的模型名称
    #   cost        — 预估费用（$0.023 估算 / $0.023 实报 / 免费）
    #   tokens      — Token 用量（↑ 输入 ↓ 输出 💭 推理）
    #   cache       — 缓存命中率（cache_read/cache_write 命中率%）
    #   context     — 上下文窗口用量（已用/总量 百分比）
    #   compression_exhausted — 上下文已满（⚠ 上下文已满）
    #   api_calls   — 本轮对话的 API 调用次数
    #   history_offset — 对话历史偏移量
```

### /aowen 命令

在飞书中发送 `/aowen` 系列命令，插件直接回复卡片：

| 命令                   | 说明                                                |
| ---------------------- | --------------------------------------------------- |
| `/aowen help`          | 显示所有命令列表                                    |
| `/aowen status`        | 查看插件状态 + 当前配置                             |
| `/aowen monitor`       | 查看监控面板（卡片数、API 调用数、错误码分布）       |
| `/aowen monitor reset` | 重置监控统计计数器                                  |
| `/aowen config reload` | 修改配置后立即生效，无需重启网关                    |

### 飞书凭据

插件复用 Hermes 已配置的飞书凭据，无需单独配置。如果 Hermes 飞书渠道能正常工作，插件也能正常工作。

---

## 架构

```
┌─────────────────────────────────────────────────────────┐
│                    Hermes Agent                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │              GatewayRunner / AIAgent               │  │
│  │   (运行时 patch — 不修改源码)                       │  │
│  └──────────────┬───────────────────────┬────────────┘  │
│                 │                       │                │
│     ┌───────────▼──────────┐  ┌────────▼─────────┐      │
│     │   FeishuAdapter      │  │   Cron Scheduler  │      │
│     │ .send() → 拦截为卡片  │  │ .deliver → 卡片    │      │
│     │ .send_clarify() →     │  └──────────────────┘      │
│     │   交互式澄清卡片       │                            │
│     │ .send_exec_approval() │                            │
│     │   → CardKit 2.0 卡片  │                            │
│     └───────────┬──────────┘                            │
│                 │                                        │
│  ┌──────────────▼────────────────────────────────────┐  │
│     │              插件 (hermes-lark-streaming)         │
│     │                                                   │
│     │  ┌─────────────┐  ┌──────────────┐  ┌──────────┐ │
│     │  │ Controller   │  │  CardKit     │  │ Patching │ │
│     │  │ (会话管理,    │  │  (卡片构建)   │  │ (运行时  │ │
│     │  │  flush, seal)│  │              │  │  补丁)   │ │
│     │  └──────┬──────┘  └──────┬───────┘  └──────────┘ │
│     │         │                │                        │
│     │  ┌──────▼──────────────────────────────┐         │
│     │  │         FeishuClient                  │         │
│     │  │  (CardKit v2.0 API: stream_element,  │         │
│     │  │   batch_update, close_streaming,     │         │
│     │  │   cardkit_update, create_card)       │         │
│     │  └──────────────────────────────────────┘         │
│     └───────────────────────────────────────────────────┘
└─────────────────────────────────────────────────────────┘
```

### 关键设计决策

- **运行时 monkey patching** — 不修改 Hermes 源码；所有补丁通过 `FeishuAdapter.method = wrapper(FeishuAdapter.method)` 注入
- **统一面板架构** — 单个 `collapsible_panel` 容纳所有推理/工具步骤，将卡片元素从 50+ 降至 4 个
- **CardKit 2.0 流式** — 使用 `stream_element` 实时文本、`batch_update` 面板更新、`close_streaming` + `cardkit_update` 封口
- **三态交互卡片** — 澄清和审批卡片维护 待选择 → 已提交 → 已确认 的状态流转
- **安全回退** — 每个卡片操作在 CardKit API 失败时自动回退到纯文本

---

## 致谢

- [Aowen-Nowor/hermes-lark-streaming](https://github.com/Aowen-Nowor/hermes-lark-streaming) — 上游插件基础 (MIT)
- [Cheerwhy/hermes-lark-streaming](https://github.com/Cheerwhy/hermes-lark-streaming) — 原始插件 (MIT)
- [larksuite/openclaw-lark](https://github.com/larksuite/openclaw-lark) — 飞书官方插件，按 MIT 协议移植特性
- [baileyh8/hermes-feishu-streaming-card](https://github.com/baileyh8/hermes-feishu-streaming-card) — 头部/状态设计参考
