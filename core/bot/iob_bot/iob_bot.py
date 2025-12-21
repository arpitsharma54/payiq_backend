import asyncio
import logging
import re
from datetime import datetime, timedelta
import pandas as pd
from deposit.models import Payin
from playwright.async_api import async_playwright
import base64
import easyocr
from merchants.models import BankAccount, ExtractedTransactions
from asgiref.sync import sync_to_async
logger = logging.getLogger(__name__)
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from channels.layers import get_channel_layer
import redis
import os

# Get the directory where this bot file is located
BOT_DIR = os.path.dirname(os.path.abspath(__file__))

# Initialize once per Celery worker
OCR_MODEL = easyocr.Reader(['en'], gpu=False)

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


async def check_logged_out(page) -> bool:
    """
    Check if the 'logged out' or 'login denied' message is displayed on the page.
    These messages indicate the session is invalid and requires re-login.
    """

    try:
        text = await page.inner_text("body")
        logout_messages = [
            "You are Logged OUT of internet banking due to",
            "Login Denied",
            "Your are NOT allowed to login due to"
    ]
        return any(msg in text for msg in logout_messages)
    except Exception:
        return False



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


def extract_utr_from_text(text: str) -> str | None:
    """
    Extract UTR from transaction text.
    UTR patterns: 4-6 uppercase letters followed by 8-16 digits, or 10-16 digits
    """
    if not text or not isinstance(text, str):
        return None

    # Try multiple UTR patterns
    patterns = [
        r'\b([A-Z]{4,6}\d{8,16})\b',  # UPI reference like IMPS123456789012
        r'\b(\d{10,16})\b',  # Numeric UTR like 123456789012
        r'UPI/(\d{12})',  # UPI format like UPI/531500483153
        r'IMPS/(\d{12})',  # IMPS format
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            utr = match.group(1)
            # Validate UTR length
            if 10 <= len(utr) <= 16:
                return utr

    return None


def process_csv_transactions(csv_path: str, bank_account_id: int) -> list:
    """
    Process CSV file and extract credit transactions.
    Returns a list of ExtractedTransactions objects ready to be saved.
    """
    try:
        # Read CSV file
        df = pd.read_csv(csv_path)
        logger.info(f"CSV file loaded: {len(df)} rows found")

        # Filter rows where Debit is NaN (credit transactions only)
        credit_transactions = df[df['Debit'].isna()].copy()
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
                credit_amount = row.get('Credit', 0)
                if pd.isna(credit_amount) or credit_amount <= 0:
                    skipped_count += 1
                    continue

                # Extract UTR from Narration column (most likely to contain UTR)
                narration = str(row.get('Narration', ''))
                utr = extract_utr_from_text(narration)

                if not utr:
                    # Try other columns if Narration doesn't have UTR
                    description = str(row.get('Description', ''))
                    remarks = str(row.get('Remarks', ''))
                    combined_text = f"{description} {remarks} {narration}"
                    utr = extract_utr_from_text(combined_text)

                if not utr:
                    logger.debug(f"Skipping transaction at row {index}: No UTR found. Narration: {narration[:50]}")
                    skipped_count += 1
                    continue

                # Validate amount
                try:
                    amount = int(float(credit_amount))
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


async def save_extracted_transactions(transactions: list) -> dict:
    """
    Save extracted transactions to database with duplicate checking.
    Returns a dict with success count and skipped count.
    """
    if not transactions:
        logger.warning("No transactions to save")
        return {"saved": 0, "skipped": 0, "errors": 0}

    try:
        # Check for existing transactions to avoid duplicates (within the same merchant)
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
    Handles the entire process with proper error handling.
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
    await send_status('running', 'Verifying transactions...')
    logger.info("Starting transaction verification...")

    try:
        def do_verification():
            assigned_payins = Payin.objects.filter(status='assigned')
            expired_initiated_payins = Payin.objects.filter(status='initiated', created_at__lte=timezone.now() - timedelta(minutes=11))
            logger.info(f"Found {assigned_payins.count()} assigned payins to verify")
            logger.info(f"Found {expired_initiated_payins.count()} expired initiated payins to verify")

            for expired_initiated_payin in expired_initiated_payins:
                expired_initiated_payin.status = 'dropped'
                expired_initiated_payin.save()

            verified_count = 0
            duplicate_count = 0
            dropped_count = 0
            not_found_count = 0
            error_count = 0

            for payin in assigned_payins:
                try:
                    with transaction.atomic():
                        payin = Payin.objects.select_for_update().get(id=payin.id)

                        if not payin.user_submitted_utr or payin.user_submitted_utr == '-':
                            logger.debug(f"Payin {payin.id}: No UTR submitted, skipping")
                            not_found_count += 1
                            continue

                        transaction_obj = ExtractedTransactions.objects.filter(
                            utr=payin.user_submitted_utr,
                            merchant_id=payin.merchant_id
                        ).first()

                        if not transaction_obj:
                            logger.debug(f"Payin {payin.id}: No matching transaction found for UTR {payin.user_submitted_utr}")
                            not_found_count += 1
                            continue

                        logger.debug(f"Payin {payin.id}: Found transaction {transaction_obj.id} with UTR {transaction_obj.utr}")

                        if transaction_obj.is_used:
                            logger.warning(
                                f"Payin {payin.id}: Transaction {transaction_obj.id} (UTR: {transaction_obj.utr}) "
                                f"is already used. Marking payin as duplicate."
                            )
                            payin.status = 'duplicate'
                            if hasattr(payin, 'assigned_at') and payin.assigned_at:
                                payin.duration = timezone.now() - payin.assigned_at
                            payin.save(update_fields=['status', 'duration'])
                            duplicate_count += 1

                        elif transaction_obj.amount != int(float(payin.pay_amount or 0)):
                            logger.warning(
                                f"Payin {payin.id}: Amount mismatch. "
                                f"Payin amount: {payin.pay_amount}, Transaction amount: {transaction_obj.amount}. "
                                f"Marking payin as dropped."
                            )
                            payin.status = 'dropped'
                            payin.amount = transaction_obj.amount
                            if hasattr(payin, 'assigned_at') and payin.assigned_at:
                                payin.duration = timezone.now() - payin.assigned_at
                            payin.save(update_fields=['status', 'duration', 'amount'])
                            dropped_count += 1

                        else:
                            logger.info(
                                f"Payin {payin.id}: Transaction {transaction_obj.id} is valid. "
                                f"Amount: {transaction_obj.amount}, UTR: {transaction_obj.utr}"
                            )

                            transaction_obj.is_used = True
                            transaction_obj.save(update_fields=['is_used'])

                            payin.status = 'success'
                            payin.confirmed_amount = payin.pay_amount
                            payin.utr = transaction_obj.utr

                            if hasattr(payin, 'assigned_at') and payin.assigned_at:
                                payin.duration = timezone.now() - payin.assigned_at

                            payin.save(update_fields=['status', 'confirmed_amount', 'duration', 'utr'])
                            verified_count += 1

                except Payin.DoesNotExist:
                    logger.warning(f"Payin {payin.id} no longer exists, skipping")
                    error_count += 1
                    continue
                except Exception as e:
                    logger.error(f"Error verifying payin {payin.id}: {str(e)}", exc_info=True)
                    error_count += 1
                    continue
            
            expired_assigned_payins = Payin.objects.filter(status='assigned', created_at__lte=timezone.now() - timedelta(minutes=11))
            logger.info(f"Found {expired_assigned_payins.count()} expired assigned payins to verify")
            for expired_assigned_payin in expired_assigned_payins:
                expired_assigned_payin.status = 'dropped'
                expired_assigned_payin.save()
            logger.info(f"Dropped {expired_assigned_payins.count()} expired assigned payins")
            return {
                "verified": verified_count,
                "duplicates": duplicate_count,
                "dropped": dropped_count,
                "not_found": not_found_count,
                "errors": error_count,
                "total": assigned_payins.count()
            }

        result = await sync_to_async(do_verification)()

        logger.info(
            f"Transaction verification completed - "
            f"Verified: {result['verified']}, "
            f"Duplicates: {result['duplicates']}, "
            f"Dropped: {result['dropped']}, "
            f"Not found: {result['not_found']}, "
            f"Errors: {result['errors']}"
        )

        await send_status('running', f"Verified: {result['verified']} transactions")
        return result

    except Exception as e:
        logger.error(f"Error in transaction verification: {str(e)}", exc_info=True)
        await send_status('error', f'Verification error: {str(e)}')
        return {"verified": 0, "duplicates": 0, "dropped": 0, "not_found": 0, "errors": 1, "total": 0}


async def download_statement(page, bank_account_id: int, send_status) -> dict:
    """
    Download and process statement. This is called in a loop.
    Returns the result of transaction extraction.
    """
    try:
        # Navigate to Account statement page
        await send_status('running', 'Navigating to account statement')

        # Click on Account statement with retry logic
        max_retries = 3
        retry_count = 0
        account_statement_clicked = False

        while retry_count < max_retries and not account_statement_clicked:
            # Check stop flag at start of each retry
            await check_stop_and_raise(bank_account_id, send_status)
            try:
                # Try multiple selectors for Account statement
                selectors = [
                    "xpath=//a[contains(., 'Account statement')]",
                    "xpath=//a[contains(., 'Account Statement')]",
                    "xpath=//a[contains(., 'account statement')]",
                    "xpath=//a[contains(@href, 'account') or contains(@href, 'statement')]",
                ]

                for selector in selectors:
                    try:
                        button = page.locator(selector)
                        await button.wait_for(state="visible", timeout=10000)
                        await button.click()
                        logger.info(f'Account statement menu clicked using selector: {selector}')
                        await send_status('running', 'Account statement menu clicked')
                        account_statement_clicked = True
                        break
                    except Exception:
                        continue

                if not account_statement_clicked:
                    raise Exception("Account statement link not found with any selector")

            except Exception as e:
                retry_count += 1
                if retry_count < max_retries:
                    logger.warning(f"Attempt {retry_count} failed to click Account statement: {str(e)}. Retrying...")
                    await asyncio.sleep(2)
                    await page.reload()
                    await asyncio.sleep(3)
                else:
                    logger.error(f"Failed to click Account statement after {max_retries} attempts: {str(e)}")
                    raise

        await asyncio.sleep(5)

        # Select account
        await page.evaluate("""
            const sel = document.querySelector('#accountNo');
            sel.selectedIndex = 1;
        """)
        logger.info('Account number selected')
        await send_status('running', 'Account number selected')

        # Set from date (today's date)
        from datetime import datetime
        today = datetime.now().strftime('%m/%d/%Y')

        await page.evaluate(f"""() => {{
            const el = document.querySelector('#fromDate');
            el.removeAttribute('readonly');
            el.value = '{today}';
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }}""")
        logger.info(f'From date set to {today}')
        await send_status('running', f'From date set to {today}')

        # Set to date
        await page.evaluate(f"""() => {{
            const el = document.querySelector('#toDate');
            el.removeAttribute('readonly');
            el.value = '{today}';
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }}""")
        logger.info(f'To date set to {today}')
        await send_status('running', f'To date set to {today}')

        # Check stop flag before downloading statement
        await check_stop_and_raise(bank_account_id, send_status)
        # Click view button
        await page.evaluate("() => { document.getElementById('accountstatement_view').click(); }")
        await send_status('running', 'Clicking view button')
        await asyncio.sleep(5)

        # Check if there's no data to display - skip download and proceed to verification
        no_data_locator = page.locator("strong:has-text('Nothing found to display')")
        no_data_count = await no_data_locator.count()
        if no_data_count > 0:
            logger.info("No transactions found to display, skipping CSV download")
            await send_status('running', 'No transactions found, proceeding to verification')
            return {"saved": 0, "skipped": 0, "errors": 0, "extracted": 0}

        # Wait for the CSV download button to be ready
        csv_button = page.locator("#accountstatement_csvAcctStmt")
        await csv_button.wait_for(state="visible", timeout=10000)

        # Intercept download BEFORE clicking
        async with page.expect_download() as download_info:
            await csv_button.click()
            logger.info('CSV download button clicked')

        # Get the intercepted download
        download = await download_info.value
        await send_status('running', 'CSV button clicked')

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


async def perform_login(page, bank_account, send_status, bank_account_id: int) -> bool:
    """
    Perform login with captcha retry logic.
    Returns True if login successful, False otherwise.
    """
    # Get login credentials
    username = bank_account.username or ''
    username2 = bank_account.username2 or ''
    password = bank_account.password or ''

    # Captcha retry loop
    max_captcha_retries = 10
    captcha_attempt = 0
    login_successful = False

    while captcha_attempt < max_captcha_retries and not login_successful:
        await check_stop_and_raise(bank_account_id, send_status)

        captcha_attempt += 1
        logger.info(f'Captcha attempt {captcha_attempt}/{max_captcha_retries}')
        await send_status('running', f'Captcha attempt {captcha_attempt}/{max_captcha_retries}')

        try:
            await page.wait_for_load_state('domcontentloaded', timeout=10000)
            await page.wait_for_selector('#captchaimg', state='visible', timeout=10000)
            await page.wait_for_selector('#password', state='visible', timeout=5000)
        except Exception as e:
            logger.warning(f'Timeout waiting for form elements: {str(e)}')
            await asyncio.sleep(2)

        # Fill login credentials
        try:
            if bank_account.login_type == 'corp':
                await page.locator('#loginsubmit_loginId').fill(username)
                await page.locator('#loginsubmit_userId').fill(username2)
            else:
                await page.locator('#loginsubmit_loginId').fill(username)

            await page.locator('#password').fill(password)
            logger.info('Credentials filled successfully')
        except Exception as e:
            logger.warning(f'Error filling credentials: {str(e)}')
            await asyncio.sleep(1)
            continue

        # Extract and process captcha
        await send_status('running', 'Getting captcha image')
        try:
            src = await page.evaluate('document.getElementById("captchaimg").src')
        except Exception as e:
            logger.warning(f'Error getting captcha image: {str(e)}')
            await asyncio.sleep(1)
            continue

        img_bytes = base64.b64decode(src.replace('data:image/png;base64,', ''))
        img_path = os.path.join(BOT_DIR, f"decoded_image_{bank_account_id}.png")
        with open(img_path, "wb") as f:
            f.write(img_bytes)

        await send_status('running', 'Extracting captcha text')
        result = OCR_MODEL.readtext(img_path)
        text = ''.join([detection[1] for detection in result])
        cleaned_text = text.replace(" ", "")

        if len(cleaned_text) < 6:
            cleaned_text = cleaned_text + "f" * (6 - len(cleaned_text))

        # Fill captcha and submit
        try:
            captcha_input = page.locator('#loginsubmit_captchaid')
            await captcha_input.clear()
            await captcha_input.fill(cleaned_text.upper())
            await send_status('running', 'Filling captcha')
            await asyncio.sleep(4)

            await page.locator('#btnSubmit').click()
            logger.info('Login button clicked')
            await send_status('running', 'Clicking login button')
        except Exception as e:
            logger.warning(f'Error submitting form: {str(e)}')
            await asyncio.sleep(1)
            continue

        # Wait for navigation
        try:
            await send_status('running', 'Waiting for login to complete')
            await page.wait_for_load_state('networkidle', timeout=20000)
        except Exception as e:
            logger.warning(f"Timeout waiting for page load: {str(e)}")

        await asyncio.sleep(1)

        # Check for captcha error
        current_url = page.url
        if 'Captcha+entered+is+Incorrect' in current_url or 'errmsg=Captcha' in current_url:
            logger.warning(f'Captcha incorrect on attempt {captcha_attempt}')
            await send_status('running', f'Captcha incorrect, retrying ({captcha_attempt}/{max_captcha_retries})')
            try:
                await page.wait_for_load_state('domcontentloaded', timeout=10000)
                await page.wait_for_selector('#captchaimg', state='visible', timeout=10000)
            except Exception:
                await asyncio.sleep(2)
            continue

        # Check if login was successful
        if 'corplogin' not in current_url:
            logger.info('Login successful - no longer on login page')
            login_successful = True
            break

        try:
            await page.wait_for_selector("xpath=//a[contains(., 'Account statement')]", timeout=10000, state="visible")
            logger.info('Login completed, Account statement link found')
            await send_status('running', 'Login completed')
            login_successful = True
            break
        except Exception:
            if 'corplogin' in page.url:
                logger.warning(f'Still on login page after attempt {captcha_attempt}')
                try:
                    await page.wait_for_selector('#captchaimg', state='visible', timeout=10000)
                except Exception:
                    await asyncio.sleep(2)
                continue

    return login_successful


async def attempt_relogin(page, bank_account, send_status, bank_account_id: int, netbanking_url: str) -> bool:
    """
    Attempt to re-login after logout detection.
    Max 5 attempts with 3 second delay between each.
    Returns True if successful, False if all attempts fail.
    """
    for attempt in range(1, MAX_RELOGIN_ATTEMPTS + 1):
        await send_status('running', f'Re-login attempt {attempt}/{MAX_RELOGIN_ATTEMPTS}...')
        logger.info(f"Re-login attempt {attempt}/{MAX_RELOGIN_ATTEMPTS} for bank account {bank_account_id}")

        await asyncio.sleep(RELOGIN_DELAY_SECONDS)

        # Check stop flag
        await check_stop_and_raise(bank_account_id, send_status)

        # Navigate to login page fresh
        try:
            await page.goto(netbanking_url, wait_until='networkidle', timeout=60000)
            logger.info('Login page loaded for re-login')
            await send_status('running', 'Login page loaded')
        except Exception as e:
            logger.warning(f'Navigation error during re-login: {e}')
            try:
                await page.goto(netbanking_url, wait_until='domcontentloaded', timeout=60000)
                await asyncio.sleep(3)
            except Exception:
                continue

        # Attempt login
        if await perform_login(page, bank_account, send_status, bank_account_id):
            await send_status('running', 'Re-login successful! Restarting monitoring...')
            logger.info(f"Re-login successful for bank account {bank_account_id}")
            return True

        logger.warning(f"Re-login attempt {attempt} failed for bank account {bank_account_id}")

    await send_status('error', f'Re-login failed after {MAX_RELOGIN_ATTEMPTS} attempts. Stopping bot.')
    logger.error(f"Re-login failed after {MAX_RELOGIN_ATTEMPTS} attempts for bank account {bank_account_id}")
    return False


async def run_bot_for_account(bank_account_id: int):
    """
    Run bot for a specific bank account with persistent browser session.
    - Login once
    - Loop: download statement -> process -> wait
    - Only logout and close browser when stopped
    """
    browser = None
    page = None

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
                # Create a new context with realistic settings
                context = await browser.new_context(
                    viewport={"width": 1920, "height": 1080},
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
                netbanking_url = bank_account.netbanking_url
                await send_status('running', 'Navigating to login page')

                try:
                    await page.goto(netbanking_url, wait_until='networkidle', timeout=60000)
                    logger.info('Page loaded successfully')
                    await send_status('running', 'Page loaded successfully')
                except Exception as e:
                    logger.warning(f'Navigation error: {e}')
                    await page.goto(netbanking_url, wait_until='domcontentloaded', timeout=60000)
                    await asyncio.sleep(3)

                # Check stop flag after navigation
                await check_stop_and_raise(bank_account_id, send_status)

                # Perform login using the reusable function
                login_successful = await perform_login(page, bank_account, send_status, bank_account_id)

                if not login_successful:
                    logger.error('Login failed after maximum captcha attempts')
                    await send_status('error', 'Login failed after maximum captcha attempts')
                    await page.screenshot(path=os.path.join(BOT_DIR, f'login_failed_{bank_account_id}.png'))
                    raise Exception('Login failed after maximum captcha attempts')

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
                    if await check_logged_out(page):
                        logger.warning(f"Logout detected for bank account {bank_account_id}")
                        await send_status('running', 'Session logged out detected. Attempting re-login...')

                        if not await attempt_relogin(page, bank_account, send_status, bank_account_id, netbanking_url):
                            raise Exception("Re-login failed after maximum attempts")

                        # Reset iteration count after successful relogin (fresh start)
                        iteration = 0
                        logger.info(f"Re-login successful for bank account {bank_account_id}. Restarting monitoring fresh.")
                        continue

                    await send_status('running', f'Iteration {iteration}: Downloading statement...')

                    try:
                        # Download and process statement
                        result = await download_statement(page, bank_account_id, send_status)
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
                        if await check_logged_out(page):
                            logger.warning(f"Error appears to be due to logout for bank account {bank_account_id}")
                            await send_status('running', 'Error due to session logout. Attempting re-login...')

                            if not await attempt_relogin(page, bank_account, send_status, bank_account_id, netbanking_url):
                                raise Exception("Re-login failed after maximum attempts")

                            # Reset iteration count after successful relogin (fresh start)
                            iteration = 0
                            logger.info(f"Re-login successful for bank account {bank_account_id}. Restarting monitoring fresh.")
                            continue
                        # Continue to next iteration even on other errors

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
                    await send_status('running', 'Logging out...')
                    logout_button = page.locator("xpath=//a[contains(., 'Logout')]")
                    await logout_button.click(timeout=5000)
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


async def main():
    """
    Main function that runs bot for all enabled bank accounts.
    """
    try:
        # Get all enabled bank accounts
        enabled_accounts = await sync_to_async(list)(
            BankAccount.objects.filter(is_enabled=True, deleted_at=None).values_list('id', flat=True)
        )

        if not enabled_accounts:
            logger.info("No enabled bank accounts found. Bot will not run.")
            return

        logger.info(f"Found {len(enabled_accounts)} enabled bank account(s). Starting bot execution...")

        # Run bot for each enabled bank account
        for bank_account_id in enabled_accounts:
            try:
                await run_bot_for_account(bank_account_id)
                logger.info(f"Successfully completed bot execution for bank account {bank_account_id}")
            except Exception as e:
                logger.error(f"Failed to run bot for bank account {bank_account_id}: {str(e)}", exc_info=True)
                continue

        logger.info("Bot execution completed for all enabled bank accounts")
    except Exception as e:
        logger.error(f"Failed to get enabled bank accounts: {str(e)}", exc_info=True)
        raise


def run_async(func, *args, **kwargs):
    return asyncio.run(func(*args, **kwargs))


def run_bot():
    try:
        print("Running bot...")
        run_async(main)
        print("Verifying transactions...")
        logger.info("Starting transaction verification...")
        assigned_payins = Payin.objects.filter(status='assigned')
        logger.info(f"Found {assigned_payins.count()} assigned payins to verify")

        verified_count = 0
        duplicate_count = 0
        dropped_count = 0
        not_found_count = 0
        error_count = 0
        for payin in assigned_payins:
            merchant_id = payin.merchant_id
            _send_status = send_status_to_websocket
            def send_status(status, message=""):
                asyncio.run(_send_status(status, message, merchant_id))
            send_status('running', 'verifying transactions')
            try:
                with transaction.atomic():
                    payin = Payin.objects.select_for_update().get(id=payin.id)

                    if not payin.user_submitted_utr or payin.user_submitted_utr == '-':
                        logger.debug(f"Payin {payin.id}: No UTR submitted, skipping")
                        not_found_count += 1
                        continue

                    transaction_obj = ExtractedTransactions.objects.filter(
                        utr=payin.user_submitted_utr,
                        merchant_id=payin.merchant_id
                    ).first()

                    if not transaction_obj:
                        logger.debug(f"Payin {payin.id}: No matching transaction found for UTR {payin.user_submitted_utr}")
                        not_found_count += 1
                        continue

                    logger.debug(f"Payin {payin.id}: Found transaction {transaction_obj.id} with UTR {transaction_obj.utr}")

                    if transaction_obj.is_used:
                        logger.warning(
                            f"Payin {payin.id}: Transaction {transaction_obj.id} (UTR: {transaction_obj.utr}) "
                            f"is already used. Marking payin as duplicate."
                        )
                        payin.status = 'duplicate'
                        if hasattr(payin, 'assigned_at') and payin.assigned_at:
                            payin.duration = timezone.now() - payin.assigned_at
                        payin.save(update_fields=['status', 'duration'])
                        duplicate_count += 1

                    elif transaction_obj.amount != int(float(payin.pay_amount or 0)):
                        logger.warning(
                            f"Payin {payin.id}: Amount mismatch. "
                            f"Payin amount: {payin.pay_amount}, Transaction amount: {transaction_obj.amount}. "
                            f"Marking payin as dispute."
                        )
                        payin.status = 'dropped'
                        if hasattr(payin, 'assigned_at') and payin.assigned_at:
                            payin.duration = timezone.now() - payin.assigned_at
                        payin.save(update_fields=['status', 'duration'])
                        dropped_count += 1

                    else:
                        logger.info(
                            f"Payin {payin.id}: Transaction {transaction_obj.id} is valid. "
                            f"Amount: {transaction_obj.amount}, UTR: {transaction_obj.utr}"
                        )

                        transaction_obj.is_used = True
                        transaction_obj.save(update_fields=['is_used'])

                        payin.status = 'success'
                        payin.confirmed_amount = payin.pay_amount
                        payin.utr = transaction_obj.utr

                        if hasattr(payin, 'assigned_at') and payin.assigned_at:
                            payin.duration = timezone.now() - payin.assigned_at

                        payin.save(update_fields=['status', 'confirmed_amount', 'duration', 'utr'])
                        verified_count += 1

            except Payin.DoesNotExist:
                logger.warning(f"Payin {payin.id} no longer exists, skipping")
                error_count += 1
                continue
            except Exception as e:
                logger.error(f"Error verifying payin {payin.id}: {str(e)}", exc_info=True)
                error_count += 1
                continue

        logger.info(
            f"Transaction verification completed - "
            f"Verified: {verified_count}, "
            f"Duplicates: {duplicate_count}, "
            f"Dropped: {dropped_count}, "
            f"Not found: {not_found_count}, "
            f"Errors: {error_count}"
        )
        send_status('running', 'transaction verification completed')

        return {
            "verified": verified_count,
            "duplicates": duplicate_count,
            "disputes": dropped_count,
            "not_found": not_found_count,
            "errors": error_count,
            "total": assigned_payins.count()
        }
    except Exception as e:
        logger.error(f"Bot task failed: {str(e)}", exc_info=True)
        raise
