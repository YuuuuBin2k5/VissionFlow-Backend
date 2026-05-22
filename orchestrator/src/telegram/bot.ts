import { Telegraf, Markup } from 'telegraf';
import dotenv from 'dotenv';
import prisma from '../database/db';
import { addJobToQueue, tiktokQueue } from '../queue/queue';
import { parseBotIntent } from './intentRouter';
import {
  auditBotAction,
  buildActionSummary,
  executeConfirmedAction,
  formatDateTime,
  getJobDetails,
  getPendingApprovalReport,
  getRecommendation,
  getScheduleReport,
  getStatusReport,
  parseScheduleTime,
  resolveJobId,
} from './botActions';
import { cancelConfirmation, consumeConfirmation, createConfirmation } from './confirmationStore';
import * as fs from 'fs';
import * as path from 'path';

dotenv.config();

function escapeHtml(unsafe: string): string {
  return unsafe
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

const token = process.env.TELEGRAM_BOT_TOKEN;
if (!token || token === 'YOUR_TELEGRAM_BOT_TOKEN_HERE') {
  console.warn('[Telegram Bot] WARNING: TELEGRAM_BOT_TOKEN is not configured in .env. Bot will not start.');
}

export const bot = new Telegraf(token || '');

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
const GEMINI_MODEL_CANDIDATES = [
  process.env.GEMINI_MODEL,
  process.env.GOOGLE_GEMINI_MODEL,
  'gemini-2.0-flash',
  'gemini-2.5-flash',
  'gemini-1.5-flash-latest',
  'gemini-1.5-flash',
].filter(Boolean) as string[];
const AMBIGUOUS_MUSIC_TITLE_NORMALIZED = new Set([
  'tunglacuaanhau',
]);

const controlCenterKeyboard = Markup.inlineKeyboard([
  [
    Markup.button.callback('Trạng thái', 'quick:status'),
    Markup.button.callback('Lịch hôm nay', 'quick:schedule_today'),
  ],
  [
    Markup.button.callback('Lịch tuần', 'quick:schedule_week'),
    Markup.button.callback('Chờ duyệt', 'quick:pending'),
  ],
  [
    Markup.button.callback('Mẫu thao tác', 'quick:templates'),
    Markup.button.callback('Mẫu trend', 'quick:trend_templates'),
  ],
  [
    Markup.button.callback('Đề xuất', 'quick:recommend'),
  ],
]);

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

interface CampaignWizardState {
  step: 'awaiting_topic' | 'awaiting_target';
  topic?: string;
  target?: string;
  targetDate?: 'today' | 'tomorrow' | string;
}

const campaignWizards = new Map<number, CampaignWizardState>();
const calendarEditStates = new Map<number, { jobId: number }>();
const calendarInputStates = new Map<number, { step: 'awaiting_date' }>();

interface ActiveCreationSession {
  chatId: number;
  kind: 'single_video' | 'music_video' | 'render_music' | 'campaign';
  title: string;
  subtitle: string;
  jobId?: number;
  campaignId?: number;
  messageId?: number;
  startedAt: number;
  timer?: NodeJS.Timeout;
}

const activeCreationSessions = new Map<number, ActiveCreationSession>();

function isCancelRequest(text: string) {
  const normalized = text.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd').trim();
  return ['/cancel', 'cancel', 'huy', 'huy thao tac', 'dung lai', 'stop'].includes(normalized);
}

function cancelOnlyKeyboard(session: ActiveCreationSession) {
  const target = session.jobId ? String(session.jobId) : 'pending';
  return Markup.inlineKeyboard([
    [Markup.button.callback('Hủy thao tác', `cancel_active:${target}:${session.chatId}`)],
  ]);
}

function resolveProgressPercent(state?: string, latestStep?: string) {
  const key = `${state || ''} ${latestStep || ''}`.toUpperCase();
  if (key.includes('FAILED') || key.includes('QUALITY_FAILED')) return 100;
  if (key.includes('PUBLISHED') || key.includes('RENDERED_SUBTITLED') || key.includes('RENDER_SUCCESS')) return 100;
  if (key.includes(MUSIC_AUDIO_WAITING_STATE)) return 18;
  if (key.includes('QUALITY_CHECK')) return 90;
  if (key.includes('STREAM_RENDERING') || key.includes('VIDEO_RENDER')) return 76;
  if (key.includes('WEB_DOM_BUILD') || key.includes('ASSETS_READY')) return 62;
  if (key.includes('SIGNAL_PROCESSING') || key.includes('AUDIO_COMPOSED')) return 45;
  if (key.includes('AI_CREATIVE') || key.includes('AI_PARSED') || key.includes('LLM_SCRIPT')) return 32;
  if (key.includes('AI_PROCESSING')) return 22;
  if (key.includes('QUEUED') || key.includes('START')) return 12;
  return 6;
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
    }
  }

  const percent = resolveProgressPercent(state, latestStep);
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
  const percent = session.jobId ? resolveProgressPercent(
    (await prisma.videoPipelineJobs.findUnique({ where: { id: session.jobId } }))?.pipeline_state,
    (await prisma.processRealtimeLogs.findFirst({ where: { job_id: session.jobId }, orderBy: { logged_at: 'desc' } }))?.execution_step,
  ) : 6;

  const isTerminal = percent >= 100;
  try {
    await bot.telegram.editMessageText(
      session.chatId,
      session.messageId,
      undefined,
      text,
      {
        parse_mode: 'HTML',
        ...(isTerminal ? {} : cancelOnlyKeyboard(session)),
      },
    );
  } catch (error: any) {
    const message = String(error?.message || '');
    if (!message.includes('message is not modified')) {
      console.warn('[Telegram Bot] Failed to refresh progress card:', message);
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
  activeSession.timer = setInterval(() => refreshActiveOperation(activeSession).catch(console.error), 5000);
  return activeSession;
}

function stopActiveOperation(chatId: number) {
  const session = activeCreationSessions.get(chatId);
  if (session?.timer) clearInterval(session.timer);
  activeCreationSessions.delete(chatId);
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

async function removeQueuedBullJobs(jobId: number) {
  for (const type of ['PLANNING', 'RENDER', 'PUBLISH']) {
    const queueJob = await tiktokQueue.getJob(`${type}_${jobId}`);
    if (!queueJob) continue;

    const state = await queueJob.getState();
    if (['waiting', 'delayed', 'prioritized', 'failed', 'completed', 'waiting-children'].includes(state)) {
      try {
        await queueJob.remove();
      } catch (error) {
        console.warn(`[Telegram Bot] Could not remove ${type}_${jobId} from queue:`, error);
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
  await auditBotAction(jobId, 'BOT_CANCEL_ACTIVE', 'SUCCESS', 'User cancelled active creation operation.');

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
  if (job.pipeline_state === 'PUBLISHED') {
    return { ok: false, reason: `Job #${jobId} đã đăng thành công trước đó.` };
  }

  await removeQueuedBullJobs(jobId);
  await prisma.videoPipelineJobs.update({
    where: { id: jobId },
    data: {
      pipeline_state: 'PUBLISH_QUEUED',
      error_log_trace: null,
    },
  });
  await addJobToQueue(jobId, 'PUBLISH');
  await auditBotAction(jobId, 'BOT_RETRY_PUBLISH', 'INFO', `User retried publish for job #${jobId}.`);
  return { ok: true, reason: `Đã đưa Job #${jobId} vào hàng đợi đăng lại.` };
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
  await auditBotAction(job.id, 'BOT_MUSIC_IMAGE_UPLOAD', 'SUCCESS', `Received user portrait image for music video Job #${job.id}.`);
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
    `▪️ Đang lưu file và đưa vào hàng đợi render...`,
  );

  await downloadTelegramFile(ctx, payload.fileId, outputPath);
  metadata.audio_path = outputPath;
  metadata.user_audio_path = outputPath;
  metadata.requires_user_audio = true;
  metadata.auto_select_viral_segment = true;
  metadata.render_audio_source = 'provided_audio';
  metadata.visual_mode = metadata.visual_mode || 'auto';
  metadata.user_wants_custom_image = metadata.user_wants_custom_image ?? false;

  await prisma.videoPipelineJobs.update({
    where: { id: job.id },
    data: {
      audio_file_path: outputPath,
      scenes_layout_json: JSON.stringify(metadata),
      pipeline_state: 'QUEUED',
      error_log_trace: null,
    },
  });
  await addJobToQueue(job.id, 'RENDER');
  await auditBotAction(job.id, 'BOT_MUSIC_AUDIO_UPLOAD', 'SUCCESS', `Received user audio file for music video Job #${job.id}.`);

  const activeSession = activeCreationSessions.get(chatId);
  if (activeSession) {
    activeSession.jobId = job.id;
    activeSession.subtitle = job.video_title_idea || activeSession.subtitle;
    await refreshActiveOperation(activeSession);
  }

  await ctx.replyWithHTML(
    `🎧 <b>Bắt đầu phân tích nhạc</b>\n` +
    `Hệ thống sẽ tự chọn khúc viral, cắt đoạn hay và render chữ động đồng bộ theo nhạc.`,
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

function parseMetadata(raw: any): Record<string, any> {
  try {
    const parsed = raw && typeof raw === 'string' ? JSON.parse(raw) : raw || {};
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function isAutoMusicValue(value?: string | null) {
  const normalized = String(value || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd')
    .trim();
  return !normalized || [
    'hot trending',
    'auto detect',
    'tu dong phat hien',
    'tu dong san tim trend',
    'video am nhac xu huong',
  ].includes(normalized);
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
    const prompt = hasSpecificTitle && !hasSpecificArtist ? `
Bạn là giám đốc dữ liệu âm nhạc Việt Nam.
Người dùng đã cung cấp TÊN BÀI HÁT CỐ ĐỊNH. Bạn chỉ được tìm/điền đúng ca sĩ hoặc nghệ sĩ của bài đó.
TUYỆT ĐỐI KHÔNG đổi sang bài hát khác.

ĐẦU VÀO:
- Tên bài cố định: "${songTitle}"
- Ca sĩ hiện tại: "${artistName}"

ĐẦU RA JSON DUY NHẤT:
{"song_title":"${songTitle.replace(/"/g, '\\"')}","artist_name":"Ca sĩ cụ thể của đúng bài này","mood":"SAD_RAIN|CYBERPUNK_NIGHT|COZY_CHILL|FOCUS_LOFI","confidence":0.0,"ambiguous":false,"candidates":[]}

Nếu tên bài có nhiều ca sĩ/phiên bản phổ biến hoặc bạn không chắc trên 90%, bắt buộc trả:
{"song_title":"${songTitle.replace(/"/g, '\\"')}","artist_name":"","mood":"COZY_CHILL","confidence":0.0,"ambiguous":true,"candidates":["Tên bài - Ca sĩ 1","Tên bài - Ca sĩ 2"]}
` : `
Bạn là giám đốc âm nhạc TikTok Việt Nam.
Hãy chọn đúng 1 bài nhạc Việt/TikTok trend cụ thể để người dùng có thể tự cung cấp file audio.
Nếu đã có tên bài nhưng thiếu ca sĩ, hãy điền ca sĩ phù hợp.

ĐẦU VÀO:
- Tên bài: "${songTitle}"
- Ca sĩ: "${artistName}"

ĐẦU RA JSON DUY NHẤT:
{"song_title":"Tên bài cụ thể","artist_name":"Ca sĩ cụ thể","mood":"SAD_RAIN|CYBERPUNK_NIGHT|COZY_CHILL|FOCUS_LOFI","confidence":0.0,"ambiguous":false,"candidates":[]}
`;
    let raw = '';
    const errors: string[] = [];
    for (const model of GEMINI_MODEL_CANDIDATES) {
      const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;
      try {
        const response = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            contents: [{ parts: [{ text: prompt }] }],
            generationConfig: { temperature: 0.55, responseMimeType: 'application/json' },
          }),
        });
        if (!response.ok) {
          errors.push(`${model}: ${response.status}`);
          continue;
        }
        const data: any = await response.json();
        raw = data?.candidates?.[0]?.content?.parts?.[0]?.text || '';
        if (raw) break;
        errors.push(`${model}: empty response`);
      } catch (modelError: any) {
        errors.push(`${model}: ${modelError.message}`);
      }
    }
    if (!raw) {
      throw new Error(`Không model Gemini nào phản hồi hợp lệ (${errors.join('; ')}).`);
    }
    const parsed = raw ? JSON.parse(raw.trim()) : null;
    const resolvedTitle = String(parsed?.song_title || '').trim();
    const resolvedArtist = String(parsed?.artist_name || '').trim();
    const confidence = Number(parsed?.confidence ?? 0.75);
    const ambiguous = parsed?.ambiguous === true || parsed?.needs_artist === true;
    if (hasSpecificTitle && !hasSpecificArtist && (ambiguous || confidence < 0.9)) {
      const candidates = Array.isArray(parsed?.candidates) && parsed.candidates.length
        ? ` Gợi ý đang mơ hồ: ${parsed.candidates.slice(0, 3).join('; ')}.`
        : '';
      throw new Error(`${buildArtistRequiredError(songTitle)}${candidates}`);
    }
    if (!resolvedTitle || !resolvedArtist || isAutoMusicValue(resolvedTitle) || isAutoMusicValue(resolvedArtist)) {
      throw new Error('Gemini không trả về được tên bài hát và ca sĩ cụ thể.');
    }
    if (hasSpecificTitle && normalizeMusicText(resolvedTitle) !== normalizeMusicText(songTitle)) {
      throw new Error(`Gemini đã đổi bài hát từ "${songTitle}" sang "${resolvedTitle}", nên hệ thống đã dừng để tránh sai file.`);
    }
    return {
      songTitle: hasSpecificTitle ? songTitle : resolvedTitle,
      artistName: resolvedArtist,
      mood: parsed?.mood || 'COZY_CHILL',
    };
  } catch (error: any) {
    throw new Error(`Không thể tự chọn bài hát cụ thể bằng Gemini: ${error.message}. Vui lòng nhập rõ theo mẫu /music_video Tên bài | Ca sĩ.`);
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

function getControlCenterMessage() {
  return (
    `BẢNG ĐIỀU KHIỂN HỆ THỐNG\n` +
    `──────────────────────────────\n` +
    `Chọn phím chức năng bên dưới hoặc gửi yêu cầu bằng ngôn ngữ tự nhiên.\n\n` +
    `Ví dụ yêu cầu:\n` +
    `• "Xem lịch hôm nay"\n` +
    `• "Video nào đang chờ duyệt"\n` +
    `• "Remix nhạc job 31 phong cách deep house"\n` +
    `• "Dời job 31 sang 20:00 tối mai"\n\n` +
    `Các lệnh chuẩn hóa:\n` +
    `• /templates - Xem hướng dẫn mẫu thao tác nâng cao\n` +
    `• /job_config <job_id> - Xem cấu hình tác vụ\n` +
    `• /set_job_config <job_id> key=value; - Sửa cấu hình tác vụ`
  );
}

function getTemplateMessage() {
  return (
    `HƯỚNG DẪN THAO TÁC HỆ THỐNG\n` +
    `──────────────────────────────\n` +
    `PHÂN HỆ VẬN HÀNH\n` +
    `• /schedule today - Xem lịch đăng hôm nay\n` +
    `• /schedule week - Xem lịch đăng tuần này\n` +
    `• /pending - Xem hàng đợi video chờ duyệt\n` +
    `• /status - Xem trạng thái hệ thống\n\n` +
    `PHÂN HỆ BIÊN TẬP & RENDER\n` +
    `• Bấm "Mẫu trend" để áp dụng cấu hình/remix cho tác vụ.\n` +
    `• Sau khi chọn mẫu, hệ thống sẽ gửi nút xác nhận thực thi.\n\n` +
    `THIẾT LẬP CẤU HÌNH & LỊCH ĐĂNG\n` +
    `• /job_config <job_id> - Xem thông số Job\n` +
    `• /set_job_config <job_id> key=value; - Cập nhật thông số Job\n` +
    `  (Ví dụ: /set_job_config 31 mood=FOCUS_LOFI; bpm=120)\n` +
    `• /reschedule <job_id> YYYY-MM-DD HH:mm - Thay đổi lịch cụ thể\n` +
    `  (Ví dụ: /reschedule 31 2026-05-22 19:30)`
  );
}

function getTrendingTemplateMessage(jobId: number | null = null) {
  const targetText = jobId ? `Tác vụ: Job #${jobId}` : 'Khởi tạo tác vụ mới';
  return (
    `DANH SÁCH MẪU XU HƯỚNG (${targetText})\n` +
    `──────────────────────────────\n` +
    Object.values(TREND_PRESETS).map((preset) => (
      `• ${preset.label}: ${preset.description}`
    )).join('\n') +
    `\n\n` +
    (jobId
      ? `Hành động: Chọn một mẫu bên dưới để áp cấu hình, sau đó xác nhận thực thi.`
      : `[!] Không tìm thấy tác vụ phù hợp để áp cấu hình. Chọn mẫu dưới đây để tạo một tác vụ mới đưa vào hàng đợi Render.`)
  );
}

function trendTemplateKeyboard(jobId: number | null) {
  const callback = (presetKey: string) => jobId ? `tpl:${presetKey}:${jobId}` : `create_tpl:${presetKey}`;
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
      Markup.button.callback('Video chờ duyệt', 'quick:pending'),
      Markup.button.callback('Trạng thái', 'quick:status'),
    ],
  ]);
}

function postTemplateKeyboard(jobId: number, mode: 'remix' | 'render' = 'remix') {
  return Markup.inlineKeyboard([
    [
      mode === 'render'
        ? Markup.button.callback('Render ngay', `start_render:${jobId}`)
        : Markup.button.callback('Remix ngay', `start_remix:${jobId}`),
      Markup.button.callback('Xem config', `show_config:${jobId}`),
    ],
    [
      Markup.button.callback('Xem Preview', `preview:${jobId}`),
      Markup.button.callback('Mẫu khác', 'quick:trend_templates'),
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
    metadata.artist_name = metadata.artist_name || 'AgentTiktok';
    metadata.mood = metadata.mood || metadata.music_mood || 'FOCUS_LOFI';
  } else {
    const preset = TREND_PRESETS[presetKey];
    if (!preset) throw new Error('Mẫu trend không hợp lệ.');
    Object.assign(metadata, preset.updates);
    metadata.render_mode = 'music_remix_reactive';
    metadata.audio_path = metadata.audio_path || job.audio_file_path;
    metadata.source_audio_path = metadata.source_audio_path || metadata.audio_path || job.audio_file_path;
    metadata.song_title = metadata.song_title || job.video_title_idea || `Job #${jobId}`;
    metadata.artist_name = metadata.artist_name || 'AgentTiktok Remix';
  }

  await prisma.videoPipelineJobs.update({
    where: { id: jobId },
    data: { scenes_layout_json: JSON.stringify(metadata) },
  });
  await auditBotAction(jobId, 'BOT_TREND_PRESET', 'SUCCESS', `Applied trend preset ${presetKey} to job #${jobId}.`);
  return metadata;
}

async function createVideoFromTrendTemplate(chatId: number | string, presetKey: string) {
  const preset = TREND_PRESETS[presetKey] || TREND_PRESETS.trend_bass;
  const scheduled = new Date(Date.now() + 24 * 60 * 60 * 1000);
  const telegramChatId = typeof chatId === 'number' || /^\d+$/.test(String(chatId)) ? BigInt(chatId) : BigInt(0);
  const campaign = await prisma.channelsCampaign.create({
    data: {
      telegram_chat_id: telegramChatId,
      topic: `${preset.label} TikTok video`,
      target_audience: 'Người xem TikTok thích nội dung kiến thức, chill và trend audio-reactive',
      status: 'RUNNING',
    },
  });

  const metadata = {
    ...preset.updates,
    render_mode: 'classic_video',
    desired_next_render_mode: 'music_remix_reactive',
    selected_template: presetKey,
    music_mood: preset.updates.mood,
    content_category: 'music_trend_template',
    primary_goal: 'VIEWS',
    concept_description: preset.description,
  };

  const job = await prisma.videoPipelineJobs.create({
    data: {
      campaign_id: campaign.id,
      day_number: 1,
      scheduled_post_time: scheduled,
      video_title_idea: `${preset.label} - video TikTok tự động`,
      scenes_layout_json: JSON.stringify(metadata),
      pipeline_state: 'QUEUED',
    },
  });

  await addJobToQueue(job.id, 'RENDER');
  await auditBotAction(job.id, 'BOT_TEMPLATE_CREATE', 'SUCCESS', `Created and queued video from preset ${presetKey}.`);
  return job;
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
    render_music:
      `[!] Không thể thực thi lệnh Render Audio do: ${reason}.\n\n` +
      `Vui lòng cung cấp mã Job ID cụ thể.\n` +
      `Cú pháp:\n` +
      `/render_music ${jobHint}\n` +
      `Hoặc: "render job ${jobHint} kiểu music reactive"`,
    remix_music:
      `[!] Không thể thực thi lệnh Remix Audio do: ${reason}.\n\n` +
      `Vui lòng chọn một mẫu cấu hình phù hợp bên dưới và xác nhận quyền sở hữu:`,
    preview:
      `[!] Vui lòng cung cấp mã Job ID để xem trước.\n\n` +
      `Cú pháp:\n` +
      `/preview ${jobHint}\n` +
      `Hoặc: "xem video job ${jobHint}"`,
    logs:
      `[!] Vui lòng cung cấp mã Job ID để xem nhật ký.\n\n` +
      `Cú pháp:\n` +
      `/logs ${jobHint}\n` +
      `Hoặc: "xem tiến độ job ${jobHint}"`,
    force_post:
      `[!] Vui lòng cung cấp mã Job ID để đăng ngay.\n\n` +
      `Cú pháp:\n` +
      `/force_post ${jobHint}`,
    reschedule:
      `[!] Vui lòng cung cấp mã Job ID và thời gian mới.\n\n` +
      `Cú pháp:\n` +
      `/reschedule ${jobHint} 2026-05-22 19:30\n` +
      `Hoặc: "dời job ${jobHint} sang 22h tối nay"`,
    job_config:
      `[!] Vui lòng cung cấp mã Job ID để xem cấu hình.\n\n` +
      `Cú pháp:\n` +
      `/job_config ${jobHint}`,
    set_job_config:
      `[!] Vui lòng cung cấp mã Job ID và các cặp thông số (key=value).\n\n` +
      `Cú pháp:\n` +
      `/set_job_config ${jobHint} remix_style=trend_bass; mood=CYBERPUNK_NIGHT; bpm=128\n\n` +
      `Các khóa cấu hình: ${Array.from(JOB_CONFIG_KEYS).join(', ')}`,
    start_campaign:
      `[!] Vui lòng cung cấp chủ đề và đối tượng mục tiêu.\n\n` +
      `Cú pháp:\n` +
      `/startcampaign Chủ đề | Đối tượng mục tiêu\n` +
      `Hoặc gõ /startcampaign để chọn mẫu chiến dịch có sẵn.`,
    viral_script:
      `[!] Vui lòng cung cấp chủ đề kênh và nội dung kịch bản gốc.\n\n` +
      `Cú pháp:\n` +
      `/viral_script Chủ đề | Kịch bản gốc`,
    campaign:
      `[!] Vui lòng cung cấp mã Campaign ID.\n\n` +
      `Cú pháp:\n` +
      `/pause_campaign 1\n` +
      `/resume_campaign 1\n` +
      `/cancel_campaign 1`,
    hooks:
      `[!] Vui lòng cung cấp chủ đề để tạo hook.\n\n` +
      `Cú pháp:\n` +
      `/hooks Chủ đề`,
  };

  const keyboard = command === 'remix_music' || command === 'set_job_config'
    ? trendTemplateKeyboard(jobId)
    : Markup.inlineKeyboard([
      [
        Markup.button.callback('Video chờ duyệt', 'quick:pending'),
        Markup.button.callback('Mẫu trend', 'quick:trend_templates'),
      ],
      [
        Markup.button.callback('Trạng thái', 'quick:status'),
        Markup.button.callback('Lịch hôm nay', 'quick:schedule_today'),
      ],
    ]);

  await ctx.reply(guideByCommand[command] || getTemplateMessage(), keyboard);
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

// Global error handling
bot.catch((err: any, ctx) => {
  console.error(`[Telegram Bot Error] Error for ${ctx.updateType}:`, err);
  try {
    ctx.reply(`🚨 THÔNG BÁO LỖI HỆ THỐNG: ${err.message || err}`);
  } catch (replyErr) {
    console.error('[Telegram Bot Error] Failed to send error reply:', replyErr);
  }
});

// Middleware logging
bot.use(async (ctx, next) => {
  const start = Date.now();
  await next();
  const ms = Date.now() - start;
  console.log(`[Telegram Bot] Processed update in ${ms}ms`);
});

// Chào mừng người dùng
bot.use(async (ctx, next) => {
  const chatId = ctx.chat?.id;
  if (!chatId) return next();

  const activeSession = activeCreationSessions.get(chatId);
  if (!activeSession) return next();

  const callbackData = (ctx.callbackQuery as any)?.data;
  if (callbackData?.startsWith('cancel_active:') || callbackData?.startsWith('music_visual:')) return next();

  if (ctx.callbackQuery) {
    await ctx.answerCbQuery('Hệ thống đang tạo nội dung. Chat tạm khóa, chỉ có thể hủy thao tác hiện tại.', { show_alert: true });
    return;
  }

  const message = ctx.message as any;
  if (message?.audio || message?.document || message?.photo) {
    const waitingJob = await findWaitingMusicAudioJob(chatId);
    if (waitingJob) return next();
    await ctx.replyWithHTML(
      `Phiên tạo đang chạy nên chat tạm khóa.\n` +
      `Bạn có thể hủy thao tác hiện tại bằng nút bên dưới.`,
      cancelOnlyKeyboard(activeSession),
    );
    return;
  }

  const text = (ctx.message as any)?.text;
  if (typeof text === 'string') {
    if (isCancelRequest(text)) {
      await cancelActiveOperation(ctx, activeSession);
      return;
    }
    await ctx.replyWithHTML(
      `Phiên tạo đang chạy nên chat tạm khóa.\n` +
      `Bạn có thể hủy thao tác hiện tại bằng nút bên dưới.`,
      cancelOnlyKeyboard(activeSession),
    );
    return;
  }

  await ctx.replyWithHTML(
    `Phiên tạo đang chạy nên chat tạm khóa.\n` +
    `Bạn có thể hủy thao tác hiện tại bằng nút bên dưới.`,
    cancelOnlyKeyboard(activeSession),
  );
});

bot.start((ctx) => {
  ctx.replyWithHTML(
    `🤖 <b>HỆ THỐNG AI ORCHESTRATOR - TỰ ĐỘNG HÓA KÊNH TIKTOK</b>\n` +
    `──────────────────────────────\n` +
    `Chào mừng đến với trung tâm vận hành. Hệ thống hoạt động theo quy trình 3 bước (SOP) rõ ràng:\n\n` +
    `<b>BƯỚC 1: KHỞI TẠO (INPUT)</b>\n` +
    `• /startcampaign - Khởi chạy chiến dịch tự động 30 ngày\n` +
    `• /music_video &lt;Tên bài hát&gt; | &lt;Ca sĩ&gt; - Tạo video WebGL độc lập (Săn trend nếu trống)\n\n` +
    `<b>BƯỚC 2: QUẢN LÝ &amp; TÙY CHỈNH (CONTROL)</b>\n` +
    `• /status - Xem hiện trạng vận hành kênh\n` +
    `• /schedule - Tra cứu lịch đăng hôm nay hoặc tuần này\n` +
    `• /pending - Xem danh sách video chờ duyệt đăng\n` +
    `• /job_config &lt;job_id&gt; - Xem thông số sáng tạo &amp; đề xuất AI\n` +
    `• /set_job_config &lt;job_id&gt; key=value; - Cập nhật thủ công cấu hình Job\n` +
    `• /logs &lt;job_id&gt; - Nhật ký tiến trình tác vụ\n\n` +
    `<b>BƯỚC 3: PHÊ DUYỆT &amp; ĐĂNG TẢI (PUBLISH)</b>\n` +
    `• /preview &lt;job_id&gt; - Xem thử và phê duyệt đăng tải\n` +
    `• /force_post &lt;job_id&gt; - Yêu cầu xuất bản ngay lập tức\n\n` +
    `<b>CÔNG CỤ BỔ TRỢ SÁNG TẠO:</b>\n` +
    `• /hooks &lt;Chủ đề&gt; - Tạo ngân hàng 20 câu hook theo nhóm cảm xúc\n` +
    `• /analyze_viral - Công cụ phân tích cấu trúc &amp; tái tạo kịch bản\n\n` +
    `ℹ️ Bấm phím chức năng dưới đây để mở Bảng điều khiển trực quan tương tác ngay!`,
    Markup.inlineKeyboard([
      [
        Markup.button.callback('🎮 Mở Bảng Điều Khiển', 'quick:menu'),
        Markup.button.callback('📊 Trạng thái', 'quick:status'),
      ],
      [
        Markup.button.callback('📅 Lịch hôm nay', 'quick:schedule_today'),
        Markup.button.callback('⏳ Video chờ duyệt', 'quick:pending'),
      ]
    ])
  );
});

bot.help((ctx) => {
  ctx.replyWithHTML(
    `🤖 <b>QUY TRÌNH VẬN HÀNH 3 BƯỚC (SOP)</b>\n` +
    `──────────────────────────────\n` +
    `<b>BƯỚC 1: KHỞI TẠO (INPUT)</b>\n` +
    `• /startcampaign - Khởi chạy chiến dịch tự động 30 ngày\n` +
    `• /music_video &lt;Tên bài hát&gt; | &lt;Ca sĩ&gt; - Tạo video WebGL độc lập (Săn trend nếu trống)\n\n` +
    `<b>BƯỚC 2: QUẢN LÝ &amp; TÙY CHỈNH (CONTROL)</b>\n` +
    `• /status - Xem hiện trạng vận hành kênh\n` +
    `• /schedule - Tra cứu lịch đăng hôm nay hoặc tuần này\n` +
    `• /pending - Xem danh sách video chờ duyệt đăng\n` +
    `• /job_config &lt;job_id&gt; - Xem thông số sáng tạo &amp; đề xuất AI\n` +
    `• /set_job_config &lt;job_id&gt; key=value; - Cập nhật thủ công cấu hình Job\n` +
    `• /logs &lt;job_id&gt; - Nhật ký tiến trình tác vụ\n\n` +
    `<b>BƯỚC 3: PHÊ DUYỆT &amp; ĐĂNG TẢI (PUBLISH)</b>\n` +
    `• /preview &lt;job_id&gt; - Xem thử và phê duyệt đăng tải\n` +
    `• /force_post &lt;job_id&gt; - Yêu cầu xuất bản ngay lập tức\n\n` +
    `<b>CÔNG CỤ BỔ TRỢ SÁNG TẠO:</b>\n` +
    `• /hooks &lt;Chủ đề&gt; - Tạo ngân hàng 20 câu hook theo nhóm cảm xúc\n` +
    `• /analyze_viral - Công cụ phân tích cấu trúc &amp; tái tạo kịch bản`
  );
});

bot.command('menu', async (ctx) => {
  await ctx.reply(getControlCenterMessage(), controlCenterKeyboard);
});

bot.command('templates', async (ctx) => {
  await ctx.reply(getTemplateMessage(), controlCenterKeyboard);
});

// Lệnh: /hooks [Chủ đề]
bot.command('hooks', async (ctx) => {
  try {
    const topic = ctx.message.text.substring(6).trim();
    if (!topic) {
      return replyCommandGuidance(ctx, 'hooks', 'chủ đề trống');
    }

    await ctx.reply(`[i] Đang khởi tạo và xây dựng cơ sở dữ liệu 20 cấu trúc Hook cho chủ đề: "${topic}"...\n(Thời gian xử lý dự kiến: 15-30 giây)`);

    // Gọi Python Worker để sinh Hook Bank
    const { spawn } = require('child_process');
    const path = require('path');
    const fs = require('fs');
    const scriptPath = path.resolve(__dirname, '../../../worker/main.py');

    const projectRoot = path.resolve(__dirname, '../../..');
    const venvPythonPathWin = path.resolve(projectRoot, 'venv/Scripts/python.exe');
    const venvPythonPathUnix = path.resolve(projectRoot, 'venv/bin/python');
    
    let pythonExecutable = 'python';
    if (fs.existsSync(venvPythonPathWin)) {
      pythonExecutable = venvPythonPathWin;
      console.log(`[Bot Hooks] Using Windows virtualenv Python: ${pythonExecutable}`);
    } else if (fs.existsSync(venvPythonPathUnix)) {
      pythonExecutable = venvPythonPathUnix;
      console.log(`[Bot Hooks] Using Unix virtualenv Python: ${pythonExecutable}`);
    }

    // Tạm thời dùng subprocess đơn giản để gọi hook generator
    // (Thực tế sẽ được tích hợp vào queue, dùng trực tiếp ở đây cho tốc độ nhanh)
    const pythonProcess = spawn(pythonExecutable, [
      '-c',
      `
import sys
sys.path.append('${path.resolve(__dirname, '../../..').replace(/\\/g, '/')}')
from worker.services.llm_service import LLMService
import json
svc = LLMService()
hooks = svc.generate_hook_bank("${topic.replace(/"/g, '\\"')}", "Người dùng TikTok", 20)
print(json.dumps(hooks, ensure_ascii=False))
`
    ]);

    let output = '';
    pythonProcess.stdout.on('data', (data: Buffer) => { output += data.toString(); });

    await new Promise((resolve) => pythonProcess.on('close', resolve));

    try {
      const hooks = JSON.parse(output.trim());

      let message = `CƠ SỞ DỮ LIỆU HOOK - CHỦ ĐỀ "${topic.toUpperCase()}"\n──────────────────────────────\n`;
      const grouped: Record<string, string[]> = {};
      for (const h of hooks) {
        if (!grouped[h.style]) grouped[h.style] = [];
        grouped[h.style].push(h.hook);
      }
      for (const [style, list] of Object.entries(grouped)) {
        message += `\n🎯 *Style: ${style}*\n`;
        for (const h of list) {
          message += `• ${h}\n`;
        }
      }
      await ctx.reply(message);
    } catch (parseErr) {
      await ctx.reply('❌ Lỗi phân tích kết quả hook. Hãy thử lại sau.');
    }
  } catch (error: any) {
    ctx.reply(`❌ Lỗi: ${error.message}`);
  }
});

// Lệnh: /analyze_viral
bot.command('analyze_viral', async (ctx) => {
  try {
    const text = ctx.message.text.substring(14).trim(); // Bỏ qua '/analyze_viral'
    if (!text || !text.includes('|')) {
      return replyCommandGuidance(ctx, 'analyze_viral', 'phân tách cú pháp không chính xác (thiếu dấu | giữa kịch bản và chủ đề mới)');
    }
    const parts = text.split('|');
    const viralScript = parts[0].trim();
    const topic = parts[1].trim();

    if (!viralScript || viralScript.length < 20) {
      return ctx.reply('[!] CẢNH BÁO: Kịch bản đầu vào quá ngắn. Yêu cầu nhập đầy đủ nội dung lời thoại video viral.');
    }

    await ctx.reply(`[i] Đang tiến hành phân tích cấu trúc video viral và tái tạo kịch bản tối ưu cho chủ đề "${topic}"...\n(Thời gian xử lý dự kiến: 20-40 giây)`);

    const { spawn } = require('child_process');
    const path = require('path');
    const fs = require('fs');
    const escapedScript = viralScript.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, '\\n');
    const escapedTopic = topic.replace(/"/g, '\\"');

    const projectRoot = path.resolve(__dirname, '../../..');
    const venvPythonPathWin = path.resolve(projectRoot, 'venv/Scripts/python.exe');
    const venvPythonPathUnix = path.resolve(projectRoot, 'venv/bin/python');
    
    let pythonExecutable = 'python';
    if (fs.existsSync(venvPythonPathWin)) {
      pythonExecutable = venvPythonPathWin;
      console.log(`[Bot Analyze] Using Windows virtualenv Python: ${pythonExecutable}`);
    } else if (fs.existsSync(venvPythonPathUnix)) {
      pythonExecutable = venvPythonPathUnix;
      console.log(`[Bot Analyze] Using Unix virtualenv Python: ${pythonExecutable}`);
    }

    const pythonProcess = spawn(pythonExecutable, [
      '-c',
      `
import sys
sys.path.append('${path.resolve(__dirname, '../../..').replace(/\\/g, '/')}')
from worker.services.llm_service import LLMService
import json
svc = LLMService()
result = svc.analyze_viral_and_recreate("${escapedScript}", "${escapedTopic}", "Người dùng TikTok")
print(json.dumps(result, ensure_ascii=False))
`
    ]);

    let output = '';
    pythonProcess.stdout.on('data', (data: Buffer) => { output += data.toString(); });

    await new Promise((resolve) => pythonProcess.on('close', resolve));

    try {
      const result = JSON.parse(output.trim());
      const analysis = result.viral_analysis || {};
      const recreated = result.recreated_script || {};

      const message =
        `<b>BÁO CÁO PHÂN TÍCH & TÁI TẠO KỊCH BẢN</b>\n` +
        `──────────────────────────────\n` +
        `<b>PHÂN TÍCH CẤU TRÚC VIRAL:</b>\n` +
        `• Công thức Hook: <b>${escapeHtml(analysis.hook_formula || 'N/A')}</b>\n` +
        `• Cảm xúc kích hoạt: <b>${escapeHtml(analysis.emotion_trigger || 'N/A')}</b>\n` +
        `• Kỹ thuật giữ chân: <b>${escapeHtml(analysis.retention_technique || 'N/A')}</b>\n` +
        `• Điểm mạnh cốt lõi:\n${(analysis.key_strengths || []).map((s: string) => `  - ${escapeHtml(s)}`).join('\n')}\n\n` +
        `<b>KỊCH BẢN TÁI TẠO ĐỘC LẬP:</b>\n` +
        `• Hook (3s): <b>"${escapeHtml(recreated.hook_text_3s || '')}"</b>\n` +
        `• Tiêu đề đề xuất: <b>${escapeHtml(recreated.video_title_idea || '')}</b>\n` +
        `• Chi tiết lời thoại:\n<i>${escapeHtml(recreated.full_voice_script || '')}</i>`;

      await ctx.replyWithHTML(message);
    } catch (parseErr) {
      await ctx.reply('[!] Lỗi phân tích kết quả cấu trúc kịch bản. Hãy thử lại sau.');
    }

  } catch (error: any) {
    ctx.reply(`[!] Lỗi phân tích viral script: ${error.message}`);
  }
});



// Giao diện Bảng Điều Khiển Khởi Tạo Chiến Dịch Tự Động 30 Ngày
// Giao diện Bảng Điều Khiển Khởi Tạo Chiến Dịch Tự Động 30 Ngày
async function replyCampaignDashboard(ctx: any) {
  const message =
    `🎯 <b>BẢNG KHỞI TẠO CHIẾN DỊCH TỰ ĐỘNG 30 NGÀY</b>\n` +
    `━━━━━━━━━━━━━━━━━━━━━\n` +
    `Chức năng khởi chạy chiến dịch (Campaign) tự động lập lịch trình sáng tạo nội dung kéo dài <b>30 ngày</b> liên tục trên TikTok.\n\n` +
    `🤖 <b>Hệ thống AI sẽ tự động xử lý:</b> \n` +
    `1️⃣ <b>Lập kế hoạch nội dung:</b> Sinh 30 chủ đề video tương thích với kênh.\n` +
    `2️⃣ <b>Soạn thảo kịch bản:</b> Tạo 30 bộ câu hook & thoại tối ưu thời gian giữ chân.\n` +
    `3️⃣ <b>Kết xuất đa phương tiện:</b> Tự động sinh video, lồng ghép âm thanh phản hồi sóng âm chuyển động hoặc remix nhạc hot.\n` +
    `4️⃣ <b>Đăng tải tự động:</b> Lập lịch và đưa vào hàng đợi chờ duyệt/xuất bản.\n\n` +
    `⚡ <b>1-TAP LAUNCH - KHỞI CHẠY NHANH QUA MẪU CÓ SẴN:</b> \n` +
    `Chọn một chủ đề tối ưu được thiết lập sẵn dưới đây để chạy ngay:\n\n` +
    `• <b>🎧 Lofi Chill & Học Tập</b>\n` +
    `  <i>Chủ đề:</i> Nhạc Lofi và trích dẫn truyền cảm hứng học tập\n` +
    `  <i>Đối tượng:</i> Học sinh, sinh viên muốn tập trung học tập\n\n` +
    `• <b>💻 Kỹ Năng Công Sở Excel/Word</b>\n` +
    `  <i>Chủ đề:</i> Mẹo tin học văn phòng Excel/Word/PPT và hiệu suất làm việc\n` +
    `  <i>Đối tượng:</i> Dân văn phòng, người đi làm muốn nâng cao năng lực\n\n` +
    `• <b>🚀 Tư Duy & Phát Triển Bản Thân</b>\n` +
    `  <i>Chủ đề:</i> Tư duy tích cực, phát triển bản thân và thói quen thành công\n` +
    `  <i>Đối tượng:</i> Người trẻ khát vọng học hỏi & cải thiện tư duy\n\n` +
    `• <b>🔥 Music Remix Hot Trend</b>\n` +
    `  <i>Chủ đề:</i> Remix các bài hát hot trend kết hợp visual chuyển động mạnh\n` +
    `  <i>Đối tượng:</i> Người trẻ mê âm nhạc & visual bắt mắt sôi động\n\n` +
    `✍️ <b>TỰ THIẾT LẬP CHỦ ĐỀ CHIẾN DỊCH RIÊNG:</b>\n` +
    `Chọn cách khởi chạy thủ công của bạn:\n` +
    `<b>Cách 1 (Khuyên dùng):</b> Bấm nút tạo <b>Step-by-Step</b> dưới đây để làm theo hướng dẫn.\n` +
    `<b>Cách 2:</b> Gửi lệnh trực tiếp theo cú pháp:\n` +
    `<code>/startcampaign Chủ đề | Đối tượng</code>\n` +
    `<i>(Ví dụ: <code>/startcampaign Tiếng Anh giao tiếp | Người mất gốc</code>)</i>`;

  const keyboard = Markup.inlineKeyboard([
    [
      Markup.button.callback('1️⃣ Lofi Chill 🎧', 'camp_preset:lofi_student'),
      Markup.button.callback('2️⃣ Kỹ năng Công sở 💻', 'camp_preset:office_skills'),
    ],
    [
      Markup.button.callback('3️⃣ Tư duy Thành công 🚀', 'camp_preset:self_dev'),
      Markup.button.callback('4️⃣ Music Remix Trend 🔥', 'camp_preset:music_trend'),
    ],
    [
      Markup.button.callback('✍️ Tạo Chiến Dịch Step-by-Step 🚀', 'camp_wizard:start'),
    ],
    [
      Markup.button.callback('🎮 Về Bảng Điều Khiển', 'quick:menu'),
    ]
  ]);

  await ctx.replyWithHTML(message, keyboard);
}

// Xử lý từng bước nhập liệu của Campaign Wizard
async function handleCampaignWizardStep(ctx: any, text: string) {
  const chatId = ctx.chat?.id;
  if (!chatId) return;

  const wizard = campaignWizards.get(chatId);
  if (!wizard) return;

  if (wizard.step === 'awaiting_topic') {
    const topic = text.trim();
    if (!topic) {
      await ctx.replyWithHTML('❌ Chủ đề không được để trống. Vui lòng nhập lại chủ đề chiến dịch:');
      return;
    }
    campaignWizards.set(chatId, { ...wizard, step: 'awaiting_target', topic });
    await ctx.replyWithHTML(
      `🎯 <b>BƯỚC 2/2: NHẬP ĐỐI TƯỢNG MỤC TIÊU</b>\n` +
      `━━━━━━━━━━━━━━━━━━━━━\n` +
      `▪️ Chủ đề đã chọn: <b>${escapeHtml(topic)}</b>\n\n` +
      `Hãy gửi tin nhắn nhập đối tượng người xem mục tiêu (Ví dụ: <i>Sinh viên mất gốc</i>, <i>Dân văn phòng bận rộn</i>, <i>Mẹ bỉm sữa</i>,...)\n\n` +
      `👉 <i>Soạn /cancel hoặc bấm nút bên dưới để hủy bỏ bất kỳ lúc nào.</i>`,
      Markup.inlineKeyboard([
        [Markup.button.callback('❌ Hủy bỏ', 'camp_wizard:cancel')]
      ])
    );
    return;
  }

  if (wizard.step === 'awaiting_target') {
    const target = text.trim();
    if (!target) {
      await ctx.replyWithHTML('❌ Đối tượng không được để trống. Vui lòng nhập lại đối tượng mục tiêu:');
      return;
    }

    // Cập nhật trạng thái
    campaignWizards.set(chatId, { ...wizard, target });

    const targetDateLabel = wizard.targetDate
      ? formatNaturalTargetDate(wizard.targetDate)
      : 'Hôm Nay hoặc Ngày Mai (Chọn bên dưới)';

    // Hiển thị thẻ xác nhận trực quan
    const confirmCard =
      `🚀 <b>XÁC NHẬN KHỞI CHẠY CHIẾN DỊCH VIDEO ĐƠN LẺ</b>\n` +
      `━━━━━━━━━━━━━━━━━━━━━\n` +
      `📊 <b>TÓM TẮT THÔNG TIN CHIẾN DỊCH:</b>\n` +
      `▪️ Chủ đề: <b>${escapeHtml(wizard.topic || '')}</b>\n` +
      `▪️ Đối tượng: <b>${escapeHtml(target)}</b>\n` +
      `▪️ Ngày lên lịch: <b>${targetDateLabel}</b>\n\n` +
      `🤖 AI sẽ tự động phân tích chủ đề, lên kế hoạch nội dung chi tiết và kết xuất video tự động.\n\n` +
      `Bạn có muốn khởi chạy chiến dịch này ngay không?`;

    const buttons = [];
    if (wizard.targetDate) {
      buttons.push([
        Markup.button.callback('🚀 Khởi chạy ngay', 'camp_wizard:launch'),
        Markup.button.callback('❌ Hủy bỏ', 'camp_wizard:cancel')
      ]);
    } else {
      buttons.push([
        Markup.button.callback('🚀 Hôm Nay', 'camp_wizard:launch_today'),
        Markup.button.callback('📅 Ngày Mai', 'camp_wizard:launch_tomorrow')
      ]);
      buttons.push([
        Markup.button.callback('❌ Hủy bỏ', 'camp_wizard:cancel')
      ]);
    }

    await ctx.replyWithHTML(confirmCard, Markup.inlineKeyboard(buttons));
    return;
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

// Gọi Gemini AI trong Node.js để sinh ý tưởng video đơn lẻ
async function generateSingleVideoIdea(topic: string, targetAudience: string): Promise<{ title: string, concept: string, mood: string }> {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    return {
      title: `Ý tưởng: ${topic}`,
      concept: `Video ngắn về ${topic} cho ${targetAudience}`,
      mood: 'educational',
    };
  }
  const prompt = `
Bạn là chuyên gia sáng tạo nội dung TikTok viral hàng đầu Việt Nam. Hãy đề xuất 1 ý tưởng video ngắn cực kỳ hấp dẫn dựa trên thông tin sau:
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
    const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${apiKey}`;
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
        generationConfig: { temperature: 0.7, responseMimeType: 'application/json' },
      }),
    });
    if (!response.ok) throw new Error(`Gemini status ${response.status}`);
    const data: any = await response.json();
    const raw = data?.candidates?.[0]?.content?.parts?.[0]?.text;
    if (!raw) throw new Error('Empty response from Gemini');
    const parsed = JSON.parse(raw.trim());
    return {
      title: parsed.title || `Ý tưởng: ${topic}`,
      concept: parsed.concept || `Video ngắn về ${topic}`,
      mood: parsed.mood || 'educational',
    };
  } catch (error) {
    console.error('Failed to generate video idea with Gemini:', error);
    return {
      title: `Bí quyết ${topic} cực hay`,
      concept: `Video chia sẻ về ${topic} cho đối tượng ${targetAudience}`,
      mood: 'educational',
    };
  }
}

// Logic thực thi khởi tạo chiến dịch 1 video đơn lẻ
async function startCampaignLogic(ctx: any, topic: string, targetAudience: string, targetDateStr: string = 'today', presetLabel?: string) {
  const targetDateText = formatNaturalTargetDate(targetDateStr);
  const activeSession = await beginActiveOperation(ctx, {
    chatId: ctx.chat.id,
    kind: 'single_video',
    title: 'Đang tạo video',
    subtitle: `${presetLabel ? `${presetLabel} - ` : ''}${topic} | ${targetAudience} | ${targetDateText}`,
  });

  try {
    // 1. Gọi Gemini sinh ý tưởng tiêu đề
    const idea = await generateSingleVideoIdea(topic, targetAudience);

    // 2. Tạo bản ghi Campaign mới trong MySQL
    const campaign = await prisma.channelsCampaign.create({
      data: {
        telegram_chat_id: BigInt(ctx.chat?.id || 0),
        topic: topic,
        target_audience: targetAudience,
        status: 'RUNNING',
      },
    });

    // 3. Tính toán thời gian đặt lịch
    let scheduledTime = parseScheduleTime(targetDateStr) || new Date();
    if (targetDateStr === 'tomorrow') {
      scheduledTime = new Date(Date.now() + 24 * 60 * 60 * 1000);
    } else if (targetDateStr !== 'today' && /^\d{4}-\d{2}-\d{2}$/.test(targetDateStr)) {
      scheduledTime = new Date(targetDateStr + 'T12:00:00+07:00'); // Mặc định 12:00 ngày được chọn
    }

    const metadata = {
      music_mood: idea.mood,
      content_category: 'educational',
      primary_goal: 'VIEWS',
      concept_description: idea.concept
    };

    // 4. Tạo Job mới trong MySQL
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
    activeSession.jobId = job.id;
    activeSession.campaignId = campaign.id;
    activeSession.subtitle = `${idea.title} | ${targetDateText}`;
    await refreshActiveOperation(activeSession);

    // 5. Đưa job vào hàng đợi RENDER ngay lập tức
    await addJobToQueue(job.id, 'RENDER');

    await auditBotAction(job.id, 'BOT_START_CAMPAIGN', 'INFO', `Khởi chạy chiến dịch đơn lẻ #${campaign.id} Job #${job.id} ngày: ${targetDateText}`);

    await refreshActiveOperation(activeSession);
  } catch (error: any) {
    console.error('Error starting single campaign:', error);
    stopActiveOperation(ctx.chat.id);
    await ctx.reply(`❌ Không thể khởi tạo chiến dịch: ${error.message}`);
  }
}

// Hàm khởi tạo Keyboard Menu Lịch trình
function getCalendarMenuKeyboard() {
  const todayStr = new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Ho_Chi_Minh' }); // YYYY-MM-DD
  const tomorrow = new Date(Date.now() + 24 * 60 * 60 * 1000);
  const tomorrowStr = tomorrow.toLocaleDateString('sv-SE', { timeZone: 'Asia/Ho_Chi_Minh' });

  return Markup.inlineKeyboard([
    [
      Markup.button.callback(`📅 Hôm Nay (${todayStr.split('-').reverse().slice(0, 2).join('/')})`, `calendar:date:${todayStr}`),
      Markup.button.callback(`📅 Ngày Mai (${tomorrowStr.split('-').reverse().slice(0, 2).join('/')})`, `calendar:date:${tomorrowStr}`)
    ],
    [
      Markup.button.callback('📅 Xem Lịch 7 Ngày Tới', 'calendar:view_7days'),
      Markup.button.callback('🔍 Nhập Ngày Khác', 'calendar:custom_input')
    ],
    [
      Markup.button.callback('🎮 Về Bảng Điều Khiển', 'quick:menu')
    ]
  ]);
}

// Hàm hiển thị Lịch trình chi tiết cho một ngày cụ thể
async function renderCalendarDateView(ctx: any, dateStr: string) {
  try {
    const startOfDay = new Date(dateStr + 'T00:00:00+07:00');
    const endOfDay = new Date(dateStr + 'T23:59:59+07:00');

    // Truy vấn tất cả Video Job được lên lịch trong ngày này
    const jobs = await prisma.videoPipelineJobs.findMany({
      where: {
        scheduled_post_time: {
          gte: startOfDay,
          lte: endOfDay
        }
      },
      orderBy: { scheduled_post_time: 'asc' }
    });

    const formattedDate = dateStr.split('-').reverse().join('/');

    if (jobs.length > 0) {
      let msg = `📅 <b>LỊCH TRÌNH VIDEO NGÀY ${formattedDate}</b>\n`;
      msg += `━━━━━━━━━━━━━━━━━━━━━\n`;
      msg += `Hiện tại đang có <b>${jobs.length} video</b> được lên lịch đăng:\n\n`;

      const buttons = [];
      for (const job of jobs) {
        const timeStr = new Date(job.scheduled_post_time).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Ho_Chi_Minh' });
        msg += `▪️ <b>Job #${job.id}</b> - Lịch đăng: <b>${timeStr}</b>\n`;
        msg += `   - Tiêu đề: <i>${escapeHtml(job.video_title_idea || '')}</i>\n`;
        msg += `   - Trạng thái: <code>${job.pipeline_state}</code>\n\n`;

        // Các nút bấm hành động cho mỗi Video Job
        buttons.push([
          Markup.button.callback(`✏️ Sửa Job #${job.id}`, `cal_edit:${job.id}`),
          Markup.button.callback(`❌ Xóa Job #${job.id}`, `cal_delete:${job.id}`)
        ]);
        if (job.pipeline_state === 'RENDERED' || job.video_output_path) {
          buttons.push([
            Markup.button.callback(`🔍 Xem trước Job #${job.id}`, `preview:${job.id}`)
          ]);
        }
      }

      buttons.push([
        Markup.button.callback('➕ Lên lịch video mới', `cal_create:${dateStr}`),
      ]);
      buttons.push([
        Markup.button.callback('⬅️ Về Lịch Trình', 'calendar:menu'),
        Markup.button.callback('🎮 Bảng Điều Khiển', 'quick:menu')
      ]);

      await ctx.replyWithHTML(msg, Markup.inlineKeyboard(buttons));
    } else {
      const msg =
        `📅 <b>LỊCH TRÌNH VIDEO NGÀY ${formattedDate}</b>\n` +
        `━━━━━━━━━━━━━━━━━━━━━\n` +
        `❌ Hiện tại chưa có video nào được lên lịch cho ngày này.\n\n` +
        `Bạn có muốn lên lịch tạo một video mới không?`;

      const keyboard = Markup.inlineKeyboard([
        [Markup.button.callback('➕ Lên lịch video mới', `cal_create:${dateStr}`)],
        [
          Markup.button.callback('⬅️ Về Lịch Trình', 'calendar:menu'),
          Markup.button.callback('🎮 Bảng Điều Khiển', 'quick:menu')
        ]
      ]);

      await ctx.replyWithHTML(msg, keyboard);
    }
  } catch (error: any) {
    console.error(`Error rendering calendar date view for ${dateStr}:`, error);
    await ctx.reply(`❌ Lỗi khi truy vấn lịch trình ngày ${dateStr}: ${error.message}`);
  }
}

// Lệnh: /start_campaign hoặc /startcampaign [Chủ đề] | [Đối tượng]
bot.command(['start_campaign', 'startcampaign'], async (ctx) => {
  try {
    const rawText = ctx.message.text.trim();
    const firstSpace = rawText.indexOf(' ');
    let paramText = '';
    if (firstSpace !== -1) {
      paramText = rawText.substring(firstSpace).trim();
    }

    if (!paramText || !paramText.includes('|')) {
      return replyCampaignDashboard(ctx);
    }

    const parts = paramText.split('|');
    const topic = parts[0].trim();
    const targetAudience = parts[1].trim();

    const chatId = ctx.chat?.id;
    if (chatId) {
      campaignWizards.set(chatId, {
        step: 'awaiting_target',
        topic,
        target: targetAudience
      });
    }

    return ctx.replyWithHTML(
      `🚀 <b>KHỞI CHẠY CHIẾN DỊCH TỪ LỆNH GÕ</b>\n` +
      `━━━━━━━━━━━━━━━━━━━━━\n` +
      `▪&nbsp;Chủ đề: <b>${escapeHtml(topic)}</b>\n` +
      `▪&nbsp;Đối tượng: <b>${escapeHtml(targetAudience)}</b>\n\n` +
      `Vui lòng chọn thời gian lên lịch đăng video bên dưới:`,
      Markup.inlineKeyboard([
        [
          Markup.button.callback('🚀 Hôm Nay', 'camp_wizard:launch_today'),
          Markup.button.callback('📅 Ngày Mai', 'camp_wizard:launch_tomorrow')
        ],
        [Markup.button.callback('❌ Hủy bỏ', 'camp_wizard:cancel')]
      ])
    );

  } catch (error: any) {
    console.error('[Bot Error] Error starting campaign:', error);
    ctx.reply(`[!] Đã xảy ra lỗi khi tạo chiến dịch: ${error.message}`);
  }
});

// Lệnh: /status
bot.command('status', async (ctx) => {
  try {
    ctx.reply(await getStatusReport());
  } catch (error: any) {
    console.error('[Bot Error] Error getting status:', error);
    ctx.reply(`❌ Không thể truy vấn trạng thái hệ thống: ${error.message}`);
  }
});

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
        Markup.button.callback('✅ Xác nhận', `confirm:${confirmation.id}`),
        Markup.button.callback('❌ Hủy bỏ', `deny:${confirmation.id}`),
      ]),
    );
  } catch (error: any) {
    console.error('[Bot Error] Error preparing campaign confirmation:', error);
    ctx.reply(`❌ Không thể chuẩn bị thao tác campaign: ${error.message}`);
  }
}

// Lệnh: /schedule today|week
bot.command('schedule', async (ctx) => {
  try {
    const text = ctx.message.text.substring(9).trim().toLowerCase();
    const period = text.includes('week') || text.includes('tuần') ? 'week' : 'today';
    await ctx.reply(await getScheduleReport(period));
  } catch (error: any) {
    console.error('[Bot Error] Error showing schedule:', error);
    ctx.reply(`❌ Không thể xem lịch: ${error.message}`);
  }
});

// Lệnh: /pending
bot.command('pending', async (ctx) => {
  try {
    await ctx.reply(await getPendingApprovalReport());
  } catch (error: any) {
    console.error('[Bot Error] Error showing pending jobs:', error);
    ctx.reply(`❌ Không thể xem video chờ duyệt: ${error.message}`);
  }
});

// ─── AI Smart Config Display ───────────────────────────────────────────────

/**
 * Gọi Gemini để gợi ý thông số sáng tạo phù hợp với bài hát/nghệ sĩ.
 * Trả về JSON gồm mood, remix_style, bpm, caption.
 */
async function generateSmartSuggestions(songTitle: string, artistName: string): Promise<Record<string, string> | null> {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) return null;
  try {
    const prompt = `
Bạn là giám đốc sáng tạo kênh âm nhạc TikTok hàng đầu Việt Nam.
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
    const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${apiKey}`;
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
        generationConfig: { temperature: 0.3, responseMimeType: 'application/json' },
      }),
    });
    if (!resp.ok) return null;
    const data: any = await resp.json();
    const raw = data?.candidates?.[0]?.content?.parts?.[0]?.text;
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/**
 * Xây dựng nội dung hiển thị config thông minh theo render_mode của job.
 * - music_reactive: hiển thị mood, caption, visual_keywords
 * - music_remix_reactive: hiển thị mood, remix_style, bpm
 * - classic_video: hiển thị trạng thái cơ bản
 */
async function buildJobConfigDisplay(jobId: number, job: any, metadata: any, withSuggestions = true): Promise<string> {
  const renderMode: string = metadata.render_mode || 'classic_video';
  const songTitle: string = metadata.song_title || job.video_title_idea || '';
  const artistName: string = metadata.artist_name || '';
  const isMusicVideo = renderMode === 'music_reactive' || renderMode === 'music_remix_reactive';

  let lines: string[] = [];
  lines.push(`⚙️ THÔNG SỐ CẤU HÌNH TÁC VỤ (JOB #${jobId})`);
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
    // Classic video
    lines.push(`▪️ Chủ đề: *${songTitle}*`);
    if (metadata.music_mood) lines.push(`▪️ Mood nhạc nền: \`${metadata.music_mood}\``);
    if (metadata.content_category) lines.push(`▪️ Thể loại nội dung: \`${metadata.content_category}\``);
    if (metadata.primary_goal) lines.push(`▪️ Mục tiêu: \`${metadata.primary_goal}\``);
  }

  // Gợi ý Gemini nếu là music video và chưa có đầy đủ config
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

      // Tạo lệnh set_job_config từ suggestions
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

bot.command('job_config', async (ctx) => {
  try {
    const text = ctx.message.text.substring(11).trim();
    const jobId = parseInt(text, 10);
    if (isNaN(jobId)) {
      return replyCommandGuidance(ctx, 'job_config', 'mã tác vụ trống');
    }
    const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
    if (!job) {
      return ctx.reply(`❌ LỖI: Không tìm thấy tác vụ Job #${jobId} trong cơ sở dữ liệu.`);
    }
    const metadata = parseMetadata(job.scenes_layout_json);
    await ctx.reply('🔄 Đang phân tích và tạo gợi ý AI cho tác vụ...', { parse_mode: 'Markdown' });
    const displayText = await buildJobConfigDisplay(jobId, job, metadata, true);
    const renderMode = metadata.render_mode || 'classic_video';
    await ctx.reply(displayText, {
      parse_mode: 'Markdown',
      ...postTemplateKeyboard(jobId, renderMode === 'music_reactive' ? 'render' : 'remix'),
    });
  } catch (error: any) {
    console.error('[Bot Error] Error showing job config:', error);
    ctx.reply(`❌ Không thể xem cấu hình tác vụ: ${error.message}`);
  }
});

bot.command('set_job_config', async (ctx) => {
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
      return ctx.reply(`❌ LỖI: Không tìm thấy tác vụ Job #${jobId} trong cơ sở dữ liệu.`);
    }

    const metadata = parseMetadata(job.scenes_layout_json);
    Object.assign(metadata, updates);
    await prisma.videoPipelineJobs.update({
      where: { id: jobId },
      data: { scenes_layout_json: JSON.stringify(metadata) },
    });
    await auditBotAction(jobId, 'BOT_JOB_CONFIG', 'SUCCESS', `Updated job config: ${JSON.stringify(updates)}`);

    await ctx.reply(
      `✅ Đã cập nhật thành công cấu hình Job #${jobId}:\n` +
      Object.entries(updates).map(([key, value]) => `▪️ <b>${escapeHtml(key)}:</b> <code>${escapeHtml(String(value))}</code>`).join('\n'),
      { parse_mode: 'HTML' }
    );
  } catch (error: any) {
    console.error('[Bot Error] Error setting job config:', error);
    ctx.reply(`Không thể cập nhật cấu hình job: ${error.message}`);
  }
});

// Lệnh: /reschedule <job_id> <YYYY-MM-DD HH:mm>
bot.command('reschedule', async (ctx) => {
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
      `Dời lịch phát sóng Job #${jobId} sang ${formatDateTime(newTime)}.`,
      { jobId, newTimeIso: newTime.toISOString() },
    );

    await ctx.reply(
      `❓ XÁC NHẬN YÊU CẦU THỰC THI HÀNH ĐỘNG HỆ THỐNG:\n\n${confirmation.summary}`,
      Markup.inlineKeyboard([
        Markup.button.callback('✅ Xác nhận', `confirm:${confirmation.id}`),
        Markup.button.callback('❌ Hủy bỏ', `deny:${confirmation.id}`),
      ]),
    );
  } catch (error: any) {
    console.error('[Bot Error] Error preparing reschedule:', error);
    ctx.reply(`❌ Không thể dời lịch: ${error.message}`);
  }
});

bot.command('pause_campaign', async (ctx) => {
  await prepareCampaignConfirmation(ctx, 'pause_campaign');
});

bot.command('resume_campaign', async (ctx) => {
  await prepareCampaignConfirmation(ctx, 'resume_campaign');
});

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

  // Tác vụ được coi là Standalone nếu được đánh dấu trước hoặc có render_mode phù hợp mà không có file thoại
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
  metadata.artist_name = metadata.artist_name || 'AgentTiktok';
  metadata.mood = metadata.mood || 'FOCUS_LOFI';
  metadata.require_tiktok_music = metadata.require_tiktok_music ?? true;
  metadata.tiktok_sound_volume_percent = metadata.tiktok_sound_volume_percent ?? 2;
  metadata.original_video_volume_percent = metadata.original_video_volume_percent ?? 100;
  metadata.tiktok_music_strategy = metadata.tiktok_music_strategy || 'add_exact_sound_at_publish';
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
    await auditBotAction(jobId, 'BOT_RENDER_MUSIC_WAIT_AUDIO', 'INFO', `Music reactive Job #${jobId} is waiting for user audio file.`);
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
  await auditBotAction(jobId, 'BOT_RENDER_MUSIC', 'INFO', `Queued music_reactive render for job #${jobId}.`);
  if (activeSession) {
    activeSession.jobId = jobId;
    await refreshActiveOperation(activeSession);
  }
  return;
}

bot.command('render_music', async (ctx) => {
  try {
    const text = ctx.message.text.substring(13).trim();
    const jobId = parseInt(text, 10);
    if (isNaN(jobId)) {
      return replyCommandGuidance(ctx, 'render_music', 'Mã tác vụ (Job ID) không hợp lệ hoặc trống');
    }
    await enqueueMusicReactiveRender(ctx, jobId);
  } catch (error: any) {
    console.error('[Bot Error] Error queueing music reactive render:', error);
    ctx.reply(`❌ Không thể render music reactive: ${error.message}`);
  }
});

async function handleCreateMusicVideoLogic(ctx: any, songTitle: string, artistName: string) {
  const resolvedIdea = await resolveConcreteMusicIdea(songTitle, artistName);
  songTitle = resolvedIdea.songTitle;
  artistName = resolvedIdea.artistName;
  const activeSession = await beginActiveOperation(ctx, {
    chatId: ctx.chat.id,
    kind: 'music_video',
    title: 'Đang tạo video âm nhạc',
    subtitle: `${songTitle} - ${artistName}`,
  });
  try {
    // 1. Tạo campaign mới
    const campaign = await prisma.channelsCampaign.create({
      data: {
        telegram_chat_id: BigInt(ctx.chat.id),
        topic: songTitle === 'HOT TRENDING' ? 'Chiến dịch Video Âm Nhạc Xu Hướng' : `Video Âm Nhạc: ${songTitle} - ${artistName}`,
        target_audience: 'Người nghe nhạc',
        status: 'RUNNING',
      },
    });

    // 2. Tạo metadata
    const metadata = {
      render_mode: 'music_reactive',
      song_title: songTitle,
      artist_name: artistName,
      is_standalone_music_video: true,
      requires_user_audio: true,
      auto_select_viral_segment: true,
      require_tiktok_music: true,
      tiktok_sound_volume_percent: 2,
      original_video_volume_percent: 100,
      tiktok_music_strategy: 'add_exact_sound_at_publish',
      mood: resolvedIdea.mood,
    };

    // 3. Tạo Job mới
    const job = await prisma.videoPipelineJobs.create({
      data: {
        campaign_id: campaign.id,
        day_number: 1,
        scheduled_post_time: new Date(),
        video_title_idea: songTitle === 'HOT TRENDING' ? 'Video Âm Nhạc Xu Hướng' : `${songTitle} - ${artistName}`,
        scenes_layout_json: JSON.stringify(metadata),
        pipeline_state: MUSIC_AUDIO_WAITING_STATE,
      },
    });
    activeSession.jobId = job.id;
    activeSession.campaignId = campaign.id;
    activeSession.subtitle = job.video_title_idea || activeSession.subtitle;
    await refreshActiveOperation(activeSession);

    await auditBotAction(job.id, 'BOT_MUSIC_VIDEO', 'INFO', `Khởi tạo video âm nhạc Job #${job.id}, đang chờ người dùng gửi file audio.`);
    await refreshActiveOperation(activeSession);
    await ctx.replyWithHTML(
      `🎵 <b>ĐÃ TẠO Ý TƯỞNG VIDEO ÂM NHẠC</b>\n` +
      `━━━━━━━━━━━━━━━━━━━━━\n` +
      `▪️ Job #${job.id}: <b>${escapeHtml(job.video_title_idea || 'Video âm nhạc')}</b>\n` +
      `▪️ Bạn có thể gửi ảnh visual trước nếu muốn, hoặc để hệ thống tự lấy.\n` +
      `▪️ Sau đó gửi file nhạc <code>.mp3</code>, <code>.wav</code> hoặc <code>.m4a</code> vào chat này.\n\n` +
      `Sau khi nhận file nhạc, hệ thống sẽ tự chọn khúc viral, cắt đoạn hay và render lyric đồng bộ theo nhạc.`,
      Markup.inlineKeyboard([
        [
          Markup.button.callback('🖼️ Tôi sẽ gửi ảnh', `music_visual:custom:${job.id}`),
          Markup.button.callback('✨ Tự lấy ảnh', `music_visual:auto:${job.id}`),
        ],
      ]),
    );

  } catch (error: any) {
    console.error('[Bot Error] Error starting music video campaign:', error);
    stopActiveOperation(ctx.chat.id);
    ctx.reply(`❌ Không thể khởi tạo video âm nhạc độc lập: ${error.message}`);
  }
}

bot.command('music_video', async (ctx) => {
  try {
    const text = ctx.message.text.substring(12).trim(); // Bỏ qua '/music_video'
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
    console.error('[Bot Error] Error starting music video campaign command:', error);
    ctx.reply(`❌ Không thể khởi tạo video âm nhạc độc lập: ${error.message}`);
  }
});

bot.command('create_music_video', async (ctx) => {
  try {
    const text = ctx.message.text.substring(19).trim(); // Bỏ qua '/create_music_video'
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
    console.error('[Bot Error] Error starting music video campaign command:', error);
    ctx.reply(`❌ Không thể khởi tạo video âm nhạc độc lập: ${error.message}`);
  }
});

bot.on(['audio', 'document', 'photo'], async (ctx) => {
  try {
    const handled = await handleWaitingMusicAttachmentUpload(ctx);
    if (!handled) {
      await ctx.reply('Hiện không có video âm nhạc nào đang chờ file nhạc/ảnh. Hãy tạo video âm nhạc trước rồi gửi ảnh tùy chọn hoặc file .mp3, .wav, .m4a.');
    }
  } catch (error: any) {
    console.error('[Bot Error] Error handling music attachment upload:', error);
    await ctx.reply(`❌ Không thể nhận file: ${error.message}`);
  }
});

bot.command('remix_music', async (ctx) => {
  try {
    const text = ctx.message.text.substring(12).trim();
    const jobId = parseInt(text, 10);
    if (isNaN(jobId)) {
      return replyCommandGuidance(ctx, 'remix_music', 'Mã tác vụ (Job ID) không hợp lệ hoặc trống');
    }

    const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
    if (!job) {
      return ctx.reply(`❌ LỖI HỆ THỐNG: Không tìm thấy tác vụ Job #${jobId} trong cơ sở dữ liệu.`);
    }

    let metadata: Record<string, any> = {};
    try {
      metadata = job.scenes_layout_json && typeof job.scenes_layout_json === 'string'
        ? JSON.parse(job.scenes_layout_json)
        : (job.scenes_layout_json as any) || {};
      if (Array.isArray(metadata)) metadata = {};
    } catch {
      metadata = {};
    }

    const audioPath = metadata.audio_path || metadata.remix_audio_path || job.audio_file_path;
    if (!audioPath || !fs.existsSync(audioPath)) {
      return ctx.reply(`⚠️ CẢNH BÁO TÀI NGUYÊN: Tác vụ Job #${jobId} chưa có tệp âm thanh hợp lệ để thực hiện Remix.`);
    }

    const confirmation = createConfirmation(
      ctx.chat.id,
      'remix_music',
      `Remix tài nguyên âm thanh cho tác vụ Job #${jobId} theo mẫu đã chọn.\nXác nhận quyền sở hữu và cấp phép bản quyền tệp âm thanh.`,
      { jobId, rightsConfirmed: true },
    );

    await ctx.reply(
      `❓ XÁC NHẬN YÊU CẦU THỰC THI REMIX:\n━━━━━━━━━━━━━━━━━━━━━\n${confirmation.summary}`,
      Markup.inlineKeyboard([
        Markup.button.callback('✅ Xác nhận', `confirm:${confirmation.id}`),
        Markup.button.callback('❌ Hủy bỏ', `deny:${confirmation.id}`),
      ]),
    );
  } catch (error: any) {
    console.error('[Bot Error] Error preparing remix music:', error);
    ctx.reply(`❌ Không thể chuẩn bị remix music: ${error.message}`);
  }
});

// Hàm xử lý chung cho xem trước video
async function handlePreviewLogic(ctx: any, jobId: number) {
  const job = await prisma.videoPipelineJobs.findUnique({
    where: { id: jobId },
    include: { campaign: true }
  });

  if (!job) {
    return ctx.reply(`❌ LỖI HỆ THỐNG: Không tìm thấy tác vụ Job #${jobId} trong cơ sở dữ liệu.`);
  }

  ctx.reply(`🔍 Đang truy xuất dữ liệu tệp tin video Job #${jobId}: "${job.video_title_idea}"...`);

  if (!job.video_output_path || !fs.existsSync(job.video_output_path)) {
    return ctx.replyWithHTML(
      `⚠️ <b>CẢNH BÁO TÀI NGUYÊN: Tệp tin video đầu ra chưa được kết xuất hoặc không tồn tại trên hệ thống lưu trữ.</b>\n━━━━━━━━━━━━━━━━━━━━━\n` +
      `▪️ Trạng thái hiện tại: <code>${escapeHtml(job.pipeline_state)}</code>\n` +
      `▪️ Ý tưởng nội dung: <b>${escapeHtml(job.video_title_idea || 'Chưa khởi tạo')}</b>`
    );
  }

  const metadata = parseMetadata(job.scenes_layout_json);
  const renderMode = metadata.render_mode || 'classic_video';
  const isMusicVideo = metadata.is_standalone_music_video || renderMode === 'music_reactive' || renderMode === 'music_remix_reactive';

  let videoCaption = '';
  if (isMusicVideo) {
    const songTitle = metadata.song_title || job.video_title_idea;
    const artistName = metadata.artist_name || 'N/A';
    const mood = metadata.mood || metadata.music_mood || 'N/A';
    const remixStyle = metadata.remix_style || 'Nguyên bản';
    const caption = metadata.caption || 'N/A';
    
    videoCaption = 
      `🎬 <b>KIỂM DUYỆT VIDEO ĐẦU RA - JOB #${job.id} (Ngày ${job.day_number})</b>\n━━━━━━━━━━━━━━━━━━━━━\n` +
      `▪️ Bài hát/Tiêu đề: <b>${escapeHtml(songTitle)}</b>\n` +
      `▪️ Ca sĩ/Nghệ sĩ: <b>${escapeHtml(artistName)}</b>\n` +
      `▪️ Sắc thái (Mood): <code>${escapeHtml(mood)}</code>\n` +
      `▪️ Style Remix: <code>${escapeHtml(remixStyle)}</code>\n` +
      `▪️ Caption/Mô tả: <i>"${escapeHtml(caption)}"</i>\n` +
      `▪️ Trạng thái hiện tại: <code>${escapeHtml(job.pipeline_state)}</code>\n\n` +
      `💡 <b>MẸO LÊN XU HƯỚNG &amp; TRÁNH BẢN QUYỀN 🚀</b>\n` +
      `Hệ thống đã phối nhạc Lofi an toàn &amp; lọc Remix chống quét bản quyền ContentID. Để video cắn đề xuất mạnh nhất:\n` +
      `1️⃣ Khi đăng trên TikTok, hãy bấm <b>Thêm âm thanh</b> (Add sound).\n` +
      `2️⃣ Tìm kiếm tên bài hát: <b>"${escapeHtml(songTitle)}"</b> của ca sĩ <b>"${escapeHtml(artistName)}"</b>.\n` +
      `3️⃣ Chọn nhạc này, đặt <b>Âm lượng</b> âm thanh TikTok về <b>1% - 3%</b> (giữ âm lượng video gốc ở 100%).\n` +
      `👉 Vừa cưỡi sóng hot trend của bài hát gốc, vừa an toàn bản quyền 100% không lo tắt tiếng!\n\n` +
      `Yêu cầu xác nhận phê duyệt xuất bản lên TikTok Studio.`;
  } else {
    videoCaption = 
      `🎬 <b>KIỂM DUYỆT VIDEO ĐẦU RA - JOB #${job.id} (Ngày ${job.day_number})</b>\n━━━━━━━━━━━━━━━━━━━━━\n` +
      `▪️ Tiêu đề: <b>${escapeHtml(job.video_title_idea || '')}</b>\n` +
      `▪️ Câu Hook (3s): <i>"${escapeHtml(job.hook_text_3s || '')}"</i>\n` +
      `▪️ Trạng thái hiện tại: <code>${escapeHtml(job.pipeline_state)}</code>\n\n` +
      `Yêu cầu xác nhận phê duyệt xuất bản lên TikTok Studio.`;
  }

  const approvalKeyboard = Markup.inlineKeyboard([
    [
      Markup.button.callback('🚀 PHÊ DUYỆT ĐĂNG', `approve_post:${jobId}`),
      Markup.button.callback('❌ HỦY TÁC VỤ', `cancel_job:${jobId}`)
    ]
  ]);
  const fileStats = fs.statSync(job.video_output_path);
  const fileSizeMb = fileStats.size / (1024 * 1024);
  const shortMediaCaption = `Preview Job #${job.id} - ${job.video_title_idea || 'Video'}`.slice(0, 900);

  try {
    await ctx.replyWithVideo(
      { source: job.video_output_path },
      {
        caption: shortMediaCaption,
        supports_streaming: true
      }
    );
  } catch (videoError: any) {
    console.warn(`[Bot Warning] Failed to upload preview video for job #${jobId}; trying document fallback:`, videoError?.message || videoError);

    try {
      await ctx.replyWithDocument(
        { source: job.video_output_path, filename: path.basename(job.video_output_path) },
        { caption: `File preview Job #${job.id}` }
      );
    } catch (documentError: any) {
      console.warn(`[Bot Warning] Failed to upload preview document for job #${jobId}:`, documentError?.message || documentError);
      await ctx.replyWithHTML(
        `⚠️ <b>Không thể tải preview lên Telegram.</b>\n` +
        `Video đã render xong nhưng Telegram upload bị ngắt hoặc file bị từ chối.\n` +
        `▪️ Job: <code>#${job.id}</code>\n` +
        `▪️ Dung lượng: <code>${fileSizeMb.toFixed(2)} MB</code>\n` +
        `▪️ Đường dẫn local: <code>${escapeHtml(job.video_output_path)}</code>`
      );
    }
  }

  await ctx.replyWithHTML(videoCaption, approvalKeyboard);
}

// Lệnh: /preview [job_id]
bot.command('preview', async (ctx) => {
  try {
    const text = ctx.message.text.substring(8).trim(); // Bỏ qua '/preview'
    const jobId = parseInt(text, 10);

    if (isNaN(jobId)) {
      return replyCommandGuidance(ctx, 'preview', 'Mã tác vụ (Job ID) không hợp lệ hoặc trống');
    }

    await handlePreviewLogic(ctx, jobId);
  } catch (error: any) {
    console.error('[Bot Error] Error previewing job:', error);
    ctx.reply(`❌ Đã xảy ra lỗi khi tải video preview: ${error.message}`);
  }
});

bot.command('retry_publish', async (ctx) => {
  try {
    const text = ctx.message.text.substring('/retry_publish'.length).trim();
    const jobId = parseInt(text, 10);
    if (isNaN(jobId)) {
      return ctx.reply('Vui lòng nhập đúng mẫu: /retry_publish <job_id>');
    }
    const result = await retryPublishJob(jobId, ctx.chat?.id);
    await ctx.reply(result.ok ? `✅ ${result.reason}` : `❌ ${result.reason}`);
  } catch (error: any) {
    console.error('[Bot Error] Error retrying publish:', error);
    await ctx.reply(`❌ Không thể đăng lại: ${error.message}`);
  }
});

// Lệnh: /preview_[job_id] (Shortcut nhấp chuột)
bot.hears(/^\/preview_(\d+)$/, async (ctx) => {
  try {
    const jobId = parseInt(ctx.match[1], 10);
    await handlePreviewLogic(ctx, jobId);
  } catch (error: any) {
    console.error('[Bot Error] Error previewing job via shortcut:', error);
    ctx.reply(`❌ Đã xảy ra lỗi khi tải video preview: ${error.message}`);
  }
});

// Lệnh: /logs [job_id] để theo dõi tiến trình hoặc debug lỗi trực tiếp từ Telegram
bot.command('logs', async (ctx) => {
  try {
    const text = ctx.message.text.substring(5).trim();
    const jobId = parseInt(text, 10);

    if (isNaN(jobId)) {
      return replyCommandGuidance(ctx, 'logs', 'Mã tác vụ (Job ID) không hợp lệ hoặc trống');
    }

    const logs = await prisma.processRealtimeLogs.findMany({
      where: { job_id: jobId },
      orderBy: { logged_at: 'asc' },
      take: 40
    });

    if (logs.length === 0) {
      return ctx.reply(`ℹ️ Không tìm thấy dữ liệu nhật ký cho Job #${jobId}.`);
    }

    let message = `📋 NHẬT KÝ TIẾN TRÌNH HỆ THỐNG - JOB #${jobId}\n━━━━━━━━━━━━━━━━━━━━━\n`;
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
    console.error('[Bot Error] Error showing logs:', error);
    ctx.reply(`❌ Không thể truy vấn logs: ${error.message}`);
  }
});

// Lệnh: /cancel để hủy bất kỳ tiến trình wizard nào đang hoạt động
bot.command('cancel', async (ctx) => {
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
      ? `Đã hủy thao tác đang chạy. ${result.reason}`
      : `Không thể hủy thao tác. ${result.reason}`);
  } else {
    await ctx.reply('ℹ️ Không có tác vụ hay tiến trình nhập liệu nào đang chạy để hủy.');
  }
});

// Lệnh: /cancel_campaign [campaign_id] để dừng/hủy chiến dịch đang chạy
bot.command('cancel_campaign', async (ctx) => {
  try {
    const text = ctx.message.text.substring(16).trim();
    const campaignId = parseInt(text, 10);

    if (isNaN(campaignId)) {
      return replyCommandGuidance(ctx, 'campaign', 'Mã chiến dịch (Campaign ID) không hợp lệ hoặc trống');
    }

    const campaign = await prisma.channelsCampaign.findUnique({
      where: { id: campaignId }
    });

    if (!campaign) {
      return ctx.reply(`❌ LỖI HỆ THỐNG: Không tìm thấy chiến dịch Campaign #${campaignId} trong cơ sở dữ liệu.`);
    }

    const confirmation = createConfirmation(
      ctx.chat.id,
      'cancel_campaign',
      `Ngừng kích hoạt chiến dịch Campaign #${campaignId}. Hệ thống lập lịch trình sẽ dừng xử lý toàn bộ tác vụ liên quan.`,
      { campaignId },
    );

    await ctx.reply(
      `❓ XÁC NHẬN YÊU CẦU HỦY CHIẾN DỊCH:\n━━━━━━━━━━━━━━━━━━━━━\n${confirmation.summary}`,
      Markup.inlineKeyboard([
        Markup.button.callback('✅ Xác nhận', `confirm:${confirmation.id}`),
        Markup.button.callback('❌ Hủy bỏ', `deny:${confirmation.id}`),
      ]),
    );
  } catch (error: any) {
    console.error('[Bot Error] Error cancelling campaign:', error);
    ctx.reply(`❌ Không thể hủy chiến dịch: ${error.message}`);
  }
});

// Lệnh: /calendar - Quản lý lịch trình video theo ngày
bot.command('calendar', async (ctx) => {
  try {
    await ctx.replyWithHTML(
      `📅 <b>QUẢN LÝ LỊCH TRÌNH VIDEO</b>\n` +
      `━━━━━━━━━━━━━━━━━━━━━\n` +
      `Chọn ngày bạn muốn xem hoặc quản lý lịch trình đăng video bên dưới:`,
      getCalendarMenuKeyboard(),
    );
  } catch (error: any) {
    console.error('[Bot Error] Error showing calendar:', error);
    ctx.reply(`❌ Lỗi khi hiển thị lịch trình: ${error.message}`);
  }
});

// Lệnh: /force_post [job_id]
bot.command('force_post', async (ctx) => {
  try {
    const text = ctx.message.text.substring(11).trim(); // Bỏ qua '/force_post'
    const jobId = parseInt(text, 10);

    if (isNaN(jobId)) {
      return replyCommandGuidance(ctx, 'force_post', 'Mã tác vụ (Job ID) không hợp lệ hoặc trống');
    }

    const job = await prisma.videoPipelineJobs.findUnique({
      where: { id: jobId }
    });

    if (!job) {
      return ctx.reply(`❌ LỖI HỆ THỐNG: Không tìm thấy tác vụ Job #${jobId} trong cơ sở dữ liệu.`);
    }

    const confirmation = createConfirmation(
      ctx.chat.id,
      'force_publish',
      `Yêu cầu xuất bản ngay lập tức tác vụ Job #${jobId}. Hệ thống tự động lập lịch sẽ bảo lưu khoảng giãn cách xuất bản an toàn.`,
      { jobId },
    );

    await ctx.reply(
      `❓ XÁC NHẬN YÊU CẦU XUẤT BẢN NGAY:\n━━━━━━━━━━━━━━━━━━━━━\n${confirmation.summary}`,
      Markup.inlineKeyboard([
        Markup.button.callback('✅ Xác nhận', `confirm:${confirmation.id}`),
        Markup.button.callback('❌ Hủy bỏ', `deny:${confirmation.id}`),
      ]),
    );

  } catch (error: any) {
    console.error('[Bot Error] Error forcing post:', error);
    ctx.reply(`❌ Đã xảy ra lỗi khi yêu cầu đăng ngay: ${error.message}`);
  }
});

bot.on('text', async (ctx) => {
  try {
    const text = ctx.message.text.trim();
    const chatId = ctx.chat?.id;

    // --- Ưu tiên 1: Xử lý nhập tiêu đề mới khi đang chỉnh sửa Calendar Job ---
    if (chatId && calendarEditStates.has(chatId)) {
      if (!text.startsWith('/')) {
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
    }

    // --- Ưu tiên 2: Xử lý nhập ngày thủ công khi đang ở trạng thái awaiting_calendar_date ---
    if (chatId && calendarInputStates.has(chatId)) {
      if (!text.startsWith('/')) {
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
    }

    // --- Ưu tiên 3: Xử lý Wizard Campaign ---
    if (chatId && campaignWizards.has(chatId)) {
      if (!text.startsWith('/')) {
        return handleCampaignWizardStep(ctx, text);
      }
    }

    if (!text || text.startsWith('/')) return;
    const lower = text.toLowerCase();

    if (
      lower.includes('menu') ||
      lower.includes('bảng điều khiển') ||
      lower.includes('bang dieu khien') ||
      lower.includes('mở bảng') ||
      lower.includes('mo bang')
    ) {
      return ctx.reply(getControlCenterMessage(), controlCenterKeyboard);
    }

    if (
      lower.includes('mẫu') ||
      lower.includes('mau') ||
      lower.includes('template') ||
      lower.includes('cách dùng') ||
      lower.includes('cach dung')
    ) {
      if (lower.includes('trend') || lower.includes('remix') || lower.includes('bass')) {
        const suggestedJobId = await getSuggestedJobId();
        return ctx.reply(getTrendingTemplateMessage(suggestedJobId), trendTemplateKeyboard(suggestedJobId));
      }
      return ctx.reply(getTemplateMessage(), controlCenterKeyboard);
    }

    const intent = await parseBotIntent(text);
    await auditBotAction(null, 'BOT_INTENT', 'INFO', `User text: "${text}" -> ${JSON.stringify(intent)}`);

    if (intent.platform === 'youtube') {
      return ctx.reply('Mình nhận ra đây là yêu cầu YouTube. Hãy gửi tin nhắn này sang bot YouTube riêng để tránh đăng nhầm nền tảng.');
    }

    // --- Xử lý intent quick_create_video (NLU) ---
    if (intent.intent === 'quick_create_video') {
      const targetDate = intent.newTimeText || 'today';
      if (intent.topic) {
        const targetAudience = intent.targetAudience || 'Người xem TikTok Việt Nam quan tâm chủ đề này';
        await ctx.replyWithHTML(
          `🤖 <b>ĐÃ HIỂU YÊU CẦU TỰ NHIÊN</b>\n` +
          `━━━━━━━━━━━━━━━━━━━━━\n` +
          `▪️ Chủ đề: <b>${escapeHtml(intent.topic)}</b>\n` +
          `▪️ Đối tượng: <b>${escapeHtml(targetAudience)}</b>\n` +
          `▪️ Lịch: <b>${escapeHtml(formatNaturalTargetDate(targetDate))}</b>\n\n` +
          `Mình sẽ tự lên ý tưởng/kịch bản và đưa video vào hàng đợi render.`
        );
        return startCampaignLogic(ctx, intent.topic, targetAudience, targetDate, 'Chat tự nhiên');
      }

      if (chatId) {
        campaignWizards.set(chatId, { step: 'awaiting_topic', targetDate });
      }
      const dateLabel = formatNaturalTargetDate(targetDate);
      await ctx.replyWithHTML(
        `🤖 <b>NHẬN DIỆN Ý ĐỊNH: TẠO VIDEO CHO ${dateLabel}</b>\n` +
        `━━━━━━━━━━━━━━━━━━━━━\n` +
        `AI đã hiểu ý bạn! Hãy bắt đầu nhập thông tin:\n\n` +
        `✍️ <b>BƯỚC 1/2: NHẬP CHỦ ĐỀ VIDEO</b>\n` +
        `Hãy gửi tin nhắn nhập chủ đề cho video (Ví dụ: <i>Kinh nghiệm du lịch tự túc</i>, <i>Học tiếng Anh giao tiếp</i>,...)\n\n` +
        `👉 <i>Soạn /cancel để hủy bỏ bất kỳ lúc nào.</i>`,
        Markup.inlineKeyboard([
          [Markup.button.callback('❌ Hủy bỏ', 'camp_wizard:cancel')],
        ]),
      );
      return;
    }

    if (intent.intent === 'view_schedule') {
      return ctx.reply(await getScheduleReport(intent.period || 'today'));
    }

    if (intent.intent === 'view_status') {
      return ctx.reply(await getStatusReport());
    }

    if (intent.intent === 'list_pending_approval') {
      return ctx.reply(await getPendingApprovalReport());
    }

    if (intent.intent === 'preview_video') {
      const jobId = await resolveJobId(intent);
      if (!jobId) return replyCommandGuidance(ctx, 'preview', 'Không thể nhận diện mã định danh tác vụ để xem trước');
      return handlePreviewLogic(ctx, jobId);
    }

    if (intent.intent === 'explain_job') {
      const jobId = await resolveJobId(intent);
      if (!jobId) return replyCommandGuidance(ctx, 'logs', 'Không thể nhận diện mã định danh tác vụ để truy xuất chi tiết');
      return ctx.reply(await getJobDetails(jobId));
    }

    if (intent.intent === 'recommend_schedule') {
      return ctx.reply(await getRecommendation());
    }

    if (intent.intent === 'render_music') {
      const jobId = await resolveJobId(intent);
      if (!jobId) return replyCommandGuidance(ctx, 'render_music', 'Không thể nhận diện mã định danh tác vụ để kết xuất');
      return enqueueMusicReactiveRender(ctx, jobId);
    }

    if (intent.intent === 'create_music_video') {
      return handleCreateMusicVideoLogic(ctx, intent.songTitle || 'HOT TRENDING', intent.artistName || 'AUTO DETECT');
    }

    const actionSummary = await buildActionSummary(intent);
    if (actionSummary) {
      const confirmation = createConfirmation(
        ctx.chat.id,
        actionSummary.action,
        actionSummary.summary,
        actionSummary.payload,
      );

      return ctx.reply(
        `❓ XÁC NHẬN YÊU CẦU THỰC THI NGHIỆP VỤ:\n━━━━━━━━━━━━━━━━━━━━━\n${confirmation.summary}`,
        Markup.inlineKeyboard([
          Markup.button.callback('✅ Xác nhận', `confirm:${confirmation.id}`),
          Markup.button.callback('❌ Hủy bỏ', `deny:${confirmation.id}`),
        ]),
      );
    }

    return ctx.reply(
      `⚠️ KHÔNG THỂ XÁC ĐỊNH Ý ĐỊNH YÊU CẦU: Ý định/Chỉ thị chưa được định nghĩa trong hệ thống nhận diện.\n\n` +
      `Khuyến nghị sử dụng các cú pháp tự nhiên mẫu sau:\n` +
      `▪️ Tra cứu lịch trình: "Xem lịch hôm nay"\n` +
      `▪️ Kiểm duyệt tác vụ: "Video nào chờ duyệt"\n` +
      `▪️ Thực thi Remix: "Remix nhạc job 31 thêm bass"\n` +
      `▪️ Dời lịch đăng: "Dời job 31 sang 2026-05-22 19:30"\n` +
      `▪️ Tạo video nhanh: "Tạo video cho hôm nay" hoặc "Làm clip ngày mai"\n\n` +
      `Hoặc gõ lệnh /menu để truy cập Bảng điều khiển hệ thống trực quan.`,
      controlCenterKeyboard,
    );
  } catch (error: any) {
    console.error('[Bot Error] Error handling natural language message:', error);
    ctx.reply(`❌ Không thể xử lý yêu cầu chat: ${error.message}`);
  }
});

// Xử lý nút bấm từ Inline Keyboard
bot.on('callback_query', async (ctx) => {
  const callbackData = (ctx.callbackQuery as any).data;
  if (!callbackData) return;

  const parts = callbackData.split(':');
  const [action, jobIdStr] = parts;

  if (action === 'cancel_active') {
    const chatId = ctx.chat?.id;
    if (!chatId) {
      await ctx.answerCbQuery('Không thể xác định chat hiện tại.', { show_alert: true });
      return;
    }
    const parsedJobId = /^\d+$/.test(jobIdStr || '') ? parseInt(jobIdStr, 10) : null;
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

  if (action === 'music_visual') {
    try {
      const mode = parts[1];
      const jobId = parseInt(parts[2], 10);
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
      return;
    }
  }

  if (action === 'tpl') {
    try {
      const presetKey = parts[1];
      const jobId = parseInt(parts[2], 10);
      if (isNaN(jobId)) {
        await ctx.answerCbQuery('LỖI: Không xác định được tác vụ Job.', { show_alert: true });
        return;
      }

      const metadata = await applyTrendPreset(jobId, presetKey);
      await ctx.answerCbQuery('Đã áp dụng mẫu cấu hình thành công.');
      const mode = presetKey === 'render_only' ? 'render' : 'remix';
      return ctx.reply(
        `✅ THIẾT LẬP CẤU HÌNH THÀNH CÔNG (JOB #${jobId})\n━━━━━━━━━━━━━━━━━━━━━\n` +
        `▪️ Chế độ Render: \`${metadata.render_mode}\`\n` +
        `▪️ Phong cách Remix: \`${metadata.remix_style || 'Nguyên bản'}\`\n` +
        `▪️ Nhạc cảm (Mood): \`${metadata.mood || 'Mặc định'}\`\n` +
        `▪️ Nhịp điệu (BPM): \`${metadata.bpm || 'Tự động'}\`\n\n` +
        `Lựa chọn hành động vận hành tiếp theo bên dưới:`,
        postTemplateKeyboard(jobId, mode),
      );
    } catch (e: any) {
      await ctx.answerCbQuery(`Lỗi: ${e.message}`, { show_alert: true });
      return;
    }
  }

  if (action === 'create_tpl') {
    try {
      const presetKey = jobIdStr;
      const job = await createVideoFromTrendTemplate(ctx.chat?.id || 'unknown', presetKey);
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
      return;
    }
  }

  if (action === 'start_render') {
    const jobId = parseInt(jobIdStr, 10);
    if (isNaN(jobId)) {
      await ctx.answerCbQuery('LỖI: Không xác định được tác vụ Job.', { show_alert: true });
      return;
    }
    await ctx.answerCbQuery('Đang đưa tác vụ vào hàng đợi kết xuất.');
    await enqueueMusicReactiveRender(ctx, jobId);
    return;
  }

  if (action === 'start_remix') {
    try {
      const jobId = parseInt(jobIdStr, 10);
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
        `❓ XÁC NHẬN YÊU CẦU THỰC THI REMIX:\n━━━━━━━━━━━━━━━━━━━━━\n${confirmation.summary}`,
        Markup.inlineKeyboard([
          Markup.button.callback('✅ Xác nhận', `confirm:${confirmation.id}`),
          Markup.button.callback('❌ Hủy bỏ', `deny:${confirmation.id}`),
        ]),
      );
    } catch (e: any) {
      await ctx.answerCbQuery(`Lỗi: ${e.message}`, { show_alert: true });
    }
    return;
  }

  if (action === 'show_config') {
    const jobId = parseInt(jobIdStr, 10);
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

  if (action === 'preview') {
    const jobId = parseInt(jobIdStr, 10);
    if (isNaN(jobId)) {
      await ctx.answerCbQuery('LỖI: Không xác định được tác vụ Job.', { show_alert: true });
      return;
    }
    await ctx.answerCbQuery();
    return handlePreviewLogic(ctx, jobId);
  }

  if (action === 'retry_publish') {
    const jobId = parseInt(jobIdStr, 10);
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

  if (action === 'camp_wizard') {
    try {
      const chatId = ctx.chat?.id;
      if (!chatId) {
        await ctx.answerCbQuery('Không thể xác định thông tin chat.', { show_alert: true });
        return;
      }

      if (jobIdStr === 'start') {
        campaignWizards.set(chatId, { step: 'awaiting_topic' });
        await ctx.answerCbQuery();
        await ctx.replyWithHTML(
          `✍️ <b>BƯỚC 1/2: NHẬP CHỦ ĐỀ CHIẾN DỊCH</b>\n` +
          `━━━━━━━━━━━━━━━━━━━━━\n` +
          `Hãy gửi tin nhắn nhập chủ đề cho chiến dịch video (Ví dụ: <i>Kinh nghiệm du lịch tự túc</i>, <i>Học tiếng Anh giao tiếp</i>,...)\n\n` +
          `👉 <i>Soạn /cancel hoặc bấm nút bên dưới để hủy bỏ bất kỳ lúc nào.</i>`,
          Markup.inlineKeyboard([
            [Markup.button.callback('❌ Hủy bỏ', 'camp_wizard:cancel')]
          ])
        );
        return;
      }

      if (jobIdStr === 'cancel') {
        campaignWizards.delete(chatId);
        calendarEditStates.delete(chatId);
        calendarInputStates.delete(chatId);
        await ctx.answerCbQuery();
        await ctx.reply('❌ Đã hủy bỏ quá trình thiết lập chiến dịch.');
        return;
      }

      if (jobIdStr === 'launch') {
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

      if (jobIdStr === 'launch_today' || jobIdStr === 'launch_tomorrow') {
        const wizard = campaignWizards.get(chatId);
        if (!wizard || !wizard.topic || !wizard.target) {
          await ctx.answerCbQuery('Lỗi: Không tìm thấy thông tin chiến dịch.', { show_alert: true });
          return;
        }
        const dateStr = jobIdStr === 'launch_today' ? 'today' : 'tomorrow';
        await ctx.answerCbQuery();
        await startCampaignLogic(ctx, wizard.topic, wizard.target, dateStr);
        campaignWizards.delete(chatId);
        return;
      }
    } catch (e: any) {
      await ctx.answerCbQuery(`Lỗi: ${e.message}`, { show_alert: true });
    }
    return;
  }

  if (action === 'calendar') {
    try {
      const chatId = ctx.chat?.id;
      if (!chatId) {
        await ctx.answerCbQuery('Không thể xác định thông tin chat.', { show_alert: true });
        return;
      }

      if (jobIdStr === 'menu') {
        await ctx.answerCbQuery();
        await ctx.replyWithHTML(
          `📅 <b>QUẢN LÝ LỊCH TRÌNH VIDEO</b>\n` +
          `━━━━━━━━━━━━━━━━━━━━━\n` +
          `Chào mừng bạn đến với trung tâm quản lý lịch trình phát video. Tại đây bạn có thể kiểm tra danh sách video đã lên lịch, chỉnh sửa tiêu đề hoặc xóa các video cũ theo từng ngày.\n\n` +
          `👇 Hãy chọn một mốc thời gian hoặc hành động bên dưới:`,
          getCalendarMenuKeyboard()
        );
        return;
      }

      if (jobIdStr === 'date') {
        const dateStr = parts.slice(2).join(':'); // e.g. calendar:date:YYYY-MM-DD
        await ctx.answerCbQuery();
        await renderCalendarDateView(ctx, dateStr);
        return;
      }

      if (jobIdStr === 'view_7days') {
        await ctx.answerCbQuery();
        const buttons = [];
        for (let i = 0; i < 7; i++) {
          const date = new Date(Date.now() + i * 24 * 60 * 60 * 1000);
          const dateStr = date.toLocaleDateString('sv-SE', { timeZone: 'Asia/Ho_Chi_Minh' });
          const formattedDate = dateStr.split('-').reverse().slice(0, 2).join('/');
          const weekday = i === 0 ? 'Hôm Nay' : i === 1 ? 'Ngày Mai' : `Thứ ${date.getDay() === 0 ? 'CN' : date.getDay() + 1}`;
          buttons.push([Markup.button.callback(`📅 ${weekday} (${formattedDate})`, `calendar:date:${dateStr}`)]);
        }
        buttons.push([Markup.button.callback('⬅️ Về Lịch Trình', 'calendar:menu')]);
        
        await ctx.replyWithHTML(
          `📅 <b>CHỌN NGÀY LÊN LỊCH (7 NGÀY TỚI)</b>\n` +
          `━━━━━━━━━━━━━━━━━━━━━\n` +
          `Chọn một ngày bên dưới để xem hoặc thêm/sửa/xóa video:`,
          Markup.inlineKeyboard(buttons)
        );
        return;
      }

      if (jobIdStr === 'custom_input') {
        calendarInputStates.set(chatId, { step: 'awaiting_date' });
        await ctx.answerCbQuery();
        await ctx.replyWithHTML(
          `🔍 <b>NHẬP NGÀY CẦN QUẢN LÝ</b>\n` +
          `━━━━━━━━━━━━━━━━━━━━━\n` +
          `Vui lòng nhập ngày theo định dạng <b>YYYY-MM-DD</b> (Ví dụ: <code>2026-05-22</code>).\n\n` +
          `👉 <i>Hoặc gõ /calendar để quay lại menu chính.</i>`
        );
        return;
      }
    } catch (e: any) {
      await ctx.answerCbQuery(`Lỗi: ${e.message}`, { show_alert: true });
    }
    return;
  }

  if (action === 'cal_create') {
    try {
      const chatId = ctx.chat?.id;
      if (!chatId) {
        await ctx.answerCbQuery('Không thể xác định thông tin chat.', { show_alert: true });
        return;
      }
      const targetDate = jobIdStr; // cal_create:YYYY-MM-DD
      campaignWizards.set(chatId, { step: 'awaiting_topic', targetDate });
      await ctx.answerCbQuery();
      await ctx.replyWithHTML(
        `✍️ <b>BƯỚC 1/2: NHẬP CHỦ ĐỀ CHO VIDEO NGÀY ${targetDate.split('-').reverse().join('/')}</b>\n` +
        `━━━━━━━━━━━━━━━━━━━━━\n` +
        `Hãy gửi tin nhắn nhập chủ đề cho video (Ví dụ: <i>Kinh nghiệm du lịch tự túc</i>, <i>Học tiếng Anh giao tiếp</i>,...)\n\n` +
        `👉 <i>Soạn /cancel hoặc bấm nút bên dưới để hủy bỏ bất kỳ lúc nào.</i>`,
        Markup.inlineKeyboard([
          [Markup.button.callback('❌ Hủy bỏ', 'camp_wizard:cancel')]
        ])
      );
    } catch (e: any) {
      await ctx.answerCbQuery(`Lỗi: ${e.message}`, { show_alert: true });
    }
    return;
  }

  if (action === 'cal_edit') {
    try {
      const chatId = ctx.chat?.id;
      if (!chatId) {
        await ctx.answerCbQuery('Không thể xác định thông tin chat.', { show_alert: true });
        return;
      }
      const jobId = parseInt(jobIdStr, 10);
      if (isNaN(jobId)) {
        await ctx.answerCbQuery('Lỗi: Mã công việc không hợp lệ.', { show_alert: true });
        return;
      }

      calendarEditStates.set(chatId, { jobId });
      await ctx.answerCbQuery();
      await ctx.replyWithHTML(
        `✏️ <b>SỬA TIÊU ĐỀ VIDEO JOB #${jobId}</b>\n` +
        `━━━━━━━━━━━━━━━━━━━━━\n` +
        `Vui lòng soạn và gửi tin nhắn chứa tiêu đề mới cho video này.\n\n` +
        `👉 <i>Hoặc gõ /calendar để quay lại menu chính.</i>`
      );
    } catch (e: any) {
      await ctx.answerCbQuery(`Lỗi: ${e.message}`, { show_alert: true });
    }
    return;
  }

  if (action === 'cal_delete') {
    try {
      const jobId = parseInt(jobIdStr, 10);
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
        `❓ <b>XÁC NHẬN YÊU CẦU XÓA VIDEO JOB #${jobId}</b>:\n━━━━━━━━━━━━━━━━━━━━━\n${confirmation.summary}`,
        Markup.inlineKeyboard([
          Markup.button.callback('✅ Xác nhận', `confirm:${confirmation.id}`),
          Markup.button.callback('❌ Hủy bỏ', `deny:${confirmation.id}`),
        ])
      );
    } catch (e: any) {
      await ctx.answerCbQuery(`Lỗi: ${e.message}`, { show_alert: true });
    }
    return;
  }

  if (action === 'camp_preset') {
    try {
      const presetKey = jobIdStr;
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

      await ctx.answerCbQuery(`Khởi chạy chiến dịch: ${preset.label}`);
      await startCampaignLogic(ctx, preset.topic, preset.target, 'today', preset.label);
    } catch (e: any) {
      await ctx.answerCbQuery(`Lỗi: ${e.message}`, { show_alert: true });
    }
    return;
  }

  if (action === 'quick') {
    try {
      await ctx.answerCbQuery();
      if (jobIdStr === 'status') {
        return ctx.reply(await getStatusReport(), controlCenterKeyboard);
      }
      if (jobIdStr === 'schedule_today') {
        return ctx.reply(await getScheduleReport('today'), controlCenterKeyboard);
      }
      if (jobIdStr === 'schedule_week') {
        return ctx.reply(await getScheduleReport('week'), controlCenterKeyboard);
      }
      if (jobIdStr === 'pending') {
        return ctx.reply(await getPendingApprovalReport(), controlCenterKeyboard);
      }
      if (jobIdStr === 'templates') {
        return ctx.reply(getTemplateMessage(), controlCenterKeyboard);
      }
      if (jobIdStr === 'trend_templates') {
        const suggestedJobId = await getSuggestedJobId();
        return ctx.reply(getTrendingTemplateMessage(suggestedJobId), trendTemplateKeyboard(suggestedJobId));
      }
      if (jobIdStr === 'recommend') {
        return ctx.reply(await getRecommendation(), controlCenterKeyboard);
      }
      return ctx.reply(getControlCenterMessage(), controlCenterKeyboard);
    } catch (e: any) {
      await ctx.answerCbQuery(`Lỗi: ${e.message}`, { show_alert: true });
      return;
    }
  }

  if (action === 'confirm') {
    try {
      const confirmation = consumeConfirmation(jobIdStr);
      if (!confirmation) {
        return ctx.answerCbQuery('LỖI: Xác nhận yêu cầu đã hết hạn hoặc không tồn tại.', { show_alert: true });
      }

      const result = await executeConfirmedAction(confirmation.action, confirmation.payload);
      await ctx.answerCbQuery('Đã phê duyệt thực thi hành động.');
      await ctx.editMessageText(result);
    } catch (e: any) {
      await ctx.answerCbQuery(`❌ Lỗi: ${e.message}`, { show_alert: true });
    }
    return;
  }

  if (action === 'deny') {
    cancelConfirmation(jobIdStr);
    await ctx.answerCbQuery('Đã hủy bỏ thực thi hành động.');
    await ctx.editMessageText('❌ YÊU CẦU ĐÃ BỊ HỦY BỎ. Không có bất kỳ thay đổi nào được ghi nhận vào hệ thống.');
    return;
  }

  const jobId = parseInt(jobIdStr, 10);

  if (action === 'approve_post') {
    try {
      const confirmation = createConfirmation(
        ctx.chat?.id || 'unknown',
        'approve_publish',
        `Phê duyệt xuất bản video Job #${jobId} lên TikTok Studio. Hệ thống lập lịch vẫn sẽ tự động giãn cách an toàn.`,
        { jobId },
      );

      await ctx.answerCbQuery('Yêu cầu xác nhận phê duyệt xuất bản.');
      await ctx.reply(
        `❓ XÁC NHẬN PHÊ DUYỆT XUẤT BẢN VIDEO:\n━━━━━━━━━━━━━━━━━━━━━\n${confirmation.summary}`,
        Markup.inlineKeyboard([
          Markup.button.callback('✅ Xác nhận', `confirm:${confirmation.id}`),
          Markup.button.callback('❌ Hủy bỏ', `deny:${confirmation.id}`),
        ]),
      );
    } catch (e: any) {
      await ctx.answerCbQuery(`❌ Lỗi: ${e.message}`, { show_alert: true });
    }
  } else if (action === 'cancel_job') {
    try {
      const confirmation = createConfirmation(
        ctx.chat?.id || 'unknown',
        'cancel_job',
        `Ngừng kích hoạt và hủy bỏ hoàn toàn tác vụ Job #${jobId}. Tác vụ này sẽ không được xử lý hoặc xuất bản.`,
        { jobId },
      );

      await ctx.answerCbQuery('Yêu cầu xác nhận hủy tác vụ.');
      await ctx.reply(
        `❓ XÁC NHẬN YÊU CẦU HỦY TÁC VỤ:\n━━━━━━━━━━━━━━━━━━━━━\n${confirmation.summary}`,
        Markup.inlineKeyboard([
          Markup.button.callback('✅ Xác nhận', `confirm:${confirmation.id}`),
          Markup.button.callback('❌ Hủy bỏ', `deny:${confirmation.id}`),
        ]),
      );
    } catch (e: any) {
      await ctx.answerCbQuery(`❌ Lỗi: ${e.message}`, { show_alert: true });
    }
  }
});
