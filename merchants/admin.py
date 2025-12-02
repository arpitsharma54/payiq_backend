from django.contrib import admin
from .models import Merchant


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
