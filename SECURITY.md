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

## Credentials

- 163 client authorization codes and AI API keys are intended to be stored in Windows Credential Manager.
- Do not place authorization codes or API keys in source code, documentation, tests, screenshots, issues, or commits.
- If a credential was ever committed or exposed, revoke or rotate it immediately.

## Before publishing to GitHub

1. Run `git status --short --ignored`.
2. Confirm `data/` is ignored and not staged.
3. Search the staged diff for keys, authorization codes, email addresses, and personal names.
4. Check that no database backup or log file is tracked.
5. If a secret was previously committed, rewrite history before pushing and rotate the secret.
