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
        if not (request.user.is_superuser or user_role == 'super_admin'):
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
        
        # Allowed status fields
        allowed_fields = ['is_enabled', 'is_qr', 'is_bank', 'status']
        update_data = {k: v for k, v in request.data.items() if k in allowed_fields}
        if not update_data:
            return Response({
                'error': 'No valid status fields provided'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        serializer = BankAccountCreateSerializer(bank_account, data=update_data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated_bank_account = serializer.save()
        # Return full serializer with read-only fields
        response_serializer = BankAccountSerializer(updated_bank_account)
        return Response(response_serializer.data, status=status.HTTP_200_OK)
