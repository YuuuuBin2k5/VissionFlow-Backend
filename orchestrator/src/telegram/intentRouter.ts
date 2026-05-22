export type BotIntentName =
  | 'view_schedule'
  | 'view_status'
  | 'list_pending_approval'
  | 'preview_video'
  | 'approve_publish'
  | 'force_publish'
  | 'reschedule_video'
  | 'pause_campaign'
  | 'resume_campaign'
  | 'cancel_job'
  | 'cancel_campaign'
  | 'explain_job'
  | 'recommend_schedule'
  | 'render_music'
  | 'remix_music'
  | 'render_remix_music'
  | 'create_music_video'
  | 'quick_create_video'
  | 'unknown';

export interface BotIntent {
  intent: BotIntentName;
  confidence: number;
  period?: 'today' | 'week';
  jobId?: number;
  campaignId?: number;
  target?: 'latest_rendered' | 'latest_pending' | 'specific';
  newTimeText?: string;
  requiresConfirmation?: boolean;
  reason?: string;
  songTitle?: string;
  artistName?: string;
  topic?: string;
  targetAudience?: string;
  platform?: 'tiktok' | 'youtube';
  contentType?: 'shorts' | 'video';
}

const SENSITIVE_INTENTS = new Set<BotIntentName>([
  'approve_publish',
  'force_publish',
  'reschedule_video',
  'pause_campaign',
  'resume_campaign',
  'cancel_job',
  'cancel_campaign',
  'remix_music',
  'render_remix_music',
]);

function normalize(text: string) {
  return text.toLowerCase().normalize('NFC').trim();
}

function stripVietnameseTones(text: string) {
  return text
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd')
    .replace(/Đ/g, 'D')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}:_\-\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function hasAny(text: string, patterns: string[]) {
  return patterns.some((pattern) => text.includes(pattern));
}

function firstNumber(text: string) {
  const match = text.match(/\d+/);
  return match ? parseInt(match[0], 10) : undefined;
}

function applyVietnameseDayPeriod(hour: number, text: string) {
  const plain = stripVietnameseTones(text);
  if (hasAny(plain, ['dem', 'khuya']) && hour === 12) return 0;
  if (hasAny(plain, ['chieu', 'toi', 'dem', 'pm']) && hour >= 1 && hour <= 11) return hour + 12;
  if (hasAny(plain, ['trua']) && hour >= 1 && hour <= 10) return hour + 12;
  return hour;
}

function extractTimeText(text: string) {
  const iso = text.match(/\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}/);
  if (iso) return iso[0];

  const explicitHour = text.match(/(?:lúc|sang|vao|vào|luc)\s*(\d{1,2})(?::(\d{2}))?\s*(?:h|giờ)?/i);
  const hourMatches = [...text.matchAll(/(\d{1,2})(?::(\d{2}))?\s*(?:h|giờ)/gi)];
  const hour = explicitHour || (hourMatches.length > 0 ? hourMatches[hourMatches.length - 1] : null);
  if (hour) {
    const minute = hour[2] || '00';
    const lower = stripVietnameseTones(text);
    const dayHint = lower.includes('mai') || lower.includes('tomorrow') ? 'tomorrow' : 'today';
    const resolvedHour = applyVietnameseDayPeriod(parseInt(hour[1], 10), text);
    return `${dayHint} ${String(resolvedHour).padStart(2, '0')}:${minute}`;
  }

  const lower = stripVietnameseTones(text);
  if (lower.includes('mai') || lower.includes('tomorrow')) return 'tomorrow';
  if (lower.includes('hom nay') || lower.includes('today')) return 'today';

  return undefined;
}

function extractQuickVideoTopic(text: string) {
  const cleaned = text
    .replace(/\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}/g, ' ')
    .replace(/\b(?:hôm nay|hom nay|ngày mai|ngay mai|today|tomorrow)\b/gi, ' ')
    .replace(/\b(?:lúc|luc|vào lúc|vao luc|vào|vao)\s*\d{1,2}(?::\d{2})?\s*(?:h|giờ|gio)?\s*(?:sáng|sang|trưa|trua|chiều|chieu|tối|toi|đêm|dem|pm|am)?/gi, ' ')
    .replace(/\d{1,2}(?::\d{2})?\s*(?:h|giờ|gio)\s*(?:sáng|sang|trưa|trua|chiều|chieu|tối|toi|đêm|dem|pm|am)?/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  const topicMatch = cleaned.match(/(?:về|ve|chủ đề|chu de|nội dung|noi dung)\s+(.+)$/i);
  if (topicMatch?.[1]) {
    return topicMatch[1]
      .replace(/^(video|clip|kịch bản|kich ban)\s+/i, '')
      .trim();
  }

  return undefined;
}

function ruleBasedIntent(text: string): BotIntent {
  const lower = normalize(text);
  const plain = stripVietnameseTones(text);
  const haystack = `${lower} ${plain}`;
  const jobId = firstNumber(lower);
  const platform = hasAny(haystack, ['youtube', 'yt', 'shorts', 'youtube short']) ? 'youtube' : undefined;
  const contentType = hasAny(haystack, ['shorts', 'short ', 'youtube short']) ? 'shorts' : undefined;

  // Nhận diện ý định tạo video nhanh cho hôm nay/ngày mai
  if (
    hasAny(haystack, [
      'tạo video', 'tao video', 'tạo clip', 'tao clip',
      'làm video', 'lam video', 'làm clip', 'lam clip',
      'lên kịch bản video', 'len kich ban video',
      'viết kịch bản video', 'viet kich ban video',
      'lên nội dung video', 'len noi dung video',
      'lập kịch bản video', 'lap kich ban video',
      'lên kịch bản', 'len kich ban',
      'viết kịch bản', 'viet kich ban',
      'lên nội dung', 'len noi dung',
      'lập kịch bản', 'lap kich ban',
    ]) &&
    hasAny(haystack, ['hôm nay', 'hom nay', 'ngày mai', 'ngay mai', 'today', 'tomorrow', 'lúc', 'luc', 'giờ', 'gio'])
  ) {
    return {
      intent: 'quick_create_video',
      confidence: 0.9,
      newTimeText: extractTimeText(text),
      topic: extractQuickVideoTopic(text),
      platform,
      contentType,
    };
  }

  if (hasAny(haystack, ['lịch', 'lich', 'schedule', 'ke hoach', 'hen gio', 'gio dang', 'dang luc nao'])) {
    return {
      intent: 'view_schedule',
      confidence: 0.8,
      period: hasAny(haystack, ['tuần', 'tuan', 'week', '7 ngay', 'bay ngay']) ? 'week' : 'today',
      platform,
    };
  }

  if (hasAny(haystack, ['trạng thái', 'trang thai', 'status', 'tiến độ', 'tien do', 'dang lam gi', 'dang lam toi dau', 'toi dau roi', 'den dau', 'co on khong', 'kiem tra bot', 'check bot'])) {
    return { intent: 'view_status', confidence: 0.8 };
  }

  if (hasAny(haystack, ['dời', 'doi', 'đổi giờ', 'doi gio', 'reschedule', 'chuyen gio', 'doi lich', 'day sang', 'keo sang', 'hen lai'])) {
    return {
      intent: 'reschedule_video',
      confidence: 0.8,
      jobId,
      target: jobId ? 'specific' : 'latest_pending',
      newTimeText: extractTimeText(text),
      requiresConfirmation: true,
    };
  }

  if (
    hasAny(haystack, [
      'tạo video nhạc', 'tao video nhac', 'tạo video âm nhạc', 'tao video am nhac',
      'tạo music video', 'tao music video', 'làm video nhạc', 'lam video nhac',
      'làm video âm nhạc', 'lam video am nhac', 'tạo clip nhạc', 'tao clip nhac',
      'tạo music video độc lập', 'tao music video doc lap'
    ])
  ) {
    let songTitle = 'HOT TRENDING';
    let artistName = 'AUTO DETECT';
    
    const parts = lower.split('|');
    if (parts.length > 1) {
      songTitle = parts[0].replace(/tạo video nhạc|tao video nhac|tạo video âm nhạc|tao video am nhac|tạo music video|tao music video|làm video nhạc|lam video nhac|làm video âm nhạc|lam video am nhac/gi, '').trim();
      artistName = parts[1].trim();
    } else {
      const songText = lower.replace(/tạo video nhạc|tao video nhac|tạo video âm nhạc|tao video am nhac|tạo music video|tao music video|làm video nhạc|lam video nhac|làm video âm nhạc|lam video am nhac|bài|bai/gi, '').trim();
      const splitKeywords = [' của ', ' by ', ' ca sĩ ', ' ca si '];
      let splitWord = '';
      for (const kw of splitKeywords) {
        if (songText.includes(kw)) {
          splitWord = kw;
          break;
        }
      }
      if (splitWord) {
        const subparts = songText.split(splitWord);
        songTitle = subparts[0].trim();
        artistName = subparts[1].trim();
      } else if (songText) {
        songTitle = songText;
        artistName = 'Tự động phát hiện';
      }
    }

    return {
      intent: 'create_music_video',
      confidence: 0.9,
      songTitle,
      artistName,
    };
  }

  if (
    hasAny(haystack, ['remix', 'phối lại', 'phoi lai', 'mix lai', 'them bass', 'thêm bass', 'dap bass', 'bass manh', 'nhạc trend', 'nhac trend', 'trend music', 'top thinh hanh', 'thinh hanh', 'hot trend']) ||
    (haystack.includes('trend') && hasAny(haystack, ['nhạc', 'nhac', 'bài', 'bai', 'chill', 'am thanh', 'audio']))
  ) {
    const shouldRender = hasAny(haystack, ['render', 'tạo', 'tao', 'lam video', 'xu ly', 'lam luon', 'cho chay']);
    return {
      intent: shouldRender ? 'render_remix_music' : 'remix_music',
      confidence: 0.8,
      jobId,
      target: jobId ? 'specific' : 'latest_pending',
      requiresConfirmation: true,
    };
  }

  if (hasAny(haystack, ['mau trend', 'mẫu trend', 'goi y trend', 'template trend', 'chon mau', 'chọn mẫu'])) {
    return { intent: 'recommend_schedule', confidence: 0.62, reason: 'User asks for selectable templates.' };
  }

  if (hasAny(haystack, ['render', 'tạo', 'tao', 'lam video', 'xu ly video']) && hasAny(haystack, ['music', 'nhạc', 'nhac', 'chill', 'audio reactive', 'visual nhac', 'song'])) {
    return { intent: 'render_music', confidence: 0.75, jobId, target: jobId ? 'specific' : 'latest_pending' };
  }

  const wantsPublish =
    lower.includes('đăng') ||
    hasAny(haystack, ['post', 'publish', 'up len', 'up tiktok', 'cho len kenh', 'day len']) ||
    /(^|\s)dang\s+(video|bai|job|tiktok)/.test(plain) ||
    (haystack.includes('up') && hasAny(haystack, ['tiktok', 'kenh', 'video'])) ||
    (haystack.includes('dua') && hasAny(haystack, ['len kenh', 'len tiktok']));

  if (wantsPublish) {
    const force = hasAny(haystack, ['ngay', 'lập tức', 'lap tuc', 'force', 'bay gio', 'luon']);
    return {
      intent: force ? 'force_publish' : 'approve_publish',
      confidence: 0.75,
      jobId,
      target: jobId ? 'specific' : 'latest_rendered',
      requiresConfirmation: true,
      platform,
    };
  }

  if (hasAny(haystack, ['chờ duyệt', 'cho duyet', 'pending', 'đã render', 'da render', 'xong chua', 'video san sang', 'can duyet'])) {
    return { intent: 'list_pending_approval', confidence: 0.75 };
  }

  if (hasAny(haystack, ['preview', 'xem video', 'xem truoc', 'cho xem', 'mo video', 'video dau'])) {
    return { intent: 'preview_video', confidence: 0.7, jobId, target: jobId ? 'specific' : 'latest_rendered' };
  }

  if (hasAny(haystack, ['tạm dừng', 'tam dung', 'pause', 'dung lai']) && hasAny(haystack, ['campaign', 'chien dich'])) {
    return { intent: 'pause_campaign', confidence: 0.75, campaignId: jobId, requiresConfirmation: true };
  }

  if (hasAny(haystack, ['tiếp tục', 'tiep tuc', 'resume', 'chay lai']) && hasAny(haystack, ['campaign', 'chien dich'])) {
    return { intent: 'resume_campaign', confidence: 0.75, campaignId: jobId, requiresConfirmation: true };
  }

  if (hasAny(haystack, ['hủy', 'huy', 'cancel', 'xoa bo']) && hasAny(haystack, ['campaign', 'chien dich'])) {
    return { intent: 'cancel_campaign', confidence: 0.75, campaignId: jobId, requiresConfirmation: true };
  }

  if (hasAny(haystack, ['hủy', 'huy', 'cancel', 'bo job', 'xoa job'])) {
    return { intent: 'cancel_job', confidence: 0.7, jobId, requiresConfirmation: true };
  }

  if (hasAny(haystack, ['giải thích', 'giai thich', 'explain', 'vi sao', 'tai sao', 'noi ro'])) {
    return { intent: 'explain_job', confidence: 0.7, jobId };
  }

  if (hasAny(haystack, ['đề xuất', 'de xuat', 'recommend', 'tối ưu', 'toi uu', 'nen lam gi', 'tu van', 'goi y'])) {
    return { intent: 'recommend_schedule', confidence: 0.65 };
  }

  return { intent: 'unknown', confidence: 0.2, reason: 'No rule matched.' };
}

function coerceIntent(value: any, fallback: BotIntent): BotIntent {
  if (!value || typeof value !== 'object') return fallback;
  const intent = value.intent as BotIntentName;
  const valid: BotIntentName[] = [
    'view_schedule', 'view_status', 'list_pending_approval', 'preview_video',
    'approve_publish', 'force_publish', 'reschedule_video', 'pause_campaign',
    'resume_campaign', 'cancel_job', 'cancel_campaign', 'explain_job',
    'recommend_schedule', 'render_music', 'remix_music', 'render_remix_music',
    'create_music_video', 'quick_create_video', 'unknown',
  ];

  if (!valid.includes(intent)) return fallback;

  return {
    intent,
    confidence: typeof value.confidence === 'number' ? value.confidence : 0.6,
    period: value.period === 'week' ? 'week' : value.period === 'today' ? 'today' : fallback.period,
    jobId: typeof value.jobId === 'number' ? value.jobId : fallback.jobId,
    campaignId: typeof value.campaignId === 'number' ? value.campaignId : fallback.campaignId,
    target: value.target || fallback.target,
    newTimeText: typeof value.newTimeText === 'string' ? value.newTimeText : fallback.newTimeText,
    requiresConfirmation: SENSITIVE_INTENTS.has(intent),
    reason: typeof value.reason === 'string' ? value.reason : undefined,
    songTitle: typeof value.songTitle === 'string' ? value.songTitle : fallback.songTitle,
    artistName: typeof value.artistName === 'string' ? value.artistName : fallback.artistName,
    topic: typeof value.topic === 'string' ? value.topic : fallback.topic,
    targetAudience: typeof value.targetAudience === 'string' ? value.targetAudience : fallback.targetAudience,
    platform: value.platform === 'youtube' ? 'youtube' : value.platform === 'tiktok' ? 'tiktok' : fallback.platform,
    contentType: value.contentType === 'shorts' ? 'shorts' : value.contentType === 'video' ? 'video' : fallback.contentType,
  };
}

async function callGeminiIntent(text: string, fallback: BotIntent): Promise<BotIntent | null> {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) return null;

  const prompt = `
Bạn là intent router cho Telegram bot quản lý kênh TikTok. Chỉ trả JSON hợp lệ, không markdown.
Người dùng có thể viết sai dấu, thiếu dấu, typo, nói tắt hoặc nói vòng. Hãy suy luận ý định gần nhất, nhưng không bịa jobId/campaignId nếu người dùng không nói rõ.
Nếu hành động thay đổi dữ liệu hoặc đăng video mà target mơ hồ, trả target="latest_pending" hoặc "latest_rendered" theo ngữ cảnh và để hệ thống xác nhận sau.
- Nếu người dùng muốn tạo một video âm nhạc / video nhạc / clip nhạc hoặc nhắc tới bài hát cụ thể (ví dụ: "tạo video nhạc", "làm clip nhạc", "tạo music video", "lên video bài hát..."), trả về intent="create_music_video" và trích xuất "songTitle", "artistName".
- Nếu người dùng muốn tạo/lên kịch bản/lên nội dung/lên lịch nhanh cho 1 video đơn lẻ nói chung (ví dụ: "lên kịch bản video cho hôm nay vào lúc 5h chiều", "làm clip ngày mai", "tạo video về học tiếng Anh hôm nay 17h"), trả về intent="quick_create_video". Hãy suy luận giờ Việt Nam: "5h chiều" = "today 17:00", "8h tối" = "today 20:00".
- Nếu câu nhắc YouTube/YT/Shorts, trả "platform"="youtube"; nếu nhắc TikTok, trả "platform"="tiktok". Nếu câu nhắc Shorts, trả "contentType"="shorts", ngược lại có thể là "video".
- Nếu câu có chủ đề sau các cụm "về...", "chủ đề...", "nội dung...", trích xuất vào "topic". Nếu có đối tượng xem, trích xuất vào "targetAudience"; nếu không có thì bỏ trống.
- Nếu câu chỉ hỏi mẫu/gợi ý/cách làm, ưu tiên recommend_schedule.

Intent hợp lệ:
view_schedule, view_status, list_pending_approval, preview_video, approve_publish, force_publish,
reschedule_video, pause_campaign, resume_campaign, cancel_job, cancel_campaign, explain_job,
recommend_schedule, render_music, remix_music, render_remix_music, create_music_video, quick_create_video, unknown.

Schema:
{
  "intent": "view_schedule",
  "confidence": 0.0,
  "period": "today|week",
  "jobId": 12,
  "campaignId": 1,
  "target": "latest_rendered|latest_pending|specific",
  "newTimeText": "YYYY-MM-DD HH:mm hoặc today 22:00 hoặc tomorrow 19:30 hoặc today hoặc tomorrow",
  "songTitle": "Tên bài hát nếu tạo video âm nhạc độc lập mới",
  "artistName": "Tên ca sĩ nếu tạo video âm nhạc độc lập mới",
  "topic": "Chủ đề video nếu người dùng đã nói rõ",
  "targetAudience": "Đối tượng xem nếu người dùng đã nói rõ",
  "platform": "tiktok|youtube",
  "contentType": "shorts|video",
  "reason": "ngắn gọn"
}

Tin nhắn người dùng: "${text.replace(/"/g, '\\"')}"
`;

  try {
    const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${apiKey}`;
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
        generationConfig: { temperature: 0.1, responseMimeType: 'application/json' },
      }),
    });

    if (!response.ok) return null;
    const data: any = await response.json();
    const raw = data?.candidates?.[0]?.content?.parts?.[0]?.text;
    if (!raw) return null;

    return coerceIntent(JSON.parse(raw), fallback);
  } catch (error) {
    console.error('[IntentRouter] Gemini intent parse failed:', error);
    return null;
  }
}

export async function parseBotIntent(text: string): Promise<BotIntent> {
  const fallback = ruleBasedIntent(text);
  const geminiIntent = await callGeminiIntent(text, fallback);
  return geminiIntent || fallback;
}
