import Modal from "@douyinfe/semi-ui-19/lib/es/modal";
import {
  cloneElement,
  isValidElement,
  type HTMLAttributes,
  type ReactNode,
} from "react";

export function Dialog({
  open,
  onClose,
  title,
  children,
  busy = false,
  motion = true,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  busy?: boolean;
  motion?: boolean;
}) {
  return (
    <Modal
      visible={open}
      title={title}
      onCancel={onClose}
      footer={null}
      width={560}
      className="workspace-dialog"
      closeIcon={<span aria-label="关闭">×</span>}
      style={{ maxWidth: "calc(100vw - 32px)" }}
      closeOnEsc={!busy}
      maskClosable={!busy}
      closable={!busy}
      keepDOM={false}
      motion={motion}
      modalRender={(node) =>
        isValidElement<HTMLAttributes<HTMLElement>>(node)
          ? cloneElement(node, {
              // Semi uses shared title/body IDs; nested dialogs need their own name.
              "aria-label": title,
              "aria-labelledby": undefined,
              "aria-describedby": undefined,
            })
          : node
      }
    >
      {open && children}
    </Modal>
  );
}
