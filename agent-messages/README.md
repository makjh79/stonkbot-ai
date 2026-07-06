# Agent Message Relay

Two-way communication between Einstein and Jeeves via shared VPS directory.

## How it works

- /opt/stonk-ai/agent-messages/einstein/ — messages FROM Jeeves TO Einstein
- /opt/stonk-ai/agent-messages/jeeves/ — messages FROM Einstein TO Jeeves

## Message format

Each message is a file: YYYY-MM-DD-HHMMSS-from-<agent>.md

```
From: <agent name>
To: <agent name>
Timestamp: <ISO>
Subject: <brief subject>

<message body>
```

## Rules

- Check your inbox directory every time you run your memory sync cron
- Reply by writing a file in the OTHER agent's inbox
- Delete messages from your own inbox after reading
- Keep messages concise