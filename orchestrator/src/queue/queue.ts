import { Queue } from 'bullmq';
import IORedis from 'ioredis';
import dotenv from 'dotenv';

dotenv.config();

const redisHost = process.env.REDIS_HOST || 'localhost';
const redisPort = parseInt(process.env.REDIS_PORT || '6379', 10);

const connection = new IORedis({
  host: redisHost,
  port: redisPort,
  maxRetriesPerRequest: null, // Yêu cầu bắt buộc của BullMQ
});

// Khởi tạo hàng đợi công việc TikTok
export const tiktokQueue = new Queue('tiktok_jobs', { connection });

export type QueueJobType = 'PLANNING' | 'RENDER' | 'PUBLISH';
export type PublishPlatform = 'tiktok' | 'youtube';

export async function addJobToQueue(jobId: number, type: QueueJobType, delayMs = 0, platform: PublishPlatform = 'tiktok') {
  const platformSuffix = type === 'PUBLISH' ? `_${platform}` : '';
  const queueJobId = `${type}_${jobId}${platformSuffix}`;
  const existingJob = await tiktokQueue.getJob(queueJobId);
  if (existingJob) {
    const state = await existingJob.getState();
    if (['delayed', 'waiting', 'waiting-children', 'prioritized', 'failed', 'completed'].includes(state)) {
      await existingJob.remove();
      console.log(`[Queue] Replaced existing job ${queueJobId} (state: ${state}) with a new job.`);
    } else {

      console.log(`[Queue] Job ${queueJobId} already exists in state ${state}; skipping duplicate enqueue.`);
      return;
    }
  }

  await tiktokQueue.add(
    'process_step',
    { jobId, type, platform },
    {
      jobId: queueJobId,
      removeOnComplete: true,
      removeOnFail: false,
      attempts: 3,
      backoff: {
        type: 'exponential',
        delay: 30000,
      },
      delay: Math.max(0, delayMs),
    }
  );
  const delayText = delayMs > 0 ? ` with delay ${Math.round(delayMs / 60000)} minute(s)` : '';
  const platformText = type === 'PUBLISH' ? ` (${platform})` : '';
  console.log(`[Queue] Added job ${jobId} with type ${type}${platformText} to Redis queue${delayText}.`);
}
