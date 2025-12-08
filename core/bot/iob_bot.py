import asyncio
import logging
import re
import pandas as pd
from deposit.models import Payin
from playwright.async_api import async_playwright
import base64
from paddleocr import PaddleOCR
from merchants.models import BankAccount, ExtractedTransactions
from asgiref.sync import sync_to_async, async_to_sync
logger = logging.getLogger(__name__)
from django.db import transaction
from django.utils import timezone
from channels.layers import get_channel_layer


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
        
        # Get bank account
        bank_account = BankAccount.objects.get(id=bank_account_id)
        
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
        # Check for existing transactions to avoid duplicates
        def check_and_save():
            existing_utrs = set(
                ExtractedTransactions.objects.filter(
                    utr__in=[t.utr for t in transactions]
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


async def run_bot_for_account(bank_account_id: int):
    """
    Run bot for a specific bank account.
    This function handles the browser automation and transaction extraction for one bank account.
    """
    browser = None
    try:
        # Get bank account details
        bank_account = await sync_to_async(BankAccount.objects.get)(id=bank_account_id)
        merchant_id = bank_account.merchant_id
        
        # Shadow global send_status to include merchant_id and bank_account_id
        _send_status =  send_status_to_websocket
        async def send_status(status, message=""):
            await _send_status(status, message, merchant_id, bank_account_id)

        await send_status('running', "Starting bot for bank account")
        logger.info(f"Starting bot for bank account: {bank_account.nickname} (ID: {bank_account_id})")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-accelerated-2d-canvas",
                    "--no-first-run",
                    "--no-zygote",
                    "--disable-gpu",
                    "--window-size=1920,1080",
                    "--disable-features=DownloadBubble,DownloadBubbleV2"  # Disable download UI
                ]
            )
            
            try:
                # Create a new context with realistic settings
                # Set downloads to be handled by Playwright only (not saved to browser's default location)
                context = await browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    ignore_https_errors=True,
                    accept_downloads=True,
                    # Set a temporary download path (we'll override with save_as)
                    # This ensures downloads are intercepted and not saved to default browser location
                )
                
                page = await context.new_page()
                
                # Hide automation indicators
                await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => false
            });
            
            // Override the plugins property to use a non-empty array
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            
            // Override the languages property
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
            
            // Override permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
                """)
                
                # Navigate with proper error handling
                try:
                    netbanking_url = bank_account.netbanking_url
                    await send_status('running', 'Navigating to login page')
                    await page.goto(netbanking_url, 
                        wait_until='networkidle',
                        timeout=60000
                    )
                    logger.info('Page loaded successfully')
                    await send_status('running', 'Page loaded successfully')
                except Exception as e:
                    logger.warning(f'Navigation error: {e}')
                    await send_status('error', f'Navigation error: {e}')
                    # Try alternative approach
                    
                    await page.goto(netbanking_url, 
                        wait_until='domcontentloaded',
                        timeout=60000
                    )
                    await asyncio.sleep(3)  # Wait for page to fully load
                
                # Fill in login credentials from bank account
                await send_status('running', 'Filling in login credentials')
                username = bank_account.username or ''
                username2 = bank_account.username2 or ''
                password = bank_account.password or ''

                # Corporate login uses loginsubmit_loginId and loginsubmit_userId
                if bank_account.login_type == 'corp':
                    await page.evaluate(f"() => {{ document.getElementById('loginsubmit_loginId').value = '{username}'; }}")
                    await page.evaluate(f"() => {{ document.getElementById('loginsubmit_userId').value = '{username2}'; }}")
                else:
                    # Normal login - just use userId
                    await page.evaluate(f"() => {{ document.getElementById('loginsubmit_userId').value = '{username}'; }}")

                await page.evaluate(f"() => {{ document.getElementById('password').value = '{password}'; }}")
                await send_status('running', 'getting captcha image')
                # Extract captcha image
                src = await page.evaluate('document.getElementById("captchaimg").src')
                logger.debug(f'Captcha image source: {src}')
                
                # Decode base64
                img_bytes = base64.b64decode(src.replace('data:image/png;base64,', ''))
                
                # Save to file (use unique filename per bank account)
                img_path = f"core/bot/decoded_image_{bank_account_id}.png"
                with open(img_path, "wb") as f:
                    f.write(img_bytes)
                
                logger.info(f"Saved captcha image to {img_path}")
                await send_status('running', 'extracting captcha text')
                # Run PaddleOCR on the saved image
                ocr = PaddleOCR(use_textline_orientation=True, lang='en')
                logger.info('OCR initialized')
                result = ocr.predict(img_path)
                logger.info('OCR prediction completed')
                text = result[0]["rec_texts"][0]
                logger.info(f'OCR extracted text: {text}')
                cleaned_text = text.replace(" ", "")
                
                # Fill captcha and submit
                await page.evaluate(f"() => {{ document.getElementById('loginsubmit_captchaid').value = '{cleaned_text}'; }}")
                logger.info('Captcha filled in form')
                await send_status('running', 'filling captcha')
                await page.evaluate("() => { document.getElementById('btnSubmit').click(); }")
                logger.info('Login button clicked')
                await send_status('running', 'clicking login button')
                # Wait for login to complete - check for either success (dashboard) or error
                try:
                    await send_status('running', 'waiting for login to complete')
                    # Wait for either the Account statement link or an error message
                    await page.wait_for_selector(
                        "xpath=//a[contains(., 'Account statement')] | //*[contains(text(), 'Invalid')] | //*[contains(text(), 'Error')]",
                        timeout=30000,
                        state="visible"
                    )
                    logger.info('Login completed, page loaded')
                    await send_status('running', 'login completed')
                except Exception as e:
                    logger.warning(f"Timeout waiting for post-login page: {str(e)}")
                    await send_status('error', f"Timeout waiting for post-login page: {str(e)}")
                    # Take screenshot for debugging
                    await page.screenshot(path=f'core/bot/login_timeout_{bank_account_id}.png')
                    logger.info(f'Screenshot saved: core/bot/login_timeout_{bank_account_id}.png')
                    # Check if we're still on login page (login might have failed)
                    current_url = page.url
                    if 'corplogin' in current_url:
                        logger.error('Still on login page - login may have failed')
                        await send_status('error', 'login failed - still on login page after timeout')
                        raise Exception('Login failed - still on login page after timeout')
                
                # Verify we're not on login page anymore
                current_url = page.url
                if 'corplogin' in current_url:
                    logger.error('Login failed - still on login page')
                    await send_status('error', 'login failed - still on login page after timeout')
                    await page.screenshot(path=f'core/bot/login_failed_{bank_account_id}.png')
                    logger.info(f'Screenshot saved: core/bot/login_failed_{bank_account_id}.png')
                    raise Exception('Login failed - captcha or credentials may be incorrect')
                
                # Click on Account statement with retry logic
                max_retries = 3
                retry_count = 0
                account_statement_clicked = False
                
                while retry_count < max_retries and not account_statement_clicked:
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
                                await send_status('running', 'account statement menu clicked')
                                account_statement_clicked = True
                                break
                            except Exception:
                                continue
                        
                        if not account_statement_clicked:
                            await send_status('error', 'account statement menu not found')
                            raise Exception("Account statement link not found with any selector")
                            
                    except Exception as e:
                        retry_count += 1
                        await send_status('error', f"Attempt {retry_count} failed to click Account statement: {str(e)}. Retrying...")
                        if retry_count < max_retries:
                            logger.warning(f"Attempt {retry_count} failed to click Account statement: {str(e)}. Retrying...")
                            await asyncio.sleep(2)
                            # Refresh page or navigate back
                            await page.reload()
                            await asyncio.sleep(3)
                        else:
                            logger.error(f"Failed to click Account statement after {max_retries} attempts: {str(e)}")
                            await page.screenshot(path=f'core/bot/account_statement_timeout_{bank_account_id}.png')
                            logger.info(f'Screenshot saved: core/bot/account_statement_timeout_{bank_account_id}.png')
                            raise
                await asyncio.sleep(5)
                
                # Select account
                await page.evaluate("""
                    const sel = document.querySelector('#accountNo');
                    sel.selectedIndex = 1;
                """)
                logger.info('Account number selected')
                await send_status('running', 'account number selected')
                # Set from date
                await page.evaluate("""() => {
                    const el = document.querySelector('#fromDate');
                    el.removeAttribute('readonly');
                    el.value = '11/11/2025';  // format expected by site
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }""")
                logger.info('From date set')
                await send_status('running', 'from date set')
                # Set to date
                await page.evaluate("""() => {
                    const el = document.querySelector('#toDate');
                    el.removeAttribute('readonly');
                    el.value = '11/11/2025';  // format expected by site
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }""")
                logger.info('To date set')
                await send_status('running', 'to date set')                
                # Click view button
                await page.evaluate("() => { document.getElementById('accountstatement_view').click(); }")
                await send_status('running', 'clicking view button')
                await asyncio.sleep(5)
                
                # Wait for the CSV download button to be ready
                csv_button = page.locator("#accountstatement_csvAcctStmt")
                await csv_button.wait_for(state="visible", timeout=10000)
                # Intercept download BEFORE clicking - this prevents it from going to browser's download folder
                # expect_download() intercepts the download and holds it in Playwright's control
                async with page.expect_download() as download_info:
                    await csv_button.click()
                    logger.info('CSV download button clicked')
                
                # Get the intercepted download (this is NOT saved to browser's default location)
                download = await download_info.value
                await send_status('running', 'csv button clicked')
                # Save the file ONLY to our project directory (use unique filename per bank account)
                csv_path = f"core/bot/statement_{bank_account_id}.csv"
                await download.save_as(csv_path)
                await send_status('running', 'csv file saved')
                logger.info(f"CSV file saved as {csv_path} (only in project directory, not in browser downloads)")
                
                # Optionally, get file info
                suggested_filename = download.suggested_filename
                logger.info(f"Downloaded file: {suggested_filename}")

                # Extract and save transactions from CSV
                result = await extract_and_save_transactions(csv_path, bank_account_id)
                logger.info(
                    f"Transaction processing completed for bank account {bank_account_id} - "
                    f"Extracted: {result.get('extracted', 0)}, "
                    f"Saved: {result.get('saved', 0)}, "
                    f"Skipped: {result.get('skipped', 0)}, "
                    f"Errors: {result.get('errors', 0)}"
                )
                await send_status('running', 'csv file processed')
                await asyncio.sleep(10)
                
                # Take screenshot
                await page.screenshot(path=f'core/bot/screenshot_{bank_account_id}.png')
                
                # Logout
                logout_button = page.locator("xpath=//a[contains(., 'Logout ')]")
                await logout_button.click()
                logger.info('Logout button clicked')
                await send_status('running', 'logout button clicked')
                await asyncio.sleep(10)
                await send_status('completed', 'Bot execution finished')
                logger.info(f'Bot execution completed for bank account {bank_account_id}')
            except Exception as e:
                logger.error(f"Bot execution failed for bank account {bank_account_id}: {str(e)}", exc_info=True)
                # Close browser before re-raising
                if browser:
                    try:
                        await browser.close()
                        logger.info('Browser closed after error')
                    except Exception as close_error:
                        logger.warning(f"Error closing browser: {str(close_error)}")
                raise
            finally:
                # Always close browser, even if an error occurred
                if browser:
                    try:
                        await browser.close()
                        logger.info('Browser closed')
                    except Exception as e:
                        logger.warning(f"Error closing browser: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to initialize browser for bank account {bank_account_id}: {str(e)}", exc_info=True)
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
                # Continue with next account even if one fails
                continue
        
        logger.info("Bot execution completed for all enabled bank accounts")
    except Exception as e:
        logger.error(f"Failed to get enabled bank accounts: {str(e)}", exc_info=True)
        raise

import asyncio

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
                # Wrap each payin verification in a transaction for atomicity
                with transaction.atomic():
                    # Use select_for_update to prevent race conditions
                    payin = Payin.objects.select_for_update().get(id=payin.id)
                    
                    # Skip if UTR is not provided
                    if not payin.user_submitted_utr or payin.user_submitted_utr == '-':
                        logger.debug(f"Payin {payin.id}: No UTR submitted, skipping")
                        not_found_count += 1
                        continue
                    
                    # Find matching transaction
                    transaction_obj = ExtractedTransactions.objects.filter(
                        utr=payin.user_submitted_utr
                    ).first()
                    
                    if not transaction_obj:
                        logger.debug(f"Payin {payin.id}: No matching transaction found for UTR {payin.user_submitted_utr}")
                        not_found_count += 1
                        continue
                    
                    logger.debug(f"Payin {payin.id}: Found transaction {transaction_obj.id} with UTR {transaction_obj.utr}")
                    
                    # Check if transaction is already used
                    if transaction_obj.is_used:
                        logger.warning(
                            f"Payin {payin.id}: Transaction {transaction_obj.id} (UTR: {transaction_obj.utr}) "
                            f"is already used. Marking payin as duplicate."
                        )
                        payin.status = 'duplicate'
                        # Calculate duration if assigned_at exists
                        if hasattr(payin, 'assigned_at') and payin.assigned_at:
                            payin.duration = timezone.now() - payin.assigned_at
                            logger.debug(f"Payin {payin.id}: Duration calculated: {payin.duration}")
                        payin.save(update_fields=['status', 'duration'])
                        duplicate_count += 1
                    
                    # Check if amount matches
                    elif transaction_obj.amount != int(float(payin.pay_amount or 0)):
                        logger.warning(
                            f"Payin {payin.id}: Amount mismatch. "
                            f"Payin amount: {payin.pay_amount}, Transaction amount: {transaction_obj.amount}. "
                            f"Marking payin as dispute."
                        )
                        payin.status = 'dropped'
                        # Calculate duration if assigned_at exists
                        if hasattr(payin, 'assigned_at') and payin.assigned_at:
                            payin.duration = timezone.now() - payin.assigned_at
                            logger.debug(f"Payin {payin.id}: Duration calculated: {payin.duration}")
                        payin.save(update_fields=['status', 'duration'])
                        dropped_count += 1
                    
                    # Transaction is valid
                    else:
                        logger.info(
                            f"Payin {payin.id}: Transaction {transaction_obj.id} is valid. "
                            f"Amount: {transaction_obj.amount}, UTR: {transaction_obj.utr}"
                        )
                        
                        # Mark transaction as used
                        transaction_obj.is_used = True
                        transaction_obj.save(update_fields=['is_used'])
                        
                        # Update payin status
                        payin.status = 'success'
                        payin.confirmed_amount = payin.pay_amount
                        payin.utr = transaction_obj.utr
                        
                        # Calculate duration if assigned_at exists
                        if hasattr(payin, 'assigned_at') and payin.assigned_at:
                            payin.duration = timezone.now() - payin.assigned_at
                            logger.debug(f"Payin {payin.id}: Duration calculated: {payin.duration}")
                        
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