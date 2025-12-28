#!/bin/bash
# Setup script for infiniteCATs backend

set -e

echo "📦 infiniteCATs Backend Setup"
echo "================================"

# Check Python version
python3 --version

# Create virtual environment
echo "Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt

echo ""
echo "✓ Setup complete!"
echo ""
echo "Make sure you have a .env file with your CEREBRAS_API_KEY:"
echo "  CEREBRAS_API_KEY=your_key_here"
echo ""
echo "Then start the server:"
echo "  source venv/bin/activate"
echo "  python app.py"
