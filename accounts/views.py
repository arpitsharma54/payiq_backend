from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework import status
from rest_framework.exceptions import ValidationError, PermissionDenied
from .serializer import LoginSerializer, UserSerializer, UserCreateSerializer, UserUpdateStatusSerializer, UserUpdateSerializer, UserGeneralUpdateSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from .models import CustomUser


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        
        if not serializer.is_valid():
            # Return validation errors
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            user = serializer.validated_data['user']
            
            # Check if user is active
            if not user.is_active:
                return Response(
                    {'error': 'User account is inactive. Please contact administrator.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Update last_login timestamp
            from django.utils import timezone
            user.last_login = timezone.now()
            user.save(update_fields=['last_login'])
            
            token = RefreshToken.for_user(user)
            
            # Serialize user data
            user_serializer = UserSerializer(user)
            
            data = {
                'refresh': str(token),
                'access': str(token.access_token),
                **user_serializer.data
            }
            return Response(data, status=status.HTTP_200_OK)
            
        except KeyError:
            # User not found in validated_data (authentication failed)
            return Response(
                {'error': 'Invalid username or password'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'error': 'An error occurred during login. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class UserListView(APIView):
    """List all users"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get list of all users (excluding superusers)"""
        users = CustomUser.objects.filter(
            deleted_at=None,
            is_superuser=False
        )
        
        # Filter by merchant access (multi-tenant)
        # If user is not super_admin, only show users that share at least one merchant
        user_role = request.user.role.lower() if request.user.role else ''
        if not (request.user.is_superuser or user_role == 'super_admin'):
            # Get current user's accessible merchant IDs
            current_user_merchant_ids = request.user.get_accessible_merchant_ids()
            
            if current_user_merchant_ids:
                # Filter users that have at least one merchant in common
                users = users.filter(merchants__id__in=current_user_merchant_ids).distinct()
            else:
                # User has no merchants, return empty queryset
                users = users.none()
        
        users = users.order_by('-id')
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class UserCreateView(APIView):
    """Create a new user - Admin only"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Create a new user"""
        # Check if user is admin or superuser
        user_role = request.user.role.lower() if request.user.role else ''
        is_superuser = request.user.is_superuser
        is_super_admin = user_role == 'super_admin'
        
        if not (is_superuser or is_super_admin):
            user_role_display = request.user.role or 'None'
            return Response(
                {
                    'error': {
                        'status_code': 403,
                        'message': f'You do not have permission to create new users. Only users with the "admin" role can create new users. Your current role is: "{user_role_display}". Please contact an administrator if you need this permission.'
                    }
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Prevent creating super_admin users through API
        requested_role = request.data.get('role', '').lower()
        if requested_role == 'super_admin':
            return Response(
                {
                    'error': {
                        'status_code': 403,
                        'message': 'Super Admin role can only be created using Django\'s createsuperuser command. It cannot be created through the API.'
                    }
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = UserCreateSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            user_serializer = UserSerializer(user)
            return Response(user_serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserUpdateStatusView(APIView):
    """Update user status (enabled/disabled) - Admin only"""
    permission_classes = [IsAuthenticated]

    def patch(self, request, user_id):
        """Update user is_active status"""
        # Check if user is admin, super_admin, or superuser
        user_role = request.user.role.lower() if request.user.role else ''
        is_admin = user_role == 'admin'
        is_super_admin = user_role == 'super_admin'
        is_superuser = request.user.is_superuser
        
        if not (is_admin or is_super_admin or is_superuser):
            return Response(
                {
                    'error': {
                        'status_code': 403,
                        'message': 'You do not have permission to enable or disable users. Only users with the "admin" role can perform this action.'
                    }
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            user = CustomUser.objects.get(id=user_id, deleted_at=None)
        except CustomUser.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = UserUpdateStatusSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            user_serializer = UserSerializer(user)
            return Response(user_serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserUpdateView(APIView):
    """Update user information - Admin only"""
    permission_classes = [IsAuthenticated]

    def patch(self, request, user_id):
        """Update user information (general info or merchants)"""
        # Check if user is admin, super_admin, or superuser
        user_role = request.user.role.lower() if request.user.role else ''
        is_admin = user_role == 'admin'
        is_super_admin = user_role == 'super_admin'
        is_superuser = request.user.is_superuser
        
        if not (is_admin or is_super_admin or is_superuser):
            return Response(
                {
                    'error': {
                        'status_code': 403,
                        'message': 'You do not have permission to update users. Only users with the "admin" role can perform this action.'
                    }
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            user = CustomUser.objects.get(id=user_id, deleted_at=None)
        except CustomUser.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if only merchants are being updated (backward compatibility)
        if 'merchants' in request.data and len(request.data) == 1:
            serializer = UserUpdateSerializer(user, data=request.data, partial=True)
        else:
            # General update (full_name, email, role, merchants)
            serializer = UserGeneralUpdateSerializer(user, data=request.data, partial=True)
        
        if serializer.is_valid():
            serializer.save()
            user_serializer = UserSerializer(user)
            return Response(user_serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)