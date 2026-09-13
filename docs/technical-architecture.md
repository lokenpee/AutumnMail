# 秋招邮件 Agent 技术架构 v0.1

> 关联文档：`docs/requirements-analysis.md`、`docs/data-model.md`
> 目标：本地优先，后端与 UI 解耦，MVP 只读邮箱，后续可扩展桌面端和自动化任务。

## 1. 技术选型

首版采用本地 Web/桌面承载方式，后端使用 Python，数据存储在 SQLite。

| 层 | 选型 | 原因 |
|---|---|---|
| 邮箱连接 | Python IMAP + 163 专用兼容处理 | 可控、易调试、无需第三方服务 |
| 数据库 | SQLite | 单用户本地场景足够，安装成本低 |
| 后端 API | FastAPI | 类型清晰、适合本地 Web 和后续桌面壳 |
| 数据访问 | SQLAlchemy 2.x 或轻量 Repository | 先隔离 SQL，后换 PostgreSQL 不影响业务层 |
| 任务调度 | 后端内置调度器 + 启动时同步 | MVP 不做独立消息队列 |
| 前端 | React/Vite，待原型确认 | 原型之后再定 UI 技术细节 |
| 分类 | 规则优先，LLM 兜底 | 降低成本，提高可解释性 |
| 结构化抽取 | 规则 + LLM + 人工确认 | DDL 和公司识别需要高可靠 |
| 凭证 | Windows Credential Manager / keyring | 不将授权码写入数据库和源码 |
| 日志 | 结构化本地日志 | 默认脱敏，不记录授权码和完整正文 |

## 2. 逻辑分层

```text
┌──────────────────────────────────────────────┐
│ UI：总览 / 邮件 / 公司 / 日历 / 待确认         │
└───────────────────────┬──────────────────────┘
                        │ HTTP / JSON
┌───────────────────────▼──────────────────────┐
│ Application API                              │
│ 查询、筛选、状态修改、DDL、公司合并、日历       │
└───────────────────────┬──────────────────────┘
                        │
┌───────────────────────▼──────────────────────┐
│ Domain Services                              │
│ Sync / Resolve / Classify / Extract / State  │
└───────────┬───────────┬───────────┬──────────┘
            │           │           │
      IMAP Client   Rules Engine  LLM Adapter
            │           │           │
┌───────────▼───────────▼───────────▼──────────┐
│ Repository Layer + SQLite                     │
│ emails / companies / classifications / DDL    │
└──────────────────────────────────────────────┘
```

## 3. 核心模块

### 3.1 `mail_sync`

职责：

- 读取账号和文件夹配置。
- 建立 163 IMAP 连接。
- 发送 163 兼容的 IMAP ID 命令。
- 文件夹发现和同步范围选择。
- 首次同步和增量同步。
- 邮件头、正文和附件元数据解析。
- 更新 `folders`、`emails` 和 `email_locations`。
- 记录同步进度、错误和重试。

### 3.2 `normalizer`

职责：

- MIME 邮件解码。
- HTML 转文本。
- 主题、发件人和地址规范化。
- 生成邮件摘要。
- 生成 `canonical_key` 和 `content_hash`。

### 3.3 `company_resolver`

职责：

- 根据用户规则、公司别名、发件域名、线程和正文识别公司。
- 生成公司候选结果和置信度。
- 低置信度结果进入待确认队列。
- 将人工确认结果写回别名和规则表。

### 3.4 `classifier`

职责：

- 按照规则匹配六类主分类。
- 对不确定邮件调用模型分类。
- 生成分类来源、置信度和理由。
- 不覆盖人工分类。

### 3.5 `deadline_extractor`

职责：

- 从正文中识别截止日期和时间。
- 处理中文日期、相对日期、缺少年份和时间精度。
- 生成多个候选时进入待确认。
- 人工修改后禁止自动覆盖。

### 3.6 `state_service`

职责：

- 根据最新邮件和人工结果派生公司/岗位状态。
- 维护完成、忽略、置顶和 DDL 状态。
- 保证邮件状态和 DDL 状态的一致性。

### 3.7 `calendar_service`

职责：

- 按日期聚合 DDL 和面试事件。
- 计算待完成、已完成、逾期和临期状态。
- 提供日期详情和邮件跳转所需的关联数据。

## 4. 同步架构

### 4.1 首次同步

```text
读取账号
  -> 连接 163 IMAP
  -> 发送 ID 命令
  -> 获取文件夹列表
  -> 按配置过滤文件夹
  -> 获取 UIDVALIDITY 和 UIDNEXT
  -> 批量 UID SEARCH
  -> 分批 FETCH 邮件头和正文
  -> 规范化
  -> 幂等写入 emails/email_locations
  -> 启动公司与分类处理
  -> 更新文件夹游标
```

### 4.2 增量同步

```text
读取 folder.last_uid
  -> 检查 UIDVALIDITY
  -> 若变化：重置该文件夹并全量重建位置
  -> 否则：UID FETCH last_uid+1:*
  -> 解析新增或变更邮件
  -> 更新 flags、位置和最后同步时间
```

### 4.3 去重规则

优先级：

1. `Message-ID`
2. 邮件头组合哈希：`from + subject + date + size`
3. 正文内容哈希

同一 `canonical_key` 只创建一个 `emails` 记录。不同文件夹中的相同邮件写入多个 `email_locations`。

### 4.4 失败处理

- 单封邮件解析失败不阻断整批同步。
- 文件夹同步失败记录错误，下一次继续。
- 认证失败立即停止重试并提示用户更新授权码。
- 网络错误使用指数退避。
- 速率限制时降低批大小和频率。

## 5. 邮件处理流水线

```text
imported
  -> normalized
  -> company_resolved
  -> classified
  -> deadline_extracted
  -> review_required 或 ready
```

每一步写入 `processing_jobs`，支持：

- 失败重试。
- 只重跑失败阶段。
- 重新分类但不影响人工结果。
- 在模型升级后选择性重跑低置信度邮件。

## 6. 公司识别策略

按以下顺序执行：

1. 人工确认的公司和岗位。
2. 同线程已经确认的公司。
3. `company_aliases` 中的发件人、域名、ATS 映射。
4. 规则模板匹配。
5. 正文签名、公司名和岗位名的组合匹配。
6. LLM 判断。
7. 仍然不确定则进入待确认队列。

结果写入 `email_company_links`。一个邮件最多有一个 `primary` 公司，可以有多个 `mentioned` 岗位。

## 7. 分类策略

### 7.1 规则层

规则优先级：

1. 人工规则。
2. 已知模板和关键词。
3. 发件人和招聘系统映射。
4. 正文流程状态词。
5. 模型分类。

建议首批规则覆盖：

- 申请已收到：`申请已收到`、`感谢投递`、`application received`。
- 拒绝：`感谢您的关注`、`未通过`、`not selected`、`unfortunately`。
- 测评：`测评`、`assessment`、`questionnaire`。
- 笔试：`笔试`、`written test`、`coding test`。
- 面试：`面试`、`interview`、`视频面试`。
- Offer：`offer`、`录用`、`录用通知`。

规则结果不能覆盖人工结果。

### 7.2 LLM 层

仅对规则无法确定或置信度低的邮件调用模型。输入尽量最小化：

- 主题
- 发件人
- 正文摘要或相关段落
- 用户已确认的上下文

模型输出结构化 JSON，由后端校验后再写入数据库。

### 7.3 置信度

建议阈值：

- `>= 0.90`：自动接受。
- `0.65 - 0.90`：展示但进入复核队列。
- `< 0.65`：不自动接受，直接待确认。

阈值做成配置，便于根据真实邮件调整。

## 8. DDL 抽取策略

1. 规则匹配明确日期表达。
2. 结合邮件接收日期推断年份。
3. 校验日期是否合理，拒绝过去过久的误抽取。
4. 多个候选日期不自动选择，进入待确认。
5. 模型只处理规则无法解析的文本。
6. 用户手动编辑后设置 `is_manual_override=1`。
7. 所有 DDL 保留原文证据。

## 9. API 草案

首版只需要本地 API，具体 URL 可在原型确认后调整。

### 账号与同步

- `GET /api/accounts`
- `POST /api/accounts`
- `PATCH /api/accounts/{id}`
- `POST /api/accounts/{id}/test`
- `GET /api/sync/status`
- `POST /api/sync/run`

### 邮件

- `GET /api/emails?start=&end=&company_id=&type=&completed=`
- `GET /api/emails/{id}`
- `PATCH /api/emails/{id}/classification`
- `PATCH /api/emails/{id}/state`
- `PATCH /api/emails/{id}/company-link`
- `GET /api/emails/{id}/locations`

### 公司和岗位

- `GET /api/companies`
- `GET /api/companies/{id}`
- `POST /api/companies/merge`
- `POST /api/companies/{id}/positions`
- `PATCH /api/positions/{id}`

### DDL

- `GET /api/deadlines?start=&end=&status=`
- `POST /api/emails/{id}/deadlines`
- `PATCH /api/deadlines/{id}`
- `POST /api/deadlines/{id}/complete`
- `POST /api/deadlines/{id}/reopen`
- `DELETE /api/deadlines/{id}`

### 日历

- `GET /api/calendar?start=&end=`
- `GET /api/calendar/days/{date}`

### 统计和复核

- `GET /api/stats?start=&end=`
- `GET /api/review-queue`
- `POST /api/review-queue/{id}/resolve`
- `GET /api/settings`
- `PATCH /api/settings`

## 10. 安全设计

- 授权码只存系统凭据管理器，数据库只保存 `credential_ref`。
- API 日志对邮箱地址、授权码、正文和链接进行脱敏。
- 不把完整原始邮件默认发送给模型。
- LLM API Key 与邮箱授权码分开管理。
- 所有本地数据库文件设置用户级访问权限。
- 提供“清除邮件索引”和“断开邮箱”操作。
- 用户操作审计写入 `audit_logs`，但不记录敏感正文。

## 11. 部署形态

### MVP

- 本地 Python 后端。
- 本地 SQLite 数据库。
- 本地 Web UI。
- 可通过 `python -m agent_mail` 启动。
- 后续可以用 Tauri、Electron 或系统托盘壳包装。

### 后续

- Windows 开机后台同步。
- 系统通知。
- 可选的本地 MCP 接口，让 Codex 或其他 Agent 查询规范化数据。
- 如果多设备需求出现，再增加加密同步服务，不改变领域模型。

## 12. 实施顺序

1. 建立 SQLite schema 和数据仓储。
2. 实现账号配置和系统凭据存储。
3. 实现 163 IMAP 连接、文件夹发现和历史同步。
4. 实现增量同步和去重。
5. 实现规范化、公司识别和分类。
6. 实现 DDL 抽取和人工覆盖。
7. 实现查询 API。
8. 接入前端原型。
9. 实现日历、提醒和统计。
