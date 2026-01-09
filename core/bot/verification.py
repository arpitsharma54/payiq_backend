"""
Transaction Verification Module
Verifies pending payins against extracted bank transactions.
"""
import asyncio
import logging
from django.db import transaction
from django.utils import timezone
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


async def send_status_to_websocket(status, message="", merchant_id=None, bank_account_id=None):
    """Send status updates via WebSocket"""
    try:
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
    except Exception as e:
        logger.warning(f"Could not send WebSocket status update: {str(e)}")


def verify_transactions_sync(bank_account_id: int = None) -> dict:
    """
    Verify pending payins against extracted transactions.

    Args:
        bank_account_id: Optional - if provided, only verify payins for this bank account's merchant

    Returns:
        dict with verification statistics
    """
    from deposit.models import Payin
    from merchants.models import ExtractedTransactions, BankAccount

    logger.info("Starting transaction verification...")

    # Get assigned payins
    assigned_payins = Payin.objects.filter(status='assigned')

    # If bank_account_id provided, filter by merchant
    if bank_account_id:
        try:
            bank_account = BankAccount.objects.get(id=bank_account_id)
            assigned_payins = assigned_payins.filter(merchant_id=bank_account.merchant_id)
            logger.info(f"Filtering payins for merchant {bank_account.merchant_id}")
        except BankAccount.DoesNotExist:
            logger.warning(f"Bank account {bank_account_id} not found")

    logger.info(f"Found {assigned_payins.count()} assigned payins to verify")

    verified_count = 0
    duplicate_count = 0
    dropped_count = 0
    not_found_count = 0
    error_count = 0

    for payin in assigned_payins:
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

                # Find matching transaction - filter by merchant through bank_account
                transaction_query = ExtractedTransactions.objects.filter(
                    utr=payin.user_submitted_utr
                )

                # Filter by merchant if payin has merchant_id
                if payin.merchant_id:
                    transaction_query = transaction_query.filter(
                        bank_account__merchant_id=payin.merchant_id
                    )

                transaction_obj = transaction_query.first()

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
                        f"Marking payin as dropped."
                    )
                    payin.status = 'dropped'
                    payin.confirmed_amount = transaction_obj.amount
                    # Calculate duration if assigned_at exists
                    if hasattr(payin, 'assigned_at') and payin.assigned_at:
                        payin.duration = timezone.now() - payin.assigned_at
                        logger.debug(f"Payin {payin.id}: Duration calculated: {payin.duration}")
                    payin.save(update_fields=['status', 'duration', 'confirmed_amount'])
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

    result = {
        "verified": verified_count,
        "duplicates": duplicate_count,
        "dropped": dropped_count,
        "not_found": not_found_count,
        "errors": error_count,
        "total": assigned_payins.count()
    }

    logger.info(
        f"Transaction verification completed - "
        f"Verified: {verified_count}, "
        f"Duplicates: {duplicate_count}, "
        f"Dropped: {dropped_count}, "
        f"Not found: {not_found_count}, "
        f"Errors: {error_count}"
    )

    return result


async def verify_transactions_async(bank_account_id: int = None) -> dict:
    """
    Async wrapper for transaction verification.

    Args:
        bank_account_id: Optional - if provided, only verify payins for this bank account's merchant
    """
    # Send status update
    if bank_account_id:
        from merchants.models import BankAccount
        try:
            bank_account = await sync_to_async(BankAccount.objects.get)(id=bank_account_id)
            await send_status_to_websocket(
                'running',
                'Verifying transactions...',
                bank_account.merchant_id,
                bank_account_id
            )
        except Exception:
            pass

    # Run verification in thread pool (it's DB heavy)
    result = await sync_to_async(verify_transactions_sync)(bank_account_id)

    # Send completion status
    if bank_account_id:
        try:
            await send_status_to_websocket(
                'running',
                f'Verification complete: {result["verified"]} verified, {result["not_found"]} pending',
                bank_account.merchant_id,
                bank_account_id
            )
        except Exception:
            pass

    return result
