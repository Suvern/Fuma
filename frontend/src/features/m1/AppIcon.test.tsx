// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { AppIconField } from "./AppIcon";
import { prepareAppIcon } from "./prepare-icon";

vi.mock("./prepare-icon", () => ({ prepareAppIcon: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("图标异步选择", () => {
  it("处理完成前阻止保存，完成后提交压缩数据", async () => {
    let finish!: (value: string) => void;
    vi.mocked(prepareAppIcon).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const changed = vi.fn();
    render(<form><AppIconField value="" onChange={changed} /></form>);
    const field = screen.getByLabelText("应用图标（选填）") as HTMLInputElement;
    fireEvent.change(field, { target: { files: [new File(["large"], "icon.png", { type: "image/png" })] } });
    expect(field.validity.customError).toBe(true);
    expect(screen.getByRole("status").textContent).toContain("正在处理");
    await act(async () => finish("data:image/webp;base64,aW1hZ2U="));
    expect(field.validity.valid).toBe(true);
    expect(changed).toHaveBeenCalledWith("data:image/webp;base64,aW1hZ2U=");
  });

  it("移除后忽略迟到的压缩结果", async () => {
    let finish!: (value: string) => void;
    vi.mocked(prepareAppIcon).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const changed = vi.fn();
    render(<AppIconField value="" onChange={changed} />);
    const field = screen.getByLabelText("应用图标（选填）") as HTMLInputElement;
    fireEvent.change(field, { target: { files: [new File(["image"], "icon.png")] } });
    fireEvent.click(screen.getByRole("button", { name: "移除图标" }));
    await act(async () => finish("stale-result"));
    expect(changed.mock.calls).toEqual([[""]]);
    expect(field.validity.valid).toBe(true);
  });
});
