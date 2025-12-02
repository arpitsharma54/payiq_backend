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
    
    # List and create payins
    path('', PayinListView.as_view(), name='payin-list'),
    
    # Create payment link
    path('create-payment-link/', PayinCreatePaymentLinkView.as_view(), name='payin-create-payment-link'),
    
    # Public payment session endpoint (no authentication required)
    path('public/session/', PayinPublicSessionView.as_view(), name='payin-public-session'),
    
    # Payin detail, update, delete
    path('<int:pk>/', PayinDetailView.as_view(), name='payin-detail'),
    
    # Individual action endpoints
    path('<int:pk>/check-status/', PayinCheckStatusView.as_view(), name='payin-check-status'),
    path('<int:pk>/reset/', PayinResetView.as_view(), name='payin-reset'),
    path('<int:pk>/notify/', PayinNotifyView.as_view(), name='payin-notify'),
    
    # Combined actions endpoint (alternative to individual endpoints)
    path('<int:pk>/actions/<str:action>/', PayinActionsView.as_view(), name='payin-actions'),
]

