// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { prepareAppIcon } from "./prepare-icon";

const bitmap = { width: 1024, height: 512, close: vi.fn() };
beforeEach(() => {
  vi.stubGlobal("createImageBitmap", vi.fn().mockResolvedValue(bitmap));
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  bitmap.close.mockClear();
});

describe("图标准备", () => {
  it("保留小图原始数据，并释放解码资源", async () => {
    const result = await prepareAppIcon(new File(["image"], "icon.png", { type: "image/png" }));
    expect(result).toBe("data:image/png;base64,aW1hZ2U=");
    expect(bitmap.close).toHaveBeenCalledOnce();
  });

  it("超过 64 KiB 的图片按比例压缩，首次仍超限时继续缩小", async () => {
    const drawImage = vi.fn();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage } as never);
    const sizes: number[][] = [];
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(function (this: HTMLCanvasElement, callback) {
      sizes.push([this.width, this.height]);
      callback(new Blob([new Uint8Array(sizes.length === 1 ? 70000 : 1000)], { type: "image/webp" }));
    });
    const result = await prepareAppIcon(new File([new Uint8Array(80000)], "icon.png", { type: "image/png" }));
    expect(sizes).toEqual([[256, 128], [128, 64]]);
    expect(atob(result.split(",")[1] ?? "").length).toBeLessThanOrEqual(65536);
    expect(result.startsWith("data:image/webp;base64,")).toBe(true);
    expect(bitmap.close).toHaveBeenCalledOnce();
  });

  it("浏览器不支持 WebP 编码时接受 PNG 回退", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage: vi.fn() } as never);
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((callback) => callback(new Blob(["png"], { type: "image/png" })));
    expect(await prepareAppIcon(new File([new Uint8Array(80000)], "icon.jpg", { type: "image/jpeg" }))).toMatch(/^data:image\/png;base64,/);
  });

  it("拒绝损坏图片以及超过源文件上限的图片", async () => {
    vi.mocked(createImageBitmap).mockRejectedValue(new Error("decode failed"));
    await expect(prepareAppIcon(new File(["broken"], "icon.png", { type: "image/png" }))).rejects.toThrow("无法识别");
    await expect(prepareAppIcon(new File([new Uint8Array(10 * 1024 * 1024 + 1)], "large.png", { type: "image/png" }))).rejects.toThrow("10 MiB");
    expect(createImageBitmap).toHaveBeenCalledTimes(1);
  });
});
