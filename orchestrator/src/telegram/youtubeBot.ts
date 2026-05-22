import { Telegraf, Markup } from 'telegraf';
import dotenv from 'dotenv';
import prisma from '../database/db';
import { addJobToQueue } from '../queue/queue';
import { parseBotIntent } from './intentRouter';
import {
  auditBotAction,
  buildYouTubeMetadata,
  createOrUpdateYouTubePublishTarget,
  executeConfirmedAction,
  formatDateTime,
  getYouTubePendingApprovalReport,
  getYouTubeScheduleReport,
  parseScheduleTime,
  resolveJobId,
} from './botActions';
import { cancelConfirmation, consumeConfirmation, createConfirmation } from './confirmationStore';
import { getYouTubeTargetStatusCounts, parseTargetTags, updateYouTubeTarget } from '../database/publishTargetRepo';
import * as fs from 'fs';

dotenv.config();

function escapeHtml(unsafe: string): string {
  return unsafe
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

const token = process.env.YOUTUBE_TELEGRAM_BOT_TOKEN;
if (!token || token === 'YOUR_YOUTUBE_TELEGRAM_BOT_TOKEN_HERE') {
  console.warn('[YouTube Bot] WARNING: YOUTUBE_TELEGRAM_BOT_TOKEN is not configured. Bot will not start.');
}

export const youtubeBot = new Telegraf(token || '');

const youtubeMenu = Markup.inlineKeyboard([
  [
    Markup.button.callback('Trạng thái', 'yt:status'),
    Markup.button.callback('Lịch hôm nay', 'yt:schedule_today'),
  ],
  [
    Markup.button.callback('Lịch tuần', 'yt:schedule_week'),
    Markup.button.callback('Chờ duyệt', 'yt:pending'),
  ],
  [
    Markup.button.callback('Tạo YouTube Short', 'yt:create_short'),
    Markup.button.callback('Tạo video YouTube', 'yt:create_video'),
  ],
]);

const createWizards = new Map<number, { step: 'topic' | 'target'; targetDate: string; contentType: 'shorts' | 'video'; topic?: string }>();

function formatTargetDate(value: string) {
  const parsed = parseScheduleTime(value);
  if (parsed) return formatDateTime(parsed);
  if (value === 'today') return 'Hôm nay';
  if (value === 'tomorrow') return 'Ngày mai';
  return value;
}

async function getYouTubeStatusReport() {
  const counts = await getYouTubeTargetStatusCounts();
  const count = (status: string) => Number(counts.find((item) => item.status === status)?.count_value || 0);
  const total = counts.reduce((sum, item) => sum + Number(item.count_value || 0), 0);
  return (
    `TRẠNG THÁI YOUTUBE BOT\n` +
    `──────────────────────────────\n` +
    `• Tổng target YouTube: ${total}\n` +
    `• Chờ duyệt: ${count('PENDING_APPROVAL')}\n` +
    `• Đã duyệt/chờ đăng: ${count('APPROVED') + count('PUBLISH_QUEUED') + count('PUBLISHING')}\n` +
    `• Đã đăng: ${count('PUBLISHED')}\n` +
    `• Thất bại: ${count('FAILED')}`
  );
}

async function createYouTubeVideoJob(ctx: any, topic: string, targetAudience: string, targetDate: string, contentType: 'shorts' | 'video') {
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

  await createOrUpdateYouTubePublishTarget(job.id, scheduledTime, contentType);
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
  const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
  if (!job) return ctx.reply(`Không tìm thấy Job #${jobId}.`);
  if (!job.video_output_path || !fs.existsSync(job.video_output_path)) {
    return ctx.reply(`Job #${jobId} chưa có file video để preview.`);
  }

  const target = await createOrUpdateYouTubePublishTarget(jobId, job.scheduled_post_time, 'shorts');
  const metadata = buildYouTubeMetadata(job, 'shorts');
  const caption =
    `YOUTUBE PREVIEW - JOB #${jobId}\n` +
    `──────────────────────────────\n` +
    `Title: ${target.title || metadata.title}\n` +
    `Lịch: ${target.scheduled_publish_time ? formatDateTime(target.scheduled_publish_time) : 'Đăng ngay'}\n` +
    `Tags: ${(parseTargetTags(target.tags).length ? parseTargetTags(target.tags) : metadata.tags).join(', ')}`;

  await ctx.replyWithVideo(
    { source: job.video_output_path },
    {
      caption: caption.slice(0, 1024),
      reply_markup: {
        inline_keyboard: [
          [
            { text: 'Duyệt đăng YouTube', callback_data: `yt:approve:${jobId}` },
            { text: 'Hủy', callback_data: `yt:cancel_target:${target.id}` },
          ],
        ],
      },
    },
  );
}

async function approveYouTubePublish(ctx: any, jobId: number) {
  const job = await prisma.videoPipelineJobs.findUnique({ where: { id: jobId } });
  if (!job) return ctx.reply(`Không tìm thấy Job #${jobId}.`);
  const target = await createOrUpdateYouTubePublishTarget(jobId, job.scheduled_post_time, 'shorts');
  const confirmation = createConfirmation(
    ctx.chat.id,
    'approve_youtube_publish',
    `Duyệt đăng YouTube Job #${jobId}: "${target.title || job.video_title_idea || 'Video'}" lúc ${target.scheduled_publish_time ? formatDateTime(target.scheduled_publish_time) : 'ngay bây giờ'}.`,
    { jobId },
  );
  return ctx.reply(
    `XÁC NHẬN ĐĂNG YOUTUBE\n━━━━━━━━━━━━━━━━━━━━━\n${confirmation.summary}`,
    Markup.inlineKeyboard([
      Markup.button.callback('Xác nhận', `yt:confirm:${confirmation.id}`),
      Markup.button.callback('Hủy', `yt:deny:${confirmation.id}`),
    ]),
  );
}

youtubeBot.start((ctx) => ctx.reply('YouTube bot đã sẵn sàng.', youtubeMenu));
youtubeBot.command('menu', (ctx) => ctx.reply('BẢNG ĐIỀU KHIỂN YOUTUBE', youtubeMenu));
youtubeBot.command('status', async (ctx) => ctx.reply(await getYouTubeStatusReport()));
youtubeBot.command('schedule', async (ctx) => {
  const text = ctx.message.text.substring(9).toLowerCase();
  return ctx.reply(await getYouTubeScheduleReport(text.includes('week') || text.includes('tuần') ? 'week' : 'today'));
});
youtubeBot.command('pending', async (ctx) => ctx.reply(await getYouTubePendingApprovalReport()));
youtubeBot.command('preview', async (ctx) => {
  const jobId = parseInt(ctx.message.text.substring(8).trim(), 10);
  if (!jobId) return ctx.reply('Hãy nhập mã job, ví dụ: /preview 12');
  return previewYouTubeJob(ctx, jobId);
});
youtubeBot.command('approve', async (ctx) => {
  const jobId = parseInt(ctx.message.text.substring(8).trim(), 10);
  if (!jobId) return ctx.reply('Hãy nhập mã job, ví dụ: /approve 12');
  return approveYouTubePublish(ctx, jobId);
});

youtubeBot.on('text', async (ctx) => {
  try {
    const chatId = ctx.chat?.id;
    const text = ctx.message.text.trim();
    if (!text || text.startsWith('/')) return;

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
    if (['menu', 'youtube', 'yt'].includes(lower)) return ctx.reply('BẢNG ĐIỀU KHIỂN YOUTUBE', youtubeMenu);

    const intent = await parseBotIntent(text);
    await auditBotAction(null, 'YOUTUBE_BOT_INTENT', 'INFO', `User text: "${text}" -> ${JSON.stringify(intent)}`);

    if (intent.platform === 'tiktok') {
      return ctx.reply('Tin nhắn này có vẻ dành cho TikTok. Hãy gửi qua bot TikTok để tránh đăng nhầm nền tảng.');
    }

    if (intent.intent === 'view_schedule') return ctx.reply(await getYouTubeScheduleReport(intent.period || 'today'));
    if (intent.intent === 'view_status') return ctx.reply(await getYouTubeStatusReport());
    if (intent.intent === 'list_pending_approval') return ctx.reply(await getYouTubePendingApprovalReport());
    if (intent.intent === 'preview_video') {
      const jobId = await resolveJobId(intent);
      if (!jobId) return ctx.reply('Không tìm thấy job để preview.');
      return previewYouTubeJob(ctx, jobId);
    }
    if (intent.intent === 'approve_publish' || intent.intent === 'force_publish') {
      const jobId = await resolveJobId(intent);
      if (!jobId) return ctx.reply('Không tìm thấy job đã render để duyệt đăng YouTube.');
      return approveYouTubePublish(ctx, jobId);
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

    return ctx.reply('Mình chưa hiểu yêu cầu YouTube này. Bạn có thể nói: "lên kịch bản youtube short về AI hôm nay 5h chiều".', youtubeMenu);
  } catch (error: any) {
    console.error('[YouTube Bot] Error handling message:', error);
    return ctx.reply(`Không thể xử lý yêu cầu YouTube: ${error.message}`);
  }
});

youtubeBot.on('callback_query', async (ctx) => {
  try {
    const data = (ctx.callbackQuery as any).data || '';
    const chatId = ctx.chat?.id;
    if (!chatId) return;

    if (data === 'yt:status') return ctx.reply(await getYouTubeStatusReport());
    if (data === 'yt:schedule_today') return ctx.reply(await getYouTubeScheduleReport('today'));
    if (data === 'yt:schedule_week') return ctx.reply(await getYouTubeScheduleReport('week'));
    if (data === 'yt:pending') return ctx.reply(await getYouTubePendingApprovalReport());
    if (data === 'yt:create_short' || data === 'yt:create_video') {
      createWizards.set(chatId, { step: 'topic', targetDate: 'today', contentType: data === 'yt:create_short' ? 'shorts' : 'video' });
      await ctx.answerCbQuery();
      return ctx.reply('Hãy gửi chủ đề video YouTube bạn muốn tạo.');
    }
    if (data.startsWith('yt:approve:')) {
      await ctx.answerCbQuery();
      return approveYouTubePublish(ctx, parseInt(data.split(':')[2], 10));
    }
    if (data.startsWith('yt:cancel_target:')) {
      const targetId = parseInt(data.split(':')[2], 10);
      await updateYouTubeTarget(targetId, { status: 'CANCELLED' });
      await ctx.answerCbQuery('Đã hủy target YouTube.');
      return ctx.reply('Đã hủy lượt đăng YouTube này.');
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
