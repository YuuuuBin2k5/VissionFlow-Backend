import { Worker, Job } from 'bullmq';
import IORedis from 'ioredis';
import { spawn } from 'child_process';
import * as path from 'path';
import * as fs from 'fs';
import prisma from '../database/db';
import { YouTubePublisherService } from '../services/youtubePublisherService';
import {
  findActiveYouTubeTarget,
  parseTargetTags,
  updateActiveYouTubeTargets,
  updateYouTubeTarget,
} from '../database/publishTargetRepo';
import dotenv from 'dotenv';

dotenv.config();

const redisHost = process.env.REDIS_HOST || 'localhost';
const redisPort = parseInt(process.env.REDIS_PORT || '6379', 10);

const connection = new IORedis({
  host: redisHost,
  port: redisPort,
  maxRetriesPerRequest: null,
});

// Khởi tạo BullMQ Worker
export const tiktokWorker = new Worker(
  'tiktok_jobs',
  async (job: Job) => {
    const { jobId, type } = job.data;
    const platform = job.data.platform || 'tiktok';
    console.log(`[Queue Worker] Received job #${jobId} (Type: ${type}, Platform: ${platform})`);

    // Ghi nhận log bắt đầu xử lý
    await prisma.processRealtimeLogs.create({
      data: {
        job_id: type !== 'PLANNING' ? jobId : null,
        execution_step: `${type}_START`,
        status_level: 'INFO',
        log_message: `Bắt đầu tiến trình ${type} cho ID #${jobId}...`,
      },
    });

    if (type === 'PUBLISH' && platform === 'youtube') {
      try {
        const publishTarget = await findActiveYouTubeTarget(jobId, ['APPROVED', 'PUBLISH_QUEUED', 'PUBLISHING']);

        if (!publishTarget) {
          throw new Error(`No approved YouTube publish target found for job #${jobId}.`);
        }

        const jobForPublish = await prisma.videoPipelineJobs.findUnique({
          where: { id: jobId },
          include: { campaign: true },
        });
        if (!jobForPublish) throw new Error(`Video job #${jobId} was not found.`);

        const videoPath = jobForPublish.video_output_path;
        if (!videoPath || !fs.existsSync(videoPath)) {
          throw new Error(`Rendered video file was not found for job #${jobId}: ${videoPath || 'empty path'}`);
        }

        await updateYouTubeTarget(publishTarget.id, { status: 'PUBLISHING', error_log: null });

        const tags = parseTargetTags(publishTarget.tags);
        const publisher = new YouTubePublisherService();
        const result = await publisher.uploadVideo({
          videoPath,
          title: publishTarget.title || jobForPublish.video_title_idea || `Video #${jobId}`,
          description: publishTarget.description || '',
          tags,
          privacyStatus: publishTarget.privacy_status,
          scheduledPublishTime: publishTarget.scheduled_publish_time,
        });

        await updateYouTubeTarget(publishTarget.id, {
          status: 'PUBLISHED',
          external_video_id: result.videoId,
          external_url: result.url,
          error_log: null,
        });

        await prisma.processRealtimeLogs.create({
          data: {
            job_id: jobId,
            execution_step: 'YOUTUBE_PUBLISH_SUCCESS',
            status_level: 'SUCCESS',
            log_message: `Published YouTube video: ${result.url}`,
          },
        });

        try {
          const { youtubeBot } = require('../telegram/youtubeBot');
          const chatId = jobForPublish.campaign?.telegram_chat_id;
          if (chatId && youtubeBot) {
            await youtubeBot.telegram.sendMessage(
              chatId.toString(),
              `✅ ĐĂNG YOUTUBE THÀNH CÔNG (JOB #${jobId})\n━━━━━━━━━━━━━━━━━━━━━\n` +
              `▪️ Tiêu đề: ${publishTarget.title || jobForPublish.video_title_idea || 'Video'}\n` +
              `▪️ Link: ${result.url}`,
            );
          }
        } catch (botErr) {
          console.error('[Queue Worker] Failed to send YouTube success notification:', botErr);
        }

        return { success: true, platform: 'youtube', url: result.url };
      } catch (error: any) {
        const message = error?.message || String(error);
        await updateActiveYouTubeTargets(jobId, ['APPROVED', 'PUBLISH_QUEUED', 'PUBLISHING'], 'FAILED', message);
        await prisma.processRealtimeLogs.create({
          data: {
            job_id: jobId,
            execution_step: 'YOUTUBE_PUBLISH_FAILED',
            status_level: 'ERROR',
            log_message: message,
          },
        });
        throw error;
      }
    }

    return new Promise((resolve, reject) => {
      // Đường dẫn đến file main.py của Python Worker
      const pythonScriptPath = path.resolve(__dirname, '../../../worker/main.py');
      
      const projectRoot = path.resolve(__dirname, '../../..');
      const venvPythonPathWin = path.resolve(projectRoot, 'venv/Scripts/python.exe');
      const venvPythonPathUnix = path.resolve(projectRoot, 'venv/bin/python');
      
      let pythonExecutable = 'python';
      if (fs.existsSync(venvPythonPathWin)) {
        pythonExecutable = venvPythonPathWin;
        console.log(`[Queue Worker] Using Windows virtualenv Python: ${pythonExecutable}`);
      } else if (fs.existsSync(venvPythonPathUnix)) {
        pythonExecutable = venvPythonPathUnix;
        console.log(`[Queue Worker] Using Unix virtualenv Python: ${pythonExecutable}`);
      } else {
        console.log(`[Queue Worker] Virtualenv Python not found. Falling back to global 'python' executable.`);
      }

      console.log(`[Queue Worker] Spawning Python worker: ${pythonScriptPath} --job-id ${jobId} --type ${type}`);

      // Kích hoạt tiến trình Python
      const pythonProcess = spawn(pythonExecutable, [
        pythonScriptPath,
        '--job-id',
        jobId.toString(),
        '--type',
        type,
      ]);

      let stdoutData = '';
      let stderrData = '';
      let cancelledByUser = false;

      const cancelWatcher = type !== 'PLANNING'
        ? setInterval(async () => {
          try {
            const currentJob = await prisma.videoPipelineJobs.findUnique({
              where: { id: jobId },
              select: { pipeline_state: true, error_log_trace: true },
            });
            const cancelTrace = currentJob?.error_log_trace || '';
            if (
              currentJob?.pipeline_state === 'FAILED' &&
              cancelTrace.toLowerCase().includes('cancel')
            ) {
              cancelledByUser = true;
              console.log(`[Queue Worker] Cancellation detected for job #${jobId}. Stopping Python worker...`);
              pythonProcess.kill('SIGTERM');
            }
          } catch (cancelCheckError) {
            console.warn('[Queue Worker] Failed to check cancellation state:', cancelCheckError);
          }
        }, 3000)
        : null;

      pythonProcess.stdout.on('data', (data) => {
        const str = data.toString();
        stdoutData += str;
        console.log(`[Python Worker stdout]: ${str.trim()}`);
      });

      pythonProcess.stderr.on('data', (data) => {
        const str = data.toString();
        stderrData += str;
        console.error(`[Python Worker stderr]: ${str.trim()}`);
      });

      pythonProcess.on('close', async (code) => {
        if (cancelWatcher) clearInterval(cancelWatcher);
        console.log(`[Queue Worker] Python child process exited with code ${code}`);
        
        if (code === 0 && !cancelledByUser) {
          await prisma.processRealtimeLogs.create({
            data: {
              job_id: type !== 'PLANNING' ? jobId : null,
              execution_step: `${type}_SUCCESS`,
              status_level: 'SUCCESS',
              log_message: `Tiến trình ${type} cho ID #${jobId} hoàn thành thành công.`,
            },
          });

          // Gửi thông báo tự động qua Telegram khi hoàn thành tiến trình
          try {
            const { bot } = require('../telegram/bot');
            if (type === 'PLANNING') {
              const campaign = await prisma.channelsCampaign.findUnique({
                where: { id: jobId }
              });
              if (campaign) {
                await bot.telegram.sendMessage(
                  campaign.telegram_chat_id.toString(),
                  `📋 *THÔNG BÁO HỆ THỐNG: HOÀN THÀNH LẬP KẾ HOẠCH CHIẾN DỊCH 30 NGÀY (CAMPAIGN #${campaign.id})*\n━━━━━━━━━━━━━━━━━━━━━\n` +
                  `▪️ Chủ đề chiến dịch: *"${campaign.topic}"*\n` +
                  `▪️ Đối tượng mục tiêu: *"${campaign.target_audience}"*\n\n` +
                  `🤖 *Trạng thái:* Hệ thống đang tự động khởi chạy quy trình chuẩn bị tài nguyên và kết xuất (Render) video cho Ngày 1.\n` +
                  `Nhật ký tiến trình và liên kết phê duyệt (/preview) tự động gửi đến người điều hành ngay sau khi tệp tin video được kết xuất thành công.`,
                  { parse_mode: 'Markdown' }
                );
                
                // Tự động kích hoạt RENDER cho Job ngày 1 để người dùng có video xem ngay
                const firstJob = await prisma.videoPipelineJobs.findFirst({
                  where: { campaign_id: campaign.id, day_number: 1 }
                });
                if (firstJob) {
                  const { addJobToQueue } = require('./queue');
                  await prisma.videoPipelineJobs.update({
                    where: { id: firstJob.id },
                    data: { pipeline_state: 'AI_PROCESSING' }
                  });
                  await addJobToQueue(firstJob.id, 'RENDER');
                  console.log(`[Queue Worker] Auto-triggered RENDER job #${firstJob.id} for Day 1 of Campaign #${campaign.id}`);
                }
              }
            } else if (type === 'RENDER') {
              const jobObj = await prisma.videoPipelineJobs.findUnique({
                where: { id: jobId },
                include: { campaign: true }
              });
              if (jobObj && jobObj.campaign) {
                let isMusicVideo = false;
                let songTitle = '';
                let artistName = '';
                let mood = '';
                let remixStyle = 'Nguyên bản';
                let caption = '';
                
                try {
                  const meta = jobObj.scenes_layout_json 
                    ? (typeof jobObj.scenes_layout_json === 'string' ? JSON.parse(jobObj.scenes_layout_json) : jobObj.scenes_layout_json)
                    : {};
                  const renderMode = meta.render_mode || '';
                  if (meta && (meta.is_standalone_music_video || renderMode === 'music_reactive' || renderMode === 'music_remix_reactive')) {
                    isMusicVideo = true;
                    songTitle = meta.song_title || jobObj.video_title_idea;
                    artistName = meta.artist_name || 'N/A';
                    mood = meta.mood || meta.music_mood || 'N/A';
                    remixStyle = meta.remix_style || 'Nguyên bản';
                    caption = meta.caption || 'N/A';
                  }
                } catch (e) {}

                if (isMusicVideo) {
                  await bot.telegram.sendMessage(
                    jobObj.campaign.telegram_chat_id.toString(),
                    `🎵 *THÔNG BÁO HỆ THỐNG: KẾT XUẤT THÀNH CÔNG VIDEO ÂM NHẠC (JOB #${jobId})*\n━━━━━━━━━━━━━━━━━━━━━\n` +
                    `▪️ Tên bài hát: *"${songTitle}"*\n` +
                    `▪️ Ca sĩ/Nghệ sĩ: *"${artistName}"*\n` +
                    `▪️ Cảm xúc (Mood): *"${mood}"*\n` +
                    `▪️ Style Remix: *"${remixStyle}"*\n` +
                    `▪️ Caption/Mô tả: _"${caption}"_\n\n` +
                    `👉 *Yêu cầu thực thi:* Sử dụng liên kết nhanh /preview\\_${jobId} hoặc gửi lệnh \`/preview ${jobId}\` để thực hiện kiểm duyệt và phê duyệt xuất bản lên TikTok Studio.`,
                    { parse_mode: 'Markdown' }
                  );
                } else {
                  await bot.telegram.sendMessage(
                    jobObj.campaign.telegram_chat_id.toString(),
                    `🎬 *THÔNG BÁO HỆ THỐNG: KẾT XUẤT THÀNH CÔNG VIDEO NGÀY ${jobObj.day_number} (JOB #${jobId})*\n━━━━━━━━━━━━━━━━━━━━━\n` +
                    `▪️ Tiêu đề/Ý tưởng: *"${jobObj.video_title_idea}"*\n` +
                    `▪️ Cấu trúc Hook (3s): *"${jobObj.hook_text_3s}"*\n\n` +
                    `👉 *Yêu cầu thực thi:* Sử dụng liên kết nhanh /preview\\_${jobId} hoặc gửi lệnh \`/preview ${jobId}\` để thực hiện kiểm duyệt và phê duyệt xuất bản lên TikTok Studio.`,
                    { parse_mode: 'Markdown' }
                  );
                }
              }
            } else if (type === 'PUBLISH') {
              const jobObj = await prisma.videoPipelineJobs.findUnique({
                where: { id: jobId },
                include: { campaign: true }
              });
              if (jobObj && jobObj.campaign) {
                await bot.telegram.sendMessage(
                  jobObj.campaign.telegram_chat_id.toString(),
                  `🚀 *THÔNG BÁO HỆ THỐNG: XUẤT BẢN THÀNH CÔNG VIDEO NGÀY ${jobObj.day_number} (JOB #${jobId})*\n━━━━━━━━━━━━━━━━━━━━━\n` +
                  `▪️ Tiêu đề/Ý tưởng: *"${jobObj.video_title_idea}"*\n\n` +
                  `🔗 *Xác nhận:* Tác vụ đã được tự động đăng tải thành công lên TikTok Studio. Vui lòng truy cập trang quản trị để xác minh trạng thái hiển thị của bài viết.`,
                  { parse_mode: 'Markdown' }
                );
              }
            }
          } catch (botErr) {
            console.error('[Queue Worker] Failed to send Telegram notification:', botErr);
          }

          resolve({ success: true, stdout: stdoutData });
        } else {
          // Ghi nhận log lỗi vào MySQL để hiển thị qua chat
          await prisma.processRealtimeLogs.create({
            data: {
              job_id: type !== 'PLANNING' ? jobId : null,
              execution_step: cancelledByUser ? `${type}_CANCELLED` : `${type}_FAILED`,
              status_level: cancelledByUser ? 'WARN' : 'ERROR',
              log_message: cancelledByUser
                ? `Tiến trình ${type} cho Job #${jobId} đã được người dùng hủy từ Telegram.`
                : `Tiến trình ${type} lỗi (Exit Code: ${code}).\nChi tiết:\n${stderrData || stdoutData}`,
            },
          });

          // Cập nhật lỗi vào bảng jobs nếu không phải job PLANNING
          if (type !== 'PLANNING') {
            await prisma.videoPipelineJobs.update({
              where: { id: jobId },
              data: {
                pipeline_state: 'FAILED',
                error_log_trace: cancelledByUser
                  ? 'User cancelled this job from Telegram progress view.'
                  : (stderrData || 'Unknown Python process error'),
              },
            });
          }

          if (type === 'PUBLISH' && !cancelledByUser) {
            try {
              const { bot } = require('../telegram/bot');
              const jobObj = await prisma.videoPipelineJobs.findUnique({
                where: { id: jobId },
                include: { campaign: true },
              });
              if (jobObj?.campaign) {
                const detail = (stderrData || stdoutData || 'Không có chi tiết lỗi.').slice(0, 900);
                await bot.telegram.sendMessage(
                  jobObj.campaign.telegram_chat_id.toString(),
                  `❌ ĐĂNG VIDEO THẤT BẠI (JOB #${jobId})\n━━━━━━━━━━━━━━━━━━━━━\n` +
                  `▪️ Tiêu đề: "${jobObj.video_title_idea || 'Video'}"\n` +
                  `▪️ Bạn có thể bấm Đăng lại để chạy lại riêng bước đăng, không render lại video.\n\n` +
                  `Chi tiết lỗi:\n\`${detail.replace(/[`\\]/g, ' ').replace(/\n/g, ' ').slice(0, 700)}\``,
                  {
                    reply_markup: {
                      inline_keyboard: [
                        [
                          { text: 'Đăng lại', callback_data: `retry_publish:${jobId}` },
                          { text: 'Xem preview', callback_data: `preview:${jobId}` },
                        ],
                      ],
                    },
                  },
                );
              }
            } catch (botErr) {
              console.error('[Queue Worker] Failed to send publish failure retry notification:', botErr);
            }
          }

          reject(new Error(cancelledByUser ? `Job #${jobId} was cancelled by user.` : `Python process failed with exit code ${code}. Stderr: ${stderrData}`));
        }
      });
    });
  },
  { connection, concurrency: 1 } // Xử lý tuần tự để tránh nghẽn luồng CPU Spikes
);

console.log('[Orchestrator Worker] BullMQ Worker initialized and listening to Redis! 📦');
