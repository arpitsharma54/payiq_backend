from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from django.db.models import Q, Sum, Count, F, DecimalField, Sum
from django.db.models.functions import TruncDate, TruncHour
from .models import Payin
from merchants.models import Merchant, BankAccount
from core.utils.multi_tenant import filter_by_user_merchants
from .serializer import (
    PayinSerializer,
    PayinCreateSerializer,
    PayinUpdateSerializer,
    PayinListSerializer,
    ExtractedTransactionSerializer
)
from merchants.models import ExtractedTransactions
from settlements.models import Settlement
import random
import string
import uuid
import os
from decimal import Decimal
import hashlib
from datetime import timedelta, date
from urllib.parse import urlencode
from django.utils import timezone


class PayinListView(APIView):
    """
    API view for listing all payins and creating a new payin.
    GET: List all payins (with optional filtering by ID and Code)
    POST: Create a new payin (New Payment Link)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get list of all payins with optional filtering"""
        queryset = Payin.objects.all()

        # Filter by user's accessible merchants (multi-tenant)
        queryset = filter_by_user_merchants(queryset, request.user, 'merchant')

        # Filter by ID if provided
        payin_id = request.query_params.get('id', None)
        if payin_id:
            try:
                queryset = queryset.filter(id=int(payin_id))
            except ValueError:
                return Response({
                    'error': 'Invalid ID format'
                }, status=status.HTTP_400_BAD_REQUEST)

        # Filter by Code if provided
        code = request.query_params.get('code', None)
        if code:
            queryset = queryset.filter(code__icontains=code)

        # Filter by status if provided
        status_filter = request.query_params.get('status', None)
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # Filter by merchant if provided (must be in user's accessible merchants)
        merchant_id = request.query_params.get('merchant', None)
        if merchant_id:
            try:
                merchant_id_int = int(merchant_id)
                # Verify user has access to this merchant
                user_role = request.user.role.lower() if request.user.role else ''
                if not (request.user.is_superuser or user_role == 'super_admin'):
                    merchant_ids = request.user.get_accessible_merchant_ids()
                    if merchant_id_int not in merchant_ids:
                        return Response({
                            'error': 'You do not have access to this merchant'
                        }, status=status.HTTP_403_FORBIDDEN)
                queryset = queryset.filter(merchant_id=merchant_id_int)
            except ValueError:
                return Response({
                    'error': 'Invalid merchant ID format'
                }, status=status.HTTP_400_BAD_REQUEST)

        # Order by created_at descending (newest first)
        queryset = queryset.order_by('-created_at')

        serializer = PayinListSerializer(queryset, many=True)
        return Response({
            'count': queryset.count(),
            'results': serializer.data
        }, status=status.HTTP_200_OK)

    def post(self, request):
        """Create a new payin (New Payment Link)"""
        serializer = PayinCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payin = serializer.save()
        # Return full serializer with read-only fields
        response_serializer = PayinSerializer(payin)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class PayinDetailView(APIView):
    """
    API view for retrieving, updating, and deleting a specific payin.
    GET: Retrieve a payin
    PUT: Update a payin (full update)
    PATCH: Update a payin (partial update)
    DELETE: Delete a payin (soft delete)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        """Get a specific payin by ID"""
        payin = get_object_or_404(Payin, pk=pk)
        serializer = PayinSerializer(payin)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, pk):
        """Full update of a payin"""
        payin = get_object_or_404(Payin, pk=pk)
        serializer = PayinUpdateSerializer(payin, data=request.data)
        serializer.is_valid(raise_exception=True)
        updated_payin = serializer.save()
        # Return full serializer with read-only fields
        response_serializer = PayinSerializer(updated_payin)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, pk):
        """Partial update of a payin"""
        payin = get_object_or_404(Payin, pk=pk)
        serializer = PayinUpdateSerializer(payin, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated_payin = serializer.save()
        # Return full serializer with read-only fields
        response_serializer = PayinSerializer(updated_payin)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        """Soft delete a payin"""
        payin = get_object_or_404(Payin, pk=pk)
        payin.soft_delete()
        return Response({
            'message': 'Payin deleted successfully'
        }, status=status.HTTP_200_OK)


class PayinCheckStatusView(APIView):
    """
    API view for checking the status of a payin.
    POST: Check and return current status
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        """Check the status of a payin"""
        payin = get_object_or_404(Payin, pk=pk)

        # If status is success, ensure duration is calculated
        if payin.status == 'success':
            payin.calculate_duration()

        serializer = PayinSerializer(payin)
        return Response({
            'id': payin.id,
            'payin_uuid': str(payin.payin_uuid),
            'status': payin.status,
            'confirmed_amount': str(payin.confirmed_amount),
            'utr': payin.utr,
            'user_submitted_utr': payin.user_submitted_utr,
            'duration': payin.get_duration_display(),
            'updated_at': payin.updated_at,
            'full_data': serializer.data
        }, status=status.HTTP_200_OK)


class PayinResetView(APIView):
    """
    API view for resetting a payin.
    POST: Reset a payin (change status back to queued/initiated)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        """Reset a payin"""
        payin = get_object_or_404(Payin, pk=pk)

        # Reset payin to initiated status
        payin.status = 'initiated'
        payin.confirmed_amount = 0
        payin.utr = None
        payin.user_submitted_utr = None
        payin.duration = None
        payin.save()

        serializer = PayinSerializer(payin)
        return Response({
            'message': 'Payin reset successfully',
            'data': serializer.data
        }, status=status.HTTP_200_OK)


class PayinNotifyView(APIView):
    """
    API view for notifying about a payin.
    POST: Send notification for a payin
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        """Notify about a payin"""
        payin = get_object_or_404(Payin, pk=pk)

        # In a real implementation, this would send notifications
        # For now, we'll just return a success message
        # You can integrate with email, SMS, or push notification services here

        serializer = PayinSerializer(payin)
        return Response({
            'message': f'Notification sent for payin {payin.id}',
            'payin_uuid': str(payin.payin_uuid),
            'status': payin.status,
            'data': serializer.data
        }, status=status.HTTP_200_OK)


class PayinActionsView(APIView):
    """
    Combined API view for payin actions (check status, reset, notify).
    POST: Perform an action on a payin
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, action):
        """Perform an action on a payin"""
        payin = get_object_or_404(Payin, pk=pk)

        if action == 'check_status':
            if payin.status == 'success':
                payin.calculate_duration()
            serializer = PayinSerializer(payin)
            return Response({
                'action': 'check_status',
                'status': payin.status,
                'data': serializer.data
            }, status=status.HTTP_200_OK)

        elif action == 'reset':
            payin.status = 'initiated'
            payin.confirmed_amount = 0
            payin.utr = None
            payin.user_submitted_utr = None
            payin.duration = None
            payin.save()
            serializer = PayinSerializer(payin)
            return Response({
                'action': 'reset',
                'message': 'Payin reset successfully',
                'data': serializer.data
            }, status=status.HTTP_200_OK)

        elif action == 'notify':
            serializer = PayinSerializer(payin)
            return Response({
                'action': 'notify',
                'message': f'Notification sent for payin {payin.id}',
                'data': serializer.data
            }, status=status.HTTP_200_OK)

        else:
            return Response({
                'error': f'Invalid action: {action}. Valid actions are: check_status, reset, notify'
            }, status=status.HTTP_400_BAD_REQUEST)


class PayinCreatePaymentLinkView(APIView):
    """
    API view for creating a new payment link.
    POST: Create a new payment link with optional fields

    Authentication: Requires valid merchant API key in header (X-API-Key) or payload (api_key).
    """
    permission_classes = [AllowAny]

    def post(self, request):
        """Create a new payment link - requires merchant API key"""
        # Extract API key from header or payload
        api_key = request.headers.get('X-API-Key') or request.data.get('api_key')

        if not api_key:
            return Response({
                'error': 'API key is required. Provide it in X-API-Key header or api_key field in request body.'
            }, status=status.HTTP_401_UNAUTHORIZED)

        # Validate API key and get merchant
        try:
            merchant = Merchant.objects.get(api_key=api_key, deleted_at=None)
        except Merchant.DoesNotExist:
            return Response({
                'error': 'Invalid API key'
            }, status=status.HTTP_403_FORBIDDEN)

        # Extract data from request
        user_id = request.data.get('user')
        merchant_order_id = request.data.get('merchant_order_id')

        # Validate required fields
        if not user_id or (isinstance(user_id, str) and user_id.strip() == ''):
            return Response({
                'error': 'User ID is a required field'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 2. Check if merchant has at least one enabled bank account
        enabled_bank_accounts = merchant.bank_accounts.filter(
            status=True,
            deleted_at=None
        )

        if not enabled_bank_accounts.exists():
            return Response({
                'error': 'Cannot create payment link. No enabled bank accounts found for this merchant. Please enable at least one bank account first.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Get the first enabled bank account
        bank_account = enabled_bank_accounts.first()

        # Generate a unique code - keep trying until we find one that doesn't exist
        max_attempts = 100  # Safety limit to prevent infinite loops
        code = None
        for attempt in range(max_attempts):
            candidate_code = ''.join(random.choices(string.ascii_letters + string.digits, k=5))
            if not Payin.objects.filter(code=candidate_code).exists():
                code = candidate_code
                break

        if code is None:
            return Response({
                'error': 'Failed to generate unique code. Please try again.'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Set pay_amount from amount if provided, otherwise use 0
        pay_amount = request.data.get('amount') if request.data.get('amount') else None
        if pay_amount:
            try:
                pay_amount = Decimal(str(pay_amount))
            except (ValueError, TypeError):
                pay_amount = Decimal('0.00')

        # Generate payin_uuid first
        payin_uuid = uuid.uuid4()

        # Generate signature (simple hash of sessionId + merchant API key)
        # In production, use a more secure signing mechanism
        sign_string = f"{payin_uuid}{merchant.api_key}"
        sign = hashlib.md5(sign_string.encode()).hexdigest()

        try:
            deposit = Payin.objects.create(
                code=code,
                merchant_order_id=merchant_order_id or uuid.uuid4(),
                merchant=merchant,
                user=user_id,
                bank=bank_account.nickname or bank_account.account_holder_name,
                status='initiated',
                payin_uuid=payin_uuid,
                pay_amount=pay_amount,
                user_submitted_utr='-',
            )
        except Exception as e:
            return Response({
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Generate payment URL with sessionId and sign
        frontend_base_url = os.getenv('FRONTEND_BASE_URL', 'http://localhost:5173')
        payment_url = f"{frontend_base_url}/payin?sessionId={payin_uuid}&sign={sign}"

        return Response({
            'message': 'Payment link created successfully',
            'payment_link_url': payment_url,
            'session_id': str(payin_uuid),
            'sign': sign,
            'merchant_id': merchant.id,
            'user_id': user_id,
            'pay_amount': str(pay_amount) if pay_amount else None,
        }, status=status.HTTP_201_CREATED)


class PayinPublicCheckStatusView(APIView):
    """
    Public API view for checking payment status by payin_uuid or merchant_order_id.
    Authentication: Requires merchant API key in header (X-API-Key) or query param (api_key).
    """
    permission_classes = [AllowAny]

    def get(self, request):
        """Check payment status by payin_uuid or merchant_order_id"""
        # Extract API key from header or query param
        api_key = request.headers.get('X-API-Key') or request.query_params.get('api_key')

        if not api_key:
            return Response({
                'error': 'API key is required. Provide it in X-API-Key header or api_key query parameter.'
            }, status=status.HTTP_401_UNAUTHORIZED)

        # Validate API key and get merchant
        try:
            merchant = Merchant.objects.get(api_key=api_key, deleted_at=None)
        except Merchant.DoesNotExist:
            return Response({
                'error': 'Invalid API key'
            }, status=status.HTTP_403_FORBIDDEN)

        # Get query parameters
        payin_uuid = request.query_params.get('payin_uuid')
        merchant_order_id = request.query_params.get('merchant_order_id')

        # At least one identifier must be provided
        if not payin_uuid and not merchant_order_id:
            return Response({
                'error': 'At least one of payin_uuid or merchant_order_id is required.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Find the payin
        try:
            if payin_uuid:
                payin = Payin.objects.get(payin_uuid=payin_uuid, merchant=merchant)
            else:
                payin = Payin.objects.get(merchant_order_id=merchant_order_id, merchant=merchant)
        except Payin.DoesNotExist:
            return Response({
                'error': 'Payment not found'
            }, status=status.HTTP_404_NOT_FOUND)
        except Payin.MultipleObjectsReturned:
            # If multiple payins found with same merchant_order_id, get the most recent
            payin = Payin.objects.filter(merchant_order_id=merchant_order_id, merchant=merchant).order_by('-created_at').first()

        return Response({
            'status': payin.status,
        }, status=status.HTTP_200_OK)


class PayinPublicSessionView(APIView):
    """
    Public API view for retrieving payment session details by sessionId (payin_uuid) and sign.
    This endpoint is accessible without authentication for payment pages.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        """Get payment session details by sessionId and sign"""
        session_id = request.query_params.get('sessionId')
        sign = request.query_params.get('sign')

        if not session_id:
            return Response({
                'error': 'sessionId is required'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            payin = Payin.objects.get(payin_uuid=session_id)
        except Payin.DoesNotExist:
            return Response({
                'error': 'Payment session not found'
            }, status=status.HTTP_404_NOT_FOUND)

        # Check if payment link has expired (10 minutes from creation)
        if payin.created_at:
            expiry_time = payin.created_at + timedelta(minutes=10)
            now = timezone.now()
            if expiry_time <= now:
                return Response({
                    'error': 'Payment link has expired. Please request a new payment link.',
                    'expired': True
                }, status=status.HTTP_410_GONE)

        # Update status from 'initiated' to 'assigned' when payment link is opened
        if payin.status == 'initiated':
            payin.status = 'assigned'
            payin.assigned_at = timezone.now()
            payin.save(update_fields=['status', 'assigned_at'])

        # Get the associated bank account
        bank_account = None

        # First, try to find bank account by nickname or account holder name if payin.bank is set
        if payin.bank:
            bank_account = payin.merchant.bank_accounts.filter(
                Q(nickname=payin.bank) | Q(account_holder_name=payin.bank),
                status=True,
                deleted_at=None
            ).first()

        # If not found or payin.bank is not set, fallback to any enabled bank account
        if not bank_account:
            bank_account = payin.merchant.bank_accounts.filter(
                status=True,
                deleted_at=None
            ).first()

        # If still no bank account found, return an error
        if not bank_account:
            return Response({
                'error': 'No enabled bank account found for this merchant. Please contact support.',
                'merchant_name': payin.merchant.name
            }, status=status.HTTP_404_NOT_FOUND)

        # Calculate expiry time (10 minutes from creation)
        expiry_timestamp = None
        if payin.created_at:
            expiry_time = payin.created_at + timedelta(minutes=10)
            expiry_timestamp = expiry_time.isoformat()

        # Prepare response data
        response_data = {
            'session_id': str(payin.payin_uuid),
            'code': payin.code,
            'pay_amount': str(payin.pay_amount) if payin.pay_amount else '0.00',
            'status': payin.status,
            'merchant_name': payin.merchant.name,
            'callback_url': payin.merchant.callback_url,
            'return_url': payin.merchant.return_url,
            'expiry_timestamp': expiry_timestamp,
            'bank_account': None,
            'upi_available': False,
            'bank_transfer_available': False,
        }

        if bank_account:
            response_data['bank_account'] = {
                'nickname': bank_account.nickname,
                'account_holder_name': bank_account.account_holder_name,
                'account_number': bank_account.account_number,
                'ifsc_code': bank_account.ifsc_code,
                'upi_id': bank_account.upi_id,
                'min_payin': str(bank_account.min_payin),
                'max_payin': str(bank_account.max_payin),
            }
            response_data['upi_available'] = bank_account.is_qr or bank_account.is_intent
            response_data['bank_transfer_available'] = bank_account.is_bank

        return Response(response_data, status=status.HTTP_200_OK)

    def post(self, request):
        """Submit UTR and/or screenshot for payment"""
        session_id = request.data.get('sessionId')
        utr = request.data.get('utr')
        screenshot = request.FILES.get('screenshot')

        if not session_id:
            return Response({
                'error': 'sessionId is required'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            payin = Payin.objects.get(payin_uuid=session_id)
        except Payin.DoesNotExist:
            return Response({
                'error': 'Payment session not found'
            }, status=status.HTTP_404_NOT_FOUND)

        # Check if payment link has expired (10 minutes from creation)
        if payin.created_at:
            expiry_time = payin.created_at + timedelta(minutes=10)
            now = timezone.now()
            if expiry_time <= now:
                return Response({
                    'error': 'Payment link has expired. Please request a new payment link.',
                    'expired': True
                }, status=status.HTTP_410_GONE)

        # Update UTR if provided
        if utr:
            payin.user_submitted_utr = utr
            payin.save(update_fields=['user_submitted_utr'])

        # Handle screenshot upload if provided
        # Note: You may want to save the screenshot file to a storage service
        if screenshot:
            # For now, we'll just acknowledge receipt
            # In production, save to S3 or similar storage
            pass

        # Build callback URL with parameters
        callback_url = None
        if payin.merchant.callback_url:
            callback_params = {
                'payin_uuid': str(payin.payin_uuid),
                'code': payin.code,
                'status': payin.status,
                'amount': str(payin.pay_amount) if payin.pay_amount else '0.00',
                'utr': utr or '',
            }
            # Add merchant_order_id if available
            if hasattr(payin, 'merchant_order_id') and payin.merchant_order_id:
                callback_params['merchant_order_id'] = str(payin.merchant_order_id)

            # Build URL with query parameters
            separator = '&' if '?' in payin.merchant.callback_url else '?'
            callback_url = f"{payin.merchant.callback_url}{separator}{urlencode(callback_params)}"

        return Response({
            'message': 'Payment details submitted successfully',
            'session_id': str(payin.payin_uuid),
            'status': payin.status,
            'callback_url': callback_url,
        }, status=status.HTTP_200_OK)


class DashboardView(APIView):
    """
    API view for dashboard statistics and metrics.
    GET: Get dashboard data including deposits, withdrawals, commission, etc.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get dashboard statistics"""
        # Get user's accessible merchants
        merchant_ids = request.user.get_accessible_merchant_ids()
        user_role = request.user.role.lower() if request.user.role else ''
        is_super_admin = request.user.is_superuser or user_role == 'super_admin'

        # Base queryset - filter by accessible merchants
        if is_super_admin:
            payins_queryset = Payin.objects.all()
        else:
            payins_queryset = Payin.objects.filter(merchant_id__in=merchant_ids)

        # Get query parameters
        merchant_codes = request.query_params.getlist('merchant_codes', [])
        time_range = request.query_params.get('time_range', '7D')  # 12H, 7D, 15D

        # Filter by merchant codes if provided
        if merchant_codes:
            payins_queryset = payins_queryset.filter(merchant__code__in=merchant_codes)

        # Calculate time range
        now = timezone.now()
        if time_range == '12H':
            start_time = now - timedelta(hours=12)
        elif time_range == '15D':
            start_time = now - timedelta(days=15)
        else:  # Default to 7D
            start_time = now - timedelta(days=7)

        # Filter by time range
        payins_queryset = payins_queryset.filter(created_at__gte=start_time)

        # Calculate metrics
        # Total deposits (success status)
        success_payins = payins_queryset.filter(status='success')
        total_deposits = success_payins.aggregate(
            total=Sum('confirmed_amount', default=Decimal('0.00'))
        )['total'] or Decimal('0.00')

        # Deposit count
        deposit_count = success_payins.count()

        # Deposit percentage (calculate commission)
        total_deposits_with_commission = success_payins.aggregate(
            total=Sum(F('confirmed_amount') * F('merchant__payin_commission') / 100, output_field=DecimalField())
        )['total'] or Decimal('0.00')

        # All-time totals for summary
        all_time_success = Payin.objects.filter(status='success')
        if not is_super_admin:
            all_time_success = all_time_success.filter(merchant_id__in=merchant_ids)
        if merchant_codes:
            all_time_success = all_time_success.filter(merchant__code__in=merchant_codes)

        all_time_deposits = all_time_success.aggregate(
            total=Sum('confirmed_amount', default=Decimal('0.00'))
        )['total'] or Decimal('0.00')

        all_time_commission = all_time_success.aggregate(
            total=Sum(F('confirmed_amount') * F('merchant__payin_commission') / 100, output_field=DecimalField())
        )['total'] or Decimal('0.00')

        # Withdrawals (currently not implemented, return 0)
        total_withdrawals = Decimal('0.00')
        withdrawal_count = 0
        withdrawal_percentage = Decimal('0.00')

        # Settlement (deposits - commission)
        settlement = Settlement.objects.filter(merchant__in=merchant_ids, status='success').aggregate(settlement=Sum('amount'))['settlement']
        if not settlement:
            settlement = 0
        # Net Balance (settlement - withdrawals)
        net_balance = (total_deposits - settlement) - all_time_commission

        # Generate chart data based on time range
        chart_data = []

        if time_range == '12H':
            # For 12H, show hourly data for the last 12 hours (IST)
            # Ensure current time is in IST (timezone.now() returns timezone-aware datetime)
            current_time_ist = timezone.localtime(now)
            # Round current time to nearest hour
            current_time = current_time_ist.replace(minute=0, second=0, microsecond=0)

            # Calculate start time (12 hours ago)
            start_time = current_time - timedelta(hours=11)  # 11 hours back + current hour = 12 hours

            # Get hourly deposits within the last 12 hours
            hourly_deposits = success_payins.filter(
                created_at__gte=start_time
            ).annotate(
                hour=TruncHour('created_at')
            ).values('hour').annotate(
                amount=Sum('confirmed_amount'),
                count=Count('id')
            ).order_by('hour')

            # Create a dictionary of actual data by hour
            # Use a normalized hour string as key for matching
            data_by_hour = {}
            for item in hourly_deposits:
                hour_dt = item['hour']
                # TruncHour returns timezone-aware datetime in project timezone (IST)
                # Convert to local time (IST) and then to naive for string comparison
                if hasattr(hour_dt, 'tzinfo') and hour_dt.tzinfo is not None:
                    hour_dt = timezone.localtime(hour_dt)
                    hour_dt = hour_dt.replace(tzinfo=None)

                # Use hour as key (YYYY-MM-DD HH:00:00 format)
                hour_key = hour_dt.strftime('%Y-%m-%d %H:00:00')
                data_by_hour[hour_key] = {
                    'amount': float(item['amount']),
                    'count': item['count']
                }

            # Generate all hours in the last 12 hours (from 11 hours ago to current hour)
            # current_time is already in IST and naive
            for i in range(11, -1, -1):  # Go from 11 hours ago to current hour
                hour_time = current_time - timedelta(hours=i)
                hour_str = hour_time.strftime('%Y-%m-%d %H:00:00')
                hour_display = hour_time.strftime('%Y-%m-%d %H:%M:%S')
                chart_data.append({
                    'date': hour_display,
                    'amount': data_by_hour.get(hour_str, {}).get('amount', 0.0),
                    'count': data_by_hour.get(hour_str, {}).get('count', 0)
                })
        else:
            # For 7D or 15D, show daily data
            # Ensure we're working in IST
            now_ist = timezone.localtime(now)

            daily_deposits = success_payins.annotate(
                date=TruncDate('created_at')
            ).values('date').annotate(
                amount=Sum('confirmed_amount'),
                count=Count('id')
            ).order_by('date')

            # Create a dictionary of actual data by date
            data_by_date = {}
            for item in daily_deposits:
                date_dt = item['date']
                # TruncDate returns a date object, but we need to ensure it's in IST
                # If it's a datetime, convert to IST first, then get date
                if not isinstance(date_dt, date):
                    # It's a datetime, convert to IST and extract date
                    if hasattr(date_dt, 'tzinfo') and date_dt.tzinfo is not None:
                        date_dt = timezone.localtime(date_dt)
                    date_dt = date_dt.date() if hasattr(date_dt, 'date') else date_dt

                date_str = date_dt.strftime('%Y-%m-%d')
                amount_value = float(item['amount']) if item['amount'] is not None else 0.0
                data_by_date[date_str] = {
                    'amount': amount_value,
                    'count': item['count']
                }

            # Generate all dates in the range (using IST)
            days = 7 if time_range == '7D' else 15
            start_date = (now_ist - timedelta(days=days-1)).date()
            end_date = now_ist.date()

            current_date = start_date
            while current_date <= end_date:
                date_str = current_date.strftime('%Y-%m-%d')
                amount = data_by_date.get(date_str, {}).get('amount', 0.0)
                count = data_by_date.get(date_str, {}).get('count', 0)
                chart_data.append({
                    'date': date_str,
                    'amount': amount,
                    'count': count
                })
                current_date += timedelta(days=1)

        return Response({
            'deposits': {
                'total': str(total_deposits),
                'count': deposit_count,
                'percentage': str(total_deposits_with_commission)
            },
            'withdrawals': {
                'total': str(total_withdrawals),
                'count': withdrawal_count,
                'percentage': str(withdrawal_percentage)
            },
            'summary': {
                'deposits': str(all_time_deposits),
                'withdrawals': str(total_withdrawals),
                'commission': str(all_time_commission),
                'chargeback': '0.00',
                'payout_balance': '0.00',
                'settlement': str(settlement),
                'net_balance': str(net_balance)
            },
            'chart': {
                'total_amount': str(total_deposits),
                'total_count': deposit_count,
                'data': chart_data
            }
        }, status=status.HTTP_200_OK)


class QueuedTransactionsView(APIView):
    """
    API view for listing queued (unused) extracted transactions.
    GET: List all extracted transactions with is_used=False
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get list of queued (unused) extracted transactions"""
        # Get base queryset - only unused transactions
        queryset = ExtractedTransactions.objects.filter(is_used=False, deleted_at=None)

        # Filter by user's accessible merchants (multi-tenant)
        # Get merchant IDs that the user can access
        user_role = request.user.role.lower() if request.user.role else ''
        is_super_admin = request.user.is_superuser or user_role == 'super_admin'

        if not is_super_admin:
            merchant_ids = request.user.get_accessible_merchant_ids()
            # Filter by bank accounts that belong to accessible merchants
            queryset = queryset.filter(bank_account__merchant_id__in=merchant_ids)

        # Filter by ID if provided
        transaction_id = request.query_params.get('id', None)
        if transaction_id:
            try:
                queryset = queryset.filter(id=int(transaction_id))
            except ValueError:
                return Response({
                    'error': 'Invalid ID format'
                }, status=status.HTTP_400_BAD_REQUEST)

        # Filter by UTR if provided
        utr = request.query_params.get('utr', None)
        if utr:
            queryset = queryset.filter(utr__icontains=utr)

        # Filter by amount if provided
        amount = request.query_params.get('amount', None)
        if amount:
            try:
                queryset = queryset.filter(amount=int(amount))
            except ValueError:
                pass

        # Filter by bank account if provided
        bank_account_id = request.query_params.get('bank_account', None)
        if bank_account_id:
            try:
                queryset = queryset.filter(bank_account_id=int(bank_account_id))
            except ValueError:
                pass

        # Order by created_at descending (newest first)
        queryset = queryset.order_by('-created_at')

        serializer = ExtractedTransactionSerializer(queryset, many=True)
        return Response({
            'count': queryset.count(),
            'results': serializer.data
        }, status=status.HTTP_200_OK)
