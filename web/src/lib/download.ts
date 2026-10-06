import { blobUrl } from "../api/client";

/** Fetch an authenticated file and hand it to the browser as a download, then release the object URL. */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const url = await blobUrl(path);
  try {
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
