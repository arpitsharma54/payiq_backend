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
    import json
    from django.utils import timezone

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
    
    call_start_time = timezone.now()
    status_changed_at = payin.updated_at.isoformat() if hasattr(payin, 'updated_at') and payin.updated_at else 'Unknown'
    
    try:
        logger.info(
            f"--- MERCHANT CALLBACK INITIATED ---\n"
            f"Payin ID: {payin.id}\n"
            f"Payin UUID: {payin.payin_uuid}\n"
            f"Status Changed At: {status_changed_at}\n"
            f"API Call Time: {call_start_time.isoformat()}\n"
            f"URL: {payin.merchant.callback_url}\n"
            f"Payload: {json.dumps(payload, indent=2)}\n"
            f"------------------------------------"
        )
        
        response = requests.post(
            payin.merchant.callback_url,
            json=payload,
            timeout=30,
            headers={'Content-Type': 'application/json'}
        )
        
        call_end_time = timezone.now()
        duration = (call_end_time - call_start_time).total_seconds()
        
        # Check if response is successful (2xx status codes)
        if response.status_code >= 200 and response.status_code < 300:
            logger.info(
                f"--- MERCHANT CALLBACK SUCCESS ---\n"
                f"Payin ID: {payin.id}\n"
                f"Response Time: {call_end_time.isoformat()} (Duration: {duration:.3f}s)\n"
                f"Status Code: {response.status_code}\n"
                f"Response Headers: {dict(response.headers)}\n"
                f"Response Body: {response.text}\n"
                f"----------------------------------"
            )
            return True
        else:
            logger.warning(
                f"--- MERCHANT CALLBACK NON-2XX RESPONSE ---\n"
                f"Payin ID: {payin.id}\n"
                f"Response Time: {call_end_time.isoformat()} (Duration: {duration:.3f}s)\n"
                f"Status Code: {response.status_code}\n"
                f"Response Headers: {dict(response.headers)}\n"
                f"Response Body: {response.text}\n"
                f"-------------------------------------------"
            )
            return False
            
    except requests.exceptions.Timeout as e:
        call_end_time = timezone.now()
        duration = (call_end_time - call_start_time).total_seconds()
        logger.error(
            f"--- MERCHANT CALLBACK TIMEOUT ---\n"
            f"Payin ID: {payin.id}\n"
            f"Status Changed At: {status_changed_at}\n"
            f"URL: {payin.merchant.callback_url}\n"
            f"Payload: {json.dumps(payload)}\n"
            f"Duration: {duration:.3f}s\n"
            f"Error: {str(e)}\n"
            f"----------------------------------"
        )
        return False
    except requests.exceptions.RequestException as e:
        call_end_time = timezone.now()
        duration = (call_end_time - call_start_time).total_seconds()
        logger.error(
            f"--- MERCHANT CALLBACK FAILED ---\n"
            f"Payin ID: {payin.id}\n"
            f"Status Changed At: {status_changed_at}\n"
            f"URL: {payin.merchant.callback_url}\n"
            f"Payload: {json.dumps(payload)}\n"
            f"Duration: {duration:.3f}s\n"
            f"Error: {str(e)}\n"
            f"---------------------------------"
        )
        return False
    except Exception as e:
        call_end_time = timezone.now()
        duration = (call_end_time - call_start_time).total_seconds()
        logger.error(
            f"--- MERCHANT CALLBACK UNEXPECTED ERROR ---\n"
            f"Payin ID: {payin.id}\n"
            f"Status Changed At: {status_changed_at}\n"
            f"URL: {payin.merchant.callback_url}\n"
            f"Payload: {json.dumps(payload)}\n"
            f"Duration: {duration:.3f}s\n"
            f"Error: {str(e)}\n"
            f"------------------------------------------",
            exc_info=True
        )
        return False
