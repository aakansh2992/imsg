"""TuneUp — an honest laptop scan / optimize / battery-care toolkit.

Scans hardware, software, and drivers on Windows, recommends updates and
optimizations (rules engine + optional Claude AI analysis), applies safe fixes
with consent, and runs a battery management (BMS) loop that stops/resumes
charging via vendor hooks or a smart plug.

What software can and cannot do about charging is documented in README.md —
this tool never pretends to control an embedded controller it can't reach.
"""

__version__ = "0.1.0"
