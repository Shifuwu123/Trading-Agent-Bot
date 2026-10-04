"""
agents/__init__.py
Módulo de subagentes del sistema multi-agente.
"""
from agents.base_agent import BaseAgent
from agents.scalper_agent import ScalperAgent
from agents.momentum_agent import MomentumAgent
from agents.speculative_agent import SpeculativeAgent
from agents.macro_agent import MacroTraderAgent

__all__ = [
    "BaseAgent",
    "ScalperAgent",
    "MomentumAgent",
    "SpeculativeAgent",
    "MacroTraderAgent",
]
