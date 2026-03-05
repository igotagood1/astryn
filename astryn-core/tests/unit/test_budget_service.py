"""Tests for services/budget.py — cost estimation and budget checking."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

from services.budget import can_use_anthropic, estimate_cost, record_usage


class TestEstimateCost:
    def test_sonnet_cost(self):
        cost = estimate_cost("claude-sonnet-4-6", input_tokens=1000, output_tokens=500)
        # 1000 * $3/1M + 500 * $15/1M = $0.003 + $0.0075 = $0.0105
        assert cost == Decimal("0.010500")

    def test_opus_cost(self):
        cost = estimate_cost("claude-opus-4-6", input_tokens=1000, output_tokens=500)
        # 1000 * $15/1M + 500 * $75/1M = $0.015 + $0.0375 = $0.0525
        assert cost == Decimal("0.052500")

    def test_haiku_cost(self):
        cost = estimate_cost("claude-haiku-4-5", input_tokens=1000, output_tokens=500)
        # 1000 * $0.80/1M + 500 * $4/1M = $0.0008 + $0.002 = $0.0028
        assert cost == Decimal("0.002800")

    def test_strips_provider_prefix(self):
        cost = estimate_cost("anthropic/claude-sonnet-4-6", input_tokens=1000, output_tokens=500)
        assert cost == Decimal("0.010500")

    def test_unknown_model_uses_default(self):
        cost = estimate_cost("unknown-model", input_tokens=1000, output_tokens=500)
        # Uses default pricing (same as sonnet)
        assert cost == Decimal("0.010500")

    def test_zero_tokens(self):
        cost = estimate_cost("claude-sonnet-4-6", input_tokens=0, output_tokens=0)
        assert cost == Decimal("0.000000")


class TestCanUseAnthropic:
    async def test_within_budget(self, mock_db):
        with patch("services.budget.repo") as mock_repo:
            mock_repo.get_usage_since = AsyncMock(return_value=[])
            result = await can_use_anthropic(mock_db)
        assert result is True

    async def test_daily_budget_exhausted(self, mock_db):
        class FakeUsage:
            estimated_cost_usd = Decimal("5.00")

        with patch("services.budget.repo") as mock_repo:
            mock_repo.get_usage_since = AsyncMock(return_value=[FakeUsage()])
            result = await can_use_anthropic(mock_db)
        assert result is False

    async def test_monthly_budget_exhausted(self, mock_db):
        class FakeUsage:
            estimated_cost_usd = Decimal("50.00")

        with patch("services.budget.repo") as mock_repo:
            # Daily check passes (no records today)
            # Monthly check fails
            mock_repo.get_usage_since = AsyncMock(side_effect=[[], [FakeUsage()]])
            result = await can_use_anthropic(mock_db)
        assert result is False


class TestRecordUsage:
    async def test_records_successfully(self, mock_db):
        with patch("services.budget.repo") as mock_repo:
            mock_repo.record_api_usage = AsyncMock()
            await record_usage(mock_db, "claude-sonnet-4-6", 1000, 500, "session-1")
        mock_repo.record_api_usage.assert_called_once()

    async def test_catches_db_errors(self, mock_db):
        """Fire-and-forget: DB errors don't propagate."""
        with patch("services.budget.repo") as mock_repo:
            mock_repo.record_api_usage = AsyncMock(side_effect=Exception("DB down"))
            # Should not raise
            await record_usage(mock_db, "claude-sonnet-4-6", 1000, 500)
