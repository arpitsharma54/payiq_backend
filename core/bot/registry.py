"""
Bot Registry - Factory pattern for selecting the appropriate bank bot
"""
import logging
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


# Registry of bank type to bot function mapping
BOT_REGISTRY: Dict[str, Callable] = {}


def register_bot(bank_type: str):
    """
    Decorator to register a bot function for a specific bank type.
    Usage:
        @register_bot('iob')
        async def run_iob_bot(bank_account_id: int):
            ...
    """
    def decorator(func: Callable):
        BOT_REGISTRY[bank_type] = func
        logger.info(f"Registered bot for bank type: {bank_type}")
        return func
    return decorator


def get_bot_for_bank_type(bank_type: str) -> Optional[Callable]:
    """
    Get the bot function for a specific bank type.
    Returns None if no bot is registered for the bank type.
    """
    return BOT_REGISTRY.get(bank_type)


def get_supported_bank_types() -> list:
    """Get list of all bank types that have a registered bot"""
    return list(BOT_REGISTRY.keys())


# Register IOB bot
@register_bot('iob')
async def run_iob_bot(bank_account_id: int):
    """Run IOB bank bot"""
    from .iob_bot.iob_bot import run_bot_for_account
    return await run_bot_for_account(bank_account_id)


# Register CUB bot
@register_bot('cub')
async def run_cub_bot(bank_account_id: int):
    """Run CUB bank bot"""
    from .cub_bot.cub_bot import run_bot_for_account
    return await run_bot_for_account(bank_account_id)



# Placeholder registrations for future bank bots
# When you implement a new bank bot, create a new folder (e.g., sbi_bot/)
# with sbi_bot.py inside it and register it here:

# @register_bot('sbi')
# async def run_sbi_bot(bank_account_id: int):
#     """Run SBI bank bot"""
#     from .sbi_bot.sbi_bot import run_bot_for_account
#     return await run_bot_for_account(bank_account_id)

# @register_bot('hdfc')
# async def run_hdfc_bot(bank_account_id: int):
#     """Run HDFC bank bot"""
#     from .hdfc_bot.hdfc_bot import run_bot_for_account
#     return await run_bot_for_account(bank_account_id)


async def run_bot_for_account(bank_account_id: int):
    """
    Main entry point - selects and runs the appropriate bot based on bank account's bank type.
    After bot execution, verifies pending transactions.
    """
    from merchants.models import BankAccount
    from asgiref.sync import sync_to_async
    from .verification import verify_transactions_async

    # Get bank account to determine bank type
    bank_account = await sync_to_async(BankAccount.objects.get)(id=bank_account_id)
    bank_type = bank_account.bank_type

    logger.info(f"Selecting bot for bank type: {bank_type} (account ID: {bank_account_id})")

    # Get the appropriate bot
    bot_func = get_bot_for_bank_type(bank_type)

    if bot_func is None:
        error_msg = f"No bot implemented for bank type: {bank_type}. Supported types: {get_supported_bank_types()}"
        logger.error(error_msg)
        raise NotImplementedError(error_msg)

    # Run the bot
    bot_result = await bot_func(bank_account_id)

    # After bot execution, verify pending transactions
    logger.info(f"Bot execution completed for account {bank_account_id}. Starting transaction verification...")
    try:
        verification_result = await verify_transactions_async(bank_account_id)
        logger.info(f"Transaction verification completed: {verification_result}")
    except Exception as e:
        logger.error(f"Error during transaction verification: {str(e)}", exc_info=True)
        # Don't fail the whole operation if verification fails

    return bot_result


def run_async(func, *args, **kwargs):
    """Helper to run async functions synchronously"""
    import asyncio
    return asyncio.run(func(*args, **kwargs))
