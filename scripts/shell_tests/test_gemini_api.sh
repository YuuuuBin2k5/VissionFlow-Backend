#!/bin/bash

# Test Gemini API key
API_KEY="AQ.Ab8RN6Jg-jLI0bl3pMyKth0x6r5NAiz-H7vpWO9Vn6hQw6yq3A"

echo "Testing Gemini API key..."
echo "Testing multiple models..."
echo ""

# Test gemini-3.5-flash (newest)
echo "=== Testing gemini-3.5-flash (Gemini 3 - newest) ==="
curl -X POST \
  "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent" \
  -H "Content-Type: application/json" \
  -H "x-goog-api-key: ${API_KEY}" \
  -d '{
    "contents": [{
      "parts": [{
        "text": "Say hello in one word"
      }]
    }]
  }' \
  --silent \
  --show-error \
  --write-out "\n\nHTTP Status: %{http_code}\n"

echo ""
echo "=== Testing gemini-1.5-flash (stable fallback) ==="
curl -X POST \
  "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent" \
  -H "Content-Type: application/json" \
  -H "x-goog-api-key: ${API_KEY}" \
  -d '{
    "contents": [{
      "parts": [{
        "text": "Say hello in one word"
      }]
    }]
  }' \
  --silent \
  --show-error \
  --write-out "\n\nHTTP Status: %{http_code}\n"

echo ""
echo "=========================="
echo "Test completed!"
echo ""
echo "RECOMMENDATION: Use gemini-3.5-flash (newest, best performance) or gemini-1.5-flash (stable)"
