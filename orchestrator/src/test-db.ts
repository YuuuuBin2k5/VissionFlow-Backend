import prisma from './database/db';

async function main() {
  console.log('--- INSPECTING JOB #1 ---');
  const job = await prisma.videoPipelineJobs.findUnique({
    where: { id: 1 }
  });
  if (job) {
    console.log(JSON.stringify(job, null, 2));
  } else {
    console.log('Job #1 not found.');
  }
}

main()
  .catch(console.error)
  .finally(() => prisma.$disconnect());
