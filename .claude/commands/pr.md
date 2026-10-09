---
description: Draft a PR title and description from the commits on this branch (prints text only, never pushes)
allowed-tools: Bash(git diff --stat master...HEAD), Bash(git log --oneline master..HEAD)
---
Base branch: `master` (this repo's only branch; edit the two lines below for another base).

Diff summary: !`git diff --stat master...HEAD`
Commits: !`git log --oneline master..HEAD`

Write a Conventional-Commit style PR title, then these sections:
- Summary: what changed and why, in a few sentences.
- Changes: one bullet per logical change, matching the commits.
- How to test: the exact `make` targets, and any manual step.
- Risks: migrations, security-relevant changes (auth, tenancy, prompts), anything unverified.

Use only the diff summary and commits above; don't invent changes or test results.
If both are empty, say there is nothing to describe against that base.
Do not push, open the PR, or run any other command. Print the text only.
