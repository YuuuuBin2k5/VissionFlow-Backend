import 'dotenv/config';
import prisma from './database/db';
import { addJobToQueue } from './queue/queue';

async function triggerStandaloneMusicVideo() {
  console.log('=== KICH HOAT TAO VIDEO AM NHAC STANDALONE GIA LAP CHAT BOT ===');
  
  // 1. Tìm hoặc tạo Campaign giả lập
  let campaign = await prisma.channelsCampaign.findFirst({
    where: { topic: 'Chiến dịch Thử Nghiệm Standalone Music Video' }
  });
  
  if (!campaign) {
    campaign = await prisma.channelsCampaign.create({
      data: {
        telegram_chat_id: BigInt(process.env.TELEGRAM_CHAT_ID || '8453418519'), // ID thật của user
        topic: 'Chiến dịch Thử Nghiệm Standalone Music Video',
        target_audience: 'Người yêu nhạc chill',
        status: 'RUNNING',
      }
    });
    console.log(`Da tao Campaign moi ID: #${campaign.id}`);
  } else {
    console.log(`Su dung Campaign co san ID: #${campaign.id}`);
  }

  // 2. Tao metadata cho Standalone Music Video
  const metadata = {
    render_mode: 'music_reactive',
    song_title: 'Sau Lời Từ Khước',
    artist_name: 'Phan Mạnh Quỳnh',
    is_standalone_music_video: true,
  };

  // 3. Tao Job moi
  const job = await prisma.videoPipelineJobs.create({
    data: {
      campaign_id: campaign.id,
      day_number: 1,
      scheduled_post_time: new Date(),
      video_title_idea: 'Sau Lời Từ Khước - Phan Mạnh Quỳnh',
      scenes_layout_json: JSON.stringify(metadata),
      pipeline_state: 'QUEUED',
    }
  });
  console.log(`Da tao Job moi ID: #${job.id} o trang thai QUEUED`);

  // 4. Dua Job vao Queue
  await addJobToQueue(job.id, 'RENDER');
  console.log(`Da dua Job #${job.id} vao Queue RENDER thanh cong! 🚀`);
  
  process.exit(0);
}

triggerStandaloneMusicVideo().catch((error) => {
  console.error('Loi khi kich hoat standalone music video:', error);
  process.exit(1);
});
