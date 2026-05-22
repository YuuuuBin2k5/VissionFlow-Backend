import express from 'express';
import dotenv from 'dotenv';
import { bot } from './telegram/bot';
import { youtubeBot } from './telegram/youtubeBot';
import prisma from './database/db';
import { ensurePublishTargetsTable } from './database/publishTargetRepo';
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

// Hàm khởi chạy hệ thống
async function startServer() {
  try {
    await ensurePublishTargetsTable();

    // 1. Khởi động Web Server
    app.listen(port, () => {
      console.log(`[Orchestrator] Web server is running on http://localhost:${port}`);
    });

    // 2. Khởi động Telegram Bot
    if (process.env.TELEGRAM_BOT_TOKEN && process.env.TELEGRAM_BOT_TOKEN !== 'YOUR_TELEGRAM_BOT_TOKEN_HERE') {
      console.log('[Orchestrator] Starting Telegram Bot polling...');
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
  prisma.$disconnect();
  process.exit(0);
});

process.once('SIGTERM', () => {
  bot.stop('SIGTERM');
  youtubeBot.stop('SIGTERM');
  prisma.$disconnect();
  process.exit(0);
});

startServer();
