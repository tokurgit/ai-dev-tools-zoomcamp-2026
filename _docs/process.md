- Tasks are GitHub issues, one at a time
- Read the acceptance criteria before starting and before closing
- Ask if requirements are not clear
- Provide options with comparison across them
- Commit regularly
- Any issue that touches code is checked before it closes to confirm total
  coverage did not drop - `uv run pytest` fails on the `--cov-fail-under`
  floor if it did (see `_docs/team/qa-engineer.md`)

Roles

- PM - grooms a task before anyone implements it, follows _docs/team/pm.md
- Engineer - implements one groomed task, follows _docs/team/software-engineer.md
- QA - checks the result against the acceptance criteria, follows _docs/team/qa-engineer.md
