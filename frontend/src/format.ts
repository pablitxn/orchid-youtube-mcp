import type { IngestionStatus } from "./api";

export function formatDateTime(value: string | null): string {
  if (value === null) {
    return "n/a";
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatDuration(seconds: number): string {
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
