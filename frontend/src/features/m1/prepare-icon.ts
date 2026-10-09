const MAX_ICON_BYTES = 64 * 1024;
const MAX_SOURCE_BYTES = 10 * 1024 * 1024;

function dataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("无法读取图片，请重新选择。"));
    reader.readAsDataURL(blob);
  });
}

/** Keep the API's 64 KiB limit while accepting ordinary exported app icons. */
export async function prepareAppIcon(file: File): Promise<string> {
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type))
    throw new Error("请选择 PNG、JPEG 或 WebP 图片。");
  if (file.size > MAX_SOURCE_BYTES)
    throw new Error("图片超过 10 MiB，请选择更小的图片。");

  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    throw new Error("无法识别这张图片，请重新导出为 PNG、JPEG 或 WebP。");
  }
  try {
    if (file.size <= MAX_ICON_BYTES) return await dataUrl(file);
    const canvas = document.createElement("canvas");
    for (const edge of [256, 128, 64]) {
      const scale = Math.min(1, edge / Math.max(bitmap.width, bitmap.height));
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      const context = canvas.getContext("2d");
      if (!context) throw new Error("浏览器无法处理图片，请选择小于 64 KiB 的图标。");
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, "image/webp", 0.9),
      );
      // Browsers without a WebP encoder fall back to PNG, preserving transparency.
      if (blob && blob.size <= MAX_ICON_BYTES) return await dataUrl(blob);
    }
    throw new Error("图片压缩失败，请换一张图片或选择小于 64 KiB 的图标。");
  } finally {
    bitmap.close();
  }
}
