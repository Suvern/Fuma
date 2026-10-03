import Modal from "@douyinfe/semi-ui-19/lib/es/modal";

/** Keep destructive actions explicit and use the same dialog language as the app. */
export function confirmAction(content: string): Promise<boolean> {
  return new Promise((resolve) => {
    Modal.confirm({
      title: "确认操作",
      content,
      okText: "确认继续",
      cancelText: "取消",
      onOk: () => resolve(true),
      onCancel: () => resolve(false),
    });
  });
}
