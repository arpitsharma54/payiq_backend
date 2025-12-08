from rest_framework import serializers
from .models import Merchant, BankAccount


class MerchantSerializer(serializers.ModelSerializer):
    payin_range = serializers.SerializerMethodField()
    payout_range = serializers.SerializerMethodField()
    
    class Meta:
        model = Merchant
        fields = [
            'id',
            'name',
            'code',
            'site',
            'return_url',
            'callback_url',
            'payout_callback_url',
            'api_key',
            'balance',
            'payin_min',
            'payin_max',
            'payin_commission',
            'payin_range',
            'payout_min',
            'payout_max',
            'payout_commission',
            'payout_range',
            'test_mode',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'balance']
    
    def get_payin_range(self, obj):
        """Returns formatted payin range"""
        return obj.get_payin_range()
    
    def get_payout_range(self, obj):
        """Returns formatted payout range"""
        return obj.get_payout_range()
    
    def validate(self, attrs):
        """Validate that min values are less than max values"""
        if 'payin_min' in attrs and 'payin_max' in attrs:
            if attrs['payin_min'] > attrs['payin_max']:
                raise serializers.ValidationError({
                    'payin_min': 'Payin minimum must be less than or equal to payin maximum.'
                })
        
        if 'payout_min' in attrs and 'payout_max' in attrs:
            if attrs['payout_min'] > attrs['payout_max']:
                raise serializers.ValidationError({
                    'payout_min': 'Payout minimum must be less than or equal to payout maximum.'
                })
        
        return attrs


class MerchantCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating merchants (excludes read-only fields)"""
    api_key = serializers.CharField(read_only=True, help_text="API key is auto-generated")
    
    class Meta:
        model = Merchant
        fields = [
            'name',
            'code',
            'site',
            'return_url',
            'callback_url',
            'payout_callback_url',
            'api_key',
            'payin_min',
            'payin_max',
            'payin_commission',
            'payout_min',
            'payout_max',
            'payout_commission',
            'test_mode',
        ]
    
    def validate(self, attrs):
        """Validate that min values are less than max values"""
        if attrs.get('payin_min', 0) > attrs.get('payin_max', 0):
            raise serializers.ValidationError({
                'payin_min': 'Payin minimum must be less than or equal to payin maximum.'
            })
        
        if attrs.get('payout_min', 0) > attrs.get('payout_max', 0):
            raise serializers.ValidationError({
                'payout_min': 'Payout minimum must be less than or equal to payout maximum.'
            })
        
        return attrs


class BankAccountSerializer(serializers.ModelSerializer):
    """Serializer for BankAccount model"""
    payin_range = serializers.SerializerMethodField()
    balance_display = serializers.SerializerMethodField()
    merchant_name = serializers.CharField(source='merchant.name', read_only=True)
    merchant_code = serializers.CharField(source='merchant.code', read_only=True)
    bank_type_display = serializers.CharField(source='get_bank_type_display', read_only=True)

    class Meta:
        model = BankAccount
        fields = [
            'id',
            'bank_type',
            'bank_type_display',
            'nickname',
            'account_holder_name',
            'account_number',
            'ifsc_code',
            'upi_id',
            'min_payin',
            'max_payin',
            'payin_range',
            'balance',
            'balance_display',
            'transaction_count',
            'is_enabled',
            'is_qr',
            'is_bank',
            'status',
            'is_approved',
            'last_scheduled_at',
            'merchant',
            'merchant_name',
            'merchant_code',
            # Netbanking fields
            'netbanking_url',
            'login_type',
            'username',
            'username2',
            'password',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'balance', 'transaction_count']
    
    def get_payin_range(self, obj):
        """Returns formatted payin range"""
        return obj.get_payin_range()
    
    def get_balance_display(self, obj):
        """Returns formatted balance with transaction count"""
        return obj.get_balance_display()


class BankAccountCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating bank accounts"""
    class Meta:
        model = BankAccount
        fields = [
            'bank_type',
            'nickname',
            'account_holder_name',
            'account_number',
            'ifsc_code',
            'upi_id',
            'min_payin',
            'max_payin',
            'is_enabled',
            'is_qr',
            'is_bank',
            'merchant',
            'status',
            'is_approved',
            # Netbanking fields
            'netbanking_url',
            'login_type',
            'username',
            'username2',
            'password',
        ]
    
    def validate(self, attrs):
        """Validate that min_payin is less than or equal to max_payin"""
        if attrs.get('min_payin', 0) > attrs.get('max_payin', 0):
            raise serializers.ValidationError({
                'min_payin': 'Minimum payin must be less than or equal to maximum payin.'
            })
        
        # Validate that only one bank account per merchant can be enabled
        is_enabled = attrs.get('is_enabled', False)
        merchant = attrs.get('merchant') or (self.instance.merchant if self.instance else None)
        
        if is_enabled and merchant:
            # Check if another bank account for this merchant is already enabled
            other_enabled = BankAccount.objects.filter(
                merchant=merchant,
                is_enabled=True,
                deleted_at=None
            )
            # Exclude self if updating
            if self.instance and self.instance.pk:
                other_enabled = other_enabled.exclude(pk=self.instance.pk)
            
            if other_enabled.exists():
                raise serializers.ValidationError({
                    'is_enabled': 'Only one bank account per merchant can be enabled at a time. Please disable the currently enabled account first.'
                })
        
        return attrs

