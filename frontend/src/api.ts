export type IngestionStatus =
  | "pending"
  | "in_progress"
  | "completed"
  | "failed";

export type ProcessingState =
  | "pending"
  | "downloading"
  | "transcribing"
  | "extracting"
  | "embedding"
  | "ready"
  | "failed";

export type Modality = "transcript" | "frame" | "audio" | "video";

export interface OverviewResponse {
  total_videos: number;
  videos_by_status: Record<string, number>;
  videos_by_processing_state: Record<string, number>;
  total_chunks: number;
  chunks_by_modality: Record<string, number>;
  latest_ingestion_at: string | null;
}

export interface PaginationInfo {
  page?: number;
  page_size?: number;
  offset?: number;
  limit?: number;
  total_items: number;
  total_pages?: number;
}

export interface VideoSummary {
  id: string;
  youtube_id: string;
  title: string;
  duration_seconds: number;
  status: IngestionStatus;
  chunk_counts: Record<string, number>;
  created_at: string;
}

export interface VideoListResponse {
  videos: VideoSummary[];
  pagination: PaginationInfo;
}

export interface AdminArtifact {
  type: string;
  label: string;
  bucket: string | null;
  path: string | null;
  url: string | null;
  content: string | null;
}

export interface AdminVideoDetail {
  id: string;
  youtube_id: string;
  youtube_url: string;
  title: string;
  description: string;
  duration_seconds: number;
  duration_display: string;
  status: IngestionStatus;
  processing_state: ProcessingState;
  chunk_counts: Record<string, number>;
  total_chunks: number;
  created_at: string;
  updated_at: string;
  upload_date: string;
  channel_name: string;
  channel_id: string;
  thumbnail_url: string;
  language: string | null;
  error_message: string | null;
  artifacts: AdminArtifact[];
}

export interface ChunkItem {
  id: string;
  modality: Modality;
  start_time: number;
  end_time: number;
  duration_seconds: number;
  timestamp: string;
  youtube_url: string;
  preview: string;
  created_at: string;
  metadata: Record<string, string | number | boolean | null>;
  artifacts: AdminArtifact[];
}

export interface AdminChunksResponse {
  video_id: string;
  modality: Modality | null;
  chunk_counts: Record<string, number>;
  pagination: PaginationInfo;
  chunks: ChunkItem[];
}

export interface TimestampRange {
  start_time: number;
  end_time: number;
  display: string;
}

export interface Citation {
  id: string;
  modality: Modality;
  timestamp_range: TimestampRange;
  content_preview: string;
  relevance_score: number;
  youtube_url: string | null;
  source_url?: string | null;
}

export interface QueryMetadata {
  video_id: string;
  video_title: string;
  modalities_searched: Modality[];
  chunks_analyzed: number;
  processing_time_ms: number;
  multimodal_content_used: string[];
}

export interface QueryResponse {
  answer: string;
  reasoning: string | null;
  confidence: number;
  citations: Citation[];
  query_metadata: QueryMetadata;
}

export interface SourceArtifact {
  type: string;
  url: string | null;
  content: string | null;
}

export interface SourceDetail {
  citation_id: string;
  modality: Modality;
  timestamp_range: TimestampRange;
  artifacts: Record<string, SourceArtifact>;
}

export interface SourcesResponse {
  sources: SourceDetail[];
  expires_at: string;
}

export interface IngestRequest {
  youtube_url: string;
  extract_frames: boolean;
  extract_audio_chunks: boolean;
  extract_video_chunks: boolean;
  language_hint: string | null;
  max_resolution: number;
}

export interface IngestResponse {
  video_id: string;
  youtube_id: string;
  title: string;
  duration_seconds: number;
  status: IngestionStatus;
  message: string;
}

export interface QueryVideoRequest {
  query: string;
  modalities: Modality[];
  max_citations: number;
  include_reasoning: boolean;
}

export interface AgentChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface AgentToolTrace {
  tool_name: string;
  mcp_tool_name: string;
  arguments: Record<string, unknown>;
  result_preview: string;
}

export interface AgentChatResponse {
  reply: string;
  response_id: string | null;
  tool_traces: AgentToolTrace[];
}

export type YouTubeAuthMode = "managed_cookie" | "none";
export type AudioDownloadPreset =
  | "mp3_128"
  | "mp3_192"
  | "m4a_128"
  | "opus_160";

export interface YouTubeAuthStatus {
  mode: YouTubeAuthMode;
  encryption_configured: boolean;
  has_managed_cookie: boolean;
  source_label: string | null;
  updated_at: string | null;
  runtime_file_present: boolean;
  cookie_line_count: number;
  domain_count: number;
  contains_youtube_domains: boolean;
  has_login_cookie_names: boolean;
}

export interface YouTubeDownloadTestRequest {
  youtube_url: string;
}

export interface YouTubeDownloadTestResult {
  youtube_url: string;
  youtube_id: string;
  title: string;
  channel_name: string;
  duration_seconds: number;
  auth_mode: YouTubeAuthMode;
  downloaded_bytes: number;
  artifact_name: string;
  elapsed_ms: number;
  note: string;
}

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)
  ?.replace(/\/$/, "") ?? "";

async function getErrorMessage(response: Response): Promise<string> {
  let message = `Request failed with status ${response.status}`;
  try {
    const errorPayload = (await response.json()) as {
      message?: string;
      detail?: string;
      error?: {
        message?: string;
        detail?: string;
      };
    };
    message =
      errorPayload.error?.message ||
      errorPayload.error?.detail ||
      errorPayload.message ||
      errorPayload.detail ||
      message;
  } catch {
    // Ignore JSON parsing issues for non-JSON error responses.
  }
  return message;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
    ...init,
  });

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  return (await response.json()) as T;
}

function extractFilename(contentDisposition: string | null): string | null {
  if (contentDisposition === null) {
    return null;
  }

  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    return decodeURIComponent(utf8Match[1]);
  }

  const quotedMatch = contentDisposition.match(/filename="([^"]+)"/i);
  if (quotedMatch?.[1]) {
    return quotedMatch[1];
  }

  const plainMatch = contentDisposition.match(/filename=([^;]+)/i);
  return plainMatch?.[1]?.trim() ?? null;
}

export async function getAdminOverview(): Promise<OverviewResponse> {
  return request<OverviewResponse>("/v1/admin/overview");
}

export async function listVideos(): Promise<VideoListResponse> {
  return request<VideoListResponse>("/v1/videos?page=1&page_size=100");
}

export async function getAdminVideoDetail(
  videoId: string,
): Promise<AdminVideoDetail> {
  return request<AdminVideoDetail>(`/v1/admin/videos/${videoId}`);
}

export async function getVideoChunks(
  videoId: string,
  modality: Modality | "all",
): Promise<AdminChunksResponse> {
  const params = new URLSearchParams({ limit: "220" });
  if (modality !== "all") {
    params.set("modality", modality);
  }
  return request<AdminChunksResponse>(
    `/v1/admin/videos/${videoId}/chunks?${params.toString()}`,
  );
}

export async function ingestVideo(
  payload: IngestRequest,
): Promise<IngestResponse> {
  return request<IngestResponse>("/v1/videos/ingest", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function queryVideo(
  videoId: string,
  payload: QueryVideoRequest,
): Promise<QueryResponse> {
  return request<QueryResponse>(`/v1/videos/${videoId}/query`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getSources(
  videoId: string,
  citationIds: string[],
): Promise<SourcesResponse> {
  const params = new URLSearchParams();
  for (const citationId of citationIds) {
    params.append("citation_ids", citationId);
  }
  for (const artifactType of [
    "transcript_text",
    "thumbnail",
    "frame_image",
    "audio_clip",
    "video_clip",
  ]) {
    params.append("include_artifacts", artifactType);
  }
  return request<SourcesResponse>(
    `/v1/videos/${videoId}/sources?${params.toString()}`,
  );
}

export async function deleteVideo(videoId: string): Promise<void> {
  await request(`/v1/videos/${videoId}`, {
    method: "DELETE",
    headers: {
      "X-Confirm-Delete": "true",
    },
  });
}

export async function chatWithVideoAgent(
  videoId: string,
  messages: AgentChatMessage[],
): Promise<AgentChatResponse> {
  return request<AgentChatResponse>(`/v1/agent/videos/${videoId}/chat`, {
    method: "POST",
    body: JSON.stringify({ messages }),
  });
}

export async function getYouTubeAuthStatus(): Promise<YouTubeAuthStatus> {
  return request<YouTubeAuthStatus>("/v1/admin/youtube-auth");
}

export async function saveYouTubeCookie(payload: {
  cookie_text: string;
  source_label: string | null;
}): Promise<YouTubeAuthStatus> {
  return request<YouTubeAuthStatus>("/v1/admin/youtube-auth/cookie", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function clearYouTubeCookie(): Promise<YouTubeAuthStatus> {
  return request<YouTubeAuthStatus>("/v1/admin/youtube-auth/cookie", {
    method: "DELETE",
  });
}

export async function runYouTubeDownloadTest(
  payload: YouTubeDownloadTestRequest,
): Promise<YouTubeDownloadTestResult> {
  return request<YouTubeDownloadTestResult>("/v1/admin/youtube-auth/download-test", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function downloadYouTubeAudio(payload: {
  youtube_url: string;
  preset: AudioDownloadPreset;
}): Promise<{
  filename: string | null;
  authMode: YouTubeAuthMode | null;
}> {
  const response = await fetch(`${API_BASE}/v1/admin/youtube-auth/download-audio`, {
    method: "POST",
    headers: {
      Accept: "audio/*,application/octet-stream",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const filename = extractFilename(response.headers.get("Content-Disposition"));
  const anchor = document.createElement("a");

  anchor.href = objectUrl;
  anchor.download = filename ?? `youtube-audio.${payload.preset.split("_")[0]}`;
  anchor.style.display = "none";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);

  return {
    filename,
    authMode: response.headers.get("X-YouTube-Auth-Mode") as YouTubeAuthMode | null,
  };
}
