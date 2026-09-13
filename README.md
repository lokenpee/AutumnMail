# Agent Mail

一个面向秋招场景的本地优先邮件整理 Agent。

它将 163 邮箱中的求职邮件同步到本机 SQLite，然后进行筛选、结构化提取、公司聚合、DDL 和面试事件管理，并通过本地 Web UI 展示。

## 功能

- 通过 163 IMAP 只读同步收件箱邮件
- 本地 SQLite 持久化
- 使用筛选模型过滤广告、营销和无关邮件
- 使用主模型提取邮件类别、公司、DDL、面试和主链接
- 公司聚合、公司搜索和公司详情时间线
- 日历展示测评、笔试、面试和 DDL
- 完成状态、DDL 修正和人工复核
- 本地 Agent 日志
- API Key 存入 Windows Credential Manager，不写入源码和数据库

## 环境要求

- Windows
- Python 3.10+
- 163 邮箱客户端授权码
- 筛选 API：支持硅基流动、DeepSeek、OpenAI、Qwen、Kimi、智谱、OpenRouter、Groq、Ollama 等 OpenAI 兼容接口
- 主模型 API：同样支持任意 OpenAI 兼容接口，可手动填写 Base URL 和模型 ID

## 启动

```powershell
python scripts\run_web.py --port 8765 --db data\agent_mail.db
```

普通用户直接双击项目根目录的：

```text
start_agent_mail.bat
```

它会后台启动服务并自动打开浏览器。停止服务时双击：

```text
stop_agent_mail.bat
```

开发环境也可以使用：

```powershell
scripts\restart_web.bat
```

访问：

```text
http://127.0.0.1:8765
```

在设置页配置邮箱、筛选 API 和主 AI API。首次连接邮箱时，授权码只保存到 Windows Credential Manager。

## 免 Python 便携版

GitHub Release 会提供 Windows 便携包：

```text
AgentMail-Windows.zip
```

普通用户只需要：

1. 下载并解压 ZIP。
2. 进入解压后的 `AgentMail` 文件夹。
3. 双击 `AgentMail.exe`。
4. 程序会自动启动本地服务并打开默认浏览器。

无需安装 Python，也不需要执行 `pip install`。首次运行会在 `AgentMail.exe` 同目录创建 `data/agent_mail.db`。

停止方式：在任务管理器中结束 `AgentMail.exe`，或使用项目中的 `stop_agent_mail.bat`。

## 构建便携版

维护者执行：

```text
build_windows.bat
```

完成后生成：

```text
dist\AgentMail\AgentMail.exe
```

用于 GitHub Release 的压缩包位于：

```text
release\AgentMail-Windows.zip
```

`build/`、`dist/` 和 `release/` 都已加入 `.gitignore`，不会进入源码仓库。

## 测试

```powershell
python -m unittest discover -s tests -v
```

## 开源前安全检查

```powershell
python scripts\check_secrets.py
```

该命令只扫描 Git 暂存区，发现数据库、日志、私钥、常见 API Key 等风险文件时会返回失败。

## 目录

```text
src/agent_mail/     后端、数据库、IMAP、AI 和同步服务
web/                本地 Web UI
scripts/            启动、重启和初始化脚本
tests/              单元测试
docs/               PRD、架构和数据模型
data/               本地运行时数据库和日志，禁止提交
```

## 隐私与安全

以下内容属于本地私有数据，**绝对不要提交到 GitHub**：

- `data/agent_mail.db`
- `data/backups/`
- `data/web.log`
- 163 邮箱授权码
- 筛选 API Key
- 主模型 API Key
- `.env`、证书、私钥和其他凭据文件

仓库通过 `.gitignore` 忽略 `data/`、数据库、日志、凭据和常见临时文件。

授权码和 API Key 使用 Windows Credential Manager 存储，不写入 SQLite 或源码。邮件数据库包含邮件正文、地址、公司和 DDL，上传前应确认 Git 暂存区中没有 `data/`。

如果曾经把授权码提交到 Git 历史中，应立刻：

1. 在 163 邮箱中重新生成授权码。
2. 在所有 API 平台撤销旧 Key。
3. 使用 `git filter-repo` 或 BFG 清理历史。
4. 重新检查 GitHub 的 secret scanning 和提交记录。

## 文档

- `docs/prd-v1.md`
- `docs/requirements-analysis.md`
- `docs/data-model.md`
- `docs/technical-architecture.md`
- `docs/p0-backlog.md`
