from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from .models import Merchant
from .serializer import MerchantSerializer, MerchantCreateSerializer


class MerchantListView(APIView):
    """
    API view for listing all merchants and creating a new merchant.
    GET: List all merchants
    POST: Create a new merchant
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get list of all merchants (excluding soft-deleted)"""
        merchants = Merchant.objects.all()
        serializer = MerchantSerializer(merchants, many=True)
        return Response({
            'count': merchants.count(),
            'results': serializer.data
        }, status=status.HTTP_200_OK)
    
    def post(self, request):
        """Create a new merchant"""
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
