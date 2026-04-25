#!/bin/bash
echo "╔══════════════════════════════════════════╗"
echo "║       PixelForge Studio — Starting       ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "📦 Installing dependencies..."
pip install -r requirements.txt --break-system-packages -q

echo "🚀 Launching Django server..."
echo ""
echo "  Open your browser at:  http://127.0.0.1:8000"
echo ""
python manage.py runserver 0.0.0.0:8000
