from django.urls import path
from .views import (
    DashboardView,
    PayinListView,
    PayinDetailView,
    PayinCheckStatusView,
    PayinResetView,
    PayinNotifyView,
    PayinActionsView,
    PayinCreatePaymentLinkView,
    PayinPublicSessionView,
)

urlpatterns = [
    # Dashboard
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    
    # Public payment session endpoint (no authentication required)
    # This must come BEFORE the empty path to ensure it's matched correctly
    path('public/session/', PayinPublicSessionView.as_view(), name='payin-public-session'),
    
    # Create payment link
    path('create-payment-link/', PayinCreatePaymentLinkView.as_view(), name='payin-create-payment-link'),
    
    # Payin detail, update, delete (must come before list to avoid matching)
    path('<int:pk>/', PayinDetailView.as_view(), name='payin-detail'),
    
    # Individual action endpoints
    path('<int:pk>/check-status/', PayinCheckStatusView.as_view(), name='payin-check-status'),
    path('<int:pk>/reset/', PayinResetView.as_view(), name='payin-reset'),
    path('<int:pk>/notify/', PayinNotifyView.as_view(), name='payin-notify'),
    
    # Combined actions endpoint (alternative to individual endpoints)
    path('<int:pk>/actions/<str:action>/', PayinActionsView.as_view(), name='payin-actions'),
    
    # List and create payins (must be last as it's a catch-all)
    path('', PayinListView.as_view(), name='payin-list'),
]

