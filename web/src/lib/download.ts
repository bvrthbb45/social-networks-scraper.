import { blobUrl } from "../api/client";

/** Present only inside the Android shell, which cannot save "blob:" downloads by itself. */
interface AndroidBridge { saveFile(base64: string, name: string, mime: string): void }

export function androidBridge(): AndroidBridge | null {
  const bridge = (window as unknown as { OpsecAndroid?: AndroidBridge }).OpsecAndroid;
  return bridge && typeof bridge.saveFile === "function" ? bridge : null;
}

function toBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

/** Fetch an authenticated file and hand it to the browser (or the Android shell) as a download. */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const url = await blobUrl(path);
  try {
    const bridge = androidBridge();
    if (bridge) {
      const blob = await (await fetch(url)).blob();
      bridge.saveFile(await toBase64(blob), filename, blob.type);
      return;
    }
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  }
}
