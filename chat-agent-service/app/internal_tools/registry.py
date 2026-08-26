# app/internal_tools/registry.py
from langchain_core.tools import tool

@tool
def get_current_datetime() -> str:
    """Returns the current date and time."""
    
@tool
def calculate(expression: str) -> str:
    """Evaluates a math expression safely."""

ALL_INTERNAL_TOOLS = [get_current_datetime, calculate]
INTERNAL_TOOL_MAP = {t.name: t for t in ALL_INTERNAL_TOOLS}