import prisma from '../database/db';
import { addJobToQueue } from '../queue/queue';
import { schedulePublishWithSpacing } from './postingPolicy';
import { getDueYouTubeTargets, updateYouTubeTarget } from '../database/publishTargetRepo';
import fs from 'fs/promises';
import path from 'path';

// ─────────────────────────────────────────────────────────────────────────────
// STORAGE RETENTION POLICY — Tự động dọn dẹp file cũ hơn 7 ngày
// Quét: worker/temp_assets  &  worker/output_videos
// Kích hoạt: mỗi 24 giờ, lần đầu sau 3 giờ khởi động (tránh xung đột cold-start)
// ─────────────────────────────────────────────────────────────────────────────
const RETENTION_MS = 7 * 24 * 60 * 60 * 1000; // 7 ngày tính bằng milliseconds
const RETENTION_SCAN_DIRS = [
  path.resolve(__dirname, '../../../../worker/temp_assets'),
  path.resolve(__dirname, '../../../../worker/output_videos'),
];

async function runStorageRetentionPolicy(): Promise<void> {
  const now = Date.now();
  console.log('[RetentionPolicy] 🗂️ Bắt đầu quét dọn file cũ hơn 7 ngày...');

  for (const scanDir of RETENTION_SCAN_DIRS) {
    // Bỏ qua nếu thư mục không tồn tại (tránh crash khi môi trường chưa khởi tạo)
    try {
      await fs.access(scanDir);
    } catch {
      console.log(`[RetentionPolicy] Thư mục không tồn tại, bỏ qua: ${scanDir}`);
      continue;
    }

    let entries: import('fs').Dirent[];
    try {
      entries = await fs.readdir(scanDir, { withFileTypes: true });
    } catch (err) {
      console.error(`[RetentionPolicy Error] Không thể đọc thư mục ${scanDir}:`, err);
      continue;
    }

    for (const entry of entries) {
      const entryPath = path.join(scanDir, entry.name);
      try {
        const stat = await fs.stat(entryPath);
        const ageMs = now - stat.mtimeMs;

        if (ageMs > RETENTION_MS) {
          if (entry.isDirectory()) {
            await fs.rm(entryPath, { recursive: true, force: true });
          } else {
            await fs.unlink(entryPath);
          }
          const ageDays = (ageMs / (24 * 60 * 60 * 1000)).toFixed(1);
          console.log(`[RetentionPolicy] 🗑️ Đã xóa (${ageDays} ngày tuổi): ${entryPath}`);
        }
      } catch (err) {
        console.error(`[RetentionPolicy Error] Không thể xử lý: ${entryPath}:`, err);
      }
    }
  }

  console.log('[RetentionPolicy] ✅ Hoàn thành quét dọn storage.');
}

export function startAutoScheduler() {
  console.log('[Scheduler] Auto-Scheduler service started! ⏱️ (Running every 1 minute)');
  
  // Chạy định kỳ mỗi 1 phút để kiểm tra và nạp các job sắp đến hạn render
  setInterval(async () => {
    try {
      const now = new Date();
      // Quét trước 24 giờ để render và gửi thông báo xem trước kịp thời
      const limitTime = new Date(now.getTime() + 24 * 60 * 60 * 1000);
      
      const jobsToRender = await prisma.videoPipelineJobs.findMany({
        where: {
          pipeline_state: 'QUEUED',
          scheduled_post_time: {
            lte: limitTime,
          },
        },
        include: {
          campaign: true,
        },
      });

      if (jobsToRender.length > 0) {
        console.log(`[Scheduler] Found ${jobsToRender.length} queued job(s) due for rendering in the next 24 hours.`);
        
        for (const job of jobsToRender) {
          // Bỏ qua nếu campaign đã bị hủy hoặc tạm dừng
          if (job.campaign && ['CANCELLED', 'PAUSED'].includes(job.campaign.status)) {
            if (job.campaign.status === 'CANCELLED') {
              await prisma.videoPipelineJobs.update({
                where: { id: job.id },
                data: {
                  pipeline_state: 'FAILED',
                  error_log_trace: 'Campaign was cancelled.',
                },
              });
            }
            continue;
          }

          console.log(`[Scheduler] Auto-triggering RENDER for Job #${job.id} (Day ${job.day_number})`);
          
          // Cập nhật trạng thái sang AI_PROCESSING để tránh bị quét lại ở chu kỳ sau
          await prisma.videoPipelineJobs.update({
            where: { id: job.id },
            data: {
              pipeline_state: 'AI_PROCESSING',
            },
          });

          // Đẩy job RENDER vào BullMQ Queue
          await addJobToQueue(job.id, 'RENDER');
        }
      }

      const approvedJobsToPublish = await prisma.videoPipelineJobs.findMany({
        where: {
          pipeline_state: 'USER_APPROVED',
          scheduled_post_time: {
            lte: now,
          },
        },
        include: {
          campaign: true,
        },
      });

      if (approvedJobsToPublish.length > 0) {
        console.log(`[Scheduler] Found ${approvedJobsToPublish.length} approved job(s) due for publishing.`);

        for (const job of approvedJobsToPublish) {
          if (job.campaign && ['CANCELLED', 'PAUSED'].includes(job.campaign.status)) {
            if (job.campaign.status === 'CANCELLED') {
              await prisma.videoPipelineJobs.update({
                where: { id: job.id },
                data: {
                  pipeline_state: 'FAILED',
                  error_log_trace: 'Campaign was cancelled.',
                },
              });
            }
            continue;
          }

          await schedulePublishWithSpacing(job.id, now, false);
        }
      }

      const youtubeTargetsToPublish = await getDueYouTubeTargets(now);

      for (const target of youtubeTargetsToPublish) {
        if (target.campaign_status && ['CANCELLED', 'PAUSED'].includes(target.campaign_status)) {
          continue;
        }
        await updateYouTubeTarget(target.id, { status: 'PUBLISH_QUEUED' });
        await addJobToQueue(target.job_id, 'PUBLISH', 0, 'youtube');
      }
    } catch (error) {
      console.error('[Scheduler Error] Error in auto-scheduler execution:', error);
    }
  }, 60 * 1000); // Tần suất 1 phút

  // ─── Storage Retention: chạy lần đầu sau 3 giờ khởi động, rồi lặp mỗi 24 giờ ───
  const RETENTION_INTERVAL_MS = 24 * 60 * 60 * 1000; // 24 giờ
  const RETENTION_INITIAL_DELAY_MS = 3 * 60 * 60 * 1000; // 3 giờ (cold-start buffer)

  setTimeout(() => {
    // Lần quét đầu tiên
    runStorageRetentionPolicy().catch((err) =>
      console.error('[RetentionPolicy Error] Lần quét đầu thất bại:', err)
    );
    // Lặp lại mỗi 24 giờ
    setInterval(() => {
      runStorageRetentionPolicy().catch((err) =>
        console.error('[RetentionPolicy Error] Quét định kỳ thất bại:', err)
      );
    }, RETENTION_INTERVAL_MS);
  }, RETENTION_INITIAL_DELAY_MS);

  console.log('[RetentionPolicy] 📅 Storage Retention Policy đã được lên lịch (lần đầu sau 3h, định kỳ mỗi 24h).');
}
