from rest_framework import serializers
from .models import Merchant


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
    class Meta:
        model = Merchant
        fields = [
            'name',
            'code',
            'site',
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

