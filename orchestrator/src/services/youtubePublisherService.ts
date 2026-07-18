import * as fs from 'fs';

export interface YouTubeUploadInput {
  videoPath: string;
  title: string;
  description: string;
  tags: string[];
  refreshToken?: string;
  privacyStatus?: string;
  scheduledPublishTime?: Date | null;
}

export interface YouTubeUploadResult {
  videoId: string;
  url: string;
}

function requireEnv(name: string) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not configured.`);
  return value;
}

function detectMimeType(videoPath: string) {
  const lower = videoPath.toLowerCase();
  if (lower.endsWith('.mov')) return 'video/quicktime';
  if (lower.endsWith('.webm')) return 'video/webm';
  return 'video/mp4';
}

export class YouTubePublisherService {
  private async getAccessToken(refreshTokenOverride?: string) {
    const clientId = requireEnv('YOUTUBE_CLIENT_ID');
    const clientSecret = requireEnv('YOUTUBE_CLIENT_SECRET');
    const refreshToken = refreshTokenOverride || requireEnv('YOUTUBE_REFRESH_TOKEN');

    const body = new URLSearchParams({
      client_id: clientId,
      client_secret: clientSecret,
      refresh_token: refreshToken,
      grant_type: 'refresh_token',
    });

    const response = await fetch('https://oauth2.googleapis.com/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    });

    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`YouTube OAuth refresh failed (${response.status}): ${detail}`);
    }

    const data: any = await response.json();
    if (!data.access_token) throw new Error('YouTube OAuth response did not include an access token.');
    return data.access_token as string;
  }

  async uploadVideo(input: YouTubeUploadInput): Promise<YouTubeUploadResult> {
    if (!fs.existsSync(input.videoPath)) {
      throw new Error(`Video file does not exist: ${input.videoPath}`);
    }

    const accessToken = await this.getAccessToken(input.refreshToken);
    const stats = fs.statSync(input.videoPath);
    const mimeType = detectMimeType(input.videoPath);
    const publishAt = input.scheduledPublishTime && input.scheduledPublishTime.getTime() > Date.now()
      ? input.scheduledPublishTime.toISOString()
      : undefined;

    const metadata = {
      snippet: {
        title: input.title.slice(0, 100),
        description: input.description.slice(0, 5000),
        tags: input.tags.slice(0, 30),
        categoryId: '22',
      },
      status: {
        privacyStatus: publishAt ? 'private' : (input.privacyStatus || process.env.YOUTUBE_DEFAULT_PRIVACY_STATUS || 'public'),
        selfDeclaredMadeForKids: false,
        ...(publishAt ? { publishAt } : {}),
      },
    };

    const initResponse = await fetch(
      'https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status',
      {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${accessToken}`,
          'Content-Type': 'application/json; charset=UTF-8',
          'X-Upload-Content-Length': String(stats.size),
          'X-Upload-Content-Type': mimeType,
        },
        body: JSON.stringify(metadata),
      },
    );

    if (!initResponse.ok) {
      const detail = await initResponse.text();
      throw new Error(`YouTube upload session failed (${initResponse.status}): ${detail}`);
    }

    const uploadUrl = initResponse.headers.get('location');
    if (!uploadUrl) throw new Error('YouTube did not return a resumable upload URL.');

    const uploadResponse = await fetch(uploadUrl, {
      method: 'PUT',
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': mimeType,
        'Content-Length': String(stats.size),
      },
      body: fs.createReadStream(input.videoPath) as any,
      duplex: 'half',
    } as any);

    if (!uploadResponse.ok) {
      const detail = await uploadResponse.text();
      throw new Error(`YouTube video upload failed (${uploadResponse.status}): ${detail}`);
    }

    const uploaded: any = await uploadResponse.json();
    if (!uploaded.id) throw new Error('YouTube upload succeeded but no video id was returned.');

    return {
      videoId: uploaded.id,
      url: `https://www.youtube.com/watch?v=${uploaded.id}`,
    };
  }
}
