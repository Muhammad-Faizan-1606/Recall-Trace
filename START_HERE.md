# Start RecallTrace in Codex

## Open the project

Extract the archive and open the enclosed recalltrace folder as the local project folder in Codex or in an editor with Codex. Open the folder containing AGENTS.md, not only the documentation subfolder. In an already installed Codex CLI, start from that folder with the codex command. If you use a cloud repository workflow, place these project files in the repository/environment selected for your task first; a local folder and this chat are not an automatically configured cloud repository.

The package contains the project files and a focused decision summary. It is not an imported Codex chat history. It does not configure credentials, create a remote repository or publish the application.

## First task to paste

Build RecallTrace from this project folder. Read AGENTS.md, HANDOFF.md, PLAN.md and STATUS.md, then the original rubric in references/Flask_Project_Rubric.pdf and the relevant specification files under documentation. This is currently documentation only. The full target is the documented 100-model Flask/Jinja/PostgreSQL product, with the complete 72-model Core release first and 28 Expanded models afterward. Start with M1: inspect the toolchain, bootstrap the real application, and deliver an authenticated company-scoped catalog CRUD slice with migrations, server validation, CSRF, flash messages, Post-Redirect-Get and meaningful PostgreSQL/authorization tests. Make necessary local changes and verify them; continue through the plan in complete working increments rather than returning only a plan or empty table scaffolding. Preserve protected history, do not invent test results, and update STATUS.md and DECISIONS.md with actual evidence and the next task.

## Resume in a later session

Read AGENTS.md, HANDOFF.md, PLAN.md and STATUS.md. Inspect the live application and latest test evidence. Continue the next incomplete milestone, keep the rubric and logical design synchronized with implemented scope, and record observed results rather than repeating the original planning exercise.

## Official guidance

- OpenAI desktop app guidance: https://learn.chatgpt.com/docs/app
- OpenAI Codex repository guidance and project instructions: https://developers.openai.com/cookbook/examples/codex/iterating-development-workflows-with-codex

AGENTS.md is recognized repository guidance. PLAN.md, STATUS.md and the other handoff documents are project conventions supplied for continuity, not mandatory Codex product files.
