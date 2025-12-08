# How to View Bot Logs

Since the bot runs as a Celery Beat scheduled task, logs are written to files and console. Here's how to view them:

## Log File Locations

After the logging configuration update, logs are written to the following files in the `payiq_backend/logs/` directory:

- **`bot.log`** - All bot execution logs (from `core.bot.bot`)
- **`celery.log`** - Celery worker and task logs
- **`deposit.log`** - Deposit task logs (from `deposit.task`)

## Viewing Logs

### 1. View Bot Logs in Real-Time (Recommended)

```bash
# View bot logs in real-time
tail -f payiq_backend/logs/bot.log

# View Celery logs in real-time
tail -f payiq_backend/logs/celery.log

# View all logs together
tail -f payiq_backend/logs/*.log
```

### 2. View Recent Logs

```bash
# Last 100 lines of bot logs
tail -n 100 payiq_backend/logs/bot.log

# Last 50 lines with timestamps
tail -n 50 payiq_backend/logs/bot.log | grep -E "\[INFO\]|\[ERROR\]|\[WARNING\]"
```

### 3. Search Logs

```bash
# Search for errors
grep -i "error" payiq_backend/logs/bot.log

# Search for specific bank account
grep "bank account.*ID" payiq_backend/logs/bot.log

# Search for today's logs
grep "$(date +%Y-%m-%d)" payiq_backend/logs/bot.log
```

### 4. View Logs by Date/Time

```bash
# View logs from last hour
grep "$(date -d '1 hour ago' +%Y-%m-%d)" payiq_backend/logs/bot.log

# View logs with timestamps
cat payiq_backend/logs/bot.log | grep -E "\[.*\]"
```

## If Logs Directory Doesn't Exist

The logs directory is automatically created when Django starts. If it doesn't exist, create it manually:

```bash
mkdir -p payiq_backend/logs
```

## Log Rotation

Logs are automatically rotated when they reach 10MB. The system keeps 5 backup files:
- `bot.log` (current)
- `bot.log.1` (previous)
- `bot.log.2` (older)
- etc.

## Viewing Celery Worker Logs

If you're running Celery workers manually, you can also see logs in the terminal:

### Start Celery Worker (for manual testing)
```bash
cd payiq_backend
celery -A payiq worker --loglevel=info
```

### Start Celery Beat (scheduler)
```bash
cd payiq_backend
celery -A payiq beat --loglevel=info
```

### Start Both Together (for development)
```bash
cd payiq_backend
celery -A payiq worker --beat --loglevel=info
```

## Production Setup

For production, you might want to:

1. **Use a process manager** (like supervisor or systemd) to run Celery workers
2. **Redirect logs** to specific files:
   ```bash
   celery -A payiq worker --loglevel=info >> logs/celery_worker.log 2>&1
   celery -A payiq beat --loglevel=info >> logs/celery_beat.log 2>&1
   ```

3. **Use log aggregation tools** like ELK stack, Splunk, or CloudWatch

## Common Log Patterns

### Bot Started
```
[INFO] 2024-01-01 10:00:00 core.bot.bot Starting bot for bank account: AccountName (ID: 1)
```

### Bot Completed
```
[INFO] 2024-01-01 10:05:00 core.bot.bot Bot execution completed for bank account 1
```

### Bot Error
```
[ERROR] 2024-01-01 10:03:00 core.bot.bot Bot execution failed for bank account 1: Error message
```

### Task Skipped (Already Running)
```
[INFO] 2024-01-01 10:00:00 deposit.task Task 'run_bot' is already running. Skipping execution.
```

## Troubleshooting

### No logs appearing?
1. Check if the logs directory exists: `ls -la payiq_backend/logs/`
2. Check file permissions: `chmod 755 payiq_backend/logs/`
3. Verify Celery workers are running: `ps aux | grep celery`
4. Check if Redis is running: `redis-cli ping`

### Logs too verbose?
Edit `payiq_backend/payiq/settings.py` and change log levels:
- `'level': 'INFO'` → `'level': 'WARNING'` (less verbose)
- `'level': 'INFO'` → `'level': 'DEBUG'` (more verbose)

