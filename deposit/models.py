from django.db import models
from django.core.validators import MinValueValidator
from django.db.models import F
from decimal import Decimal
import uuid
import logging
from core.models.base import SoftDeleteModel
from merchants.models import Merchant, BankAccount
from accounts.models import CustomUser

logger = logging.getLogger(__name__)


PAYIN_STATUS_CHOICES = [
    ('initiated', 'Initiated'),
    ('assigned', 'Assigned'),
    ('success', 'Success'),
    ('dropped', 'Dropped'),
    ('dispute', 'Dispute'),
    ('duplicate', 'Duplicate'),
]


class Payin(SoftDeleteModel):
    """
    Payin model representing a deposit/payment transaction.
    """
    # Unique identifiers
    payin_uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        help_text="Unique UUID for the payin"
    )
    code = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        null=True,
        help_text="Unique code for the payin (e.g., rnDPx, rW5ao)"
    )
    
    # Amounts
    pay_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Requested payment amount"
    )
    confirmed_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Confirmed payment amount"
    )
    
    # Relationships
    merchant = models.ForeignKey(
        Merchant,
        on_delete=models.PROTECT,
        related_name='payins',
        help_text="Merchant associated with this payin"
    )
    user = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="User ID making the payment"
    )
    
    # Merchant order information
    merchant_order_id = models.UUIDField(
        help_text="Merchant's order ID (UUID)"
    )
    
    # Bank and payment details
    bank = models.CharField(
        max_length=255,
        help_text="Bank name or identifier (e.g., ftd, iobper-alex)"
    )
    
    # UTR (Unique Transaction Reference)
    utr = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Unique Transaction Reference from bank"
    )
    user_submitted_utr = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="UTR submitted by the user"
    )
    
    # Status and timing
    status = models.CharField(
        max_length=20,
        choices=PAYIN_STATUS_CHOICES,
        default='initiated',
        help_text="Current status of the payin"
    )
    duration = models.DurationField(
        blank=True,
        null=True,
        help_text="Duration taken for payment processing"
    )
    
    # Additional metadata
    notes = models.TextField(
        blank=True,
        null=True,
        help_text="Additional notes or comments"
    )

    assigned_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Time when the payin was assigned"
    )
    
    class Meta:
        db_table = 'payins'
        verbose_name = 'Payin'
        verbose_name_plural = 'Payins'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['payin_uuid']),
            models.Index(fields=['code']),
            models.Index(fields=['merchant_order_id']),
            models.Index(fields=['status']),
            models.Index(fields=['-created_at']),
        ]
    
    def __str__(self):
        return f"Payin {self.id} - {self.payin_uuid} ({self.status})"
    
    def get_duration_display(self):
        """Returns formatted duration string"""
        if self.duration:
            total_seconds = int(self.duration.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return "-"
    
    def calculate_duration(self):
        """Calculate duration from created_at to updated_at if status is success"""
        if self.status == 'success' and self.created_at and self.updated_at:
            self.duration = self.updated_at - self.created_at
            self.save(update_fields=['duration'])
    
    def update_bank_account_balance(self):
        """Update bank account balance when deposit status changes to success"""
        if self.status != 'success':
            return
        
        # Get the amount to add (use confirmed_amount if available, otherwise pay_amount)
        amount = self.confirmed_amount if self.confirmed_amount else self.pay_amount
        if not amount or amount <= 0:
            logger.warning(f"Payin {self.id} has no valid amount to add to bank account balance")
            return
        
        # Find the bank account by matching the bank name
        # The bank field stores bank name/nickname, try to match with BankAccount
        try:
            # Try to find by nickname first
            bank_account = BankAccount.objects.filter(
                merchant=self.merchant,
                nickname=self.bank,
                deleted_at=None
            ).first()
            
            # If not found by nickname, try by account_holder_name
            if not bank_account:
                bank_account = BankAccount.objects.filter(
                    merchant=self.merchant,
                    account_holder_name=self.bank,
                    deleted_at=None
                ).first()
            
            if bank_account:
                # Update balance and transaction count atomically
                BankAccount.objects.filter(id=bank_account.id).update(
                    balance=F('balance') + amount,
                    transaction_count=F('transaction_count') + 1
                )
                logger.info(f"Updated bank account {bank_account.id} balance by ₹{amount} for payin {self.id}")
            else:
                logger.warning(f"Bank account not found for payin {self.id} with bank name: {self.bank}")
        except Exception as e:
            logger.error(f"Error updating bank account balance for payin {self.id}: {str(e)}")
    
    def save(self, *args, **kwargs):
        """Override save to update bank account balance when status changes to success"""
        update_fields = kwargs.get('update_fields', None)
        status_changed_to_success = False
        
        # Check if this is an update and status is changing to success
        if self.pk:
            try:
                old_instance = Payin.objects.get(pk=self.pk)
                old_status = old_instance.status
                
                # If status is changing to success
                if old_status != 'success' and self.status == 'success':
                    status_changed_to_success = True
                    # If update_fields is specified, make sure 'status' is included
                    if update_fields and 'status' not in update_fields:
                        # Add status to update_fields if it's being changed
                        update_fields = list(update_fields) + ['status']
                        kwargs['update_fields'] = update_fields
            except Payin.DoesNotExist:
                pass
        
        # Save the instance
        super().save(*args, **kwargs)
        
        # Update bank account balance if status changed to success
        if status_changed_to_success:
            self.update_bank_account_balance()
