"""
Utility functions for deposit/payin operations
"""
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)


def send_merchant_callback(payin) -> bool:
    """
    Send callback notification to merchant's callback URL when payment status changes.
    
    Args:
        payin: Payin instance with updated status
        
    Returns:
        bool: True if callback was sent successfully, False otherwise
    """
    # Check if merchant has callback URL configured
    if not payin.merchant or not payin.merchant.callback_url:
        logger.debug(f"Payin {payin.id}: Merchant has no callback URL configured")
        return False
    
    # Build payload with payment details
    payload = {
        'payin_uuid': str(payin.payin_uuid),
        'code': payin.code,
        'merchant_order_id': str(payin.merchant_order_id) if payin.merchant_order_id else None,
        'status': payin.status,
        'amount': str(payin.pay_amount) if payin.pay_amount else '0.00',
        'confirmed_amount': str(payin.confirmed_amount) if payin.confirmed_amount else None,
        'utr': payin.utr,
        'user': payin.user,
        'bank': payin.bank,
    }
    
    try:
        logger.info(
            f"Payin {payin.id}: Sending callback to merchant {payin.merchant.id} "
            f"at {payin.merchant.callback_url} for status: {payin.status}"
        )
        
        response = requests.post(
            payin.merchant.callback_url,
            json=payload,
            timeout=30,
            headers={'Content-Type': 'application/json'}
        )
        
        # Check if response is successful (2xx status codes)
        if response.status_code >= 200 and response.status_code < 300:
            logger.info(
                f"Payin {payin.id}: Callback sent successfully to merchant {payin.merchant.id}. "
                f"Response status: {response.status_code}"
            )
            return True
        else:
            logger.warning(
                f"Payin {payin.id}: Callback sent but received non-2xx response "
                f"({response.status_code}) from merchant {payin.merchant.id}"
            )
            return False
            
    except requests.exceptions.Timeout:
        logger.error(
            f"Payin {payin.id}: Callback request timed out after 30 seconds "
            f"for merchant {payin.merchant.id} at {payin.merchant.callback_url}"
        )
        return False
    except requests.exceptions.RequestException as e:
        logger.error(
            f"Payin {payin.id}: Failed to send callback to merchant {payin.merchant.id} "
            f"at {payin.merchant.callback_url}: {str(e)}"
        )
        return False
    except Exception as e:
        logger.error(
            f"Payin {payin.id}: Unexpected error sending callback to merchant {payin.merchant.id}: {str(e)}",
            exc_info=True
        )
        return False
