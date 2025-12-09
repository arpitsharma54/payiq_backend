"""
OpenAPI schema extensions for drf-spectacular.
This file contains schema decorators and extensions for API documentation.
"""
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample, OpenApiResponse
from drf_spectacular.types import OpenApiTypes


# Common error response schemas
ERROR_RESPONSE = {
    'type': 'object',
    'properties': {
        'error': {
            'type': 'string',
            'description': 'Error message'
        }
    }
}

VALIDATION_ERROR_RESPONSE = {
    'type': 'object',
    'additionalProperties': {
        'type': 'array',
        'items': {'type': 'string'}
    },
    'description': 'Field validation errors'
}

# Authentication schemas
LOGIN_REQUEST = {
    'type': 'object',
    'required': ['username', 'password'],
    'properties': {
        'username': {'type': 'string', 'description': 'Username'},
        'password': {'type': 'string', 'description': 'Password'}
    }
}

LOGIN_RESPONSE = {
    'type': 'object',
    'properties': {
        'refresh': {'type': 'string', 'description': 'JWT refresh token'},
        'access': {'type': 'string', 'description': 'JWT access token'},
        'id': {'type': 'integer', 'description': 'User ID'},
        'username': {'type': 'string'},
        'role': {'type': 'string', 'enum': ['super_admin', 'admin']},
        'full_name': {'type': 'string'},
        'is_active': {'type': 'boolean'},
        'last_login': {'type': 'string', 'format': 'date-time'},
        'merchants': {'type': 'array', 'items': {'type': 'integer'}},
        'merchant_names': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'id': {'type': 'integer'},
                    'name': {'type': 'string'},
                    'code': {'type': 'string'}
                }
            }
        }
    }
}

# Bot status schemas
BOT_STATUS_RESPONSE = {
    'type': 'object',
    'properties': {
        'bank_account_id': {'type': 'integer'},
        'is_running': {'type': 'boolean'},
        'status': {'type': 'string', 'enum': ['idle', 'running']},
        'task_id': {'type': 'string', 'nullable': True}
    }
}

BOT_START_RESPONSE = {
    'type': 'object',
    'properties': {
        'message': {'type': 'string'},
        'task_id': {'type': 'string'},
        'interval': {'type': 'integer', 'description': 'Bot execution interval in seconds'}
    }
}

# Dashboard schemas
DASHBOARD_RESPONSE = {
    'type': 'object',
    'properties': {
        'deposits': {
            'type': 'object',
            'properties': {
                'total': {'type': 'string'},
                'count': {'type': 'integer'},
                'percentage': {'type': 'string'}
            }
        },
        'withdrawals': {
            'type': 'object',
            'properties': {
                'total': {'type': 'string'},
                'count': {'type': 'integer'},
                'percentage': {'type': 'string'}
            }
        },
        'summary': {
            'type': 'object',
            'properties': {
                'deposits': {'type': 'string'},
                'withdrawals': {'type': 'string'},
                'commission': {'type': 'string'},
                'chargeback': {'type': 'string'},
                'payout_balance': {'type': 'string'},
                'settlement': {'type': 'string'},
                'net_balance': {'type': 'string'}
            }
        },
        'chart': {
            'type': 'object',
            'properties': {
                'total_amount': {'type': 'string'},
                'total_count': {'type': 'integer'},
                'data': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'date': {'type': 'string'},
                            'amount': {'type': 'number'},
                            'count': {'type': 'integer'}
                        }
                    }
                }
            }
        }
    }
}

# Payment session schemas
PUBLIC_SESSION_RESPONSE = {
    'type': 'object',
    'properties': {
        'session_id': {'type': 'string', 'format': 'uuid'},
        'code': {'type': 'string'},
        'pay_amount': {'type': 'string'},
        'status': {'type': 'string'},
        'merchant_name': {'type': 'string'},
        'callback_url': {'type': 'string', 'format': 'uri'},
        'return_url': {'type': 'string', 'format': 'uri'},
        'expiry_timestamp': {'type': 'string', 'format': 'date-time'},
        'bank_account': {
            'type': 'object',
            'properties': {
                'nickname': {'type': 'string'},
                'account_holder_name': {'type': 'string'},
                'account_number': {'type': 'string'},
                'ifsc_code': {'type': 'string'},
                'upi_id': {'type': 'string'},
                'min_payin': {'type': 'string'},
                'max_payin': {'type': 'string'}
            }
        },
        'upi_available': {'type': 'boolean'},
        'bank_transfer_available': {'type': 'boolean'}
    }
}

PAYMENT_LINK_REQUEST = {
    'type': 'object',
    'required': ['merchant', 'user'],
    'properties': {
        'merchant': {'type': 'integer', 'description': 'Merchant ID'},
        'user': {'type': 'string', 'description': 'User identifier'},
        'merchant_order_id': {'type': 'string', 'description': 'Optional order ID'},
        'amount': {'type': 'number', 'description': 'Optional payment amount'}
    }
}

PAYMENT_LINK_RESPONSE = {
    'type': 'object',
    'properties': {
        'message': {'type': 'string'},
        'payment_link_url': {'type': 'string', 'format': 'uri'},
        'session_id': {'type': 'string', 'format': 'uuid'},
        'sign': {'type': 'string'},
        'merchant_id': {'type': 'integer'},
        'user_id': {'type': 'string'},
        'pay_amount': {'type': 'string'}
    }
}
