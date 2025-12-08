from django.urls import path
from .views import (
    SettlementAccountListView,
    SettlementAccountDetailView,
    SettlementListView,
    SettlementDetailView,
    SettlementResetView,
)

urlpatterns = [
    # Settlement Accounts
    path('accounts/', SettlementAccountListView.as_view(), name='settlement-account-list'),
    path('accounts/<int:pk>/', SettlementAccountDetailView.as_view(), name='settlement-account-detail'),

    # Settlements (Transactions)
    path('', SettlementListView.as_view(), name='settlement-list'),
    path('<int:pk>/', SettlementDetailView.as_view(), name='settlement-detail'),
    path('<int:pk>/reset/', SettlementResetView.as_view(), name='settlement-reset'),
]
