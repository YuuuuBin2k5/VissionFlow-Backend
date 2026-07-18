import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

async function main() {
  console.log("=== PUBLISH TARGETS DEBUG ===");
  const targets = await prisma.$queryRawUnsafe(
    `SELECT * FROM publish_targets WHERE job_id IN (126, 127) ORDER BY id DESC`
  );
  console.log(JSON.stringify(targets, null, 2));

  console.log("\n=== REALTIME LOGS FOR JOB 126 & 127 ===");
  const logs = await prisma.processRealtimeLogs.findMany({
    where: { job_id: { in: [126, 127] } },
    orderBy: { logged_at: 'desc' },
    take: 30,
  });
  for (const log of logs) {
    console.log(`Job #${log.job_id} | ${log.logged_at.toISOString()} | ${log.execution_step} | ${log.status_level} | ${log.log_message}`);
  }
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
