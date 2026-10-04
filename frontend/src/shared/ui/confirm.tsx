import "../../app/semi";
import { useEffect, useRef, useState } from "react";
import { Dialog } from "./Dialog";
import { Button } from "./controls";

let active = false;

/** Keep confirmation in the caller's React tree, without a separate React root. */
export function useConfirmAction() {
  const [content, setContent] = useState<string | null>(null);
  const pending = useRef<((answer: boolean) => void) | null>(null);
  useEffect(() => () => pending.current?.(false), []);

  function settle(answer: boolean) {
    const resolve = pending.current;
    pending.current = null;
    setContent(null);
    resolve?.(answer);
  }

  async function confirmAction(message: string): Promise<boolean> {
    // A second caller must not execute its action with the first caller's consent.
    if (active) return false;
    active = true;
    try {
      return await new Promise<boolean>((resolve) => {
        pending.current = resolve;
        setContent(message);
      });
    } finally {
      pending.current = null;
      active = false;
    }
  }

  return {
    confirmAction,
    holder: (
      <Dialog
        open={content !== null}
        onClose={() => settle(false)}
        title="确认操作"
        motion={false}
      >
        <p>{content}</p>
        <div className="form-actions">
          <Button type="button" onClick={() => settle(false)}>
            取消
          </Button>
          <Button type="button" className="primary" onClick={() => settle(true)}>
            确认继续
          </Button>
        </div>
      </Dialog>
    ),
  };
}
