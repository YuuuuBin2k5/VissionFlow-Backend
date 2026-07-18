import { Queue } from 'bullmq';
import IORedis from 'ioredis';
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
    `[Redis Warning] Chưa kết nối được Redis tại ${redisHost}:${redisPort}. ` +
    `Hãy chạy "npm run dev:infra" trong thư mục orchestrator hoặc "docker compose up -d mysql redis" tại thư mục AgentTiktok. ` +
    `Chi tiết: ${message}`
  );
}

const connection = new IORedis({
  host: redisHost,
  port: redisPort,
  maxRetriesPerRequest: null, // Yêu cầu bắt buộc của BullMQ
});
connection.on('error', logRedisConnectionIssue);

// Khởi tạo hàng đợi công việc TikTok
export const tiktokQueue = new Queue('tiktok_jobs', { connection });

export type QueueJobType = 'PLANNING' | 'RENDER' | 'PUBLISH';
export type PublishPlatform = 'tiktok' | 'youtube';

export async function addJobToQueue(jobId: number, type: QueueJobType, delayMs = 0, platform: PublishPlatform = 'tiktok', publishTargetId?: number) {
  const platformSuffix = type === 'PUBLISH' ? `_${platform}` : '';
  const targetSuffix = publishTargetId ? `_target_${publishTargetId}` : '';
  const queueJobId = `${type}_${jobId}${platformSuffix}${targetSuffix}`;
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
    { jobId, type, platform, publishTargetId },
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
  const targetText = publishTargetId ? ` (Target: #${publishTargetId})` : '';
  const platformText = type === 'PUBLISH' ? ` (${platform})` : '';
  console.log(`[Queue] Added job ${jobId} with type ${type}${platformText}${targetText} to Redis queue${delayText}.`);
}
