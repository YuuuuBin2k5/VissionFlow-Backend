export type ConfirmationAction =
  | 'approve_publish'
  | 'force_publish'
  | 'reschedule_video'
  | 'pause_campaign'
  | 'resume_campaign'
  | 'cancel_job'
  | 'cancel_campaign'
  | 'remix_music'
  | 'cal_delete'
  | 'approve_youtube_publish'
  | 'approve_youtube_publish_all'
  | 'approve_tiktok_publish_all';

export interface PendingConfirmation {
  id: string;
  chatId: number | string;
  action: ConfirmationAction;
  summary: string;
  payload: Record<string, any>;
  createdAt: Date;
  expiresAt: Date;
}

const pendingConfirmations = new Map<string, PendingConfirmation>();
const DEFAULT_TTL_MS = 5 * 60 * 1000;

export function createConfirmation(
  chatId: number | string,
  action: ConfirmationAction,
  summary: string,
  payload: Record<string, any>,
  ttlMs = DEFAULT_TTL_MS,
) {
  const id = `${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
  const confirmation: PendingConfirmation = {
    id,
    chatId,
    action,
    summary,
    payload,
    createdAt: new Date(),
    expiresAt: new Date(Date.now() + ttlMs),
  };

  pendingConfirmations.set(id, confirmation);
  return confirmation;
}

export function consumeConfirmation(id: string) {
  const confirmation = pendingConfirmations.get(id);
  pendingConfirmations.delete(id);

  if (!confirmation) return null;
  if (confirmation.expiresAt.getTime() < Date.now()) return null;

  return confirmation;
}

export function cancelConfirmation(id: string) {
  return pendingConfirmations.delete(id);
}

export function getLatestPendingConfirmation(chatId: number | string): PendingConfirmation | null {
  let latest: PendingConfirmation | null = null;
  const now = Date.now();
  for (const conf of pendingConfirmations.values()) {
    if (String(conf.chatId) === String(chatId) && conf.expiresAt.getTime() > now) {
      if (!latest || conf.createdAt.getTime() > latest.createdAt.getTime()) {
        latest = conf;
      }
    }
  }
  return latest;
}

