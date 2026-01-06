# app/models.py
from django.db import models
from django.utils import timezone
from django.conf import settings
from decimal import Decimal
from datetime import date, timedelta
from django.contrib.auth import get_user_model
import random

User = get_user_model()


# ============================================================
# SHOP (TENANT) MODEL
# ============================================================
def generate_shop_id():
    return str(random.randint(100000, 999999))


class Shop(models.Model):
    PLAN_CHOICES = [
        ("trial", "Free Trial (7 Days)"),
        ("monthly", "Monthly 750 BDT"),
        ("yearly", "Yearly 7990 BDT"),
    ]

    shop_id = models.CharField(max_length=6, unique=True, default=generate_shop_id)
    shop_name = models.CharField(max_length=120)
    location = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=11)
    email_or_link = models.CharField(max_length=200, blank=True, null=True)
    owner_name = models.CharField(max_length=100)

    logo = models.ImageField(upload_to="shop_logos/", blank=True, null=True)

    plan = models.CharField(max_length=10, choices=PLAN_CHOICES)
    is_active = models.BooleanField(default=False)
    expire_date = models.DateField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    # activate subscription periods
    def activate_trial(self):
        self.plan = "trial"
        self.is_active = True
        self.expire_date = date.today() + timedelta(days=7)
        self.save()

    def activate_monthly(self):
        self.plan = "monthly"
        self.is_active = True
        self.expire_date = date.today() + timedelta(days=30)
        self.save()

    def activate_yearly(self):
        self.plan = "yearly"
        self.is_active = True
        self.expire_date = date.today() + timedelta(days=365)
        self.save()

    def __str__(self):
        return f"{self.shop_name} ({self.shop_id})"


# ============================================================
# USER PROFILE (USER → SHOP)
# ============================================================
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="users")
    role = models.CharField(
       max_length=20,
       choices=[
            ("admin", "Admin"),
            ("manager", "Manager"),
            ("seller", "Seller"),
            ("cashier", "Cashier"),
       ],
       default="admin")
    is_owner = models.BooleanField(default=False)
    profile_picture = models.ImageField(upload_to="profile_pics/", blank=True, null=True)
    
    # Permissions
    can_manage_products = models.BooleanField(default=False)
    can_manage_sales = models.BooleanField(default=False)
    can_manage_purchases = models.BooleanField(default=False)
    can_view_reports = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} → {self.shop.shop_name} ({self.role})"
# ============================================================
# MANUAL PAYMENT REQUEST
# ============================================================
class PaymentRequest(models.Model):
    PAYMENT_METHODS = [
        ("bkash", "bKash"),
        ("nagad", "Nagad"),
    ]
    
    PLAN_CHOICES = [
        ("monthly", "Monthly"),
        ("yearly", "Yearly"),
    ]

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="payment_requests")
    plan = models.CharField(max_length=10, choices=PLAN_CHOICES, default="monthly")
    method = models.CharField(max_length=10, choices=PAYMENT_METHODS, blank=True, null=True)
    sender_last4 = models.CharField(max_length=4, blank=True, null=True)
    amount = models.PositiveIntegerField()
    transaction_id = models.CharField(max_length=50, blank=True, null=True)
    screenshot = models.ImageField(upload_to="payments/", blank=True, null=True)

    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.shop.shop_name} Payment ({self.method})"


# ============================================================
# CATEGORY
# ============================================================
class Category(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=100)

    class Meta:
        verbose_name_plural = "Categories"
        unique_together = ('shop', 'name')

    def __str__(self):
        return f"{self.name} ({self.shop.shop_id if self.shop else 'No Shop'})"


# ============================================================
# PRODUCT
# ============================================================
class Product(models.Model):
    BASE_UNIT_CHOICES = [
        ('pcs', 'Pieces'),
        ('kg', 'Kilogram'),
        ('g', 'Gram'),
        ('ltr', 'Liter'),
        ('ml', 'Milliliter'),
    ]
    
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, null=True, blank=True)
    title = models.CharField(max_length=200)
    product_code = models.CharField(max_length=50)
    sku = models.CharField(max_length=50, blank=True, null=True)
    barcode = models.CharField(max_length=64, blank=True, null=True)

    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")

    # Universal inventory: base unit for stock tracking
    base_unit = models.CharField(max_length=10, choices=BASE_UNIT_CHOICES, default='pcs')
    
    purchased_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    regular_price = models.DecimalField(max_digits=10, decimal_places=2)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    image = models.ImageField(upload_to="products/", blank=True, null=True)
    
    # Changed to DecimalField to support weight units (kg, g, ltr, ml)
    stock = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    
    # Pharmacy-specific fields (optional)
    has_variants = models.BooleanField(default=False)

    # VAT fields
    vat_applicable = models.BooleanField(default=False)
    vat_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('shop', 'product_code')

    def save(self, *args, **kwargs):
        if self.selling_price is None:
            self.selling_price = max(0, self.regular_price - (self.discount or 0))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} ({self.shop.shop_id if self.shop else 'No Shop'})"


# ============================================================
# PRODUCT VARIANT
# ============================================================
class ProductVariant(models.Model):
    """
    Optional variants for products (size/color/strength/ml)
    Each variant has separate SKU/barcode and stock
    """
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    
    # Variant attributes
    variant_name = models.CharField(max_length=100)  # e.g., "500ml", "Red", "XL", "10mg"
    sku = models.CharField(max_length=50, blank=True, null=True)
    barcode = models.CharField(max_length=64, blank=True, null=True)
    
    # Pricing (can override parent product pricing)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Stock tracking (in base units)
    stock = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('product', 'variant_name')
        ordering = ['variant_name']

    def __str__(self):
        return f"{self.product.title} - {self.variant_name}"


# ============================================================
# CUSTOMER
# ============================================================
class Customer(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    points = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("shop", "phone")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.phone}) [{self.shop.shop_id if self.shop else 'No Shop'}]"


# ============================================================
# SALE + SALE ITEMS
# ============================================================
class Sale(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, null=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)

    date = models.DateTimeField(auto_now_add=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    vat_applicable = models.BooleanField(default=False)
    vat_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    payment_method = models.CharField(
        max_length=20,
        choices=[
            ("cash", "Cash"),
            ("bkash", "bKash"),
            ("nagad", "Nagad"),
            ("card", "Card"),
            ("due", "Due"),
            ("rocket", "Rocket"),
            ("bank", "Bank Transfer"),
        ],
        default="cash"
    )
    paid_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )
    due_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )
    trx_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Transaction ID"
    )
    
    redeemed_points = models.PositiveIntegerField(default=0)
    earned_points = models.PositiveIntegerField(default=0)
    
    def save(self, *args, **kwargs):
        # calculate points
        self.earned_points = int(self.total // 100)

        # ✅ Payment logic - This should match your serializer logic
        if self.payment_method != "due":
            # For non-due payments, paid_amount should equal total
            self.paid_amount = Decimal(self.total or 0)
            self.due_amount = Decimal("0.00")
        else:
            # For due payments, use the provided paid_amount
            # (if any partial payment was made)
            self.paid_amount = Decimal(self.paid_amount or 0)
            self.due_amount = Decimal(self.total or 0) - Decimal(self.paid_amount or 0)

        # customer points update
        if self.customer:
            if self.redeemed_points > 0:
                self.customer.points = max(0, self.customer.points - self.redeemed_points)
            self.customer.points += self.earned_points
            self.customer.save()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"Sale #{self.id} [{self.shop.shop_id if self.shop else 'No Shop'}]"

class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    product_variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)

    quantity = models.DecimalField(max_digits=10, decimal_places=3, default=1)
    unit = models.CharField(max_length=20, default='pcs')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    
    # VAT fields
    vat_applicable = models.BooleanField(default=False)
    vat_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    vat_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    def __str__(self):
        return f"{self.product.title} × {self.quantity}"


# ============================================================
# EXPENSE
# ============================================================
class Expense(models.Model):
    PAYMENT_METHODS = [
        ("cash", "Cash"),
        ("bank", "Bank"),
        ("mobile", "Mobile Wallet"),
        ("other", "Other"),
    ]

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, null=True, blank=True)

    date = models.DateField(auto_now_add=True)
    category = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=12, choices=PAYMENT_METHODS, default="cash")

    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expenses",
    )

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.category} - {self.amount} [{self.shop.shop_id if self.shop else 'No Shop'}]"


# ============================================================
# SUPPLIER
# ============================================================
class Supplier(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)

    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("shop", "name")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} [{self.shop.shop_id if self.shop else 'No Shop'}]"


# ============================================================
# PURCHASE
# ============================================================
class Purchase(models.Model):
    PAYMENT_METHODS = [
        ("cash", "Cash"),
        ("bank", "Bank"),
        ("mobile", "Mobile Wallet"),
        ("due", "Due"),
    ]

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, null=True, blank=True)

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    invoice_no = models.CharField(max_length=50)

    date = models.DateField(default=timezone.now)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    due_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default="cash")
    remarks = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("shop", "invoice_no")
        ordering = ["-date", "-id"]

    def save(self, *args, **kwargs):
        self.due_amount = Decimal(self.total) - Decimal(self.paid_amount)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.invoice_no} | {self.supplier.name} [{self.shop.shop_id if self.shop else 'No Shop'}]"


# ============================================================
# PURCHASE ITEM
# ============================================================
class PurchaseItem(models.Model):
    PACK_UNIT_CHOICES = [
        ('bag', 'Bag'),
        ('carton', 'Carton'),
        ('box', 'Box'),
        ('strip', 'Strip'),
        ('bottle', 'Bottle'),
        ('pack', 'Pack'),
        ('unit', 'Unit'),  # Direct base unit purchase
    ]
    
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, null=True, blank=True)
    product_variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, null=True, blank=True)

    # Pack-based purchasing
    pack_unit = models.CharField(max_length=20, choices=PACK_UNIT_CHOICES, default='unit')
    pack_size = models.DecimalField(max_digits=10, decimal_places=3, default=1)  # How many base units in one pack
    qty_packs = models.DecimalField(max_digits=10, decimal_places=3, default=1)  # Quantity of packs purchased
    
    price_per_pack = models.DecimalField(max_digits=12, decimal_places=2)  # Price per pack
    
    # Pharmacy-specific fields (optional)
    batch_no = models.CharField(max_length=50, blank=True, null=True)
    expiry_date = models.DateField(blank=True, null=True)
    mrp = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)  # Maximum Retail Price

    # Auto-calculated fields
    total_base_qty = models.DecimalField(max_digits=12, decimal_places=3, default=0)  # pack_size * qty_packs
    cost_per_base_unit = models.DecimalField(max_digits=12, decimal_places=4, default=0)  # price_per_pack / pack_size
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # price_per_pack * qty_packs

    def save(self, *args, **kwargs):
        from django.db import transaction
        
        # Calculate totals
        self.total_base_qty = Decimal(self.pack_size) * Decimal(self.qty_packs)
        self.cost_per_base_unit = Decimal(self.price_per_pack) / Decimal(self.pack_size) if self.pack_size > 0 else 0
        self.total = Decimal(self.price_per_pack) * Decimal(self.qty_packs)
        
        with transaction.atomic():
            super().save(*args, **kwargs)
            
            # Update stock (either product or variant)
            if self.product_variant:
                self.product_variant.stock = Decimal(self.product_variant.stock) + self.total_base_qty
                self.product_variant.save(update_fields=['stock'])
            elif self.product:
                self.product.stock = Decimal(self.product.stock) + self.total_base_qty
                self.product.save(update_fields=['stock'])

    def __str__(self):
        if self.product_variant:
            return f"{self.product_variant} × {self.qty_packs} {self.pack_unit}s"
        return f"{self.product.title} × {self.qty_packs} {self.pack_unit}s"


# ============================================================
# SUPPLIER PAYMENT
# ============================================================
class SupplierPayment(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, null=True, blank=True)

    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE)
    date = models.DateField(auto_now_add=True)

    memo_no = models.CharField(max_length=100, blank=True, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    payment_method = models.CharField(
        max_length=20,
        choices=[("cash", "Cash"), ("bank", "Bank"), ("mobile", "Mobile Wallet")],
        default="cash",
    )
    remarks = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.supplier.name} | {self.amount} [{self.shop.shop_id if self.shop else 'No Shop'}]"
    
class CustomerPayment(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, null=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="payments")

    date = models.DateField(auto_now_add=True)
    memo_no = models.CharField(max_length=100, blank=True, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    payment_method = models.CharField(
        max_length=20,
        choices=[("cash", "Cash"), ("bank", "Bank"), ("bkash", "Bkash"), ("nagad", "Nagad"), ("card", "Card")],
        default="cash",
    )
    remarks = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-date", "-id"]
    

# ============================================================
# STOCK LEDGER (Optional - for batch/expiry tracking and FIFO)
# ============================================================
class StockLedger(models.Model):
    """
    Track all stock movements with batch/expiry for pharmacy FIFO
    """
    TRANSACTION_TYPE_CHOICES = [
        ('purchase', 'Purchase'),
        ('sale', 'Sale'),
        ('adjustment', 'Adjustment'),
        ('return', 'Return'),
    ]
    
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, null=True, blank=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, null=True, blank=True)
    product_variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, null=True, blank=True)
    
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE_CHOICES)
    transaction_date = models.DateTimeField(auto_now_add=True)
    
    # Batch tracking for pharmacy
    batch_no = models.CharField(max_length=50, blank=True, null=True)
    expiry_date = models.DateField(blank=True, null=True)
    
    # Quantity movement (positive for in, negative for out)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    
    # Remaining quantity in this batch
    remaining_qty = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    
    # Reference to purchase/sale
    purchase_item = models.ForeignKey(PurchaseItem, on_delete=models.SET_NULL, null=True, blank=True)
    sale_item = models.ForeignKey(SaleItem, on_delete=models.SET_NULL, null=True, blank=True)
    
    notes = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['expiry_date', 'transaction_date']  # FIFO by expiry date first
        indexes = [
            models.Index(fields=['product', 'batch_no']),
            models.Index(fields=['product_variant', 'batch_no']),
            models.Index(fields=['expiry_date']),
        ]
    
    def __str__(self):
        target = self.product or self.product_variant
        return f"{target.title if target else 'Unknown'} | {self.transaction_type} | {self.quantity}"


# ============================================================
# CASH TRANSACTION / LEDGER
# ============================================================
class CashTransaction(models.Model):
    """
    Track all cash transactions like a bank ledger.
    Auto-synced from Sales, Expenses, Purchases, Customer Payments, etc.
    Also supports manual entries for investments, bank deposits/withdrawals.
    """
    TRANSACTION_TYPE_CHOICES = [
        ('credit', 'Credit'),  # Money In
        ('debit', 'Debit'),    # Money Out
    ]
    
    SOURCE_CHOICES = [
        ('sale', 'Sale'),
        ('expense', 'Expense'),
        ('purchase', 'Purchase'),
        ('supplier_payment', 'Supplier Payment'),
        ('customer_payment', 'Customer Due Payment'),
        ('investment', 'Investment/Capital'),
        ('bank_deposit', 'Bank Deposit'),
        ('bank_withdrawal', 'Bank Withdrawal'),
        ('opening_balance', 'Opening Balance'),
        ('adjustment', 'Adjustment'),
        ('other', 'Other'),
    ]
    
    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('bank', 'Bank'),
        ('bkash', 'bKash'),
        ('nagad', 'Nagad'),
        ('card', 'Card'),
        ('cheque', 'Cheque'),
        ('other', 'Other'),
    ]
    
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='cash_transactions')
    
    date = models.DateField(default=timezone.now)
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPE_CHOICES)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    running_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='cash')
    
    # Reference fields for auto-synced transactions
    sale = models.ForeignKey(Sale, on_delete=models.SET_NULL, null=True, blank=True, related_name='cash_transactions')
    expense = models.ForeignKey(Expense, on_delete=models.SET_NULL, null=True, blank=True, related_name='cash_transactions')
    purchase = models.ForeignKey(Purchase, on_delete=models.SET_NULL, null=True, blank=True, related_name='cash_transactions')
    supplier_payment = models.ForeignKey(SupplierPayment, on_delete=models.SET_NULL, null=True, blank=True, related_name='cash_transactions')
    customer_payment = models.ForeignKey(CustomerPayment, on_delete=models.SET_NULL, null=True, blank=True, related_name='cash_transactions')
    
    # Manual entry fields
    description = models.TextField(blank=True, null=True)
    reference_no = models.CharField(max_length=100, blank=True, null=True)  # Cheque no, transaction ID, etc.
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    
    # Audit fields
    is_manual = models.BooleanField(default=False)  # True if manually added
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cash_transactions'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['shop', 'date']),
            models.Index(fields=['shop', 'source']),
            models.Index(fields=['shop', 'transaction_type']),
        ]
    
    def __str__(self):
        return f"{self.date} | {self.get_transaction_type_display()} | {self.get_source_display()} | {self.amount}"
    
    @classmethod
    def get_current_balance(cls, shop):
        """Get the current cash balance for a shop"""
        from django.db.models import Sum, Case, When, F, DecimalField
        
        result = cls.objects.filter(shop=shop).aggregate(
            total_credit=Sum(
                Case(
                    When(transaction_type='credit', then=F('amount')),
                    default=0,
                    output_field=DecimalField()
                )
            ),
            total_debit=Sum(
                Case(
                    When(transaction_type='debit', then=F('amount')),
                    default=0,
                    output_field=DecimalField()
                )
            )
        )
        
        credit = result['total_credit'] or Decimal('0.00')
        debit = result['total_debit'] or Decimal('0.00')
        return credit - debit

        return f"{self.transaction_type} - {target} - {self.quantity}"
