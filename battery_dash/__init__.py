"""Battery Cycling Test Analytics Dashboard.

Ingests raw battery cycler data (NASA PCoE .mat files or generic cycler CSV
exports), computes cycle-level metrics with Pandas/SciPy, stores everything in
a SQLite test-tracking database, and serves an interactive Plotly Dash app.
"""

__version__ = "1.0.0"
