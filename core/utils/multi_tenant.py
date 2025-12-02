"""
Utility functions for multi-tenant filtering based on user's assigned merchants
"""
from django.db.models import QuerySet
from accounts.models import CustomUser


def filter_by_user_merchants(queryset: QuerySet, user: CustomUser, merchant_field: str = 'merchant'):
    """
    Filter a queryset to only include records where the merchant is in the user's assigned merchants.
    
    Args:
        queryset: The queryset to filter
        user: The CustomUser instance
        merchant_field: The field name that references the merchant (default: 'merchant')
    
    Returns:
        Filtered queryset
    """
    if user.is_superuser or (user.role and user.role.lower() == 'super_admin'):
        # Superusers and super_admin can see all merchants
        return queryset
    
    # Get merchant IDs the user can access
    merchant_ids = user.get_accessible_merchant_ids()
    
    if not merchant_ids:
        # User has no merchants assigned, return empty queryset
        return queryset.none()
    
    # Filter queryset by merchant IDs
    filter_kwargs = {f'{merchant_field}__id__in': merchant_ids}
    return queryset.filter(**filter_kwargs)

