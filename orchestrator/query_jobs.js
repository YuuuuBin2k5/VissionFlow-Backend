const { PrismaClient } = require('@prisma/client');
const prisma = new PrismaClient();

async function main() {
  console.log("=== KIỂM TRA TÁC VỤ MỚI NHẤT ===");
  const job = await prisma.videoPipelineJobs.findFirst({
    orderBy: { id: 'desc' },
  });
  
  if (!job) {
    console.log("Không có tác vụ nào trong database.");
    return;
  }

  console.log(`🔹 Job ID: #${job.id}`);
  console.log(`▪️ Tiêu đề: ${job.video_title_idea}`);
  console.log(`▪️ Trạng thái: ${job.pipeline_state}`);
  console.log(`▪️ Ngày tạo: ${job.created_at}`);
  
  console.log("\n=== NHẬT KÝ CHI TIẾT (LATEST LOGS) ===");
  const logs = await prisma.processRealtimeLogs.findMany({
    where: { job_id: job.id },
    orderBy: { logged_at: 'desc' },
    take: 5
  });
  
  for (const log of logs) {
    console.log(`- [${log.logged_at.toLocaleTimeString()}] ${log.execution_step}: ${log.log_message}`);
  }
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
