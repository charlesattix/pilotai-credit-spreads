#!/bin/bash

# Credit Spread Trading System - Setup Script

echo "===================================================================="
echo "Credit Spread Trading System - Setup"
echo "===================================================================="
echo ""

# Check Python version
echo "Checking Python version..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version)
    echo "✓ Found: $PYTHON_VERSION"
else
    echo "✗ Python 3 not found. Please install Python 3.8 or higher."
    exit 1
fi

echo ""

# Create virtual environment (optional but recommended)
read -p "Create a virtual environment? (recommended) [y/N]: " create_venv
if [[ "$create_venv" =~ ^[Yy]$ ]]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "✓ Virtual environment created"
    echo ""
    echo "To activate it, run:"
    echo "  source venv/bin/activate  (Mac/Linux)"
    echo "  venv\\Scripts\\activate     (Windows)"
    echo ""
    read -p "Activate now? [y/N]: " activate_now
    if [[ "$activate_now" =~ ^[Yy]$ ]]; then
        source venv/bin/activate
    fi
fi

echo ""
echo "Installing dependencies..."

# Try to install ta-lib separately (often fails)
echo "Attempting to install TA-Lib..."
pip3 install ta-lib 2>/dev/null
if [ $? -eq 0 ]; then
    echo "✓ TA-Lib installed successfully"
else
    echo "⚠ TA-Lib installation failed (this is common)"
    echo "  The system will use pandas-ta as a fallback"
fi

echo ""
echo "Installing other dependencies..."
pip3 install -r requirements.txt

if [ $? -eq 0 ]; then
    echo "✓ Dependencies installed successfully"
else
    echo "✗ Error installing dependencies"
    exit 1
fi

echo ""
echo "Creating required directories..."
mkdir -p data output logs output/backtest_reports
touch data/.gitkeep output/.gitkeep logs/.gitkeep
echo "✓ Directories created"

echo ""
echo "===================================================================="
echo "Setup Complete!"
echo "===================================================================="
echo ""
echo "Quick Start:"
echo "  1. Review/edit config.yaml for your preferences"
echo "  2. Run: python3 main.py scan"
echo "  3. Check output/alerts.txt for opportunities"
echo ""
echo "For detailed usage, see:"
echo "  - README.md (full documentation)"
echo "  - QUICKSTART.md (5-minute guide)"
echo "  - SAMPLE_OUTPUT.md (example alerts)"
echo ""
echo "Happy trading! 📈"
echo ""
