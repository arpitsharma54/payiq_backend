from django.urls import path
from .views import (
    MerchantListView, 
    MerchantDetailView,
    BankAccountListView,
    BankAccountDetailView,
    BankAccountStatusUpdateView,
    StartBotView,
    StopBotView,
    BotStatusView,
)

urlpatterns = [
    path('', MerchantListView.as_view(), name='merchant-list'),
    path('<int:pk>/', MerchantDetailView.as_view(), name='merchant-detail'),
    path('bank-accounts/', BankAccountListView.as_view(), name='bank-account-list'),
    # Bot status route - can get all statuses or specific account via query param
    path('bank-accounts/bot-status/', BotStatusView.as_view(), name='bot-status'),
    path('bank-accounts/<int:pk>/', BankAccountDetailView.as_view(), name='bank-account-detail'),
    path('bank-accounts/<int:pk>/status/', BankAccountStatusUpdateView.as_view(), name='bank-account-status-update'),
    path('bank-accounts/<int:pk>/start-bot/', StartBotView.as_view(), name='start-bot'),
    path('bank-accounts/<int:pk>/stop-bot/', StopBotView.as_view(), name='stop-bot'),
]

