from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db.models import Q
from .models import Merchant, BankAccount
from core.utils.multi_tenant import filter_by_user_merchants
from .serializer import (
    MerchantSerializer, 
    MerchantCreateSerializer,
    BankAccountSerializer,

    BankAccountCreateSerializer
)
from deposit.task import run_single_bot
from payiq.celery import app
from django.conf import settings
import redis

# Connect to Redis
redis_client = redis.Redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)


class MerchantListView(APIView):
    """
    API view for listing all merchants and creating a new merchant.
    GET: List all merchants
    POST: Create a new merchant
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get list of all merchants (excluding soft-deleted)"""
        merchants = Merchant.objects.filter(deleted_at=None)
        # Filter by user's accessible merchants (multi-tenant)
        merchant_ids = request.user.get_accessible_merchant_ids()
        user_role = request.user.role.lower() if request.user.role else ''
        if not (request.user.is_superuser or user_role == 'super_admin'):
            merchants = merchants.filter(id__in=merchant_ids)
        serializer = MerchantSerializer(merchants, many=True)
        return Response({
            'count': merchants.count(),
            'results': serializer.data
        }, status=status.HTTP_200_OK)
    
    def post(self, request):
        """Create a new merchant - Only super_admin can create merchants"""
        user_role = request.user.role.lower() if request.user.role else ''
        if not (request.user.is_superuser or user_role == 'super_admin'):
            return Response({
                'error': 'Only super_admin can create merchants'
            }, status=status.HTTP_403_FORBIDDEN)
        
        serializer = MerchantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        merchant = serializer.save()
        # Return full serializer with read-only fields
        response_serializer = MerchantSerializer(merchant)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class MerchantDetailView(APIView):
    """
    API view for retrieving, updating, and deleting a specific merchant.
    GET: Retrieve a merchant
    PUT: Update a merchant (full update)
    PATCH: Update a merchant (partial update)
    DELETE: Delete a merchant (soft delete)
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, pk):
        """Get a specific merchant by ID"""
        merchant = get_object_or_404(Merchant, pk=pk)
        serializer = MerchantSerializer(merchant)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def put(self, request, pk):
        """Full update of a merchant"""
        merchant = get_object_or_404(Merchant, pk=pk)
        serializer = MerchantCreateSerializer(merchant, data=request.data)
        serializer.is_valid(raise_exception=True)
        updated_merchant = serializer.save()
        # Return full serializer with read-only fields
        response_serializer = MerchantSerializer(updated_merchant)
        return Response(response_serializer.data, status=status.HTTP_200_OK)
    
    def patch(self, request, pk):
        """Partial update of a merchant"""
        merchant = get_object_or_404(Merchant, pk=pk)
        serializer = MerchantCreateSerializer(merchant, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated_merchant = serializer.save()
        # Return full serializer with read-only fields
        response_serializer = MerchantSerializer(updated_merchant)
        return Response(response_serializer.data, status=status.HTTP_200_OK)
    
    def delete(self, request, pk):
        """Soft delete a merchant"""
        merchant = get_object_or_404(Merchant, pk=pk)
        merchant.soft_delete()
        return Response({
            'message': 'Merchant deleted successfully'
        }, status=status.HTTP_200_OK)


class BankAccountListView(APIView):
    """
    API view for listing all bank accounts and creating a new bank account.
    GET: List all bank accounts (with optional filters)
    POST: Create a new bank account
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get list of all bank accounts (excluding soft-deleted) with optional filters"""
        queryset = BankAccount.objects.filter(deleted_at=None)
        
        # Filter by user's accessible merchants (multi-tenant)
        queryset = filter_by_user_merchants(queryset, request.user, 'merchant')
        
        # Apply filters
        nickname = request.query_params.get('nickname', '').strip()
        upi_id = request.query_params.get('upi_id', '').strip()
        
        if nickname:
            queryset = queryset.filter(nickname__icontains=nickname)
        if upi_id:
            queryset = queryset.filter(upi_id__icontains=upi_id)
        
        serializer = BankAccountSerializer(queryset, many=True)
        return Response({
            'count': queryset.count(),
            'results': serializer.data
        }, status=status.HTTP_200_OK)
    
    def post(self, request):
        """Create a new bank account - Only super_admin can create bank accounts"""
        user_role = request.user.role.lower() if request.user.role else ''
        if not (request.user.is_superuser or user_role == 'super_admin' or user_role == 'admin'):
            return Response({
                'error': 'Only super_admin can create bank accounts'
            }, status=status.HTTP_403_FORBIDDEN)
        
        serializer = BankAccountCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bank_account = serializer.save()
        # Return full serializer with read-only fields
        response_serializer = BankAccountSerializer(bank_account)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class BankAccountDetailView(APIView):
    """
    API view for retrieving, updating, and deleting a specific bank account.
    GET: Retrieve a bank account
    PUT: Update a bank account (full update)
    PATCH: Update a bank account (partial update)
    DELETE: Delete a bank account (soft delete)
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, pk):
        """Get a specific bank account by ID"""
        bank_account = get_object_or_404(BankAccount, pk=pk)
        serializer = BankAccountSerializer(bank_account)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def put(self, request, pk):
        """Full update of a bank account"""
        bank_account = get_object_or_404(BankAccount, pk=pk)
        serializer = BankAccountCreateSerializer(bank_account, data=request.data)
        serializer.is_valid(raise_exception=True)
        updated_bank_account = serializer.save()
        # Return full serializer with read-only fields
        response_serializer = BankAccountSerializer(updated_bank_account)
        return Response(response_serializer.data, status=status.HTTP_200_OK)
    
    def patch(self, request, pk):
        """Partial update of a bank account"""
        bank_account = get_object_or_404(BankAccount, pk=pk)
        serializer = BankAccountCreateSerializer(bank_account, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated_bank_account = serializer.save()
        # Return full serializer with read-only fields
        response_serializer = BankAccountSerializer(updated_bank_account)
        return Response(response_serializer.data, status=status.HTTP_200_OK)
    
    def delete(self, request, pk):
        """Soft delete a bank account"""
        bank_account = get_object_or_404(BankAccount, pk=pk)
        bank_account.soft_delete()
        return Response({
            'message': 'Bank account deleted successfully'
        }, status=status.HTTP_200_OK)


class BankAccountStatusUpdateView(APIView):
    """
    API view for updating specific status fields of a bank account.
    PATCH: Update status fields (is_enabled, is_qr, is_bank, status)
    """
    permission_classes = [IsAuthenticated]
    
    def patch(self, request, pk):
        """Update status fields of a bank account"""
        bank_account = get_object_or_404(BankAccount, pk=pk)

        # Check if user is super_admin for is_approved field
        user_role = request.user.role.lower() if request.user.role else ''
        is_super_admin = request.user.is_superuser or user_role == 'super_admin'

        # Allowed status fields - is_approved only for super_admin
        allowed_fields = ['is_enabled', 'is_qr', 'is_bank', 'status']
        if is_super_admin:
            allowed_fields.append('is_approved')

        update_data = {k: v for k, v in request.data.items() if k in allowed_fields}
        if not update_data:
            return Response({
                'error': 'No valid status fields provided'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # If enabling this account, ensure merchant is included in update_data for validation
        if 'is_enabled' in update_data and update_data['is_enabled']:
            update_data['merchant'] = bank_account.merchant_id
        
        serializer = BankAccountCreateSerializer(bank_account, data=update_data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated_bank_account = serializer.save()
        # Return full serializer with read-only fields
        response_serializer = BankAccountSerializer(updated_bank_account)
        return Response(response_serializer.data, status=status.HTTP_200_OK)



class StartBotView(APIView):
    """
    API view for starting the bot for a specific bank account.
    POST: Start bot
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        bank_account = get_object_or_404(BankAccount, pk=pk)
        
        # Check if already running
        lock_key = f'celery_task_run_bot_lock_{pk}'
        if redis_client.get(lock_key):
             return Response({
                'message': 'Bot is already running for this account'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Check if Celery workers are running
        try:
            inspect = app.control.inspect()
            active_workers = inspect.active()
            if not active_workers:
                return Response({
                    'message': 'Celery workers are not running. Please start Celery workers to execute bot tasks.',
                    'error': 'WORKERS_NOT_RUNNING',
                    'help': 'Run: celery -A payiq worker --beat --loglevel=info'
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as e:
            # If inspection fails, still try to queue the task
            # but warn the user
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Could not inspect Celery workers: {str(e)}")

        # Send initial status update
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                "task_status_updates",
                {
                    "type": "task_update",
                    "status": "starting",
                    "message": f"Bot starting in continuous mode (interval: {getattr(settings, 'BOT_EXECUTION_INTERVAL', 60)}s)",
                    "bank_account_id": pk,
                    "merchant_id": bank_account.merchant_id,
                }
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Could not send WebSocket status update: {str(e)}")
        
        # Trigger task
        task = run_single_bot.delay(pk)
        
        return Response({
            'message': f'Bot started successfully in continuous mode (interval: {getattr(settings, "BOT_EXECUTION_INTERVAL", 60)}s)',
            'task_id': task.id,
            'interval': getattr(settings, 'BOT_EXECUTION_INTERVAL', 60)
        }, status=status.HTTP_200_OK)


class StopBotView(APIView):
    """
    API view for stopping the bot for a specific bank account.
    POST: Stop bot
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        bank_account = get_object_or_404(BankAccount, pk=pk)
        
        # Get task ID from lock
        lock_key = f'celery_task_run_bot_lock_{pk}'
        stop_flag_key = f'bot_stop_flag_{pk}'
        task_id = redis_client.get(lock_key)
        
        if not task_id:
            return Response({
                'message': 'Bot is not running for this account'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Set stop flag to signal the continuous loop to stop
        redis_client.set(stop_flag_key, '1', ex=300)  # Expires in 5 minutes as safety
        
        # Send status update via WebSocket before stopping
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                "task_status_updates",
                {
                    "type": "task_update",
                    "status": "stopping",
                    "message": "Bot stop signal sent, stopping after current iteration...",
                    "bank_account_id": pk,
                    "merchant_id": bank_account.merchant_id,
                }
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Could not send WebSocket status update: {str(e)}")
        
        # Try graceful stop first (let current iteration finish)
        # The task will check the stop flag and exit the loop
        # If task doesn't stop within reasonable time, we can revoke it
        
        return Response({
            'message': 'Bot stop signal sent. Bot will stop after current iteration completes.'
        }, status=status.HTTP_200_OK)


class BotStatusView(APIView):
    """
    API view for getting bot status for bank accounts.
    GET: Get bot status for all bank accounts or a specific one
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Get bot status for bank accounts.
        Query params:
        - account_id (optional): Get status for specific account. If not provided, returns all.
        """
        account_id = request.query_params.get('account_id')
        
        if account_id:
            try:
                pk = int(account_id)
            except (ValueError, TypeError):
                return Response({
                    'error': 'Invalid account_id parameter'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get status for specific bank account
            bank_account = get_object_or_404(BankAccount, pk=pk)
            lock_key = f'celery_task_run_bot_lock_{pk}'
            task_id = redis_client.get(lock_key)
            
            is_running = task_id is not None
            
            # Check if task is actually active in Celery
            status_detail = 'idle'
            if is_running:
                try:
                    inspect = app.control.inspect()
                    active_tasks = inspect.active()
                    if active_tasks:
                        # Check if this task is in any worker's active tasks
                        task_found = False
                        for worker, tasks in active_tasks.items():
                            for task in tasks:
                                if task.get('id') == task_id:
                                    task_found = True
                                    status_detail = 'running'
                                    break
                            if task_found:
                                break
                        if not task_found:
                            # Lock exists but task not active - clean up
                            redis_client.delete(lock_key)
                            is_running = False
                            status_detail = 'idle'
                except Exception:
                    # If inspection fails, assume running if lock exists
                    status_detail = 'running' if is_running else 'idle'
            
            return Response({
                'bank_account_id': pk,
                'is_running': is_running,
                'status': status_detail,
                'task_id': task_id if is_running else None
            }, status=status.HTTP_200_OK)
        else:
            # Get status for all accessible bank accounts
            queryset = BankAccount.objects.filter(deleted_at=None)
            queryset = filter_by_user_merchants(queryset, request.user, 'merchant')
            
            statuses = {}
            try:
                inspect = app.control.inspect()
                active_tasks = inspect.active() or {}
                active_task_ids = set()
                for worker, tasks in active_tasks.items():
                    for task in tasks:
                        active_task_ids.add(task.get('id'))
            except Exception:
                active_task_ids = set()
            
            for account in queryset:
                lock_key = f'celery_task_run_bot_lock_{account.id}'
                task_id = redis_client.get(lock_key)
                is_running = task_id is not None and task_id in active_task_ids
                
                # Clean up stale locks
                if task_id and task_id not in active_task_ids:
                    redis_client.delete(lock_key)
                    is_running = False
                
                statuses[account.id] = {
                    'is_running': is_running,
                    'status': 'running' if is_running else 'idle',
                    'task_id': task_id if is_running else None
                }
            
            return Response({
                'statuses': statuses
            }, status=status.HTTP_200_OK)
