from rest_framework import serializers
from .models import Payin
from merchants.serializer import MerchantSerializer
from accounts.models import CustomUser


class PayinSerializer(serializers.ModelSerializer):
    """Serializer for Payin with nested merchant and user information"""
    merchant_name = serializers.CharField(source='merchant.name', read_only=True)
    merchant_code = serializers.CharField(source='merchant.code', read_only=True)
    duration_display = serializers.SerializerMethodField()
    
    class Meta:
        model = Payin
        fields = [
            'id',
            'payin_uuid',
            'code',
            'pay_amount',
            'confirmed_amount',
            'merchant',
            'merchant_name',
            'merchant_code',
            'merchant_order_id',
            'user',
            'bank',
            'utr',
            'user_submitted_utr',
            'status',
            'duration',
            'duration_display',
            'notes',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'payin_uuid',
            'code',
            'duration',
            'created_at',
            'updated_at',
        ]
    
    def get_duration_display(self, obj):
        """Returns formatted duration string"""
        return obj.get_duration_display()


class PayinCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a new Payin"""
    
    class Meta:
        model = Payin
        fields = [
            'pay_amount',
            'merchant',
            'user',
            'merchant_order_id',
            'bank',
            'notes',
        ]
    
    def validate(self, attrs):
        """Validate payin data"""
        merchant = attrs.get('merchant')
        pay_amount = attrs.get('pay_amount')
        
        if merchant:
            # Check if merchant has at least one enabled bank account
            from merchants.models import BankAccount
            enabled_accounts = BankAccount.objects.filter(
                merchant=merchant,
                is_enabled=True,
                deleted_at=None
            )
            if not enabled_accounts.exists():
                raise serializers.ValidationError({
                    'merchant': 'Cannot create payment link. No enabled bank accounts found for this merchant. Please enable at least one bank account first.'
                })
            
            if pay_amount:
                # Check if amount is within merchant's payin range
                if merchant.payin_min > 0 and pay_amount < merchant.payin_min:
                    raise serializers.ValidationError({
                        'pay_amount': f'Amount must be at least ₹{merchant.payin_min}'
                    })
                if merchant.payin_max > 0 and pay_amount > merchant.payin_max:
                    raise serializers.ValidationError({
                        'pay_amount': f'Amount must not exceed ₹{merchant.payin_max}'
                    })
        
        return attrs
    
    def create(self, validated_data):
        """Create a new payin with auto-generated code"""
        # Generate a unique code if not provided
        import random
        import string
        
        while True:
            code = ''.join(random.choices(string.ascii_letters + string.digits, k=5))
            if not Payin.objects.filter(code=code).exists():
                validated_data['code'] = code
                break
        
        return super().create(validated_data)


class PayinUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating a Payin"""
    
    class Meta:
        model = Payin
        fields = [
            'confirmed_amount',
            'status',
            'utr',
            'user_submitted_utr',
            'bank',
            'notes',
        ]
    
    def validate(self, attrs):
        """Validate update data"""
        status = attrs.get('status')
        instance = self.instance
        
        # If status is being changed to success, calculate duration
        if status == 'success' and instance:
            if not instance.duration:
                instance.calculate_duration()
        
        return attrs


class PayinListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing payins"""
    merchant_name = serializers.CharField(source='merchant.name', read_only=True)
    merchant_code = serializers.CharField(source='merchant.code', read_only=True)
    duration_display = serializers.SerializerMethodField()
    
    class Meta:
        model = Payin
        fields = [
            'id',
            'code',
            'payin_uuid',
            'confirmed_amount',
            'merchant_order_id',
            'merchant_name',
            'merchant_code',
            'user',
            'bank',
            'status',
            'duration_display',
            'pay_amount',
            'utr',
            'user_submitted_utr',
            'updated_at',
        ]
    
    def get_duration_display(self, obj):
        """Returns formatted duration string"""
        return obj.get_duration_display()

