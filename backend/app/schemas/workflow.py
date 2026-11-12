from typing import Optional

from pydantic import BaseModel


class InvoiceData(BaseModel):
    """Fields extracted from an invoice. Every key is required; null means the invoice does not state it."""
    vendor_name: Optional[str]
    invoice_date: Optional[str]
    total_amount: Optional[str]
    tax_amount: Optional[str]

    # The model sometimes returns amounts as JSON numbers
    model_config = {"coerce_numbers_to_str": True}
