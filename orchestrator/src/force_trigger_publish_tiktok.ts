import { tiktokQueue, addJobToQueue } from './queue/queue';
import prisma from './database/db';

async function main() {
  const jobId = 207;
  const queueJobId = `PUBLISH_${jobId}_tiktok`;
  
  console.log(`--- FORCE CLEANING REDIS PUBLISH JOB ${queueJobId} ---`);
  
  const existingJob = await tiktokQueue.getJob(queueJobId);
  if (existingJob) {
    const state = await existingJob.getState();
    console.log(`Found job ${queueJobId} in state: ${state}. Removing it...`);
    try {
      await existingJob.remove();
      console.log(`Successfully removed job ${queueJobId} from BullMQ.`);
    } catch (err: any) {
      console.warn(`Failed to remove job directly (it might be locked): ${err.message}. Trying to update state first...`);
      // If active/locked, we can try to force release
      try {
        await (existingJob as any).discard();
        await existingJob.remove();
        console.log(`Discarded and removed job ${queueJobId}.`);
      } catch (discardErr: any) {
        console.error(`Failed to discard: ${discardErr.message}`);
      }
    }
  } else {
    console.log(`Job ${queueJobId} not found in BullMQ.`);
  }

  // Reset pipeline state to a clean starting state
  console.log(`Resetting database job #${jobId} status to USER_APPROVED...`);
  await prisma.videoPipelineJobs.update({
    where: { id: jobId },
    data: {
      pipeline_state: 'USER_APPROVED',
      error_log_trace: null
    }
  });

  // Enqueue new job
  console.log(`Enqueuing clean publish job for Job #${jobId}...`);
  // Directly add to queue with a forced clean ID by calling tiktokQueue.add if addJobToQueue skips it
  await tiktokQueue.add(
    'process_step',
    { jobId, type: 'PUBLISH', platform: 'tiktok' },
    {
      jobId: queueJobId,
      removeOnComplete: true,
      removeOnFail: false,
      attempts: 3,
      backoff: {
        type: 'exponential',
        delay: 30000,
      },
      delay: 0,
    }
  );
  
  console.log('🎉 Successfully force-triggered TikTok publish job!');
}

main()
  .then(() => prisma.$disconnect())
  .catch((err) => {
    console.error('Error:', err);
    prisma.$disconnect();
    process.exit(1);
  });
