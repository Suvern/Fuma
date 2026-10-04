import { useId, useRef, useState } from "react";
import { Button } from "../../shared/ui/controls";

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
  const generation = useRef(0);
  return (
    <div className="field">
      <label htmlFor={id}>应用图标（选填）</label>
      <input
        ref={input}
        id={id}
        type="file"
        name="icon_file"
        accept="image/png,image/jpeg,image/webp"
        disabled={disabled}
        aria-describedby={`${id}-help`}
        aria-invalid={!!error}
        onChange={(event) => {
          const field = event.currentTarget;
          const file = field.files?.[0];
          const current = ++generation.current;
          field.setCustomValidity("");
          setError("");
          if (!file) return;
          const fail = (message: string) => {
            field.setCustomValidity(message);
            setError(message);
          };
          if (
            file.size > 65536 ||
            !["image/png", "image/jpeg", "image/webp"].includes(file.type)
          ) {
            fail("请选择不超过 64 KiB 的 PNG、JPEG 或 WebP 图片。");
            return;
          }
          field.setCustomValidity("图标读取中，请稍候。");
          const reader = new FileReader();
          reader.onload = () => {
            if (current !== generation.current) return;
            field.setCustomValidity("");
            onChange(String(reader.result));
          };
          reader.onerror = () => {
            if (current === generation.current)
              fail("无法读取图片，请重新选择。");
          };
          reader.readAsDataURL(file);
        }}
      />
      <p id={`${id}-help`} className="muted">
        PNG、JPEG 或 WebP，最大 64 KiB。未设置时显示应用名称首字。
      </p>
      {error && <p role="alert">{error}</p>}
      {value && <AppIcon name="应用" value={value} />}
      {(value || error) && (
        <Button
          type="button"
          disabled={disabled}
          onClick={() => {
            generation.current++;
            onChange("");
            setError("");
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
