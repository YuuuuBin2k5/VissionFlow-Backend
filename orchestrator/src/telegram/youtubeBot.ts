import { Telegraf, Markup } from 'telegraf';
import dotenv from 'dotenv';
import prisma from '../database/db';
import { addJobToQueue, tiktokQueue } from '../queue/queue';
import { parseBotIntent } from './intentRouter';
import {
  YOUTUBE_BOT_COMMANDS,
  buildActiveSessionLockMessage,
  buildContentHubMessage,
  buildHelpMessage,
  buildSetupMessage,
  buildStartMessage,
  buildUnknownIntentMessage,
  youtubeContentKeyboard,
  youtubeMainKeyboard,
} from './botUxCatalog';
import { generateContentWithFallback, cleanAndParseJson } from './geminiHelper';
import {
  auditBotAction,
  buildActionSummary,
  buildYouTubeMetadata,
  createOrUpdateYouTubePublishTarget,
  detectJobContentType,
  executeConfirmedAction,
  formatDateTime,
  getYouTubePendingApprovalReport,
  getYouTubeScheduleReport,
  getYouTubeStatusReport,
  parseScheduleTime,
  resolveJobId,
  resolveTimeWithContext,
  escapeHtml,
  getRecommendation,
} from './botActions';
import { cancelConfirmation, consumeConfirmation, createConfirmation, getLatestPendingConfirmation } from './confirmationStore';
import { deletePublishTarget, findYouTubeTargetByConnection, findYouTubeTargets, getYouTubeTargetStatusCounts, parseTargetTags, updateYouTubeTarget } from '../database/publishTargetRepo';
import {
  disconnectPlatform,
  getAllPlatformConnections,
  getConnectedPlatformConnection as originalGetConnected,
  upsertTelegramUser,
} from '../database/userConnectionRepo';

// Hàm tự động ưu tiên kênh chính "Góc Chiêm Nghiệm | YuuBin" và loại trừ kênh phụ của bot kia
async function getConnectedPlatformConnection(userId: number, platform: 'youtube' | 'tiktok') {
  if (platform === 'youtube') {
    const connections = await getAllPlatformConnections(userId, 'youtube');
    // Tìm connection có account_name chứa 'chiem nghiem' hoặc 'yuubin'
    const found = connections.find(c => 
      c.account_name && 
      (c.account_name.toLowerCase().includes('chiem nghiem') || 
       c.account_name.toLowerCase().includes('yuubin'))
    );
    if (found && found.status === 'connected') return found;
    
    // Nếu không tìm thấy, lấy kết nối đầu tiên KHÔNG phải là AsinMochii để tránh bị dính chéo
    const fallback = connections.find(c => 
      c.account_name && 
      !c.account_name.toLowerCase().includes('asinmochii') &&
      !c.account_name.toLowerCase().includes('mochii') &&
      !c.account_name.toLowerCase().includes('bonii')
    );
    if (fallback && fallback.status === 'connected') return fallback;
  }
  return originalGetConnected(userId, platform);
}

// Lấy danh sách kênh YouTube thuộc về bot này (Góc Chiêm Nghiệm | YuuBin)
// Loại bỏ kênh AsinMochiiBonii để tránh hiển thị nhầm sang bot kia
async function getOwnYouTubeConnections(userId: number) {
  const all = await getAllPlatformConnections(userId, 'youtube');
  const own = all.filter(c =>
    !c.account_name ||
    (!c.account_name.toLowerCase().includes('asinmochii') &&
     !c.account_name.toLowerCase().includes('mochii') &&
     !c.account_name.toLowerCase().includes('bonii'))
  );
  // Nếu lọc ra rỗng (chưa xác định kênh nào), trả về tất cả để tránh bị mất kết nối
  return own.length > 0 ? own : all;
}
import { buildYouTubeConnectUrl } from '../services/youtubeOAuthService';
import * as fs from 'fs';
import path from 'path';

dotenv.config();

const MUSIC_AUDIO_WAITING_STATE = 'WAITING_MUSIC_AUDIO';
const ACCEPTED_MUSIC_AUDIO_EXTENSIONS = new Set(['.mp3', '.wav', '.m4a']);
const ACCEPTED_MUSIC_IMAGE_EXTENSIONS = new Set(['.jpg', '.jpeg', '.png', '.webp']);
const MUSIC_UPLOAD_DIR = path.resolve(__dirname, '..', '..', '..', 'worker', 'temp_assets', 'user_music_uploads');
const CANCELLABLE_PIPELINE_STATES = [
  MUSIC_AUDIO_WAITING_STATE,
  'QUEUED',
  'PLANNING',
  'AI_PROCESSING',
  'ASSETS_READY',
  'AUDIO_COMPOSED',
  'RENDERING',
  'RENDER_QUEUED',
  'PUBLISH_QUEUED',
  'PUBLISHING',
  'USER_APPROVED',
];

interface ActiveCreationSession {
  chatId: number;
  kind: 'single_video' | 'music_video' | 'render_music' | 'campaign' | 'translate_dub';
  title: string;
  subtitle: string;
  jobId?: number;
  campaignId?: number;
  messageId?: number;
  startedAt: number;
  timer?: NodeJS.Timeout;
  lastText?: string;
  lastEditTime?: number;
  tempSourceType?: 'file' | 'link';
  tempSourcePath?: string;
  tempSourceUrl?: string;
  tempFileName?: string;
}

interface CampaignWizardState {
  step: 'awaiting_topic' | 'awaiting_target';
  topic?: string;
  target?: string;
  targetDate?: 'today' | 'tomorrow' | string;
}

const activeCreationSessions = new Map<number, ActiveCreationSession>();
const campaignWizards = new Map<number, CampaignWizardState>();
const calendarEditStates = new Map<number, { jobId: number }>();
const calendarInputStates = new Map<number, { step: 'awaiting_date' }>();

const JOB_CONFIG_KEYS = new Set([
  'mood',
  'remix_style',
  'bpm',
  'song_title',
  'artist_name',
  'caption',
  'audio_path',
  'background_video_path',
  'rights_confirmed',
]);

const TREND_PRESETS: Record<string, { label: string; updates: Record<string, any>; description: string }> = {
  trend_bass: {
    label: 'Trend Bass',
    description: 'Bass mạnh, phù hợp video phong cách trẻ trung, visual mạnh.',
    updates: { remix_style: 'trend_bass', mood: 'CYBERPUNK_NIGHT', bpm: 128 },
  },
  deep_house: {
    label: 'Deep House',
    description: 'Nhịp đều đặn, phù hợp nội dung đêm/tập trung/tài chính.',
    updates: { remix_style: 'deep_house', mood: 'FOCUS_LOFI', bpm: 124 },
  },
  lofi_chill: {
    label: 'Lofi Chill',
    description: 'Nhịp chậm, ấm áp, phù hợp học tập/kể chuyện/thư giãn.',
    updates: { remix_style: 'lofi_chill', mood: 'COZY_CHILL', bpm: 88 },
  },
};

const token = process.env.YOUTUBE_TELEGRAM_BOT_TOKEN;
if (!token || token === 'YOUR_YOUTUBE_TELEGRAM_BOT_TOKEN_HERE') {
  console.warn('[YouTube Bot] WARNING: YOUTUBE_TELEGRAM_BOT_TOKEN is not configured. Bot will not start.');
}

const telegramHandlerTimeoutMs = parseInt(process.env.TELEGRAM_HANDLER_TIMEOUT_MS || '600000', 10);

function isTelegrafTimeout(error: any) {
  return String(error?.name || '').includes('Timeout') ||
    String(error?.message || '').includes('Promise timed out');
}

export const youtubeBot = new Telegraf(token || '', { handlerTimeout: telegramHandlerTimeoutMs });

youtubeBot.telegram.setMyCommands(YOUTUBE_BOT_COMMANDS).catch((error) => {
  console.warn('[YouTube Bot Warning] Could not register command menu:', error?.message || error);
});

youtubeBot.catch((err: any, ctx) => {
  if (isTelegrafTimeout(err)) {
    console.warn(
      `[YouTube Bot Warning] Handler xử lý quá ${telegramHandlerTimeoutMs}ms cho update ${ctx.updateType}. ` +
      'Nếu thao tác này thường xuyên chậm, hãy chuyển phần xử lý dài sang hàng đợi nền.'
    );
    return;
  }
  console.error(`[YouTube Bot Error] Error for ${ctx.updateType}:`, err);
  try {
    ctx.reply(`🚨 THÔNG BÁO LỖI HỆ THỐNG YOUTUBE BOT: ${err.message || err}`);
  } catch (replyErr) {
    console.error('[YouTube Bot Error] Failed to send error reply:', replyErr);
  }
});

const AMBIGUOUS_MUSIC_TITLE_NORMALIZED = new Set([
  'tunglacuaanhau',
]);

function isCancelRequest(text: string) {
  const normalized = text.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd').trim();
  return ['/cancel', 'cancel', 'huy', 'huy thao tac', 'dung lai', 'stop'].includes(normalized);
}

function cancelOnlyKeyboard(session: ActiveCreationSession) {
  const target = session.jobId ? String(session.jobId) : 'pending';
  return Markup.inlineKeyboard([
    [Markup.button.callback('Hủy thao tác', `yt:cancel_active:${target}:${session.chatId}`)],
  ]);
}

function isAutoMusicValue(value?: string | null) {
  const normalized = String(value || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd')
    .trim();
  if (!normalized) return true;

  const autoWords = [
    'hot trending',
    'auto detect',
    'tu dong phat hien',
    'tu dong san tim trend',
    'video am nhac xu huong',
    'nhac xu huong',
    'auto',
    'trending',
    'ngau nhien',
    'random',
    'hot trend',
    'bai hat hot',
    'trend hot',
    'xu huong',
  ];
  if (autoWords.includes(normalized)) return true;

  const commandPatterns = [
    'tao video', 'lam video', 'dang giup', 'dang ho', 'len lich', 'quay video', 'render video',
    'giup toi', 'giup em', 'giup minh', 'cho toi', 'cho minh', 'cho em', 'sang mai', 'chieu mai',
    'toi mai', 'ngay mai', 'hom nay', 'ngay kia', 'tuan sau', 'gio sang', 'gio chieu', 'gio toi',
    'dang dung gio', 'dang ho toi', 'dang ho em', 'dang ho minh'
  ];
  for (const pattern of commandPatterns) {
    if (normalized.includes(pattern)) return true;
  }

  if ((normalized.startsWith('hay ') || normalized.startsWith('tao ') || normalized.startsWith('lam ')) && normalized.length > 12) {
    return true;
  }

  return false;
}

function normalizeMusicText(value?: string | null) {
  return String(value || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd')
    .replace(/[^a-z0-9]+/g, '')
    .trim();
}

function isKnownAmbiguousMusicTitle(songTitle: string) {
  return AMBIGUOUS_MUSIC_TITLE_NORMALIZED.has(normalizeMusicText(songTitle));
}

function buildArtistRequiredError(songTitle: string) {
  return `Tên bài "${songTitle}" có nhiều phiên bản/nghệ sĩ nên hệ thống không tự đoán để tránh sai file. Vui lòng nhập rõ theo mẫu /music_video ${songTitle} | Ca sĩ.`;
}

async function resolveConcreteMusicIdea(songTitle: string, artistName: string) {
  if (!isAutoMusicValue(songTitle) && !isAutoMusicValue(artistName)) {
    return { songTitle, artistName, mood: 'COZY_CHILL' };
  }

  const hasSpecificTitle = !isAutoMusicValue(songTitle);
  const hasSpecificArtist = !isAutoMusicValue(artistName);
  if (hasSpecificTitle && !hasSpecificArtist && isKnownAmbiguousMusicTitle(songTitle)) {
    throw new Error(buildArtistRequiredError(songTitle));
  }
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    throw new Error('Không thể tự chọn bài hát vì GEMINI_API_KEY chưa được cấu hình. Vui lòng nhập rõ tên bài hát và ca sĩ, hoặc cấu hình Gemini.');
  }

  try {
    const prompt = `
Bạn là giám đốc dữ liệu âm nhạc Việt Nam.
Người dùng đã cung cấp TÊN BÀI HÁT CỐ ĐỊNH. Bạn chỉ được tìm/điền đúng ca sĩ hoặc nghệ sĩ của bài đó.
TUYỆT ĐỐI KHÔNG đổi sang bài hát khác.

ĐẦU VÀO:
- Tên bài cố định: "${songTitle}"
- Ca sĩ hiện tại: "${artistName}"

Hãy phân tích bài hát nổi tiếng nhất tương ứng và điền tên nghệ sĩ thực tế. Trả về định dạng JSON thuần không bọc Markdown:
{
  "songTitle": "Tên bài hát đầy đủ và viết hoa chữ cái đầu phù hợp",
  "artistName": "Tên ca sĩ hoặc nghệ sĩ biểu diễn nổi tiếng nhất liên quan",
  "mood": "Chọn sắc thái phù hợp: COZY_CHILL hoặc CYBERPUNK_NIGHT hoặc FOCUS_LOFI"
}
`;
    const result = await generateContentWithFallback(prompt, { temperature: 0.1, responseMimeType: 'application/json' });
    const raw = result.text;
    if (!raw) throw new Error('Không nhận được kết quả gợi ý nhạc từ AI.');
    const parsed = cleanAndParseJson(raw);
    return {
      songTitle: parsed.songTitle || songTitle,
      artistName: parsed.artistName || 'Nghệ sĩ Việt',
      mood: parsed.mood || 'COZY_CHILL',
    };
  } catch (error: any) {
    console.error(`[Gemini Error] resolveConcreteMusicIdea failed: ${error.message}`);
    throw new Error(`Không thể tự chọn bài hát cụ thể bằng Gemini: ${error.message}. Vui lòng nhập rõ theo mẫu /music_video Tên bài | Ca sĩ.`);
  }
}

async function findWaitingMusicAudioJob(chatId: number) {
  return prisma.videoPipelineJobs.findFirst({
    where: {
      pipeline_state: MUSIC_AUDIO_WAITING_STATE,
      campaign: { telegram_chat_id: BigInt(chatId) },
    },
    include: { campaign: true },
    orderBy: { updated_at: 'desc' },
  });
}

async function findLatestCancellableJobForChat(chatId: number) {
  return prisma.videoPipelineJobs.findFirst({
    where: {
      pipeline_state: { in: CANCELLABLE_PIPELINE_STATES },
      campaign: { telegram_chat_id: BigInt(chatId) },
    },
    include: { campaign: true },
    orderBy: { updated_at: 'desc' },
  });
}

function extractTelegramAudioPayload(message: any) {
  if (message?.audio) {
    return {
      fileId: message.audio.file_id,
      fileName: message.audio.file_name || `${message.audio.file_unique_id || message.audio.file_id}.mp3`,
      mimeType: message.audio.mime_type || 'audio/mpeg',
    };
  }
  if (message?.document) {
    return {
      fileId: message.document.file_id,
      fileName: message.document.file_name || `${message.document.file_unique_id || message.document.file_id}`,
      mimeType: message.document.mime_type || '',
    };
  }
  return null;
}

function extractTelegramImagePayload(message: any) {
  if (message?.photo?.length) {
    const photo = [...message.photo].sort((a: any, b: any) => (b.file_size || 0) - (a.file_size || 0))[0];
    return {
      fileId: photo.file_id,
      fileName: `${photo.file_unique_id || photo.file_id}.jpg`,
      mimeType: 'image/jpeg',
    };
  }
  if (message?.document) {
    const mimeType = message.document.mime_type || '';
    const fileName = message.document.file_name || `${message.document.file_unique_id || message.document.file_id}`;
    const ext = path.extname(fileName).toLowerCase();
    if (mimeType.startsWith('image/') || ACCEPTED_MUSIC_IMAGE_EXTENSIONS.has(ext)) {
      return {
        fileId: message.document.file_id,
        fileName,
        mimeType,
      };
    }
  }
  return null;
}

function normalizeAudioFileName(fileName: string, jobId: number) {
  const ext = path.extname(fileName || '').toLowerCase();
  const safeBase = path.basename(fileName || `audio_${jobId}${ext}`, ext)
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9_-]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 80) || `audio_${jobId}`;
  return `job_${jobId}_${Date.now()}_${safeBase}${ext}`;
}

function normalizeImageFileName(fileName: string, jobId: number) {
  const rawExt = path.extname(fileName || '').toLowerCase();
  const ext = ACCEPTED_MUSIC_IMAGE_EXTENSIONS.has(rawExt) ? rawExt : '.jpg';
  const safeBase = path.basename(fileName || `portrait_${jobId}${ext}`, rawExt)
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9_-]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 80) || `portrait_${jobId}`;
  return `job_${jobId}_${Date.now()}_${safeBase}${ext}`;
}

async function downloadTelegramFile(ctx: any, fileId: string, outputPath: string) {
  const link = await ctx.telegram.getFileLink(fileId);
  const response = await fetch(link.href);
  if (!response.ok) throw new Error(`Không tải được file Telegram (${response.status}).`);
  const arrayBuffer = await response.arrayBuffer();
  await fs.promises.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.promises.writeFile(outputPath, Buffer.from(arrayBuffer));
}

async function handleWaitingMusicImageUpload(ctx: any, job: any) {
  const payload = extractTelegramImagePayload(ctx.message);
  if (!payload) return false;

  const ext = path.extname(payload.fileName || '').toLowerCase();
  if (!ACCEPTED_MUSIC_IMAGE_EXTENSIONS.has(ext)) {
    await ctx.reply('File ảnh chưa hợp lệ. Hệ thống chỉ nhận .jpg, .jpeg, .png hoặc .webp.');
    return true;
  }

  const metadata = parseMetadata(job.scenes_layout_json);
  const outputPath = path.join(MUSIC_UPLOAD_DIR, normalizeImageFileName(payload.fileName, job.id));
  await ctx.replyWithHTML(
    `🖼️ <b>Đã nhận ảnh visual</b>\n` +
    `━━━━━━━━━━━━━━━━━━━━━\n` +
    `▪️ Job #${job.id}: <b>${escapeHtml(job.video_title_idea || 'Video âm nhạc')}</b>\n` +
    `▪️ Ảnh này sẽ được dùng cho style <code>portrait_lyric</code>.\n\n` +
    `Bây giờ bạn gửi tiếp file nhạc <code>.mp3</code>, <code>.wav</code> hoặc <code>.m4a</code>.`,
  );

  await downloadTelegramFile(ctx, payload.fileId, outputPath);
  metadata.visual_mode = 'portrait_lyric';
  metadata.user_wants_custom_image = true;
  metadata.user_provided_visual_asset = true;
  metadata.user_portrait_path = outputPath;
  metadata.visual_assets = {
    ...(metadata.visual_assets || {}),
    portrait_image_path: outputPath,
  };

  await prisma.videoPipelineJobs.update({
    where: { id: job.id },
    data: {
      scenes_layout_json: JSON.stringify(metadata),
      error_log_trace: null,
    },
  });
  await auditBotAction(job.id, 'YOUTUBE_BOT_MUSIC_IMAGE_UPLOAD', 'SUCCESS', `Received user portrait image for music video Job #${job.id}.`);
  return true;
}

async function handleWaitingMusicAttachmentUpload(ctx: any) {
  const chatId = ctx.chat?.id;
  if (!chatId) return false;

  const waitingJob = await findWaitingMusicAudioJob(chatId);
  if (!waitingJob) return false;
  const resolvedWaiting = await ensureConcreteMusicIdeaForJob(waitingJob);
  const job = resolvedWaiting.job;

  const imageHandled = await handleWaitingMusicImageUpload(ctx, job);
  if (imageHandled) return true;

  const payload = extractTelegramAudioPayload(ctx.message);
  if (!payload) {
    await ctx.replyWithHTML(
      `Vui lòng gửi file nhạc dạng <code>.mp3</code>, <code>.wav</code> hoặc <code>.m4a</code> cho:\n` +
      `<b>${escapeHtml(job.video_title_idea || 'Video âm nhạc')}</b>\n\n` +
      `Nếu muốn tự cung cấp ảnh visual, bạn có thể gửi thêm ảnh <code>.jpg</code>, <code>.png</code> hoặc <code>.webp</code> trước khi gửi nhạc.`,
    );
    return true;
  }

  const ext = path.extname(payload.fileName || '').toLowerCase();
  if (!ACCEPTED_MUSIC_AUDIO_EXTENSIONS.has(ext)) {
    await ctx.reply('File chưa hợp lệ. Hệ thống chỉ nhận nhạc .mp3, .wav hoặc .m4a.');
    return true;
  }

  const metadata = parseMetadata(job.scenes_layout_json);
  const outputPath = path.join(MUSIC_UPLOAD_DIR, normalizeAudioFileName(payload.fileName, job.id));
  await ctx.replyWithHTML(
    `✅ <b>Đã nhận file nhạc</b>\n` +
    `━━━━━━━━━━━━━━━━━━━━━\n` +
    `▪️ Job #${job.id}: <b>${escapeHtml(job.video_title_idea || 'Video âm nhạc')}</b>\n` +
    `▪️ Đang lưu file nhạc...`,
  );

  await downloadTelegramFile(ctx, payload.fileId, outputPath);
  metadata.audio_path = outputPath;
  metadata.user_audio_path = outputPath;
  metadata.requires_user_audio = true;
  metadata.render_audio_source = 'provided_audio';
  metadata.visual_mode = metadata.visual_mode || 'auto';
  metadata.user_wants_custom_image = metadata.user_wants_custom_image ?? false;

  await prisma.videoPipelineJobs.update({
    where: { id: job.id },
    data: {
      audio_file_path: outputPath,
      scenes_layout_json: JSON.stringify(metadata),
      error_log_trace: null,
    },
  });
  await auditBotAction(job.id, 'YOUTUBE_BOT_MUSIC_AUDIO_UPLOAD', 'SUCCESS', `Received user audio file for music video Job #${job.id}.`);

  const activeSession = activeCreationSessions.get(chatId);
  if (activeSession) {
    activeSession.jobId = job.id;
    activeSession.subtitle = job.video_title_idea || activeSession.subtitle;
    await refreshActiveOperation(activeSession);
  }

  const keyboard = Markup.inlineKeyboard([
    [
      Markup.button.callback('✂️ Tự Cắt Đoạn Viral (>= 60s)', `yt:music_cut_mode:viral:${job.id}`),
      Markup.button.callback('🎵 Giữ Nguyên Toàn Bộ Bài', `yt:music_cut_mode:full:${job.id}`),
    ]
  ]);

  await ctx.replyWithHTML(
    `👉 <b>HÃY LỰA CHỌN PHƯƠNG THỨC RENDER YOUTUBE:</b>\n` +
    `━━━━━━━━━━━━━━━━━━━━━\n` +
    `1. <b>✂️ Tự Cắt Đoạn Viral (Khuyên dùng):</b> Gemini & Librosa sẽ tự động phân tích và trích xuất đoạn cao trào, hook hay nhất của bài nhạc (ít nhất từ 60 giây trở lên) để làm video ngắn dễ lên xu hướng.\n` +
    `2. <b>🎵 Giữ Nguyên Toàn Bộ Bài:</b> Hệ thống sẽ render toàn bộ độ dài của bài nhạc từ đầu đến cuối làm video âm nhạc hoàn chỉnh.\n\n` +
    `<i>Vui lòng chọn nút tương ứng bên dưới để bắt đầu Render:</i>`,
    keyboard,
  );
  return true;
}

async function handleIncomingDubVideoUpload(ctx: any) {
  const chatId = ctx.chat?.id;
  if (!chatId) return false;

  const session = activeCreationSessions.get(chatId);
  if (!session || session.kind !== 'translate_dub') return false;

  let fileId = '';
  let fileName = 'dub_video.mp4';

  if (ctx.message.video) {
    fileId = ctx.message.video.file_id;
    fileName = ctx.message.video.file_name || `dub_${Date.now()}.mp4`;
  } else if (ctx.message.document) {
    const doc = ctx.message.document;
    const mime = doc.mime_type || '';
    if (mime.includes('video') || (doc.file_name && doc.file_name.match(/\.(mp4|mov|avi|mkv|webm)$/i))) {
      fileId = doc.file_id;
      fileName = doc.file_name;
    }
  }

  if (!fileId) {
    await ctx.reply('Vui lòng gửi file video (dạng .mp4, .mov, .avi,...) hoặc dán đường dẫn YouTube/TikTok.');
    return true;
  }

  await ctx.reply('📥 Đã nhận file video nguồn! Đang tải xuống máy chủ...');

  const uploadsDir = path.resolve(__dirname, '../../../shared/assets/uploads/dub_sources');
  const uniqueName = `job_dub_${Date.now()}_${fileName.replace(/\s+/g, '_')}`;
  const outputPath = path.join(uploadsDir, uniqueName);

  await downloadTelegramFile(ctx, fileId, outputPath);

  session.tempSourceType = 'file';
  session.tempSourcePath = outputPath;
  session.tempFileName = fileName;

  await ctx.reply(
    `📥 Đã tải video thành công!\n` +
    `👉 Vui lòng chọn tỷ lệ kích thước màn hình để lồng tiếng (tránh méo hình, phù hợp YouTube Short):`,
    Markup.inlineKeyboard([
      [
        Markup.button.callback('📺 Giữ nguyên gốc (Original)', 'yt:dub_ratio:original'),
        Markup.button.callback('📱 Dọc 9:16 (Blur Padding)', 'yt:dub_ratio:vertical_blur')
      ],
      [
        Markup.button.callback('❌ Hủy bỏ', 'yt:cancel_active:pending')
      ]
    ])
  );

  return true;
}


async function cancelActiveOperation(ctx: any, session: ActiveCreationSession) {
  if (session.jobId) {
    await cancelPersistedJob(session.jobId, session.chatId);
  } else if (session.campaignId) {
    await prisma.channelsCampaign.update({ where: { id: session.campaignId }, data: { status: 'CANCELLED' } });
  }
  stopActiveOperation(session.chatId);
  await ctx.replyWithHTML(
    `Đã hủy thao tác đang chạy.\n` +
    `${session.jobId ? `Job #${session.jobId} đã được chuyển sang trạng thái FAILED.` : 'Phiên tạo đã được đóng.'}`,
  );
}

async function getSuggestedJobId(): Promise<number | null> {
  const job = await prisma.videoPipelineJobs.findFirst({
    where: {
      OR: [
        { audio_file_path: { not: null } },
        { pipeline_state: { in: ['RENDERED', 'RENDERED_SUBTITLED', 'AUDIO_COMPOSED', 'ASSETS_READY', 'USER_APPROVED', 'PUBLISH_QUEUED', 'PUBLISHING'] } },
      ],
    },
    orderBy: { updated_at: 'desc' },
  });
  return job?.id || null;
}

async function replyCommandGuidance(ctx: any, command: string, reason: string) {
  const jobId = await getSuggestedJobId();
  const jobHint = jobId || 'job_id';
  const guideByCommand: Record<string, string> = {
    render_music: `Thiếu Job ID.\nDùng: /render_music ${jobHint}`,
    remix_music: `Thiếu Job ID.\nDùng: /remix_music ${jobHint}`,
    preview: `Thiếu Job ID.\nDùng: /preview ${jobHint}`,
    logs: `Thiếu Job ID.\nDùng: /logs ${jobHint}`,
    force_post: `Thiếu Job ID.\nDùng: /force_post ${jobHint}`,
    reschedule: `Thiếu Job ID hoặc thời gian.\nDùng: /reschedule ${jobHint} YYYY-MM-DD HH:mm`,
    job_config: `Thiếu Job ID.\nDùng: /job_config ${jobHint}`,
    set_job_config: `Thiếu Job ID hoặc tham số.\nDùng: /set_job_config ${jobHint} key=value`,
    campaign: `Thiếu Campaign ID.\nDùng: /pause_campaign <campaign_id> hoặc /resume_campaign <campaign_id>`,
    approve: `Thiếu Job ID.\nDùng: /approve ${jobHint}`,
  };

  const keyboard = Markup.inlineKeyboard([
    [
      Markup.button.callback('Chờ duyệt', 'yt:pending'),
      Markup.button.callback('Lịch', 'yt:schedule_today'),
    ],
    [
      Markup.button.callback('Trạng thái', 'yt:status'),
      Markup.button.callback('Menu', 'yt:menu_home'),
    ],
  ]);

  await ctx.reply(`Không chạy được lệnh: ${reason}.\n${guideByCommand[command] || 'Dùng /help để xem lệnh.'}`, keyboard);
}

function trendTemplateKeyboard(jobId: number | null) {
  const callback = (presetKey: string) => jobId ? `yt:tpl:${presetKey}:${jobId}` : `yt:create_tpl:${presetKey}`;
  return Markup.inlineKeyboard([
    [
      Markup.button.callback(TREND_PRESETS.trend_bass.label, callback('trend_bass')),
      Markup.button.callback(TREND_PRESETS.deep_house.label, callback('deep_house')),
    ],
    [
      Markup.button.callback(TREND_PRESETS.lofi_chill.label, callback('lofi_chill')),
      Markup.button.callback('Render nguyên bản', callback('render_only')),
    ],
    [
      Markup.button.callback('Video chờ duyệt', 'yt:pending'),
      Markup.button.callback('Trạng thái', 'yt:status'),
    ],
  ]);
}

function postTemplateKeyboard(jobId: number, mode: 'remix' | 'render' = 'remix') {
  return Markup.inlineKeyboard([
    [
      mode === 'render'
        ? Markup.button.callback('Render ngay', `yt:start_render:${jobId}`)
        : Markup.button.callback('Remix ngay', `yt:start_remix:${jobId}`),
      Markup.button.callback('Xem config', `yt:show_config:${jobId}`),
    ],
    [
      Markup.button.callback('Xem Preview', `yt:preview:${jobId}`),
      Markup.button.callback('Cấu hình khác', 'yt:calendar:trend_templates'),
    ],
  ]);
}

async function applyTrendPreset(jobId: number, presetKey: string) {
  const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
  if (!job) throw new Error(`Không tìm thấy job #${jobId}.`);

  const metadata = parseMetadata(job.scenes_layout_json);
  if (presetKey === 'render_only') {
    metadata.render_mode = 'music_reactive';
    metadata.audio_path = metadata.audio_path || job.audio_file_path;
    metadata.song_title = metadata.song_title || job.video_title_idea || `Job #${jobId}`;
    metadata.artist_name = metadata.artist_name || 'AgentYouTube';
    metadata.mood = metadata.mood || metadata.music_mood || 'FOCUS_LOFI';
  } else {
    const preset = TREND_PRESETS[presetKey];
    if (!preset) throw new Error('Cấu hình split-screen không hợp lệ.');
    Object.assign(metadata, preset.updates);
    metadata.render_mode = 'music_remix_reactive';
    metadata.audio_path = metadata.audio_path || job.audio_file_path;
    metadata.source_audio_path = metadata.source_audio_path || metadata.audio_path || job.audio_file_path;
    metadata.song_title = metadata.song_title || job.video_title_idea || `Job #${jobId}`;
    metadata.artist_name = metadata.artist_name || 'AgentYouTube Remix';
  }

  await prisma.videoPipelineJobs.update({
    where: { id: jobId },
    data: { scenes_layout_json: JSON.stringify(metadata) },
  });
  await auditBotAction(jobId, 'YOUTUBE_BOT_TREND_PRESET', 'SUCCESS', `Applied trend preset ${presetKey} to job #${jobId}.`);
  return metadata;
}

async function createVideoFromTrendTemplate(ctx: any, presetKey: string) {
  const connected = await ensureYouTubeConnected(ctx);
  if (!connected) return null;

  const preset = TREND_PRESETS[presetKey] || TREND_PRESETS.trend_bass;
  const scheduled = new Date(Date.now() + 24 * 60 * 60 * 1000);
  const campaign = await prisma.channelsCampaign.create({
    data: {
      telegram_chat_id: BigInt(ctx.chat.id),
      topic: `${preset.label} YouTube video`,
      target_audience: 'Người xem YouTube thích nội dung chill và lofi trend',
      status: 'RUNNING',
    },
  });
  await prisma.$executeRawUnsafe(`UPDATE channels_campaign SET user_id = ${Number(connected.user.id)} WHERE id = ${Number(campaign.id)}`);

  const metadata = {
    ...preset.updates,
    render_mode: 'classic_video',
    desired_next_render_mode: 'music_remix_reactive',
    selected_template: presetKey,
    music_mood: preset.updates.mood,
    content_category: 'music_trend_template',
    primary_goal: 'VIEWS',
    concept_description: preset.description,
    platform: 'youtube',
  };

  const job = await prisma.videoPipelineJobs.create({
    data: {
      campaign_id: campaign.id,
      day_number: 1,
      scheduled_post_time: scheduled,
      video_title_idea: `${preset.label} - video YouTube tự động`,
      scenes_layout_json: JSON.stringify(metadata),
      pipeline_state: 'QUEUED',
    },
  });

  await createOrUpdateYouTubePublishTarget(job.id, scheduled, 'shorts', connected.user.id, connected.connection.id);
  await addJobToQueue(job.id, 'RENDER');
  await auditBotAction(job.id, 'YOUTUBE_BOT_TEMPLATE_CREATE', 'SUCCESS', `Created and queued YouTube video from preset ${presetKey}.`);
  return job;
}

async function generateSmartSuggestions(songTitle: string, artistName: string): Promise<Record<string, string> | null> {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) return null;
  try {
    const prompt = `
Bạn là giám đốc sáng tạo kênh âm nhạc YouTube Studio hàng đầu Việt Nam.
Phân tích bài hát và đề xuất thông số kỹ thuật phù hợp nhất:

BÀI HÁT: "${songTitle}"
NGHỆ SĨ: "${artistName}"

Trả về JSON DUY NHẤT (không markdown):
{
  "mood": "SAD_RAIN | CYBERPUNK_NIGHT | COZY_CHILL | FOCUS_LOFI",
  "remix_style": "trend_bass | deep_house | lofi_chill",
  "bpm": "<số nguyên từ 70 đến 140>",
  "caption": "<câu caption nghệ thuật tiếng Việt dưới 80 ký tự>",
  "visual_keywords": "<3 từ khóa tiếng Anh tìm video nền Pexels>",
  "rationale": "<lý do ngắn gọn 1 câu>"
}
`;
    const result = await generateContentWithFallback(prompt, { temperature: 0.3, responseMimeType: 'application/json' });
    const raw = result.text;
    if (!raw) return null;
    return cleanAndParseJson(raw);
  } catch {
    return null;
  }
}

async function buildJobConfigDisplay(jobId: number, job: any, metadata: any, withSuggestions = true): Promise<string> {
  const renderMode: string = metadata.render_mode || 'classic_video';
  const songTitle: string = metadata.song_title || job.video_title_idea || '';
  const artistName: string = metadata.artist_name || '';
  const isMusicVideo = renderMode === 'music_reactive' || renderMode === 'music_remix_reactive';

  let lines: string[] = [];
  lines.push(`⚙️ THÔNG SỐ CẤU HÌNH TÁC VỤ YOUTUBE (JOB #${jobId})`);
  lines.push(`━━━━━━━━━━━━━━━━━━━━━`);
  lines.push(`▪️ Chế độ Render: \`${renderMode}\``);
  lines.push(`▪️ Trạng thái: \`${job.pipeline_state}\``);

  if (isMusicVideo) {
    lines.push(`▪️ Tên bài hát: *${songTitle || 'Chưa xác định'}*`);
    lines.push(`▪️ Nghệ sĩ: *${artistName || 'Chưa xác định'}*`);
    lines.push(`▪️ Mood hiện tại: \`${metadata.mood || metadata.music_mood || 'Chưa phân tích'}\``);

    if (renderMode === 'music_remix_reactive') {
      lines.push(`▪️ Phong cách Remix: \`${metadata.remix_style || 'trend_bass'}\``);
      lines.push(`▪️ Nhịp điệu (BPM): \`${metadata.bpm || metadata.detected_bpm || 'auto'}\``);
      lines.push(`▪️ Xác nhận bản quyền: \`${metadata.rights_confirmed ? 'ĐÃ XÁC NHẬN' : 'CHƯA XÁC NHẬN'}\``);
    }

    if (metadata.caption) {
      lines.push(`▪️ Caption: _${metadata.caption}_`);
    }
    if (metadata.visual_keywords) {
      lines.push(`▪️ Từ khóa visual: \`${metadata.visual_keywords}\``);
    }
    if (metadata.audio_path) {
      const audioFile = metadata.audio_path.split('\\').pop() || metadata.audio_path;
      lines.push(`▪️ File âm thanh: \`${audioFile}\``);
    }
  } else {
    lines.push(`▪️ Chủ đề: *${songTitle}*`);
    if (metadata.music_mood) lines.push(`▪️ Mood nhạc nền: \`${metadata.music_mood}\``);
    if (metadata.content_category) lines.push(`▪️ Thể loại nội dung: \`${metadata.content_category}\``);
    if (metadata.primary_goal) lines.push(`▪️ Mục tiêu: \`${metadata.primary_goal}\``);
  }

  if (isMusicVideo && withSuggestions && songTitle) {
    const suggestions = await generateSmartSuggestions(songTitle, artistName);
    if (suggestions) {
      lines.push(``);
      lines.push(`🤖 *GỢI Ý THÔNG SỐ TỐI ƯU TỪ AI (${songTitle}):*`);
      lines.push(`▪️ Mood phù hợp nhất: \`${suggestions.mood}\``);
      if (renderMode === 'music_remix_reactive') {
        lines.push(`▪️ Remix style tối ưu: \`${suggestions.remix_style}\``);
        lines.push(`▪️ BPM đề xuất: \`${suggestions.bpm}\``);
      }
      if (suggestions.visual_keywords) lines.push(`▪️ Visual keywords: \`${suggestions.visual_keywords}\``);
      if (suggestions.caption) lines.push(`▪️ Caption đề xuất: _${suggestions.caption}_`);
      if (suggestions.rationale) lines.push(`▪️ Phân tích: _${suggestions.rationale}_`);

      const configStr = renderMode === 'music_remix_reactive'
        ? `mood=${suggestions.mood}; remix_style=${suggestions.remix_style}; bpm=${suggestions.bpm}`
        : `mood=${suggestions.mood}`;
      lines.push(``);
      lines.push(`📌 *Áp dụng ngay:*`);
      lines.push(`\`/set_job_config ${jobId} ${configStr}\``);
    }
  } else if (isMusicVideo) {
    lines.push(``);
    lines.push(`📌 *Cập nhật thông số:*`);
    const configHint = renderMode === 'music_remix_reactive'
      ? `mood=SAD_RAIN; remix_style=deep_house; bpm=95`
      : `mood=SAD_RAIN`;
    lines.push(`\`/set_job_config ${jobId} ${configHint}\``);
  } else {
    lines.push(``);
    lines.push(`📌 *Cập nhật thông số:*`);
    lines.push(`\`/set_job_config ${jobId} mood=COZY_CHILL; remix_style=lofi_chill\``);
  }

  return lines.join('\n');
}

function parseConfigUpdates(text: string) {
  const updates: Record<string, any> = {};
  for (const part of text.split(';')) {
    const trimmed = part.trim();
    if (!trimmed) continue;
    const eqIndex = trimmed.indexOf('=');
    if (eqIndex <= 0) continue;
    const key = trimmed.slice(0, eqIndex).trim();
    let value: any = trimmed.slice(eqIndex + 1).trim();
    if (!JOB_CONFIG_KEYS.has(key)) continue;
    if (key === 'bpm') {
      const parsed = Number(value);
      if (!Number.isFinite(parsed) || parsed < 60 || parsed > 180) continue;
      value = parsed;
    }
    if (key === 'rights_confirmed') {
      value = ['true', '1', 'yes', 'co', 'có'].includes(String(value).toLowerCase());
    }
    updates[key] = value;
  }
  return updates;
}

function getCalendarMenuKeyboard() {
  const todayStr = new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Ho_Chi_Minh' });
  const tomorrow = new Date(Date.now() + 24 * 60 * 60 * 1000);
  const tomorrowStr = tomorrow.toLocaleDateString('sv-SE', { timeZone: 'Asia/Ho_Chi_Minh' });

  return Markup.inlineKeyboard([
    [
      Markup.button.callback(`📅 Hôm Nay (${todayStr.split('-').reverse().slice(0, 2).join('/')})`, `yt:calendar:date:${todayStr}`),
      Markup.button.callback(`📅 Ngày Mai (${tomorrowStr.split('-').reverse().slice(0, 2).join('/')})`, `yt:calendar:date:${tomorrowStr}`)
    ],
    [
      Markup.button.callback('📅 Xem Lịch 7 Ngày Tới', 'yt:calendar:view_7days'),
      Markup.button.callback('🔍 Nhập Ngày Khác', 'yt:calendar:custom_input')
    ],
    [
      Markup.button.callback('🎮 Về Bảng Điều Khiển', 'yt:menu_home')
    ]
  ]);
}

async function renderCalendarDateView(ctx: any, dateStr: string) {
  try {
    const startOfDay = new Date(dateStr + 'T00:00:00+07:00');
    const endOfDay = new Date(dateStr + 'T23:59:59+07:00');

    const jobs = await prisma.videoPipelineJobs.findMany({
      where: {
        scheduled_post_time: {
          gte: startOfDay,
          lte: endOfDay
        },
        scenes_layout_json: {
          contains: '"platform":"youtube"'
        }
      },
      orderBy: { scheduled_post_time: 'asc' }
    });

    const formattedDate = dateStr.split('-').reverse().join('/');

    if (jobs.length > 0) {
      let msg = `📅 <b>LỊCH TRÌNH YOUTUBE NGÀY ${formattedDate}</b>\n`;
      msg += `━━━━━━━━━━━━━━━━━━━━━\n`;
      msg += `Hiện tại đang có <b>${jobs.length} video</b> YouTube được lên lịch đăng:\n\n`;

      const buttons = [];
      for (const job of jobs) {
        const timeStr = new Date(job.scheduled_post_time).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Ho_Chi_Minh' });
        msg += `▪️ <b>Job #${job.id}</b> - Lịch đăng: <b>${timeStr}</b>\n`;
        msg += `   - Tiêu đề: <i>${escapeHtml(job.video_title_idea || '')}</i>\n`;
        msg += `   - Trạng thái: <code>${job.pipeline_state}</code>\n\n`;

        buttons.push([
          Markup.button.callback(`✏️ Sửa Job #${job.id}`, `yt:cal_edit:${job.id}`),
          Markup.button.callback(`❌ Xóa Job #${job.id}`, `yt:cal_delete:${job.id}`)
        ]);
        if (job.pipeline_state === 'RENDERED' || job.video_output_path) {
          buttons.push([
            Markup.button.callback(`🔍 Xem trước Job #${job.id}`, `yt:preview:${job.id}`)
          ]);
        }
      }

      buttons.push([
        Markup.button.callback('➕ Lên lịch video mới', `yt:cal_create:${dateStr}`),
      ]);
      buttons.push([
        Markup.button.callback('⬅️ Về Lịch Trình', 'yt:calendar:menu'),
        Markup.button.callback('🎮 Bảng Điều Khiển', 'yt:menu_home')
      ]);

      await ctx.replyWithHTML(msg, Markup.inlineKeyboard(buttons));
    } else {
      const msg =
        `📅 <b>LỊCH TRÌNH YOUTUBE NGÀY ${formattedDate}</b>\n` +
        `━━━━━━━━━━━━━━━━━━━━━\n` +
        `❌ Hiện tại chưa có video nào được lên lịch cho ngày này.\n\n` +
        `Bạn có muốn lên lịch tạo một video mới không?`;

      const keyboard = Markup.inlineKeyboard([
        [Markup.button.callback('➕ Lên lịch video mới', `yt:cal_create:${dateStr}`)],
        [
          Markup.button.callback('⬅️ Về Lịch Trình', 'yt:calendar:menu'),
          Markup.button.callback('🎮 Bảng Điều Khiển', 'yt:menu_home')
        ]
      ]);

      await ctx.replyWithHTML(msg, keyboard);
    }
  } catch (error: any) {
    console.error(`Error rendering calendar date view for ${dateStr}:`, error);
    await ctx.reply(`❌ Lỗi khi truy vấn lịch trình ngày ${dateStr}: ${error.message}`);
  }
}

async function enqueueMusicReactiveRender(ctx: any, jobId: number) {
  const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
  if (!job) {
    return ctx.reply(`❌ LỖI HỆ THỐNG: Không tìm thấy tác vụ Job #${jobId} trong cơ sở dữ liệu.`);
  }
  const chatId = ctx.chat?.id;
  const activeSession = chatId && !activeCreationSessions.has(chatId)
    ? await beginActiveOperation(ctx, {
      chatId,
      kind: 'render_music',
      title: 'Đang tạo video âm nhạc',
      subtitle: job.video_title_idea || `Job #${jobId}`,
      jobId,
      campaignId: job.campaign_id || undefined,
    })
    : (chatId ? activeCreationSessions.get(chatId) : undefined);

  let metadata: Record<string, any> = {};
  try {
    metadata = job.scenes_layout_json && typeof job.scenes_layout_json === 'string'
      ? JSON.parse(job.scenes_layout_json)
      : (job.scenes_layout_json as any) || {};
    if (Array.isArray(metadata)) metadata = {};
  } catch {
    metadata = {};
  }

  const isStandalone = metadata.is_standalone_music_video === true || 
    (metadata.render_mode === 'music_reactive' && !job.audio_file_path);

  if (!isStandalone) {
    if (!job.audio_file_path || !fs.existsSync(job.audio_file_path)) {
      if (chatId) stopActiveOperation(chatId);
      return ctx.reply(
        `⚠️ CẢNH BÁO TÀI NGUYÊN: Tác vụ Job #${jobId} chưa có tệp âm thanh hợp lệ (audio_file_path). Thực hiện kết xuất (Render) bản chuẩn trước để tạo tệp âm thanh, hoặc cấu hình bổ sung audio_path trong metadata.`,
      );
    }
  }

  metadata.render_mode = 'music_reactive';
  if (!isStandalone) {
    metadata.audio_path = job.audio_file_path;
  }
  metadata.song_title = metadata.song_title || job.video_title_idea || `Job #${jobId}`;
  metadata.artist_name = metadata.artist_name || 'AgentYouTube';
  metadata.mood = metadata.mood || 'FOCUS_LOFI';
  metadata.require_youtube_music = metadata.require_youtube_music ?? true;
  metadata.youtube_sound_volume_percent = metadata.youtube_sound_volume_percent ?? 2;
  metadata.original_video_volume_percent = metadata.original_video_volume_percent ?? 100;
  metadata.youtube_music_strategy = metadata.youtube_music_strategy || 'add_exact_sound_at_publish';

  if (isStandalone && !metadata.audio_path && !job.audio_file_path) {
    metadata.requires_user_audio = true;
    metadata.auto_select_viral_segment = true;
    await prisma.videoPipelineJobs.update({
      where: { id: jobId },
      data: {
        scenes_layout_json: JSON.stringify(metadata),
        pipeline_state: MUSIC_AUDIO_WAITING_STATE,
      },
    });
    await auditBotAction(jobId, 'YOUTUBE_BOT_RENDER_MUSIC_WAIT_AUDIO', 'INFO', `Music reactive Job #${jobId} is waiting for user audio file.`);
    if (activeSession) {
      activeSession.jobId = jobId;
      await refreshActiveOperation(activeSession);
    }
    await ctx.replyWithHTML(
      `🎵 <b>Job #${jobId} đang chờ file nhạc thật</b>\n` +
      `Vui lòng gửi file <code>.mp3</code>, <code>.wav</code> hoặc <code>.m4a</code>. Sau đó hệ thống sẽ tự render.`,
    );
    return;
  }

  await prisma.videoPipelineJobs.update({
    where: { id: jobId },
    data: {
      scenes_layout_json: JSON.stringify(metadata),
      pipeline_state: 'QUEUED',
    },
  });
  await addJobToQueue(jobId, 'RENDER');
  await auditBotAction(jobId, 'YOUTUBE_BOT_RENDER_MUSIC', 'INFO', `Queued music_reactive render for job #${jobId}.`);
  if (activeSession) {
    activeSession.jobId = jobId;
    await refreshActiveOperation(activeSession);
  }
  return;
}

async function handleCreateMusicVideoLogic(ctx: any, songTitle: string, artistName: string, targetDateStr: string = 'today') {
  const connected = await ensureYouTubeConnected(ctx);
  if (!connected) return;

  const resolvedIdea = await resolveConcreteMusicIdea(songTitle, artistName);
  songTitle = resolvedIdea.songTitle;
  artistName = resolvedIdea.artistName;

  let scheduledTime = parseScheduleTime(targetDateStr) || new Date();
  if (targetDateStr === 'tomorrow') {
    scheduledTime = new Date(Date.now() + 24 * 60 * 60 * 1000);
  } else if (targetDateStr && targetDateStr !== 'today' && /^\d{4}-\d{2}-\d{2}$/.test(targetDateStr)) {
    scheduledTime = new Date(targetDateStr + 'T12:00:00+07:00');
  }

  const activeSession = await beginActiveOperation(ctx, {
    chatId: ctx.chat.id,
    kind: 'music_video',
    title: 'Đang tạo video âm nhạc',
    subtitle: `${songTitle} - ${artistName} | Đặt lịch: ${formatDateTime(scheduledTime)}`,
  });

  try {
    const campaign = await prisma.channelsCampaign.create({
      data: {
        telegram_chat_id: BigInt(ctx.chat.id),
        topic: songTitle === 'HOT TRENDING' ? 'Chiến dịch Video Âm Nhạc Xu Hướng' : `Video Âm Nhạc: ${songTitle} - ${artistName}`,
        target_audience: 'Người nghe nhạc',
        status: 'RUNNING',
      },
    });
    await prisma.$executeRawUnsafe(`UPDATE channels_campaign SET user_id = ${Number(connected.user.id)} WHERE id = ${Number(campaign.id)}`);

    const metadata = {
      render_mode: 'music_reactive',
      song_title: songTitle,
      artist_name: artistName,
      is_standalone_music_video: true,
      requires_user_audio: true,
      auto_select_viral_segment: true,
      require_youtube_music: true,
      youtube_sound_volume_percent: 2,
      original_video_volume_percent: 100,
      youtube_music_strategy: 'add_exact_sound_at_publish',
      mood: resolvedIdea.mood,
      platform: 'youtube',
    };

    const job = await prisma.videoPipelineJobs.create({
      data: {
        campaign_id: campaign.id,
        day_number: 1,
        scheduled_post_time: scheduledTime,
        video_title_idea: songTitle === 'HOT TRENDING' ? 'Video Âm Nhạc Xu Hướng' : `${songTitle} - ${artistName}`,
        scenes_layout_json: JSON.stringify(metadata),
        pipeline_state: MUSIC_AUDIO_WAITING_STATE,
      },
    });

    await createOrUpdateYouTubePublishTarget(job.id, scheduledTime, 'shorts', connected.user.id, connected.connection.id);

    activeSession.jobId = job.id;
    activeSession.campaignId = campaign.id;
    activeSession.subtitle = `${job.video_title_idea} | Lịch đăng: ${formatDateTime(scheduledTime)}`;
    await refreshActiveOperation(activeSession);

    await auditBotAction(job.id, 'YOUTUBE_BOT_MUSIC_VIDEO', 'INFO', `Khởi tạo video âm nhạc Job #${job.id}, lên lịch ${formatDateTime(scheduledTime)}, đang chờ người dùng gửi file audio.`);
    await refreshActiveOperation(activeSession);

    await ctx.replyWithHTML(
      `🎵 <b>ĐÃ TẠO Ý TƯỞNG VIDEO ÂM NHẠC YOUTUBE</b>\n` +
      `━━━━━━━━━━━━━━━━━━━━━\n` +
      `▪️ Job #${job.id}: <b>${escapeHtml(job.video_title_idea || 'Video âm nhạc')}</b>\n` +
      `▪️ Lịch đăng: <b>${escapeHtml(formatDateTime(scheduledTime))}</b>\n` +
      `▪️ Bạn có thể gửi ảnh visual trước nếu muốn, hoặc để hệ thống tự lấy.\n` +
      `▪️ Sau đó gửi file nhạc <code>.mp3</code>, <code>.wav</code> hoặc <code>.m4a</code> vào chat này.\n\n` +
      `Sau khi nhận file nhạc, hệ thống sẽ tự chọn khúc viral, cắt đoạn hay và render lyric đồng bộ theo nhạc.`,
      Markup.inlineKeyboard([
        [
          Markup.button.callback('🖼️ Tôi sẽ gửi ảnh', `yt:music_visual:custom:${job.id}`),
          Markup.button.callback('✨ Tự lấy ảnh', `yt:music_visual:auto:${job.id}`),
        ],
        [
          Markup.button.callback('🌸 Lofi Anime Loop', `yt:music_visual:lofi_anime:${job.id}`),
        ]
      ]),
    );

  } catch (error: any) {
    console.error('Error starting YouTube music video campaign:', error);
    stopActiveOperation(ctx.chat.id);
    ctx.reply(`❌ Không thể khởi tạo video âm nhạc độc lập: ${error.message}`);
  }
}

async function prepareCampaignConfirmation(ctx: any, action: 'pause_campaign' | 'resume_campaign') {
  try {
    const commandLength = action === 'pause_campaign' ? 15 : 16;
    const text = ctx.message.text.substring(commandLength).trim();
    const campaignId = parseInt(text, 10);

    if (isNaN(campaignId)) {
      return replyCommandGuidance(ctx, 'campaign', 'mã chiến dịch trống');
    }

    const campaign = await prisma.channelsCampaign.findUnique({ where: { id: campaignId } });
    if (!campaign) {
      return ctx.reply(`❌ LỖI: Không tìm thấy chiến dịch Campaign #${campaignId} trong cơ sở dữ liệu.`);
    }

    const confirmation = createConfirmation(
      ctx.chat.id,
      action,
      `${action === 'pause_campaign' ? 'Tạm dừng hoạt động' : 'Kích hoạt lại'} chiến dịch Campaign #${campaignId}.`,
      { campaignId },
    );

    await ctx.reply(
      `❓ XÁC NHẬN YÊU CẦU THỰC THI HÀNH ĐỘNG HỆ THỐNG:\n\n${confirmation.summary}`,
      Markup.inlineKeyboard([
        Markup.button.callback('✅ Xác nhận', `yt:confirm:${confirmation.id}`),
        Markup.button.callback('❌ Hủy bỏ', `yt:deny:${confirmation.id}`),
      ]),
    );
  } catch (error: any) {
    console.error('Error preparing campaign confirmation:', error);
    ctx.reply(`❌ Không thể chuẩn bị thao tác campaign: ${error.message}`);
  }
}

async function ensureConcreteMusicIdeaForJob(job: any) {
  const metadata = parseMetadata(job.scenes_layout_json);
  if (!isAutoMusicValue(metadata.song_title || job.video_title_idea) && !isAutoMusicValue(metadata.artist_name)) {
    return { job, metadata };
  }

  const resolved = await resolveConcreteMusicIdea(metadata.song_title || job.video_title_idea || 'HOT TRENDING', metadata.artist_name || 'AUTO DETECT');
  metadata.song_title = resolved.songTitle;
  metadata.artist_name = resolved.artistName;
  metadata.mood = metadata.mood || resolved.mood;
  const title = `${resolved.songTitle} - ${resolved.artistName}`;
  const updated = await prisma.videoPipelineJobs.update({
    where: { id: job.id },
    data: {
      video_title_idea: title,
      scenes_layout_json: JSON.stringify(metadata),
    },
    include: { campaign: true },
  });
  return { job: updated, metadata };
}

function parseMetadata(raw: any): Record<string, any> {
  try {
    const parsed = raw && typeof raw === 'string' ? JSON.parse(raw) : raw || {};
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function resolveProgressPercent(state?: string, latestStep?: string, loggedAt?: Date | null) {
  const key = `${state || ''} ${latestStep || ''}`.toUpperCase();
  if (key.includes('FAILED') || key.includes('QUALITY_FAILED')) return 100;
  if (key.includes('PUBLISHED') || key.includes('RENDERED_SUBTITLED') || key.includes('RENDER_SUCCESS')) return 100;
  if (key.includes(MUSIC_AUDIO_WAITING_STATE)) return 18;

  let basePercent = 6;
  let maxPercent = 11;
  let estimatedDuration = 10; // seconds to smoothly creep to maxPercent

  if (key.includes('QUALITY_CHECK')) {
    basePercent = 90;
    maxPercent = 99;
    estimatedDuration = 15;
  } else if (key.includes('STREAM_RENDERING') || key.includes('VIDEO_RENDER')) {
    basePercent = 76;
    maxPercent = 89;
    estimatedDuration = 45;
  } else if (key.includes('WEB_DOM_BUILD') || key.includes('ASSETS_READY')) {
    basePercent = 62;
    maxPercent = 75;
    estimatedDuration = 20;
  } else if (key.includes('SIGNAL_PROCESSING') || key.includes('AUDIO_COMPOSED')) {
    basePercent = 45;
    maxPercent = 61;
    estimatedDuration = 30;
  } else if (key.includes('AI_CREATIVE') || key.includes('AI_PARSED') || key.includes('LLM_SCRIPT')) {
    basePercent = 32;
    maxPercent = 44;
    estimatedDuration = 30;
  } else if (key.includes('AI_PROCESSING')) {
    basePercent = 22;
    maxPercent = 31;
    estimatedDuration = 15;
  } else if (key.includes('QUEUED') || key.includes('START')) {
    basePercent = 12;
    maxPercent = 21;
    estimatedDuration = 15;
  }

  if (loggedAt) {
    const elapsedSeconds = Math.max(0, (Date.now() - new Date(loggedAt).getTime()) / 1000);
    const ratio = Math.min(1, elapsedSeconds / estimatedDuration);
    const creep = Math.round(ratio * (maxPercent - basePercent));
    return basePercent + creep;
  }

  return basePercent;
}

function progressBar(percent: number) {
  const total = 12;
  const filled = Math.max(1, Math.min(total, Math.round((percent / 100) * total)));
  return `${'█'.repeat(filled)}${'░'.repeat(total - filled)} ${percent}%`;
}

function operationStatusLabel(state?: string, latestStep?: string) {
  const key = `${state || ''} ${latestStep || ''}`.toUpperCase();
  if (key.includes('FAILED') || key.includes('QUALITY_FAILED')) return 'Đã dừng hoặc có lỗi';
  if (key.includes('PUBLISHED')) return 'Đã đăng thành công';
  if (key.includes('RENDERED_SUBTITLED') || key.includes('RENDER_SUCCESS')) return 'Đã tạo xong, sẵn sàng kiểm duyệt';
  if (key.includes(MUSIC_AUDIO_WAITING_STATE)) return 'Đang chờ bạn gửi file nhạc';
  if (key.includes('QUALITY_CHECK')) return 'Đang kiểm tra chất lượng';
  if (key.includes('STREAM_RENDERING') || key.includes('VIDEO_RENDER')) return 'Đang kết xuất video';
  if (key.includes('WEB_DOM_BUILD')) return 'Đang dựng khung hình chuyển động';
  if (key.includes('SIGNAL_PROCESSING') || key.includes('AUDIO_COMPOSED')) return 'Đang xử lý âm thanh';
  if (key.includes('AI_CREATIVE') || key.includes('AI_PARSED') || key.includes('LLM_SCRIPT')) return 'Đang viết kịch bản và phân tích nội dung';
  if (key.includes('AI_PROCESSING')) return 'Đang chuẩn bị AI';
  if (key.includes('QUEUED') || key.includes('START')) return 'Đang xếp vào hàng xử lý';
  return 'Đang chuẩn bị phiên làm việc';
}

async function buildActiveOperationCard(session: ActiveCreationSession) {
  let state = 'INITIALIZING';
  let latestStep = 'BOT_LOCKED';
  let latestMessage = 'Chat đang tạm khóa để hệ thống tập trung xử lý tác vụ này.';
  let jobTitle = session.subtitle;
  let latestLoggedAt: Date | null = null;

  if (session.jobId) {
    const job = await prisma.videoPipelineJobs.findUnique({ where: { id: session.jobId } });
    if (job) {
      let displayJob = job;
      if (job.pipeline_state === MUSIC_AUDIO_WAITING_STATE) {
        const resolved = await ensureConcreteMusicIdeaForJob(job);
        displayJob = resolved.job;
      }
      state = displayJob.pipeline_state;
      jobTitle = displayJob.video_title_idea || jobTitle;
      if (state === MUSIC_AUDIO_WAITING_STATE) {
        latestMessage = 'Hãy gửi file nhạc .mp3, .wav hoặc .m4a vào chat này để bắt đầu render.';
      }
    }
    const log = await prisma.processRealtimeLogs.findFirst({
      where: { job_id: session.jobId },
      orderBy: { logged_at: 'desc' },
    });
    if (log) {
      latestStep = log.execution_step;
      latestMessage = log.log_message;
      latestLoggedAt = log.logged_at;
    }
  }

  const percent = resolveProgressPercent(state, latestStep, latestLoggedAt);
  const elapsedSeconds = Math.max(1, Math.round((Date.now() - session.startedAt) / 1000));
  const status = operationStatusLabel(state, latestStep);
  const waitingForMusic = state === MUSIC_AUDIO_WAITING_STATE;

  return (
    `╭────────────────────╮\n` +
    `  <b>${escapeHtml(session.title)}</b>\n` +
    `╰────────────────────╯\n` +
    `\n` +
    `<b>Trạng thái</b>: ${escapeHtml(status)}\n` +
    `<b>Tiến trình</b>: <code>${progressBar(percent)}</code>\n` +
    `<b>Tác vụ</b>: ${session.jobId ? `Job #${session.jobId}` : 'Đang chuẩn bị'}\n` +
    `<b>Nội dung</b>: ${escapeHtml(jobTitle)}\n` +
    `<b>Thời gian</b>: ${elapsedSeconds}s\n` +
    `\n` +
    `<i>${escapeHtml(latestMessage).slice(0, 420)}</i>\n` +
    `\n` +
    (waitingForMusic
      ? `<b>Chat đang chờ file nhạc.</b> Bạn có thể gửi audio hoặc hủy thao tác.`
      : `<b>Chat đang tạm khóa.</b> Nếu muốn dừng, chỉ dùng nút bên dưới.`)
  );
}

async function refreshActiveOperation(session: ActiveCreationSession) {
  if (!session.messageId) return;
  const text = await buildActiveOperationCard(session);
  
  if (session.lastText === text) {
    return;
  }

  const job = session.jobId ? await prisma.videoPipelineJobs.findUnique({ where: { id: session.jobId } }) : null;
  const log = session.jobId ? await prisma.processRealtimeLogs.findFirst({ where: { job_id: session.jobId }, orderBy: { logged_at: 'desc' } }) : null;
  const percent = resolveProgressPercent(job?.pipeline_state, log?.execution_step, log?.logged_at);

  const isTerminal = percent >= 100;

  const now = Date.now();
  const timeSinceLastEdit = now - (session.lastEditTime || 0);
  if (!isTerminal && timeSinceLastEdit < 3000) {
    return;
  }

  try {
    await youtubeBot.telegram.editMessageText(
      session.chatId,
      session.messageId,
      undefined,
      text,
      {
        parse_mode: 'HTML',
        ...(isTerminal ? {} : cancelOnlyKeyboard(session)),
      },
    );
    session.lastText = text;
    session.lastEditTime = now;
  } catch (error: any) {
    const message = String(error?.message || '');
    if (message.includes('message is not modified')) {
      session.lastText = text;
    } else if (message.includes('429') || error?.code === 429) {
      console.warn(`[YouTube Bot] Rate limited (429) on chat ${session.chatId}. Backing off update timer...`);
      if (session.timer) {
        clearInterval(session.timer);
        session.timer = setInterval(() => refreshActiveOperation(session).catch(console.error), 8000);
      }
    } else {
      console.warn('[YouTube Bot] Failed to refresh progress card:', message);
    }
  }

  if (isTerminal) {
    stopActiveOperation(session.chatId);
  }
}

async function beginActiveOperation(ctx: any, session: Omit<ActiveCreationSession, 'startedAt'>) {
  const activeSession: ActiveCreationSession = {
    ...session,
    startedAt: Date.now(),
  };
  activeCreationSessions.set(activeSession.chatId, activeSession);
  const sent = await ctx.replyWithHTML(await buildActiveOperationCard(activeSession), cancelOnlyKeyboard(activeSession));
  activeSession.messageId = sent.message_id;
  activeSession.timer = setInterval(() => refreshActiveOperation(activeSession).catch(console.error), 4000);
  return activeSession;
}

function stopActiveOperation(chatId: number) {
  const session = activeCreationSessions.get(chatId);
  if (session?.timer) clearInterval(session.timer);
  activeCreationSessions.delete(chatId);
}

async function removeQueuedBullJobs(jobId: number) {
  for (const type of ['PLANNING', 'RENDER', 'PUBLISH']) {
    const baseJob = await tiktokQueue.getJob(`${type}_${jobId}`);
    if (baseJob) {
      try {
        await baseJob.remove();
      } catch {}
    }
    if (type === 'PUBLISH') {
      const platformJob = await tiktokQueue.getJob(`PUBLISH_${jobId}_youtube`);
      if (platformJob) {
        try {
          await platformJob.remove();
        } catch {}
      }
    }
  }
}

async function cancelPersistedJob(jobId: number, chatId?: number) {
  const job = await prisma.videoPipelineJobs.findUnique({
    where: { id: jobId },
    include: { campaign: true },
  });
  if (!job) {
    return { ok: false, reason: `Không tìm thấy Job #${jobId}.` };
  }

  if (
    chatId &&
    job.campaign?.telegram_chat_id &&
    String(job.campaign.telegram_chat_id) !== String(chatId)
  ) {
    return { ok: false, reason: `Job #${jobId} không thuộc chat hiện tại.` };
  }

  if (['FAILED', 'RENDERED', 'RENDERED_SUBTITLED', 'PUBLISHED', 'COMPLETED', 'CANCELLED'].includes(job.pipeline_state)) {
    return { ok: false, reason: `Job #${jobId} đã ở trạng thái ${job.pipeline_state}, không cần hủy thêm.` };
  }

  await removeQueuedBullJobs(jobId);
  await prisma.videoPipelineJobs.update({
    where: { id: jobId },
    data: {
      pipeline_state: 'FAILED',
      error_log_trace: 'User cancelled this job from Telegram progress view.',
    },
  });
  if (job.campaign_id) {
    await prisma.channelsCampaign.update({
      where: { id: job.campaign_id },
      data: { status: 'CANCELLED' },
    });
  }
  await prisma.$executeRawUnsafe(
    `UPDATE publish_targets SET status = 'CANCELLED' WHERE job_id = ? AND platform = 'youtube' AND status IN ('PENDING_APPROVAL', 'APPROVED', 'PUBLISH_QUEUED')`,
    jobId
  );

  await auditBotAction(jobId, 'YOUTUBE_BOT_CANCEL_ACTIVE', 'SUCCESS', 'User cancelled active creation operation.');
  return { ok: true, reason: `Job #${jobId} đã được chuyển sang trạng thái FAILED.` };
}

async function retryPublishJob(jobId: number, chatId?: number) {
  const job = await prisma.videoPipelineJobs.findUnique({
    where: { id: jobId },
    include: { campaign: true },
  });
  if (!job) {
    return { ok: false, reason: `Không tìm thấy Job #${jobId}.` };
  }
  if (
    chatId &&
    job.campaign?.telegram_chat_id &&
    String(job.campaign.telegram_chat_id) !== String(chatId)
  ) {
    return { ok: false, reason: `Job #${jobId} không thuộc chat hiện tại.` };
  }
  if (!job.video_output_path || !fs.existsSync(job.video_output_path)) {
    return { ok: false, reason: `Job #${jobId} chưa có file video để đăng lại.` };
  }
  if (job.campaign && ['PAUSED', 'CANCELLED'].includes(job.campaign.status)) {
    return { ok: false, reason: `Campaign #${job.campaign.id} đang ${job.campaign.status}, chưa thể đăng lại.` };
  }

  await removeQueuedBullJobs(jobId);
  const targets = await prisma.publishTargets.findMany({
    where: { job_id: jobId, platform: 'youtube' }
  });
  if (targets.length === 0) {
    return { ok: false, reason: 'Không tìm thấy liên kết YouTube target để đăng lại.' };
  }

  for (const target of targets) {
    await prisma.publishTargets.update({
      where: { id: target.id },
      data: { status: 'PUBLISH_QUEUED', error_log: null }
    });
    await addJobToQueue(jobId, 'PUBLISH', 0, 'youtube', target.id);
  }

  await auditBotAction(jobId, 'YOUTUBE_BOT_RETRY_PUBLISH', 'INFO', `User retried YouTube publish for job #${jobId}.`);
  return { ok: true, reason: `Đã đưa Job #${jobId} vào hàng đợi đăng lại YouTube.` };
}

const youtubeMenu = Markup.inlineKeyboard([
  [
    Markup.button.callback('📊 Trạng thái', 'yt:status'),
    Markup.button.callback('📅 Lịch hôm nay', 'yt:schedule_today'),
  ],
  [
    Markup.button.callback('👤 Quản lý tài khoản', 'yt:accounts'),
    Markup.button.callback('⏳ Video chờ duyệt', 'yt:pending'),
  ],
  [
    Markup.button.callback('📆 Lịch tuần', 'yt:schedule_week'),
    Markup.button.callback('💡 Đề xuất', 'yt:recommend'),
  ],
]);

const createWizards = new Map<number, { step: 'topic' | 'target'; targetDate: string; contentType: 'shorts' | 'video'; topic?: string }>();

function onboardingKeyboard(connectUrl?: string) {
  return youtubeMainKeyboard(connectUrl);
}

async function buildWelcomeMessage(userId: number, userName: string = 'Nhà Sáng Tạo') {
  const connection = await getConnectedPlatformConnection(userId, 'youtube');
  return buildStartMessage({
    platform: 'youtube',
    userName,
    connectionLabel: connection?.account_name || null,
  });
}

async function buildSetupReport(userId: number) {
  const connection = await getConnectedPlatformConnection(userId, 'youtube');
  return buildSetupMessage(Boolean(connection), 'youtube');
}

async function startYouTubeTranslateDubSession(ctx: any) {
  try {
    const chatId = ctx.chat?.id;
    if (!chatId) return;

    if (activeCreationSessions.has(chatId)) {
      activeCreationSessions.delete(chatId);
    }

    const session: ActiveCreationSession = {
      chatId,
      kind: 'translate_dub',
      title: 'Dịch thuật & Lồng tiếng AI',
      subtitle: 'Lồng tiếng Việt cho video nguồn',
      startedAt: Date.now(),
    };
    activeCreationSessions.set(chatId, session);

    await ctx.replyWithHTML(
      `<b>Dịch & lồng tiếng video</b>\n` +
      `Gửi một file video <code>.mp4</code>/<code>.mov</code> hoặc dán link YouTube/TikTok nguồn.\n\n` +
      `Sau khi nhận nguồn, bot sẽ hỏi tỷ lệ hiển thị để tạo bản lồng tiếng phù hợp YouTube/Shorts.\n\n` +
      `Gõ <b>/cancel</b> để hủy.`,
    );
  } catch (error: any) {
    console.error('[YouTube Bot Error] Error starting translate dub session:', error);
    await ctx.reply(`Không thể khởi tạo phiên lồng tiếng: ${error.message}`);
  }
}

function helpMessage() {
  return buildHelpMessage('youtube');
}

async function getOrCreateBotUser(ctx: any) {
  const from = ctx.from;
  const chat = ctx.chat;
  if (!from?.id) throw new Error('Không xác định được Telegram user.');
  const displayName = [from.first_name, from.last_name].filter(Boolean).join(' ') || from.username || null;
  return upsertTelegramUser({
    telegramUserId: from.id,
    telegramChatId: chat?.id || null,
    displayName,
  });
}

async function ensureYouTubeConnected(ctx: any) {
  const user = await getOrCreateBotUser(ctx);
  const connection = await getConnectedPlatformConnection(user.id, 'youtube');
  if (connection) return { user, connection };
  const url = buildYouTubeConnectUrl(user.id);
  await ctx.reply(
    `Bạn cần kết nối kênh YouTube trước.\n\n` +
    `Lý do: mỗi người dùng đăng lên kênh riêng, nên bot cần quyền upload của đúng tài khoản YouTube của bạn. Sau khi kết nối, bạn không cần nhập token thủ công.`,
    Markup.inlineKeyboard([
      [Markup.button.url('Kết nối YouTube', url)],
      [Markup.button.callback('Xem hướng dẫn', 'yt:help')],
    ]),
  );
  return null;
}

function formatTargetDate(value: string) {
  const parsed = parseScheduleTime(value);
  if (parsed) return formatDateTime(parsed);
  if (value === 'today') return 'Hôm nay';
  if (value === 'tomorrow') return 'Ngày mai';
  return value;
}


async function generateSingleVideoIdea(topic: string, targetAudience: string, isLongPhilosophy: boolean = false): Promise<{ title: string, concept: string, mood: string }> {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    return {
      title: `Ý tưởng: ${topic}`,
      concept: isLongPhilosophy ? `Diễn giải sâu sắc triết lý: ${topic}` : `Video ngắn về ${topic} cho ${targetAudience}`,
      mood: isLongPhilosophy ? 'dramatic' : 'educational',
    };
  }
  const prompt = isLongPhilosophy
    ? `
Bạn là nhà triết học và chuyên gia truyền cảm hứng sâu sắc hàng đầu. Hãy đề xuất 1 ý tưởng video dài phân tích sâu sắc câu nói triết lý/châm ngôn sau:
- Câu nói triết lý: "${topic}"
- Đối tượng mục tiêu: "${targetAudience}"

Hãy trả về kết quả dưới dạng JSON duy nhất, có cấu trúc:
{
  "title": "Tiêu đề chiêm nghiệm triết lý sâu sắc (dưới 60 ký tự, lay động lòng người)",
  "concept": "Mô tả ngắn gọn về hướng tiếp cận sâu lắng và ý nghĩa cốt lõi của video",
  "mood": "dramatic"
}
Lưu ý quan trọng: Phần "mood" hãy đặt là "dramatic" hoặc "chill" để phù hợp với nhịp điệu chậm rãi, sâu lắng. Chỉ trả về chuỗi JSON thô hợp lệ, không bọc trong markdown tam giác hay bất cứ ký tự nào khác.
`
    : `
Bạn là chuyên gia sáng tạo nội dung YouTube Shorts viral hàng đầu Việt Nam. Hãy đề xuất 1 ý tưởng video ngắn cực kỳ hấp dẫn dựa trên thông tin sau:
- Chủ đề: "${topic}"
- Đối tượng xem mục tiêu: "${targetAudience}"

Hãy trả về kết quả dưới dạng JSON duy nhất, có cấu trúc:
{
  "title": "Tiêu đề video viral cực chất (dưới 60 ký tự, thu hút, tò mò, gây bất ngờ)",
  "concept": "Mô tả ngắn gọn về ý tưởng và kịch bản phân cảnh chính của video",
  "mood": "educational"
}
Lưu ý quan trọng: Phần "mood" phải chọn một trong các giá trị: "educational", "energetic", "lofi", "chill", "dramatic". Chỉ trả về chuỗi JSON thô hợp lệ, không bọc trong markdown tam giác hay bất cứ ký tự nào khác.
`;
  try {
    const result = await generateContentWithFallback(prompt, { temperature: 0.7, responseMimeType: 'application/json' });
    const raw = result.text;
    const parsed = cleanAndParseJson(raw);
    return {
      title: parsed.title || `Ý tưởng: ${topic}`,
      concept: parsed.concept || `Video ngắn về ${topic}`,
      mood: parsed.mood || (isLongPhilosophy ? 'dramatic' : 'educational'),
    };
  } catch (error) {
    console.error('Failed to generate video idea with Gemini:', error);
    return {
      title: isLongPhilosophy ? `Suy ngẫm: ${topic.slice(0, 30)}...` : `Bí quyết ${topic} cực hay`,
      concept: `Góc nhìn sáng tạo về ${topic} dành riêng cho ${targetAudience}.`,
      mood: isLongPhilosophy ? 'dramatic' : 'educational',
    };
  }
}

function formatNaturalTargetDate(targetDateStr: string) {
  const parsed = parseScheduleTime(targetDateStr);
  if (parsed) return formatDateTime(parsed);
  if (targetDateStr === 'today') return 'Hôm Nay (Ngay lúc gửi)';
  if (targetDateStr === 'tomorrow') return 'Ngày Mai';
  if (/^\d{4}-\d{2}-\d{2}$/.test(targetDateStr)) return targetDateStr.split('-').reverse().join('/');
  return targetDateStr;
}

async function startCampaignLogic(ctx: any, topic: string, targetAudience: string, targetDateStr: string = 'today', presetLabel?: string) {
  const connected = await ensureYouTubeConnected(ctx);
  if (!connected) return;

  const targetDateText = formatNaturalTargetDate(targetDateStr);
  let cleanTopic = topic.trim();
  
  const activeSession = await beginActiveOperation(ctx, {
    chatId: ctx.chat.id,
    kind: 'single_video',
    title: 'Đang tạo video YouTube',
    subtitle: `${presetLabel ? `${presetLabel} - ` : ''}${cleanTopic.slice(0, 25)}... | ${targetAudience} | ${targetDateText}`,
  });

  try {
    const idea = await generateSingleVideoIdea(cleanTopic, targetAudience, false);

    const campaign = await prisma.channelsCampaign.create({
      data: {
        telegram_chat_id: BigInt(ctx.chat?.id || 0),
        topic: cleanTopic.length > 250 ? cleanTopic.slice(0, 250) : cleanTopic,
        target_audience: targetAudience,
        status: 'RUNNING',
      },
    });
    await prisma.$executeRawUnsafe(`UPDATE channels_campaign SET user_id = ${Number(connected.user.id)} WHERE id = ${Number(campaign.id)}`);

    let scheduledTime = parseScheduleTime(targetDateStr) || new Date();
    if (targetDateStr === 'tomorrow') {
      scheduledTime = new Date(Date.now() + 24 * 60 * 60 * 1000);
    } else if (targetDateStr !== 'today' && /^\d{4}-\d{2}-\d{2}$/.test(targetDateStr)) {
      scheduledTime = new Date(targetDateStr + 'T12:00:00+07:00');
    }

    const metadata = {
      music_mood: idea.mood,
      content_category: 'youtube',
      primary_goal: 'VIEWS',
      concept_description: idea.concept,
      platform: 'youtube',
      content_type: 'shorts',
    };

    const job = await prisma.videoPipelineJobs.create({
      data: {
        campaign_id: campaign.id,
        day_number: 1,
        scheduled_post_time: scheduledTime,
        video_title_idea: idea.title,
        scenes_layout_json: JSON.stringify(metadata),
        pipeline_state: 'QUEUED',
      },
    });

    await createOrUpdateYouTubePublishTarget(job.id, scheduledTime, 'shorts', connected.user.id, connected.connection.id);

    activeSession.jobId = job.id;
    activeSession.campaignId = campaign.id;
    activeSession.subtitle = `${idea.title} | ${targetDateText}`;
    await refreshActiveOperation(activeSession);

    await addJobToQueue(job.id, 'RENDER');

    await auditBotAction(job.id, 'YOUTUBE_BOT_START_CAMPAIGN', 'INFO', `Khởi chạy chiến dịch YouTube đơn lẻ #${campaign.id} Job #${job.id} ngày: ${targetDateText}`);
    await refreshActiveOperation(activeSession);
  } catch (error: any) {
    console.error('Error starting single YouTube campaign:', error);
    stopActiveOperation(ctx.chat.id);
    await ctx.reply(`❌ Không thể khởi tạo chiến dịch YouTube: ${error.message}`);
  }
}

async function replyCampaignDashboard(ctx: any) {
  const message =
    `<b>Tạo chiến dịch YouTube</b>\n` +
    `Nhập chủ đề và nhóm người xem. Bot sẽ lập lịch chuỗi video cho kênh YouTube.\n\n` +
    `Dùng lệnh:\n` +
    `<code>/startcampaign Chủ đề | Đối tượng</code>\n\n` +
    `Hoặc bấm <b>Tạo thủ công</b> để nhập từng bước.`;

  const keyboard = Markup.inlineKeyboard([
    [Markup.button.callback('Tạo thủ công', 'yt:camp_wizard:start')],
    [
      Markup.button.callback('Lịch', 'yt:schedule_today'),
      Markup.button.callback('Menu', 'yt:menu_home'),
    ],
  ]);

  await ctx.replyWithHTML(message, keyboard);
}

async function handleCampaignWizardStep(ctx: any, text: string) {
  const chatId = ctx.chat?.id;
  if (!chatId) return;

  const wizard = campaignWizards.get(chatId);
  if (!wizard) return;

  if (wizard.step === 'awaiting_topic') {
    const topic = text.trim();
    if (!topic) {
      await ctx.replyWithHTML('❌ Chủ đề không được để trống. Vui lòng nhập lại chủ đề chiến dịch YouTube:');
      return;
    }

    campaignWizards.set(chatId, {
      ...wizard,
      step: 'awaiting_target',
      topic,
    });
    await ctx.replyWithHTML(
      `✍️ <b>CHỦ ĐỀ ĐÃ NHẬN:</b> <b>${escapeHtml(topic)}</b>\n\n` +
      `Hãy gửi nhóm <b>Đối tượng người xem mục tiêu</b> bạn muốn hướng tới:\n` +
      `<i>(Ví dụ: Học sinh, dân công sở, lập trình viên, người thích nghe nhạc chill)</i>`
    );
    return;
  }

  if (wizard.step === 'awaiting_target') {
    const target = text.trim();
    if (!target) {
      await ctx.replyWithHTML('❌ Đối tượng không được để trống. Vui lòng nhập lại đối tượng mục tiêu:');
      return;
    }

    const topic = wizard.topic || 'Chủ đề tự chọn';
    campaignWizards.delete(chatId);

    return startCampaignLogic(ctx, topic, target, wizard.targetDate || 'today', 'Step-by-Step');
  }
}

async function createYouTubeVideoJob(ctx: any, topic: string, targetAudience: string, targetDate: string, contentType: 'shorts' | 'video') {
  const connected = await ensureYouTubeConnected(ctx);
  if (!connected) return;
  const scheduledTime = parseScheduleTime(targetDate) || (targetDate === 'tomorrow' ? new Date(Date.now() + 24 * 60 * 60 * 1000) : new Date());
  const contentLabel = contentType === 'shorts' ? 'YouTube Short' : 'YouTube Video';

  const campaign = await prisma.channelsCampaign.create({
    data: {
      telegram_chat_id: BigInt(ctx.chat?.id || 0),
      topic,
      target_audience: targetAudience,
      status: 'RUNNING',
    },
  });
  await prisma.$executeRawUnsafe(`UPDATE channels_campaign SET user_id = ${Number(connected.user.id)} WHERE id = ${Number(campaign.id)}`);

  const job = await prisma.videoPipelineJobs.create({
    data: {
      campaign_id: campaign.id,
      day_number: 1,
      scheduled_post_time: scheduledTime,
      video_title_idea: `${contentLabel}: ${topic}`.slice(0, 255),
      scenes_layout_json: JSON.stringify({
        platform: 'youtube',
        content_type: contentType,
        music_mood: contentType === 'shorts' ? 'energetic' : 'educational',
        content_category: 'youtube',
        primary_goal: 'VIEWS',
        concept_description: `${contentLabel} về ${topic} cho ${targetAudience}`,
      }),
      pipeline_state: 'QUEUED',
    },
  });

  await createOrUpdateYouTubePublishTarget(job.id, scheduledTime, contentType, connected.user.id, connected.connection.id);
  await addJobToQueue(job.id, 'RENDER');
  await auditBotAction(job.id, 'YOUTUBE_BOT_CREATE', 'INFO', `Created ${contentLabel} job from YouTube bot.`);

  await ctx.replyWithHTML(
    `✅ <b>ĐÃ TẠO ${escapeHtml(contentLabel.toUpperCase())}</b>\n` +
    `━━━━━━━━━━━━━━━━━━━━━\n` +
    `▪️ Job: <b>#${job.id}</b>\n` +
    `▪️ Chủ đề: <b>${escapeHtml(topic)}</b>\n` +
    `▪️ Đối tượng: <b>${escapeHtml(targetAudience)}</b>\n` +
    `▪️ Lịch YouTube: <b>${escapeHtml(formatDateTime(scheduledTime))}</b>\n\n` +
    `Mình đã đưa video vào hàng đợi render. Sau khi render xong, dùng /preview ${job.id} để xem và duyệt đăng YouTube.`
  );
}

async function previewYouTubeJob(ctx: any, jobId: number) {
  const user = await getOrCreateBotUser(ctx);
  const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
  if (!job) return ctx.reply(`Không tìm thấy Job #${jobId}.`);
  if (!job.video_output_path || !fs.existsSync(job.video_output_path)) {
    return ctx.reply(`Job #${jobId} chưa có file video để preview.`);
  }

  // 1. Lấy danh sách tất cả các tài khoản liên kết của user
  const connections = await getOwnYouTubeConnections(user.id);
  if (connections.length === 0) {
    const url = buildYouTubeConnectUrl(user.id);
    return ctx.reply(
      `Bạn cần kết nối kênh YouTube trước khi xem preview và duyệt đăng.\n\n` +
      `Bấm nút dưới đây để kết nối kênh của bạn.`,
      Markup.inlineKeyboard([[Markup.button.url('Kết nối YouTube', url)]])
    );
  }

  // 2. Lấy tất cả các publish_targets đang có cho job này ở trạng thái PENDING_APPROVAL
  let activeTargets = await findYouTubeTargets(jobId, ['PENDING_APPROVAL'], user.id);

  // Nếu chưa có bất kỳ target nào được chọn, tự động chọn tài khoản đầu tiên làm mặc định
  if (activeTargets.length === 0) {
    const firstConn = connections[0];
    const contentType = detectJobContentType(job);
    const defaultTarget = await createOrUpdateYouTubePublishTarget(
      jobId,
      job.scheduled_post_time,
      contentType,
      user.id,
      firstConn.id
    );
    if (defaultTarget) {
      activeTargets.push(defaultTarget);
    }
  }

  // 3. Xây dựng nội dung hiển thị
  const contentType = detectJobContentType(job);
  const metadata = buildYouTubeMetadata(job, contentType);
  
  const selectedChannelsNames = activeTargets
    .map(t => {
      const conn = connections.find(c => c.id === t.platform_connection_id);
      return conn ? (conn.account_name || `Kênh ID: ${conn.external_account_id}`) : 'Kênh ẩn';
    })
    .join(', ');

  const firstTarget = activeTargets[0];
  const publishTime = firstTarget?.scheduled_publish_time ? new Date(firstTarget.scheduled_publish_time) : null;
  const isPast = publishTime ? publishTime.getTime() < Date.now() : true;
  const displayTime = isPast ? 'Đăng ngay (Lịch cũ đã qua)' : formatDateTime(publishTime!);

  const caption =
    `📺 YOUTUBE PREVIEW - JOB #${jobId}\n` +
    `──────────────────────────────\n` +
    `▪️ Tiêu đề: ${firstTarget?.title || metadata.title}\n` +
    `▪️ Lịch đăng: ${displayTime}\n` +
    `▪️ Tài khoản nhận bài: <b>${escapeHtml(selectedChannelsNames || 'Chưa chọn')}</b>\n` +
    `▪️ Tags: ${(parseTargetTags(firstTarget?.tags).length ? parseTargetTags(firstTarget.tags) : metadata.tags).join(', ')}`;

  // 4. Xây dựng phím tương tác động (Checkbox Keyboard)
  const inlineKeyboard: any[] = [];

  // Thêm hàng nút bấm cho mỗi tài khoản
  connections.forEach(conn => {
    const isSelected = activeTargets.some(t => t.platform_connection_id === conn.id);
    const prefix = isSelected ? '☑️' : '⬜';
    const action = isSelected ? 'deselect' : 'select';
    inlineKeyboard.push([
      {
        text: `${prefix} ${conn.account_name || 'YouTube Channel'}`,
        callback_data: `yt:toggle_account:${jobId}:${conn.id}:${action}`
      }
    ]);
  });

  // Nút hành động phê duyệt
  const N = activeTargets.length;
  if (N > 0) {
    inlineKeyboard.push([
      { text: `🚀 Phê Duyệt & Đăng Video [Chọn ${N}]`, callback_data: `yt:approve_all:${jobId}` }
    ]);
  } else {
    inlineKeyboard.push([
      { text: `⚠️ Vui lòng chọn ít nhất 1 tài khoản`, callback_data: `yt:noop` }
    ]);
  }

  // Nút hủy/đóng
  inlineKeyboard.push([
    { text: '❌ Hủy lượt đăng', callback_data: `yt:cancel_job:${jobId}` }
  ]);

  const fileStats = fs.statSync(job.video_output_path);
  const fileSizeMb = fileStats.size / (1024 * 1024);

  if (fileSizeMb > 49.0) {
    console.warn(`[YouTube Bot] Video for job #${jobId} is too large (${fileSizeMb.toFixed(2)} MB). Skipping upload to prevent timeout.`);
    await ctx.replyWithHTML(
      `⚠️ <b>Không thể tải preview lên Telegram do dung lượng lớn.</b>\n` +
      `Video đã render xong thành công nhưng kích thước (<code>${fileSizeMb.toFixed(2)} MB</code>) vượt quá giới hạn upload 50MB của Telegram Bot API.\n━━━━━━━━━━━━━━━━━━━━━\n` +
      `${caption}`,
      { reply_markup: { inline_keyboard: inlineKeyboard } }
    );
    return;
  }

  try {
    await ctx.replyWithVideo(
      { source: job.video_output_path },
      {
        caption: caption.slice(0, 1000),
        parse_mode: 'HTML',
        reply_markup: { inline_keyboard: inlineKeyboard },
      },
    );
  } catch (videoError: any) {
    console.warn(`[YouTube Bot Warning] Failed to upload preview video for job #${jobId}; trying document fallback:`, videoError?.message || videoError);

    try {
      await ctx.replyWithDocument(
        { source: job.video_output_path, filename: path.basename(job.video_output_path) },
        {
          caption: caption.slice(0, 1000),
          parse_mode: 'HTML',
          reply_markup: { inline_keyboard: inlineKeyboard },
        },
      );
    } catch (documentError: any) {
      console.warn(`[YouTube Bot Warning] Failed to upload preview document for job #${jobId}:`, documentError?.message || documentError);
      await ctx.replyWithHTML(
        `⚠️ <b>Không thể tải preview lên Telegram.</b>\n` +
        `Video đã render xong thành công nhưng gặp sự cố khi upload lên Telegram.\n━━━━━━━━━━━━━━━━━━━━━\n` +
        `${caption}`,
        { reply_markup: { inline_keyboard: inlineKeyboard } }
      );
    }
  }
}

async function approveYouTubePublishAll(ctx: any, jobId: number, newTimeText?: string) {
  const user = await getOrCreateBotUser(ctx);
  const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
  if (!job) return ctx.reply(`Không tìm thấy Job #${jobId}.`);

  const connections = await getOwnYouTubeConnections(user.id);
  const activeTargets = await findYouTubeTargets(jobId, ['PENDING_APPROVAL'], user.id);

  if (activeTargets.length === 0) {
    return ctx.reply('⚠️ Vui lòng chọn ít nhất 1 tài khoản YouTube để đăng bài.');
  }

  let scheduledTime = job.scheduled_post_time || new Date();
  if (newTimeText) {
    scheduledTime = resolveTimeWithContext(newTimeText, scheduledTime);
  }

  const isPast = scheduledTime.getTime() < Date.now();
  if (isPast) {
    scheduledTime = new Date();
  }
  const displayTime = isPast ? 'Đăng ngay bây giờ (Do lịch cũ đã qua)' : formatDateTime(scheduledTime);

  const selectedNames = activeTargets
    .map(t => {
      const conn = connections.find(c => c.id === t.platform_connection_id);
      return conn ? (conn.account_name || `Kênh ID: ${conn.external_account_id}`) : 'Kênh ẩn';
    })
    .join(', ');

  const confirmation = createConfirmation(
    ctx.chat.id,
    'approve_youtube_publish_all',
    `Duyệt đăng YouTube Job #${jobId} lên <b>${activeTargets.length} kênh</b>: ${escapeHtml(selectedNames)}\n` +
    `Lịch đăng: ${displayTime}.`,
    { jobId, userId: user.id, newTimeIso: scheduledTime.toISOString() },
  );

  return ctx.replyWithHTML(
    `❓ <b>XÁC NHẬN PHÊ DUYỆT ĐĂNG HÀNG LOẠT</b>\n━━━━━━━━━━━━━━━━━━━━━\n${confirmation.summary}`,
    Markup.inlineKeyboard([
      Markup.button.callback('✅ Xác nhận đăng', `yt:confirm:${confirmation.id}`),
      Markup.button.callback('❌ Hủy', `yt:deny:${confirmation.id}`),
    ]),
  );
}

youtubeBot.start(async (ctx) => {
  const user = await getOrCreateBotUser(ctx);
  const connection = await getConnectedPlatformConnection(user.id, 'youtube');
  const url = connection ? undefined : buildYouTubeConnectUrl(user.id);
  const firstName = ctx.from?.first_name || 'Nhà Sáng Tạo';
  return ctx.replyWithHTML(await buildWelcomeMessage(user.id, firstName), onboardingKeyboard(url));
});

youtubeBot.command('status', async (ctx) => {
  try {
    const user = await getOrCreateBotUser(ctx);
    return ctx.replyWithHTML(await getYouTubeStatusReport(user.id));
  } catch (error: any) {
    ctx.reply(`❌ Không thể truy vấn trạng thái: ${error.message}`);
  }
});

youtubeBot.command('schedule', async (ctx) => {
  try {
    const user = await getOrCreateBotUser(ctx);
    const text = ctx.message.text.substring(9).toLowerCase();
    return ctx.replyWithHTML(await getYouTubeScheduleReport(text.includes('week') || text.includes('tuần') ? 'week' : 'today', user.id));
  } catch (error: any) {
    ctx.reply(`❌ Không thể xem lịch: ${error.message}`);
  }
});

youtubeBot.command('pending', async (ctx) => {
  try {
    const user = await getOrCreateBotUser(ctx);
    return ctx.replyWithHTML(await getYouTubePendingApprovalReport(user.id));
  } catch (error: any) {
    ctx.reply(`❌ Không thể xem video chờ duyệt: ${error.message}`);
  }
});

youtubeBot.command('preview', async (ctx) => {
  try {
    const text = ctx.message.text.substring(8).trim();
    const jobId = parseInt(text, 10);
    if (isNaN(jobId)) {
      return replyCommandGuidance(ctx, 'preview', 'Mã tác vụ không hợp lệ hoặc trống');
    }
    return previewYouTubeJob(ctx, jobId);
  } catch (error: any) {
    ctx.reply(`❌ Không thể xem preview: ${error.message}`);
  }
});

youtubeBot.command('approve', async (ctx) => {
  try {
    const jobId = parseInt(ctx.message.text.substring(8).trim(), 10);
    if (!jobId) return replyCommandGuidance(ctx, 'approve', 'Thiếu Job ID');
    return approveYouTubePublishAll(ctx, jobId);
  } catch (error: any) {
    ctx.reply(`❌ Không thể duyệt đăng: ${error.message}`);
  }
});

youtubeBot.command('music_video', async (ctx) => {
  try {
    const text = ctx.message.text.substring(12).trim();
    let songTitle = '';
    let artistName = '';
    
    if (text && text.includes('|')) {
      const parts = text.split('|');
      songTitle = parts[0].trim();
      artistName = parts[1].trim();
    } else if (text) {
      songTitle = text.trim();
      artistName = 'Tự động phát hiện';
    } else {
      songTitle = 'HOT TRENDING';
      artistName = 'AUTO DETECT';
    }

    await handleCreateMusicVideoLogic(ctx, songTitle, artistName);
  } catch (error: any) {
    ctx.reply(`❌ Không thể tạo video âm nhạc: ${error.message}`);
  }
});

youtubeBot.command('create_music_video', async (ctx) => {
  try {
    const text = ctx.message.text.substring(19).trim();
    let songTitle = '';
    let artistName = '';
    
    if (text && text.includes('|')) {
      const parts = text.split('|');
      songTitle = parts[0].trim();
      artistName = parts[1].trim();
    } else if (text) {
      songTitle = text.trim();
      artistName = 'Tự động phát hiện';
    } else {
      songTitle = 'HOT TRENDING';
      artistName = 'AUTO DETECT';
    }

    await handleCreateMusicVideoLogic(ctx, songTitle, artistName);
  } catch (error: any) {
    ctx.reply(`❌ Không thể tạo video âm nhạc: ${error.message}`);
  }
});

youtubeBot.command('remix_music', async (ctx) => {
  try {
    const text = ctx.message.text.substring(12).trim();
    const jobId = parseInt(text, 10);
    if (isNaN(jobId)) {
      return replyCommandGuidance(ctx, 'remix_music', 'Mã tác vụ không hợp lệ hoặc trống');
    }

    const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
    if (!job) {
      return ctx.reply(`❌ LỖI HỆ THỐNG: Không tìm thấy tác vụ Job #${jobId}.`);
    }

    const metadata = parseMetadata(job.scenes_layout_json);
    const audioPath = metadata.audio_path || metadata.remix_audio_path || job.audio_file_path;
    if (!audioPath || !fs.existsSync(audioPath)) {
      return ctx.reply(`⚠️ CẢNH BÁO TÀI NGUYÊN: Tác vụ Job #${jobId} chưa có tệp âm thanh hợp lệ để thực hiện Remix.`);
    }

    const confirmation = createConfirmation(
      ctx.chat.id,
      'remix_music',
      `Remix tài nguyên âm thanh cho tác vụ YouTube Job #${jobId} theo mẫu đã chọn.`,
      { jobId, rightsConfirmed: true }
    );

    await ctx.reply(
      `❓ XÁC NHẬN YÊU CẦU THỰC THI REMIX YOUTUBE:\n━━━━━━━━━━━━━━━━━━━━━\n${confirmation.summary}`,
      Markup.inlineKeyboard([
        Markup.button.callback('✅ Xác nhận', `yt:confirm:${confirmation.id}`),
        Markup.button.callback('❌ Hủy bỏ', `yt:deny:${confirmation.id}`),
      ])
    );
  } catch (error: any) {
    ctx.reply(`❌ Không thể chuẩn bị remix: ${error.message}`);
  }
});

youtubeBot.command('render_music', async (ctx) => {
  try {
    const text = ctx.message.text.substring(13).trim();
    const jobId = parseInt(text, 10);
    if (isNaN(jobId)) {
      return replyCommandGuidance(ctx, 'render_music', 'Mã tác vụ không hợp lệ hoặc trống');
    }
    await enqueueMusicReactiveRender(ctx, jobId);
  } catch (error: any) {
    ctx.reply(`❌ Không thể render music reactive: ${error.message}`);
  }
});

youtubeBot.command('job_config', async (ctx) => {
  try {
    const text = ctx.message.text.substring(11).trim();
    const jobId = parseInt(text, 10);
    if (isNaN(jobId)) {
      return replyCommandGuidance(ctx, 'job_config', 'mã tác vụ trống');
    }
    const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
    if (!job) {
      return ctx.reply(`❌ LỖI: Không tìm thấy tác vụ Job #${jobId}.`);
    }
    const metadata = parseMetadata(job.scenes_layout_json);
    await ctx.reply('🔄 Đang phân tích và gợi ý AI cho tác vụ YouTube...', { parse_mode: 'Markdown' });
    const displayText = await buildJobConfigDisplay(jobId, job, metadata, true);
    const renderMode = metadata.render_mode || 'classic_video';
    await ctx.reply(displayText, {
      parse_mode: 'Markdown',
      ...postTemplateKeyboard(jobId, renderMode === 'music_reactive' ? 'render' : 'remix'),
    });
  } catch (error: any) {
    ctx.reply(`❌ Không thể xem cấu hình: ${error.message}`);
  }
});

youtubeBot.command('set_job_config', async (ctx) => {
  try {
    const text = ctx.message.text.substring(15).trim();
    const match = text.match(/^(\d+)\s+(.+)$/s);
    if (!match) {
      return replyCommandGuidance(ctx, 'set_job_config', 'cú pháp trống');
    }

    const jobId = parseInt(match[1], 10);
    const updates = parseConfigUpdates(match[2]);
    if (Object.keys(updates).length === 0) {
      return replyCommandGuidance(ctx, 'set_job_config', 'tham số cấu hình không hợp lệ');
    }

    const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
    if (!job) {
      return ctx.reply(`❌ LỖI: Không tìm thấy tác vụ Job #${jobId}.`);
    }

    const metadata = parseMetadata(job.scenes_layout_json);
    Object.assign(metadata, updates);
    await prisma.videoPipelineJobs.update({
      where: { id: jobId },
      data: { scenes_layout_json: JSON.stringify(metadata) },
    });
    await auditBotAction(jobId, 'YOUTUBE_BOT_JOB_CONFIG', 'SUCCESS', `Updated job config: ${JSON.stringify(updates)}`);

    await ctx.reply(
      `✅ Đã cập nhật thành công cấu hình YouTube Job #${jobId}:\n` +
      Object.entries(updates).map(([key, value]) => `▪️ <b>${escapeHtml(key)}:</b> <code>${escapeHtml(String(value))}</code>`).join('\n'),
      { parse_mode: 'HTML' }
    );
  } catch (error: any) {
    ctx.reply(`❌ Không thể cập nhật cấu hình: ${error.message}`);
  }
});

youtubeBot.command('reschedule', async (ctx) => {
  try {
    const text = ctx.message.text.substring(11).trim();
    const match = text.match(/^(\d+)\s+(.+)$/);
    if (!match) {
      return replyCommandGuidance(ctx, 'reschedule', 'cú pháp trống');
    }

    const jobId = parseInt(match[1], 10);
    const newTime = parseScheduleTime(match[2]);
    if (!newTime) {
      return replyCommandGuidance(ctx, 'reschedule', 'thời gian không hợp lệ');
    }

    const confirmation = createConfirmation(
      ctx.chat.id,
      'reschedule_video',
      `Dời lịch phát sóng YouTube Job #${jobId} sang ${formatDateTime(newTime)}.`,
      { jobId, newTimeIso: newTime.toISOString() },
    );

    await ctx.reply(
      `❓ XÁC NHẬN YÊU CẦU THỰC THI HÀNG ĐỘNG HỆ THỐNG:\n\n${confirmation.summary}`,
      Markup.inlineKeyboard([
        Markup.button.callback('✅ Xác nhận', `yt:confirm:${confirmation.id}`),
        Markup.button.callback('❌ Hủy bỏ', `yt:deny:${confirmation.id}`),
      ]),
    );
  } catch (error: any) {
    ctx.reply(`❌ Không thể dời lịch: ${error.message}`);
  }
});

youtubeBot.command('calendar', async (ctx) => {
  try {
    await ctx.replyWithHTML(
      `📅 <b>QUẢN LÝ LỊCH TRÌNH YOUTUBE</b>\n` +
      `━━━━━━━━━━━━━━━━━━━━━\n` +
      `Chọn ngày bạn muốn xem hoặc quản lý lịch trình đăng video YouTube bên dưới:`,
      getCalendarMenuKeyboard(),
    );
  } catch (error: any) {
    ctx.reply(`❌ Lỗi khi hiển thị lịch trình: ${error.message}`);
  }
});

youtubeBot.command('force_post', async (ctx) => {
  try {
    const text = ctx.message.text.substring(11).trim();
    const jobId = parseInt(text, 10);
    if (isNaN(jobId)) {
      return replyCommandGuidance(ctx, 'force_post', 'Mã tác vụ trống hoặc không hợp lệ');
    }

    const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
    if (!job) {
      return ctx.reply(`❌ LỖI HỆ THỐNG: Không tìm thấy tác vụ Job #${jobId}.`);
    }

    const confirmation = createConfirmation(
      ctx.chat.id,
      'force_publish',
      `Yêu cầu xuất bản ngay lập tức YouTube Job #${jobId}.`,
      { jobId },
    );

    await ctx.reply(
      `❓ XÁC NHẬN YÊU CẦU XUẤT BẢN NGAY YOUTUBE:\n━━━━━━━━━━━━━━━━━━━━━\n${confirmation.summary}`,
      Markup.inlineKeyboard([
        Markup.button.callback('✅ Xác nhận', `yt:confirm:${confirmation.id}`),
        Markup.button.callback('❌ Hủy bỏ', `yt:deny:${confirmation.id}`),
      ]),
    );
  } catch (error: any) {
    ctx.reply(`❌ Đã xảy ra lỗi khi yêu cầu đăng ngay: ${error.message}`);
  }
});

youtubeBot.command('retry_publish', async (ctx) => {
  try {
    const text = ctx.message.text.substring('/retry_publish'.length).trim();
    const jobId = parseInt(text, 10);
    if (isNaN(jobId)) {
      return ctx.reply('Vui lòng nhập đúng mẫu: /retry_publish <job_id>');
    }
    const result = await retryPublishJob(jobId, ctx.chat?.id);
    await ctx.reply(result.ok ? `✅ ${result.reason}` : `❌ ${result.reason}`);
  } catch (error: any) {
    ctx.reply(`❌ Không thể đăng lại: ${error.message}`);
  }
});

youtubeBot.command('logs', async (ctx) => {
  try {
    const text = ctx.message.text.substring(5).trim();
    const jobId = parseInt(text, 10);
    if (isNaN(jobId)) {
      return replyCommandGuidance(ctx, 'logs', 'Mã tác vụ trống hoặc không hợp lệ');
    }

    const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
    if (!job) {
      return ctx.reply(`❌ Không tìm thấy tác vụ #${jobId}.`);
    }

    const isRunning = CANCELLABLE_PIPELINE_STATES.includes(job.pipeline_state);
    if (isRunning) {
      stopActiveOperation(ctx.chat.id);
      
      const kind = String(job.video_title_idea || '').toLowerCase().includes('[dub]') || job.scenes_layout_json?.toString().includes('translate_dub')
        ? 'translate_dub' 
        : 'campaign';

      await beginActiveOperation(ctx, {
        chatId: ctx.chat.id,
        title: job.pipeline_state === MUSIC_AUDIO_WAITING_STATE ? 'Đang Chờ Gửi File Nhạc' : 'Tiến Trình Tạo Video Tự Động',
        subtitle: job.video_title_idea || 'Đang xử lý tác vụ...',
        kind: kind as any,
        jobId: job.id,
      });
      return;
    }

    const logs = await prisma.processRealtimeLogs.findMany({
      where: { job_id: jobId },
      orderBy: { logged_at: 'asc' },
      take: 40
    });

    if (logs.length === 0) {
      return ctx.reply(`ℹ️ Không tìm thấy dữ liệu nhật ký cho Job #${jobId} (Trạng thái hiện tại: ${job.pipeline_state}).`);
    }

    let message = `📋 NHẬT KÝ TIẾN TRÌNH YOUTUBE - JOB #${jobId} (ĐÃ KẾT THÚC)\n━━━━━━━━━━━━━━━━━━━━━\n`;
    for (const log of logs) {
      const emoji = log.status_level === 'ERROR' ? '❌' : log.status_level === 'SUCCESS' ? '✅' : 'ℹ️';
      const timeStr = new Date(log.logged_at).toLocaleTimeString('vi-VN');
      message += `${emoji} (${timeStr}) ${log.execution_step}: ${log.log_message}\n`;
    }

    if (message.length > 4000) {
      message = message.substring(0, 3970) + '...\n(Log quá dài, đã lược bớt)';
    }

    await ctx.reply(message);
  } catch (error: any) {
    ctx.reply(`❌ Không thể truy vấn logs: ${error.message}`);
  }
});

youtubeBot.command('cancel', async (ctx) => {
  const chatId = ctx.chat?.id;
  if (!chatId) return;
  const activeSession = activeCreationSessions.get(chatId);
  if (activeSession) {
    await cancelActiveOperation(ctx, activeSession);
    return;
  }

  const hadWizard = campaignWizards.has(chatId);
  const hadEdit = calendarEditStates.has(chatId);
  const hadInput = calendarInputStates.has(chatId);
  campaignWizards.delete(chatId);
  calendarEditStates.delete(chatId);
  calendarInputStates.delete(chatId);
  if (hadWizard || hadEdit || hadInput) {
    await ctx.reply('❌ Đã hủy bỏ tất cả tiến trình nhập liệu đang chờ (Wizard / Lịch trình / Chỉnh sửa).');
    return;
  }

  const latestJob = await findLatestCancellableJobForChat(chatId);
  if (latestJob) {
    const result = await cancelPersistedJob(latestJob.id, chatId);
    await ctx.reply(result.ok
      ? `Đã hủy thao tác đang chạy.\n${result.reason}`
      : `Không thể hủy thao tác.\n${result.reason}`);
  } else {
    await ctx.reply('ℹ️ Không có tác vụ hay tiến trình nhập liệu nào đang chạy để hủy.');
  }
});

youtubeBot.command('connect_youtube', async (ctx) => {
  const user = await getOrCreateBotUser(ctx);
  return ctx.reply('Bấm nút dưới đây để kết nối kênh YouTube của bạn.', Markup.inlineKeyboard([Markup.button.url('Kết nối YouTube', buildYouTubeConnectUrl(user.id))]));
});

youtubeBot.command('disconnect_youtube', async (ctx) => {
  const user = await getOrCreateBotUser(ctx);
  await disconnectPlatform(user.id, 'youtube');
  return ctx.reply('Đã ngắt kết nối YouTube cho tài khoản Telegram này.');
});

youtubeBot.command('connection', async (ctx) => {
  const user = await getOrCreateBotUser(ctx);
  const connection = await getConnectedPlatformConnection(user.id, 'youtube');
  return ctx.reply(
    connection ? 'YouTube đã kết nối cho tài khoản này. Bạn có thể tạo video hoặc duyệt đăng ngay.' : 'YouTube chưa kết nối. Bấm nút bên dưới để kết nối.',
    connection ? youtubeMenu : onboardingKeyboard(buildYouTubeConnectUrl(user.id)),
  );
});
youtubeBot.command('menu', async (ctx) => {
  const user = await getOrCreateBotUser(ctx);
  const connection = await getConnectedPlatformConnection(user.id, 'youtube');
  return ctx.replyWithHTML(
    await buildWelcomeMessage(user.id, ctx.from?.first_name || 'Nhà Sáng Tạo'),
    connection ? youtubeMainKeyboard() : onboardingKeyboard(buildYouTubeConnectUrl(user.id)),
  );
});
youtubeBot.command('help', async (ctx) => ctx.replyWithHTML(helpMessage(), youtubeMainKeyboard()));
youtubeBot.command('translate_dub', async (ctx) => startYouTubeTranslateDubSession(ctx));
youtubeBot.command('setup', async (ctx) => {
  const user = await getOrCreateBotUser(ctx);
  const connection = await getConnectedPlatformConnection(user.id, 'youtube');
  return ctx.reply(await buildSetupReport(user.id), connection ? youtubeMenu : onboardingKeyboard(buildYouTubeConnectUrl(user.id)));
});

async function showAccountsReport(ctx: any) {
  const user = await getOrCreateBotUser(ctx);
  const connections = await getOwnYouTubeConnections(user.id);

  if (connections.length === 0) {
    return ctx.replyWithHTML(
      `<b>DANH SÁCH TÀI KHOẢN YOUTUBE LIÊN KẾT</b>\n` +
      `──────────────────────────────\n` +
      `Chưa có tài khoản nào được kết nối.\n\n` +
      `Bấm nút dưới đây để thêm liên kết mới.`,
      Markup.inlineKeyboard([
        [Markup.button.url('🔗 Kết nối YouTube mới', buildYouTubeConnectUrl(user.id))],
        [Markup.button.callback('Quay lại Menu', 'yt:menu_home')]
      ])
    );
  }

  const lines = connections.map((conn, idx) => {
    const name = conn.account_name || `Kênh #${conn.id}`;
    const channelId = conn.external_account_id || 'N/A';
    const statusIcon = conn.status === 'connected' ? '✅' : '❌';
    return `${idx + 1}. ${statusIcon} <b>${escapeHtml(name)}</b>\n   ID: <code>${escapeHtml(channelId)}</code>\n   Trạng thái: ${conn.status}`;
  });

  const report =
    `<b>DANH SÁCH TÀI KHOẢN YOUTUBE LIÊN KẾT</b>\n` +
    `──────────────────────────────\n\n` +
    lines.join('\n\n');

  const inlineButtons: any[] = [];
  connections.forEach((conn) => {
    inlineButtons.push([
      Markup.button.callback(`❌ Ngắt ${conn.account_name || 'YouTube'}`, `yt:disconnect:${conn.id}`)
    ]);
  });
  inlineButtons.push([
    Markup.button.url('🔗 Kết nối YouTube mới', buildYouTubeConnectUrl(user.id))
  ]);
  inlineButtons.push([
    Markup.button.callback('Quay lại Menu', 'yt:menu_home')
  ]);

  const keyboard = Markup.inlineKeyboard(inlineButtons);

  if (ctx.callbackQuery) {
    try {
      await ctx.editMessageText(report, {
        parse_mode: 'HTML',
        reply_markup: keyboard.reply_markup,
      });
      return;
    } catch {
      // Fallback
    }
  }
  return ctx.replyWithHTML(report, keyboard);
}

youtubeBot.command('accounts', async (ctx) => showAccountsReport(ctx));




youtubeBot.on(['audio', 'document', 'photo', 'video', 'video_note'], async (ctx) => {
  try {
    const dubHandled = await handleIncomingDubVideoUpload(ctx);
    if (dubHandled) return;

    const handled = await handleWaitingMusicAttachmentUpload(ctx);
    if (!handled) {
      await ctx.reply('Hiện không có tác vụ YouTube nào đang chờ nhận tệp tin.');
    }
  } catch (error: any) {
    console.error('[YouTube Bot Error] Error handling attachment upload:', error);
    const errMsg = error?.message || String(error);
    if (errMsg.toLowerCase().includes('too big') || errMsg.toLowerCase().includes('400')) {
      await ctx.replyWithHTML(
        `⚠️ <b>TỆP QUÁ LỚN (GIỚI HẠN TELEGRAM 20MB)</b>\n` +
        `━━━━━━━━━━━━━━━━━━━━━\n` +
        `Telegram Bot API áp dụng giới hạn nghiêm ngặt: <b>Không cho phép tải xuống các file gửi trực tiếp lớn hơn 20MB</b> qua bot.\n\n` +
        `👉 <b>CÁCH GIẢI QUYẾT RẤT ĐƠN GIẢN:</b>\n` +
        `1️⃣ <b>Gửi link video (Khuyên dùng):</b> Hãy tải video của bạn lên YouTube (ở chế độ không công khai/unlisted), Google Drive (mở quyền chia sẻ xem), hoặc Douyin / TikTok rồi <b>dán link video vào bot</b>. Tiến trình tải video từ link chạy độc lập nên <b>không giới hạn dung lượng</b> (video 500MB hay 1GB+ đều tải vô cùng mượt mà!).\n\n` +
        `2️⃣ <b>Đặt file trực tiếp (Dành cho Local Dev):</b> Vì bạn đang chạy dự án ngay trên máy cá nhân, bạn chỉ cần copy file video đó trực tiếp vào thư mục:\n` +
        `<code>shared/assets/uploads/dub_sources/</code>\n` +
        `Sau đó, nhắn tin gửi tên file chính xác cho bot!`
      );
      return;
    }
    await ctx.reply(`❌ Không thể nhận file: ${error.message}`);
  }
});

youtubeBot.on('text', async (ctx) => {
  try {
    const chatId = ctx.chat?.id;
    const text = ctx.message.text.trim();
    if (!text || text.startsWith('/')) return;

    // --- Ưu tiên 0: Xử lý khi đang ở phiên lồng tiếng hoặc có lock activeOperation ---
    if (chatId && activeCreationSessions.has(chatId)) {
      const session = activeCreationSessions.get(chatId)!;
      if (session.kind === 'translate_dub') {
        if (isCancelRequest(text)) {
          activeCreationSessions.delete(chatId);
          await ctx.reply('❌ Đã hủy phiên lồng tiếng AI.');
          return;
        }

        const isUrl = /^(https?:\/\/)?([\w-]+\.)+[\w-]+(\/[\w-./?%&=]*)?$/i.test(text) || text.startsWith('http');
        if (isUrl) {
          await ctx.reply('📥 Đã nhận đường link video nguồn! Đang lưu thông tin...');
          session.tempSourceType = 'link';
          session.tempSourceUrl = text;
          session.tempFileName = `${text.slice(0, 45)}...`;

          await ctx.reply(
            `📥 Đã lưu thông tin đường dẫn nguồn!\n` +
            `👉 Vui lòng chọn tỷ lệ kích thước màn hình để lồng tiếng (tránh méo hình, phù hợp YouTube Short):`,
            Markup.inlineKeyboard([
              [
                Markup.button.callback('📺 Giữ nguyên gốc (Original)', 'yt:dub_ratio:original'),
                Markup.button.callback('📱 Dọc 9:16 (Blur Padding)', 'yt:dub_ratio:vertical_blur')
              ],
              [
                Markup.button.callback('❌ Hủy bỏ', 'yt:cancel_active:pending')
              ]
            ])
          );
          return;
        } else {
          await ctx.reply('Tệp tin hoặc đường dẫn chưa hợp lệ. Vui lòng gửi một file video (.mp4/.mov) hoặc một đường dẫn YouTube/TikTok.');
          return;
        }
      }

      // Check locked active operations
      const pipelineJob = session.jobId ? await prisma.videoPipelineJobs.findUnique({ where: { id: session.jobId } }) : null;
      const isWaitingForMusic = pipelineJob?.pipeline_state === MUSIC_AUDIO_WAITING_STATE;
      if (!isWaitingForMusic) {
        await ctx.replyWithHTML(buildActiveSessionLockMessage(session.subtitle));
        return;
      }
    }

    // --- Ưu tiên 1: Chỉnh sửa tiêu đề Calendar Job ---
    if (chatId && calendarEditStates.has(chatId)) {
      const editState = calendarEditStates.get(chatId)!;
      calendarEditStates.delete(chatId);
      try {
        await prisma.videoPipelineJobs.update({
          where: { id: editState.jobId },
          data: { video_title_idea: text },
        });
        await ctx.replyWithHTML(
          `✅ <b>ĐÃ CẬP NHẬT TIÊU ĐỀ THÀNH CÔNG</b>\n` +
          `━━━━━━━━━━━━━━━━━━━━━\n` +
          `▪️ Job #${editState.jobId}\n` +
          `▪️ Tiêu đề mới: <b>${escapeHtml(text)}</b>\n\n` +
          `💡 Sử dụng /calendar để quay lại quản lý lịch trình.`,
        );
      } catch (err: any) {
        await ctx.reply(`❌ Lỗi khi cập nhật tiêu đề Job #${editState.jobId}: ${err.message}`);
      }
      return;
    }

    // --- Ưu tiên 2: Nhập ngày Calendar thủ công ---
    if (chatId && calendarInputStates.has(chatId)) {
      calendarInputStates.delete(chatId);
      const dateMatch = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
      if (dateMatch) {
        return renderCalendarDateView(ctx, text);
      } else {
        await ctx.replyWithHTML(
          `❌ <b>Định dạng ngày không hợp lệ.</b>\n` +
          `Vui lòng nhập đúng định dạng <code>YYYY-MM-DD</code> (ví dụ: <code>2026-05-22</code>).\n\n` +
          `Hoặc gõ /calendar để quay lại menu lịch trình.`,
        );
      }
      return;
    }

    // --- Ưu tiên 3: Wizard Campaign ---
    if (chatId && campaignWizards.has(chatId)) {
      return handleCampaignWizardStep(ctx, text);
    }

    // Check if there is a pending confirmation for this chat that could be adjusted
    if (chatId) {
      const latestConfirm = getLatestPendingConfirmation(chatId);
      if (latestConfirm && ['approve_youtube_publish', 'approve_youtube_publish_all'].includes(latestConfirm.action)) {
        const parsedIntent = await parseBotIntent(text, 'youtube');
        if (parsedIntent.newTimeText) {
          cancelConfirmation(latestConfirm.id);
          const jobId = latestConfirm.payload.jobId;
          await ctx.reply(`🔄 Nhận diện điều chỉnh thời gian đăng cho Job #${jobId}...`);
          return approveYouTubePublishAll(ctx, jobId, parsedIntent.newTimeText);
        }
      }
    }

    const wizard = chatId ? createWizards.get(chatId) : null;
    if (wizard) {
      if (wizard.step === 'topic') {
        createWizards.set(chatId, { ...wizard, step: 'target', topic: text });
        return ctx.reply('Bạn muốn nhắm đến đối tượng người xem nào? Ví dụ: sinh viên, dân văn phòng, người mới học AI.');
      }
      if (wizard.step === 'target' && wizard.topic) {
        createWizards.delete(chatId);
        return createYouTubeVideoJob(ctx, wizard.topic, text, wizard.targetDate, wizard.contentType);
      }
    }

    const lower = text.toLowerCase();
    if (['menu', 'youtube', 'yt'].includes(lower)) {
      const user = await getOrCreateBotUser(ctx);
      const connection = await getConnectedPlatformConnection(user.id, 'youtube');
      return ctx.replyWithHTML(
        await buildWelcomeMessage(user.id, ctx.from?.first_name || 'Nhà Sáng Tạo'),
        connection ? youtubeMainKeyboard() : onboardingKeyboard(buildYouTubeConnectUrl(user.id)),
      );
    }
    if (['help', 'hướng dẫn', 'huong dan'].includes(lower)) return ctx.replyWithHTML(helpMessage(), youtubeMainKeyboard());

    const intent = await parseBotIntent(text, 'youtube');
    await auditBotAction(null, 'YOUTUBE_BOT_INTENT', 'INFO', `User text: "${text}" -> ${JSON.stringify(intent)}`);

    if (intent.platform === 'tiktok') {
      return ctx.reply('Tin nhắn này có vẻ dành cho TikTok. Hãy gửi qua bot TikTok để tránh đăng nhầm nền tảng.');
    }

    const user = await getOrCreateBotUser(ctx);

    if (intent.intent === 'view_schedule') return ctx.replyWithHTML(await getYouTubeScheduleReport(intent.period || 'today', user.id));
    if (intent.intent === 'view_status') return ctx.replyWithHTML(await getYouTubeStatusReport(user.id));
    if (intent.intent === 'list_pending_approval') return ctx.replyWithHTML(await getYouTubePendingApprovalReport(user.id));
    if (intent.intent === 'preview_video') {
      const jobId = await resolveJobId(intent);
      if (!jobId) return ctx.reply('Không tìm thấy job để preview.');
      return previewYouTubeJob(ctx, jobId);
    }
    if (intent.intent === 'approve_publish' || intent.intent === 'force_publish') {
      const jobId = await resolveJobId(intent);
      if (!jobId) return ctx.reply('Không tìm thấy job đã render để duyệt đăng YouTube.');
      return approveYouTubePublishAll(ctx, jobId, intent.newTimeText);
    }
    if (intent.intent === 'render_music') {
      const jobId = await resolveJobId(intent);
      if (!jobId) return ctx.reply('Không tìm thấy job để render.');
      return enqueueMusicReactiveRender(ctx, jobId);
    }
    if (intent.intent === 'create_music_video') {
      return handleCreateMusicVideoLogic(ctx, intent.songTitle || 'HOT TRENDING', intent.artistName || 'AUTO DETECT', intent.newTimeText || 'today');
    }
    if (intent.intent === 'quick_create_video') {
      const targetDate = intent.newTimeText || 'today';
      const contentType = intent.contentType || 'shorts';
      if (intent.topic) {
        return createYouTubeVideoJob(
          ctx,
          intent.topic,
          intent.targetAudience || 'Người xem YouTube Việt Nam quan tâm chủ đề này',
          targetDate,
          contentType,
        );
      }
      if (chatId) createWizards.set(chatId, { step: 'topic', targetDate, contentType });
      return ctx.reply(`Mình đã hiểu lịch ${formatTargetDate(targetDate)}. Hãy gửi chủ đề video YouTube bạn muốn làm.`);
    }

    const actionSummary = await buildActionSummary(intent);
    if (actionSummary) {
      const confirmation = createConfirmation(
        ctx.chat.id,
        actionSummary.action === 'approve_publish' ? 'approve_youtube_publish' : actionSummary.action as any,
        actionSummary.summary.replace(/TikTok Studio/g, 'YouTube').replace(/phát hành video/g, 'đăng video'),
        actionSummary.payload,
      );

      return ctx.reply(
        `❓ XÁC NHẬN YÊU CẦU THỰC THI NGHIỆP VỤ:\n━━━━━━━━━━━━━━━━━━━━━\n${confirmation.summary}`,
        Markup.inlineKeyboard([
          Markup.button.callback('✅ Xác nhận', `yt:confirm:${confirmation.id}`),
          Markup.button.callback('❌ Hủy bỏ', `yt:deny:${confirmation.id}`),
        ]),
      );
    }

    return ctx.reply(buildUnknownIntentMessage('youtube'), youtubeMainKeyboard());
  } catch (error: any) {
    console.error('[YouTube Bot] Error handling message:', error);
    return ctx.reply(`Không thể xử lý yêu cầu YouTube: ${error.message}`);
  }
});

function getTrendingTemplateMessage(jobId: number | null = null) {
  const targetText = jobId ? `Tác vụ: Job #${jobId}` : 'Khởi tạo tác vụ mới';
  return (
    `CẤU HÌNH SPLIT-SCREEN YOUTUBE (${targetText})\n` +
    `──────────────────────────────\n` +
    Object.values(TREND_PRESETS).map((preset) => (
      `• ${preset.label}: ${preset.description}`
    )).join('\n') +
    `\n\n` +
    (jobId
      ? `Chọn một cấu hình bên dưới, sau đó xác nhận thực thi.`
      : `[!] Chưa có tác vụ phù hợp. Chọn một cấu hình để tạo tác vụ mới đưa vào hàng đợi render.`)
  );
}

async function safeAnswerCbQuery(ctx: any, text?: string, options?: any) {
  try {
    await ctx.answerCbQuery(text, options);
  } catch (error: any) {
    const msg = error.message || String(error);
    if (msg.includes('query is too old') || msg.includes('query ID is invalid')) {
      console.warn('[YouTube Bot Warning] Could not answer callback query (ignored safely):', msg);
    } else {
      console.error('[YouTube Bot Error] Failed to answer callback query:', error);
    }
  }
}

youtubeBot.on('callback_query', async (ctx) => {
  try {
    const data = (ctx.callbackQuery as any).data || '';
    const chatId = ctx.chat?.id;
    if (!chatId) return;

    const user = await getOrCreateBotUser(ctx);

    if (data === 'yt:content_hub') {
      await ctx.answerCbQuery();
      const connection = await getConnectedPlatformConnection(user.id, 'youtube');
      return ctx.replyWithHTML(
        buildContentHubMessage('youtube'),
        youtubeContentKeyboard(connection ? undefined : buildYouTubeConnectUrl(user.id)),
      );
    }
    if (data === 'yt:content_music_video') {
      await ctx.answerCbQuery('Đang mở luồng tạo music video...');
      return handleCreateMusicVideoLogic(ctx, 'HOT TRENDING', 'AUTO DETECT');
    }
    if (data === 'yt:content_translate_dub') {
      await ctx.answerCbQuery('Đang mở luồng dịch & lồng tiếng...');
      return startYouTubeTranslateDubSession(ctx);
    }
    if (data === 'yt:connect') {
      await ctx.answerCbQuery();
      return ctx.reply('Bấm nút dưới đây để kết nối kênh YouTube của bạn.', Markup.inlineKeyboard([Markup.button.url('Kết nối YouTube', buildYouTubeConnectUrl(user.id))]));
    }
    if (data === 'yt:accounts') {
      await ctx.answerCbQuery();
      return showAccountsReport(ctx);
    }
    if (data.startsWith('yt:disconnect:')) {
      const parts = data.split(':');
      const connId = parseInt(parts[2], 10);
      try {
        const conn = await prisma.platformConnections.findUnique({ where: { id: connId } });
        if (!conn || conn.user_id !== user.id) {
          await ctx.answerCbQuery('Không tìm thấy liên kết tài khoản.', { show_alert: true });
          return;
        }
        await prisma.$executeRawUnsafe(`DELETE FROM platform_connections WHERE id = ${connId}`);
        await ctx.answerCbQuery(`Đã ngắt kết nối: ${conn.account_name || 'Kênh'}`);
        return showAccountsReport(ctx);
      } catch (e: any) {
        await ctx.answerCbQuery(`Lỗi: ${e.message}`, { show_alert: true });
        return;
      }
    }
    if (data === 'yt:menu_home') {
      await ctx.answerCbQuery();
      const connection = await getConnectedPlatformConnection(user.id, 'youtube');
      return ctx.replyWithHTML(
        await buildWelcomeMessage(user.id, ctx.from?.first_name || 'Nhà Sáng Tạo'),
        connection ? youtubeMainKeyboard() : onboardingKeyboard(buildYouTubeConnectUrl(user.id)),
      );
    }
    if (data === 'yt:connection') {
      const connection = await getConnectedPlatformConnection(user.id, 'youtube');
      await ctx.answerCbQuery();
      return ctx.reply(
        connection ? 'YouTube đã kết nối cho tài khoản này. Bạn có thể tạo video hoặc duyệt đăng ngay.' : 'YouTube chưa kết nối. Bấm nút bên dưới để kết nối.',
        connection ? youtubeMenu : onboardingKeyboard(buildYouTubeConnectUrl(user.id)),
      );
    }
    if (data === 'yt:setup') {
      const connection = await getConnectedPlatformConnection(user.id, 'youtube');
      await ctx.answerCbQuery();
      return ctx.replyWithHTML(
        await buildSetupReport(user.id),
        connection ? youtubeMainKeyboard() : onboardingKeyboard(buildYouTubeConnectUrl(user.id)),
      );
    }
    if (data === 'yt:help') {
      await ctx.answerCbQuery();
      return ctx.replyWithHTML(helpMessage(), youtubeMainKeyboard());
    }
    if (data === 'yt:status') return ctx.replyWithHTML(await getYouTubeStatusReport(user.id));
    if (data === 'yt:schedule_today') return ctx.replyWithHTML(await getYouTubeScheduleReport('today', user.id));
    if (data === 'yt:schedule_week') return ctx.replyWithHTML(await getYouTubeScheduleReport('week', user.id));
    if (data === 'yt:pending') return ctx.replyWithHTML(await getYouTubePendingApprovalReport(user.id));
    if (data === 'yt:create_short' || data === 'yt:create_video') {
      createWizards.set(chatId, { step: 'topic', targetDate: 'today', contentType: data === 'yt:create_short' ? 'shorts' : 'video' });
      await ctx.answerCbQuery();
      return ctx.reply('Hãy gửi chủ đề video YouTube bạn muốn tạo.');
    }
    if (data.startsWith('yt:toggle_account:')) {
      await ctx.answerCbQuery();
      const parts = data.split(':');
      const jobId = parseInt(parts[2], 10);
      const connId = parseInt(parts[3], 10);
      const action = parts[4];

      if (action === 'select') {
        const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
        if (job) {
          const contentType = detectJobContentType(job);
          await createOrUpdateYouTubePublishTarget(jobId, job.scheduled_post_time, contentType, user.id, connId);
        }
      } else if (action === 'deselect') {
        const target = await findYouTubeTargetByConnection(jobId, connId);
        if (target && target.status === 'PENDING_APPROVAL') {
          await deletePublishTarget(target.id);
        }
      }

      const connections = await getOwnYouTubeConnections(user.id);
      const activeTargets = await findYouTubeTargets(jobId, ['PENDING_APPROVAL'], user.id);
      const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });

      if (job) {
        const contentType = detectJobContentType(job);
        const metadata = buildYouTubeMetadata(job, contentType);
        const selectedChannelsNames = activeTargets
          .map(t => {
            const conn = connections.find(c => c.id === t.platform_connection_id);
            return conn ? (conn.account_name || `Kênh ID: ${conn.external_account_id}`) : 'Kênh ẩn';
          })
          .join(', ');

        const firstTarget = activeTargets[0];
        const publishTime = firstTarget?.scheduled_publish_time ? new Date(firstTarget.scheduled_publish_time) : null;
        const isPast = publishTime ? publishTime.getTime() < Date.now() : true;
        const displayTime = isPast ? 'Đăng ngay (Lịch cũ đã qua)' : formatDateTime(publishTime!);

        const caption =
          `📺 YOUTUBE PREVIEW - JOB #${jobId}\n` +
          `──────────────────────────────\n` +
          `▪️ Tiêu đề: ${firstTarget?.title || metadata.title}\n` +
          `▪️ Lịch đăng: ${displayTime}\n` +
          `▪️ Tài khoản nhận bài: <b>${escapeHtml(selectedChannelsNames || 'Chưa chọn')}</b>\n` +
          `▪️ Tags: ${(parseTargetTags(firstTarget?.tags).length ? parseTargetTags(firstTarget.tags) : metadata.tags).join(', ')}`;

        const inlineKeyboard: any[] = [];
        connections.forEach(conn => {
          const isSelected = activeTargets.some(t => t.platform_connection_id === conn.id);
          const prefix = isSelected ? '☑️' : '⬜';
          const act = isSelected ? 'deselect' : 'select';
          inlineKeyboard.push([
            {
              text: `${prefix} ${conn.account_name || 'YouTube Channel'}`,
              callback_data: `yt:toggle_account:${jobId}:${conn.id}:${act}`
            }
          ]);
        });

        const N = activeTargets.length;
        if (N > 0) {
          inlineKeyboard.push([
            { text: `🚀 Phê Duyệt & Đăng Video [Chọn ${N}]`, callback_data: `yt:approve_all:${jobId}` }
          ]);
        } else {
          inlineKeyboard.push([
            { text: `⚠️ Vui lòng chọn ít nhất 1 tài khoản`, callback_data: `yt:noop` }
          ]);
        }

        inlineKeyboard.push([
          { text: '❌ Hủy lượt đăng', callback_data: `yt:cancel_job:${jobId}` }
        ]);

        try {
          await ctx.editMessageCaption(caption.slice(0, 1000), {
            parse_mode: 'HTML',
            reply_markup: { inline_keyboard: inlineKeyboard }
          });
        } catch (editErr) {
          console.warn('[YouTube Bot] Failed to edit message caption, sending fallback preview...');
          await previewYouTubeJob(ctx, jobId);
        }
      }
      return;
    }

    if (data.startsWith('yt:approve_all:')) {
      await ctx.answerCbQuery();
      return approveYouTubePublishAll(ctx, parseInt(data.split(':')[2], 10));
    }

    if (data === 'yt:noop') {
      return ctx.answerCbQuery('Hãy chọn ít nhất một kênh YouTube bằng cách bấm vào các dòng có ô vuông ở trên.', { show_alert: true });
    }

    if (data.startsWith('yt:approve:')) {
      await ctx.answerCbQuery();
      return approveYouTubePublishAll(ctx, parseInt(data.split(':')[2], 10));
    }
    if (data.startsWith('yt:cancel_target:')) {
      const targetId = parseInt(data.split(':')[2], 10);
      await updateYouTubeTarget(targetId, { status: 'CANCELLED' });
      await ctx.answerCbQuery('Đã hủy target YouTube.');
      return ctx.reply('Đã hủy lượt đăng YouTube này.');
    }
    if (data.startsWith('yt:camp_preset:')) {
      const presetKey = data.split(':')[2];
      const presets: Record<string, { label: string; topic: string; target: string }> = {
        lofi_student: {
          label: 'Lofi Chill & Học Tập 🎧',
          topic: 'Nhạc Lofi và trích dẫn truyền cảm hứng học tập',
          target: 'Học sinh, sinh viên muốn tập trung học tập',
        },
        office_skills: {
          label: 'Kỹ Năng Công Sở Excel/Word 💻',
          topic: 'Mẹo tin học văn phòng Excel/Word/PPT và hiệu suất làm việc',
          target: 'Dân văn phòng, người đi làm muốn nâng cao năng lực',
        },
        self_dev: {
          label: 'Tư Duy & Phát Triển Bản Thân 🚀',
          topic: 'Tư duy tích cực, phát triển bản thân và thói quen thành công',
          target: 'Người trẻ khát vọng học hỏi & cải thiện tư duy',
        },
        music_trend: {
          label: 'Music Remix Hot Trend 🔥',
          topic: 'Remix các bài hát hot trend kết hợp visual chuyển động mạnh',
          target: 'Người trẻ mê âm nhạc & visual bắt mắt sôi động',
        },
      };

      const preset = presets[presetKey];
      if (!preset) {
        await ctx.answerCbQuery('Mẫu chiến dịch không hợp lệ.', { show_alert: true });
        return;
      }

      await ctx.answerCbQuery(`Khởi chạy chiến dịch YouTube: ${preset.label}`);
      await startCampaignLogic(ctx, preset.topic, preset.target, 'today', preset.label);
      return;
    }

    if (data.startsWith('yt:camp_wizard:')) {
      const action = data.split(':')[2];
      if (action === 'start') {
        campaignWizards.set(chatId, { step: 'awaiting_topic' });
        await ctx.answerCbQuery();
        await ctx.replyWithHTML(
          `✍️ <b>BƯỚC 1/2: NHẬP CHỦ ĐỀ CHIẾN DỊCH YOUTUBE</b>\n` +
          `━━━━━━━━━━━━━━━━━━━━━\n` +
          `Hãy gửi tin nhắn nhập chủ đề cho chiến dịch video (Ví dụ: <i>Kinh nghiệm du lịch tự túc</i>, <i>Học tiếng Anh giao tiếp</i>,...)\n\n` +
          `👉 <i>Soạn /cancel hoặc bấm nút bên dưới để hủy bỏ bất kỳ lúc nào.</i>`,
          Markup.inlineKeyboard([
            [Markup.button.callback('❌ Hủy bỏ', 'yt:camp_wizard:cancel')]
          ])
        );
        return;
      }

      if (action === 'cancel') {
        campaignWizards.delete(chatId);
        calendarEditStates.delete(chatId);
        calendarInputStates.delete(chatId);
        await ctx.answerCbQuery();
        await ctx.reply('❌ Đã hủy bỏ quá trình thiết lập chiến dịch YouTube.');
        return;
      }

      if (action === 'launch') {
        const wizard = campaignWizards.get(chatId);
        if (!wizard || !wizard.topic || !wizard.target) {
          await ctx.answerCbQuery('Lỗi: Không tìm thấy thông tin chiến dịch.', { show_alert: true });
          return;
        }
        await ctx.answerCbQuery();
        await startCampaignLogic(ctx, wizard.topic, wizard.target, wizard.targetDate || 'today');
        campaignWizards.delete(chatId);
        return;
      }

      if (action === 'launch_today' || action === 'launch_tomorrow') {
        const wizard = campaignWizards.get(chatId);
        if (!wizard || !wizard.topic || !wizard.target) {
          await ctx.answerCbQuery('Lỗi: Không tìm thấy thông tin chiến dịch.', { show_alert: true });
          return;
        }
        const dateStr = action === 'launch_today' ? 'today' : 'tomorrow';
        await ctx.answerCbQuery();
        await startCampaignLogic(ctx, wizard.topic, wizard.target, dateStr);
        campaignWizards.delete(chatId);
        return;
      }
      return;
    }

    if (data.startsWith('yt:cancel_active:')) {
      const parts = data.split(':');
      const target = parts[2];
      const parsedJobId = /^\d+$/.test(target || '') ? parseInt(target, 10) : null;
      const session = activeCreationSessions.get(chatId);
      const targetJobId = parsedJobId || session?.jobId || (await findLatestCancellableJobForChat(chatId))?.id;
      if (!session && !targetJobId) {
        await ctx.answerCbQuery('Không có thao tác đang chạy để hủy.', { show_alert: true });
        return;
      }

      await ctx.answerCbQuery('Đang hủy thao tác hiện tại...');
      if (targetJobId) {
        const result = await cancelPersistedJob(targetJobId, chatId);
        stopActiveOperation(chatId);
        await ctx.replyWithHTML(result.ok
          ? `Đã hủy thao tác đang chạy.\n${result.reason}`
          : `Không thể hủy thao tác.\n${result.reason}`);
        return;
      }

      if (session) {
        await cancelActiveOperation(ctx, session);
      }
      return;
    }

    if (data.startsWith('yt:dub_ratio:')) {
      try {
        const ratioMode = data.split(':')[2];
        const session = activeCreationSessions.get(chatId);
        if (!session || session.kind !== 'translate_dub' || !session.tempSourceType) {
          await ctx.answerCbQuery('Phiên lồng tiếng không còn hiệu lực.', { show_alert: true });
          return;
        }

        await ctx.answerCbQuery('Đang thiết lập và khởi tạo tiến trình...');
        await ctx.editMessageReplyMarkup({ inline_keyboard: [] }).catch(() => {});

        const isFile = session.tempSourceType === 'file';
        if (!isFile && process.env.ENABLE_DUBBING_URL_IMPORT !== 'true') {
          await ctx.answerCbQuery('Nhập URL đang tạm tắt để bảo vệ nguồn video. Hãy gửi tệp video.', { show_alert: true });
          return;
        }
        const scenesLayout = {
          render_mode: 'translate_dub',
          dub_source_type: session.tempSourceType,
          dub_source_path: isFile ? session.tempSourcePath : undefined,
          dub_source_url: !isFile ? session.tempSourceUrl : undefined,
          voice_gender: 'female',
          target_language: 'vi',
          aspect_ratio: ratioMode,
          platform: 'youtube'
        };

        const job = await prisma.videoPipelineJobs.create({
          data: {
            day_number: 1,
            scheduled_post_time: new Date(),
            video_title_idea: isFile ? `[DUB] ${session.tempFileName}` : `[DUB LINK] ${session.tempFileName}`,
            pipeline_state: 'QUEUED',
            scenes_layout_json: JSON.stringify(scenesLayout)
          }
        });

        const connection = await getConnectedPlatformConnection(user.id, 'youtube');
        if (connection) {
          await createOrUpdateYouTubePublishTarget(job.id, new Date(), 'shorts', user.id, connection.id);
        }

        await addJobToQueue(job.id, 'RENDER');
        await auditBotAction(job.id, 'YOUTUBE_BOT_DUB_VIDEO_UPLOAD', 'SUCCESS', `Created YouTube dubbing Job #${job.id} with ratio ${ratioMode}.`);

        session.jobId = job.id;
        session.subtitle = isFile ? `[DUB] ${session.tempFileName}` : `[DUB LINK] ${session.tempFileName}`;
        
        delete session.tempSourceType;
        delete session.tempSourcePath;
        delete session.tempSourceUrl;
        delete session.tempFileName;

        await beginActiveOperation(ctx, session);
      } catch (e: any) {
        await ctx.answerCbQuery(`Lỗi: ${e.message}`, { show_alert: true });
      }
      return;
    }

    if (data.startsWith('yt:music_visual:')) {
      try {
        const parts = data.split(':');
        const mode = parts[2];
        const jobId = parseInt(parts[3], 10);
        if (isNaN(jobId)) {
          await ctx.answerCbQuery('Không xác định được Job.', { show_alert: true });
          return;
        }

        const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
        if (!job || job.pipeline_state !== MUSIC_AUDIO_WAITING_STATE) {
          await ctx.answerCbQuery('Job này không còn ở trạng thái chờ file nhạc.', { show_alert: true });
          return;
        }

        const metadata = parseMetadata(job.scenes_layout_json);
        if (mode === 'custom') {
          metadata.visual_mode = 'portrait_lyric';
          metadata.user_wants_custom_image = true;
          await prisma.videoPipelineJobs.update({
            where: { id: jobId },
            data: { scenes_layout_json: JSON.stringify(metadata) },
          });
          await ctx.answerCbQuery('Bạn có thể gửi ảnh visual trước khi gửi nhạc.');
          await ctx.replyWithHTML(
            `🖼️ <b>Đã chọn: tự cung cấp ảnh</b>\n` +
            `Gửi ảnh <code>.jpg</code>, <code>.png</code> hoặc <code>.webp</code> vào chat này.\n` +
            `Sau khi gửi ảnh, bạn gửi tiếp file nhạc <code>.mp3</code>, <code>.wav</code> hoặc <code>.m4a</code>.`,
          );
          return;
        }

        if (mode === 'lofi_anime') {
          metadata.visual_mode = 'lofi_anime';
          metadata.visual_template = 'lofi_anime';
          metadata.music_video_template = 'lofi_anime';
          metadata.user_wants_custom_image = false;
          await prisma.videoPipelineJobs.update({
            where: { id: jobId },
            data: { scenes_layout_json: JSON.stringify(metadata) },
          });
          await ctx.answerCbQuery('Đã chọn: Anime Loop Lofi cực chill.');
          await ctx.replyWithHTML(
            `🌸 <b>Đã chọn: Anime Loop Lofi cực chill</b>\n` +
            `Bây giờ bạn chỉ cần gửi file nhạc <code>.mp3</code>, <code>.wav</code> hoặc <code>.m4a</code>.`,
          );
          return;
        }

        metadata.visual_mode = 'auto';
        metadata.user_wants_custom_image = false;
        await prisma.videoPipelineJobs.update({
          where: { id: jobId },
          data: { scenes_layout_json: JSON.stringify(metadata) },
        });
        await ctx.answerCbQuery('Hệ thống sẽ tự lấy ảnh/video visual.');
        await ctx.replyWithHTML(
          `✨ <b>Đã chọn: hệ thống tự lấy visual</b>\n` +
          `Bây giờ bạn chỉ cần gửi file nhạc <code>.mp3</code>, <code>.wav</code> hoặc <code>.m4a</code>.`,
        );
        return;
      } catch (e: any) {
        await ctx.answerCbQuery(`Lỗi: ${e.message}`, { show_alert: true });
      }
      return;
    }

    if (data.startsWith('yt:music_cut_mode:')) {
      try {
        const parts = data.split(':');
        const mode = parts[2]; // 'viral' or 'full'
        const jobId = parseInt(parts[3], 10);
        if (isNaN(jobId)) {
          await ctx.answerCbQuery('Không xác định được Job.', { show_alert: true });
          return;
        }

        const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
        if (!job) {
          await ctx.answerCbQuery('Không tìm thấy Job.', { show_alert: true });
          return;
        }

        await ctx.editMessageReplyMarkup({ inline_keyboard: [] }).catch(() => {});

        const metadata = parseMetadata(job.scenes_layout_json);
        const isViral = mode === 'viral';
        metadata.auto_select_viral_segment = isViral;

        await ctx.answerCbQuery(`Đã chọn: ${isViral ? 'Cắt đoạn Viral' : 'Giữ nguyên toàn bộ bài'}`);

        await prisma.videoPipelineJobs.update({
          where: { id: jobId },
          data: {
            scenes_layout_json: JSON.stringify(metadata),
            pipeline_state: 'QUEUED',
            error_log_trace: null,
          },
        });
        await addJobToQueue(jobId, 'RENDER');
        await auditBotAction(jobId, 'YOUTUBE_BOT_MUSIC_CUT_MODE_SELECTED', 'SUCCESS', `User chose ${mode} audio mode for YouTube Job #${jobId}.`);

        if (chatId) {
          const activeSession = activeCreationSessions.get(chatId);
          if (activeSession) {
            activeSession.jobId = jobId;
            await refreshActiveOperation(activeSession);
          }
        }

        await ctx.replyWithHTML(
          `🎧 <b>Bắt đầu hàng đợi Render YouTube (Job #${jobId})</b>\n` +
          `━━━━━━━━━━━━━━━━━━━━━\n` +
          `▪️ Chế độ âm thanh: <b>${isViral ? '✂️ Tự Cắt Đoạn Viral (>= 60s)' : '🎵 Giữ Nguyên Toàn Bộ Bài'}</b>\n` +
          `▪️ Tiến trình phân tích âm thanh, nhịp điệu và render phụ đề đang được xử lý...`
        );
      } catch (e: any) {
        await ctx.answerCbQuery(`Lỗi: ${e.message}`, { show_alert: true });
      }
      return;
    }

    if (data.startsWith('yt:tpl:')) {
      try {
        const parts = data.split(':');
        const presetKey = parts[2];
        const jobId = parseInt(parts[3], 10);
        if (isNaN(jobId)) {
          await ctx.answerCbQuery('LỖI: Không xác định được tác vụ Job.', { show_alert: true });
          return;
        }

        const metadata = await applyTrendPreset(jobId, presetKey);
        await ctx.answerCbQuery('Đã áp dụng mẫu cấu hình thành công.');
        const mode = presetKey === 'render_only' ? 'render' : 'remix';
        return ctx.reply(
          `✅ THIẾT LẬP CẤU HÌNH THÀNH CÔNG (JOB #${jobId})\n━━━━━━━━━━━━━━━━━━━━━\n` +
          `▪️ Chế độ Render YouTube: \`${metadata.render_mode}\`\n` +
          `▪️ Phong cách Remix: \`${metadata.remix_style || 'Nguyên bản'}\`\n` +
          `▪️ Nhạc cảm (Mood): \`${metadata.mood || 'Mặc định'}\`\n` +
          `▪️ Nhịp điệu (BPM): \`${metadata.bpm || 'Tự động'}\`\n\n` +
          `Lựa chọn hành động vận hành tiếp theo bên dưới:`,
          postTemplateKeyboard(jobId, mode),
        );
      } catch (e: any) {
        await ctx.answerCbQuery(`Lỗi: ${e.message}`, { show_alert: true });
      }
      return;
    }

    if (data.startsWith('yt:create_tpl:')) {
      try {
        const presetKey = data.split(':')[2];
        const job = await createVideoFromTrendTemplate(ctx.chat?.id || 'unknown', presetKey);
        if (!job) {
          await ctx.answerCbQuery('Lỗi: Không tạo được tác vụ từ mẫu.', { show_alert: true });
          return;
        }
        await ctx.answerCbQuery('Khởi tạo tác vụ mới thành công.');
        return beginActiveOperation(ctx, {
          chatId: ctx.chat?.id || 0,
          kind: 'single_video',
          title: 'Đang tạo video từ mẫu',
          subtitle: TREND_PRESETS[presetKey]?.label || 'Bản chuẩn',
          jobId: job.id,
          campaignId: job.campaign_id || undefined,
        });
      } catch (e: any) {
        await ctx.answerCbQuery(`Lỗi: ${e.message}`, { show_alert: true });
      }
      return;
    }

    if (data.startsWith('yt:start_render:')) {
      const jobId = parseInt(data.split(':')[2], 10);
      if (isNaN(jobId)) {
        await ctx.answerCbQuery('LỖI: Không xác định được tác vụ Job.', { show_alert: true });
        return;
      }
      await ctx.answerCbQuery('Đang đưa tác vụ vào hàng đợi kết xuất.');
      await enqueueMusicReactiveRender(ctx, jobId);
      return;
    }

    if (data.startsWith('yt:start_remix:')) {
      try {
        const jobId = parseInt(data.split(':')[2], 10);
        if (isNaN(jobId)) {
          await ctx.answerCbQuery('LỖI: Không xác định được tác vụ Job.', { show_alert: true });
          return;
        }

        const confirmation = createConfirmation(
          ctx.chat?.id || 'unknown',
          'remix_music',
          `Remix tài nguyên âm thanh cho tác vụ Job #${jobId} theo mẫu đã chọn.\nXác nhận quyền sở hữu và cấp phép bản quyền tệp âm thanh.`,
          { jobId, rightsConfirmed: true },
        );

        await ctx.answerCbQuery('Yêu cầu xác nhận bản quyền tài nguyên.');
        await ctx.reply(
          `❓ XÁC NHẬN YÊU CẦU THỰC THI REMIX YOUTUBE:\n━━━━━━━━━━━━━━━━━━━━━\n${confirmation.summary}`,
          Markup.inlineKeyboard([
            Markup.button.callback('✅ Xác nhận', `yt:confirm:${confirmation.id}`),
            Markup.button.callback('❌ Hủy bỏ', `yt:deny:${confirmation.id}`),
          ]),
        );
      } catch (e: any) {
        await ctx.answerCbQuery(`Lỗi: ${e.message}`, { show_alert: true });
      }
      return;
    }

    if (data.startsWith('yt:show_config:')) {
      const jobId = parseInt(data.split(':')[2], 10);
      if (isNaN(jobId)) {
        await ctx.answerCbQuery('LỖI: Không xác định được tác vụ Job.', { show_alert: true });
        return;
      }
      const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
      if (!job) {
        await ctx.answerCbQuery(`❌ LỖI: Không tìm thấy tác vụ Job #${jobId}.`, { show_alert: true });
        return;
      }
      const metadata = parseMetadata(job.scenes_layout_json);
      await ctx.answerCbQuery('🤖 Đang phân tích và tạo gợi ý AI...');
      const displayText = await buildJobConfigDisplay(jobId, job, metadata, true);
      const renderMode = metadata.render_mode || 'classic_video';
      return ctx.reply(displayText, {
        parse_mode: 'Markdown',
        ...postTemplateKeyboard(jobId, renderMode === 'music_reactive' ? 'render' : 'remix'),
      });
    }

    if (data.startsWith('yt:preview:')) {
      const jobId = parseInt(data.split(':')[2], 10);
      if (isNaN(jobId)) {
        await ctx.answerCbQuery('LỖI: Không xác định được tác vụ Job.', { show_alert: true });
        return;
      }
      await ctx.answerCbQuery();
      return previewYouTubeJob(ctx, jobId);
    }

    if (data.startsWith('yt:retry_publish:')) {
      const jobId = parseInt(data.split(':')[2], 10);
      if (isNaN(jobId)) {
        await ctx.answerCbQuery('Không xác định được Job để đăng lại.', { show_alert: true });
        return;
      }
      try {
        const result = await retryPublishJob(jobId, ctx.chat?.id);
        await ctx.answerCbQuery(result.ok ? 'Đã đưa job vào hàng đợi đăng lại.' : result.reason, { show_alert: !result.ok });
        await ctx.reply(result.ok ? `✅ ${result.reason}` : `❌ ${result.reason}`);
      } catch (error: any) {
        await ctx.answerCbQuery(`Không thể đăng lại: ${error.message}`, { show_alert: true });
      }
      return;
    }

    if (data.startsWith('yt:cancel_job:')) {
      try {
        const jobId = parseInt(data.split(':')[2], 10);
        const confirmation = createConfirmation(
          ctx.chat?.id || 'unknown',
          'cancel_job',
          `Ngừng kích hoạt và hủy bỏ hoàn toàn tác vụ Job #${jobId}. Tác vụ này sẽ không được xử lý hoặc xuất bản.`,
          { jobId },
        );

        await ctx.answerCbQuery('Yêu cầu xác nhận hủy tác vụ.');
        await ctx.reply(
          `❓ XÁC NHẬN YÊU CẦU HỦY TÁC VỤ YOUTUBE:\n━━━━━━━━━━━━━━━━━━━━━\n${confirmation.summary}`,
          Markup.inlineKeyboard([
            Markup.button.callback('✅ Xác nhận', `yt:confirm:${confirmation.id}`),
            Markup.button.callback('❌ Hủy bỏ', `yt:deny:${confirmation.id}`),
          ]),
        );
      } catch (e: any) {
        await ctx.answerCbQuery(`❌ Lỗi: ${e.message}`, { show_alert: true });
      }
      return;
    }

    if (data.startsWith('yt:calendar:')) {
      try {
        const parts = data.split(':');
        const action = parts[2];

        if (action === 'menu') {
          await ctx.answerCbQuery();
          await ctx.replyWithHTML(
            `📅 <b>QUẢN LÝ LỊCH TRÌNH VIDEO YOUTUBE</b>\n` +
            `━━━━━━━━━━━━━━━━━━━━━\n` +
            `Chào mừng bạn đến với trung tâm quản lý lịch trình phát video YouTube. Tại đây bạn có thể kiểm tra danh sách video đã lên lịch, chỉnh sửa tiêu đề hoặc xóa các video cũ theo từng ngày.\n\n` +
            `👇 Hãy chọn một mốc thời gian hoặc hành động bên dưới:`,
            getCalendarMenuKeyboard()
          );
          return;
        }

        if (action === 'date') {
          const dateStr = parts.slice(3).join(':'); // e.g. yt:calendar:date:YYYY-MM-DD
          await ctx.answerCbQuery();
          await renderCalendarDateView(ctx, dateStr);
          return;
        }

        if (action === 'view_7days') {
          await ctx.answerCbQuery();
          const buttons = [];
          for (let i = 0; i < 7; i++) {
            const date = new Date(Date.now() + i * 24 * 60 * 60 * 1000);
            const dateStr = date.toLocaleDateString('sv-SE', { timeZone: 'Asia/Ho_Chi_Minh' });
            const formattedDate = dateStr.split('-').reverse().slice(0, 2).join('/');
            const weekday = i === 0 ? 'Hôm Nay' : i === 1 ? 'Ngày Mai' : `Thứ ${date.getDay() === 0 ? 'CN' : date.getDay() + 1}`;
            buttons.push([Markup.button.callback(`📅 ${weekday} (${formattedDate})`, `yt:calendar:date:${dateStr}`)]);
          }
          buttons.push([Markup.button.callback('⬅️ Về Lịch Trình', 'yt:calendar:menu')]);
          
          await ctx.replyWithHTML(
            `📅 <b>CHỌN NGÀY LÊN LỊCH YOUTUBE (7 NGÀY TỚI)</b>\n` +
            `━━━━━━━━━━━━━━━━━━━━━\n` +
            `Chọn một ngày bên dưới để xem hoặc thêm/sửa/xóa video:`,
            Markup.inlineKeyboard(buttons)
          );
          return;
        }

        if (action === 'custom_input') {
          calendarInputStates.set(chatId, { step: 'awaiting_date' });
          await ctx.answerCbQuery();
          await ctx.replyWithHTML(
            `🔍 <b>NHẬP NGÀY CẦN QUẢN LÝ YOUTUBE</b>\n` +
            `━━━━━━━━━━━━━━━━━━━━━\n` +
            `Vui lòng nhập ngày theo định dạng <b>YYYY-MM-DD</b> (Ví dụ: <code>2026-05-22</code>).\n\n` +
            `👉 <i>Hoặc gõ /calendar để quay lại menu chính.</i>`
          );
          return;
        }

        if (action === 'trend_templates') {
          const suggestedJobId = await getSuggestedJobId();
          await ctx.answerCbQuery();
          return ctx.reply(getTrendingTemplateMessage(suggestedJobId), trendTemplateKeyboard(suggestedJobId));
        }
      } catch (e: any) {
        await ctx.answerCbQuery(`Lỗi: ${e.message}`, { show_alert: true });
      }
      return;
    }

    if (data.startsWith('yt:cal_create:')) {
      try {
        const targetDate = data.split(':')[2];
        campaignWizards.set(chatId, { step: 'awaiting_topic', targetDate });
        await ctx.answerCbQuery();
        await ctx.replyWithHTML(
          `✍️ <b>BƯỚC 1/2: NHẬP CHỦ ĐỀ CHO VIDEO YOUTUBE NGÀY ${targetDate.split('-').reverse().join('/')}</b>\n` +
          `━━━━━━━━━━━━━━━━━━━━━\n` +
          `Hãy gửi tin nhắn nhập chủ đề cho video (Ví dụ: <i>Kinh nghiệm du lịch tự túc</i>, <i>Học tiếng Anh giao tiếp</i>,...)\n\n` +
          `👉 <i>Soạn /cancel hoặc bấm nút bên dưới để hủy bỏ bất kỳ lúc nào.</i>`,
          Markup.inlineKeyboard([
            [Markup.button.callback('❌ Hủy bỏ', 'yt:camp_wizard:cancel')]
          ])
        );
      } catch (e: any) {
        await ctx.answerCbQuery(`Lỗi: ${e.message}`, { show_alert: true });
      }
      return;
    }

    if (data.startsWith('yt:cal_edit:')) {
      try {
        const jobId = parseInt(data.split(':')[2], 10);
        if (isNaN(jobId)) {
          await ctx.answerCbQuery('Lỗi: Mã công việc không hợp lệ.', { show_alert: true });
          return;
        }

        calendarEditStates.set(chatId, { jobId });
        await ctx.answerCbQuery();
        await ctx.replyWithHTML(
          `✏️ <b>SỬA TIÊU ĐỀ VIDEO YOUTUBE JOB #${jobId}</b>\n` +
          `━━━━━━━━━━━━━━━━━━━━━\n` +
          `Vui lòng soạn và gửi tin nhắn chứa tiêu đề mới cho video này.\n\n` +
          `👉 <i>Hoặc gõ /calendar để quay lại menu chính.</i>`
        );
      } catch (e: any) {
        await ctx.answerCbQuery(`Lỗi: ${e.message}`, { show_alert: true });
      }
      return;
    }

    if (data.startsWith('yt:cal_delete:')) {
      try {
        const jobId = parseInt(data.split(':')[2], 10);
        if (isNaN(jobId)) {
          await ctx.answerCbQuery('Lỗi: Mã công việc không hợp lệ.', { show_alert: true });
          return;
        }

        const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
        if (!job) {
          await ctx.answerCbQuery('Lỗi: Không tìm thấy Video Job này trong cơ sở dữ liệu.', { show_alert: true });
          return;
        }

        const confirmation = createConfirmation(
          ctx.chat?.id || 'unknown',
          'cal_delete',
          `Xác nhận xóa Video Job #${jobId} (${job.video_title_idea || 'Không có tiêu đề'}) khỏi cơ sở dữ liệu.`,
          { jobId }
        );

        await ctx.answerCbQuery('Yêu cầu xác nhận xóa Video Job.');
        await ctx.reply(
          `❓ <b>XÁC NHẬN YÊU CẦU XÓA VIDEO JOB YOUTUBE #${jobId}</b>:\n━━━━━━━━━━━━━━━━━━━━━\n${confirmation.summary}`,
          Markup.inlineKeyboard([
            Markup.button.callback('✅ Xác nhận', `yt:confirm:${confirmation.id}`),
            Markup.button.callback('❌ Hủy bỏ', `yt:deny:${confirmation.id}`),
          ])
        );
      } catch (e: any) {
        await ctx.answerCbQuery(`Lỗi: ${e.message}`, { show_alert: true });
      }
      return;
    }

    if (data.startsWith('yt:confirm:')) {
      const confirmation = consumeConfirmation(data.split(':')[2]);
      if (!confirmation) return ctx.answerCbQuery('Xác nhận đã hết hạn.', { show_alert: true });
      const result = await executeConfirmedAction(confirmation.action, confirmation.payload);
      await ctx.answerCbQuery('Đã xác nhận.');
      return ctx.reply(result);
    }
    if (data.startsWith('yt:deny:')) {
      cancelConfirmation(data.split(':')[2]);
      await ctx.answerCbQuery('Đã hủy.');
      return ctx.reply('Đã hủy yêu cầu đăng YouTube.');
    }
  } catch (error: any) {
    console.error('[YouTube Bot] Callback error:', error);
    await ctx.answerCbQuery(`Lỗi: ${error.message}`, { show_alert: true });
  }
});
