"""
Base bot class that all bank-specific bots should inherit from.
This provides common functionality and defines the interface for bank bots.
"""
import asyncio
import logging
import re
import pandas as pd
from abc import ABC, abstractmethod
from playwright.async_api import async_playwright
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer

from merchants.models import BankAccount, ExtractedTransactions

logger = logging.getLogger(__name__)


async def send_status_to_websocket(status, message="", merchant_id=None, bank_account_id=None):
    """Send status updates via WebSocket"""
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


class BaseBankBot(ABC):
    """
    Abstract base class for all bank-specific bots.
    Each bank bot should inherit from this class and implement the required methods.
    """

    def __init__(self, bank_account_id: int):
        self.bank_account_id = bank_account_id
        self.bank_account = None
        self.merchant_id = None
        self.browser = None
        self.page = None
        self.context = None

    async def send_status(self, status: str, message: str = ""):
        """Send status update via WebSocket"""
        await send_status_to_websocket(status, message, self.merchant_id, self.bank_account_id)

    async def initialize(self):
        """Initialize the bot by loading bank account details"""
        self.bank_account = await sync_to_async(BankAccount.objects.get)(id=self.bank_account_id)
        self.merchant_id = self.bank_account.merchant_id
        logger.info(f"Initialized bot for bank account: {self.bank_account.nickname} (ID: {self.bank_account_id})")

    async def launch_browser(self, headless: bool = True):
        """Launch browser with standard configuration"""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(
            headless=headless,
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
                "--disable-features=DownloadBubble,DownloadBubbleV2"
            ]
        )

        self.context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            ignore_https_errors=True,
            accept_downloads=True,
        )

        self.page = await self.context.new_page()

        # Hide automation indicators
        await self.page.add_init_script("""
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

        logger.info("Browser launched successfully")

    async def close_browser(self):
        """Close browser safely"""
        if self.browser:
            try:
                await self.browser.close()
                logger.info("Browser closed")
            except Exception as e:
                logger.warning(f"Error closing browser: {str(e)}")

    async def save_screenshot(self, filename: str = None):
        """Save a screenshot for debugging"""
        if not filename:
            filename = f"screenshot_{self.bank_account_id}.png"
        path = f"core/bot/{filename}"
        await self.page.screenshot(path=path)
        logger.info(f"Screenshot saved: {path}")

    @abstractmethod
    async def login(self) -> bool:
        """
        Perform login to the bank's netbanking portal.
        Returns True if login successful, False otherwise.
        """
        pass

    @abstractmethod
    async def navigate_to_statement(self) -> bool:
        """
        Navigate to the account statement page.
        Returns True if successful, False otherwise.
        """
        pass

    @abstractmethod
    async def download_statement(self, from_date: str, to_date: str) -> str | None:
        """
        Download the account statement for the given date range.
        Returns the path to the downloaded file, or None if failed.
        """
        pass

    @abstractmethod
    async def logout(self):
        """Perform logout from the bank portal"""
        pass

    async def run(self) -> dict:
        """
        Main method to run the bot.
        This orchestrates the entire process: login, navigate, download, process, logout.
        """
        try:
            await self.initialize()
            await self.send_status('running', 'Starting bot for bank account')

            await self.launch_browser()

            # Login
            await self.send_status('running', 'Logging in...')
            if not await self.login():
                await self.send_status('error', 'Login failed')
                raise Exception("Login failed")

            # Navigate to statement
            await self.send_status('running', 'Navigating to statement page...')
            if not await self.navigate_to_statement():
                await self.send_status('error', 'Failed to navigate to statement')
                raise Exception("Failed to navigate to statement page")

            # Download statement
            await self.send_status('running', 'Downloading statement...')
            from datetime import datetime
            today = datetime.now().strftime('%d/%m/%Y')
            csv_path = await self.download_statement(today, today)

            if not csv_path:
                await self.send_status('error', 'Failed to download statement')
                raise Exception("Failed to download statement")

            # Process transactions
            await self.send_status('running', 'Processing transactions...')
            result = await extract_and_save_transactions(csv_path, self.bank_account_id)
            logger.info(
                f"Transaction processing completed - "
                f"Extracted: {result.get('extracted', 0)}, "
                f"Saved: {result.get('saved', 0)}, "
                f"Skipped: {result.get('skipped', 0)}"
            )

            # Logout
            await self.send_status('running', 'Logging out...')
            await self.logout()

            await self.send_status('completed', 'Bot execution finished')
            logger.info(f"Bot execution completed for bank account {self.bank_account_id}")

            return result

        except Exception as e:
            logger.error(f"Bot execution failed: {str(e)}", exc_info=True)
            await self.send_status('error', f'Bot failed: {str(e)}')
            raise
        finally:
            await self.close_browser()
