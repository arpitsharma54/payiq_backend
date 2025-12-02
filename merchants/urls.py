from django.urls import path
from .views import (
    MerchantListView, 
    MerchantDetailView,
    BankAccountListView,
    BankAccountDetailView,
    BankAccountStatusUpdateView,
)

urlpatterns = [
    path('', MerchantListView.as_view(), name='merchant-list'),
    path('<int:pk>/', MerchantDetailView.as_view(), name='merchant-detail'),
    path('bank-accounts/', BankAccountListView.as_view(), name='bank-account-list'),
    path('bank-accounts/<int:pk>/', BankAccountDetailView.as_view(), name='bank-account-detail'),
    path('bank-accounts/<int:pk>/status/', BankAccountStatusUpdateView.as_view(), name='bank-account-status-update'),
]

