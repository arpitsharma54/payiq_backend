import asyncio
import logging
import re
import os
import pandas as pd
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
from merchants.models import BankAccount, ExtractedTransactions
from deposit.models import Payin
from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from channels.layers import get_channel_layer
import redis

# Get the directory where this bot file is located
BOT_DIR = os.path.dirname(os.path.abspath(__file__))

logger = logging.getLogger(__name__)

# Redis client for checking stop flag
redis_client = redis.Redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)

# Get bot execution interval from settings (default: 30 seconds)
BOT_INTERVAL = getattr(settings, 'BOT_EXECUTION_INTERVAL', 30)


class BotStoppedException(Exception):
    """Exception raised when bot is stopped by user."""
    pass


class LoggedOutException(Exception):
    """Exception raised when session logout is detected."""
    pass


# Constants for relogin
MAX_RELOGIN_ATTEMPTS = 5
RELOGIN_DELAY_SECONDS = 3


def check_stop_flag(bank_account_id: int) -> bool:
    """Check if stop flag is set for the given bank account."""
    stop_flag_key = f'bot_stop_flag_{bank_account_id}'
    return redis_client.get(stop_flag_key) is not None


async def check_stop_and_raise(bank_account_id: int, send_status=None):
    """Check stop flag and raise exception if set."""
    if check_stop_flag(bank_account_id):
        logger.info(f"Stop flag detected for bank account {bank_account_id}. Stopping bot immediately.")
        if send_status:
            await send_status('stopped', 'Bot stopped by user request')
        raise BotStoppedException(f"Bot stopped by user request for account {bank_account_id}")


async def send_status_to_websocket(status, message="", merchant_id=None, bank_account_id=None):
    channel_layer = get_channel_layer()
    payload = {
        "type": "task_update",
        "status": status,
        "message": message,
    }
    if merchant_id:
        payload["merchant_id"] = merchant_id
    if bank_account_id:
        payload["bank_account_id"] = bank_account_id

    await channel_layer.group_send(
        "task_status_updates",
        payload,
    )


async def check_logged_out(page) -> bool:
    """
    Check if the 'logged out' message is displayed on the page.
    CUB shows: "You are seeing this page"
    """
    try:
        # Check for CUB logout message
        logout_locator = page.get_by_text("You are seeing this page")
        is_visible = await logout_locator.is_visible(timeout=1000)
        return is_visible
    except Exception:
        return False


def process_csv_transactions(csv_path: str, bank_account_id: int) -> list:
    """
    Process CSV file and extract credit transactions.
    Returns a list of ExtractedTransactions objects ready to be saved.
    """
    try:
        # Read CSV file with pipe delimiter
        df = pd.read_csv(
            csv_path,
            engine="python",
            sep="|",
            on_bad_lines="skip"
        )
        logger.info(f"CSV file loaded: {len(df)} rows found")

        # Normalize column names
        df.columns = df.columns.str.lower().str.strip()

        # Filter only CR (credit) transactions
        credit_transactions = df[df["cr"].notna() & (df["cr"].astype(str).str.strip() != "")].copy()
        logger.info(f"Credit transactions found: {len(credit_transactions)}")

        if credit_transactions.empty:
            logger.warning("No credit transactions found in CSV")
            return []

        # Get bank account and merchant
        bank_account = BankAccount.objects.select_related('merchant').get(id=bank_account_id)
        merchant = bank_account.merchant

        transactions = []
        skipped_count = 0

        # Process each transaction
        for index, row in credit_transactions.iterrows():
            try:
                # Get credit amount
                credit_amount = row.get('cr', 0)
                if pd.isna(credit_amount) or str(credit_amount).strip() == "":
                    skipped_count += 1
                    continue

                # Extract UTR from description
                description = str(row.get('description', ''))
                utr = extract_utr_from_description(description)

                if not utr:
                    logger.debug(f"Skipping transaction at row {index}: No UTR found. Description: {description[:50]}")
                    skipped_count += 1
                    continue

                # Clean and validate amount
                try:
                    amount_str = str(credit_amount).replace(",", "")
                    amount = int(float(amount_str))
                    if amount <= 0:
                        skipped_count += 1
                        continue
                except (ValueError, TypeError):
                    logger.warning(f"Invalid amount format at row {index}: {credit_amount}")
                    skipped_count += 1
                    continue

                # Create transaction object
                transactions.append(ExtractedTransactions(
                    bank_account=bank_account,
                    merchant=merchant,
                    amount=amount,
                    utr=utr
                ))

            except Exception as e:
                logger.warning(f"Error processing row {index}: {str(e)}")
                skipped_count += 1
                continue

        logger.info(f"Successfully extracted {len(transactions)} transactions, skipped {skipped_count}")
        return transactions

    except FileNotFoundError:
        logger.error(f"CSV file not found: {csv_path}")
        return []
    except pd.errors.EmptyDataError:
        logger.error("CSV file is empty")
        return []
    except Exception as e:
        logger.error(f"Error processing CSV file: {str(e)}", exc_info=True)
        return []


def extract_utr_from_description(description: str) -> str | None:
    """
    Extract UTR from transaction description.
    Handles both UPI and NEFT formats.
    """
    if not isinstance(description, str):
        return None

    # Pattern 1: For NEFT transactions - UTR:XXXXXXXXXX
    neft_match = re.search(r"UTR:([A-Z0-9]+)", description)
    if neft_match:
        return neft_match.group(1)

    # Pattern 2: For UPI transactions - UPI/CR/XXXXXXXXXXXX
    upi_match = re.search(r"UPI/CR/(\d{12})", description)
    if upi_match:
        return upi_match.group(1)

    return None


async def save_extracted_transactions(transactions: list) -> dict:
    """
    Save extracted transactions to database with duplicate checking.
    Returns a dict with success count and skipped count.
    """
    if not transactions:
        logger.warning("No transactions to save")
        return {"saved": 0, "skipped": 0, "errors": 0}

    try:
        # Check for existing transactions to avoid duplicates
        def check_and_save():
            merchant = transactions[0].merchant
            existing_utrs = set(
                ExtractedTransactions.objects.filter(
                    utr__in=[t.utr for t in transactions],
                    merchant=merchant
                ).values_list('utr', flat=True)
            )

            # Filter out duplicates
            new_transactions = [
                t for t in transactions
                if t.utr not in existing_utrs
            ]

            if not new_transactions:
                logger.info("All transactions already exist in database")
                return {
                    "saved": 0,
                    "skipped": len(transactions),
                    "errors": 0
                }

            # Bulk create new transactions
            ExtractedTransactions.objects.bulk_create(new_transactions, ignore_conflicts=True)

            return {
                "saved": len(new_transactions),
                "skipped": len(transactions) - len(new_transactions),
                "errors": 0
            }

        result = await sync_to_async(check_and_save)()
        logger.info(f"Transactions saved: {result['saved']}, skipped (duplicates): {result['skipped']}")
        return result

    except Exception as e:
        logger.error(f"Error saving transactions to database: {str(e)}", exc_info=True)
        return {"saved": 0, "skipped": 0, "errors": len(transactions)}


async def extract_and_save_transactions(csv_path: str, bank_account_id: int) -> dict:
    """
    Main function to extract transactions from CSV and save to database.
    """
    try:
        # Process CSV in thread pool (pandas is synchronous)
        transactions = await asyncio.to_thread(
            process_csv_transactions,
            csv_path,
            bank_account_id
        )

        if not transactions:
            logger.warning("No transactions extracted from CSV")
            return {"saved": 0, "skipped": 0, "errors": 0, "extracted": 0}

        # Save to database
        result = await save_extracted_transactions(transactions)
        result["extracted"] = len(transactions)

        return result

    except Exception as e:
        logger.error(f"Error in extract_and_save_transactions: {str(e)}", exc_info=True)
        return {"saved": 0, "skipped": 0, "errors": 1, "extracted": 0}


async def verify_transactions(send_status) -> dict:
    """
    Verify pending payins against extracted transactions.
    Called after each statement download.
    """
    from core.bot.verification import verify_transactions_async
    return await verify_transactions_async(None)


async def perform_login(page, login_page, bank_account, send_status, bank_account_id: int) -> bool:
    """
    Perform login to CUB netbanking.
    Returns True if login successful, False otherwise.
    """
    try:
        # Get login credentials
        username = bank_account.username or ''
        password = bank_account.password or ''

        await send_status('running', 'Filling login credentials')
        await login_page.wait_for_selector("#uid", state="visible", timeout=10000)
        await login_page.locator("#uid").fill(username)
        logger.info('Username filled')

        await asyncio.sleep(2)
        await check_stop_and_raise(bank_account_id, send_status)

        await login_page.get_by_role("button", name="Continue").click()
        await login_page.wait_for_load_state("networkidle")
        logger.info('Continue button clicked')

        await send_status('running', 'Filling password')
        await login_page.evaluate("""
        (password) => {
            const el = document.querySelector('#passInput');
            el.value = password;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }
        """, password)
        logger.info('Password filled')

        await asyncio.sleep(2)
        await check_stop_and_raise(bank_account_id, send_status)

        # Handle MFA checkbox
        await send_status('running', 'Handling MFA checkbox')
        await login_page.wait_for_selector("#MFACheckBox", timeout=10000)
        await login_page.locator("#MFACheckBox").check(force=True)
        is_checked = await login_page.locator("#MFACheckBox").is_checked()
        logger.info(f'MFA checkbox checked: {is_checked}')

        await asyncio.sleep(2)
        await check_stop_and_raise(bank_account_id, send_status)

        await send_status('running', 'Submitting login')
        await login_page.locator("#continueBtn").click()
        await login_page.wait_for_load_state("networkidle")
        logger.info('Login submitted')

        await send_status('running', 'Login successful')
        return True

    except Exception as e:
        logger.error(f"Login failed: {str(e)}", exc_info=True)
        await send_status('error', f'Login failed: {str(e)}')
        return False


async def download_statement(login_page, bank_account_id: int, send_status) -> dict:
    """
    Download and process statement. This is called in a loop.
    Returns the result of transaction extraction.
    """
    try:
        await send_status('running', 'Navigating to account statement')

        # Navigate to transaction history
        nav_frame = login_page.frame_locator("#nav")
        
        # Check if Transaction History link is already visible (optimization for subsequent iterations)
        transaction_history_link = nav_frame.get_by_role("link", name="Transaction History")
        try:
            # Try to check if it's visible with a short timeout
            await transaction_history_link.wait_for(state="visible", timeout=2000)
            logger.info('Transaction History link already visible, clicking directly')
            await transaction_history_link.click()
        except Exception:
            # Not visible yet, need to navigate through menu
            logger.info('Navigating through Accounts menu to Transaction History')
            await nav_frame.get_by_role("link", name="Accounts").click()
            await asyncio.sleep(2)
            await check_stop_and_raise(bank_account_id, send_status)
            
            try:
                await nav_frame.get_by_role("link", name="Account Statement").click()
                await asyncio.sleep(2)
                await check_stop_and_raise(bank_account_id, send_status)
            except Exception as e:
                # Retry if first attempt fails
                await nav_frame.get_by_role("link", name="Accounts").click()
                await nav_frame.get_by_role("link", name="Account Statement").click()
                await asyncio.sleep(2)
                await check_stop_and_raise(bank_account_id, send_status)
            
            await nav_frame.get_by_role("link", name="Transaction History").click()
        
        await asyncio.sleep(2)
        logger.info('Navigated to transaction history')

        # Select account
        await send_status('running', 'Selecting account')
        folder_frame_locator = login_page.frame_locator("iframe[name=\"folderFrame\"]")
        await folder_frame_locator.get_by_role("cell", name="Account Select Select").get_by_role("button").click()
        await asyncio.sleep(2)
        await check_stop_and_raise(bank_account_id, send_status)

        await folder_frame_locator.get_by_role("listitem").first.click()
        await asyncio.sleep(2)
        logger.info('Account selected')

        # Select period
        await send_status('running', 'Setting date range')
        await folder_frame_locator.get_by_role("button", name="Select from List").click()
        await asyncio.sleep(2)
        await folder_frame_locator.get_by_role("listitem").filter(has_text="Select Period").click()
        await asyncio.sleep(2)

        # Set dates
        yesterday_date = (datetime.now() - timedelta(days=1)).strftime("%d/%m/%Y")
        today_date = datetime.now().strftime("%d/%m/%Y")
        from_date_locator = folder_frame_locator.get_by_role("textbox", name="Select From Date")
        await from_date_locator.wait_for()
        await from_date_locator.evaluate("""
            (input, date) => {
                input.removeAttribute('readonly');
                input.value = date;
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
                input.dispatchEvent(new Event('blur', { bubbles: true }));
            }
        """, yesterday_date)

        await asyncio.sleep(2)
        to_date_locator = folder_frame_locator.get_by_role("textbox", name="Select To Date")
        await to_date_locator.wait_for()
        await to_date_locator.evaluate("""
            (input, date) => {
                input.removeAttribute('readonly');
                input.value = date;
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
                input.dispatchEvent(new Event('blur', { bubbles: true }));
            }
        """, today_date)
        logger.info(f'Date range set to {yesterday_date} - {today_date}')

        await asyncio.sleep(2)
        await check_stop_and_raise(bank_account_id, send_status)

        # Select CSV format and download
        await send_status('running', 'Downloading statement')
        await folder_frame_locator.get_by_role("button", name="Select", exact=True).click()
        await folder_frame_locator.get_by_role("listitem").filter(has_text="Csv").click()
        await folder_frame_locator.get_by_role("button", name="Download").click()

        # Intercept download
        async with login_page.expect_download() as download_info:
            await folder_frame_locator.get_by_role("button", name="Yes").click()

        download = await download_info.value
        logger.info('CSV download initiated')

        # Save the file
        csv_path = os.path.join(BOT_DIR, f"statement_{bank_account_id}.csv")
        await download.save_as(csv_path)
        await send_status('running', 'CSV file saved')
        logger.info(f"CSV file saved as {csv_path}")

        # Extract and save transactions from CSV
        result = await extract_and_save_transactions(csv_path, bank_account_id)
        logger.info(
            f"Transaction processing completed for bank account {bank_account_id} - "
            f"Extracted: {result.get('extracted', 0)}, "
            f"Saved: {result.get('saved', 0)}, "
            f"Skipped: {result.get('skipped', 0)}, "
            f"Errors: {result.get('errors', 0)}"
        )
        await send_status('running', f"Processed: {result.get('saved', 0)} new transactions")

        return result

    except BotStoppedException:
        raise
    except Exception as e:
        logger.error(f"Error downloading statement: {str(e)}", exc_info=True)
        await send_status('error', f'Error downloading statement: {str(e)}')
        return {"saved": 0, "skipped": 0, "errors": 1, "extracted": 0}


async def attempt_relogin(page, bank_account, send_status, bank_account_id: int, netbanking_url: str, login_page=None) -> tuple:
    """
    Attempt to re-login after logout detection.
    Max 5 attempts with 3 second delay between each.
    Returns (success: bool, login_page: Page | None)
    """
    for attempt in range(1, MAX_RELOGIN_ATTEMPTS + 1):
        await send_status('running', f'Re-login attempt {attempt}/{MAX_RELOGIN_ATTEMPTS}...')
        logger.info(f"Re-login attempt {attempt}/{MAX_RELOGIN_ATTEMPTS} for bank account {bank_account_id}")

        await asyncio.sleep(RELOGIN_DELAY_SECONDS)
        await check_stop_and_raise(bank_account_id, send_status)

        try:
            # If login_page exists and has logout popup, close it first
            if login_page:
                try:
                    close_button = login_page.get_by_text("Click here to Close Window")
                    if await close_button.is_visible(timeout=2000):
                        logger.info('Logout popup detected, clicking close button')
                        await close_button.click()
                        await asyncio.sleep(2)
                        # Close the login_page popup
                        await login_page.close()
                        logger.info('Logout popup closed')
                except Exception as e:
                    logger.debug(f'No logout popup to close: {e}')

            # Navigate to login page fresh
            await page.goto(netbanking_url, wait_until='networkidle', timeout=60000)
            logger.info('Login page loaded for re-login')
        except Exception as e:
            logger.warning(f'Navigation error during re-login: {e}')
            try:
                await page.goto(netbanking_url, wait_until='domcontentloaded', timeout=60000)
                await asyncio.sleep(3)
            except Exception:
                continue

        # Click Personal link and get popup
        try:
            async with page.expect_popup() as popup:
                await page.get_by_role("link", name="Personal").click()
            login_page = await popup.value
            await login_page.wait_for_load_state("networkidle")

            # Attempt login
            if await perform_login(page, login_page, bank_account, send_status, bank_account_id):
                await send_status('running', 'Re-login successful! Restarting monitoring...')
                logger.info(f"Re-login successful for bank account {bank_account_id}")
                return True, login_page
        except Exception as e:
            logger.warning(f"Re-login attempt {attempt} failed: {str(e)}")
            continue

    await send_status('error', f'Re-login failed after {MAX_RELOGIN_ATTEMPTS} attempts. Stopping bot.')
    logger.error(f"Re-login failed after {MAX_RELOGIN_ATTEMPTS} attempts for bank account {bank_account_id}")
    return False, None


async def run_bot_for_account(bank_account_id: int):
    """
    Run bot for a specific bank account with persistent browser session.
    - Login once
    - Loop: download statement -> process -> verify -> wait
    - Only logout and close browser when stopped
    """
    browser = None
    page = None
    login_page = None

    try:
        # Get bank account details
        bank_account = await sync_to_async(BankAccount.objects.get)(id=bank_account_id)
        merchant_id = bank_account.merchant_id

        # Shadow global send_status to include merchant_id and bank_account_id
        _send_status = send_status_to_websocket
        async def send_status(status, message=""):
            await _send_status(status, message, merchant_id, bank_account_id)

        await send_status('running', "Starting bot for bank account")
        logger.info(f"Starting bot for bank account: {bank_account.nickname} (ID: {bank_account_id})")

        # Check stop flag before starting
        await check_stop_and_raise(bank_account_id, send_status)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--disable-accelerated-2d-canvas",
                    "--disable-webgl",
                    "--disable-webgl2",
                    "--disable-features=VizDisplayCompositor",
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-zygote",
                    "--window-size=1920,1080",
                    "--disable-features=DownloadBubble,DownloadBubbleV2"
                ]
            )

            try:
                # Create context
                context = await browser.new_context(
                    viewport={"width": 1500, "height": 1080},
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    ignore_https_errors=True,
                    accept_downloads=True,
                )

                page = await context.new_page()

                # Hide automation indicators
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => false
                    });
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5]
                    });
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['en-US', 'en']
                    });
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ?
                            Promise.resolve({ state: Notification.permission }) :
                            originalQuery(parameters)
                    );
                """)

                # ============ LOGIN PHASE (runs once) ============
                netbanking_url = bank_account.netbanking_url or 'https://www.onlinebanking.cub.bank.in/servlet/ibs.servlets.IBSLoginServlet#4'
                await send_status('running', 'Navigating to login page')

                try:
                    await page.goto(netbanking_url, wait_until='networkidle', timeout=60000)
                    logger.info('Page loaded successfully')
                    await send_status('running', 'Page loaded successfully')
                except Exception as e:
                    logger.warning(f'Navigation error: {e}')
                    await page.goto(netbanking_url, wait_until='domcontentloaded', timeout=60000)
                    await asyncio.sleep(3)

                await check_stop_and_raise(bank_account_id, send_status)

                # Click Personal link and get popup
                await send_status('running', 'Opening login popup')
                async with page.expect_popup() as popup:
                    await page.get_by_role("link", name="Personal").click()

                login_page = await popup.value
                await login_page.wait_for_load_state("networkidle")
                logger.info('Login popup opened')

                # Perform login
                login_successful = await perform_login(page, login_page, bank_account, send_status, bank_account_id)

                if not login_successful:
                    logger.error('Login failed')
                    await send_status('error', 'Login failed')
                    raise Exception('Login failed')

                await send_status('running', 'Login successful! Starting continuous monitoring...')
                logger.info(f'Login successful for bank account {bank_account_id}. Starting continuous monitoring...')

                # ============ MAIN LOOP (runs until stopped) ============
                iteration = 0
                while True:
                    iteration += 1
                    logger.info(f"=== Iteration {iteration} for bank account {bank_account_id} ===")
                    await send_status('running', f'Iteration {iteration}: Checking status...')

                    # Check stop flag at start of each iteration
                    await check_stop_and_raise(bank_account_id, send_status)

                    # Check for logout condition BEFORE processing
                    if await check_logged_out(login_page):
                        logger.warning(f"Logout detected for bank account {bank_account_id}")
                        await send_status('running', 'Session logged out detected. Attempting re-login...')

                        success, new_login_page = await attempt_relogin(page, bank_account, send_status, bank_account_id, netbanking_url, login_page)
                        if not success:
                            raise Exception("Re-login failed after maximum attempts")

                        login_page = new_login_page
                        iteration = 0
                        logger.info(f"Re-login successful for bank account {bank_account_id}. Restarting monitoring fresh.")
                        continue

                    await send_status('running', f'Iteration {iteration}: Downloading statement...')

                    try:
                        # Download and process statement
                        result = await download_statement(login_page, bank_account_id, send_status)
                        logger.info(f"Iteration {iteration} statement download completed: {result}")

                        # Verify transactions after each download
                        await check_stop_and_raise(bank_account_id, send_status)
                        verify_result = await verify_transactions(send_status)
                        logger.info(f"Iteration {iteration} verification completed: {verify_result}")

                    except BotStoppedException:
                        raise
                    except Exception as e:
                        logger.error(f"Error in iteration {iteration}: {str(e)}")
                        await send_status('error', f'Iteration {iteration} error: {str(e)}')

                        # Check if this error is due to logout
                        if await check_logged_out(login_page):
                            logger.warning(f"Error appears to be due to logout for bank account {bank_account_id}")
                            await send_status('running', 'Error due to session logout. Attempting re-login...')

                            success, new_login_page = await attempt_relogin(page, bank_account, send_status, bank_account_id, netbanking_url, login_page)
                            if not success:
                                raise Exception("Re-login failed after maximum attempts")

                            login_page = new_login_page
                            iteration = 0
                            logger.info(f"Re-login successful for bank account {bank_account_id}. Restarting monitoring fresh.")
                            continue

                    # Check stop flag before waiting
                    await check_stop_and_raise(bank_account_id, send_status)

                    # Wait for interval, checking stop flag every 2 seconds
                    await send_status('running', f'Waiting {BOT_INTERVAL}s before next iteration...')
                    logger.info(f"Waiting {BOT_INTERVAL} seconds before next iteration...")

                    wait_elapsed = 0
                    while wait_elapsed < BOT_INTERVAL:
                        await asyncio.sleep(2)
                        wait_elapsed += 2

                        # Check stop flag during wait
                        if check_stop_flag(bank_account_id):
                            logger.info(f"Stop flag detected during wait for account {bank_account_id}")
                            await send_status('stopped', 'Bot stopped by user request')
                            raise BotStoppedException(f"Bot stopped during wait for account {bank_account_id}")

            except BotStoppedException:
                logger.info(f"Bot stopped by user for bank account {bank_account_id}")
                # Try to logout gracefully
                try:
                    if login_page:
                        await send_status('running', 'Logging out...')
                        right_frame = login_page.frame_locator("#rightFrame")
                        await right_frame.get_by_role("link", name="Logout").click()
                        logger.info('Logout button clicked')
                        await asyncio.sleep(2)
                except Exception as logout_err:
                    logger.warning(f"Could not logout gracefully: {logout_err}")

                await send_status('stopped', 'Bot stopped successfully')
                raise

            except Exception as e:
                logger.error(f"Bot execution failed for bank account {bank_account_id}: {str(e)}", exc_info=True)
                await send_status('error', f'Bot failed: {str(e)}')
                raise

            finally:
                # Close browser
                if browser:
                    try:
                        await browser.close()
                        logger.info('Browser closed')
                    except Exception as e:
                        logger.warning(f"Error closing browser: {str(e)}")

    except BotStoppedException:
        raise
    except Exception as e:
        logger.error(f"Failed to run bot for bank account {bank_account_id}: {str(e)}", exc_info=True)
        raise
