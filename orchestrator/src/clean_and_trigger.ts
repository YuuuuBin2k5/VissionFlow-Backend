import { tiktokQueue, addJobToQueue } from './queue/queue';
import prisma from './database/db';

async function main() {
  const jobId = process.argv[2] ? parseInt(process.argv[2], 10) : 62;
  if (isNaN(jobId)) {
    throw new Error('Invalid Job ID provided');
  }
  const queueJobId = `RENDER_${jobId}`;
  console.log(`--- FORCE CLEANING REDIS JOB ${queueJobId} ---`);
  
  const existingJob = await tiktokQueue.getJob(queueJobId);
  if (existingJob) {
    const state = await existingJob.getState();
    console.log(`Found job ${queueJobId} in state: ${state}. Removing it now...`);
    await existingJob.remove();
    console.log(`Successfully removed job ${queueJobId} from BullMQ!`);
  } else {
    console.log(`Job ${queueJobId} not found in BullMQ.`);
  }

  // Cập nhật lại database job 31 sang trạng thái QUEUED để bắt đầu lại sạch sẽ
  await prisma.videoPipelineJobs.update({
    where: { id: jobId },
    data: {
      pipeline_state: 'QUEUED',
      error_log_trace: null
    }
  });
  console.log(`Updated DB Job #${jobId} status to QUEUED.`);

  // Enqueue lại job render
  console.log(`Enqueueing job #${jobId} (RENDER) to BullMQ...`);
  await addJobToQueue(jobId, 'RENDER');
  console.log(`Successfully triggered clean render for Job #${jobId}!`);
}

main().then(() => process.exit(0)).catch(err => {
  console.error('Error:', err);
  process.exit(1);
});
