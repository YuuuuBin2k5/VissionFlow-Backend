import { executeConfirmedAction } from './telegram/botActions';

async function main() {
  console.log('--- TESTING NEW REMIX_MUSIC ENGINE (CREATE SEPARATE JOB) ---');
  try {
    const result = await executeConfirmedAction('remix_music', {
      jobId: 31,
      rightsConfirmed: true,
    });
    console.log('Result:', result);
  } catch (error) {
    console.error('Failed to trigger remix:', error);
  }
}

main().then(() => process.exit(0));
