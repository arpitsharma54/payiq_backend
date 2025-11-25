from django.urls import path
from .views import MerchantListView, MerchantDetailView

urlpatterns = [
    path('', MerchantListView.as_view(), name='merchant-list'),
    path('<int:pk>/', MerchantDetailView.as_view(), name='merchant-detail'),
]

