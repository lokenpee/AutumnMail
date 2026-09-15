# Security Policy

## Local-only data

Agent Mail is designed as a local-first application.

The following files are private runtime data and must never be committed:

- `data/agent_mail.db`
- `data/*.db-wal`
- `data/*.db-shm`
- `data/backups/`
- `data/web.log`
- `.env` files
- certificate and private-key files

The repository `.gitignore` excludes these paths.

Release ZIP 和 GitHub 源码压缩包不包含 `data/`、SQLite 数据库、Windows 凭据或任何用户资料；首次运行时才会在本机创建数据库。API Key 的“已保存”状态来自当前 Windows 用户的 Credential Manager，因此在同一台电脑上运行过开发版后再运行 release，仍可能看到之前保存的 Key。这不是 release 包携带的 Key；可在设置页点击“清除已保存 Key”。

## Credentials

- 163 client authorization codes and AI API keys are intended to be stored in Windows Credential Manager.
- Do not place authorization codes or API keys in source code, documentation, tests, screenshots, issues, or commits.
- If a credential was ever committed or exposed, revoke or rotate it immediately.

邮箱同步和规则处理默认在本机完成。启用云端筛选/主模型后，邮件正文（以及为请求所需的字段）会按你填写的 Base URL 发送给对应的 AI 服务商；API Key 也只会作为该请求的 Authorization 发送给该服务商，不会自动发送到本项目、GitHub 或开发者。使用 Ollama/LM Studio 等本地 Base URL 时，模型请求可保持在本机。

## Before publishing to GitHub

1. Run `git status --short --ignored`.
2. Confirm `data/` is ignored and not staged.
3. Search the staged diff for keys, authorization codes, email addresses, and personal names.
4. Check that no database backup or log file is tracked.
5. If a secret was previously committed, rewrite history before pushing and rotate the secret.
