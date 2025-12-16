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
echo "Make sure Ollama is running:"
echo "  ollama serve"
echo ""
echo "Then in another terminal, start the server:"
echo "  source venv/bin/activate"
echo "  python app.py"
