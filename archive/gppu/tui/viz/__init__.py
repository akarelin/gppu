# .. archived 2026-11-22: gppu/tui/viz/__init__.py as it was at fec31bb; gppu's reduction removed it
"""Visualization widgets for gppu TUI apps."""

from .heatmap import Heatmap, render_heatmap_lines

__all__ = ['Heatmap', 'render_heatmap_lines']
