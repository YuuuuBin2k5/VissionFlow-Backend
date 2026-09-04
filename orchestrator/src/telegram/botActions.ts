import * as fs from 'fs';
import prisma from '../database/db';
import { addJobToQueue } from '../queue/queue';
import { computeSafePublishTime, schedulePublishWithSpacing } from '../scheduler/postingPolicy';
import { BotIntent } from './intentRouter';
import {
  createYouTubeTarget,
  deletePublishTarget,
  findActiveYouTubeTarget,
  findYouTubeTargetByConnection,
  findYouTubeTargets,
  getYouTubePendingTargets,
  getYouTubeTargetsForSchedule,
  parseTargetTags,
  updateYouTubeTarget,
  findTikTokTargets,
  updateTikTokTarget,
  getYouTubeTargetStatusCounts,
  createTikTokTarget,
  findActiveTikTokTarget,
  findTikTokTargetByConnection,
} from '../database/publishTargetRepo';

const RENDERED_STATES = ['RENDERED', 'RENDERED_SUBTITLED'];
const FULLY_RENDERED_STATES = ['RENDERED', 'RENDERED_SUBTITLED', 'USER_APPROVED', 'PUBLISH_QUEUED', 'PUBLISHING', 'PUBLISHED'];
const ACTIVE_STATES = ['QUEUED', 'AI_PROCESSING', 'AI_PARSED', 'AUDIO_COMPOSED', 'ASSETS_READY', 'RENDERED', 'RENDERED_SUBTITLED', 'USER_APPROVED', 'PUBLISH_QUEUED', 'PUBLISHING'];
const YOUTUBE_ACTIVE_TARGET_STATES = ['PENDING_APPROVAL', 'APPROVED', 'PUBLISH_QUEUED', 'PUBLISHING'];

function parseJobMetadata(raw: any): Record<string, any> {
  try {
    const parsed = raw && typeof raw === 'string' ? JSON.parse(raw) : raw || {};
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function resolveAudioPath(job: { audio_file_path: string | null; scenes_layout_json: any }) {
  const metadata = parseJobMetadata(job.scenes_layout_json);
  return {
    metadata,
    audioPath: metadata.audio_path || metadata.remix_audio_path || job.audio_file_path,
  };
}

function formatDateTime(date: Date) {
  return date.toLocaleString('vi-VN', {
    hour: '2-digit',
    minute: '2-digit',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });
}

function startOfToday() {
  const date = new Date();
  date.setHours(0, 0, 0, 0);
  return date;
}

function addDays(date: Date, days: number) {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function parseScheduleTime(text?: string) {
  if (!text) return null;
  const trimmed = text.trim();
  const iso = trimmed.match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{1,2}):(\d{2})$/);
  if (iso) {
    return new Date(
      parseInt(iso[1], 10),
      parseInt(iso[2], 10) - 1,
      parseInt(iso[3], 10),
      parseInt(iso[4], 10),
      parseInt(iso[5], 10),
      0,
      0,
    );
  }

  const relative = trimmed.match(/^(today|tomorrow)\s+(\d{1,2}):(\d{2})$/i);
  if (relative) {
    const date = new Date();
    if (relative[1].toLowerCase() === 'tomorrow') date.setDate(date.getDate() + 1);
    date.setHours(parseInt(relative[2], 10), parseInt(relative[3], 10), 0, 0);
    return date;
  }

  return null;
}

export async function auditBotAction(jobId: number | null, step: string, level: 'INFO' | 'WARN' | 'ERROR' | 'SUCCESS', message: string) {
  await prisma.processRealtimeLogs.create({
    data: {
      job_id: jobId,
      execution_step: step,
      status_level: level,
      log_message: message,
    },
  });
}

export function escapeHtml(unsafe: string): string {
  return unsafe
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

export async function getStatusReport() {
  const jobs = await prisma.videoPipelineJobs.findMany({
    select: { pipeline_state: true },
  });
  const campaigns = await prisma.channelsCampaign.findMany({
    select: { status: true },
  });

  const count = (state: string) => jobs.filter((job) => job.pipeline_state === state).length;
  const processing = jobs.filter((job) => ['AI_PROCESSING', 'AI_PARSED', 'AUDIO_COMPOSED', 'ASSETS_READY'].includes(job.pipeline_state)).length;
  const rendered = jobs.filter((job) => RENDERED_STATES.includes(job.pipeline_state)).length;

  return (
    `<b>📊 TRẠNG THÁI HỆ THỐNG TIKTOK</b>\n` +
    `──────────────────────────────\n` +
    `• Tổng số tác vụ: <b>${jobs.length}</b>\n` +
    `  - Chờ xử lý: <code>${count('QUEUED')}</code>\n` +
    `  - Đang xử lý AI/Assets: <code>${processing}</code>\n` +
    `  - Chờ kiểm duyệt: <code>${rendered}</code>\n` +
    `  - Đã duyệt &amp; Chờ đăng: <code>${count('USER_APPROVED') + count('PUBLISH_QUEUED') + count('PUBLISHING')}</code>\n` +
    `  - Đã đăng: <code>${count('PUBLISHED')}</code>\n` +
    `  - Thất bại/Hủy: <code>${count('FAILED')}</code>\n\n` +
    `<b>🚀 CHIẾN DỊCH (CAMPAIGNS)</b>\n` +
    `• Đang chạy: <b>${campaigns.filter((c) => c.status === 'RUNNING').length}</b>\n` +
    `• Tạm dừng: <b>${campaigns.filter((c) => c.status === 'PAUSED').length}</b>\n` +
    `• Đã hủy: <b>${campaigns.filter((c) => c.status === 'CANCELLED').length}</b>`
  );
}

export async function getScheduleReport(period: 'today' | 'tomorrow' | 'week' = 'today') {
  const start = period === 'tomorrow' ? addDays(startOfToday(), 1) : startOfToday();
  const end = addDays(startOfToday(), period === 'week' ? 7 : (period === 'tomorrow' ? 2 : 1));
  const jobs = await prisma.videoPipelineJobs.findMany({
    where: {
      scheduled_post_time: { gte: start, lt: end },
    },
    include: { campaign: true },
    orderBy: { scheduled_post_time: 'asc' },
  });

  const periodLabel = period === 'today' ? 'HÔM NAY' : period === 'tomorrow' ? 'NGÀY MAI' : '7 NGÀY TỚI';
  if (jobs.length === 0) {
    return (
      `<b>📅 LỊCH PHÁT SÓNG TIKTOK (${periodLabel})</b>\n` +
      `──────────────────────────────\n` +
      `<i>Không có tác vụ nào được lên lịch.</i>`
    );
  }

  const title = `<b>📅 LỊCH PHÁT SÓNG TIKTOK (${periodLabel})</b>\n──────────────────────────────`;
  const lines = jobs.map((job) => (
    `• <b>Job #${job.id}</b> | <code>${formatDateTime(job.scheduled_post_time)}</code>\n` +
    `  - Trạng thái: <code>${escapeHtml(job.pipeline_state)}</code>\n` +
    `  - Ý tưởng: <i>${escapeHtml(job.video_title_idea || 'Chưa có tiêu đề')}</i>`
  ));

  return `${title}\n\n${lines.join('\n\n')}`;
}

export async function getPendingApprovalReport() {
  const jobs = await prisma.videoPipelineJobs.findMany({
    where: { pipeline_state: { in: RENDERED_STATES } },
    orderBy: { scheduled_post_time: 'asc' },
    take: 10,
  });

  if (jobs.length === 0) {
    return (
      `<b>⏳ VIDEO TIKTOK CHỜ DUYỆT (PENDING)</b>\n` +
      `──────────────────────────────\n` +
      `<i>Không có video nào đang chờ phê duyệt.</i>`
    );
  }

  return (
    `<b>⏳ VIDEO TIKTOK CHỜ DUYỆT (PENDING)</b>\n` +
    `──────────────────────────────\n` +
    `Phát hiện <b>${jobs.length}</b> video đang chờ kiểm duyệt:\n\n` +
    jobs.map((job) => (
      `• <b>Job #${job.id}</b> | Lịch: <code>${formatDateTime(job.scheduled_post_time)}</code>\n` +
      `  - Tiêu đề: <i>${escapeHtml(job.video_title_idea || 'Chưa có tiêu đề')}</i>\n` +
      `  - Xem trước: /preview_${job.id}`
    )).join('\n\n')
  );
}

function coerceJsonObject(raw: any): Record<string, any> {
  try {
    const parsed = raw && typeof raw === 'string' ? JSON.parse(raw) : raw || {};
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

export function detectJobContentType(job: any): 'shorts' | 'video' {
  const titleIdea = String(job.video_title_idea || '').toLowerCase();
  if (titleIdea.includes('short')) return 'shorts';

  try {
    const meta = typeof job.scenes_layout_json === 'string'
      ? JSON.parse(job.scenes_layout_json)
      : job.scenes_layout_json;
    if (meta && typeof meta === 'object') {
      if (Array.isArray(meta)) {
        const totalDuration = meta.reduce((sum: number, scene: any) => sum + (scene.duration || 0), 0);
        if (totalDuration > 0 && totalDuration <= 60) return 'shorts';
      } else {
        if (meta.content_type === 'video') return 'video';
        if (meta.content_type === 'shorts') return 'shorts';
        if (meta.platform_shape === 'vertical_9_16') return 'shorts';
      }
    }
  } catch {}

  try {
    const seo = typeof job.seo_tags_metadata === 'string'
      ? JSON.parse(job.seo_tags_metadata)
      : job.seo_tags_metadata;
    if (seo && typeof seo === 'object') {
      if (seo.platform_shape === 'vertical_9_16') return 'shorts';
      if (seo.retention_plan?.platform_shape === 'vertical_9_16') return 'shorts';
      if (seo.retention_plan?.retention_mode === 'campaign_short_form') return 'shorts';
    }
  } catch {}

  return 'shorts';
}

function cleanText(value: any) {
  return String(value || '')
    .replace(/[<>]/g, '')
    .replace(/\s+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function trimUtf8Bytes(input: string, maxBytes: number) {
  const encoder = new TextEncoder();
  if (encoder.encode(input).length <= maxBytes) return input;

  let output = '';
  for (const char of input) {
    const next = output + char;
    if (encoder.encode(next).length > maxBytes) break;
    output = next;
  }
  return output.trim();
}

function normalizeHashtags(raw: any, contentType: 'shorts' | 'video') {
  const source = Array.isArray(raw) ? [...raw] : [];
  const result: string[] = [];
  const seen = new Set<string>();

  if (contentType === 'shorts' && !source.some(tag => String(tag || '').toLowerCase() === 'shorts')) {
    source.unshift('Shorts');
  }

  for (const tag of source) {
    const cleaned = String(tag || '')
      .replace(/^#/, '')
      .replace(/\s+/g, '')
      .replace(/[^\p{L}\p{N}_]/gu, '')
      .trim();

    if (!cleaned) continue;

    const key = cleaned.toLowerCase();
    if (seen.has(key)) continue;

    seen.add(key);
    result.push(cleaned);

    if (result.length >= 8) break;
  }

  return result;
}

function normalizeApiTags(raw: any) {
  const source = Array.isArray(raw) ? raw : [];
  const result: string[] = [];
  const seen = new Set<string>();

  for (const tag of source) {
    const cleaned = String(tag || '')
      .replace(/^#/, '')
      .replace(/[<>]/g, '')
      .trim();

    if (!cleaned) continue;

    const key = cleaned.toLowerCase();
    if (seen.has(key)) continue;

    seen.add(key);
    result.push(cleaned);
  }

  return result;
}

function pickTitle(titleOptions: any[], fallback: string) {
  const candidates = Array.isArray(titleOptions)
    ? titleOptions.map(cleanText).filter(Boolean)
    : [];

  const good = candidates.find((title) => title.length <= 70)
    || candidates[0]
    || fallback;

  return cleanText(good);
}

function ensureShortsTitle(titleBase: string, shouldMarkShorts: boolean) {
  let title = cleanText(titleBase);

  // Shorts is a format, not title copy. Preserve legacy behavior only when it
  // is deliberately enabled by deployment configuration.
  if (shouldMarkShorts && process.env.AUTO_APPEND_SHORTS_HASHTAG === 'true' && !title.toLowerCase().includes('#shorts')) {
    const withShorts = `${title} #Shorts`;
    title = withShorts.length <= 100 ? withShorts : title;
  }

  return title.slice(0, 100).trim();
}

function buildFallbackDescription(params: {
  title: string;
  hook?: string;
  caption?: string;
  pinnedComment?: string;
  hashtags: string[];
}) {
  const hashtagLine = params.hashtags.map((tag) => `#${tag}`).join(' ');

  const intro =
    params.caption ||
    params.hook ||
    `Một video ngắn về ${params.title}.`;

  const body = [
    cleanText(intro),
    'Một góc nhìn nhẹ nhàng để bạn sống chậm lại, nhìn rõ hơn điều mình đang có và tìm thấy chút bình yên trong những điều rất nhỏ.',
    params.pinnedComment ? `Gợi ý suy ngẫm: ${cleanText(params.pinnedComment)}` : '',
    hashtagLine,
  ].filter(Boolean);

  return body.join('\n\n');
}

function trimApiTagsToLimit(tags: string[]) {
  const result: string[] = [];

  for (const tag of tags) {
    const next = [...result, tag];
    const serialized = next.join(',');

    if (serialized.length > 450) break;
    result.push(tag);
  }

  return result;
}

export function buildYouTubeMetadata(job: any, contentType: 'shorts' | 'video' = 'shorts') {
  const seo = coerceJsonObject(job.seo_tags_metadata);
  const meta = coerceJsonObject(job.scenes_layout_json);

  const shouldMarkShorts = contentType === 'shorts';

  const hashtags = normalizeHashtags(
    seo.youtube_hashtags || seo.hashtags || meta.music_hashtags,
    contentType
  );

  const apiTags = normalizeApiTags(
    seo.youtube_api_tags || seo.keyword_tags || seo.tags || seo.hashtags || hashtags
  );

  const firstTitleOption = seo.youtube_title_options && Array.isArray(seo.youtube_title_options) && seo.youtube_title_options.length > 0
    ? cleanText(seo.youtube_title_options[0])
    : '';

  const titleBase = firstTitleOption || pickTitle(
    seo.youtube_title_options,
    seo.title || meta.publish_caption || job.video_title_idea || `Video #${job.id}`
  );

  const title = ensureShortsTitle(titleBase, shouldMarkShorts);

  let description = cleanText(
    seo.youtube_scannable_description ||
    seo.youtube_description ||
    seo.description ||
    seo.caption_seo ||
    seo.caption
  );

  if (!description) {
    const fallbackCaption = seo.caption_seo || seo.caption || meta.caption || meta.publish_caption;
    description = buildFallbackDescription({
      title,
      hook: fallbackCaption ? undefined : job.hook_text_3s,
      caption: fallbackCaption,
      pinnedComment: seo.pinned_comment || meta.pinned_comment || job.pinned_comment,
      hashtags,
    });
  }

  return {
    title,
    description: trimUtf8Bytes(description, 4800),
    tags: trimApiTagsToLimit(apiTags),
  };
}

export async function createOrUpdateYouTubePublishTarget(
  jobId: number,
  scheduledTime?: Date | null,
  contentType?: 'shorts' | 'video',
  userId?: number | null,
  platformConnectionId?: number | null
) {
  const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
  if (!job) throw new Error(`Không tìm thấy Job #${jobId}.`);
  const resolvedContentType = contentType || detectJobContentType(job);
  const metadata = buildYouTubeMetadata(job, resolvedContentType);

  const existing = platformConnectionId
    ? await findYouTubeTargetByConnection(jobId, platformConnectionId)
    : await findActiveYouTubeTarget(jobId, YOUTUBE_ACTIVE_TARGET_STATES, userId);

  if (existing) {
    const seo = coerceJsonObject(job.seo_tags_metadata);
    const hasAISeo = Object.keys(seo).length > 0;
    return updateYouTubeTarget(existing.id, {
      user_id: existing.user_id || userId || null,
      platform_connection_id: existing.platform_connection_id || platformConnectionId || null,
      status: 'PENDING_APPROVAL',
      scheduled_publish_time: scheduledTime || job.scheduled_post_time || existing.scheduled_publish_time,
      title: hasAISeo ? metadata.title : (existing.title || metadata.title),
      description: hasAISeo ? metadata.description : (existing.description || metadata.description),
      tags: hasAISeo ? metadata.tags : (parseTargetTags(existing.tags).length ? parseTargetTags(existing.tags) : metadata.tags),
      error_log: null,
    });
  }

  return createYouTubeTarget({
    userId,
    platformConnectionId,
    jobId,
    scheduledTime: scheduledTime || job.scheduled_post_time || null,
    privacyStatus: process.env.YOUTUBE_DEFAULT_PRIVACY_STATUS || 'public',
    title: metadata.title,
    description: metadata.description,
    tags: metadata.tags,
  });
}

export async function createOrUpdateTikTokPublishTarget(
  jobId: number,
  scheduledTime?: Date | null,
  contentType?: 'shorts' | 'video',
  userId?: number | null,
  platformConnectionId?: number | null
) {
  const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
  if (!job) throw new Error(`Không tìm thấy Job #${jobId}.`);
  const resolvedContentType = contentType || detectJobContentType(job);
  const metadata = buildYouTubeMetadata(job, resolvedContentType); // Re-use general metadata helper

  const existing = platformConnectionId
    ? await findTikTokTargetByConnection(jobId, platformConnectionId)
    : await findActiveTikTokTarget(jobId, ['PENDING_APPROVAL', 'APPROVED', 'PUBLISH_QUEUED', 'PUBLISHING'], userId);

  if (existing) {
    const seo = coerceJsonObject(job.seo_tags_metadata);
    const hasAISeo = Object.keys(seo).length > 0;
    return updateTikTokTarget(existing.id, {
      user_id: existing.user_id || userId || null,
      platform_connection_id: existing.platform_connection_id || platformConnectionId || null,
      status: 'PENDING_APPROVAL',
      scheduled_publish_time: scheduledTime || job.scheduled_post_time || existing.scheduled_publish_time,
      title: hasAISeo ? metadata.title : (existing.title || metadata.title),
      description: hasAISeo ? metadata.description : (existing.description || metadata.description),
      tags: hasAISeo ? metadata.tags : (parseTargetTags(existing.tags).length ? parseTargetTags(existing.tags) : metadata.tags),
      error_log: null,
    });
  }

  return createTikTokTarget({
    userId,
    platformConnectionId,
    jobId,
    scheduledTime: scheduledTime || job.scheduled_post_time || null,
    privacyStatus: 'public',
    title: metadata.title,
    description: metadata.description,
    tags: metadata.tags,
  });
}


export async function getYouTubeStatusReport(userId?: number | null) {
  const counts = await getYouTubeTargetStatusCounts(userId);
  const count = (status: string) => Number(counts.find((item) => item.status === status)?.count_value || 0);
  const total = counts.reduce((sum, item) => sum + Number(item.count_value || 0), 0);
  return (
    `<b>📊 TRẠNG THÁI HỆ THỐNG YOUTUBE</b>\n` +
    `──────────────────────────────\n` +
    `• Tổng tác vụ YouTube: <b>${total}</b>\n` +
    `  - Chờ duyệt: <code>${count('PENDING_APPROVAL')}</code>\n` +
    `  - Đã duyệt/Chờ đăng: <code>${count('APPROVED') + count('PUBLISH_QUEUED') + count('PUBLISHING')}</code>\n` +
    `  - Đã đăng thành công: <code>${count('PUBLISHED')}</code>\n` +
    `  - Thất bại/Lỗi: <code>${count('FAILED')}</code>`
  );
}

export async function getYouTubeScheduleReport(period: 'today' | 'tomorrow' | 'week' = 'today', userId?: number | null) {
  const start = period === 'tomorrow' ? addDays(startOfToday(), 1) : startOfToday();
  const end = addDays(startOfToday(), period === 'week' ? 7 : (period === 'tomorrow' ? 2 : 1));
  const targets = await getYouTubeTargetsForSchedule(start, end, userId);

  const periodLabel = period === 'today' ? 'HÔM NAY' : period === 'tomorrow' ? 'NGÀY MAI' : '7 NGÀY TỚI';
  if (targets.length === 0) {
    return (
      `<b>📅 LỊCH PHÁT SÓNG YOUTUBE (${periodLabel})</b>\n` +
      `──────────────────────────────\n` +
      `<i>Không có video YouTube nào được lên lịch.</i>`
    );
  }

  return (
    `<b>📅 LỊCH PHÁT SÓNG YOUTUBE (${periodLabel})</b>\n` +
    `──────────────────────────────\n\n` +
    targets.map((target) => (
      `• <b>Job #${target.job_id}</b> | <code>${target.scheduled_publish_time ? formatDateTime(target.scheduled_publish_time) : 'Chưa có lịch'}</code>\n` +
      `  - Trạng thái: <code>${escapeHtml(target.status)}</code>\n` +
      `  - Tiêu đề: <i>${escapeHtml(target.title || target.video_title_idea || 'Chưa có tiêu đề')}</i>\n` +
      `  - Link: ${target.external_url ? `<a href="${escapeHtml(target.external_url)}">Xem Video</a>` : '<i>Chưa đăng</i>'}`
    )).join('\n\n')
  );
}

export async function getYouTubePendingApprovalReport(userId?: number | null) {
  const targets = await getYouTubePendingTargets(userId);

  if (targets.length === 0) {
    return (
      `<b>⏳ VIDEO YOUTUBE CHỜ DUYỆT (PENDING)</b>\n` +
      `──────────────────────────────\n` +
      `<i>Không có video YouTube nào đang chờ duyệt.</i>`
    );
  }

  return (
    `<b>⏳ VIDEO YOUTUBE CHỜ DUYỆT (PENDING)</b>\n` +
    `──────────────────────────────\n\n` +
    targets.map((target) => (
      `• <b>Job #${target.job_id}</b> | Lịch: <code>${target.scheduled_publish_time ? formatDateTime(target.scheduled_publish_time) : 'Chưa có lịch'}</code>\n` +
      `  - Tiêu đề: <i>${escapeHtml(target.title || target.video_title_idea || 'Chưa có tiêu đề')}</i>\n` +
      `  - Xem trước: /preview ${target.job_id}`
    )).join('\n\n')
  );
}

export async function getJobDetails(jobId: number) {
  const job = await prisma.videoPipelineJobs.findUnique({
    where: { id: jobId },
    include: { campaign: true },
  });

  if (!job) return `[!] Không tìm thấy tác vụ (Job #${jobId}) trong cơ sở dữ liệu.`;

  const hasOutput = Boolean(job.video_output_path && fs.existsSync(job.video_output_path));
  return (
    `CHI TIẾT TÁC VỤ (JOB #${job.id})\n` +
    `──────────────────────────────\n` +
    `• Ý tưởng: ${job.video_title_idea || 'Chưa thiết lập'}\n` +
    `• Chiến dịch: #${job.campaign_id || 'Không'} (Trạng thái: ${job.campaign?.status || 'N/A'})\n` +
    `• Ngày thứ: ${job.day_number}\n` +
    `• Lịch đăng: ${formatDateTime(job.scheduled_post_time)}\n` +
    `• Trạng thái: ${job.pipeline_state}\n` +
    `• Video file: ${hasOutput ? 'Đã render' : 'Chưa có'}\n` +
    `• Nhật ký lỗi: ${job.error_log_trace || 'Không có ghi nhận lỗi'}`
  );
}

export async function resolveJobId(intent: BotIntent) {
  if (intent.jobId) return intent.jobId;

  if (intent.target === 'latest_rendered') {
    const job = await prisma.videoPipelineJobs.findFirst({
      where: { pipeline_state: { in: FULLY_RENDERED_STATES } },
      orderBy: { updated_at: 'desc' },
    });
    return job?.id || null;
  }

  if (intent.target === 'latest_pending') {
    const job = await prisma.videoPipelineJobs.findFirst({
      where: { pipeline_state: { in: ACTIVE_STATES } },
      orderBy: { scheduled_post_time: 'asc' },
    });
    return job?.id || null;
  }

  return null;
}

export async function buildActionSummary(intent: BotIntent) {
  if (intent.intent === 'reschedule_video') {
    const jobId = await resolveJobId(intent);
    const newTime = parseScheduleTime(intent.newTimeText);
    if (!jobId || !newTime) return null;
    const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
    if (!job) return null;
    return {
      action: 'reschedule_video' as const,
      summary: `Dời lịch phát sóng Job #${jobId} từ ${formatDateTime(job.scheduled_post_time)} sang ${formatDateTime(newTime)}.`,
      payload: { jobId, newTimeIso: newTime.toISOString() },
    };
  }

  if (intent.intent === 'approve_publish' || intent.intent === 'force_publish') {
    const jobId = await resolveJobId(intent);
    if (!jobId) return null;
    const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
    if (!job) return null;
    let summary = `Phê duyệt phát hành video Job #${jobId} lên TikTok Studio (Hệ thống tự động xếp giãn cách an toàn).`;
    const payload: any = { jobId };
    if (intent.newTimeText) {
      const scheduledTime = resolveTimeWithContext(intent.newTimeText, job.scheduled_post_time || new Date());
      summary = `Phê duyệt phát hành video Job #${jobId} lên TikTok Studio, lịch đăng được đổi thành: ${formatDateTime(scheduledTime)} (Hệ thống tự động xếp giãn cách an toàn).`;
      payload.newTimeIso = scheduledTime.toISOString();
    }
    return {
      action: intent.intent,
      summary,
      payload,
    };
  }

  if (intent.intent === 'remix_music' || intent.intent === 'render_remix_music') {
    const jobId = await resolveJobId(intent);
    if (!jobId) return null;
    const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
    if (!job) return null;
    const { audioPath } = resolveAudioPath(job);
    if (!audioPath || !fs.existsSync(audioPath)) return null;
    return {
      action: 'remix_music' as const,
      summary: `Khởi tạo tác vụ video remix độc lập kế thừa từ gốc Job #${jobId} (áp dụng phong cách nhạc remix mới và render audio-reactive).`,
      payload: { jobId, rightsConfirmed: true },
    };
  }

  if (intent.intent === 'cancel_job') {
    const jobId = await resolveJobId(intent);
    if (!jobId) return null;
    return {
      action: 'cancel_job' as const,
      summary: `Hủy bỏ hoàn toàn tác vụ Job #${jobId} (Nội dung này sẽ không được xuất bản).`,
      payload: { jobId },
    };
  }

  if (intent.intent === 'pause_campaign' || intent.intent === 'resume_campaign' || intent.intent === 'cancel_campaign') {
    if (!intent.campaignId) return null;
    return {
      action: intent.intent,
      summary: `${intent.intent === 'pause_campaign' ? 'Tạm dừng hoạt động' : intent.intent === 'resume_campaign' ? 'Kích hoạt chạy lại' : 'Hủy bỏ toàn diện'} chiến dịch Campaign #${intent.campaignId}.`,
      payload: { campaignId: intent.campaignId },
    };
  }

  return null;
}

export async function executeConfirmedAction(action: string, payload: Record<string, any>) {
  if (action === 'approve_youtube_publish') {
    const target = await findActiveYouTubeTarget(payload.jobId, ['PENDING_APPROVAL'], payload.userId || null);
    if (!target) throw new Error(`Không tìm thấy YouTube publish target chờ duyệt cho Job #${payload.jobId}.`);
    const scheduledAt = target.scheduled_publish_time || new Date();
    const delayMs = Math.max(0, scheduledAt.getTime() - Date.now());
    await updateYouTubeTarget(target.id, { status: delayMs > 0 ? 'PUBLISH_QUEUED' : 'APPROVED', error_log: null });
    await addJobToQueue(payload.jobId, 'PUBLISH', delayMs, 'youtube');
    return `✅ Đã duyệt đăng YouTube cho Job #${payload.jobId}. ${delayMs > 0 ? `Sẽ đăng lúc ${formatDateTime(scheduledAt)}.` : 'Đang đưa vào hàng đợi upload.'}`;
  }

  if (action === 'approve_youtube_publish_all') {
    const targets = await findYouTubeTargets(payload.jobId, ['PENDING_APPROVAL'], payload.userId || null);
    if (targets.length === 0) throw new Error(`Không tìm thấy publish targets chờ duyệt cho Job #${payload.jobId}.`);

    const scheduledAt = payload.newTimeIso ? new Date(payload.newTimeIso) : (targets[0].scheduled_publish_time || new Date());
    const delayMs = Math.max(0, scheduledAt.getTime() - Date.now());

    for (const target of targets) {
      await updateYouTubeTarget(target.id, {
        status: delayMs > 0 ? 'PUBLISH_QUEUED' : 'APPROVED',
        scheduled_publish_time: scheduledAt,
        error_log: null
      });
      await addJobToQueue(payload.jobId, 'PUBLISH', delayMs, 'youtube', target.id);
    }

    return `✅ Đã duyệt đăng YouTube thành công cho Job #${payload.jobId} lên ${targets.length} tài khoản.\n` +
           `Lịch đăng: ${delayMs > 0 ? formatDateTime(scheduledAt) : 'Đang đưa vào hàng đợi upload.'}`;
  }

  if (action === 'approve_tiktok_publish_all') {
    const targets = await findTikTokTargets(payload.jobId, ['PENDING_APPROVAL', 'FAILED', 'APPROVED', 'PUBLISH_QUEUED'], payload.userId || null);
    if (targets.length === 0) throw new Error(`Không tìm thấy TikTok publish targets chờ duyệt cho Job #${payload.jobId}.`);

    const scheduledAt = payload.newTimeIso ? new Date(payload.newTimeIso) : (targets[0].scheduled_publish_time || new Date());
    const delayMs = Math.max(0, scheduledAt.getTime() - Date.now());

    for (const target of targets) {
      await updateTikTokTarget(target.id, {
        status: delayMs > 0 ? 'PUBLISH_QUEUED' : 'APPROVED',
        scheduled_publish_time: scheduledAt,
        error_log: null
      });
      await addJobToQueue(payload.jobId, 'PUBLISH', delayMs, 'tiktok', target.id);
    }

    return `✅ Đã duyệt đăng TikTok thành công cho Job #${payload.jobId} lên ${targets.length} tài khoản.\n` +
           `Lịch đăng: ${delayMs > 0 ? formatDateTime(scheduledAt) : 'Đang đưa vào hàng đợi upload.'}`;
  }

  if (action === 'reschedule_video') {
    const requestedTime = new Date(payload.newTimeIso);
    if (requestedTime.getTime() <= Date.now()) {
      throw new Error('Thời gian dời lịch phát sóng phải nằm trong tương lai.');
    }
    const job = await prisma.videoPipelineJobs.findUnique({ where: { id: payload.jobId } });
    if (!job) throw new Error(`Không tìm thấy tác vụ Job #${payload.jobId}.`);

    const blockingJobs = await prisma.videoPipelineJobs.findMany({
      where: {
        id: { not: payload.jobId },
        campaign_id: job.campaign_id,
        pipeline_state: { in: ['PUBLISHED', 'USER_APPROVED', 'PUBLISH_QUEUED', 'PUBLISHING'] },
      },
      select: { scheduled_post_time: true },
    });
    const newTime = computeSafePublishTime(
      requestedTime,
      blockingJobs.map((blockingJob) => blockingJob.scheduled_post_time),
    );

    await prisma.videoPipelineJobs.update({
      where: { id: payload.jobId },
      data: { scheduled_post_time: newTime },
    });
    await prisma.$executeRawUnsafe(
      `UPDATE publish_targets SET scheduled_publish_time = ? WHERE job_id = ? AND platform = 'youtube' AND status IN ('PENDING_APPROVAL', 'APPROVED', 'PUBLISH_QUEUED')`,
      newTime,
      payload.jobId,
    );
    await auditBotAction(payload.jobId, 'BOT_RESCHEDULE', 'SUCCESS', `Rescheduled job #${payload.jobId} from requested ${requestedTime.toISOString()} to ${newTime.toISOString()}.`);
    return newTime.getTime() === requestedTime.getTime()
      ? `[✓] Đã dời lịch phát sóng Job #${payload.jobId} sang: ${formatDateTime(newTime)}.`
      : `[✓] Đã dời lịch phát sóng Job #${payload.jobId}.\n[!] Tự động điều chỉnh sang: ${formatDateTime(newTime)} để đảm bảo giãn cách an toàn.`;
  }

  if (action === 'approve_publish' || action === 'force_publish') {
    const job = await prisma.videoPipelineJobs.findUnique({
      where: { id: payload.jobId },
      include: { campaign: true },
    });
    if (!job) throw new Error(`Không tìm thấy tác vụ Job #${payload.jobId}.`);
    const hasVideoFile = Boolean(job.video_output_path && fs.existsSync(job.video_output_path));
    if (!FULLY_RENDERED_STATES.includes(job.pipeline_state) && !(job.pipeline_state === 'FAILED' && hasVideoFile)) {
      throw new Error(`Tác vụ Job #${payload.jobId} chưa hoàn tất render, trạng thái hiện tại: ${job.pipeline_state}.`);
    }
    if (!hasVideoFile) {
      throw new Error(`Tác vụ Job #${payload.jobId} chưa có tệp video đầu ra.`);
    }
    if (job.campaign && ['PAUSED', 'CANCELLED'].includes(job.campaign.status)) {
      throw new Error(`Chiến dịch Campaign #${job.campaign.id} đang ở trạng thái ${job.campaign.status}, không thể xuất bản.`);
    }

    if (payload.newTimeIso) {
      const scheduledTime = new Date(payload.newTimeIso);
      await prisma.videoPipelineJobs.update({
        where: { id: payload.jobId },
        data: { scheduled_post_time: scheduledTime },
      });
    }

    const { safePublishTime, delayMs } = await schedulePublishWithSpacing(payload.jobId);
    await auditBotAction(payload.jobId, 'BOT_PUBLISH_APPROVED', 'SUCCESS', `Approved publish for job #${payload.jobId}.`);
    return delayMs > 0
      ? `[✓] Đã phê duyệt Job #${payload.jobId}.\n[i] Hệ thống xếp lịch phát sóng lúc: ${formatDateTime(safePublishTime)}.`
      : `[✓] Đã phê duyệt Job #${payload.jobId}.\n[i] Tiến hành đăng tải ngay lập tức.`;
  }

  if (action === 'cancel_job') {
    await prisma.videoPipelineJobs.update({
      where: { id: payload.jobId },
      data: { pipeline_state: 'FAILED', error_log_trace: 'User cancelled this job via AI Control Center.' },
    });
    await prisma.$executeRawUnsafe(
      `UPDATE publish_targets SET status = 'CANCELLED' WHERE job_id = ? AND platform = 'youtube' AND status IN ('PENDING_APPROVAL', 'APPROVED', 'PUBLISH_QUEUED')`,
      payload.jobId,
    );
    await auditBotAction(payload.jobId, 'BOT_CANCEL_JOB', 'SUCCESS', `Cancelled job #${payload.jobId}.`);
    return `[✓] Đã hủy bỏ tác vụ Job #${payload.jobId}.`;
  }

  if (action === 'cal_delete') {
    const job = await prisma.videoPipelineJobs.findUnique({ where: { id: payload.jobId } });
    const title = job ? job.video_title_idea : 'Unknown';
    await prisma.videoPipelineJobs.delete({
      where: { id: payload.jobId },
    });
    await auditBotAction(null, 'BOT_DELETE_JOB', 'SUCCESS', `Deleted job #${payload.jobId} (${title}) from Calendar.`);
    return `[✓] Đã xóa hoàn toàn tác vụ Job #${payload.jobId} khỏi cơ sở dữ liệu.`;
  }

  if (action === 'remix_music') {
    if (!payload.rightsConfirmed) {
      throw new Error('Cần xác nhận quyền sử dụng/remix audio trước khi tạo bản remix.');
    }

    const job = await prisma.videoPipelineJobs.findUnique({ where: { id: payload.jobId } });
    if (!job) throw new Error(`Không tìm thấy tác vụ Job #${payload.jobId}.`);

    const { metadata, audioPath } = resolveAudioPath(job);
    if (!audioPath || !fs.existsSync(audioPath)) {
      throw new Error(`Tác vụ Job #${payload.jobId} chưa có audio hợp lệ để remix.`);
    }

    const {
      background_video_path,
      audio_reactive_data_path,
      reactive_template_path,
      audio_path,
      remix_audio_path,
      detected_bpm,
      duration_seconds,
      source_audio_path,
      video_output_path,
      ...cleanMetadata
    } = metadata;

    const remixMetadata = {
      ...cleanMetadata,
      render_mode: 'music_remix_reactive',
      rights_confirmed: true,
      remix_style: cleanMetadata.remix_style || process.env.REMIX_STYLE || 'trend_bass',
      song_title: cleanMetadata.song_title || job.video_title_idea || `Job #${payload.jobId}`,
      artist_name: cleanMetadata.artist_name || 'AgentTiktok Remix',
      mood: cleanMetadata.mood || cleanMetadata.music_mood || 'CYBERPUNK_NIGHT',
    };

    const newJob = await prisma.videoPipelineJobs.create({
      data: {
        campaign_id: job.campaign_id,
        day_number: job.day_number,
        scheduled_post_time: new Date(Date.now() + 4 * 60 * 60 * 1000),
        video_title_idea: `[Remix] ${job.video_title_idea}`,
        hook_text_3s: job.hook_text_3s,
        full_voice_script: job.full_voice_script,
        scenes_layout_json: JSON.stringify(remixMetadata),
        audio_file_path: job.audio_file_path,
        pipeline_state: 'QUEUED',
      },
    });

    await addJobToQueue(newJob.id, 'RENDER');
    await auditBotAction(newJob.id, 'BOT_REMIX_MUSIC', 'SUCCESS', `Created new remix job #${newJob.id} cloned from original job #${payload.jobId} and enqueued it.`);
    
    return `[✓] Đã tạo thành công Job video remix (#${newJob.id}) từ gốc Job #${payload.jobId}.\n[i] Tác vụ đã được thêm vào hàng đợi render.`;
  }

  if (action === 'pause_campaign' || action === 'resume_campaign' || action === 'cancel_campaign') {
    const status = action === 'pause_campaign' ? 'PAUSED' : action === 'resume_campaign' ? 'RUNNING' : 'CANCELLED';
    await prisma.channelsCampaign.update({
      where: { id: payload.campaignId },
      data: { status },
    });
    if (action === 'cancel_campaign') {
      await prisma.videoPipelineJobs.updateMany({
        where: {
          campaign_id: payload.campaignId,
          pipeline_state: { in: ACTIVE_STATES },
        },
        data: {
          pipeline_state: 'FAILED',
          error_log_trace: 'Campaign was cancelled via AI Control Center.',
        },
      });
    }
    await auditBotAction(null, `BOT_${status}_CAMPAIGN`, 'SUCCESS', `Set campaign #${payload.campaignId} to ${status}.`);
    return `[✓] Chiến dịch Campaign #${payload.campaignId} đã chuyển sang trạng thái: ${status}.`;
  }

  throw new Error(`Unsupported confirmation action: ${action}`);
}

export async function getRecommendation() {
  const pending = await prisma.videoPipelineJobs.count({ where: { pipeline_state: { in: RENDERED_STATES } } });
  const approved = await prisma.videoPipelineJobs.count({ where: { pipeline_state: { in: ['USER_APPROVED', 'PUBLISH_QUEUED', 'PUBLISHING'] } } });
  const failed = await prisma.videoPipelineJobs.count({ where: { pipeline_state: 'FAILED' } });

  return (
    `ĐỀ XUẤT VẬN HÀNH\n` +
    `──────────────────────────────\n` +
    `• Kiểm duyệt: Hiện có ${pending} video cần duyệt. Hãy ưu tiên duyệt sớm để tránh lỡ lịch.\n` +
    `• Hàng đợi: Có ${approved} video đã duyệt đang chờ đăng. Khoảng cách thời gian đăng được tự động giãn cách an toàn.\n` +
    `• Sự cố: Có ${failed} video lỗi. Hãy chạy lệnh /logs <job_id> để kiểm tra.\n` +
    `• Mẹo: Khung giờ đăng 11:30 và 19:30 mang lại tỷ lệ giữ chân người xem tốt nhất.`
  );
}

export function resolveTimeWithContext(newTimeText: string, pendingTime: Date): Date {
  const parsed = parseScheduleTime(newTimeText);
  if (!parsed) return pendingTime;

  const lower = newTimeText.toLowerCase();
  const hasDayHint =
    lower.includes('today') ||
    lower.includes('tomorrow') ||
    lower.includes('mai') ||
    lower.includes('hom nay') ||
    lower.includes('nay') ||
    lower.includes('hom') ||
    /^\d{4}-\d{2}-\d{2}/.test(newTimeText);

  if (hasDayHint) {
    return parsed;
  } else {
    const target = new Date(pendingTime.getTime());
    target.setHours(parsed.getHours(), parsed.getMinutes(), 0, 0);
    return target;
  }
}

export { parseScheduleTime, formatDateTime };

