from django.contrib import admin
from .models import Payin


@admin.register(Payin)
class PayinAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'code',
        'payin_uuid',
        'pay_amount',
        'confirmed_amount',
        'merchant',
        'user',
        'bank',
        'status',
        'utr',
        'created_at',
        'updated_at',
    ]
    list_filter = [
        'status',
        'merchant',
        'bank',
        'created_at',
    ]
    search_fields = [
        'code',
        'payin_uuid',
        'merchant_order_id',
        'utr',
        'user_submitted_utr',
    ]
    readonly_fields = [
        'payin_uuid',
        'code',
        'created_at',
        'updated_at',
        'duration',
    ]
    fieldsets = (
        ('Basic Information', {
            'fields': ('payin_uuid', 'code', 'status', 'merchant', 'user')
        }),
        ('Amounts', {
            'fields': ('pay_amount', 'confirmed_amount')
        }),
        ('Order Details', {
            'fields': ('merchant_order_id', 'bank')
        }),
        ('Transaction References', {
            'fields': ('utr', 'user_submitted_utr')
        }),
        ('Timing', {
            'fields': ('duration', 'created_at', 'updated_at')
        }),
        ('Additional', {
            'fields': ('notes',)
        }),
    )
    ordering = ['-created_at']
