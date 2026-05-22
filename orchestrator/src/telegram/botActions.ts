import * as fs from 'fs';
import prisma from '../database/db';
import { addJobToQueue } from '../queue/queue';
import { computeSafePublishTime, schedulePublishWithSpacing } from '../scheduler/postingPolicy';
import { BotIntent } from './intentRouter';
import {
  createYouTubeTarget,
  findActiveYouTubeTarget,
  getYouTubePendingTargets,
  getYouTubeTargetsForSchedule,
  parseTargetTags,
  updateYouTubeTarget,
} from '../database/publishTargetRepo';

const RENDERED_STATES = ['RENDERED', 'RENDERED_SUBTITLED'];
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
    `TRẠNG THÁI HỆ THỐNG\n` +
    `──────────────────────────────\n` +
    `• Tổng số tác vụ: ${jobs.length}\n` +
    `  - Chờ xử lý: ${count('QUEUED')}\n` +
    `  - Đang xử lý AI/Assets: ${processing}\n` +
    `  - Chờ kiểm duyệt: ${rendered}\n` +
    `  - Đã duyệt & Chờ đăng: ${count('USER_APPROVED') + count('PUBLISH_QUEUED') + count('PUBLISHING')}\n` +
    `  - Đã đăng: ${count('PUBLISHED')}\n` +
    `  - Thất bại/Hủy: ${count('FAILED')}\n\n` +
    `CHIẾN DỊCH (CAMPAIGNS)\n` +
    `• Đang chạy: ${campaigns.filter((c) => c.status === 'RUNNING').length}\n` +
    `• Tạm dừng: ${campaigns.filter((c) => c.status === 'PAUSED').length}\n` +
    `• Đã hủy: ${campaigns.filter((c) => c.status === 'CANCELLED').length}`
  );
}

export async function getScheduleReport(period: 'today' | 'week' = 'today') {
  const start = startOfToday();
  const end = addDays(start, period === 'today' ? 1 : 7);
  const jobs = await prisma.videoPipelineJobs.findMany({
    where: {
      scheduled_post_time: { gte: start, lt: end },
    },
    include: { campaign: true },
    orderBy: { scheduled_post_time: 'asc' },
  });

  const periodLabel = period === 'today' ? 'HÔM NAY' : '7 NGÀY TỚI';
  if (jobs.length === 0) {
    return (
      `LỊCH PHÁT SÓNG (${periodLabel})\n` +
      `──────────────────────────────\n` +
      `Không có tác vụ nào được lên lịch.`
    );
  }

  const title = `LỊCH PHÁT SÓNG (${periodLabel})\n──────────────────────────────`;
  const lines = jobs.map((job) => (
    `• Job #${job.id} | ${formatDateTime(job.scheduled_post_time)}\n` +
    `  - Trạng thái: ${job.pipeline_state}\n` +
    `  - Nội dung: ${job.video_title_idea || 'Chưa có tiêu đề'}`
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
      `VIDEO CHỜ KIỂM DUYỆT (PENDING)\n` +
      `──────────────────────────────\n` +
      `Không có video nào đang chờ phê duyệt.`
    );
  }

  return (
    `VIDEO CHỜ KIỂM DUYỆT (PENDING)\n` +
    `──────────────────────────────\n` +
    `Phát hiện ${jobs.length} video đang chờ kiểm duyệt:\n\n` +
    jobs.map((job) => (
      `• Job #${job.id} | Lịch đăng: ${formatDateTime(job.scheduled_post_time)}\n` +
      `  - Tiêu đề: ${job.video_title_idea || 'Chưa có tiêu đề'}\n` +
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

function normalizeTags(tags: any): string[] {
  if (!Array.isArray(tags)) return [];
  const seen = new Set<string>();
  return tags
    .map((tag) => String(tag || '').replace(/^#/, '').trim())
    .filter(Boolean)
    .filter((tag) => {
      const key = tag.toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, 30);
}

export function buildYouTubeMetadata(job: any, contentType: 'shorts' | 'video' = 'shorts') {
  const seo = coerceJsonObject(job.seo_tags_metadata);
  const meta = coerceJsonObject(job.scenes_layout_json);
  const tags = normalizeTags(seo.hashtags || meta.music_hashtags || ['shorts', 'youtube', 'viral']);
  const shouldMarkShorts = contentType === 'shorts';
  if (shouldMarkShorts && !tags.some((tag) => tag.toLowerCase() === 'shorts')) tags.unshift('Shorts');

  const titleBase = seo.title || meta.publish_caption || job.video_title_idea || `Video #${job.id}`;
  const title = shouldMarkShorts && !String(titleBase).toLowerCase().includes('#shorts')
    ? `${titleBase} #Shorts`
    : String(titleBase);
  const hashtagLine = tags.map((tag) => `#${tag.replace(/\s+/g, '')}`).join(' ');
  const descriptionParts = [
    seo.description || meta.caption || meta.publish_caption || job.hook_text_3s || titleBase,
    hashtagLine,
  ].filter(Boolean);

  return {
    title: title.slice(0, 100),
    description: descriptionParts.join('\n\n').slice(0, 5000),
    tags,
  };
}

export async function createOrUpdateYouTubePublishTarget(jobId: number, scheduledTime?: Date | null, contentType: 'shorts' | 'video' = 'shorts') {
  const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
  if (!job) throw new Error(`Không tìm thấy Job #${jobId}.`);
  const metadata = buildYouTubeMetadata(job, contentType);

  const existing = await findActiveYouTubeTarget(jobId, YOUTUBE_ACTIVE_TARGET_STATES);

  if (existing) {
    return updateYouTubeTarget(existing.id, {
      scheduled_publish_time: scheduledTime || job.scheduled_post_time || existing.scheduled_publish_time,
      title: existing.title || metadata.title,
      description: existing.description || metadata.description,
      tags: parseTargetTags(existing.tags).length ? parseTargetTags(existing.tags) : metadata.tags,
    });
  }

  return createYouTubeTarget({
    jobId,
    scheduledTime: scheduledTime || job.scheduled_post_time || null,
    privacyStatus: process.env.YOUTUBE_DEFAULT_PRIVACY_STATUS || 'public',
    title: metadata.title,
    description: metadata.description,
    tags: metadata.tags,
  });
}

export async function getYouTubeScheduleReport(period: 'today' | 'week' = 'today') {
  const start = startOfToday();
  const end = addDays(start, period === 'today' ? 1 : 7);
  const targets = await getYouTubeTargetsForSchedule(start, end);

  if (targets.length === 0) return `LỊCH YOUTUBE (${period === 'today' ? 'HÔM NAY' : '7 NGÀY TỚI'})\n──────────────────────────────\nKhông có video YouTube nào được lên lịch.`;

  return `LỊCH YOUTUBE (${period === 'today' ? 'HÔM NAY' : '7 NGÀY TỚI'})\n──────────────────────────────\n\n` +
    targets.map((target) => (
      `• Job #${target.job_id} | ${target.scheduled_publish_time ? formatDateTime(target.scheduled_publish_time) : 'Chưa có lịch'}\n` +
      `  - Trạng thái: ${target.status}\n` +
      `  - Tiêu đề: ${target.title || target.video_title_idea || 'Chưa có tiêu đề'}\n` +
      `  - Link: ${target.external_url || 'Chưa đăng'}`
    )).join('\n\n');
}

export async function getYouTubePendingApprovalReport() {
  const targets = await getYouTubePendingTargets();

  if (targets.length === 0) return 'VIDEO YOUTUBE CHỜ DUYỆT\n──────────────────────────────\nKhông có video YouTube nào đang chờ duyệt.';

  return 'VIDEO YOUTUBE CHỜ DUYỆT\n──────────────────────────────\n\n' +
    targets.map((target) => (
      `• Job #${target.job_id} | ${target.scheduled_publish_time ? formatDateTime(target.scheduled_publish_time) : 'Chưa có lịch'}\n` +
      `  - Tiêu đề: ${target.title || target.video_title_idea || 'Chưa có tiêu đề'}\n` +
      `  - Xem trước: /preview ${target.job_id}`
    )).join('\n\n');
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
      where: { pipeline_state: { in: RENDERED_STATES } },
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
    return {
      action: intent.intent,
      summary: `Phê duyệt phát hành video Job #${jobId} lên TikTok Studio (Hệ thống tự động xếp giãn cách an toàn).`,
      payload: { jobId },
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
    const target = await findActiveYouTubeTarget(payload.jobId, ['PENDING_APPROVAL', 'FAILED']);
    if (!target) throw new Error(`Không tìm thấy YouTube publish target chờ duyệt cho Job #${payload.jobId}.`);
    const scheduledAt = target.scheduled_publish_time || new Date();
    const delayMs = Math.max(0, scheduledAt.getTime() - Date.now());
    await updateYouTubeTarget(target.id, { status: delayMs > 0 ? 'PUBLISH_QUEUED' : 'APPROVED', error_log: null });
    await addJobToQueue(payload.jobId, 'PUBLISH', delayMs, 'youtube');
    return `✅ Đã duyệt đăng YouTube cho Job #${payload.jobId}. ${delayMs > 0 ? `Sẽ đăng lúc ${formatDateTime(scheduledAt)}.` : 'Đang đưa vào hàng đợi upload.'}`;
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
    if (!RENDERED_STATES.includes(job.pipeline_state) && job.pipeline_state !== 'USER_APPROVED' && job.pipeline_state !== 'PUBLISH_QUEUED' && job.pipeline_state !== 'PUBLISHING') {
      throw new Error(`Tác vụ Job #${payload.jobId} chưa hoàn tất render, trạng thái hiện tại: ${job.pipeline_state}.`);
    }
    if (!job.video_output_path || !fs.existsSync(job.video_output_path)) {
      throw new Error(`Tác vụ Job #${payload.jobId} chưa có tệp video đầu ra.`);
    }
    if (job.campaign && ['PAUSED', 'CANCELLED'].includes(job.campaign.status)) {
      throw new Error(`Chiến dịch Campaign #${job.campaign.id} đang ở trạng thái ${job.campaign.status}, không thể xuất bản.`);
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

export { parseScheduleTime, formatDateTime };
