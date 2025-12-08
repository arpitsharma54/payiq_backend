# Concurrent Bot Execution Guide

## How Multiple Users Starting Bots Works

### ✅ **YES - Parallel Execution is Supported**

The system is designed to handle **multiple bots running simultaneously for different bank accounts**.

### Current Behavior

1. **Different Bank Accounts = Parallel Execution** ✅
   - User A starts bot for Bank Account 1
   - User B starts bot for Bank Account 2
   - User C starts bot for Bank Account 3
   - **Result**: All three bots run in parallel

2. **Same Bank Account = Prevented** ❌
   - User A starts bot for Bank Account 1
   - User B tries to start bot for Bank Account 1 (while A's bot is running)
   - **Result**: User B gets error: "Bot is already running for this account"

### How It Works

#### Lock Mechanism (Per Bank Account)
- Each bank account has its own Redis lock: `celery_task_run_bot_lock_{bank_account_id}`
- Lock prevents the same bank account from running multiple bots simultaneously
- Different bank accounts have different locks, so they can run in parallel

#### Code Flow:
```python
# In StartBotView (merchants/views.py)
lock_key = f'celery_task_run_bot_lock_{pk}'  # Unique per bank account
if redis_client.get(lock_key):
    return Response({'message': 'Bot is already running for this account'})

# In run_single_bot (deposit/task.py)
lock_key = f'celery_task_run_bot_lock_{bank_account_id}'  # Same unique key
redis_client.set(lock_key, self.request.id, ex=lock_timeout)  # Acquire lock
```

### Resource Considerations

#### Celery Worker Concurrency
By default, Celery workers use concurrency based on CPU cores. To control this:

**Start worker with specific concurrency:**
```bash
celery -A payiq worker --concurrency=4 --beat --loglevel=info
```

This allows up to 4 tasks to run simultaneously.

**Recommended settings:**
- **Development**: `--concurrency=2` (2 parallel bots)
- **Production**: `--concurrency=4` to `--concurrency=8` (depending on server resources)

#### Browser Instances
- Each bot launches its own Playwright browser instance
- Multiple browser instances can run in parallel
- Each instance uses memory (~200-500MB per browser)
- System resources (CPU, RAM) determine how many can run simultaneously

### Example Scenarios

#### Scenario 1: Multiple Users, Different Accounts ✅
```
User A → Start Bot (Account 1) → ✅ Running
User B → Start Bot (Account 2) → ✅ Running (parallel)
User C → Start Bot (Account 3) → ✅ Running (parallel)
```
**Result**: All 3 bots run simultaneously

#### Scenario 2: Same User, Different Accounts ✅
```
User A → Start Bot (Account 1) → ✅ Running
User A → Start Bot (Account 2) → ✅ Running (parallel)
User A → Start Bot (Account 3) → ✅ Running (parallel)
```
**Result**: All 3 bots run simultaneously

#### Scenario 3: Multiple Users, Same Account ❌
```
User A → Start Bot (Account 1) → ✅ Running
User B → Start Bot (Account 1) → ❌ Error: "Bot is already running"
User C → Start Bot (Account 1) → ❌ Error: "Bot is already running"
```
**Result**: Only User A's bot runs

#### Scenario 4: Sequential Execution (After First Completes) ✅
```
User A → Start Bot (Account 1) → ✅ Running
User B → Start Bot (Account 1) → ❌ Error (waiting...)
[Bot completes]
User B → Start Bot (Account 1) → ✅ Running (now works)
```
**Result**: Second request works after first completes

### Monitoring Concurrent Executions

#### Check Active Locks:
```bash
redis-cli
> KEYS celery_task_run_bot_lock_*
```

#### Check Active Celery Tasks:
```bash
celery -A payiq inspect active
```

#### View Logs for All Bots:
```bash
tail -f payiq_backend/logs/bot.log | grep -E "Starting bot|completed|failed"
```

### Best Practices

1. **Set Appropriate Concurrency**
   - Don't set concurrency higher than your server can handle
   - Each bot uses ~200-500MB RAM + CPU for browser automation
   - Monitor system resources: `htop` or `top`

2. **Monitor Resource Usage**
   ```bash
   # Check memory usage
   free -h
   
   # Check CPU usage
   top
   
   # Check running browser processes
   ps aux | grep chromium
   ```

3. **Handle Errors Gracefully**
   - If a bot fails, the lock is released automatically
   - Lock timeout is 1 hour (safety measure)
   - Failed bots don't block other bank accounts

4. **Production Recommendations**
   - Use process manager (supervisor/systemd) to restart workers
   - Set concurrency based on server specs
   - Monitor logs for bottlenecks
   - Consider load balancing if needed

### Troubleshooting

#### Issue: "Bot is already running" but no bot is actually running
**Solution**: Lock might be stuck. Clear it:
```bash
redis-cli
> DEL celery_task_run_bot_lock_{bank_account_id}
```

#### Issue: Too many bots running, server overloaded
**Solution**: Reduce Celery concurrency:
```bash
# Restart worker with lower concurrency
celery -A payiq worker --concurrency=2 --beat --loglevel=info
```

#### Issue: Bots not running in parallel
**Solution**: Check Celery concurrency setting:
```bash
celery -A payiq inspect stats
# Look for "pool" -> "processes" or "threads"
```

### Summary

✅ **Multiple users can start bots for different bank accounts in parallel**
✅ **Each bank account can only have one bot running at a time**
✅ **System resources (CPU, RAM) determine maximum parallel executions**
✅ **Celery concurrency setting controls how many tasks run simultaneously**

The system is designed to be safe (prevent duplicate executions) while allowing parallel processing for different bank accounts.

