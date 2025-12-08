# Celery Worker Setup Guide

## Problem: Bot Not Running / No Logs

If you're calling the start-bot API but not seeing:
- Status updates in the UI
- Logs in log files
- Bot execution

**The most likely cause is that Celery workers are not running.**

## Solution: Start Celery Workers

Celery workers are separate processes that execute the queued tasks. You need to start them separately from the Django server.

### Option 1: Start Worker and Beat Together (Recommended for Development)

```bash
cd payiq_backend
celery -A payiq worker --beat --loglevel=info
```

This starts:
- **Celery Worker**: Executes queued tasks (like bot execution)
- **Celery Beat**: Scheduler that triggers periodic tasks

### Option 2: Start Separately (Recommended for Production)

**Terminal 1 - Celery Worker:**
```bash
cd payiq_backend
celery -A payiq worker --loglevel=info
```

**Terminal 2 - Celery Beat (Scheduler):**
```bash
cd payiq_backend
celery -A payiq beat --loglevel=info
```

### Option 3: Run in Background

```bash
cd payiq_backend

# Start worker in background
nohup celery -A payiq worker --loglevel=info > logs/celery_worker.log 2>&1 &

# Start beat in background
nohup celery -A payiq beat --loglevel=info > logs/celery_beat.log 2>&1 &
```

## Verify Workers Are Running

### Check if Celery processes are running:
```bash
ps aux | grep celery
```

You should see processes like:
- `celery -A payiq worker`
- `celery -A payiq beat`

### Check Celery status:
```bash
cd payiq_backend
celery -A payiq inspect active
```

### Check if tasks are being processed:
```bash
cd payiq_backend
celery -A payiq inspect stats
```

## Prerequisites

Before starting Celery workers, ensure:

1. **Redis is running:**
   ```bash
   redis-cli ping
   # Should return: PONG
   ```

2. **Django settings are correct:**
   - `CELERY_BROKER_URL` points to Redis
   - `CELERY_RESULT_BACKEND` points to Redis

3. **Virtual environment is activated:**
   ```bash
   source venv/bin/activate  # or your venv path
   ```

## Troubleshooting

### Issue: "No module named 'payiq'"
**Solution:** Make sure you're in the `payiq_backend` directory and Django settings are correct.

### Issue: "Connection refused" to Redis
**Solution:** 
1. Start Redis: `redis-server`
2. Or check Redis is running: `redis-cli ping`

### Issue: Tasks queued but not executing
**Solution:** 
1. Verify workers are running: `ps aux | grep celery`
2. Check worker logs for errors
3. Restart workers

### Issue: No logs appearing
**Solution:**
1. Check if logs directory exists: `ls -la payiq_backend/logs/`
2. Check file permissions: `chmod 755 payiq_backend/logs/`
3. Verify logging configuration in `settings.py`
4. Check worker is actually processing tasks (see logs in terminal or `celery.log`)

## Production Setup

For production, use a process manager:

### Using Supervisor

Create `/etc/supervisor/conf.d/celery.conf`:

```ini
[program:celery_worker]
command=/path/to/venv/bin/celery -A payiq worker --loglevel=info
directory=/path/to/payiq_backend
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/path/to/payiq_backend/logs/celery_worker.log

[program:celery_beat]
command=/path/to/venv/bin/celery -A payiq beat --loglevel=info
directory=/path/to/payiq_backend
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/path/to/payiq_backend/logs/celery_beat.log
```

Then:
```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start celery_worker
sudo supervisorctl start celery_beat
```

### Using systemd

Create `/etc/systemd/system/celery-worker.service`:

```ini
[Unit]
Description=Celery Worker
After=network.target

[Service]
Type=forking
User=www-data
Group=www-data
WorkingDirectory=/path/to/payiq_backend
ExecStart=/path/to/venv/bin/celery -A payiq worker --loglevel=info --detach
ExecStop=/bin/kill -s TERM $MAINPID
Restart=always

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable celery-worker
sudo systemctl start celery-worker
```

## Quick Start Checklist

1. ✅ Redis is running (`redis-cli ping`)
2. ✅ Virtual environment activated
3. ✅ In `payiq_backend` directory
4. ✅ Start Celery worker: `celery -A payiq worker --beat --loglevel=info`
5. ✅ Check logs: `tail -f logs/bot.log`

## Testing Bot Execution

1. Start Celery workers (see above)
2. Call the start-bot API from frontend
3. Watch logs in real-time:
   ```bash
   tail -f payiq_backend/logs/bot.log
   ```
4. Check WebSocket status updates in browser console

