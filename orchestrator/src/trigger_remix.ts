import { executeConfirmedAction } from './telegram/botActions';

async function main() {
  console.log('--- TRIGGERING REMIX MUSIC FOR JOB 31 ---');
  try {
    const result = await executeConfirmedAction('remix_music', {
      jobId: 31,
      rightsConfirmed: true,
    });
    console.log('Result:', result);
    console.log('Successfully triggered! Check worker logs now.');
  } catch (error) {
    console.error('Failed to trigger remix:', error);
  }
}

main().then(() => process.exit(0));
