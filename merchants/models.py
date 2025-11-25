from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal
from core.models.base import SoftDeleteModel


class Merchant(SoftDeleteModel):
    name = models.CharField(max_length=255, help_text="Merchant name")
    code = models.CharField(max_length=100, unique=True, help_text="Unique merchant code")
    site = models.URLField(max_length=500, help_text="Merchant site URL")
    api_key = models.CharField(max_length=255, unique=True, help_text="API key for merchant")
    
    # Balance field (can be negative)
    balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Current balance"
    )
    
    # Payin configuration
    payin_min = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Minimum payin amount"
    )
    payin_max = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Maximum payin amount"
    )
    payin_commission = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('100.00'))],
        help_text="Payin commission percentage"
    )
    
    # Payout configuration
    payout_min = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Minimum payout amount"
    )
    payout_max = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Maximum payout amount"
    )
    payout_commission = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('100.00'))],
        help_text="Payout commission percentage"
    )
    
    # Test mode flag
    test_mode = models.BooleanField(default=False, help_text="Enable test mode")
    
    class Meta:
        db_table = 'merchants'
        verbose_name = 'Merchant'
        verbose_name_plural = 'Merchants'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} ({self.code})"
    
    def get_payin_range(self):
        """Returns formatted payin range string"""
        return f"₹{self.payin_min} - ₹{self.payin_max}"
    
    def get_payout_range(self):
        """Returns formatted payout range string"""
        return f"₹{self.payout_min} - ₹{self.payout_max}"
