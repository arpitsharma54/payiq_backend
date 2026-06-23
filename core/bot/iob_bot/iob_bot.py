import asyncio
import logging
import re
from datetime import datetime, timedelta
import pandas as pd
from deposit.models import Payin
from playwright.async_api import async_playwright
from PIL import Image, ImageEnhance
import easyocr
from merchants.models import BankAccount, ExtractedTransactions
from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from channels.layers import get_channel_layer
import redis
import os

logger = logging.getLogger(__name__)

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
OCR_MODEL = easyocr.Reader(['en'], gpu=False)
redis_client = redis.Redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)
BOT_INTERVAL = getattr(settings, 'BOT_EXECUTION_INTERVAL', 30)

MAX_RELOGIN_ATTEMPTS = 5
RELOGIN_DELAY_SECONDS = 3


class BotStoppedException(Exception):
    pass


class LoggedOutException(Exception):
    pass


async def check_logged_out(page) -> bool:
    """
    Check if the 'logged out' or 'login denied' message is displayed on the page.
    These messages indicate the session is invalid and requires re-login.
    """
    try:
        text = page.get_by_text("Successful logout")
        text2 = page.get_by_text("Your session has expired")
        if await text.is_visible():
            return True
        elif await text2.is_visible():
            return True
        return False
    except Exception:
        return False


def check_stop_flag(bank_account_id: int) -> bool:
    stop_flag_key = f'bot_stop_flag_{bank_account_id}'
    return redis_client.get(stop_flag_key) is not None


async def check_stop_and_raise(bank_account_id: int, send_status=None):
    if check_stop_flag(bank_account_id):
        logger.info(f"Stop flag detected for bank account {bank_account_id}")
        if send_status:
            await send_status('stopped', 'Bot stopped by user request')
        raise BotStoppedException(f"Bot stopped by user request for account {bank_account_id}")


async def save_screenshot(page, prefix="error"):
    try:
        if page:
            screenshots_dir = os.path.join(settings.BASE_DIR, 'logs', 'screenshots')
            os.makedirs(screenshots_dir, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{prefix}_{timestamp}.png"
            filepath = os.path.join(screenshots_dir, filename)
            await page.screenshot(path=filepath, full_page=True)
            logger.info(f"Screenshot saved to {filepath}")
    except Exception as e:
        logger.error(f"Failed to take screenshot: {e}", exc_info=True)


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

    await channel_layer.group_send("task_status_updates", payload)


def extract_utr_from_text(text: str) -> str | None:
    if not text or not isinstance(text, str):
        return None

    patterns = [
        r'\b([A-Z]{4,6}\d{8,16})\b',
        r'\b(\d{10,16})\b',
        r'UPI/(\d{12})',
        r'IMPS/(\d{12})',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            utr = match.group(1)
            if 10 <= len(utr) <= 16:
                return utr

    return None


def preprocess_captcha(img_path: str) -> str:
    img = Image.open(img_path).convert("L")
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(2.5)
    processed_path = img_path.replace(".png", "_processed.png")
    img.save(processed_path)
    return processed_path


def process_csv_transactions(csv_path: str, bank_account_id: int) -> list:
    try:
        header_row_index = 0
        with open(csv_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                if 'debit' in line.lower() and 'credit' in line.lower():
                    header_row_index = i
                    break

        df = pd.read_csv(csv_path, skiprows=header_row_index)
        logger.info(f"CSV loaded: {len(df)} rows, header at row {header_row_index}")

        df.columns = df.columns.str.strip()

        if 'Debit' not in df.columns:
            logger.error("Could not find 'Debit' column in CSV")
            return []

        credit_transactions = df[df['Debit'].isna()].copy()
        logger.info(f"Credit transactions found: {len(credit_transactions)}")

        if credit_transactions.empty:
            logger.warning("No credit transactions in CSV")
            return []

        bank_account = BankAccount.objects.select_related('merchant').get(id=bank_account_id)
        merchant = bank_account.merchant

        transactions = []
        skipped_count = 0

        for index, row in credit_transactions.iterrows():
            try:
                credit_amount = row.get('Credit', 0)
                if pd.isna(credit_amount) or credit_amount <= 0:
                    skipped_count += 1
                    continue

                narration = str(row.get('Narration', ''))
                utr = extract_utr_from_text(narration)

                if not utr:
                    description = str(row.get('Description', ''))
                    remarks = str(row.get('Remarks', ''))
                    utr = extract_utr_from_text(f"{description} {remarks} {narration}")

                if not utr:
                    logger.debug(f"Row {index}: No UTR found. Narration: {narration[:50]}")
                    skipped_count += 1
                    continue

                try:
                    amount = int(float(credit_amount))
                    if amount <= 0:
                        skipped_count += 1
                        continue
                except (ValueError, TypeError):
                    logger.warning(f"Row {index}: Invalid amount {credit_amount}")
                    skipped_count += 1
                    continue

                transactions.append(ExtractedTransactions(
                    bank_account=bank_account,
                    merchant=merchant,
                    amount=amount,
                    utr=utr
                ))

            except Exception as e:
                logger.warning(f"Error processing row {index}: {e}")
                skipped_count += 1
                continue

        logger.info(f"Extracted {len(transactions)} transactions, skipped {skipped_count}")
        return transactions

    except FileNotFoundError:
        logger.error(f"CSV file not found: {csv_path}")
        return []
    except pd.errors.EmptyDataError:
        logger.error("CSV file is empty")
        return []
    except Exception as e:
        logger.error(f"Error processing CSV: {e}", exc_info=True)
        return []


async def save_extracted_transactions(transactions: list) -> dict:
    if not transactions:
        logger.warning("No transactions to save")
        return {"saved": 0, "skipped": 0, "errors": 0}

    try:
        def check_and_save():
            merchant = transactions[0].merchant
            existing_utrs = set(
                ExtractedTransactions.objects.filter(
                    utr__in=[t.utr for t in transactions],
                    merchant=merchant
                ).values_list('utr', flat=True)
            )

            new_transactions = [t for t in transactions if t.utr not in existing_utrs]

            if not new_transactions:
                logger.info("All transactions already exist in DB")
                return {"saved": 0, "skipped": len(transactions), "errors": 0}

            ExtractedTransactions.objects.bulk_create(new_transactions, ignore_conflicts=True)
            return {
                "saved": len(new_transactions),
                "skipped": len(transactions) - len(new_transactions),
                "errors": 0
            }

        result = await sync_to_async(check_and_save)()
        logger.info(f"Saved: {result['saved']}, skipped (duplicates): {result['skipped']}")
        return result

    except Exception as e:
        logger.error(f"Error saving transactions: {e}", exc_info=True)
        return {"saved": 0, "skipped": 0, "errors": len(transactions)}


async def extract_and_save_transactions(csv_path: str, bank_account_id: int) -> dict:
    try:
        transactions = await asyncio.to_thread(process_csv_transactions, csv_path, bank_account_id)

        if not transactions:
            logger.warning("No transactions extracted from CSV")
            return {"saved": 0, "skipped": 0, "errors": 0, "extracted": 0}

        result = await save_extracted_transactions(transactions)
        result["extracted"] = len(transactions)
        return result

    except Exception as e:
        logger.error(f"Error in extract_and_save_transactions: {e}", exc_info=True)
        return {"saved": 0, "skipped": 0, "errors": 1, "extracted": 0}


async def verify_transactions(send_status) -> dict:
    await send_status('running', 'Verifying transactions...')
    logger.info("Starting transaction verification")

    try:
        def do_verification():
            assigned_payins = Payin.objects.filter(status='assigned')
            expired_initiated_payins = Payin.objects.filter(
                status='initiated',
                created_at__lte=timezone.now() - timedelta(minutes=11)
            )
            logger.info(f"Assigned payins: {assigned_payins.count()}, expired initiated: {expired_initiated_payins.count()}")

            for payin in expired_initiated_payins:
                payin.status = 'dropped'
                payin.save()

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
                            logger.debug(f"Payin {payin.id}: No matching transaction for UTR {payin.user_submitted_utr}")
                            not_found_count += 1
                            continue

                        if transaction_obj.is_used:
                            logger.warning(f"Payin {payin.id}: UTR {transaction_obj.utr} already used — marking duplicate")
                            payin.status = 'duplicate'
                            if hasattr(payin, 'utr_submitted_at') and payin.utr_submitted_at:
                                payin.duration = timezone.now() - payin.utr_submitted_at
                            payin.save(update_fields=['status', 'duration'])
                            duplicate_count += 1

                        elif transaction_obj.amount != int(float(payin.pay_amount or 0)):
                            logger.warning(
                                f"Payin {payin.id}: Amount mismatch — "
                                f"payin={payin.pay_amount}, transaction={transaction_obj.amount} — marking dropped"
                            )
                            payin.status = 'dropped'
                            payin.amount = transaction_obj.amount
                            if hasattr(payin, 'utr_submitted_at') and payin.utr_submitted_at:
                                payin.duration = timezone.now() - payin.utr_submitted_at
                            payin.save(update_fields=['status', 'duration', 'amount'])
                            dropped_count += 1

                        else:
                            logger.info(f"Payin {payin.id}: Verified — amount={transaction_obj.amount}, UTR={transaction_obj.utr}")
                            transaction_obj.is_used = True
                            transaction_obj.used_at = timezone.now()
                            transaction_obj.save(update_fields=['is_used', 'used_at'])

                            payin.status = 'success'
                            payin.confirmed_amount = payin.pay_amount
                            payin.utr = transaction_obj.utr
                            if hasattr(payin, 'utr_submitted_at') and payin.utr_submitted_at:
                                payin.duration = timezone.now() - payin.utr_submitted_at
                            payin.save(update_fields=['status', 'confirmed_amount', 'duration', 'utr'])
                            verified_count += 1

                except Payin.DoesNotExist:
                    logger.warning(f"Payin {payin.id} no longer exists, skipping")
                    error_count += 1
                except Exception as e:
                    logger.error(f"Error verifying payin {payin.id}: {e}", exc_info=True)
                    error_count += 1

            expired_assigned_payins = Payin.objects.filter(
                status='assigned',
                created_at__lte=timezone.now() - timedelta(minutes=11)
            )
            for payin in expired_assigned_payins:
                payin.status = 'dropped'
                payin.save()
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
            f"Verification done — verified={result['verified']}, duplicates={result['duplicates']}, "
            f"dropped={result['dropped']}, not_found={result['not_found']}, errors={result['errors']}"
        )
        await send_status('running', f"Verified: {result['verified']} transactions")
        return result

    except Exception as e:
        logger.error(f"Error in transaction verification: {e}", exc_info=True)
        await send_status('error', f'Verification error: {e}')
        return {"verified": 0, "duplicates": 0, "dropped": 0, "not_found": 0, "errors": 1, "total": 0}


async def perform_login(page, bank_account, send_status, bank_account_id: int) -> bool:
    username = bank_account.username or ''
    password = bank_account.password or ''
    max_captcha_retries = 10

    for captcha_attempt in range(1, max_captcha_retries + 1):
        await check_stop_and_raise(bank_account_id, send_status)
        logger.info(f"Captcha attempt {captcha_attempt}/{max_captcha_retries}")
        await send_status('running', f'Captcha attempt {captcha_attempt}/{max_captcha_retries}')

        # Click login page redirection button — only on the landing page
        try:
            login_redirect_btn = await page.wait_for_selector('#login_page_redirection_button', timeout=10000)
            await login_redirect_btn.click()
            # domcontentloaded is enough — the form is in the initial HTML, not lazy-loaded
            await page.wait_for_load_state('domcontentloaded', timeout=15000)
        except Exception as e:
            await save_screenshot(page, f"login_redirect_error_acc{bank_account_id}_attempt{captcha_attempt}")
            logger.warning(f"Login redirect button not found (may already be on form): {e}")

        # Fill user ID — wait_for_selector polls until element is in DOM, no extra networkidle needed
        try:
            result = await page.evaluate("""
            () => {
            const el = document.querySelector('paper-input');
            return {
                exists: !!el,
                hasShadow: !!el?.shadowRoot,
                shadowChildren: el?.shadowRoot?.children.length || 0
            };
            }
            """)
            print("DEBUG:", result)
            user_id_input = page.locator('paper-input').locator('input').first
            await user_id_input.wait_for(timeout=30000)
            await user_id_input.fill(username)
        except Exception as e:
            await save_screenshot(page, f"login_userid_error_acc{bank_account_id}_attempt{captcha_attempt}")
            logger.warning(f"Error filling user ID: {e}")
            continue

        # Fill password
        try:
            password_input = page.get_by_role("textbox", name="Password")
            await password_input.type(password)
            logger.info("Credentials filled")
        except Exception as e:
            await save_screenshot(page, f"login_password_error_acc{bank_account_id}_attempt{captcha_attempt}")
            logger.warning(f"Error filling password: {e}")
            continue

        # Capture captcha — wait_for_selector handles when it's ready
        await send_status('running', 'Capturing captcha image')
        try:
            canvas = await page.wait_for_selector('#captchaCanvas', timeout=30000)
            img_path = os.path.join(BOT_DIR, f"captcha_{bank_account_id}.png")
            await canvas.screenshot(path=img_path)
        except Exception as e:
            await save_screenshot(page, f"login_captcha_capture_error_acc{bank_account_id}_attempt{captcha_attempt}")
            logger.warning(f"Error capturing captcha: {e}")
            continue

        processed_path = preprocess_captcha(img_path)
        await send_status('running', 'Extracting captcha text')

        results = OCR_MODEL.readtext(
            processed_path,
            detail=0,
            allowlist='0123456789',
            text_threshold=0.5,
            low_text=0.3,
            width_ths=1.0,
            paragraph=False,
        )
        captcha_text = ''.join(''.join(results).split())
        logger.info(f"Captcha extracted: '{captcha_text}'")

        # Fill captcha and submit
        try:
            captcha_input = await page.wait_for_selector('input[aria-labelledby="paper-input-label-4"]', timeout=30000)
            await captcha_input.type(captcha_text)
            submit_button = await page.wait_for_selector('#btn_loginConfirm', timeout=30000)
            await submit_button.click()
            await send_status('running', 'Submitting login')
            logger.info("Login button clicked")
        except Exception as e:
            await save_screenshot(page, f"login_submit_error_acc{bank_account_id}_attempt{captcha_attempt}")
            logger.warning(f"Error submitting login form: {e}")
            continue

        # Wait for post-submit navigation — domcontentloaded is enough to check outcome
        try:
            await page.wait_for_load_state('domcontentloaded', timeout=20000)
        except Exception as e:
            await save_screenshot(page, f"login_post_submit_timeout_acc{bank_account_id}_attempt{captcha_attempt}")
            logger.warning(f"Timeout after login submit: {e}")

        await asyncio.sleep(1)

        # Check for error message
        has_error = await page.locator("#errMsg").is_visible(timeout=1000)
        if has_error:
            try:
                await page.get_by_role("button", name="Close").click()
            except Exception:
                await save_screenshot(page, f"login_close_error_btn_failed_acc{bank_account_id}_attempt{captcha_attempt}")
                pass
            logger.warning(f"Login error on attempt {captcha_attempt}")
            await send_status('running', f'Login error, retrying ({captcha_attempt}/{max_captcha_retries})')
            continue

        # Confirm login succeeded by checking login button is gone
        login_button = page.get_by_role("button", name="UserId Login")
        try:
            await login_button.wait_for(state="hidden", timeout=3000)
            logger.info("Login successful")
            return True
        except Exception:
            await save_screenshot(page, f"login_failed_still_on_login_page_acc{bank_account_id}_attempt{captcha_attempt}")
            logger.info("Login failed — still on login page")

    return False


async def download_statement(page, bank_account_id: int, send_status) -> dict:
    """Navigate from the Accounts menu each iteration, download CSV, extract and save transactions."""
    try:

        # Accounts menu
        await send_status('running', 'Navigating to Accounts')
        await page.locator("#desktop_nav_menu_1 > .content-align-vertical-center").click()
        logger.info("Accounts menu clicked")

        # Operative accounts
        await page.get_by_role("link", name="Operative accounts").wait_for(state="visible")
        await page.get_by_role("link", name="Operative accounts").click()
        await page.wait_for_load_state("domcontentloaded")
        logger.info("Operative accounts clicked")

        # Account card
        await send_status('running', 'Selecting account card')
        await page.locator("opr-account-card").first.click()
        logger.info("Account card clicked")

        # Recent transactions tab
        await page.get_by_role("tablist").get_by_text("Recent transactions").wait_for(state="visible")
        await page.get_by_role("tablist").get_by_text("Recent transactions").click()
        await page.wait_for_load_state("domcontentloaded")
        logger.info("Recent transactions tab clicked")

        # Detailed statement button
        await send_status('running', 'Opening detailed statement')
        await page.get_by_role("button", name="Detailed statement").wait_for(state="visible")
        await page.get_by_role("button", name="Detailed statement").click()
        await page.wait_for_load_state("domcontentloaded")
        logger.info("Detailed statement button clicked")

        # Custom range
        await page.get_by_role("radio", name="Custom range").wait_for(state="visible")
        await page.get_by_role("radio", name="Custom range").click()
        await page.wait_for_load_state("domcontentloaded")
        logger.info("Custom range selected")

        # Set dates
        local_now = timezone.localtime(timezone.now())
        today = local_now.strftime('%d/%m/%Y')
        yesterday = (local_now - timedelta(days=3)).strftime('%d/%m/%Y')

        await page.get_by_label("From date").first.fill(yesterday)
        logger.info(f"From date: {yesterday}")
        await send_status('running', f'From date: {yesterday}')

        await page.get_by_label("To date").first.fill(today)
        logger.info(f"To date: {today}")
        await send_status('running', f'To date: {today}')

        await check_stop_and_raise(bank_account_id, send_status)

        # Apply
        await page.get_by_role("button", name="Apply").wait_for(state="visible")
        await page.get_by_role("button", name="Apply").click()
        await page.wait_for_load_state("domcontentloaded")
        logger.info("Apply button clicked")
        await send_status('running', 'Applying date filter')

        # Check for no data
        no_data_locator = page.locator("strong:has-text('Nothing found to display')")
        if await no_data_locator.count() > 0:
            logger.info("No transactions to display, skipping download")
            await send_status('running', 'No transactions found, proceeding to verification')
            return {"saved": 0, "skipped": 0, "errors": 0, "extracted": 0}
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(3000)
        no_data = page.locator("iob-detailed-statement").get_by_text("No records found!")

        if await no_data.is_visible():
            logger.info("No transactions found")
            return {
                "saved": 0,
                "skipped": 0,
                "errors": 0,
                "extracted": 0
            }
        # Download CSV — intercept download before clicking
        await page.get_by_role("button", name="Download Button press enter").wait_for(state="visible")
        await page.get_by_role("button", name="Download Button press enter").click()
        await page.wait_for_load_state("domcontentloaded")

        await page.get_by_role("listbox").get_by_text("CSV").wait_for(state="visible")

        async with page.expect_download() as download_info:
            await page.get_by_role("listbox").get_by_text("CSV").click()
            logger.info("CSV download initiated")

        download = await download_info.value
        csv_path = os.path.join(BOT_DIR, f"statement_{bank_account_id}.csv")
        await download.save_as(csv_path)
        logger.info(f"CSV saved to {csv_path}")
        await send_status('running', 'CSV downloaded, processing transactions')

        result = await extract_and_save_transactions(csv_path, bank_account_id)
        logger.info(
            f"Account {bank_account_id} — extracted={result.get('extracted', 0)}, "
            f"saved={result.get('saved', 0)}, skipped={result.get('skipped', 0)}, "
            f"errors={result.get('errors', 0)}"
        )
        await send_status('running', f"Saved {result.get('saved', 0)} new transactions")
        return result

    except BotStoppedException:
        raise
    except Exception as e:
        logger.error(f"Error downloading statement: {e}", exc_info=True)
        await send_status('error', f'Statement error: {e}')
        await save_screenshot(page, f"download_statement_error_acc{bank_account_id}")
        raise


async def attempt_relogin(page, bank_account, send_status, bank_account_id: int, netbanking_url: str) -> bool:
    for attempt in range(1, MAX_RELOGIN_ATTEMPTS + 1):
        await send_status('running', f'Re-login attempt {attempt}/{MAX_RELOGIN_ATTEMPTS}')
        logger.info(f"Re-login attempt {attempt}/{MAX_RELOGIN_ATTEMPTS} for account {bank_account_id}")

        await asyncio.sleep(RELOGIN_DELAY_SECONDS)
        await check_stop_and_raise(bank_account_id, send_status)

        try:
            await page.goto(netbanking_url, wait_until='domcontentloaded', timeout=60000)
        except Exception as e:
            logger.warning(f"Navigation error during re-login: {e}")
            await save_screenshot(page, f"relogin_nav_error_acc{bank_account_id}_attempt{attempt}")
            try:
                await page.goto(netbanking_url, wait_until='domcontentloaded', timeout=60000)
                await asyncio.sleep(3)
            except Exception:
                continue

        if await perform_login(page, bank_account, send_status, bank_account_id):
            await send_status('running', 'Re-login successful')
            logger.info(f"Re-login successful for account {bank_account_id}")
            return True

        logger.warning(f"Re-login attempt {attempt} failed for account {bank_account_id}")

    await send_status('error', f'Re-login failed after {MAX_RELOGIN_ATTEMPTS} attempts')
    logger.error(f"All re-login attempts failed for account {bank_account_id}")
    return False


async def run_bot_for_account(bank_account_id: int):
    """
    Run bot for a specific bank account:
    - Login once
    - Loop: navigate from Accounts menu -> download statement -> verify -> wait BOT_INTERVAL seconds
    - On stop: logout gracefully then close browser
    """
    browser = None
    page = None

    try:
        bank_account = await sync_to_async(BankAccount.objects.get)(id=bank_account_id)
        merchant_id = bank_account.merchant_id

        _send_status = send_status_to_websocket
        async def send_status(status, message=""):
            await _send_status(status, message, merchant_id, bank_account_id)

        await send_status('running', 'Starting bot')
        logger.info(f"Starting bot for {bank_account.nickname} (ID: {bank_account_id})")

        await check_stop_and_raise(bank_account_id, send_status)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--window-size=1500,800",
                    "--disable-features=DownloadBubble,DownloadBubbleV2",
                ]
            )

            try:
                context = await browser.new_context(
                    permissions=["geolocation"],
                    locale="en-US",
                    timezone_id="Asia/Kolkata",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                    ignore_https_errors=True,
                    accept_downloads=True,
                )
                page = await context.new_page()

                # await page.add_init_script("""
                #     Object.defineProperty(navigator, 'webdriver', { get: () => false });
                #     Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                #     Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                #     const originalQuery = window.navigator.permissions.query;
                #     window.navigator.permissions.query = (parameters) => (
                #         parameters.name === 'notifications' ?
                #             Promise.resolve({ state: Notification.permission }) :
                #             originalQuery(parameters)
                #     );
                # """)

                # ── LOGIN ──────────────────────────────────────────────────
                netbanking_url = bank_account.netbanking_url
                await send_status('running', 'Navigating to login page')

                try:
                    # page.on("console", lambda msg: print("CONSOLE:", msg.type, msg.text))
                    # page.on("pageerror", lambda e: print("PAGE ERROR:", e))
                    # page.on("requestfailed", lambda req: print("REQUEST FAILED:", req.url))
                    await page.goto(netbanking_url, wait_until="networkidle")
                    await asyncio.sleep(3)
                    logger.info("Login page loaded")
                except Exception as e:
                    logger.warning(f"Navigation error: {e}")
                    await page.goto(netbanking_url, wait_until='domcontentloaded', timeout=60000)
                    await asyncio.sleep(3)

                await check_stop_and_raise(bank_account_id, send_status)

                if not await perform_login(page, bank_account, send_status, bank_account_id):
                    await send_status('error', 'Login failed after maximum captcha attempts')
                    raise Exception("Login failed after maximum captcha attempts")

                await send_status('running', 'Login successful — starting monitoring')
                logger.info(f"Login successful for account {bank_account_id}")

                # ── MAIN LOOP ──────────────────────────────────────────────
                iteration = 0
                while True:
                    iteration += 1
                    logger.info(f"=== Iteration {iteration} — account {bank_account_id} ===")
                    await send_status('running', f'Iteration {iteration}: starting')

                    await check_stop_and_raise(bank_account_id, send_status)

                    if await check_logged_out(page):
                        logger.warning(f"Session expired for account {bank_account_id}")
                        await send_status('running', 'Session expired — attempting re-login')
                        if not await attempt_relogin(page, bank_account, send_status, bank_account_id, netbanking_url):
                            raise Exception("Re-login failed after maximum attempts")
                        iteration = 0
                        continue

                    try:
                        result = await download_statement(page, bank_account_id, send_status)
                        logger.info(f"Iteration {iteration} download result: {result}")

                        await check_stop_and_raise(bank_account_id, send_status)

                        verify_result = await verify_transactions(send_status)
                        logger.info(f"Iteration {iteration} verification result: {verify_result}")

                    except BotStoppedException:
                        raise
                    except Exception as e:
                        logger.error(f"Iteration {iteration} error: {e}", exc_info=True)
                        await send_status('error', f'Iteration {iteration} error: {e}')
                        await save_screenshot(page, f"iteration_error_acc{bank_account_id}_iter{iteration}")

                        if await check_logged_out(page):
                            await send_status('running', 'Session expired — attempting re-login')
                            if not await attempt_relogin(page, bank_account, send_status, bank_account_id, netbanking_url):
                                raise Exception("Re-login failed after maximum attempts")
                            iteration = 0
                            continue

                    await check_stop_and_raise(bank_account_id, send_status)

                    # Wait BOT_INTERVAL seconds, checking stop flag every 2 seconds
                    await send_status('running', f'Waiting {BOT_INTERVAL}s before next iteration')
                    logger.info(f"Waiting {BOT_INTERVAL} seconds")
                    wait_elapsed = 0
                    while wait_elapsed < BOT_INTERVAL:
                        await asyncio.sleep(2)
                        wait_elapsed += 2
                        if check_stop_flag(bank_account_id):
                            await send_status('stopped', 'Bot stopped by user request')
                            raise BotStoppedException(f"Bot stopped during wait for account {bank_account_id}")

            except BotStoppedException:
                logger.info(f"Bot stopped for account {bank_account_id} — logging out")
                await send_status('running', 'Logging out...')
                if page:
                    try:
                        await page.get_by_role("button", name="Logout").click(timeout=5000)
                        await page.locator("oe-i18n-msg[msgid='m_confirmLogout']").wait_for(state="visible", timeout=5000)
                        await page.get_by_role("button", name="Yes").click(timeout=5000)
                        logger.info("Logged out successfully")
                        await asyncio.sleep(2)
                    except Exception as e:
                        logger.warning(f"Could not logout gracefully: {e}")
                await send_status('stopped', 'Bot stopped successfully')
                raise

            except Exception as e:
                logger.error(f"Bot execution failed for account {bank_account_id}: {e}", exc_info=True)
                await send_status('error', f'Bot failed: {e}')
                await save_screenshot(page, f"bot_fatal_error_acc{bank_account_id}")
                raise

            finally:
                if browser:
                    try:
                        await browser.close()
                        logger.info("Browser closed")
                    except Exception as e:
                        logger.warning(f"Error closing browser: {e}")

    except BotStoppedException:
        raise
    except Exception as e:
        logger.error(f"Failed to run bot for account {bank_account_id}: {e}", exc_info=True)
        raise


async def main():
    try:
        enabled_accounts = await sync_to_async(list)(
            BankAccount.objects.filter(is_enabled=True, deleted_at=None).values_list('id', flat=True)
        )
        if not enabled_accounts:
            logger.info("No enabled bank accounts found")
            return

        logger.info(f"Found {len(enabled_accounts)} enabled bank account(s)")
        for bank_account_id in enabled_accounts:
            try:
                await run_bot_for_account(bank_account_id)
            except Exception as e:
                logger.error(f"Failed for account {bank_account_id}: {e}", exc_info=True)

        logger.info("Bot execution completed for all enabled accounts")

    except Exception as e:
        logger.error(f"Failed to get enabled bank accounts: {e}", exc_info=True)
        raise


def run_async(func, *args, **kwargs):
    return asyncio.run(func(*args, **kwargs))
