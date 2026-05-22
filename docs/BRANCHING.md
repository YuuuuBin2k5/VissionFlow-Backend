# Branching Strategy

## Permanent Branches

Use two long-lived branches:

- `main`: stable production-ready code.
- `develop`: integration branch for upcoming work.

Do not push directly to `main`.

## Short-Lived Branches

Use short-lived branches for work:

- `feature/<name>` for new capabilities.
- `fix/<name>` for non-urgent bug fixes.
- `hotfix/<name>` for urgent fixes from `main`.
- `docs/<name>` for documentation-only changes.

Delete short-lived branches after merge.

## Recommended Starting Branches

Create only these two first:

```text
main
develop
```

Then create feature branches only when needed, for example:

```text
feature/youtube-bot-v1
feature/security-env-cleanup
feature/publisher-adapters
feature/render-worker-refactor
hotfix/tiktok-publish-button
```

## Merge Flow

Normal feature:

```text
feature/name -> develop -> main
```

Urgent production fix:

```text
main -> hotfix/name -> main
                  -> develop
```

## Commit Style

Use Conventional Commits:

```text
feat: add youtube telegram bot
fix: prevent tiktok bot from handling youtube intents
docs: add architecture guardrails
chore: update env example
```

## Protection Rules

Protect `main`:

- Require pull request before merge.
- Require status checks before merge.
- Block direct pushes.
- Prefer squash merge for clean history.

Protect `develop` after the project becomes active with multiple feature branches.
