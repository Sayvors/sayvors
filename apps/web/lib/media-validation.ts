// lib/media-validation.ts
//
// Client-side validation for media that is ultimately published to Google.
// Mirrors the server limits in app/modules/media/service.py and the Google
// constraints in google_publish.py so a bad file is rejected before it leaves
// the browser, with a message that says what to fix.

export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
export const MAX_GOOGLE_PHOTO_BYTES = 5 * 1024 * 1024;
export const MIN_GOOGLE_EDGE = 250;

export type MediaKind = "image" | "video";
export type PublishMethod = "post" | "gallery" | "profile" | "banner";

export interface FieldIssue {
  field: "file" | "url" | "schedule" | "caption" | "method" | "category";
  level: "error" | "warning";
  message: string;
}

const IMAGE_EXT: Record<string, string> = {
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
  webp: "image/webp",
  gif: "image/gif",
};

const VIDEO_EXT: Record<string, string> = {
  mp4: "video/mp4",
  mov: "video/quicktime",
};

export const ALLOWED_IMAGE_EXT = Object.keys(IMAGE_EXT);
export const ALLOWED_VIDEO_EXT = Object.keys(VIDEO_EXT);

export function fileExtension(name: string): string {
  const i = (name || "").lastIndexOf(".");
  return i >= 0 ? (name.slice(i + 1) || "").toLowerCase() : "";
}

export function kindOfFile(file: File | null): MediaKind | null {
  if (!file) return null;
  const ext = fileExtension(file.name);
  if (ext in IMAGE_EXT) return "image";
  if (ext in VIDEO_EXT) return "video";
  if (file.type.startsWith("image/")) return "image";
  if (file.type.startsWith("video/")) return "video";
  return null;
}

export function validateMediaFile(
  file: File | null,
  method: PublishMethod,
): FieldIssue[] {
  const issues: FieldIssue[] = [];
  if (!file) {
    issues.push({ field: "file", level: "error", message: "Choose a file to upload." });
    return issues;
  }
  if (file.size <= 0) {
    issues.push({ field: "file", level: "error", message: "That file is empty." });
    return issues;
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    issues.push({
      field: "file",
      level: "error",
      message: `That file is too large — maximum ${MAX_UPLOAD_BYTES / 1024 / 1024}MB.`,
    });
  }
  const kind = kindOfFile(file);
  if (!kind) {
    issues.push({ field: "file", level: "error", message: "Only JPG, PNG, WEBP, GIF, MP4 or MOV files." });
    return issues;
  }
  if (kind === "video" && method !== "post") {
    issues.push({
      field: "method",
      level: "error",
      message: "Videos can only be published as a Google post — profile, gallery and banner are photos.",
    });
  }
  if (kind === "image" && method !== "post" && file.size > MAX_GOOGLE_PHOTO_BYTES) {
    issues.push({
      field: "file",
      level: "error",
      message: `Google accepts photos up to ${MAX_GOOGLE_PHOTO_BYTES / 1024 / 1024}MB for this surface — yours is ${(file.size / 1024 / 1024).toFixed(1)}MB.`,
    });
  }
  return issues;
}

export interface ImageDimensions {
  width: number;
  height: number;
}

export function validateImageDimensions(
  dims: ImageDimensions,
  method: PublishMethod,
): FieldIssue[] {
  const issues: FieldIssue[] = [];
  if (dims.width < MIN_GOOGLE_EDGE || dims.height < MIN_GOOGLE_EDGE) {
    issues.push({
      field: "file",
      level: "error",
      message: `Image is too small — ${dims.width}×${dims.height}px, minimum ${MIN_GOOGLE_EDGE}×${MIN_GOOGLE_EDGE}px.`,
    });
    return issues;
  }
  const ratio = dims.width / dims.height;
  if (method === "profile") {
    if (Math.abs(ratio - 1) > 0.1) {
      issues.push({
        field: "file",
        level: "warning",
        message: "Profile pictures are displayed as a circle — a square photo crops cleanest.",
      });
    }
    if (dims.width < 720) {
      issues.push({
        field: "file",
        level: "warning",
        message: "Google recommends at least 720×720px for a profile picture.",
      });
    }
  }
  if (method === "banner") {
    if (dims.width < 480 || dims.height < 270) {
      issues.push({
        field: "file",
        level: "error",
        message: `Cover photos need at least 480×270px — yours is ${dims.width}×${dims.height}px.`,
      });
    }
    if (Math.abs(ratio - 16 / 9) > 0.2) {
      issues.push({
        field: "file",
        level: "warning",
        message: "Cover photos look best at 16:9 (1024×576px). Google will crop the rest.",
      });
    }
    if (dims.width < 1024) {
      issues.push({
        field: "file",
        level: "warning",
        message: "Google recommends 1024×576px for a cover photo.",
      });
    }
  }
  if (method === "gallery") {
    if (dims.width < 720 || dims.height < 720) {
      issues.push({
        field: "file",
        level: "warning",
        message: "Google recommends at least 720×720px for gallery photos.",
      });
    }
  }
  return issues;
}

export function wallTimeToInstant(value: string): Date | null {
  const v = (value || "").trim();
  if (!v) return null;
  // Treat the input as Riyadh wall time (UTC+3, no DST) — that is the zone
  // Google's schedule is interpreted in.
  let iso = v;
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(iso)) iso += ":00";
  if (!/([+-]\d{2}:\d{2}|Z)$/.test(iso)) iso += "+03:00";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function validateSchedule(value: string, now: Date = new Date()): FieldIssue[] {
  const issues: FieldIssue[] = [];
  if (!value.trim()) return issues;
  const at = wallTimeToInstant(value);
  if (!at) {
    issues.push({ field: "schedule", level: "error", message: "That doesn't look like a valid date and time." });
    return issues;
  }
  if (at.getTime() <= now.getTime() + 60_000) {
    issues.push({ field: "schedule", level: "error", message: "Choose a time at least a minute from now." });
  }
  return issues;
}

export function validateMediaUrl(raw: string): FieldIssue[] {
  const issues: FieldIssue[] = [];
  const value = (raw || "").trim();
  if (!value) {
    issues.push({ field: "url", level: "error", message: "Paste a public http(s) link." });
    return issues;
  }
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    issues.push({ field: "url", level: "error", message: "That doesn't look like a URL." });
    return issues;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    issues.push({ field: "url", level: "error", message: "Only http or https links." });
    return issues;
  }
  if (parsed.protocol === "http:") {
    issues.push({ field: "url", level: "warning", message: "Use https — Google and some networks refuse plain http." });
  }
  if (!parsed.hostname) {
    issues.push({ field: "url", level: "error", message: "That URL has no host." });
  }
  return issues;
}

export function mediaKindFromUrl(url: string): MediaKind {
  return /\.(mp4|webm|mov|m4v)(\?|$)/i.test(url) ? "video" : "image";
}

export function inspectImageFile(file: File): Promise<ImageDimensions> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve({ width: img.naturalWidth, height: img.naturalHeight });
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Could not read that image."));
    };
    img.src = url;
  });
}

export function probeImageUrl(url: string): Promise<ImageDimensions> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const timer = setTimeout(() => {
      img.onload = null;
      img.onerror = null;
      reject(new Error("Timed out loading the image."));
    }, 8000);
    img.onload = () => {
      clearTimeout(timer);
      if (img.naturalWidth === 0) reject(new Error("That link is not an image."));
      else resolve({ width: img.naturalWidth, height: img.naturalHeight });
    };
    img.onerror = () => {
      clearTimeout(timer);
      reject(new Error("Could not load that image — check the link and CORS."));
    };
    img.src = url;
  });
}

export function formatBytes(n: number): string {
  if (!n || n <= 0) return "";
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(n % (1024 * 1024) === 0 ? 0 : 1)}MB`;
  return `${Math.round(n / 1024)}KB`;
}

export function riyadhLabel(iso: string): string {
  try {
    return new Date(iso).toLocaleString("en-GB", { timeZone: "Asia/Riyadh", dateStyle: "medium", timeStyle: "short" });
  } catch {
    return iso;
  }
}
