---
name: cron-test-skill
description: A scheduled skill for integration testing
trigger: cron
schedule: "*/5 * * * *"
autonomy: autonomous
tools: []
shell-policy: none
---
# Cron Test Skill
Run every 5 minutes. Log a heartbeat.
