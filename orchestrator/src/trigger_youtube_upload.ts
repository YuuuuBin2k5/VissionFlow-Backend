import { PrismaClient } from '@prisma/client';
import { addJobToQueue } from './queue/queue';

const prisma = new PrismaClient();

async function main() {
  const jobId = 206;
  const targetId = 103;
  
  console.log(`Resetting publish target #${targetId} status to APPROVED...`);
  await prisma.$executeRawUnsafe(
    `UPDATE publish_targets SET status = 'APPROVED', error_log = NULL WHERE id = ?`,
    targetId
  );
  
  console.log(`Enqueuing YouTube PUBLISH job for Job #${jobId}, Target #${targetId}...`);
  await addJobToQueue(jobId, 'PUBLISH', 0, 'youtube', targetId);
  
  console.log('🎉 Successfully enqueued YouTube upload job!');
}

main()
  .catch(err => console.error('Error:', err))
  .finally(async () => {
    await prisma.$disconnect();
    process.exit(0);
  });
