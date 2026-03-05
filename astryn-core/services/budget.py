"""Budget service — cost estimation and spend tracking for Anthropic API usage.

Budget checks are advisory: if a budget is exhausted, the coordinator falls
back to Ollama. Recording is fire-and-forget — DB errors are caught and logged
so they never kill a user request.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

import db.repository as repo
from llm.config import settings

logger = logging.getLogger(__name__)

# Pricing per 1M tokens (as of March 2026)
# Updates to these values require a code change.
_PRICING: dict[str, dict[str, Decimal]] = {
    "claude-sonnet-4-6": {
        "input": Decimal("3.00"),
        "output": Decimal("15.00"),
    },
    "claude-opus-4-6": {
        "input": Decimal("15.00"),
        "output": Decimal("75.00"),
    },
    "claude-haiku-4-5": {
        "input": Decimal("0.80"),
        "output": Decimal("4.00"),
    },
}

# Fallback pricing for unknown models
_DEFAULT_PRICING = {
    "input": Decimal("3.00"),
    "output": Decimal("15.00"),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """Estimate cost in USD for a given model and token counts."""
    # Strip provider prefix if present (e.g. "anthropic/claude-sonnet-4-6")
    model_key = model.split("/")[-1] if "/" in model else model

    # Try exact match first, then prefix match
    pricing = _PRICING.get(model_key)
    if pricing is None:
        for key, val in _PRICING.items():
            if model_key.startswith(key):
                pricing = val
                break
    if pricing is None:
        pricing = _DEFAULT_PRICING

    input_cost = pricing["input"] * Decimal(input_tokens) / Decimal("1000000")
    output_cost = pricing["output"] * Decimal(output_tokens) / Decimal("1000000")
    return (input_cost + output_cost).quantize(Decimal("0.000001"))


async def can_use_anthropic(db: AsyncSession) -> bool:
    """Check whether Anthropic usage is within daily and monthly budgets."""
    now = datetime.now(UTC)

    # Daily check
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    daily_records = await repo.get_usage_since(db, day_start)
    daily_spend = sum(r.estimated_cost_usd for r in daily_records)
    if daily_spend >= settings.astryn_anthropic_daily_budget_usd:
        logger.info("Daily Anthropic budget exhausted: $%.4f", daily_spend)
        return False

    # Monthly check
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_records = await repo.get_usage_since(db, month_start)
    monthly_spend = sum(r.estimated_cost_usd for r in monthly_records)
    if monthly_spend >= settings.astryn_anthropic_monthly_budget_usd:
        logger.info("Monthly Anthropic budget exhausted: $%.4f", monthly_spend)
        return False

    return True


async def record_usage(
    db: AsyncSession,
    model: str,
    input_tokens: int,
    output_tokens: int,
    session_id: str | None = None,
) -> None:
    """Record API usage. Fire-and-forget — catches DB errors."""
    try:
        cost = estimate_cost(model, input_tokens, output_tokens)
        await repo.record_api_usage(
            db=db,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=cost,
            session_id=session_id,
        )
    except Exception:
        logger.exception("Failed to record API usage (non-fatal)")
