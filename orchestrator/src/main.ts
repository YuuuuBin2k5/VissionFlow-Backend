import express from 'express';
import dotenv from 'dotenv';
import { bot } from './telegram/bot';
import { youtubeBot } from './telegram/youtubeBot';
import { youtubeSecondBot } from './telegram/youtubeSecondBot';
import prisma from './database/db';
import { ensurePublishTargetsTable } from './database/publishTargetRepo';
import { ensureUserConnectionTables } from './database/userConnectionRepo';
import { ensureVideoJobLanguageColumns } from './database/videoJobSchema';
import { handleYouTubeOAuthCallback } from './services/youtubeOAuthService';
import './queue/worker'; // Khởi chạy BullMQ Worker
import { startAutoScheduler } from './scheduler/scheduler';

dotenv.config();

const app = express();
const port = process.env.PORT || 3000;

app.use(express.json());

// Health check endpoint
app.get('/health', async (req, res) => {
  try {
    // Kiểm tra kết nối DB
    await prisma.$queryRaw`SELECT 1`;
    res.json({ status: 'OK', database: 'CONNECTED', service: 'TIKTOK_ORCHESTRATOR' });
  } catch (error: any) {
    res.status(500).json({ status: 'ERROR', database: 'DISCONNECTED', message: error.message });
  }
});

app.get('/oauth2callback', async (req, res) => {
  try {
    const code = String(req.query.code || '');
    const state = String(req.query.state || '');
    if (!code || !state) {
      res.status(400).send('Missing OAuth code or state.');
      return;
    }

    await handleYouTubeOAuthCallback(code, state);
    res.send('Kết nối YouTube thành công. Bạn có thể quay lại Telegram bot.');
  } catch (error: any) {
    console.error('[OAuth] YouTube callback failed:', error);
    res.status(400).send(`Kết nối YouTube thất bại: ${error.message}`);
  }
});

// Hàm khởi chạy hệ thống
async function startServer() {
  try {
    await ensurePublishTargetsTable();
    await ensureUserConnectionTables();
    await ensureVideoJobLanguageColumns();

    // 1. Khởi động Web Server
    app.listen(port, () => {
      console.log(`[Orchestrator] Web server is running on http://localhost:${port}`);
    });

    // 2. Khởi động Telegram Bot
    if (process.env.TELEGRAM_BOT_TOKEN && process.env.TELEGRAM_BOT_TOKEN !== 'YOUR_TELEGRAM_BOT_TOKEN_HERE') {
      console.log('[Orchestrator] Starting Telegram Bot polling...');
      await bot.telegram.setMyCommands([
        { command: 'start', description: 'Bắt đầu và mở hướng dẫn nhanh' },
        { command: 'help', description: 'Xem quy trình sử dụng bot' },
        { command: 'menu', description: 'Mở bảng điều khiển chính' },
        { command: 'create', description: 'Tạo video mới bằng wizard' },
        { command: 'schedule', description: 'Xem lịch đăng hôm nay hoặc tuần' },
        { command: 'pending', description: 'Xem video chờ duyệt' },
        { command: 'status', description: 'Xem worker và hàng đợi' },
        { command: 'templates', description: 'Xem mẫu chủ đề và định dạng' },
        { command: 'cancel', description: 'Hủy thao tác hiện tại' },
      ]);
      bot.launch({ dropPendingUpdates: true });
      console.log('[Orchestrator] Telegram Bot is online and listening! 🚀');
    } else {
      console.warn('[Orchestrator] WARNING: Telegram Bot Token not set correctly. Skipping bot startup.');
    }

    if (process.env.YOUTUBE_TELEGRAM_BOT_TOKEN && process.env.YOUTUBE_TELEGRAM_BOT_TOKEN !== 'YOUR_YOUTUBE_TELEGRAM_BOT_TOKEN_HERE') {
      console.log('[Orchestrator] Starting YouTube Telegram Bot polling...');
      youtubeBot.launch({ dropPendingUpdates: true });
      console.log('[Orchestrator] YouTube Telegram Bot is online and listening! ▶️');
    } else {
      console.warn('[Orchestrator] YouTube bot token not set. Skipping YouTube bot startup.');
    }

    if (process.env.YOUTUBE_SECOND_TELEGRAM_BOT_TOKEN && process.env.YOUTUBE_SECOND_TELEGRAM_BOT_TOKEN !== 'YOUR_YOUTUBE_SECOND_TELEGRAM_BOT_TOKEN_HERE') {
      console.log('[Orchestrator] Starting YouTube Second Telegram Bot polling...');
      youtubeSecondBot.launch({ dropPendingUpdates: true });
      console.log('[Orchestrator] YouTube Second Telegram Bot is online and listening! 🚀');
    } else {
      console.warn('[Orchestrator] YouTube second bot token not set. Skipping YouTube second bot startup.');
    }

    // 3. Khởi động Bộ lập lịch tự động
    startAutoScheduler();

  } catch (error) {
    console.error('[Orchestrator] Failed to start server:', error);
    process.exit(1);
  }
}

// Xử lý dừng tiến trình an toàn
process.once('SIGINT', () => {
  bot.stop('SIGINT');
  youtubeBot.stop('SIGINT');
  youtubeSecondBot.stop('SIGINT');
  prisma.$disconnect();
  process.exit(0);
});

process.once('SIGTERM', () => {
  bot.stop('SIGTERM');
  youtubeBot.stop('SIGTERM');
  youtubeSecondBot.stop('SIGTERM');
  prisma.$disconnect();
  process.exit(0);
});

startServer();
// Touched to trigger nodemon restart and reload env with encryption key
