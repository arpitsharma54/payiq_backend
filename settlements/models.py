from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal
from core.models.base import SoftDeleteModel


# Settlement instrument choices
INSTRUMENT_CHOICES = [
    ('bank', 'Bank Transfer'),
    ('crypto', 'Cryptocurrency'),
]

# Settlement status choices
SETTLEMENT_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('processing', 'Processing'),
    ('success', 'Success'),
    ('failed', 'Failed'),
    ('cancelled', 'Cancelled'),
]


class SettlementAccount(SoftDeleteModel):
    """Model for settlement accounts (bank accounts for receiving settlements)"""

    # Relationship
    merchant = models.ForeignKey(
        'merchants.Merchant',
        on_delete=models.CASCADE,
        related_name='settlement_accounts',
        help_text="Merchant associated with this settlement account"
    )

    # Basic Information
    nickname = models.CharField(
        max_length=255,
        help_text="Nickname for this settlement account"
    )

    # Instrument Type
    instrument_type = models.CharField(
        max_length=20,
        choices=INSTRUMENT_CHOICES,
        default='bank',
        help_text="Type of settlement instrument"
    )

    # Bank Details (used when instrument_type is 'bank')
    account_holder_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Bank account holder's name"
    )
    account_number = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Bank account number"
    )
    ifsc_code = models.CharField(
        max_length=11,
        blank=True,
        null=True,
        help_text="IFSC code"
    )

    # Crypto Details (used when instrument_type is 'crypto')
    crypto_wallet_address = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Cryptocurrency wallet address"
    )
    crypto_network = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Cryptocurrency network (e.g., ERC20, TRC20, BEP20)"
    )

    class Meta:
        db_table = 'settlement_accounts'
        verbose_name = 'Settlement Account'
        verbose_name_plural = 'Settlement Accounts'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.nickname} - {self.merchant.code}"

    def get_display_details(self):
        """Returns formatted account details based on instrument type"""
        if self.instrument_type == 'bank':
            return f"{self.account_holder_name}\n{self.account_number}\n{self.ifsc_code}"
        elif self.instrument_type == 'crypto':
            return f"{self.crypto_wallet_address}\n{self.crypto_network}"
        return ""


class Settlement(SoftDeleteModel):
    """Model for settlement transactions"""

    # Relationship
    merchant = models.ForeignKey(
        'merchants.Merchant',
        on_delete=models.CASCADE,
        related_name='settlements',
        help_text="Merchant for this settlement"
    )

    settlement_account = models.ForeignKey(
        'SettlementAccount',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='settlements',
        help_text="Settlement account used for this settlement (from)"
    )

    to_settlement_account = models.ForeignKey(
        'SettlementAccount',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='settlements_received',
        help_text="Destination settlement account (to)"
    )

    # Amount
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="Settlement amount"
    )

    # Status
    status = models.CharField(
        max_length=20,
        choices=SETTLEMENT_STATUS_CHOICES,
        default='pending',
        help_text="Settlement status"
    )

    # Settlement Method (instrument type at time of settlement)
    method = models.CharField(
        max_length=20,
        choices=INSTRUMENT_CHOICES,
        default='bank',
        help_text="Settlement method used"
    )

    # Bank Details (snapshot at time of settlement)
    bank_account_holder_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Account holder name (snapshot)"
    )
    bank_account_number = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Account number (snapshot)"
    )
    bank_ifsc_code = models.CharField(
        max_length=11,
        blank=True,
        null=True,
        help_text="IFSC code (snapshot)"
    )

    # Reference
    reference_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        unique=True,
        help_text="External reference ID (UTR, transaction hash, etc.)"
    )

    # Notes
    notes = models.TextField(
        blank=True,
        null=True,
        help_text="Additional notes"
    )

    class Meta:
        db_table = 'settlements'
        verbose_name = 'Settlement'
        verbose_name_plural = 'Settlements'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['merchant']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Settlement #{self.id} - {self.merchant.code} - ₹{self.amount}"

    def get_bank_details_display(self):
        """Returns formatted bank details"""
        if self.bank_account_holder_name:
            return f"{self.bank_account_holder_name}\n{self.bank_account_number}\n{self.bank_ifsc_code}"
        return ""

    def save(self, *args, **kwargs):
        """Override save to snapshot account details"""
        # If settlement_account is provided and bank details are not set, copy them
        if self.settlement_account and not self.bank_account_number:
            if self.settlement_account.instrument_type == 'bank':
                self.bank_account_holder_name = self.settlement_account.account_holder_name
                self.bank_account_number = self.settlement_account.account_number
                self.bank_ifsc_code = self.settlement_account.ifsc_code
                self.method = 'bank'
        super().save(*args, **kwargs)
