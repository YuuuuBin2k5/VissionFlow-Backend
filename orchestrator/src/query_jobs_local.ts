import prisma from './database/db';

async function main() {
  console.log("=== THÔNG TIN BẢN GHI ĐĂNG CHO JOB #126 ===");
  const targets = await prisma.$queryRaw<any[]>`
    SELECT * FROM publish_targets
    WHERE job_id = 126
  `;
  
  for (const t of targets) {
    console.log(`\n🔹 Target ID: #${t.id} (Platform: ${t.platform})`);
    console.log(`▪️ Status: ${t.status}`);
    console.log(`▪️ Title: "${t.title}"`);
    console.log(`▪️ Description: "${t.description ? t.description.slice(0, 300) : ''}..."`);
    console.log(`▪️ Tags: ${JSON.stringify(t.tags)}`);
  }
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
