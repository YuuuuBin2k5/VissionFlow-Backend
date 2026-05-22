import prisma from './database/db';
import { tiktokQueue } from './queue/queue';

async function main() {
  console.log("=== CHECKING BULLMQ QUEUE STATUS ===");
  const waiting = await tiktokQueue.getWaiting();
  const active = await tiktokQueue.getActive();
  const delayed = await tiktokQueue.getDelayed();
  const failed = await tiktokQueue.getFailed();

  console.log(`Waiting jobs (${waiting.length}):`, waiting.map(j => `${j.id} (${j.name})`));
  console.log(`Active jobs (${active.length}):`, active.map(j => `${j.id} (${j.name})`));
  console.log(`Delayed jobs (${delayed.length}):`, delayed.map(j => `${j.id} (${j.name})`));
  console.log(`Failed jobs (${failed.length}):`, failed.map(j => `${j.id} (${j.name})`));

  console.log("\n=== DATABASE JOBS STATUS ===");
  const jobs = await prisma.videoPipelineJobs.findMany({
    orderBy: { id: 'desc' },
    take: 10
  });
  for (const job of jobs) {
    console.log(`Job #${job.id}: State=${job.pipeline_state}, CampaignId=${job.campaign_id}, ScheduledPostTime=${job.scheduled_post_time}`);
  }

  process.exit(0);
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
