#!/bin/bash
# VPLink Web Control Center — Start Script
# Usage: ./start.sh [port]
# Default API port: 5180, Frontend dev: 5173

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLIENT_DIR="$SCRIPT_DIR/client"
SERVER_DIR="$SCRIPT_DIR/server"
API_PORT="${1:-5180}"
WEB_PORT="${2:-5173}"

echo "⚡ VPLink Web Control Center"
echo "   API: http://localhost:$API_PORT"
echo "   Web: http://localhost:$WEB_PORT"
echo ""

# Start API server
echo "Starting API server on port $API_PORT..."
VPLINK_WEB_PORT=$API_PORT python3 "$SERVER_DIR/app.py" &
SERVER_PID=$!
sleep 1

# Verify API
if curl -s "http://localhost:$API_PORT/api/health" > /dev/null 2>&1; then
  echo "✓ API server running"
else
  echo "✗ API server failed to start"
  kill $SERVER_PID 2>/dev/null
  exit 1
fi

# Start frontend dev server (or serve built files)
if [ -d "$CLIENT_DIR/dist" ]; then
  echo "Serving built frontend on port $WEB_PORT..."
  cd "$CLIENT_DIR"
  npx serve dist -l $WEB_PORT &
  FRONTEND_PID=$!
else
  echo "Building and serving frontend on port $WEB_PORT..."
  cd "$CLIENT_DIR"
  npm run build 2>/dev/null
  npx serve dist -l $WEB_PORT &
  FRONTEND_PID=$!
fi

sleep 1
echo "✓ Frontend running"
echo ""
echo "🌐 Open http://localhost:$WEB_PORT in your browser"
echo "   Press Ctrl+C to stop"
echo ""

# Cleanup on exit
trap "kill $SERVER_PID $FRONTEND_PID 2>/dev/null; echo 'Stopped.'" EXIT
wait
