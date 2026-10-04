import "../../app/semi";
import Modal from "@douyinfe/semi-ui-19/lib/es/modal";

let active = false;

/** Keep destructive actions explicit and use the same dialog language as the app. */
export async function confirmAction(content: string): Promise<boolean> {
  // A second caller must not execute its action with the first caller's consent.
  if (active) return false;
  active = true;
  try {
    return await new Promise<boolean>((resolve) => {
      Modal.confirm({
        title: "确认操作",
        content,
        okText: "确认继续",
        cancelText: "取消",
        okButtonProps: { "aria-label": "确认继续" },
        cancelButtonProps: { "aria-label": "取消" },
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });
  } finally {
    active = false;
  }
}
