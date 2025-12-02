import re
import logging
from rest_framework import serializers
from .models import CustomUser
from django.contrib.auth import authenticate

logger = logging.getLogger(__name__)


class LoginSerializer(serializers.Serializer):
    """Serializer for login - doesn't extend ModelSerializer to avoid validation issues"""
    username = serializers.CharField(required=True, write_only=True)
    password = serializers.CharField(required=True, write_only=True)

    def validate(self, attrs):
        username = attrs.get('username')
        password = attrs.get('password')
        
        if not username or not password:
            raise serializers.ValidationError({
                'error': 'Username and password are required'
            })
        logger.debug(f'Attempting authentication for username: {username}')
        # Try to authenticate
        user = authenticate(username=username, password=password)
        logger.debug(f'Authentication result: {"Success" if user else "Failed"}')
        if not user:
            # Check if user exists but password might be wrong
            try:
                user_obj = CustomUser.objects.get(username=username)
                # If user exists but authentication failed, password is wrong
                raise serializers.ValidationError({
                    'error': 'Invalid username or password'
                })
            except CustomUser.DoesNotExist:
                # User doesn't exist
                raise serializers.ValidationError({
                    'error': 'Invalid username or password'
                })
        
        # Check if user is active
        if not user.is_active:
            raise serializers.ValidationError({
                'error': 'User account is inactive. Please contact administrator.'
            })
        
        attrs['user'] = user
        return attrs


class UserSerializer(serializers.ModelSerializer):
    """Serializer for user data in login response and user list"""
    last_login = serializers.DateTimeField(format='%d %b %Y, %I:%M %p IST', read_only=True, allow_null=True)
    merchants = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    merchant_names = serializers.SerializerMethodField()
    
    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'email', 'role', 'full_name', 'is_active', 'last_login', 'merchants', 'merchant_names']
        read_only_fields = ['id', 'username', 'email', 'role', 'full_name', 'is_active', 'last_login', 'merchants', 'merchant_names']
    
    def get_merchant_names(self, obj):
        """Return list of merchant names"""
        return [{'id': m.id, 'name': m.name, 'code': m.code} for m in obj.merchants.filter(deleted_at=None)]


class UserCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new users"""
    password = serializers.CharField(write_only=True, required=True, min_length=8)
    
    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'full_name', 'role', 'password', 'is_active', 'merchants']
        extra_kwargs = {
            'username': {'required': True},
            'full_name': {'required': True},
            'role': {'required': True},
        }
    
    def create(self, validated_data):
        merchants = validated_data.pop('merchants', [])
        password = validated_data.pop('password')
        user = CustomUser.objects.create_user(**validated_data)
        user.set_password(password)
        user.save()
        # Assign merchants to user
        if merchants:
            user.merchants.set(merchants)
        return user


class UserUpdateStatusSerializer(serializers.ModelSerializer):
    """Serializer for updating user status (enabled/disabled)"""
    
    class Meta:
        model = CustomUser
        fields = ['is_active']


class UserUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating user merchants"""
    
    class Meta:
        model = CustomUser
        fields = ['merchants']


class UserGeneralUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating general user information (name, email, role, merchants)"""
    
    class Meta:
        model = CustomUser
        fields = ['full_name', 'email', 'role', 'merchants']
        extra_kwargs = {
            'full_name': {'required': False},
            'email': {'required': False},
            'role': {'required': False},
        }
    
    def validate_role(self, value):
        """Prevent changing role to super_admin via API"""
        if value and value.lower() == 'super_admin':
            raise serializers.ValidationError(
                'Super Admin role can only be assigned using Django\'s createsuperuser command.'
            )
        return value
    
    def update(self, instance, validated_data):
        merchants = validated_data.pop('merchants', None)
        # Update other fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        # Update merchants if provided
        if merchants is not None:
            instance.merchants.set(merchants)
        return instance
    
    def update(self, instance, validated_data):
        merchants = validated_data.pop('merchants', None)
        if merchants is not None:
            instance.merchants.set(merchants)
        return instance