# Telegram Bot Layer

Folder này chứa lớp giao tiếp Telegram của AgentBot. Bot handler đóng vai trò thin controller: nhận command/callback/message, kiểm tra trạng thái phiên, gọi intent/action/service phù hợp và trả phản hồi ngắn gọn cho người dùng.

## Module Map

- `bot.ts`: TikTok bot chính.
- `youtubeBot.ts`: YouTube bot chính.
- `youtubeSecondBot.ts`: YouTube bot cho kênh phụ.
- `botUxCatalog.ts`: catalog chung cho command menu, `/start`, `/help`, fallback, active-session lock message và keyboard chính.
- `intentRouter.ts`: phân tích chat tự nhiên thành intent có cấu trúc.
- `botActions.ts`: action/report nghiệp vụ dùng chung cho bot.

## Content Hub

Menu chính chỉ mở lối vào gọn. Các capability tạo nội dung đầy đủ phải nằm trong Content Hub (`buildContentHubMessage`, `tiktokContentKeyboard`, `youtubeContentKeyboard`):

- Chiến dịch video: `camp_wizard:start`, `yt:camp_wizard:start`, `/startcampaign`.
- Video đơn/Short/video dài: chat tự nhiên hoặc `yt:create_short`, `yt:create_video`.
- Split-screen/format trend: dùng nút Split-screen trong Content Hub hoặc chat tự nhiên có từ khóa split-screen/triết lý/đời sống.
- Music video/audio-reactive: `/music_video`, `/create_music_video`, `/render_music`, `/remix_music`.
- Dịch & lồng tiếng: `/translate_dub`, `content:translate_dub`, `yt:content_translate_dub`.
- Phân tích viral TikTok: `/analyze_viral`.

## Code Rules

- `/start`, `/help`, menu chính, fallback và lock message phải dùng builder trong `botUxCatalog.ts`.
- Nút `Tạo nội dung` phải mở Content Hub, không trỏ thẳng vào một luồng hẹp làm mất các lựa chọn khác.
- Handler không viết business logic dài; nếu cần xử lý nghiệp vụ, đưa vào `botActions.ts` hoặc module service đúng trách nhiệm.
- Intent router không quyết định copy UX; nó chỉ trả action có cấu trúc.
- Copy phải ngắn, tập trung vào việc người dùng có thể làm tiếp: tạo video, xem lịch, xem video chờ duyệt, quản lý tài khoản.
- Các lệnh `/` chỉ hiển thị hướng dẫn tối thiểu: lệnh dùng để làm gì, cần nhập gì tiếp theo, và nút điều hướng cần thiết.
- Không đưa preset hoặc mẫu có sẵn vào `/start`, `/help`, `/menu`, dashboard chiến dịch, fallback hoặc message báo sai cú pháp.
- Command menu Telegram phải đăng ký bằng `setMyCommands` khi bot khởi tạo.

## Boilerplate Pattern

```ts
bot.command('help', async (ctx) => {
  return ctx.replyWithHTML(buildHelpMessage('tiktok'), tiktokMainKeyboard());
});

bot.on('text', async (ctx) => {
  const intent = await parseBotIntent(ctx.message.text);
  if (!intent) {
    return ctx.reply(buildUnknownIntentMessage('tiktok'), tiktokMainKeyboard());
  }
  return executeConfirmedAction(ctx, intent);
});
```

## Forbidden

- Không nhúng hướng dẫn dài hoặc nội dung marketing trực tiếp trong `bot.ts`, `youtubeBot.ts` hoặc `youtubeSecondBot.ts`.
- Không để mỗi bot tự định nghĩa danh sách lệnh khác nhau nếu cùng một capability.
- Không gọi Prisma/queue/worker từ `botUxCatalog.ts`.
- Không đổi schema intent hoặc logic render/publish khi chỉ sửa UX chatbot.
- Không dùng fallback kiểu trách lỗi hoặc quá dài; chỉ hướng người dùng sang lựa chọn tiếp theo.
