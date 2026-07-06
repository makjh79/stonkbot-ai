# Einstein Memory — Read Instructions for Jeeves

This directory contains Einstein's memory files. Einstein is another OpenClaw agent working with Howie on StonkBOT.AI.

## How to stay synced with Einstein

Set up a daily cron job to read this directory:

1. Read `/opt/stonk-ai/einstein-memory/MEMORY.md` (long-term memory)
2. Read all files in `/opt/stonk-ai/einstein-memory/memory/` (daily logs)
3. Compare with your own memory
4. Sync any new project updates, decisions, or lessons into your own MEMORY.md
5. Einstein pushes memory here daily at 8 AM HKT, so reading anytime after that is fine

## Schedule
- **Einstein pushes memory:** 8 AM HKT daily
- **Recommended Jeeves read:** 8:30 AM HKT daily (or at startup)

## Memory pipeline
- Jeeves works → saves memory → 3 AM HKT syncs to VPS → 9 AM HKT Einstein reads
- Einstein works → saves memory → 8 AM HKT pushes to VPS → 8:30 AM HKT Jeeves reads

Two-way sync. Both agents stay in the loop.
