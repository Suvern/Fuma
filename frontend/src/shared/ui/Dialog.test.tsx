// @vitest-environment jsdom
import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Dialog } from "./Dialog";
import { useCommand } from "./common";
import { Button } from "./controls";

let client: QueryClient;
afterEach(() => {
  cleanup();
  client?.clear();
  vi.restoreAllMocks();
});

function Editor({
  onSaved,
  save,
}: {
  onSaved: () => void;
  save: () => Promise<void>;
}) {
  const cmd = useCommand();
  return (
    <>
      {cmd.feedback}
      <label>
        授权说明
        <input defaultValue="原授权" />
      </label>
      <Button
        type="button"
        disabled={cmd.pending}
        onClick={() =>
          void cmd.run("save", save, onSaved, "已保存", "确认保存此次授权？")
        }
      >
        保存授权
      </Button>
    </>
  );
}
function Fixture({ save }: { save: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState(0);
  return (
    <>
      <Button type="button" onClick={() => setOpen(true)}>
        打开授权编辑
      </Button>
      <output>已保存 {saved} 次</output>
      <Dialog open={open} onClose={() => setOpen(false)} title="授权编辑">
        {open && (
          <Editor
            save={save}
            onSaved={() => {
              setSaved((value) => value + 1);
              setOpen(false);
            }}
          />
        )}
      </Dialog>
    </>
  );
}

it("真实确认框保存关闭父 Dialog 后不在 React 生命周期中同步卸载 root，重新打开清空表单", async () => {
  const error = vi.spyOn(console, "error").mockImplementation(() => {});
  const save = vi.fn(async () => {});
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Fixture save={save} />
    </QueryClientProvider>,
  );
  for (let iteration = 1; iteration <= 2; iteration++) {
    fireEvent.click(screen.getByRole("button", { name: "打开授权编辑" }));
    const field = (await screen.findByLabelText("授权说明")) as HTMLInputElement;
    expect(field.value).toBe("原授权");
    fireEvent.change(field, { target: { value: "新授权草稿" } });
    fireEvent.click(screen.getByRole("button", { name: "保存授权" }));
    let confirm = await screen.findByRole("button", { name: "确认继续" });
    expect(screen.getByRole("dialog", { name: "确认操作" })).toBeTruthy();
    expect(screen.getByRole("dialog", { name: "授权编辑" })).toBeTruthy();
    expect(save).toHaveBeenCalledTimes(iteration - 1);
    if (iteration === 1) {
      fireEvent.click(screen.getByRole("button", { name: "取消" }));
      await waitFor(() => {
        expect(screen.queryByRole("button", { name: "确认继续" })).toBeNull();
        expect(
          screen.getByRole<HTMLButtonElement>("button", { name: "保存授权" })
            .disabled,
        ).toBe(false);
      });
      expect(save).not.toHaveBeenCalled();
      expect(field.value).toBe("新授权草稿");
      fireEvent.click(screen.getByRole("button", { name: "保存授权" }));
      confirm = await screen.findByRole("button", { name: "确认继续" });
    }
    fireEvent.click(confirm);
    await screen.findByText(`已保存 ${iteration} 次`);
    // jsdom does not run CSS animations. Drive the real Semi leave event instead
    // of mocking Modal or its portal lifecycle; this catches static root teardown.
    await act(async () => {
      document
        .querySelectorAll(
          ".semi-modal-wrap:has(.semi-modal-content-animate-hide), .semi-modal-mask-animate-hide",
        )
        .forEach((element) => {
          fireEvent.animationEnd(element);
          // React selects this fallback when jsdom lacks AnimationEvent.
          fireEvent(element, new Event("webkitAnimationEnd", { bubbles: true }));
        });
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(save).toHaveBeenCalledTimes(iteration);
  }
  expect(error.mock.calls).toEqual([]);
});
