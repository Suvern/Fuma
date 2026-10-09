import { useEffect, useId, useRef, useState } from "react";
import { Button } from "../../shared/ui/controls";
import { prepareAppIcon } from "./prepare-icon";

export function AppIcon({ name, value }: { name: string; value?: string }) {
  const [failed, setFailed] = useState<string>();
  return value && failed !== value ? (
    <img
      className="app-monogram"
      src={value}
      alt=""
      width={48}
      height={48}
      style={{ objectFit: "cover" }}
      onError={() => setFailed(value)}
    />
  ) : (
    <div className="app-monogram" aria-hidden="true">
      {name[0]}
    </div>
  );
}

export function AppIconField({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState("");
  const [processing, setProcessing] = useState(false);
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; }, []);
  return (
    <div className="field">
      <label htmlFor={id}>应用图标（选填）</label>
      <input
        ref={input}
        id={id}
        className="file-control-input"
        tabIndex={-1}
        aria-hidden="true"
        type="file"
        name="icon_file"
        accept="image/png,image/jpeg,image/webp"
        disabled={disabled}
        aria-describedby={`${id}-help`}
        aria-invalid={!!error}
        onInvalid={(event) => {
          event.preventDefault();
          document.getElementById(`${id}-choose`)?.focus();
        }}
        onChange={async (event) => {
          const field = event.currentTarget;
          const file = field.files?.[0];
          if (!file) return;
          const current = ++generation.current;
          field.value = "";
          field.setCustomValidity("图标处理中，请稍候。");
          setError("");
          setProcessing(true);
          try {
            const result = await prepareAppIcon(file);
            if (current !== generation.current) return;
            field.setCustomValidity("");
            onChange(result);
          } catch (cause) {
            if (current !== generation.current) return;
            const message = cause instanceof Error ? cause.message : "无法处理图片，请重新选择。";
            field.setCustomValidity(message);
            setError(message);
          } finally {
            if (current === generation.current) setProcessing(false);
          }
        }}
      />
      <Button
        id={`${id}-choose`}
        type="button"
        disabled={disabled}
        aria-describedby={`${id}-help ${id}-status`}
        aria-invalid={!!error}
        aria-busy={processing}
        onClick={() => input.current?.click()}
      >
        {processing ? "正在处理图标…" : value ? "更换图标" : "选择图标"}
      </Button>
      <p id={`${id}-help`} className="muted">
        支持 PNG、JPEG、WebP，最大 10 MiB。自动缩放压缩至 64 KiB 以内。
      </p>
      <div id={`${id}-status`}>
        {processing && <p role="status">正在处理图片，完成后即可保存。</p>}
        {error && <p role="alert">{error}</p>}
      </div>
      {value && <AppIcon name="应用" value={value} />}
      {(value || error || processing) && (
        <Button
          type="button"
          disabled={disabled}
          onClick={() => {
            generation.current++;
            onChange("");
            setError("");
            setProcessing(false);
            if (input.current) {
              input.current.value = "";
              input.current.setCustomValidity("");
            }
          }}
        >
          移除图标
        </Button>
      )}
    </div>
  );
}
