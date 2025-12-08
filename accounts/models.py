from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from core.models.base import SoftDeleteModel

USER_ROLE_CHOICES = [
    ('super_admin', 'Super Admin'),
    ('admin', 'Admin'),
]

class CustomUserManager(BaseUserManager):
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError('The Username field must be set')
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
        
    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('role', 'super_admin')  # Set role to super_admin for superusers

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        return self.create_user(username, password=password, **extra_fields)

class CustomUser(AbstractBaseUser, SoftDeleteModel, PermissionsMixin):
    full_name = models.CharField(max_length=255)
    username = models.CharField(max_length=255, unique=True)
    role = models.CharField(max_length=255, choices=USER_ROLE_CHOICES)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    merchants = models.ManyToManyField(
        'merchants.Merchant',
        related_name='users',
        blank=True,
        help_text="Merchants this user can access"
    )

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['full_name', 'role']

    objects = CustomUserManager()

    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
    
    def get_accessible_merchant_ids(self):
        """Return list of merchant IDs this user can access"""
        if self.is_superuser or (self.role and self.role.lower() == 'super_admin'):
            # Superusers and super_admin can access all merchants
            from merchants.models import Merchant
            return list(Merchant.objects.filter(deleted_at=None).values_list('id', flat=True))
        return list(self.merchants.filter(deleted_at=None).values_list('id', flat=True))