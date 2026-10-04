import {
  Children,
  Fragment,
  isValidElement,
  useEffect,
  useLayoutEffect,
  useId,
  useRef,
  useState,
  type ChangeEvent,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import SemiSelect from "@douyinfe/semi-ui-19/lib/es/select";
import DatePicker from "@douyinfe/semi-ui-19/lib/es/datePicker";
import SemiTextArea from "@douyinfe/semi-ui-19/lib/es/input/textarea";
import "./FormControls.css";

type Label = { label?: string };
type Option = { value: string; label: ReactNode; disabled?: boolean };
function optionsOf(children: ReactNode): Option[] {
  return Children.toArray(children).flatMap((child) => {
    if (
      !isValidElement<{
        children?: ReactNode;
        value?: string;
        disabled?: boolean;
      }>(child)
    )
      return [];
    if (child.type === Fragment) return optionsOf(child.props.children);
    if (child.type !== "option") return [];
    return [
      {
        value: String(child.props.value ?? child.props.children ?? ""),
        label: child.props.children,
        disabled: child.props.disabled,
      },
    ];
  });
}
function change<T>(value: string) {
  return {
    target: { value },
    currentTarget: { value },
  } as unknown as ChangeEvent<T>;
}
function useFieldsetDisabled(disabled?: boolean) {
  const ref = useRef<HTMLSpanElement>(null);
  const [inherited, setInherited] = useState(false);
  useEffect(() => {
    const fields: HTMLFieldSetElement[] = [];
    let ancestor = ref.current?.parentElement;
    while (ancestor) {
      if (ancestor instanceof HTMLFieldSetElement) fields.push(ancestor);
      ancestor = ancestor.parentElement;
    }
    const update = () => setInherited(fields.some((field) => field.disabled));
    update();
    const observer = new MutationObserver(update);
    fields.forEach((field) =>
      observer.observe(field, {
        attributes: true,
        attributeFilter: ["disabled"],
      }),
    );
    return () => observer.disconnect();
  }, []);
  return { ref, disabled: Boolean(disabled || inherited) };
}

/** Native-shaped single select; label mirrors the visible field label. */
export function Select({
  children,
  value,
  defaultValue,
  onChange,
  name,
  required,
  disabled,
  label,
  id,
  ...props
}: Omit<
  SelectHTMLAttributes<HTMLSelectElement>,
  "multiple" | "size" | "onBlur" | "onFocus" | "onKeyDown"
> &
  Label) {
  const options = optionsOf(children);
  const [draft, setDraft] = useState(
    String(defaultValue ?? options[0]?.value ?? ""),
  );
  const chosen = String(value ?? draft);
  const valid = options.some(
    (option) => option.value === chosen && !option.disabled,
  );
  const needsChoice =
    chosen === "" && options.some((option) => option.value === "");
  const unavailable = !valid && !needsChoice;
  const current = valid ? chosen : "";
  const proxy = useRef<HTMLInputElement>(null);
  const [invalid, setInvalid] = useState(false);
  useLayoutEffect(() => {
    proxy.current?.setCustomValidity(valid ? "" : "原选项不可用，请重新选择。");
  }, [valid]);
  const labelId = useId();
  const { ref: fieldRef, disabled: isDisabled } = useFieldsetDisabled(disabled);
  useEffect(() => {
    const form = proxy.current?.form;
    const reset = () => {
      if (value === undefined) {
        setDraft(String(defaultValue ?? options[0]?.value ?? ""));
        setInvalid(false);
      }
    };
    form?.addEventListener("reset", reset);
    return () => form?.removeEventListener("reset", reset);
  }, [value, defaultValue, options]);
  return (
    <span className="form-control" ref={fieldRef}>
      <span className="form-control-caption" id={labelId}>
        {label ?? props["aria-label"] ?? name ?? "选择选项"}
      </span>
      <SemiSelect
        id={id}
        aria-labelledby={props["aria-labelledby"] ?? labelId}
        aria-describedby={props["aria-describedby"]}
        aria-invalid={invalid || !valid || props["aria-invalid"]}
        style={{ width: "100%", ...props.style }}
        className={props.className}
        value={valid ? current : undefined}
        placeholder={
          valid || needsChoice ? "请选择" : "原选项不可用，请重新选择"
        }
        optionList={options}
        disabled={isDisabled}
        onChange={(next) => {
          if (isDisabled || fieldRef.current?.closest("fieldset:disabled"))
            return;
          const nextValue = String(next ?? "");
          if (
            !options.some(
              (option) => option.value === nextValue && !option.disabled,
            )
          )
            return;
          setInvalid(false);
          setDraft(nextValue);
          onChange?.(change<HTMLSelectElement>(nextValue));
        }}
      />
      <input
        ref={proxy}
        className="form-control-proxy"
        aria-hidden="true"
        tabIndex={-1}
        name={name}
        value={current}
        onChange={() => {}}
        required={required}
        disabled={isDisabled}
        onInvalid={(event) => {
          event.preventDefault();
          setInvalid(true);
          fieldRef.current
            ?.querySelector<HTMLElement>('[role="combobox"]')
            ?.focus();
        }}
      />
      {(invalid || unavailable) && (
        <span role="alert" className="form-control-error">
          {unavailable ? "原选项不可用，请重新选择。" : "请选择此项后继续。"}
        </span>
      )}
    </span>
  );
}

/** Calendar selection returns a local date string, never a UTC-shifted day. */
export function DateInput({
  value,
  defaultValue,
  onChange,
  name,
  required,
  disabled,
  label,
  type = "date",
  min,
  max,
  id,
  ...props
}: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> &
  Label & { type?: "date" | "datetime-local" }) {
  const [draft, setDraft] = useState(String(defaultValue ?? ""));
  const current = String(value ?? draft);
  const labelId = useId();
  const { ref: fieldRef, disabled: isDisabled } = useFieldsetDisabled(disabled);
  const selected = current
    ? new Date(type === "date" ? `${current}T00:00:00` : current)
    : undefined;
  const proxy = useRef<HTMLInputElement>(null);
  const [invalid, setInvalid] = useState(false);
  const parsed =
    !current ||
    Boolean(
      selected &&
      Number.isFinite(selected.getTime()) &&
      selected.getFullYear() === Number(current.slice(0, 4)) &&
      selected.getMonth() + 1 === Number(current.slice(5, 7)) &&
      selected.getDate() === Number(current.slice(8, 10)),
    );
  useLayoutEffect(() => {
    proxy.current?.setCustomValidity(parsed ? "" : "请输入有效日期。");
    // Semi places these public ARIA props on a non-interactive wrapper. Associate
    // its rendered combobox and text input with the same label as well.
    const labelledBy = props["aria-labelledby"] ?? labelId;
    fieldRef.current
      ?.querySelector('[role="combobox"]')
      ?.setAttribute("aria-labelledby", labelledBy);
    const input = fieldRef.current?.querySelector<HTMLInputElement>(
      "input:not(.form-control-proxy)",
    );
    input?.setAttribute("aria-labelledby", labelledBy);
    if (id) input?.setAttribute("id", id);
  });
  useEffect(() => {
    const form = proxy.current?.form;
    const reset = () => {
      if (value === undefined) {
        setDraft(String(defaultValue ?? ""));
        setInvalid(false);
      }
    };
    form?.addEventListener("reset", reset);
    return () => form?.removeEventListener("reset", reset);
  }, [value, defaultValue]);
  return (
    <span className="form-control" ref={fieldRef}>
      <span className="form-control-caption" id={labelId}>
        {label ?? props["aria-label"] ?? name ?? "选择日期"}
      </span>
      <DatePicker
        type={type === "date" ? "date" : "dateTime"}
        format={type === "date" ? "yyyy-MM-dd" : "yyyy-MM-dd HH:mm"}
        value={
          selected && Number.isFinite(selected.getTime()) ? selected : undefined
        }
        showClear={!required}
        disabled={isDisabled}
        style={{ width: "100%" }}
        aria-labelledby={props["aria-labelledby"] ?? labelId}
        aria-describedby={props["aria-describedby"]}
        placeholder={props.placeholder}
        disabledDate={(date) =>
          Boolean(
            date &&
            ((min && date < new Date(`${String(min).slice(0, 10)}T00:00:00`)) ||
              (max && date > new Date(`${String(max).slice(0, 10)}T23:59:59`))),
          )
        }
        onChangeWithDateFirst
        inputReadOnly={props.readOnly}
        onChange={(dates) => {
          if (isDisabled || fieldRef.current?.closest("fieldset:disabled"))
            return;
          const raw = Array.isArray(dates) ? dates[0] : dates;
          const date = raw instanceof Date ? raw : undefined;
          const pad = (n: number) => String(n).padStart(2, "0");
          const next = date
            ? `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}${type === "datetime-local" ? `T${pad(date.getHours())}:${pad(date.getMinutes())}` : ""}`
            : "";
          setDraft(next);
          setInvalid(false);
          onChange?.(change<HTMLInputElement>(next));
        }}
      />
      <input
        ref={proxy}
        className="form-control-proxy"
        aria-hidden="true"
        tabIndex={-1}
        name={name}
        type={type}
        min={min}
        max={max}
        value={current}
        onChange={() => {}}
        required={required}
        disabled={isDisabled}
        onInvalid={(event) => {
          event.preventDefault();
          setInvalid(true);
          fieldRef.current
            ?.querySelector<HTMLInputElement>(".semi-input")
            ?.focus();
        }}
      />
      {(invalid || !parsed) && (
        <span role="alert" className="form-control-error">
          请输入有效日期，并满足日期范围要求。
        </span>
      )}
    </span>
  );
}

export function TextArea({
  onChange,
  onInput,
  readOnly,
  value,
  defaultValue,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <SemiTextArea
      {...props}
      {...(value !== undefined ? { value: String(value) } : {})}
      defaultValue={
        defaultValue === undefined ? undefined : String(defaultValue)
      }
      readonly={readOnly}
      onChange={(_, event) =>
        onChange?.(event as unknown as ChangeEvent<HTMLTextAreaElement>)
      }
      onInput={onInput as never}
    />
  );
}
