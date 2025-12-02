from django.urls import path
from .views import LoginView, UserListView, UserCreateView, UserUpdateStatusView, UserUpdateView

urlpatterns = [
    path('login/', LoginView.as_view(), name='user-login'),
    path('users/', UserListView.as_view(), name='user-list'),
    path('users/create/', UserCreateView.as_view(), name='user-create'),
    path('users/<int:user_id>/status/', UserUpdateStatusView.as_view(), name='user-update-status'),
    path('users/<int:user_id>/', UserUpdateView.as_view(), name='user-update'),
]