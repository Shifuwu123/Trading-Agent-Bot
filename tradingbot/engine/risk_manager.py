from tradingbot.core.config import AppConfig
from tradingbot.utils.logger import log

class RiskManager:
    """
    RiskManager handles the validation of trades based on risk constraints.
    """
    def __init__(self, config: AppConfig):
        self.config = config
        self.risk_config = config.risk

    def can_open_position(self, current_open_positions: int) -> bool:
        """
        Checks if a new position can be opened based on max_open_positions.
        """
        if current_open_positions >= self.risk_config.max_open_positions:
            log.warning(
                f"Cannot open position: Current positions ({current_open_positions}) "
                f"reached limit ({self.risk_config.max_open_positions})."
            )
            return False
        
        log.info(
            f"Can open position: {current_open_positions} open positions, "
            f"limit is {self.risk_config.max_open_positions}."
        )
        return True

    def check_capital_exposure(self, current_exposure: float, total_capital: float) -> bool:
        """
        Checks if current capital exposure is within max_capital_exposure_pct limit.
        """
        if total_capital <= 0:
            log.error("Total capital must be greater than zero to check exposure.")
            return False
            
        exposure_pct = current_exposure / total_capital
        if exposure_pct >= self.risk_config.max_capital_exposure_pct:
            log.warning(
                f"High capital exposure: {exposure_pct:.2%} exceeds "
                f"limit of {self.risk_config.max_capital_exposure_pct:.2%}."
            )
            return False
            
        log.info(
            f"Capital exposure is safe: {exposure_pct:.2%} "
            f"(limit {self.risk_config.max_capital_exposure_pct:.2%})."
        )
        return True

    def check_daily_loss(self, daily_loss: float, total_capital: float) -> bool:
        """
        Checks if daily loss has exceeded daily_loss_limit_pct.
        daily_loss should be a positive float representing the absolute amount lost.
        """
        if total_capital <= 0:
            log.error("Total capital must be greater than zero to check daily loss.")
            return False

        # Use absolute value in case daily_loss is passed as a negative number
        loss_pct = abs(daily_loss) / total_capital
        if loss_pct >= self.risk_config.daily_loss_limit_pct:
            log.warning(
                f"Daily loss limit reached: {loss_pct:.2%} >= "
                f"{self.risk_config.daily_loss_limit_pct:.2%}."
            )
            return False
            
        log.info(
            f"Daily loss is within limits: {loss_pct:.2%} "
            f"(limit {self.risk_config.daily_loss_limit_pct:.2%})."
        )
        return True

    def calculate_position_size(self, total_capital: float, entry_price: float, stop_loss_price: float, is_dca: bool = False) -> float:
        """
        Calculates position size based on max_loss_per_trade_pct and slot allocation.
        Returns the number of units to trade.
        """
        if total_capital <= 0 or entry_price <= 0 or stop_loss_price <= 0:
            log.error("Invalid input values for calculating position size.")
            return 0.0

        if entry_price == stop_loss_price:
            log.error("Entry price and stop loss cannot be equal.")
            return 0.0

        risk_amount = total_capital * self.risk_config.max_loss_per_trade_pct
        price_risk_per_unit = abs(entry_price - stop_loss_price)
        
        position_size = risk_amount / price_risk_per_unit
        
        # Check against slot budget and total capital exposure
        usable_exposure_pct = self.risk_config.max_capital_exposure_pct
        if not is_dca:
            usable_exposure_pct = max(0.05, usable_exposure_pct - getattr(self.risk_config, "reserve_capital_pct", 0.30))

        max_positions = max(1, getattr(self.risk_config, "max_open_positions", 10))
        slot_budget = (total_capital * usable_exposure_pct) / max_positions
        min_order = getattr(self.risk_config, "min_order_usd", 1.0)
        max_investment = min(total_capital * self.risk_config.max_capital_exposure_pct, max(slot_budget, min_order))
        investment_size = position_size * entry_price
        
        if investment_size > max_investment:
            position_size = max_investment / entry_price
            log.info(
                f"Position size limited by slot budget / capital exposure (${max_investment:,.2f} USD). "
                f"New size: {position_size:.4f}"
            )

        log.info(
            f"Calculated position size: {position_size:.4f} units "
            f"(Risk Amount: {risk_amount:.2f}, Price Risk: {price_risk_per_unit:.2f})"
        )
        return position_size
