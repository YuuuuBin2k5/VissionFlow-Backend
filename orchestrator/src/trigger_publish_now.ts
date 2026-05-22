import { addJobToQueue } from './queue/queue';

async function main() {
  const jobId = process.argv[2] ? parseInt(process.argv[2], 10) : 31;
  console.log(`--- ENQUEUING PUBLISH NOW FOR JOB ${jobId} ---`);
  await addJobToQueue(jobId, 'PUBLISH', 0);
  console.log('Successfully enqueued publish job with 0 delay!');
}

main().then(() => process.exit(0));
