from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django import forms
from accounts.models import CustomUser


class CustomUserAdmin(BaseUserAdmin):
    """Admin interface for CustomUser model with proper password handling"""
    form = UserChangeForm
    add_form = UserCreationForm
    
    list_display = ('username', 'full_name', 'role', 'is_active', 'is_staff', 'is_superuser')
    list_filter = ('role', 'is_active', 'is_staff', 'is_superuser', 'created_at')
    search_fields = ('username', 'full_name')
    list_per_page = 10
    ordering = ('username',)
    
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('full_name',)}),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Role', {'fields': ('role',)}),
        ('Important dates', {'fields': ('last_login', 'created_at', 'updated_at')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'full_name', 'role', 'password1', 'password2'),
        }),
    )
    
    readonly_fields = ('last_login', 'created_at', 'updated_at')
    
    def save_model(self, request, obj, form, change):
        """Save user model - password handling is done by Django's forms"""
        # For existing users, Django's UserChangeForm handles password correctly:
        # - The password field is read-only and shows hash info
        # - Password changes should be done via the password reset form
        # - We should NOT touch the password here to avoid accidentally changing it
        
        # For new users, Django's UserCreationForm handles password hashing automatically
        # Just call the parent save_model which handles everything correctly
        super().save_model(request, obj, form, change)


admin.site.register(CustomUser, CustomUserAdmin)