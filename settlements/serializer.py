from rest_framework import serializers
from .models import SettlementAccount, Settlement


class SettlementAccountSerializer(serializers.ModelSerializer):
    """Serializer for SettlementAccount model (read operations)"""
    merchant_name = serializers.CharField(source='merchant.name', read_only=True)
    merchant_code = serializers.CharField(source='merchant.code', read_only=True)
    instrument_type_display = serializers.CharField(source='get_instrument_type_display', read_only=True)
    account_type_display = serializers.CharField(source='get_account_type_display', read_only=True)

    class Meta:
        model = SettlementAccount
        fields = [
            'id',
            'merchant',
            'merchant_name',
            'merchant_code',
            'nickname',
            'instrument_type',
            'instrument_type_display',
            'account_type',
            'account_type_display',
            'account_holder_name',
            'account_number',
            'ifsc_code',
            'crypto_wallet_address',
            'crypto_network',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class SettlementAccountCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating settlement accounts"""
    class Meta:
        model = SettlementAccount
        fields = [
            'merchant',
            'nickname',
            'instrument_type',
            'account_type',
            'account_holder_name',
            'account_number',
            'ifsc_code',
            'crypto_wallet_address',
            'crypto_network',
        ]

    def validate(self, attrs):
        """Validate based on instrument type"""
        instrument_type = attrs.get('instrument_type', 'bank')

        if instrument_type == 'bank':
            # Bank details are required
            if not attrs.get('account_holder_name'):
                raise serializers.ValidationError({
                    'account_holder_name': 'Account holder name is required for bank instrument.'
                })
            if not attrs.get('account_number'):
                raise serializers.ValidationError({
                    'account_number': 'Account number is required for bank instrument.'
                })
            if not attrs.get('ifsc_code'):
                raise serializers.ValidationError({
                    'ifsc_code': 'IFSC code is required for bank instrument.'
                })
        elif instrument_type == 'crypto':
            # Crypto details are required
            if not attrs.get('crypto_wallet_address'):
                raise serializers.ValidationError({
                    'crypto_wallet_address': 'Wallet address is required for crypto instrument.'
                })
            if not attrs.get('crypto_network'):
                raise serializers.ValidationError({
                    'crypto_network': 'Network is required for crypto instrument.'
                })

        return attrs


class SettlementSerializer(serializers.ModelSerializer):
    """Serializer for Settlement model (read operations)"""
    merchant_name = serializers.CharField(source='merchant.name', read_only=True)
    merchant_code = serializers.CharField(source='merchant.code', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    method_display = serializers.CharField(source='get_method_display', read_only=True)
    settlement_account_nickname = serializers.CharField(
        source='settlement_account.nickname',
        read_only=True,
        allow_null=True
    )
    to_settlement_account_nickname = serializers.CharField(
        source='to_settlement_account.nickname',
        read_only=True,
        allow_null=True
    )
    to_settlement_account_holder_name = serializers.CharField(
        source='to_settlement_account.account_holder_name',
        read_only=True,
        allow_null=True
    )
    to_settlement_account_number = serializers.CharField(
        source='to_settlement_account.account_number',
        read_only=True,
        allow_null=True
    )
    to_settlement_account_ifsc_code = serializers.CharField(
        source='to_settlement_account.ifsc_code',
        read_only=True,
        allow_null=True
    )
    bank_details_display = serializers.SerializerMethodField()

    class Meta:
        model = Settlement
        fields = [
            'id',
            'merchant',
            'merchant_name',
            'merchant_code',
            'settlement_account',
            'settlement_account_nickname',
            'to_settlement_account',
            'to_settlement_account_nickname',
            'to_settlement_account_holder_name',
            'to_settlement_account_number',
            'to_settlement_account_ifsc_code',
            'amount',
            'status',
            'status_display',
            'method',
            'method_display',
            'bank_account_holder_name',
            'bank_account_number',
            'bank_ifsc_code',
            'bank_details_display',
            'reference_id',
            'notes',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_bank_details_display(self, obj):
        """Returns formatted bank details"""
        return obj.get_bank_details_display()


class SettlementCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating settlements"""
    class Meta:
        model = Settlement
        fields = [
            'merchant',
            'settlement_account',
            'to_settlement_account',
            'amount',
            'bank_account_holder_name',
            'bank_account_number',
            'bank_ifsc_code',
            'reference_id',
            'notes',
        ]

    def validate(self, attrs):
        """Validate settlement data"""
        settlement_account = attrs.get('settlement_account')

        # If settlement_account is provided, bank details will be auto-filled
        # If not, validate that bank details are provided
        if not settlement_account:
            if not attrs.get('bank_account_holder_name'):
                raise serializers.ValidationError({
                    'bank_account_holder_name': 'Account holder name is required when no settlement account is selected.'
                })
            if not attrs.get('bank_account_number'):
                raise serializers.ValidationError({
                    'bank_account_number': 'Account number is required when no settlement account is selected.'
                })
            if not attrs.get('bank_ifsc_code'):
                raise serializers.ValidationError({
                    'bank_ifsc_code': 'IFSC code is required when no settlement account is selected.'
                })

        return attrs


class SettlementUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating settlement status"""
    class Meta:
        model = Settlement
        fields = [
            'status',
            'reference_id',
            'notes',
        ]
