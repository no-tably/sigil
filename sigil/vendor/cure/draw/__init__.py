"""[Draw]: Theme, Canvas, Layout, Graph, Widgets, Paint, Memo, Views.

{Context} (`context.py`) is the data every widget paints from: theme, charset, caps,
surface level (from the app's base), focus, now.
"""

from .paint import Frame, Tiled, frame, sizes
from .context import Context
