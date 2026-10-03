import Modal from "@douyinfe/semi-ui-19/lib/es/modal";
import type { ReactNode } from "react";

export function Dialog({
  open,
  onClose,
  title,
  children,
  busy = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  busy?: boolean;
}) {
  if (!open) return null;
  return (
    <Modal
      visible={open}
      title={title}
      onCancel={onClose}
      footer={null}
      width={560}
      style={{ maxWidth: "calc(100vw - 32px)" }}
      closeOnEsc={!busy}
      maskClosable={!busy}
      closable={!busy}
      keepDOM={false}
    >
      {open && children}
    </Modal>
  );
}
