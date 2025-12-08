from django.contrib import admin
from .models import SettlementAccount, Settlement


@admin.register(SettlementAccount)
class SettlementAccountAdmin(admin.ModelAdmin):
    list_display = ['id', 'nickname', 'merchant', 'instrument_type', 'account_holder_name', 'account_number', 'created_at']
    list_filter = ['instrument_type', 'merchant']
    search_fields = ['nickname', 'account_holder_name', 'account_number']
    ordering = ['-created_at']


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = ['id', 'merchant', 'amount', 'status', 'method', 'reference_id', 'created_at']
    list_filter = ['status', 'method', 'merchant']
    search_fields = ['reference_id', 'bank_account_holder_name', 'bank_account_number']
    ordering = ['-created_at']
