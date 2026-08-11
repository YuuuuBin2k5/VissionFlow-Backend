#!/bin/bash

API_KEY="AQ.Ab8RN6Jg-jLI0bl3pMyKth0x6r5NAiz-H7vpWO9Vn6hQw6yq3A"

echo "================================================"
echo "TESTING ALL GEMINI MODELS WITH QUOTA"
echo "================================================"
echo ""

# Array of models to test (from quota list)
models=(
    "gemini-2.5-flash"
    "gemini-2.5-flash-lite"
    "gemini-2.0-flash"
    "gemini-2.0-flash-lite"
    "gemini-3-flash-preview"
    "gemini-3.5-flash"
    "gemini-3.1-flash-lite"
    "gemini-3.1-pro-preview"
    "gemini-2.5-pro"
    "gemini-flash-latest"
)

# Counter for successes
success_count=0
working_models=()

for model in "${models[@]}"; do
    echo "┌─────────────────────────────────────────────"
    echo "│ Testing: $model"
    echo "└─────────────────────────────────────────────"
    
    response=$(curl -s -w "\nHTTP_CODE:%{http_code}" -X POST \
        "https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent" \
        -H "Content-Type: application/json" \
        -H "x-goog-api-key: ${API_KEY}" \
        -d '{
            "contents": [{
                "parts": [{
                    "text": "Say hello"
                }]
            }]
        }')
    
    http_code=$(echo "$response" | grep "HTTP_CODE:" | cut -d':' -f2)
    body=$(echo "$response" | sed '/HTTP_CODE:/d')
    
    # Check for success
    if echo "$body" | grep -q '"candidates"'; then
        echo "✅ SUCCESS (HTTP $http_code)"
        echo "   Response preview: $(echo "$body" | head -c 100)..."
        working_models+=("$model")
        ((success_count++))
    elif echo "$body" | grep -q '"error"'; then
        error_msg=$(echo "$body" | grep -o '"message":"[^"]*"' | head -1)
        echo "❌ FAILED (HTTP $http_code)"
        echo "   Error: $error_msg"
    else
        echo "⚠️  UNKNOWN (HTTP $http_code)"
        echo "   Response: $(echo "$body" | head -c 150)"
    fi
    
    echo ""
    sleep 1  # Rate limit protection
done

echo "================================================"
echo "SUMMARY"
echo "================================================"
echo "Total models tested: ${#models[@]}"
echo "Working models: $success_count"
echo ""

if [ $success_count -gt 0 ]; then
    echo "✅ WORKING MODELS:"
    for model in "${working_models[@]}"; do
        echo "   - $model"
    done
else
    echo "❌ NO WORKING MODELS FOUND!"
fi

echo ""
echo "Test completed at $(date)"
