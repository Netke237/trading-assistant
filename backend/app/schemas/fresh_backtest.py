"""No absent fresh-run field may acquire a current scan setting."""
from datetime import date
import inspect
import math
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

SUPPORTED = ('pullback_ema', 'breakout_base', 'ma_crossover', 'mean_reversion_rsi',
             'mean_reversion_bb', 'mean_reversion_multi')


def signal_functions():
    from app.services.strategy_engine import _multi_variant_fns
    return {k: v for k, v in _multi_variant_fns().items() if k != 'mean_reversion_vwap'}


def parameter_contract(strategy):
    """Types only: exposing required fields does not prefill unknown originals."""
    fn = signal_functions()[strategy]
    return {name: ('null' if value.default is None else type(value.default).__name__)
            for name, value in inspect.signature(fn).parameters.items()
            if name not in {'bars', 'direction'}}


def validate_parameters(strategy, params):
    if not isinstance(params, dict):
        raise ValueError('Parameters must be an explicit object')
    if strategy == 'mean_reversion_multi':
        if set(params) != {'variants', 'min_confirmations', 'variant_params'}:
            raise ValueError('Complete multi configuration is required')
        variants = params['variants']
        if (not isinstance(variants, list) or not variants or len(variants) > 6
                or any(not isinstance(v, str) or v not in signal_functions() for v in variants)
                or len(set(variants)) != len(variants)):
            raise ValueError('Choose unique supported daily variants')
        minimum = params['min_confirmations']
        if type(minimum) is not int or not 1 <= minimum <= len(variants):
            raise ValueError('Invalid confirmation count')
        nested = params['variant_params']
        if not isinstance(nested, dict) or set(nested) != set(variants):
            raise ValueError('Explicit parameters are required for every selected variant')
        for variant in variants:
            validate_parameters(variant, nested[variant])
        return
    contract = parameter_contract(strategy)
    if set(params) != set(contract):
        raise ValueError('Every parameter is required; unknown parameters are rejected')
    for name, kind in contract.items():
        value = params[name]
        if kind == 'null':
            # current_price is a live override, never a price for a historical run.
            if value is not None:
                raise ValueError(f'{name} must explicitly be null')
        elif kind == 'bool':
            if type(value) is not bool:
                raise ValueError(f'{name} must be boolean')
        elif kind == 'int':
            if type(value) is not int or not 1 <= value <= 390:
                raise ValueError(f'{name} must be an integer from 1 to 390')
        elif kind == 'float':
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1000:
                raise ValueError(f'{name} must be finite and nonnegative')
        elif kind == 'str':
            if name == 'ma_type' and value not in ('EMA', 'SMA'):
                raise ValueError('ma_type must be EMA or SMA')
            if not isinstance(value, str):
                raise ValueError(f'{name} must be text')
    from app.services.strategy_engine import bars_needed, SIGNAL_WINDOW_BARS
    if bars_needed(strategy, params) > SIGNAL_WINDOW_BARS:
        raise ValueError('Parameters exceed the engine signal window')


class FreshBacktestRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    symbol: str = Field(pattern=r'^[A-Z][A-Z0-9.\-^]{0,14}$')
    strategy: Literal['pullback_ema', 'breakout_base', 'ma_crossover', 'mean_reversion_rsi',
                      'mean_reversion_bb', 'mean_reversion_multi']
    direction: Literal['Bullish', 'Bearish']
    params: dict
    start: date
    end: date
    commission: float = Field(ge=0, lt=1)
    hold_max_days: int | None = Field(ge=1, le=3650)
    min_trades: int = Field(ge=1, le=100000)
    min_win_rate: float = Field(ge=0, le=1)
    initial_cash: Literal[100000]
    order_size: Literal[.9999999999999998]
    margin: Literal[1]
    spread: Literal[0]
    exclusive_orders: Literal[True]
    trade_on_close: Literal[False]
    finalize_trades: Literal[False]
    sizing: Literal['fraction of available equity; whole units']
    confirmed: Literal[True]

    @model_validator(mode='after')
    def explicit_configuration(self):
        if self.start >= self.end or (self.end - self.start).days > 3650:
            raise ValueError('Evaluation window must be positive and at most ten years; end is exclusive')
        if self.end > date.today():
            raise ValueError('Evaluation end cannot be in the future')
        validate_parameters(self.strategy, self.params)
        return self
