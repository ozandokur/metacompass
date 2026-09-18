"""MetaCompass: a tool-using agent for BI metadata questions that knows when to abstain.

The package is layered left to right (spec §3.2):
data -> store -> indices (retrieval, graph) -> tools -> agent -> api / ui.
All metadata it works on is synthetic (fictional company: Northwind Motors).
"""

__version__ = "0.1.0"
