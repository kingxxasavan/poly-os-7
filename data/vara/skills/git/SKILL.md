---
name: git
description: Use git safely - inspect, commit in small steps, branch, and work with GitHub remotes
---

# git

- Look before acting: `git status`, `git diff`, `git log --oneline -10` (these need no approval).
- New project: `git init`, a `.gitignore` for the language (`.venv/`, `__pycache__/`, `build/`, `node_modules/`, `*.gcode`).
- Commit small, related changes with a clear message in the imperative ("Add gripper servo control").
  Stage specific files (`git add path`), not everything, unless the person asked.
- Never `push --force`, `reset --hard`, `clean -fd` or rewrite history without the person saying so
  explicitly; explain what would be lost first.
- Pushing uses the person's own credentials; if it asks for a login, tell them to set up
  `gh auth login` or an SSH key themselves. Never ask for their password or token.
