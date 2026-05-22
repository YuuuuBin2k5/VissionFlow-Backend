import prisma from '../database/db';
import { addJobToQueue } from '../queue/queue';
import { schedulePublishWithSpacing } from './postingPolicy';
import { getDueYouTubeTargets, updateYouTubeTarget } from '../database/publishTargetRepo';

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
}
