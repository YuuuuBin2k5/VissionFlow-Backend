#!/bin/bash

API_KEY="AQ.Ab8RN6Jg-jLI0bl3pMyKth0x6r5NAiz-H7vpWO9Vn6hQw6yq3A"

echo "================================================"
echo "TESTING STRUCTURED OUTPUT (JSON Schema)"
echo "================================================"
echo ""

# Test with working models
models=("gemini-3.1-flash-lite" "gemini-3-flash-preview")

for model in "${models[@]}"; do
    echo "┌─────────────────────────────────────────────"
    echo "│ Testing: $model"
    echo "└─────────────────────────────────────────────"
    
    response=$(curl -s -X POST \
        "https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent" \
        -H "Content-Type: application/json" \
        -H "x-goog-api-key: ${API_KEY}" \
        -d '{
            "contents": [{
                "parts": [{
                    "text": "Create a simple video script with 1 scene"
                }]
            }],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "title": {
                            "type": "STRING"
                        },
                        "scenes": {
                            "type": "ARRAY",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "narration": {"type": "STRING"},
                                    "duration": {"type": "INTEGER"}
                                },
                                "required": ["narration", "duration"]
                            }
                        }
                    },
                    "required": ["title", "scenes"]
                }
            }
        }')
    
    # Check for success
    if echo "$response" | grep -q '"candidates"'; then
        echo "✅ SUCCESS"
        # Extract and validate JSON structure
        json_text=$(echo "$response" | jq -r '.candidates[0].content.parts[0].text' 2>/dev/null)
        if [ $? -eq 0 ] && [ ! -z "$json_text" ]; then
            echo "📦 Structured JSON Response:"
            echo "$json_text" | jq '.' 2>/dev/null || echo "$json_text"
            
            # Validate required fields
            if echo "$json_text" | jq -e '.title' >/dev/null 2>&1 && \
               echo "$json_text" | jq -e '.scenes' >/dev/null 2>&1; then
                echo "✅ Schema validation: PASSED"
            else
                echo "❌ Schema validation: FAILED (missing required fields)"
            fi
        else
            echo "⚠️  Could not parse structured output"
        fi
    else
        echo "❌ FAILED"
        echo "$response" | jq '.error.message' 2>/dev/null || echo "$response"
    fi
    
    echo ""
    sleep 2
done

echo "================================================"
echo "Test completed"
echo "================================================"
