import { Markup } from 'telegraf';

export type BotPlatform = 'tiktok' | 'youtube';

type StartMessageOptions = {
  platform: BotPlatform;
  userName?: string;
  connectionLabel?: string | null;
  variantLabel?: string;
};

function escapeHtml(value: string) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

const platformLabel: Record<BotPlatform, string> = {
  tiktok: 'TikTok',
  youtube: 'YouTube',
};

export const TIKTOK_BOT_COMMANDS = [
  { command: 'start', description: 'Bắt đầu' },
  { command: 'menu', description: 'Menu chính' },
  { command: 'startcampaign', description: 'Tạo chiến dịch' },
  { command: 'splitscreen', description: 'Tạo video chia màn hình' },
  { command: 'music_video', description: 'Tạo video nhạc' },
  { command: 'translate_dub', description: 'Dịch/lồng tiếng' },
  { command: 'status', description: 'Trạng thái' },
  { command: 'schedule', description: 'Lịch đăng' },
  { command: 'pending', description: 'Chờ duyệt' },
  { command: 'preview', description: 'Xem video' },
  { command: 'accounts', description: 'Tài khoản' },
  { command: 'help', description: 'Tất cả lệnh' },
  { command: 'cancel', description: 'Hủy thao tác' },
];

export const YOUTUBE_BOT_COMMANDS = [
  { command: 'start', description: 'Bắt đầu' },
  { command: 'menu', description: 'Menu chính' },
  { command: 'connect_youtube', description: 'Kết nối kênh' },
  { command: 'startcampaign', description: 'Tạo chiến dịch' },
  { command: 'splitscreen', description: 'Tạo video chia màn hình' },
  { command: 'music_video', description: 'Tạo video nhạc' },
  { command: 'translate_dub', description: 'Dịch/lồng tiếng' },
  { command: 'status', description: 'Trạng thái' },
  { command: 'schedule', description: 'Lịch đăng' },
  { command: 'pending', description: 'Chờ duyệt' },
  { command: 'preview', description: 'Xem video' },
  { command: 'approve', description: 'Duyệt đăng' },
  { command: 'accounts', description: 'Tài khoản' },
  { command: 'help', description: 'Tất cả lệnh' },
  { command: 'cancel', description: 'Hủy thao tác' },
];

export function buildStartMessage(options: StartMessageOptions) {
  const label = platformLabel[options.platform];
  const greetingName = escapeHtml(options.userName || 'Nhà sáng tạo');
  const connectionLine = options.platform === 'youtube'
    ? options.connectionLabel
      ? `Kênh: <code>${escapeHtml(options.connectionLabel)}</code>`
      : 'Kênh: <code>chưa kết nối</code>. Bấm nút kết nối để bắt đầu.'
    : 'Sẵn sàng tạo, theo dõi và duyệt video TikTok.';

  return (
    `<b>${label} AgentBot${options.variantLabel ? ` - ${escapeHtml(options.variantLabel)}` : ''}</b>\n` +
    `Xin chào <b>${greetingName}</b>. ${connectionLine}\n\n` +
    `<b>Luồng làm việc</b>\n` +
    `1. Tạo nội dung: bấm <b>Tạo nội dung</b> hoặc dùng /startcampaign\n` +
    `2. Theo dõi: /schedule, /status, /pending\n` +
    `3. Duyệt đăng: /preview &lt;job_id&gt;, ${options.platform === 'youtube' ? '/approve' : '/force_post'} &lt;job_id&gt;\n\n` +
    `<b>Lệnh cần nhớ</b>\n` +
    `• /menu - mở bảng điều khiển\n` +
    `• /help - xem lệnh\n` +
    `• /cancel - hủy thao tác hiện tại`
  );
}

export function buildHelpMessage(platform: BotPlatform) {
  const label = platformLabel[platform];
  const publishCommand = platform === 'youtube' ? '/approve &lt;job_id&gt;' : '/force_post &lt;job_id&gt;';
  const connectCommand = platform === 'youtube' ? '• /connect_youtube - kết nối kênh\n' : '• /accounts - quản lý tài khoản TikTok\n';

  return (
    `<b>Lệnh ${label}</b>\n\n` +
    `<b>Tạo nội dung</b>\n` +
    `• /startcampaign - tạo chiến dịch\n` +
    `• /splitscreen - tạo video chia màn hình\n` +
    `• /music_video - tạo video nhạc\n` +
    `• /translate_dub - dịch và lồng tiếng video\n` +
    `\n<b>Quản lý</b>\n` +
    `• /status - trạng thái\n` +
    `• /schedule - lịch đăng\n` +
    `• /pending - video chờ duyệt\n` +
    `• /logs &lt;job_id&gt; - log xử lý\n` +
    `• /reschedule &lt;job_id&gt; &lt;thời gian&gt; - dời lịch\n\n` +
    `<b>Duyệt đăng</b>\n` +
    `• /preview &lt;job_id&gt; - xem trước\n` +
    `• ${publishCommand} - duyệt đăng\n\n` +
    `<b>Tài khoản và hỗ trợ</b>\n` +
    connectCommand +
    `• /menu - menu chính\n` +
    `• /cancel - hủy thao tác`
  );
}

export function buildUnknownIntentMessage(platform: BotPlatform) {
  const label = platformLabel[platform];

  return (
    `Mình chưa hiểu yêu cầu ${label} này.\n\n` +
    `Chọn nhanh:\n` +
    `• /menu - mở menu\n` +
    `• /schedule - xem lịch\n` +
    `• /pending - video chờ duyệt`
  );
}

export function buildActiveSessionLockMessage(subtitle: string) {
  return (
    `🔒 <b>Đang xử lý tác vụ</b>\n` +
    `Tác vụ: <b>${escapeHtml(subtitle || 'đang chạy')}</b>\n\n` +
    `Để tránh xung đột hàng đợi, hãy chờ tác vụ xong hoặc bấm <b>Hủy thao tác</b>.`
  );
}

export function buildSetupMessage(isConnected: boolean, platform: BotPlatform) {
  const label = platformLabel[platform];
  return (
    `<b>Kiểm tra thiết lập ${label}</b>\n` +
    `• Kết nối: <b>${isConnected ? 'Đã sẵn sàng' : 'Chưa kết nối'}</b>\n` +
    `• Tạo video: <b>${isConnected ? 'Có thể dùng ngay' : 'Cần kết nối trước'}</b>\n\n` +
    `${isConnected ? 'Bạn có thể tạo video bằng /startcampaign hoặc nhắn yêu cầu tự nhiên.' : `Bấm nút kết nối ${label} để bắt đầu.`}`
  );
}

export function tiktokMainKeyboard() {
  return Markup.inlineKeyboard([
    [
      Markup.button.callback('Tạo nội dung', 'content:hub'),
      Markup.button.callback('Lịch', 'quick:schedule_today'),
    ],
    [
      Markup.button.callback('Chờ duyệt', 'quick:pending'),
      Markup.button.callback('Tài khoản', 'tt:accounts'),
    ],
    [
      Markup.button.callback('Trợ giúp', 'quick:help'),
      Markup.button.callback('Trạng thái', 'quick:status'),
    ],
  ]);
}

export function youtubeMainKeyboard(connectUrl?: string) {
  const connectButton = connectUrl
    ? Markup.button.url('Kết nối YouTube', connectUrl)
    : Markup.button.callback('Tài khoản', 'yt:accounts');

  return Markup.inlineKeyboard([
    [
      Markup.button.callback('Tạo nội dung', 'yt:content_hub'),
      Markup.button.callback('Lịch', 'yt:schedule_today'),
    ],
    [
      Markup.button.callback('Chờ duyệt', 'yt:pending'),
      connectButton,
    ],
    [
      Markup.button.callback('Trợ giúp', 'yt:help'),
      Markup.button.callback('Trạng thái', 'yt:status'),
    ],
  ]);
}

export function buildContentHubMessage(platform: BotPlatform) {
  const label = platformLabel[platform];
  const splitLine = platform === 'tiktok'
    ? '• Split-screen: tạo nội dung dạng chia màn hình.'
    : '• Split-screen/Short: tạo nội dung ngắn theo format chia màn hình.';

  return (
    `<b>Tạo nội dung ${label}</b>\n` +
    `Chọn đúng luồng cần tạo:\n\n` +
    `• Chiến dịch: tạo chuỗi video theo chủ đề.\n` +
    `• Video đơn: tạo một Short/video theo lịch.\n` +
    `${splitLine}\n` +
    `• Music video: tạo visual nhạc/audio-reactive.\n` +
    `• Dịch & lồng tiếng: gửi file hoặc link video nguồn.`
  );
}

export function tiktokContentKeyboard() {
  return Markup.inlineKeyboard([
    [
      Markup.button.callback('Chiến dịch', 'camp_wizard:start'),
      Markup.button.callback('Split-screen', 'quick:trend_templates'),
    ],
    [
      Markup.button.callback('Music video', 'content:music_video'),
      Markup.button.callback('Dịch & lồng tiếng', 'content:translate_dub'),
    ],
    [
      Markup.button.callback('Phân tích viral', 'content:analyze_viral'),
      Markup.button.callback('Quay lại', 'quick:menu'),
    ],
  ]);
}

export function youtubeContentKeyboard(connectUrl?: string) {
  const connectButton = connectUrl
    ? Markup.button.url('Kết nối YouTube', connectUrl)
    : Markup.button.callback('Tài khoản', 'yt:accounts');

  return Markup.inlineKeyboard([
    [
      Markup.button.callback('YouTube Short', 'yt:create_short'),
      Markup.button.callback('Video dài', 'yt:create_video'),
    ],
    [
      Markup.button.callback('Chiến dịch', 'yt:camp_wizard:start'),
      Markup.button.callback('Split-screen', 'yt:calendar:trend_templates'),
    ],
    [
      Markup.button.callback('Music video', 'yt:content_music_video'),
      Markup.button.callback('Dịch & lồng tiếng', 'yt:content_translate_dub'),
    ],
    [
      connectButton,
      Markup.button.callback('Quay lại', 'yt:menu_home'),
    ],
  ]);
}
