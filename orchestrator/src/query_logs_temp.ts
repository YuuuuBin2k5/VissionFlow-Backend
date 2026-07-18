import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

async function main() {
  console.log("=== REALTIME LOGS FOR JOB #116 ===");
  const logs = await prisma.processRealtimeLogs.findMany({
    where: { job_id: 116 },
    orderBy: { logged_at: 'asc' },
  });
  
  for (const log of logs) {
    console.log(`[${log.logged_at.toISOString()}] [${log.execution_step}] [${log.status_level}] ${log.log_message}`);
  }
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
