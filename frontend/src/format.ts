import type { AudioDownloadState, IngestionStatus, YouTubeAuthMode } from "./api";

export function formatDateTime(value: string | null): string {
  if (value === null) {
    return "n/a";
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) {
    return "n/a";
  }

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remaining = Math.floor(seconds % 60);

  if (hours > 0) {
    return `${hours}h ${minutes}m ${remaining}s`;
  }

  if (minutes > 0) {
    return `${minutes}m ${remaining}s`;
  }

  return `${remaining}s`;
}

export function formatCompactNumber(value: number): string {
  return new Intl.NumberFormat(undefined, {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

export function formatStatusLabel(status: string): string {
  return status.replace(/_/g, " ");
}

export function statusTone(status: IngestionStatus | string): string {
  switch (status) {
    case "completed":
    case "ready":
      return "success";
    case "in_progress":
    case "downloading":
    case "transcribing":
    case "extracting":
    case "embedding":
      return "warning";
    case "failed":
      return "danger";
    default:
      return "neutral";
  }
}

export function formatYouTubeAuthMode(mode: YouTubeAuthMode): string {
  return mode.replace(/_/g, " ");
}

export function youtubeAuthTone(mode: YouTubeAuthMode | null | undefined): string {
  switch (mode) {
    case "managed_cookie":
      return "success";
    default:
      return "neutral";
  }
}

export function formatAudioDownloadState(state: AudioDownloadState): string {
  return state.replace(/_/g, " ");
}

export function audioDownloadTone(state: AudioDownloadState): string {
  switch (state) {
    case "completed":
      return "success";
    case "failed":
      return "danger";
    case "downloading":
    case "uploading":
      return "warning";
    default:
      return "neutral";
  }
}

export function formatBytes(value: number | null | undefined): string {
  if (value == null) {
    return "n/a";
  }

  if (value < 1024) {
    return `${value} B`;
  }

  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }

  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatElapsed(value: number): string {
  if (value < 1000) {
    return `${value} ms`;
  }

  return `${(value / 1000).toFixed(1)} s`;
}
