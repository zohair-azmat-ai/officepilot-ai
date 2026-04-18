"""
schemas/command.py — Request / response models for the natural-language
                     parse-command endpoint.
"""

from pydantic import BaseModel


class ParseCommandRequest(BaseModel):
    """Raw natural-language command sent by the user."""
    command: str


class ParsedItem(BaseModel):
    """
    A single parsed line item extracted from a multi-item command.
    Shape matches QuotationItem so the frontend can forward it directly.
    """
    description: str
    size:        str   = ""
    quantity:    float
    rate:        float
    amount:      float   # qty × rate, pre-computed


class ParsedFields(BaseModel):
    """
    Structured quotation fields extracted from the command.
    Has the same shape as QuotationCreateRequest so the frontend
    can forward it directly to POST /quotations/create.
    """
    year:        str
    month:       str
    date:        str
    client_name: str
    # Single-item fields (populated from first item; backward compat)
    description: str
    size:        str
    quantity:    float
    rate:        float
    tax:         float
    total:       float
    # Multi-item list (empty for single-item commands)
    items:       list[ParsedItem] = []


class FieldConfidence(BaseModel):
    """
    Per-field flag: True = explicitly found in the command text.
    False = defaulted / auto-calculated.
    """
    client_name: bool
    description: bool
    size:        bool
    quantity:    bool
    rate:        bool
    tax:         bool


class ParseCommandResponse(BaseModel):
    """Full response returned by POST /quotations/parse-command."""
    success:    bool
    parsed:     ParsedFields
    confidence: FieldConfidence
    warnings:   list[str]
