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
import { decryptConnectionRefreshToken, getConnectedPlatformConnection, getPlatformConnectionById } from '../database/userConnectionRepo';
import { Prisma } from '@prisma/client';
import { schedulePublishWithSpacing } from '../scheduler/postingPolicy';
import dotenv from 'dotenv';

dotenv.config();

const redisHost = process.env.REDIS_HOST || 'localhost';
const redisPort = parseInt(process.env.REDIS_PORT || '6379', 10);
let lastRedisErrorLogAt = 0;

function logRedisConnectionIssue(error: any) {
  const now = Date.now();
  if (now - lastRedisErrorLogAt < 30000) return;
  lastRedisErrorLogAt = now;

  const message = error?.message || String(error);
  console.warn(
    `[Redis Warning] Worker chưa kết nối được Redis tại ${redisHost}:${redisPort}. ` +
    `Hãy chạy "npm run dev:infra" trong thư mục orchestrator hoặc "docker compose up -d mysql redis" tại thư mục AgentTiktok. ` +
    `Chi tiết: ${message}`
  );
}

const connection = new IORedis({
  host: redisHost,
  port: redisPort,
  maxRetriesPerRequest: null,
});
connection.on('error', logRedisConnectionIssue);

// Khởi tạo BullMQ Worker
export const tiktokWorker = new Worker(
  'tiktok_jobs',
  async (job: Job) => {
    const { jobId, type, publishTargetId } = job.data;
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

    return new Promise(async (resolve, reject) => {
      let proxyIp = '';
      let proxyPort = 0;
      let proxyUser = '';
      let proxyPass = '';

      if (type === 'PUBLISH') {
        try {
          let publishTarget: any = null;
          if (publishTargetId) {
            const rows = await prisma.$queryRaw<any[]>(
              Prisma.sql`SELECT * FROM publish_targets WHERE id = ${publishTargetId} LIMIT 1`
            );
            publishTarget = rows[0] || null;
          } else {
            const rows = await prisma.$queryRaw<any[]>(
              Prisma.sql`SELECT * FROM publish_targets WHERE job_id = ${jobId} AND status IN ('APPROVED', 'PUBLISH_QUEUED', 'PUBLISHING') LIMIT 1`
            );
            publishTarget = rows[0] || null;
          }

          if (publishTarget && publishTarget.platform_connection_id) {
            const connRecord = await prisma.platformConnections.findUnique({
              where: { id: publishTarget.platform_connection_id }
            });
            if (connRecord) {
              // Find matching BotAccount
              let botAccount = await prisma.botAccounts.findFirst({
                where: {
                  OR: [
                    { bot_id: connRecord.external_account_id || undefined },
                    { username: connRecord.account_name || undefined }
                  ]
                }
              });

              if (!botAccount && connRecord.account_name) {
                const cleanName = connRecord.account_name.replace('@', '').toLowerCase();
                const allBots = await prisma.botAccounts.findMany();
                botAccount = allBots.find(b => {
                  const bName = b.username.replace('@', '').toLowerCase();
                  return bName.includes(cleanName) || cleanName.includes(bName);
                }) || null;
              }

              if (botAccount) {
                proxyIp = botAccount.proxy_ip || '';
                proxyPort = botAccount.proxy_port || 0;
                proxyUser = botAccount.proxy_user || '';
                proxyPass = botAccount.proxy_pass || '';
                console.log(`[Queue Worker] Dynamic proxy matched: ${proxyIp}:${proxyPort}`);
              }
            }
          }
        } catch (proxyErr) {
          console.warn('[Queue Worker Warning] Failed to fetch proxy info:', proxyErr);
        }
      }

      // Đường dẫn đến file main.py của Python Worker
      const pythonScriptPath = path.resolve(__dirname, '../../../worker/main.py');
      
      const projectRoot = path.resolve(__dirname, '../../..');
      const venvPythonPathWin = path.resolve(projectRoot, 'venv/Scripts/python.exe');
      const venvPythonPathWin2 = path.resolve(projectRoot, 'AgentTiktok/venv/Scripts/python.exe');
      const venvPythonPathUnix = path.resolve(projectRoot, 'venv/bin/python');
      
      let pythonExecutable = 'python';
      if (fs.existsSync(venvPythonPathWin)) {
        pythonExecutable = venvPythonPathWin;
        console.log(`[Queue Worker] Using Windows virtualenv Python: ${pythonExecutable}`);
      } else if (fs.existsSync(venvPythonPathWin2)) {
        pythonExecutable = venvPythonPathWin2;
        console.log(`[Queue Worker] Using Windows AgentTiktok virtualenv Python: ${pythonExecutable}`);
      } else if (fs.existsSync(venvPythonPathUnix)) {
        pythonExecutable = venvPythonPathUnix;
        console.log(`[Queue Worker] Using Unix virtualenv Python: ${pythonExecutable}`);
      } else {
        console.log(`[Queue Worker] Virtualenv Python not found. Falling back to global 'python' executable.`);
      }

      const pythonArgs = [
        pythonScriptPath,
        '--job-id',
        jobId.toString(),
        '--type',
        type,
      ];
      if (publishTargetId) {
        pythonArgs.push('--publish-target-id', publishTargetId.toString());
      }
      if (proxyIp) {
        pythonArgs.push('--proxy-ip', proxyIp);
        pythonArgs.push('--proxy-port', proxyPort.toString());
        if (proxyUser) {
          pythonArgs.push('--proxy-user', proxyUser);
        }
        if (proxyPass) {
          pythonArgs.push('--proxy-pass', proxyPass);
        }
      }

      console.log(`[Queue Worker] Spawning Python worker: ${pythonExecutable} ${pythonArgs.join(' ')}`);

      // Kích hoạt tiến trình Python
      const pythonProcess = spawn(pythonExecutable, pythonArgs);

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
              if (jobObj) {
                const campaign = jobObj.campaign;
                const autoPublish = jobObj.auto_publish || campaign?.auto_publish;

                if (autoPublish) {
                  console.log(`[Queue Worker] Auto-publish enabled for Job #${jobId}. Automatically scheduling publish...`);
                  try {
                    const { safePublishTime, delayMs } = await schedulePublishWithSpacing(jobId);
                    const targetChatId = campaign?.telegram_chat_id || process.env.TELEGRAM_CHAT_ID;
                    if (targetChatId) {
                      await bot.telegram.sendMessage(
                        targetChatId.toString(),
                        `🎬 *THÔNG BÁO HỆ THỐNG: KẾT XUẤT THÀNH CÔNG & TỰ ĐỘNG PHÊ DUYỆT (JOB #${jobId})*\n━━━━━━━━━━━━━━━━━━━━━\n` +
                        `▪️ Tiêu đề/Ý tưởng: *"${jobObj.video_title_idea}"*\n` +
                        `▪️ Trạng thái: *Đã tự động duyệt (Auto-Publish)*\n` +
                        `▪️ Giờ phát sóng: *${safePublishTime.toLocaleString('vi-VN')}* (sau ${Math.round(delayMs / 60000)} phút)\n\n` +
                        `🔗 Video đã được xếp vào hàng đợi đăng tải có giãn cách an toàn.`,
                        { parse_mode: 'Markdown' }
                      );
                    }
                  } catch (spacingErr) {
                    console.error('[Queue Worker Error] Failed to schedule auto-publish:', spacingErr);
                  }
                } else if (campaign) {
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
                      campaign.telegram_chat_id.toString(),
                      `🎵 *THÔNG BÁO HỆ THỐNG: KẾT XUẤT THÀNH CÔNG VIDEO AM NHẠC (JOB #${jobId})*\n━━━━━━━━━━━━━━━━━━━━━\n` +
                      `▪️ Tên bài hát: *"${songTitle}"*\n` +
                      `▪️ Ca sĩ/Nghệ sĩ: *"${artistName}"*\n` +
                      `▪️ Cảm xúc (Mood): *"${mood}"*\n` +
                      `▪️ Style Remix: *"${remixStyle}"*\n` +
                      `▪️ Caption/Mô tả: _"${caption}"_\n\n` +
                      `👉 *Yêu cầu thực thi:* Sử dụng liên kết nhanh /preview\\_${jobId} hoặc gửi lệnh \`/preview ${jobId}\` để thực hiện kiểm duyệt và phê duyệt xuất bản lên TikTok Studio.`,
                      { parse_mode: 'Markdown' }
                    );
                  } else {
                    // Kiểm tra nếu là tác vụ dịch thuật lồng tiếng (DUB)
                    const isDubJob = String(jobObj.video_title_idea || '').includes('[DUB]') || jobObj.scenes_layout_json?.toString().includes('translate_dub');
                    
                    if (isDubJob) {
                      try {
                        // Tự động tải lên và phân phối video thành phẩm trực tiếp cho người dùng
                        const { handlePreviewLogic } = require('../telegram/bot');
                        const mockCtx = {
                          chat: { id: campaign.telegram_chat_id },
                          reply: (msg: string) => bot.telegram.sendMessage(campaign.telegram_chat_id.toString(), msg),
                          replyWithHTML: (msg: string, kb: any) => bot.telegram.sendMessage(campaign.telegram_chat_id.toString(), msg, { parse_mode: 'HTML', reply_markup: kb?.reply_markup }),
                          replyWithVideo: (source: any, extra: any) => bot.telegram.sendVideo(campaign.telegram_chat_id.toString(), source.source, extra),
                          replyWithDocument: (source: any, extra: any) => bot.telegram.sendDocument(campaign.telegram_chat_id.toString(), source.source, extra),
                        };
                        await handlePreviewLogic(mockCtx, jobId);
                      } catch (dubErr) {
                        console.error('[Queue Worker Error] Failed to auto-deliver dub video:', dubErr);
                        // Fallback gửi tin nhắn báo thành công tiêu chuẩn
                        await bot.telegram.sendMessage(
                          campaign.telegram_chat_id.toString(),
                          `🎬 *THÔNG BÁO HỆ THỐNG: KẾT XUẤT THÀNH CÔNG VIDEO LỒNG TIẾNG (JOB #${jobId})*\n━━━━━━━━━━━━━━━━━━━━━\n` +
                          `▪️ Tiêu đề: *"${jobObj.video_title_idea}"*\n\n` +
                          `👉 Sử dụng lệnh \`/preview ${jobId}\` để tải video về!`,
                          { parse_mode: 'Markdown' }
                        );
                      }
                    } else {
                      await bot.telegram.sendMessage(
                        campaign.telegram_chat_id.toString(),
                        `🎬 *THÔNG BÁO HỆ THỐNG: KẾT XUẤT THÀNH CÔNG VIDEO NGÀY ${jobObj.day_number} (JOB #${jobId})*\n━━━━━━━━━━━━━━━━━━━━━\n` +
                        `▪️ Tiêu đề/Ý tưởng: *"${jobObj.video_title_idea}"*\n` +
                        `▪️ Cấu trúc Hook (3s): *"${jobObj.hook_text_3s}"*\n\n` +
                        `👉 *Yêu cầu thực thi:* Sử dụng liên kết nhanh /preview\\_${jobId} hoặc gửi lệnh \`/preview ${jobId}\` để thực hiện kiểm duyệt và phê duyệt xuất bản lên TikTok Studio.`,
                        { parse_mode: 'Markdown' }
                      );
                    }
                  }
                }
              }
            } else if (type === 'PUBLISH') {
              const jobObj = await prisma.videoPipelineJobs.findUnique({
                where: { id: jobId },
                include: { campaign: true }
              });
              if (jobObj && jobObj.campaign) {
                let platformName = 'TikTok Studio';
                try {
                  const rows = await prisma.$queryRaw<any[]>(
                    Prisma.sql`SELECT platform FROM publish_targets WHERE job_id = ${jobId} LIMIT 1`
                  );
                  if (rows[0] && rows[0].platform === 'youtube') {
                    platformName = 'YouTube Studio';
                  }
                } catch (e) {}

                await bot.telegram.sendMessage(
                  jobObj.campaign.telegram_chat_id.toString(),
                  `🚀 *THÔNG BÁO HỆ THỐNG: XUẤT BẢN THÀNH CÔNG VIDEO NGÀY ${jobObj.day_number} (JOB #${jobId})*\n━━━━━━━━━━━━━━━━━━━━━\n` +
                  `▪️ Tiêu đề/Ý tưởng: *"${jobObj.video_title_idea}"*\n\n` +
                  `🔗 *Xác nhận:* Tác vụ đã được tự động đăng tải thành công lên ${platformName}. Vui lòng truy cập trang quản trị để xác minh trạng thái hiển thị của bài viết.`,
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
