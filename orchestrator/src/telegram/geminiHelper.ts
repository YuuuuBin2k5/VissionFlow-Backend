import dotenv from 'dotenv';
dotenv.config();

export const GEMINI_MODEL_CANDIDATES = [
  process.env.GEMINI_MODEL,
  process.env.GOOGLE_GEMINI_MODEL,
  'gemini-2.5-flash',
  'gemini-2.5-flash-lite',
  'gemini-2.5-pro',
  'gemini-2.0-flash',
].filter(Boolean) as string[];

export interface GeminiRequestOptions {
  temperature?: number;
  responseMimeType?: 'application/json' | 'text/plain';
}

export async function generateContentWithFallback(
  prompt: string,
  options: GeminiRequestOptions = {}
): Promise<{ text: string; modelUsed: string }> {
  const rawKey = process.env.GEMINI_API_KEY || '';
  const rawKeys = process.env.GEMINI_API_KEYS || '';
  const mergedKeys = `${rawKey},${rawKeys}`;
  
  // Support comma-separated list of API keys for rotation
  let apiKeys = mergedKeys.split(',').map(k => k.trim()).filter(Boolean);

  const errors: string[] = [];
  const temperature = options.temperature ?? 0.7;
  const responseMimeType = options.responseMimeType ?? 'application/json';

  // 1. Thử các tài nguyên của Gemini trước
  if (apiKeys.length > 0) {
    for (const model of GEMINI_MODEL_CANDIDATES) {
      for (let i = 0; i < apiKeys.length; i++) {
        const apiKey = apiKeys[i];
        const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 8000); // 8 giây timeout

        try {
          const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              contents: [{ parts: [{ text: prompt }] }],
              generationConfig: { temperature, responseMimeType },
            }),
            signal: controller.signal
          });

          clearTimeout(timeoutId);

          if (!response.ok) {
            errors.push(`${model} (Key #${i + 1}): ${response.status}`);
            if (response.status === 429) {
              console.warn(`[Gemini] API Key #${i + 1} bị quá hạn ngạch (429). Đang chuyển sang key tiếp theo...`);
              apiKeys.splice(i, 1);
              i--; 
            }
            continue;
          }

          const data: any = await response.json();
          const text = data?.candidates?.[0]?.content?.parts?.[0]?.text;
          if (text) {
            return { text: text.trim(), modelUsed: model };
          }
          errors.push(`${model} (Key #${i + 1}): empty response`);
        } catch (error: any) {
          clearTimeout(timeoutId);
          const isAbort = error.name === 'AbortError' || error.message?.includes('aborted');
          errors.push(`${model} (Key #${i + 1}): ${isAbort ? 'Timeout 8s' : error.message}`);
        }
      }
    }
  } else {
    errors.push('Không có GEMINI_API_KEY hay GEMINI_API_KEYS nào được thiết lập');
  }

  // 2. Dự phòng 1: Sử dụng Groq (Llama 3, Mixtral...)
  try {
    const groqResult = await callGroqFallback(prompt, errors);
    if (groqResult) return groqResult;
  } catch (err: any) {
    errors.push(`Groq Fatal: ${err.message}`);
  }

  // 3. Dự phòng 2: Sử dụng OpenRouter (DeepSeek, Llama, Gemini...)
  try {
    const openRouterResult = await callOpenRouterFallback(prompt, errors);
    if (openRouterResult) return openRouterResult;
  } catch (err: any) {
    errors.push(`OpenRouter Fatal: ${err.message}`);
  }

  throw new Error(`Không model hoặc API Key nào phản hồi hợp lệ (${errors.join('; ')}).`);
}

async function callGroqFallback(prompt: string, errors: string[]): Promise<{ text: string; modelUsed: string } | null> {
  const apiKey = process.env.GROQ_API_KEY;
  if (!apiKey) return null;

  const models = ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant', 'mixtral-8x7b-32768', 'llama3-8b-8192'];
  for (const model of models) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 8000);

    try {
      const response = await fetch('https://api.groq.com/openai/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${apiKey}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          model,
          messages: [{ role: 'user', content: prompt }],
          temperature: 0.1,
          response_format: { type: 'json_object' }
        }),
        signal: controller.signal
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        errors.push(`Groq (${model}): ${response.status}`);
        continue;
      }

      const data: any = await response.json();
      const text = data?.choices?.[0]?.message?.content;
      if (text) {
        return { text: text.trim(), modelUsed: `Groq:${model}` };
      }
      errors.push(`Groq (${model}): empty response`);
    } catch (err: any) {
      clearTimeout(timeoutId);
      const isAbort = err.name === 'AbortError' || err.message?.includes('aborted');
      errors.push(`Groq (${model}): ${isAbort ? 'Timeout 8s' : err.message}`);
    }
  }
  return null;
}

async function callOpenRouterFallback(prompt: string, errors: string[]): Promise<{ text: string; modelUsed: string } | null> {
  const apiKey = process.env.OPENROUTER_API_KEY;
  if (!apiKey) return null;

  const models = ['google/gemini-2.5-flash:free', 'meta-llama/llama-3.3-70b-instruct:free', 'deepseek/deepseek-chat'];
  for (const model of models) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 8000);

    try {
      const response = await fetch('https://openrouter.ai/api/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${apiKey}`,
          'Content-Type': 'application/json',
          'HTTP-Referer': 'https://github.com/YuuBin/AgentBot',
          'X-Title': 'AgentBot'
        },
        body: JSON.stringify({
          model,
          messages: [{ role: 'user', content: prompt }],
          temperature: 0.1,
          response_format: { type: 'json_object' }
        }),
        signal: controller.signal
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        errors.push(`OpenRouter (${model}): ${response.status}`);
        continue;
      }

      const data: any = await response.json();
      const text = data?.choices?.[0]?.message?.content;
      if (text) {
        return { text: text.trim(), modelUsed: `OpenRouter:${model}` };
      }
      errors.push(`OpenRouter (${model}): empty response`);
    } catch (err: any) {
      clearTimeout(timeoutId);
      const isAbort = err.name === 'AbortError' || err.message?.includes('aborted');
      errors.push(`OpenRouter (${model}): ${isAbort ? 'Timeout 8s' : err.message}`);
    }
  }
  return null;
}

export function cleanAndParseJson(rawText: string): any {
  if (!rawText) return null;
  let text = rawText.trim();
  
  // 1. Loại bỏ các khối code block markdown ```json ... ``` hoặc ``` ... ```
  if (text.includes('```')) {
    const lines = text.split('\n');
    const cleanedLines = [];
    let inCodeBlock = false;
    for (const line of lines) {
      if (line.trim().startsWith('```')) {
        inCodeBlock = !inCodeBlock;
        continue;
      }
      cleanedLines.push(line);
    }
    text = cleanedLines.join('\n').trim();
  }

  // 2. Tìm ký tự mở đầu JSON thực sự ( { hoặc [ )
  let firstCharIndex = -1;
  let openChar = '';
  let closeChar = '';
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '{') {
      firstCharIndex = i;
      openChar = '{';
      closeChar = '}';
      break;
    } else if (text[i] === '[') {
      firstCharIndex = i;
      openChar = '[';
      closeChar = ']';
      break;
    }
  }

  if (firstCharIndex !== -1) {
    let depth = 0;
    let inString = false;
    let escapeNext = false;
    let matchingIndex = -1;
    for (let i = firstCharIndex; i < text.length; i++) {
      const char = text[i];
      if (escapeNext) {
        escapeNext = false;
        continue;
      }
      if (char === '\\') {
        escapeNext = true;
        continue;
      }
      if (char === '"') {
        inString = !inString;
        continue;
      }
      if (!inString) {
        if (char === openChar) {
          depth++;
        } else if (char === closeChar) {
          depth--;
          if (depth === 0) {
            matchingIndex = i;
            break;
          }
        }
      }
    }

    if (matchingIndex !== -1) {
      text = text.substring(firstCharIndex, matchingIndex + 1);
    } else {
      // Fallback nếu không tìm thấy matching brace/bracket
      const lastCloseIndex = text.lastIndexOf(closeChar);
      if (lastCloseIndex > firstCharIndex) {
        text = text.substring(firstCharIndex, lastCloseIndex + 1);
      }
    }
  }

  // 3. Tiến hành Parse JSON an toàn
  try {
    return JSON.parse(text);
  } catch (error: any) {
    // Dự phòng dấu phẩy thừa ở cuối các phần tử JSON (trailing commas)
    try {
      const relaxedText = text.replace(/,(\s*[}\]])/g, '$1');
      return JSON.parse(relaxedText);
    } catch {
      throw new Error(`JSON parse error: ${error.message} (Raw: ${rawText})`);
    }
  }
}
