from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from .models import SettlementAccount, Settlement
from core.utils.multi_tenant import filter_by_user_merchants
from .serializer import (
    SettlementAccountSerializer,
    SettlementAccountCreateSerializer,
    SettlementSerializer,
    SettlementCreateSerializer,
    SettlementUpdateSerializer
)


class SettlementAccountListView(APIView):
    """
    API view for listing all settlement accounts and creating a new settlement account.
    GET: List all settlement accounts
    POST: Create a new settlement account
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get list of all settlement accounts (excluding soft-deleted) with optional filters"""
        queryset = SettlementAccount.objects.filter(deleted_at=None)

        # Filter by user's accessible merchants (multi-tenant)
        queryset = filter_by_user_merchants(queryset, request.user, 'merchant')

        # Apply filters
        nickname = request.query_params.get('nickname', '').strip()
        merchant_id = request.query_params.get('merchant', '').strip()
        instrument_type = request.query_params.get('instrument_type', '').strip()

        if nickname:
            queryset = queryset.filter(nickname__icontains=nickname)
        if merchant_id:
            queryset = queryset.filter(merchant_id=merchant_id)
        if instrument_type:
            queryset = queryset.filter(instrument_type=instrument_type)

        serializer = SettlementAccountSerializer(queryset, many=True)
        return Response({
            'count': queryset.count(),
            'results': serializer.data
        }, status=status.HTTP_200_OK)

    def post(self, request):
        """Create a new settlement account"""
        user_role = request.user.role.lower() if request.user.role else ''
        if not (request.user.is_superuser or user_role in ['super_admin', 'admin']):
            return Response({
                'error': 'Only admins can create settlement accounts'
            }, status=status.HTTP_403_FORBIDDEN)

        serializer = SettlementAccountCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        settlement_account = serializer.save()
        # Return full serializer with read-only fields
        response_serializer = SettlementAccountSerializer(settlement_account)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class SettlementAccountDetailView(APIView):
    """
    API view for retrieving, updating, and deleting a specific settlement account.
    GET: Retrieve a settlement account
    PUT: Update a settlement account (full update)
    PATCH: Update a settlement account (partial update)
    DELETE: Delete a settlement account (soft delete)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        """Get a specific settlement account by ID"""
        settlement_account = get_object_or_404(SettlementAccount, pk=pk, deleted_at=None)
        serializer = SettlementAccountSerializer(settlement_account)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, pk):
        """Full update of a settlement account"""
        settlement_account = get_object_or_404(SettlementAccount, pk=pk, deleted_at=None)
        serializer = SettlementAccountCreateSerializer(settlement_account, data=request.data)
        serializer.is_valid(raise_exception=True)
        updated_account = serializer.save()
        response_serializer = SettlementAccountSerializer(updated_account)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, pk):
        """Partial update of a settlement account"""
        settlement_account = get_object_or_404(SettlementAccount, pk=pk, deleted_at=None)
        serializer = SettlementAccountCreateSerializer(settlement_account, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated_account = serializer.save()
        response_serializer = SettlementAccountSerializer(updated_account)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        """Soft delete a settlement account"""
        settlement_account = get_object_or_404(SettlementAccount, pk=pk, deleted_at=None)
        settlement_account.soft_delete()
        return Response({
            'message': 'Settlement account deleted successfully'
        }, status=status.HTTP_200_OK)


class SettlementListView(APIView):
    """
    API view for listing all settlements and creating a new settlement.
    GET: List all settlements
    POST: Create a new settlement
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get list of all settlements (excluding soft-deleted) with optional filters"""
        queryset = Settlement.objects.filter(deleted_at=None)

        # Filter by user's accessible merchants (multi-tenant)
        queryset = filter_by_user_merchants(queryset, request.user, 'merchant')

        # Apply filters
        settlement_id = request.query_params.get('id', '').strip()
        merchant_id = request.query_params.get('merchant', '').strip()
        settlement_status = request.query_params.get('status', '').strip()

        if settlement_id:
            queryset = queryset.filter(id=settlement_id)
        if merchant_id:
            queryset = queryset.filter(merchant_id=merchant_id)
        if settlement_status:
            queryset = queryset.filter(status=settlement_status)

        serializer = SettlementSerializer(queryset, many=True)
        return Response({
            'count': queryset.count(),
            'results': serializer.data
        }, status=status.HTTP_200_OK)

    def post(self, request):
        """Create a new settlement"""
        user_role = request.user.role.lower() if request.user.role else ''
        if not (request.user.is_superuser or user_role in ['super_admin', 'admin']):
            return Response({
                'error': 'Only admins can create settlements'
            }, status=status.HTTP_403_FORBIDDEN)

        serializer = SettlementCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        settlement = serializer.save()
        # Return full serializer with read-only fields
        response_serializer = SettlementSerializer(settlement)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class SettlementDetailView(APIView):
    """
    API view for retrieving, updating, and deleting a specific settlement.
    GET: Retrieve a settlement
    PATCH: Update a settlement (status, reference_id, notes)
    DELETE: Delete a settlement (soft delete)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        """Get a specific settlement by ID"""
        settlement = get_object_or_404(Settlement, pk=pk, deleted_at=None)
        serializer = SettlementSerializer(settlement)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, pk):
        """Update settlement status and reference"""
        settlement = get_object_or_404(Settlement, pk=pk, deleted_at=None)
        serializer = SettlementUpdateSerializer(settlement, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated_settlement = serializer.save()
        response_serializer = SettlementSerializer(updated_settlement)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        """Soft delete a settlement"""
        settlement = get_object_or_404(Settlement, pk=pk, deleted_at=None)
        settlement.soft_delete()
        return Response({
            'message': 'Settlement deleted successfully'
        }, status=status.HTTP_200_OK)


class SettlementResetView(APIView):
    """
    API view for resetting a settlement status to pending.
    POST: Reset settlement status
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        """Reset settlement status to pending"""
        settlement = get_object_or_404(Settlement, pk=pk, deleted_at=None)

        user_role = request.user.role.lower() if request.user.role else ''
        if not (request.user.is_superuser or user_role in ['super_admin', 'admin']):
            return Response({
                'error': 'Only admins can reset settlements'
            }, status=status.HTTP_403_FORBIDDEN)

        settlement.status = 'pending'
        settlement.reference_id = None
        settlement.save()

        response_serializer = SettlementSerializer(settlement)
        return Response(response_serializer.data, status=status.HTTP_200_OK)
