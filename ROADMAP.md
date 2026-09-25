# Next improvements

These are candidates for later small, testable changes. Each change should be useful on its own.

1. Show model-by-model latency and token usage beside each answer, with a per-run total.
2. Add configurable timeout and concurrency limits for large councils; report skipped or timed-out members.
3. Add export of one completed council run as a portable Markdown file with question, member answers, rankings, and final answer.
4. Add a local-only health view for 9Router connection, combo membership, and chairman readiness.
5. Add a Telegram delivery adapter for AI-Ege that sends the final answer plus a compact participation report and links to detailed local history.

Do not run these changes automatically on a schedule. Ege can ask AI-Ege to choose one item, implement it, run CI, and publish the reviewed result.
