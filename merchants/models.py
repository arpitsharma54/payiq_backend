import os
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal
import secrets
from core.models.base import SoftDeleteModel


# Bank type choices for the bot system
BANK_TYPE_CHOICES = [
    ('iob', 'Indian Overseas Bank (IOB)'),
    ('sbi', 'State Bank of India (SBI)'),
    ('hdfc', 'HDFC Bank'),
    ('icici', 'ICICI Bank'),
    ('axis', 'Axis Bank'),
    ('kotak', 'Kotak Mahindra Bank'),
    ('pnb', 'Punjab National Bank (PNB)'),
    ('bob', 'Bank of Baroda (BOB)'),
    ('canara', 'Canara Bank'),
    ('union', 'Union Bank of India'),
    ('idbi', 'IDBI Bank'),
    ('yes', 'Yes Bank'),
    ('indusind', 'IndusInd Bank'),
    ('federal', 'Federal Bank'),
    ('rbl', 'RBL Bank'),
    ('other', 'Other'),
]


class BankAccount(SoftDeleteModel):
    """Model for bank accounts associated with merchants"""

    # Bank Type for bot selection
    bank_type = models.CharField(
        max_length=20,
        choices=BANK_TYPE_CHOICES,
        default='iob',
        help_text="Type of bank (used to select appropriate bot)"
    )

    # Basic Information
    nickname = models.CharField(
        max_length=255,
        help_text="Nickname for this bank account"
    )
    account_holder_name = models.CharField(
        max_length=255,
        help_text="Bank account holder's name"
    )
    account_number = models.CharField(
        max_length=16,
        help_text="16 digit account number"
    )
    ifsc_code = models.CharField(
        max_length=16,
        help_text="16 digit IFSC code"
    )
    upi_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="UPI ID for this bank account"
    )
    
    # Payin Limits
    min_payin = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Minimum payin amount"
    )
    max_payin = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Maximum payin amount"
    )
    
    # Balance and Transaction Count
    balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Current account balance"
    )
    transaction_count = models.IntegerField(
        default=0,
        help_text="Number of transactions"
    )
    
    # Feature Flags
    is_enabled = models.BooleanField(
        default=True,
        help_text="Whether this bank account is enabled"
    )
    is_qr = models.BooleanField(
        default=False,
        help_text="Whether QR code is enabled for this account"
    )
    is_bank = models.BooleanField(
        default=False,
        help_text="Whether bank transfer is enabled"
    )
    status = models.BooleanField(
        default=False,
        help_text="Account status (active/inactive)"
    )
    
    # Scheduling
    last_scheduled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last scheduled transaction time (IST)"
    )
    
    # Netbanking fields
    netbanking_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        help_text="URL for netbanking login"
    )
    login_type = models.CharField(
        max_length=20,
        choices=[('normal', 'Normal Login'), ('corp', 'Corporate Login')],
        default='normal',
        help_text="Type of login (normal or corporate)"
    )
    username = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Netbanking username"
    )
    username2 = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Second username for corporate login"
    )
    password = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Netbanking password"
    )

    # Approval status
    is_approved = models.BooleanField(
        default=False,
        help_text="Whether this bank account is approved by super admin"
    )

    # Relationship
    merchant = models.ForeignKey(
        'Merchant',
        on_delete=models.CASCADE,
        related_name='bank_accounts',
        help_text="Merchant associated with this bank account"
    )
    
    class Meta:
        db_table = 'bank_accounts'
        verbose_name = 'Bank Account'
        verbose_name_plural = 'Bank Accounts'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.nickname} - {self.account_holder_name}"
    
    def get_payin_range(self):
        """Returns formatted payin range string"""
        return f"₹{self.min_payin} - ₹{self.max_payin}"
    
    def get_balance_display(self):
        """Returns formatted balance with transaction count"""
        return f"₹{self.balance:,.2f} ({self.transaction_count})"
    
    def save(self, *args, **kwargs):
        """Override save to ensure only one bank account per merchant is enabled at a time"""
        # If this account is being enabled, disable all other accounts for the same merchant
        if self.is_enabled and self.merchant_id:
            # Get all other bank accounts for this merchant (excluding self if updating)
            other_accounts = BankAccount.objects.filter(
                merchant_id=self.merchant_id,
                is_enabled=True,
                deleted_at=None
            )
            # Exclude self if this is an update (pk exists)
            if self.pk:
                other_accounts = other_accounts.exclude(pk=self.pk)
            
            # Disable all other enabled accounts for this merchant
            if other_accounts.exists():
                other_accounts.update(is_enabled=False)
        
        super().save(*args, **kwargs)


class Merchant(SoftDeleteModel):
    name = models.CharField(max_length=255, help_text="Merchant name")
    code = models.CharField(max_length=100, unique=True, help_text="Unique merchant code")
    site = models.URLField(max_length=500, help_text="Merchant site URL")
    return_url = models.URLField(max_length=500, blank=True, null=True, help_text="Return URL for merchant")
    callback_url = models.URLField(max_length=500, blank=True, null=True, help_text="Callback URL for merchant")
    payout_callback_url = models.URLField(max_length=500, blank=True, null=True, help_text="Payout callback URL for merchant")
    api_key = models.CharField(max_length=255, unique=True, blank=True, help_text="API key for merchant (auto-generated)")
    
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
    
    def save(self, *args, **kwargs):
        """Override save to auto-generate API key if not provided"""
        if not self.pk and not self.api_key:
            # Only generate API key for new merchants (when pk is None)
            # Generate a secure random API key
            self.api_key = secrets.token_urlsafe(32)
            # Ensure uniqueness
            while Merchant.objects.filter(api_key=self.api_key).exists():
                self.api_key = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    def get_payment_url(self, user_id):
        """Returns the payment URL for the merchant"""
        return f"{os.getenv('FRONTEND_BASE_URL')}/pay/{self.code}/{user_id}"


class ExtractedTransactions(SoftDeleteModel):
    """Model for extracted transactions"""
    bank_account = models.ForeignKey(BankAccount, on_delete=models.CASCADE, related_name='extracted_transactions')
    amount = models.PositiveIntegerField(help_text="Amount of the transaction")
    utr = models.CharField(max_length=255, help_text="UTR of the transaction", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, help_text="Creation time")
    is_used = models.BooleanField(default=False, help_text="Whether the transaction has been used", db_index=True)

    class Meta:
        db_table = 'extracted_transactions'
        verbose_name = 'Extracted Transaction'
        verbose_name_plural = 'Extracted Transactions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['utr', 'is_used']),
            models.Index(fields=['bank_account', 'utr']),
        ]

    def __str__(self):
        return f"{self.amount} - {self.utr}"

    @property
    def merchant(self):
        """Get merchant through bank_account relationship"""
        return self.bank_account.merchant if self.bank_account else None

    @property
    def merchant_id(self):
        """Get merchant_id through bank_account relationship"""
        return self.bank_account.merchant_id if self.bank_account else None