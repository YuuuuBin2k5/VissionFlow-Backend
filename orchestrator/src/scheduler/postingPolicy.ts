import prisma from '../database/db';
import { addJobToQueue } from '../queue/queue';

const MIN_HOURS_BETWEEN_POSTS = parseInt(process.env.MIN_HOURS_BETWEEN_POSTS || '4', 10);
const MIN_POST_INTERVAL_MS = MIN_HOURS_BETWEEN_POSTS * 60 * 60 * 1000;

const BLOCKING_STATES = ['PUBLISHED', 'USER_APPROVED', 'PUBLISH_QUEUED', 'PUBLISHING'];

export function computeSafePublishTime(requestedAt: Date, blockedTimes: Date[]): Date {
  let target = new Date(requestedAt.getTime());
  const sortedTimes = blockedTimes
    .map((time) => new Date(time.getTime()))
    .sort((a, b) => a.getTime() - b.getTime());

  let changed = true;
  while (changed) {
    changed = false;
    for (const blockedTime of sortedTimes) {
      const distance = Math.abs(target.getTime() - blockedTime.getTime());
      if (distance < MIN_POST_INTERVAL_MS) {
        target = new Date(blockedTime.getTime() + MIN_POST_INTERVAL_MS);
        changed = true;
      }
    }
  }

  return target;
}

export async function schedulePublishWithSpacing(jobId: number, requestedAt = new Date(), respectFutureBlockers = true) {
  const job = await prisma.videoPipelineJobs.findUnique({
    where: { id: jobId },
    include: { campaign: true },
  });

  if (!job) {
    throw new Error(`Video job #${jobId} was not found.`);
  }

  const plannedTime = job.scheduled_post_time || requestedAt;
  const requestedPublishTime = new Date(Math.max(requestedAt.getTime(), plannedTime.getTime()));

  const campaignScope = job.campaign_id
    ? { campaign_id: job.campaign_id }
    : {};

  const blockingJobs = await prisma.videoPipelineJobs.findMany({
    where: {
      ...campaignScope,
      id: { not: jobId },
      pipeline_state: { in: BLOCKING_STATES },
    },
    select: {
      id: true,
      scheduled_post_time: true,
      pipeline_state: true,
    },
    orderBy: {
      scheduled_post_time: 'asc',
    },
  });

  const safePublishTime = computeSafePublishTime(
    requestedPublishTime,
    blockingJobs
      .map((blockingJob) => blockingJob.scheduled_post_time)
      .filter((blockedTime) => respectFutureBlockers || blockedTime.getTime() <= requestedPublishTime.getTime()),
  );
  const delayMs = Math.max(0, safePublishTime.getTime() - requestedAt.getTime());

  await prisma.videoPipelineJobs.update({
    where: { id: jobId },
    data: {
      pipeline_state: 'PUBLISH_QUEUED',
      scheduled_post_time: safePublishTime,
    },
  });

  if (safePublishTime.getTime() !== requestedPublishTime.getTime()) {
    const nearestBlocker = blockingJobs.find((blockingJob) => {
      const distance = Math.abs(requestedPublishTime.getTime() - blockingJob.scheduled_post_time.getTime());
      return distance < MIN_POST_INTERVAL_MS;
    });

    const reason = nearestBlocker
      ? `Too close to job #${nearestBlocker.id} (${nearestBlocker.pipeline_state})`
      : 'Duplicate or unsafe publish window';

    const message =
      `Scheduler moved publish time for job #${jobId}: ` +
      `${requestedPublishTime.toISOString()} -> ${safePublishTime.toISOString()} (${reason}, min gap ${MIN_HOURS_BETWEEN_POSTS}h).`;

    console.log(`[PostingPolicy] ${message}`);
    await prisma.processRealtimeLogs.create({
      data: {
        job_id: jobId,
        execution_step: 'SCHEDULER_GUARD',
        status_level: 'WARN',
        log_message: message,
      },
    });
  }

  await addJobToQueue(jobId, 'PUBLISH', delayMs);

  return {
    safePublishTime,
    delayMs,
  };
}
