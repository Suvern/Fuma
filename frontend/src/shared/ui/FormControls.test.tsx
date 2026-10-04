// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { Select, DateInput, TextArea } from "./FormControls";
afterEach(cleanup);

it("Semi select preserves empty/default FormData values and an exact accessible label", async () => {
  const { container } = render(
    <form>
      <div>
        <Select label="存储" name="storage" defaultValue="default">
          <option value="default">系统默认</option>
          <option value="">本机私有</option>
          <option value="cloud">私有云</option>
        </Select>
      </div>
    </form>,
  );
  const form = container.querySelector("form")!;
  expect(container.querySelector("select")).toBeNull();
  expect(new FormData(form).get("storage")).toBe("default");
  fireEvent.click(screen.getByText("存储"));
  expect(document.activeElement).not.toBe(
    container.querySelector(".form-control-proxy"),
  );
  fireEvent.click(screen.getByRole("combobox", { name: "存储" }));
  fireEvent.click(await screen.findByRole("option", { name: /本机私有/ }));
  expect(new FormData(form).get("storage")).toBe("");
  expect(form.checkValidity()).toBe(true);
});

it("unavailable or disabled selections block submission instead of becoming a valid empty option", async () => {
  const view = (value: string) => (
    <form>
      <Select label="存储" name="storage" value={value}>
        <option value="">本机私有</option>
        <option value="old" disabled>
          停用云位置
        </option>
      </Select>
    </form>
  );
  const { container, rerender } = render(view("missing"));
  const form = container.querySelector("form")!;
  expect(screen.getByRole("alert").textContent).toContain("原选项不可用");
  await act(async () => expect(form.checkValidity()).toBe(false));
  expect(
    screen.getByRole("combobox", { name: "存储" }).textContent,
  ).not.toContain("本机私有");
  rerender(view("old"));
  await act(async () => expect(form.checkValidity()).toBe(false));
  rerender(view(""));
  expect(form.checkValidity()).toBe(true);
});

it("required fields show a visible error and ancestor fieldsets disable and omit values", async () => {
  const view = (disabled: boolean) => (
    <fieldset disabled={disabled}>
      <form>
        <Select label="目标" name="target" required>
          <option value="">请选择</option>
          <option value="cloud">私有云</option>
        </Select>
        <TextArea name="notes" defaultValue="说明" />
      </form>
    </fieldset>
  );
  const { container, rerender } = render(view(false));
  const form = container.querySelector("form")!;
  await act(async () => expect(form.checkValidity()).toBe(false));
  expect(screen.getByRole("alert").textContent).toContain("请选择此项");
  rerender(view(true));
  await waitFor(() =>
    expect(
      screen
        .getByRole("combobox", { name: "目标" })
        .getAttribute("aria-disabled"),
    ).toBe("true"),
  );
  expect(Array.from(new FormData(form).entries())).toEqual([]);
});

it("date and textarea adapters preserve native submission without shifting the local day", async () => {
  const { container } = render(
    <form>
      <DateInput label="开始日期" name="date" defaultValue="2026-10-04" />
      <DateInput
        label="时间"
        type="datetime-local"
        name="time"
        defaultValue="2026-10-04T09:30"
      />
      <TextArea name="notes" defaultValue="发布说明" required />
    </form>,
  );
  const values = Object.fromEntries(
    new FormData(container.querySelector("form")!),
  );
  expect(values).toEqual({
    date: "2026-10-04",
    time: "2026-10-04T09:30",
    notes: "发布说明",
  });
  expect(screen.getByRole("textbox", { name: "开始日期" })).toBeTruthy();
  fireEvent.change(screen.getByRole("textbox", { name: "开始日期" }), {
    target: { value: "2026-10-05" },
  });
  fireEvent.blur(screen.getByRole("textbox", { name: "开始日期" }));
  await waitFor(() =>
    expect(new FormData(container.querySelector("form")!).get("date")).toBe(
      "2026-10-05",
    ),
  );
  await act(async () => container.querySelector("form")!.reset());
  expect(new FormData(container.querySelector("form")!).get("date")).toBe(
    "2026-10-04",
  );
});

it("out-of-range and invalid optional dates cannot silently submit an empty replacement", async () => {
  const view = (value: string) => (
    <form>
      <DateInput label="日期" name="date" value={value} min="2026-10-04" />
    </form>
  );
  const { container, rerender } = render(view("2026-10-03"));
  await act(async () =>
    expect(container.querySelector("form")!.checkValidity()).toBe(false),
  );
  expect(screen.getByRole("alert").textContent).toContain("日期范围");
  rerender(view("invalid"));
  await act(async () =>
    expect(container.querySelector("form")!.checkValidity()).toBe(false),
  );
  rerender(view("2026-10-05"));
  expect(container.querySelector("form")!.checkValidity()).toBe(true);
});
