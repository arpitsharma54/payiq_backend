from django.contrib import admin
from .models import Merchant, BankAccount, ExtractedTransactions


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'code',
        'site',
        'api_key',
        'balance',
        'get_payin_range_display',
        'payin_commission',
        'get_payout_range_display',
        'payout_commission',
        'test_mode',
        'created_at',
    ]
    list_filter = ['test_mode', 'created_at', 'updated_at']
    search_fields = ['name', 'code', 'api_key', 'site']
    readonly_fields = ['created_at', 'updated_at', 'deleted_at']
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'code', 'site', 'api_key')
        }),
        ('Balance', {
            'fields': ('balance',)
        }),
        ('Payin Configuration', {
            'fields': ('payin_min', 'payin_max', 'payin_commission')
        }),
        ('Payout Configuration', {
            'fields': ('payout_min', 'payout_max', 'payout_commission')
        }),
        ('Settings', {
            'fields': ('test_mode',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'deleted_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_payin_range_display(self, obj):
        return obj.get_payin_range()
    get_payin_range_display.short_description = 'Payin Range'
    
    def get_payout_range_display(self, obj):
        return obj.get_payout_range()
    get_payout_range_display.short_description = 'Payout Range'

@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = [
        'nickname',
        'bank_type',
        'account_holder_name',
        'account_number',
        'merchant',
        'balance',
        'get_payin_range_display',
        'is_enabled',
        'is_approved',
        'is_qr',
        'is_bank',
        'status',
        'created_at',
    ]
    list_filter = ['bank_type', 'is_enabled', 'is_approved', 'is_qr', 'is_bank', 'status', 'login_type', 'merchant', 'created_at']
    search_fields = ['nickname', 'account_holder_name', 'account_number', 'ifsc_code', 'upi_id']
    readonly_fields = ['created_at', 'updated_at', 'deleted_at', 'balance', 'transaction_count']
    fieldsets = (
        ('Bank & Basic Information', {
            'fields': ('bank_type', 'nickname', 'account_holder_name', 'account_number', 'ifsc_code', 'upi_id', 'merchant')
        }),
        ('Payin Limits', {
            'fields': ('min_payin', 'max_payin')
        }),
        ('Balance & Transactions', {
            'fields': ('balance', 'transaction_count')
        }),
        ('Netbanking Details', {
            'fields': ('netbanking_url', 'login_type', 'username', 'username2', 'password'),
            'classes': ('collapse',)
        }),
        ('Status & Flags', {
            'fields': ('is_enabled', 'is_approved', 'is_qr', 'is_bank', 'status')
        }),
        ('Scheduling', {
            'fields': ('last_scheduled_at',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'deleted_at'),
            'classes': ('collapse',)
        }),
    )

    def get_payin_range_display(self, obj):
        return obj.get_payin_range()
    get_payin_range_display.short_description = 'Payin Range'


@admin.register(ExtractedTransactions)
class ExtractedTransactionsAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'bank_account',
        'amount',
        'utr',
        'is_used',
        'created_at',
    ]
    list_filter = ['is_used', 'bank_account', 'created_at']
    search_fields = ['utr', 'bank_account__nickname', 'bank_account__account_number']
    readonly_fields = ['created_at']
    fieldsets = (
        ('Transaction Details', {
            'fields': ('bank_account', 'amount', 'utr', 'is_used')
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )

