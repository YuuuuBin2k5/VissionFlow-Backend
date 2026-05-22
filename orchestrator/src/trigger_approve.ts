import { executeConfirmedAction } from './telegram/botActions';

async function main() {
  const jobId = process.argv[2] ? parseInt(process.argv[2], 10) : 31;
  console.log(`--- APPROVING AND SCHEDULING PUBLISH FOR JOB ${jobId} ---`);
  try {
    const result = await executeConfirmedAction('approve_publish', {
      jobId: jobId,
    });
    console.log('Result:', result);
    console.log('Successfully approved! The job is now queued for TikTok publishing.');
  } catch (error) {
    console.error('Failed to approve job:', error);
  }
}

main().then(() => process.exit(0));
